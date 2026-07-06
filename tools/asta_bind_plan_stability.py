#!/usr/bin/env python3
"""ASTA 단계 7 대표 bind coverage와 plan 안정성을 검증하는 순수 함수 모듈."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from tools.asta_quality_agent import parse_xplan_operations


RAW_VALUE_KEYS = {"value", "raw_value", "bind_value", "literal", "sample_value"}


def _blocked(reason_code: str, **evidence: Any) -> dict[str, Any]:
    return {
        "status": "BLOCKED",
        "reason_code": reason_code,
        "evaluation_allowed": False,
        "raw_bind_values_retained": False,
        **evidence,
    }


def _bind_signature(bindings: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    signature: list[dict[str, Any]] = []
    positions: set[int] = set()
    names: set[str] = set()
    for binding in bindings:
        name = str(binding.get("name") or "").upper()
        position = binding.get("position")
        oracle_type = str(binding.get("oracle_type") or "").upper()
        if not name or not isinstance(position, int) or position <= 0 or not oracle_type:
            return None
        if position in positions or name in names:
            return None
        positions.add(position)
        names.add(name)
        signature.append({"name": name, "position": position, "oracle_type": oracle_type})
    return sorted(signature, key=lambda item: item["position"])


def validate_representative_bind_set(
    bind_cases: list[dict[str, Any]], policy: dict[str, Any],
) -> dict[str, Any]:
    """원문 bind 없이 metadata·NULL·bucket coverage와 Before/After 동일 적용을 확인한다."""
    if not bind_cases:
        return _blocked("BIND_COVERAGE_INSUFFICIENT", bind_case_count=0)
    case_ids: set[str] = set()
    expected_signature: list[dict[str, Any]] | None = None
    covered: set[str] = set()
    for case_index, case in enumerate(bind_cases):
        case_id = str(case.get("bind_case_id") or "")
        if not case_id or case_id in case_ids:
            return _blocked("BIND_CASE_ID_INVALID", bind_case_index=case_index)
        case_ids.add(case_id)
        bindings = list(case.get("bindings") or [])
        for binding_index, binding in enumerate(bindings):
            if RAW_VALUE_KEYS.intersection(binding):
                return _blocked(
                    "RAW_BIND_VALUE_FORBIDDEN", bind_case_id=case_id, bind_index=binding_index,
                )
        signature = _bind_signature(bindings)
        if not signature:
            return _blocked("BIND_METADATA_INCOMPLETE", bind_case_id=case_id)
        if expected_signature is None:
            expected_signature = signature
        elif signature != expected_signature:
            return _blocked("BIND_METADATA_MISMATCH", bind_case_id=case_id)
        before_fingerprint = case.get("before_bind_fingerprint")
        after_fingerprint = case.get("after_bind_fingerprint")
        if not before_fingerprint or not after_fingerprint:
            return _blocked("BIND_FINGERPRINT_MISSING", bind_case_id=case_id)
        if before_fingerprint != after_fingerprint:
            return _blocked("BEFORE_AFTER_BIND_SET_MISMATCH", bind_case_id=case_id)
        if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", str(before_fingerprint)):
            return _blocked("BIND_FINGERPRINT_FORMAT_INVALID", bind_case_id=case_id)
        case_bucket = str(case.get("selectivity_bucket") or "").upper()
        if not case_bucket:
            return _blocked("BIND_SELECTIVITY_BUCKET_MISSING", bind_case_id=case_id)
        covered.add(case_bucket)
        for binding in bindings:
            bucket = str(binding.get("selectivity_bucket") or "").upper()
            is_null = binding.get("is_null")
            if not isinstance(is_null, bool) or (bucket == "NULL") != is_null:
                return _blocked("BIND_NULL_SEMANTICS_INVALID", bind_case_id=case_id)
            if not binding.get("value_fingerprint"):
                return _blocked("BIND_FINGERPRINT_MISSING", bind_case_id=case_id)
            if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", str(binding["value_fingerprint"])):
                return _blocked("BIND_FINGERPRINT_FORMAT_INVALID", bind_case_id=case_id)
    required = {str(value).upper() for value in policy.get("required_selectivity_buckets") or []}
    missing = sorted(required - covered)
    minimum = int(policy.get("min_bind_cases", 1))
    if len(bind_cases) < minimum or missing:
        return _blocked(
            "BIND_COVERAGE_INSUFFICIENT",
            bind_case_count=len(bind_cases),
            covered_selectivity_buckets=sorted(covered),
            missing_selectivity_buckets=missing,
        )
    return {
        "status": "VERIFIED",
        "reason_code": "BIND_COVERAGE_VERIFIED",
        "evaluation_allowed": True,
        "bind_case_count": len(bind_cases),
        "covered_selectivity_buckets": sorted(covered),
        "missing_selectivity_buckets": [],
        "bind_signature": expected_signature,
        "raw_bind_values_retained": False,
    }


def _base_object(value: Any) -> str:
    return str(value or "").rsplit(".", 1)[-1].upper()


def _digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _descendants(target_id: int, by_id: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    pending = list(by_id.get(target_id, {}).get("child_ids") or [])
    seen: set[int] = set()
    while pending:
        node_id = pending.pop(0)
        if node_id in seen:
            continue
        seen.add(node_id)
        node = by_id.get(node_id)
        if node:
            result.append(node)
            pending.extend(node.get("child_ids") or [])
    return result


def summarize_plan_sample(plan_text: str, target_object: str) -> dict[str, Any]:
    """Plan hash와 별도로 정규화 shape 및 target subtree Starts를 요약한다."""
    nodes = parse_xplan_operations(plan_text)
    target = _base_object(target_object)
    targets = [
        node for node in nodes
        if _base_object(node.get("object_name")) == target
        and isinstance(node.get("starts"), int) and node["starts"] > 0
    ]
    if len(targets) != 1:
        return {
            "status": "BLOCKED",
            "reason_code": "TARGET_PLAN_NODE_MISSING" if not targets else "TARGET_PLAN_NODE_AMBIGUOUS",
        }
    by_id = {node["id"]: node for node in nodes}
    target_node = targets[0]
    subtree = [target_node, *_descendants(target_node["id"], by_id)]
    shape = []
    for node in nodes:
        parent = by_id.get(node.get("parent_id"))
        shape.append({
            "operation": " ".join(str(node.get("operation") or "").upper().split()),
            "object": _base_object(node.get("object_name")),
            "parent_operation": " ".join(str(parent.get("operation") if parent else "").upper().split()),
        })
    starts_profile = [
        {
            "operation": " ".join(str(node.get("operation") or "").upper().split()),
            "object": _base_object(node.get("object_name")),
            "starts": node.get("starts"),
        }
        for node in subtree
        if isinstance(node.get("starts"), int) and node["starts"] > 0
    ]
    operations = {item["operation"] for item in shape}
    anti_present = any("ANTI" in operation for operation in operations)
    barrier_present = "SORT UNIQUE" in operations and "UNION-ALL" in operations
    if target_node["starts"] == 1 and anti_present and barrier_present:
        family = "SET_OPERATION_BARRIER"
    elif target_node["starts"] == 1 and anti_present:
        family = "ANTI_SINGLE_PRODUCER"
    elif target_node["starts"] > 1:
        family = "REPEATED_CORRELATED"
    else:
        family = "OTHER"
    hash_match = re.search(r"Plan hash value:\s*(\d+)", plan_text, re.IGNORECASE)
    return {
        "status": "COMPLETED",
        "reason_code": None,
        "plan_hash": int(hash_match.group(1)) if hash_match else None,
        "plan_family": family,
        "target_node_id": target_node["id"],
        "target_starts": target_node["starts"],
        "shape_signature": _digest(shape),
        "starts_signature": _digest(starts_profile),
        "starts_profile": starts_profile,
    }


def evaluate_bind_plan_stability(
    bind_cases: list[dict[str, Any]], policy: dict[str, Any],
) -> dict[str, Any]:
    """대표 bind별 intent/equivalence 선행 조건과 plan family/shape/Starts 안정성을 검증한다."""
    coverage = validate_representative_bind_set(bind_cases, policy)
    if coverage["status"] != "VERIFIED":
        return {**coverage, "bind_results": [], "plan_stability_verified": False}
    target_object = str(policy.get("target_object") or "")
    if not target_object:
        return _blocked("TARGET_PLAN_OBJECT_REQUIRED", bind_results=[], plan_stability_verified=False)
    expected_by_bucket = {
        str(bucket).upper(): {str(family).upper() for family in families}
        for bucket, families in (policy.get("expected_plan_families") or {}).items()
    }
    minimum_samples = int(policy.get("min_plan_samples_per_bind", 2))
    bind_results: list[dict[str, Any]] = []
    all_families: set[str] = set()
    reason_codes = ["BIND_COVERAGE_VERIFIED"]
    for case in bind_cases:
        case_id = str(case["bind_case_id"])
        intent = case.get("optimizer_intent") or {}
        if intent.get("status") != "VERIFIED" or intent.get("allow_downstream_evaluation") is not True:
            return _blocked(
                "BIND_OPTIMIZER_INTENT_NOT_VERIFIED", bind_case_id=case_id,
                bind_results=bind_results, plan_stability_verified=False,
            )
        equivalence = case.get("equivalence") or {}
        if equivalence.get("status") != "VERIFIED" or equivalence.get("allow_performance_measurement") is not True:
            return _blocked(
                "BIND_EQUIVALENCE_NOT_VERIFIED", bind_case_id=case_id,
                bind_results=bind_results, plan_stability_verified=False,
            )
        before_samples = list(case.get("before_plan_samples") or [])
        if len(before_samples) < minimum_samples:
            return _blocked(
                "INSUFFICIENT_BEFORE_BIND_PLAN_EVIDENCE", bind_case_id=case_id,
                observed_plan_samples=len(before_samples), bind_results=bind_results,
                plan_stability_verified=False,
            )
        before_summaries = [summarize_plan_sample(sample, target_object) for sample in before_samples]
        if any(summary["status"] != "COMPLETED" for summary in before_summaries):
            return _blocked(
                "INSUFFICIENT_BEFORE_BIND_PLAN_EVIDENCE", bind_case_id=case_id,
                plan_evidence=before_summaries, bind_results=bind_results,
                plan_stability_verified=False,
            )
        before_families = {summary["plan_family"] for summary in before_summaries}
        before_shapes = {summary["shape_signature"] for summary in before_summaries}
        before_starts = {summary["starts_signature"] for summary in before_summaries}
        if len(before_families) > 1 or len(before_shapes) > 1 or len(before_starts) > 1:
            return _blocked(
                "BEFORE_PLAN_UNSTABLE", bind_case_id=case_id,
                observed_plan_families=sorted(before_families), bind_results=bind_results,
                plan_stability_verified=False,
            )
        samples = list(case.get("after_plan_samples") or [])
        if len(samples) < minimum_samples:
            return _blocked(
                "INSUFFICIENT_BIND_PLAN_EVIDENCE", bind_case_id=case_id,
                observed_plan_samples=len(samples), bind_results=bind_results,
                plan_stability_verified=False,
            )
        summaries = [summarize_plan_sample(sample, target_object) for sample in samples]
        if any(summary["status"] != "COMPLETED" for summary in summaries):
            return _blocked(
                "INSUFFICIENT_BIND_PLAN_EVIDENCE", bind_case_id=case_id,
                plan_evidence=summaries, bind_results=bind_results,
                plan_stability_verified=False,
            )
        families = {summary["plan_family"] for summary in summaries}
        shapes = {summary["shape_signature"] for summary in summaries}
        starts = {summary["starts_signature"] for summary in summaries}
        hashes = {summary["plan_hash"] for summary in summaries}
        if len(families) > 1:
            return _blocked(
                "PLAN_FLIP_DETECTED", bind_case_id=case_id,
                observed_plan_families=sorted(families), bind_results=bind_results,
                plan_stability_verified=False,
            )
        if len(shapes) > 1:
            return _blocked(
                "PLAN_SHAPE_UNSTABLE", bind_case_id=case_id,
                observed_plan_hashes=sorted(value for value in hashes if value is not None),
                bind_results=bind_results, plan_stability_verified=False,
            )
        if len(starts) > 1:
            return _blocked(
                "STARTS_SUBTREE_UNSTABLE", bind_case_id=case_id,
                bind_results=bind_results, plan_stability_verified=False,
            )
        family = next(iter(families))
        bucket = str(case.get("selectivity_bucket") or "").upper()
        allowed_families = expected_by_bucket.get(bucket) or set()
        if family not in allowed_families:
            return _blocked(
                "UNEXPECTED_PLAN_FAMILY", bind_case_id=case_id,
                selectivity_bucket=bucket, observed_plan_family=family,
                expected_plan_families=sorted(allowed_families), bind_results=bind_results,
                plan_stability_verified=False,
            )
        if len(hashes) > 1:
            reason_codes.append("PLAN_HASH_VARIATION_SHAPE_STABLE")
        all_families.add(family)
        bind_results.append({
            "bind_case_id": case_id,
            "selectivity_bucket": bucket,
            "stable": True,
            "plan_family": family,
            "plan_hashes": sorted(value for value in hashes if value is not None),
            "shape_signature": next(iter(shapes)),
            "starts_signature": next(iter(starts)),
            "target_starts": summaries[0]["target_starts"],
            "before_plan_family": before_summaries[0]["plan_family"],
            "before_plan_hashes": sorted({
                summary["plan_hash"] for summary in before_summaries if summary["plan_hash"] is not None
            }),
            "before_shape_signature": next(iter(before_shapes)),
            "before_starts_signature": next(iter(before_starts)),
        })
    variation = len(all_families) > 1
    if variation:
        reason_codes.append("EXPECTED_BIND_SENSITIVE_PLAN_VARIATION")
    return {
        "status": "VERIFIED",
        "reason_code": "BIND_SENSITIVE_PLAN_VARIATION_ACCEPTED" if variation else "PLAN_STABILITY_VERIFIED",
        "evaluation_allowed": True,
        "plan_stability_verified": True,
        "plan_hash_only_success": False,
        "observed_plan_families": sorted(all_families),
        "bind_results": bind_results,
        "reason_codes": sorted(set(reason_codes)),
        "coverage": coverage,
    }


def _empty_budget_state() -> dict[str, Any]:
    return {
        "used_total_runs": 0,
        "used_total_wall_time_ms": 0,
        "candidates": {},
        "terminal_candidates": {},
    }


def _bind_campaign_blocked(reason_code: str, **details: Any) -> dict[str, Any]:
    return {
        "status": "BLOCKED",
        "reason_code": reason_code,
        "all_representative_binds_passed": False,
        "processed_run_count": 0,
        "performance_evaluated": False,
        "budget_state": _empty_budget_state(),
        **details,
    }


def _preflight_bind_execution_budget(
    bind_cases: list[dict[str, Any]], policy: dict[str, Any],
) -> dict[str, Any]:
    before_runs = [run for case in bind_cases for run in (case.get("before_runs") or [])]
    after_runs = [run for case in bind_cases for run in (case.get("after_runs") or [])]
    all_runs = [*before_runs, *after_runs]
    walls = [run.get("elapsed_wall_ms") for run in all_runs]
    if any(not isinstance(value, (int, float)) or value < 0 for value in walls):
        return {"status": "BLOCKED", "reason_code": "BIND_EXECUTION_BUDGET_EVIDENCE_INCOMPLETE"}
    total_runs = len(all_runs)
    total_wall = int(sum(walls))
    candidate_runs = len(after_runs)
    candidate_wall = int(sum(run["elapsed_wall_ms"] for run in after_runs))
    reason = None
    if total_runs > int(policy.get("max_total_runs", 0)):
        reason = "TOTAL_RUN_BUDGET_EXCEEDED"
    elif total_wall > int(policy.get("max_total_wall_time_ms", 0)):
        reason = "TOTAL_TIME_BUDGET_EXCEEDED"
    elif candidate_runs > int(policy.get("max_candidate_runs", 0)):
        reason = "CANDIDATE_RUN_BUDGET_EXCEEDED"
    elif candidate_wall > int(policy.get("max_candidate_wall_time_ms", 0)):
        reason = "CANDIDATE_TIME_BUDGET_EXCEEDED"
    return {
        "status": "BLOCKED" if reason else "WITHIN_BUDGET",
        "reason_code": reason,
        "planned_total_runs": total_runs,
        "planned_total_wall_time_ms": total_wall,
        "planned_candidate_runs": candidate_runs,
        "planned_candidate_wall_time_ms": candidate_wall,
    }


def evaluate_bind_campaign(
    candidate_id: str,
    bind_cases: list[dict[str, Any]],
    stability_policy: dict[str, Any],
    execution_policy: dict[str, Any],
) -> dict[str, Any]:
    """모든 bind의 intent/equivalence/plan 안정성을 확인한 뒤에만 반복 측정을 평가한다."""
    coverage = validate_representative_bind_set(bind_cases, stability_policy)
    if coverage.get("status") != "VERIFIED":
        return _bind_campaign_blocked(
            str(coverage.get("reason_code") or "BIND_COVERAGE_INSUFFICIENT"),
            stability_evaluated=False, coverage=coverage,
        )
    for case in bind_cases:
        intent = case.get("optimizer_intent") or {}
        if intent.get("status") != "VERIFIED" or intent.get("allow_downstream_evaluation") is not True:
            return _bind_campaign_blocked(
                "BIND_OPTIMIZER_INTENT_NOT_VERIFIED",
                failed_bind_case_id=case.get("bind_case_id"), stability_evaluated=False,
            )

    from tools.asta_result_equivalence import verify_result_equivalence

    for case in bind_cases:
        payload = case.get("equivalence_evidence") or {}
        equivalence = verify_result_equivalence(
            str(payload.get("sql_text") or ""),
            list(payload.get("before_runs") or []),
            list(payload.get("after_runs") or []),
        )
        if equivalence.get("status") != "VERIFIED":
            return _bind_campaign_blocked(
                "BIND_CASE_EQUIVALENCE_FAILED",
                failed_bind_case_id=case.get("bind_case_id"),
                failed_bind_reason=equivalence.get("reason_code"),
                stability_evaluated=False,
                equivalence=equivalence,
            )
    stability = evaluate_bind_plan_stability(bind_cases, stability_policy)
    if stability.get("status") != "VERIFIED":
        return _bind_campaign_blocked(
            str(stability.get("reason_code") or "BIND_PLAN_STABILITY_NOT_VERIFIED"),
            failed_bind_case_id=stability.get("bind_case_id"),
            stability=stability, stability_evaluated=True,
        )
    preflight = _preflight_bind_execution_budget(bind_cases, execution_policy)
    if preflight["status"] != "WITHIN_BUDGET":
        return _bind_campaign_blocked(
            "BIND_EXECUTION_BUDGET_EXCEEDED",
            budget_reason=preflight.get("reason_code"),
            budget_preflight=preflight,
            stability=stability, stability_evaluated=True,
        )

    from tools.asta_execution_budget import evaluate_measurement_campaign

    state = _empty_budget_state()
    bind_results: list[dict[str, Any]] = []
    processed = 0
    for case in bind_cases:
        result = evaluate_measurement_campaign(
            candidate_id,
            case.get("optimizer_intent") or {},
            list(case.get("before_runs") or []),
            list(case.get("after_runs") or []),
            str(stability_policy.get("workload") or "OLTP"),
            execution_policy,
            state,
            equivalence_evidence=case.get("equivalence_evidence") or {},
        )
        state = result["state"]
        processed += int(result.get("processed_run_count") or 0)
        bind_result = {
            "bind_case_id": case["bind_case_id"],
            "selectivity_bucket": case["selectivity_bucket"],
            "status": result["status"],
            "reason_code": result["reason_code"],
            "median_elapsed_us": (result.get("after_summary") or {}).get("median_elapsed_us"),
            "median_buffer_gets": (result.get("after_summary") or {}).get("median_buffer_gets"),
            "elapsed_noise_pct": (result.get("after_summary") or {}).get("elapsed_noise_pct"),
            "latency_guard_passed": result.get("latency_guard_passed"),
            "semantic_equivalent": result.get("semantic_equivalent") is True,
        }
        bind_results.append(bind_result)
        if result["status"] != "ACCEPTED":
            failed_reason = str(result.get("reason_code") or "BIND_CASE_EVALUATION_FAILED")
            if failed_reason == "OLTP_LATENCY_GUARD_NOT_MET":
                overall_reason = "BIND_CASE_LATENCY_REGRESSION"
            elif failed_reason.startswith("RESULT_") or failed_reason == "FULL_RESULT_EVIDENCE_REQUIRED":
                overall_reason = "BIND_CASE_EQUIVALENCE_FAILED"
            elif failed_reason == "PERFORMANCE_NOT_IMPROVED":
                overall_reason = "BIND_CASE_PERFORMANCE_REGRESSION"
            elif failed_reason == "MEASUREMENT_NOISE_TOO_HIGH":
                overall_reason = "BIND_CASE_MEASUREMENT_UNSTABLE"
            elif "BUDGET" in failed_reason:
                overall_reason = "BIND_EXECUTION_BUDGET_EXCEEDED"
            else:
                overall_reason = "BIND_CASE_EVALUATION_FAILED"
            return {
                "status": "REJECTED" if result["status"] == "REJECTED" else "BLOCKED",
                "reason_code": overall_reason,
                "failed_bind_case_id": case["bind_case_id"],
                "failed_bind_reason": failed_reason,
                "all_representative_binds_passed": False,
                "processed_run_count": processed,
                "performance_evaluated": result.get("performance_evaluated") is True,
                "bind_results": bind_results,
                "stability": stability,
                "stability_evaluated": True,
                "budget_state": state,
            }
    elapsed_values = [item["median_elapsed_us"] for item in bind_results]
    noise_values = [item["elapsed_noise_pct"] for item in bind_results]
    return {
        "status": "ACCEPTED",
        "reason_code": "BIND_PLAN_STABILITY_VERIFIED",
        "all_representative_binds_passed": True,
        "bind_case_count": len(bind_cases),
        "successful_bind_count": len(bind_results),
        "processed_run_count": processed,
        "performance_evaluated": True,
        "worst_after_elapsed_us": max(elapsed_values),
        "worst_after_noise_pct": max(noise_values),
        "bind_results": bind_results,
        "stability": stability,
        "stability_evaluated": True,
        "budget_preflight": preflight,
        "budget_state": state,
    }
