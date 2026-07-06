#!/usr/bin/env python3
"""ASTA 단계 4~8 gate를 하나의 결정론적 fail-closed 상태머신으로 통합한다."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any


STAGE_ORDER = [
    "OPTIMIZER_INTENT",
    "FULL_RESULT_EQUIVALENCE",
    "BIND_PLAN_STABILITY",
    "EXECUTION_MEASUREMENT",
    "FINAL_DECISION",
]

TERMINAL_STATUS = {
    "BLOCKED": "BLOCKED",
    "REJECTED": "REJECTED",
    "FAILED": "FAILED",
    "ERROR": "FAILED",
}

ALLOWED_EVIDENCE = {
    "producer_starts", "result_digest_scope", "result_digest_mode",
    "bind_case_count", "successful_bind_count", "failed_bind_case_id",
    "observed_plan_families", "median_elapsed_us", "buffer_reduction_pct",
    "noise_pct", "budget_status", "workload", "plan_family", "target_starts",
    "measurement_count", "equivalence_strength", "evidence_level",
    "applicability",
}


def _safe_text(value: Any, limit: int = 2000) -> str | None:
    if value is None:
        return None
    text = str(value)
    text = re.sub(r"'(?:''|[^'])*'", "'?'", text)
    text = re.sub(r"(:[A-Za-z][A-Za-z0-9_$#]*)\s*=\s*[^,\s)]+", r"\1=?", text)
    text = re.sub(
        r"\b(?:SELECT|WITH|INSERT|UPDATE|DELETE|MERGE)\b[\s\S]*$",
        "[SQL_TEXT_REDACTED]", text, flags=re.IGNORECASE,
    )
    return text[:limit]


def _safe_evidence(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    safe: dict[str, Any] = {}
    for key in sorted(ALLOWED_EVIDENCE.intersection(value)):
        item = value[key]
        if isinstance(item, (str, int, float, bool)) or item is None:
            safe[key] = _safe_text(item) if isinstance(item, str) else item
        elif isinstance(item, list):
            safe[key] = [_safe_text(entry, 200) for entry in item[:20]]
    return safe


def _snapshot(
    attempt_id: str,
    stages: list[dict[str, Any]],
    overall_status: str,
    reason_code: str,
    current_stage: str | None,
    terminal: bool,
    original_error: str | None = None,
) -> dict[str, Any]:
    verified = {item["stage"] for item in stages if item["status"] in {"VERIFIED", "ACCEPTED"}}
    if "EXECUTION_MEASUREMENT" in verified:
        evidence_level = "FULL_RESULT_REPRESENTATIVE_BINDS_REPEATED"
    elif "BIND_PLAN_STABILITY" in verified:
        evidence_level = "FULL_RESULT_REPRESENTATIVE_BINDS"
    elif "FULL_RESULT_EQUIVALENCE" in verified:
        evidence_level = "FULL_RESULT"
    elif "OPTIMIZER_INTENT" in verified:
        evidence_level = "OPTIMIZER_INTENT"
    else:
        evidence_level = "NONE"
    return {
        "contract_version": "asta.workflow.v1",
        "attempt_id": attempt_id,
        "overall_status": overall_status,
        "reason_code": reason_code,
        "current_stage": current_stage,
        "terminal": terminal,
        "evidence_level": evidence_level,
        "stages": stages,
        "original_error": _safe_text(original_error),
    }


def reduce_workflow_events(
    events: list[dict[str, Any]],
    *,
    attempt_id: str,
    previous: dict[str, Any] | None = None,
    restart_authorized: bool = False,
) -> dict[str, Any]:
    """이벤트를 순서대로 축약하며 terminal 결과와 재조회 일관성을 보존한다."""
    if previous and previous.get("terminal") is True:
        previous_attempt = str(previous.get("attempt_id") or "")
        if previous_attempt == attempt_id:
            return deepcopy(previous)
        if not restart_authorized:
            return _snapshot(
                attempt_id, [], "BLOCKED", "RESTART_NOT_AUTHORIZED", None, True,
            )
    stages: list[dict[str, Any]] = []
    expected_index = 0
    for event in events:
        stage = str(event.get("stage") or "").upper()
        status = str(event.get("status") or "").upper()
        reason = str(event.get("reason_code") or "STATE_EVIDENCE_INCOMPLETE").upper()
        if stage not in STAGE_ORDER:
            return _snapshot(
                attempt_id, stages, "BLOCKED", "UNKNOWN_WORKFLOW_STAGE", stage or None, True,
                event.get("error"),
            )
        stage_index = STAGE_ORDER.index(stage)
        if stage_index != expected_index:
            return _snapshot(
                attempt_id, stages, "BLOCKED", "STATE_TRANSITION_OUT_OF_ORDER", stage, True,
                event.get("error"),
            )
        if status not in {"VERIFIED", "ACCEPTED", *TERMINAL_STATUS.keys()}:
            return _snapshot(
                attempt_id, stages, "BLOCKED", "STATE_EVIDENCE_INCOMPLETE", stage, True,
                event.get("error"),
            )
        item = {
            "sequence": len(stages) + 1,
            "stage": stage,
            "status": status,
            "reason_code": reason,
            "evidence": _safe_evidence(event.get("evidence")),
        }
        error = _safe_text(event.get("error"))
        if error:
            item["error"] = error
        stages.append(item)
        if status in TERMINAL_STATUS:
            return _snapshot(
                attempt_id, stages, TERMINAL_STATUS[status], reason, stage, True, error,
            )
        required_success = "ACCEPTED" if stage in {"EXECUTION_MEASUREMENT", "FINAL_DECISION"} else "VERIFIED"
        if status != required_success:
            return _snapshot(
                attempt_id, stages, "BLOCKED", "INVALID_GATE_SUCCESS_STATUS", stage, True, error,
            )
        expected_index += 1
    if expected_index == len(STAGE_ORDER):
        return _snapshot(
            attempt_id, stages, "ACCEPTED", stages[-1]["reason_code"], STAGE_ORDER[-1], True,
        )
    current = STAGE_ORDER[expected_index] if expected_index < len(STAGE_ORDER) else STAGE_ORDER[-1]
    return _snapshot(attempt_id, stages, "RUNNING", "NEXT_GATE_PENDING", current, False)
