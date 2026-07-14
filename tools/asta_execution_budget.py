#!/usr/bin/env python3
"""ASTA 단계 5 반복 측정 schedule, 실행예산과 fail-closed 판정을 제공한다.

외부 DB/프로세스를 실행하지 않으며 이미 수집된 event record만 결정론적으로 평가한다.
"""

from __future__ import annotations

import statistics
from copy import deepcopy
from typing import Any


def resolve_execution_policy(config: dict[str, Any], workload: str) -> dict[str, Any]:
    """공통 예산에 workload별 override를 적용하되 입력 config를 변경하지 않는다."""
    resolved = deepcopy(config.get("defaults") or {})
    overrides = (config.get("workloads") or {}).get(str(workload).upper()) or {}
    resolved.update(deepcopy(overrides))
    return resolved


def _rotate(values: list[str], offset: int) -> list[str]:
    if not values:
        return []
    normalized = offset % len(values)
    return values[normalized:] + values[:normalized]


def build_execution_schedule(
    candidate_ids: list[str], policy: dict[str, Any], rotation: int = 0,
) -> dict[str, Any]:
    """Before와 후보의 warm-up/measurement 순서를 round별로 회전한다."""
    candidates = list(candidate_ids)
    max_candidates = int(policy.get("max_candidates", 0))
    if not candidates or len(candidates) > max_candidates:
        return {
            "status": "BLOCKED",
            "reason_code": "CANDIDATE_BUDGET_EXCEEDED" if candidates else "NO_CANDIDATES",
            "events": [],
            "warmup_event_count": 0,
            "measurement_event_count": 0,
            "total_planned_runs": 0,
        }
    warmups = int(policy.get("warmup_runs_per_target", 0))
    measurements = int(policy.get("measurement_runs_per_target", 0))
    runs_per_target = warmups + measurements
    total_planned = (len(candidates) + 1) * runs_per_target
    preflight_reason = None
    if total_planned > int(policy.get("max_total_runs", 0)):
        preflight_reason = "TOTAL_RUN_BUDGET_EXCEEDED"
    elif runs_per_target > int(policy.get("max_candidate_runs", 0)):
        preflight_reason = "CANDIDATE_RUN_BUDGET_EXCEEDED"
    if preflight_reason:
        return {
            "status": "BLOCKED",
            "reason_code": preflight_reason,
            "events": [],
            "warmup_event_count": 0,
            "measurement_event_count": 0,
            "total_planned_runs": total_planned,
        }
    events: list[dict[str, Any]] = []

    def append_event(phase: str, target_id: str, round_no: int) -> None:
        events.append({
            "sequence": len(events) + 1,
            "phase": phase,
            "side": "BEFORE" if target_id == "BEFORE" else "AFTER",
            "target_id": target_id,
            "round": round_no,
        })

    for warmup_round in range(warmups):
        append_event("WARMUP", "BEFORE", warmup_round + 1)
        for candidate_id in _rotate(candidates, rotation + warmup_round):
            append_event("WARMUP", candidate_id, warmup_round + 1)
    for measurement_round in range(measurements):
        append_event("MEASURE", "BEFORE", measurement_round + 1)
        for candidate_id in _rotate(candidates, rotation + measurement_round):
            append_event("MEASURE", candidate_id, measurement_round + 1)
    warmup_count = sum(event["phase"] == "WARMUP" for event in events)
    measurement_count = len(events) - warmup_count
    return {
        "status": "PLANNED",
        "reason_code": None,
        "events": events,
        "warmup_event_count": warmup_count,
        "measurement_event_count": measurement_count,
        "total_planned_runs": len(events),
    }


def _median(runs: list[dict[str, Any]], field: str) -> int | float | None:
    values = [run.get(field) for run in runs if isinstance(run.get(field), (int, float))]
    if len(values) != len(runs) or not values:
        return None
    result = float(statistics.median(values))
    return int(result) if result.is_integer() else round(result, 3)


def _noise(runs: list[dict[str, Any]], field: str) -> float | None:
    values = [float(run[field]) for run in runs if isinstance(run.get(field), (int, float))]
    if len(values) != len(runs) or len(values) < 2:
        return None
    middle = statistics.median(values)
    if middle <= 0:
        return None
    return round((max(values) - min(values)) * 100.0 / middle, 3)


