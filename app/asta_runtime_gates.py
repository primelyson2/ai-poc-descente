"""Fail-closed adapter from the deployed ADB response to roadmap gate state.

This module never evaluates SQL text and never upgrades missing evidence.  It
only reduces explicit ADB evidence into the phase 4->6->7->5 state machine so
that proxy re-queries and the UI observe one deterministic terminal result.
"""

from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any

from tools.asta_vector_learning import classify_vector_learning
from tools.asta_workflow_state import reduce_workflow_events


def _comparison(payload: dict[str, Any]) -> dict[str, Any]:
    direct = payload.get("comparison")
    if isinstance(direct, dict):
        return direct
    before_after = payload.get("before_after")
    if isinstance(before_after, dict) and isinstance(before_after.get("comparison"), dict):
        return before_after["comparison"]
    result = payload.get("result")
    if isinstance(result, dict):
        return _comparison(result)
    return {}


def _error_text(payload: dict[str, Any]) -> str | None:
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error.get("code") or "") or None
    if error:
        return str(error)
    if payload.get("error_message"):
        return str(payload["error_message"])
    return None


def _gate_status(value: Any, success: str) -> str:
    status = str(value or "").upper()
    if status == success:
        return success
    if status in {"FAILED", "ERROR"}:
        return "FAILED"
    if status in {"REJECTED", "NON_EQUIVALENT", "NOT_IMPROVED"}:
        return "REJECTED"
    return "BLOCKED"


def _events(payload: dict[str, Any], comparison: dict[str, Any]) -> list[dict[str, Any]]:
    top_status = str(payload.get("status") or "").upper()
    error = _error_text(payload)
    intent_raw = comparison.get("optimizer_intent_status")
    if not intent_raw and top_status in {"FAILED", "ERROR"}:
        intent_raw = "FAILED"
    intent_status = _gate_status(intent_raw, "VERIFIED")
    events: list[dict[str, Any]] = [{
        "stage": "OPTIMIZER_INTENT",
        "status": intent_status,
        "reason_code": comparison.get("optimizer_intent_reason")
        or comparison.get("verdict_reason")
        or ("OPTIMIZER_INTENT_EVIDENCE_REQUIRED" if intent_status == "BLOCKED" else "CANDIDATE_ORACLE_ERROR"),
        "error": error,
        "evidence": {
            "producer_starts": comparison.get("producer_starts"),
            "plan_family": comparison.get("plan_family"),
        },
    }]
    if intent_status != "VERIFIED":
        return events

    equivalence_status = _gate_status(comparison.get("equivalence_status"), "VERIFIED")
    events.append({
        "stage": "FULL_RESULT_EQUIVALENCE",
        "status": equivalence_status,
        "reason_code": comparison.get("equivalence_reason")
        or comparison.get("verdict_reason")
        or "FULL_RESULT_EVIDENCE_REQUIRED",
        "evidence": {
            "result_digest_scope": comparison.get("result_digest_scope"),
            "result_digest_mode": comparison.get("result_digest_mode"),
            "equivalence_strength": comparison.get("equivalence_strength"),
        },
    })
    if equivalence_status != "VERIFIED":
        return events

    bind_raw = str(comparison.get("bind_stability_status") or "").upper()
    bind_not_applicable = bind_raw == "NOT_APPLICABLE"
    bind_status = "VERIFIED" if bind_not_applicable else _gate_status(bind_raw, "VERIFIED")
    events.append({
        "stage": "BIND_PLAN_STABILITY",
        "status": bind_status,
        "reason_code": comparison.get("bind_stability_reason") or (
            "BIND_NOT_APPLICABLE" if bind_not_applicable else "BIND_COVERAGE_INSUFFICIENT"
        ),
        "evidence": {
            "applicability": "NOT_APPLICABLE" if bind_not_applicable else "APPLICABLE",
            "bind_case_count": comparison.get("bind_case_count"),
            "successful_bind_count": comparison.get("successful_bind_count"),
            "observed_plan_families": comparison.get("observed_plan_families"),
        },
    })
    if bind_status != "VERIFIED":
        return events

    measurement_status = _gate_status(comparison.get("measurement_status"), "ACCEPTED")
    events.append({
        "stage": "EXECUTION_MEASUREMENT",
        "status": measurement_status,
        "reason_code": comparison.get("measurement_reason") or comparison.get("verdict_reason") or "MEASUREMENT_EVIDENCE_INCOMPLETE",
        "evidence": {
            "median_elapsed_us": comparison.get("after_median_elapsed_us") or comparison.get("after_elapsed_time_us"),
            "buffer_reduction_pct": comparison.get("buffer_gets_reduction_pct"),
            "noise_pct": comparison.get("noise_pct"),
            "budget_status": comparison.get("budget_status"),
            "measurement_count": comparison.get("measurement_count"),
        },
    })
    if measurement_status != "ACCEPTED":
        return events
    final_status = "ACCEPTED" if str(comparison.get("verdict") or "").upper() == "IMPROVED" else "REJECTED"
    events.append({
        "stage": "FINAL_DECISION",
        "status": final_status,
        "reason_code": "ALL_GATES_VERIFIED" if final_status == "ACCEPTED" else str(comparison.get("verdict_reason") or "FINAL_DECISION_REJECTED"),
    })
    return events


def apply_runtime_gates(payload: dict[str, Any]) -> dict[str, Any]:
    """Attach deterministic workflow/vector decisions without exposing SQL/binds."""
    out = deepcopy(payload)
    comparison = _comparison(out)
    attempt_id = str(out.get("run_id") or (out.get("result") or {}).get("run_id") or "asta-runtime")
    snapshot = reduce_workflow_events(_events(out, comparison), attempt_id=attempt_id)
    fingerprint = hashlib.sha256(attempt_id.encode("utf-8")).hexdigest()
    vector = classify_vector_learning(snapshot, {
        "case_fingerprint": fingerprint,
        "workload": comparison.get("workload_type"),
        "strategy_id": comparison.get("strategy_id"),
        "buffer_reduction_pct": comparison.get("buffer_gets_reduction_pct"),
        "median_elapsed_us": comparison.get("after_median_elapsed_us") or comparison.get("after_elapsed_time_us"),
        "noise_pct": comparison.get("noise_pct"),
        "bind_case_count": comparison.get("bind_case_count"),
        "successful_bind_count": comparison.get("successful_bind_count"),
    })
    out["workflow_state"] = snapshot
    out["vector_learning"] = vector
    if snapshot["terminal"] and snapshot["overall_status"] != "ACCEPTED":
        out["status"] = snapshot["overall_status"]
    return out