def summarize_measurements(runs: list[dict[str, Any]], policy: dict[str, Any]) -> dict[str, Any]:
    """Warm-up을 제외한 완료 measurement record만 중앙값/noise evidence로 집계한다."""
    records = deepcopy(runs)
    warmups = [run for run in records if str(run.get("phase") or "").upper() == "WARMUP"]
    measured = [run for run in records if str(run.get("phase") or "").upper() == "MEASURE"]
    completed = [run for run in measured if str(run.get("status") or "").upper() == "COMPLETED"]
    expected = int(policy.get("measurement_runs_per_target", 0))
    median_elapsed = _median(completed, "last_elapsed_time_us")
    median_buffers = _median(completed, "last_cr_buffer_gets")
    elapsed_noise = _noise(completed, "last_elapsed_time_us")
    expected_warmups = int(policy.get("warmup_runs_per_target", 0))
    completed_warmups = [run for run in warmups if str(run.get("status") or "").upper() == "COMPLETED"]
    complete = (
        len(warmups) == expected_warmups
        and len(completed_warmups) == expected_warmups
        and len(measured) == expected
        and len(completed) == expected
    )
    metrics_complete = median_elapsed is not None and median_buffers is not None and elapsed_noise is not None
    status = "COMPLETE" if complete and metrics_complete else "INCOMPLETE"
    reason_code = None if status == "COMPLETE" else "MEASUREMENT_INCOMPLETE"
    return {
        "status": status,
        "reason_code": reason_code,
        "warmup_count": len(warmups),
        "completed_warmup_count": len(completed_warmups),
        "measurement_count": len(measured),
        "completed_measurement_count": len(completed),
        "expected_measurement_count": expected,
        "median_elapsed_us": median_elapsed,
        "median_buffer_gets": median_buffers,
        "elapsed_noise_pct": elapsed_noise,
        "measurement_runs": completed,
    }


def _initial_state(state: dict[str, Any] | None) -> dict[str, Any]:
    value = deepcopy(state) if state is not None else {}
    value.setdefault("used_total_runs", 0)
    value.setdefault("used_total_wall_time_ms", 0)
    value.setdefault("candidates", {})
    value.setdefault("terminal_candidates", {})
    return value


def check_execution_budget(
    candidate_id: str,
    before_runs: list[dict[str, Any]],
    after_runs: list[dict[str, Any]],
    policy: dict[str, Any],
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """수집된 실행 record를 전체/후보별 run·wall-time budget에 원자적으로 반영한다."""
    ledger = _initial_state(state)
    terminal_reason = ledger["terminal_candidates"].get(candidate_id)
    if terminal_reason:
        return {
            "status": "BLOCKED",
            "reason_code": "CANDIDATE_TERMINAL_FAILURE",
            "terminal_reason": terminal_reason,
            "usage": None,
            "remaining": None,
            "state": ledger,
            "additional_runs_allowed": False,
        }
    all_runs = [*deepcopy(before_runs), *deepcopy(after_runs)]
    wall_values = [run.get("elapsed_wall_ms") for run in all_runs]
    if any(not isinstance(value, (int, float)) or value < 0 for value in wall_values):
        ledger["terminal_candidates"][candidate_id] = "BUDGET_EVIDENCE_INCOMPLETE"
        return {
            "status": "BLOCKED",
            "reason_code": "BUDGET_EVIDENCE_INCOMPLETE",
            "usage": None,
            "remaining": None,
            "state": ledger,
            "additional_runs_allowed": False,
        }
    current_total_runs = len(all_runs)
    current_total_time = int(sum(wall_values))
    candidate_runs = len(after_runs)
    candidate_time = int(sum(run["elapsed_wall_ms"] for run in after_runs))
    ledger["used_total_runs"] += current_total_runs
    ledger["used_total_wall_time_ms"] += current_total_time
    previous_candidate = ledger["candidates"].get(candidate_id) or {"used_runs": 0, "used_wall_time_ms": 0}
    candidate_usage = {
        "used_runs": previous_candidate["used_runs"] + candidate_runs,
        "used_wall_time_ms": previous_candidate["used_wall_time_ms"] + candidate_time,
    }
    ledger["candidates"][candidate_id] = candidate_usage
    usage = {
        "total_runs": ledger["used_total_runs"],
        "total_wall_time_ms": ledger["used_total_wall_time_ms"],
        "candidate_runs": candidate_usage["used_runs"],
        "candidate_wall_time_ms": candidate_usage["used_wall_time_ms"],
    }
    reason_code = None
    if usage["total_runs"] > int(policy.get("max_total_runs", 0)):
        reason_code = "TOTAL_RUN_BUDGET_EXCEEDED"
    elif usage["total_wall_time_ms"] > int(policy.get("max_total_wall_time_ms", 0)):
        reason_code = "TOTAL_TIME_BUDGET_EXCEEDED"
    elif usage["candidate_runs"] > int(policy.get("max_candidate_runs", 0)):
        reason_code = "CANDIDATE_RUN_BUDGET_EXCEEDED"
    elif usage["candidate_wall_time_ms"] > int(policy.get("max_candidate_wall_time_ms", 0)):
        reason_code = "CANDIDATE_TIME_BUDGET_EXCEEDED"
    if reason_code:
        ledger["terminal_candidates"][candidate_id] = reason_code
    remaining = {
        "total_runs": max(0, int(policy.get("max_total_runs", 0)) - usage["total_runs"]),
        "total_wall_time_ms": max(
            0, int(policy.get("max_total_wall_time_ms", 0)) - usage["total_wall_time_ms"]
        ),
        "candidate_runs": max(0, int(policy.get("max_candidate_runs", 0)) - usage["candidate_runs"]),
        "candidate_wall_time_ms": max(
            0, int(policy.get("max_candidate_wall_time_ms", 0)) - usage["candidate_wall_time_ms"]
        ),
    }
    return {
        "status": "BLOCKED" if reason_code else "WITHIN_BUDGET",
        "reason_code": reason_code,
        "usage": usage,
        "remaining": remaining,
        "state": ledger,
        "additional_runs_allowed": reason_code is None and remaining["candidate_runs"] > 0,
    }


def _terminalize(state: dict[str, Any], candidate_id: str, reason_code: str) -> dict[str, Any]:
    value = _initial_state(state)
    value["terminal_candidates"][candidate_id] = reason_code
    return value


def _blocked_campaign(
    candidate_id: str,
    reason_code: str,
    state: dict[str, Any],
    processed_run_count: int,
    *,
    budget: dict[str, Any] | None = None,
    before_summary: dict[str, Any] | None = None,
    after_summary: dict[str, Any] | None = None,
    cancel_requested: bool = False,
    runaway_check: bool = False,
    optimizer_verdict: str | None = None,
    equivalence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "status": "BLOCKED",
        "reason_code": reason_code,
        "candidate_id": candidate_id,
        "optimizer_intent_verdict": optimizer_verdict,
        "equivalence_status": equivalence.get("status") if equivalence else None,
        "equivalence_verdict": equivalence.get("reason_code") if equivalence else None,
        "equivalence_evidence": equivalence.get("evidence") if equivalence else None,
        "processed_run_count": processed_run_count,
        "budget": budget,
        "before_summary": before_summary,
        "after_summary": after_summary,
        "candidate_evaluation_allowed": False,
        "digest_evaluated": False,
        "performance_evaluated": False,
        "semantic_equivalent": False,
        "cancel_requested": cancel_requested,
        "runaway_session_check_required": runaway_check,
        "additional_runs_allowed": False,
        "state": state,
    }


def evaluate_measurement_campaign(
    candidate_id: str,
    optimizer_intent: dict[str, Any],
    before_runs: list[dict[str, Any]],
    after_runs: list[dict[str, Any]],
    workload: str,
    policy: dict[str, Any],
    state: dict[str, Any] | None = None,
    equivalence_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Optimizer intent→전체 결과 동등성→측정 budget/성능 순으로 fail-closed 판정한다."""
    ledger = _initial_state(state)
    intent_verdict = str(optimizer_intent.get("verdict_reason") or "INSUFFICIENT_PLAN_EVIDENCE")
    if optimizer_intent.get("status") != "VERIFIED" or optimizer_intent.get("allow_downstream_evaluation") is not True:
        return _blocked_campaign(
            candidate_id, "OPTIMIZER_INTENT_NOT_VERIFIED", ledger, 0,
            optimizer_verdict=intent_verdict,
        )
    if candidate_id in ledger["terminal_candidates"]:
        return _blocked_campaign(
            candidate_id, "CANDIDATE_TERMINAL_FAILURE", ledger, 0,
            optimizer_verdict=intent_verdict,
        )

    from tools.asta_result_equivalence import verify_result_equivalence

    equivalence_payload = equivalence_evidence or {}
    equivalence = verify_result_equivalence(
        str(equivalence_payload.get("sql_text") or ""),
        list(equivalence_payload.get("before_runs") or []),
        list(equivalence_payload.get("after_runs") or []),
    )
    if equivalence.get("status") != "VERIFIED" or equivalence.get("allow_performance_measurement") is not True:
        reason = str(equivalence.get("reason_code") or "RESULT_EVIDENCE_INCOMPLETE")
        terminal_state = _terminalize(ledger, candidate_id, reason)
        return _blocked_campaign(
            candidate_id, reason, terminal_state, 0,
            optimizer_verdict=intent_verdict, equivalence=equivalence,
        )

    all_runs = [*before_runs, *after_runs]
    budget = check_execution_budget(candidate_id, before_runs, after_runs, policy, ledger)
    consumed_state = budget["state"]
    statuses = [str(run.get("status") or "").upper() for run in all_runs]
    runaway = "RUNAWAY" in statuses
    timeout = "TIMEOUT" in statuses or any(
        isinstance(run.get("elapsed_wall_ms"), (int, float))
        and run["elapsed_wall_ms"] > int(policy.get("per_run_timeout_ms", 0))
        for run in all_runs
    )
    execution_failed = any(status in {"FAILED", "ERROR", "CANCELLED"} for status in statuses)
    safety_reason = (
        "RUNAWAY_EXECUTION_DETECTED" if runaway else
        "RUN_TIMEOUT" if timeout else
        "CANDIDATE_EXECUTION_FAILED" if execution_failed else None
    )
    if safety_reason:
        terminal_state = _terminalize(consumed_state, candidate_id, safety_reason)
        return _blocked_campaign(
            candidate_id, safety_reason, terminal_state, len(all_runs), budget=budget,
            cancel_requested=True, runaway_check=True, optimizer_verdict=intent_verdict,
        )
    if budget["status"] != "WITHIN_BUDGET":
        return _blocked_campaign(
            candidate_id, str(budget["reason_code"]), consumed_state, len(all_runs),
            budget=budget, optimizer_verdict=intent_verdict,
        )

    before_summary = summarize_measurements(before_runs, policy)
    after_summary = summarize_measurements(after_runs, policy)
    if before_summary["status"] != "COMPLETE" or after_summary["status"] != "COMPLETE":
        reason = "MEASUREMENT_INCOMPLETE"
        terminal_state = _terminalize(consumed_state, candidate_id, reason)
        return _blocked_campaign(
            candidate_id, reason, terminal_state, len(all_runs), budget=budget,
            before_summary=before_summary, after_summary=after_summary,
            optimizer_verdict=intent_verdict,
        )
    from tools.asta_optimizer_intent import evaluate_candidate_after_optimizer_intent

    comparison = evaluate_candidate_after_optimizer_intent(
        optimizer_intent,
        before_summary["measurement_runs"],
        after_summary["measurement_runs"],
        workload,
    )
    comparison.update({
        "semantic_equivalent": True,
        "equivalence_strength": "FULL_RESULT_DIGEST",
        "digest_evaluated": True,
        "equivalence_status": equivalence["status"],
        "equivalence_verdict": equivalence["reason_code"],
        "equivalence_evidence": equivalence.get("evidence"),
        "result_digest_scope": equivalence.get("result_digest_scope"),
        "result_digest_mode": equivalence.get("result_digest_mode"),
    })
    reason = None
    status = "ACCEPTED"
    if comparison.get("semantic_equivalent") is not True:
        status, reason = "REJECTED", "RESULT_DIGEST_NOT_EQUIVALENT"
    elif comparison.get("latency_guard_passed") is not True:
        status, reason = "REJECTED", "OLTP_LATENCY_GUARD_NOT_MET"
    elif not isinstance(comparison.get("primary_reduction_pct"), (int, float)) or comparison["primary_reduction_pct"] < 5:
        status, reason = "REJECTED", "PERFORMANCE_NOT_IMPROVED"
    else:
        reason = "MEASUREMENT_ACCEPTED"
    final_state = consumed_state if status == "ACCEPTED" else _terminalize(consumed_state, candidate_id, reason)
    return {
        **comparison,
        "status": status,
        "reason_code": reason,
        "candidate_id": candidate_id,
        "optimizer_intent_verdict": comparison.get("optimizer_intent_verdict"),
        "processed_run_count": len(all_runs),
        "budget": budget,
        "before_summary": before_summary,
        "after_summary": after_summary,
        "cancel_requested": False,
        "runaway_session_check_required": False,
        "additional_runs_allowed": False,
        "state": final_state,
    }
