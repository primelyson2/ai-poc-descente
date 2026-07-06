#!/usr/bin/env python3
"""Before/After XPLAN으로 구조적 optimizer 의도를 검증하는 순수 함수 모듈."""

from __future__ import annotations

import re
from typing import Any

from tools.asta_quality_agent import parse_xplan_operations


def _plan_hash(plan_text: str) -> int | None:
    match = re.search(r"Plan hash value:\s*(\d+)", plan_text, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _base_object(value: str | None) -> str:
    return str(value or "").rsplit(".", 1)[-1].upper()


def _operation_family(operation: str | None) -> str:
    value = " ".join(str(operation or "").upper().split())
    if value == "VIEW" or value.startswith("VIEW "):
        return "VIEW"
    if "INDEX" in value and ("SCAN" in value or "ACCESS" in value):
        return "INDEX_ACCESS"
    if value.startswith("TABLE ACCESS"):
        return "TABLE_ACCESS"
    return value


def _active_object_nodes(plan_text: str, object_name: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes = parse_xplan_operations(plan_text)
    target = _base_object(object_name)
    matches = [node for node in nodes if _base_object(node.get("object_name")) == target]
    active = [node for node in matches if isinstance(node.get("starts"), int) and node["starts"] > 0]
    return nodes, active


def match_semantic_plan_nodes(before_plan: str, after_plan: str, object_name: str) -> dict[str, Any]:
    """Plan node id/hash가 아닌 object, operation family, active execution으로 대응 node를 찾는다."""
    before_hash = _plan_hash(before_plan)
    after_hash = _plan_hash(after_plan)
    _, before_nodes = _active_object_nodes(before_plan, object_name)
    _, after_nodes = _active_object_nodes(after_plan, object_name)
    common = {
        "before_plan_hash": before_hash,
        "after_plan_hash": after_hash,
        "plan_hash_changed": before_hash is not None and after_hash is not None and before_hash != after_hash,
    }
    if len(before_nodes) != 1 or len(after_nodes) != 1:
        return {
            "status": "INSUFFICIENT_PLAN_EVIDENCE",
            **common,
            "before_node": before_nodes[0] if len(before_nodes) == 1 else None,
            "after_node": after_nodes[0] if len(after_nodes) == 1 else None,
            "match_basis": [],
            "reason_codes": ["TARGET_PLAN_NODE_MISSING" if not before_nodes or not after_nodes else "TARGET_PLAN_NODE_AMBIGUOUS"],
        }
    before_node = before_nodes[0]
    after_node = after_nodes[0]
    if _operation_family(before_node["operation"]) != _operation_family(after_node["operation"]):
        return {
            "status": "INSUFFICIENT_PLAN_EVIDENCE",
            **common,
            "before_node": before_node,
            "after_node": after_node,
            "match_basis": ["OBJECT_NAME", "ACTIVE_EXECUTION"],
            "reason_codes": ["OPERATION_FAMILY_MISMATCH"],
        }
    return {
        "status": "MATCHED",
        **common,
        "before_node": before_node,
        "after_node": after_node,
        "match_basis": ["OBJECT_NAME", "OPERATION_FAMILY", "ACTIVE_EXECUTION"],
        "reason_codes": ["SEMANTIC_PLAN_NODE_MATCHED"],
    }


def _tree_maps(nodes: list[dict[str, Any]]) -> tuple[dict[int, dict[str, Any]], dict[int, list[int]]]:
    by_id = {node["id"]: node for node in nodes}
    children = {node_id: list(node.get("child_ids") or []) for node_id, node in by_id.items()}
    return by_id, children


def _ancestor_nodes(node_id: int, by_id: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    ancestors: list[dict[str, Any]] = []
    current = by_id.get(node_id)
    seen: set[int] = set()
    while current and current.get("parent_id") is not None and current["parent_id"] not in seen:
        parent_id = current["parent_id"]
        seen.add(parent_id)
        current = by_id.get(parent_id)
        if current:
            ancestors.append(current)
    return ancestors


def _descendant_nodes(
    node_id: int, by_id: dict[int, dict[str, Any]], children: dict[int, list[int]],
) -> list[dict[str, Any]]:
    descendants: list[dict[str, Any]] = []
    pending = list(children.get(node_id, []))
    seen: set[int] = set()
    while pending:
        child_id = pending.pop(0)
        if child_id in seen:
            continue
        seen.add(child_id)
        child = by_id.get(child_id)
        if child:
            descendants.append(child)
            pending.extend(children.get(child_id, []))
    return descendants


def _max_active_starts(nodes: list[dict[str, Any]]) -> int | None:
    values = [node["starts"] for node in nodes if isinstance(node.get("starts"), int) and node["starts"] > 0]
    return max(values) if values else None


def _matching_descendant_evidence(
    before_nodes: list[dict[str, Any]], after_nodes: list[dict[str, Any]], producer_object: str,
) -> list[dict[str, Any]]:
    before_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    after_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for nodes, destination in ((before_nodes, before_by_key), (after_nodes, after_by_key)):
        for node in nodes:
            object_name = _base_object(node.get("object_name"))
            if object_name and object_name != _base_object(producer_object):
                destination.setdefault((object_name, _operation_family(node["operation"])), []).append(node)
    evidence: list[dict[str, Any]] = []
    for key in sorted(set(before_by_key).intersection(after_by_key)):
        before = max(before_by_key[key], key=lambda item: (item.get("buffers") or 0, item["id"]))
        after = max(after_by_key[key], key=lambda item: (item.get("buffers") or 0, item["id"]))
        evidence.append({
            "object_name": key[0],
            "operation": key[1],
            "before_node_id": before["id"],
            "after_node_id": after["id"],
            "before_starts": before.get("starts"),
            "after_starts": after.get("starts"),
        })
    return evidence


def verify_optimizer_intent(
    before_plan: str, after_plan: str, strategy_plan: dict[str, Any],
) -> dict[str, Any]:
    """Strategy expected_plan_effect를 실제 tree/Starts로 검증하고 다음 평가 허용 여부를 결정한다."""
    target = strategy_plan.get("target") or {}
    object_name = str(target.get("object") or "")
    matched = match_semantic_plan_nodes(before_plan, after_plan, object_name)
    common = {
        "strategy_id": strategy_plan.get("strategy_id"),
        "before_plan_hash": matched.get("before_plan_hash"),
        "after_plan_hash": matched.get("after_plan_hash"),
        "plan_hash_changed": matched.get("plan_hash_changed"),
    }
    if matched.get("status") != "MATCHED":
        return {
            "status": "BLOCKED",
            "verdict_reason": "INSUFFICIENT_PLAN_EVIDENCE",
            **common,
            "checks": {},
            "evidence": {"node_match": matched},
            "reason_codes": list(matched.get("reason_codes") or ["PLAN_NODE_MATCH_FAILED"]),
            "allow_downstream_evaluation": False,
            "report_reason_ko": "필수 Plan node/Starts/operation 증거가 없거나 모호하여 후보를 판정하지 않았습니다.",
        }

    before_all = parse_xplan_operations(before_plan)
    after_all = parse_xplan_operations(after_plan)
    before_by_id, before_children = _tree_maps(before_all)
    after_by_id, after_children = _tree_maps(after_all)
    before_node = matched["before_node"]
    after_node = matched["after_node"]
    before_descendants = _descendant_nodes(before_node["id"], before_by_id, before_children)
    after_descendants = _descendant_nodes(after_node["id"], after_by_id, after_children)
    before_subtree = [before_node, *before_descendants]
    after_subtree = [after_node, *after_descendants]
    ancestors = _ancestor_nodes(after_node["id"], after_by_id)
    ancestor_operations = [node["operation"] for node in ancestors]
    expected = strategy_plan.get("expected_plan_effect") or {}
    expected_starts = next(
        (
            expected[key] for key in (
                "producer_starts", "fact_scan_starts", "aggregate_producer_starts",
                "composite_key_producer_starts",
            )
            if isinstance(expected.get(key), int)
        ),
        None,
    )
    producer_starts_ok = isinstance(expected_starts, int) and after_node.get("starts") == expected_starts
    before_max_starts = _max_active_starts(before_subtree)
    after_max_starts = _max_active_starts(after_subtree)
    repeated_removed = (
        isinstance(before_max_starts, int)
        and before_max_starts > 1
        and isinstance(after_max_starts, int)
        and after_max_starts <= 1
    )
    anti_nodes = [node for node in ancestors if "ANTI" in node["operation"]]
    anti_present = bool(anti_nodes)
    sort_unique_present = "SORT UNIQUE" in ancestor_operations
    union_present = "UNION-ALL" in ancestor_operations
    barrier_maintained = sort_unique_present and union_present
    strategy_id = str(strategy_plan.get("strategy_id") or "")
    distinct_remerged = strategy_id == "NOT_EXISTS_DISTINCT_KEY_ANTI" and not producer_starts_ok
    checks = {
        "producer_starts_1": producer_starts_ok,
        "repeated_subtree_removed": repeated_removed,
        "anti_consumer_present": anti_present,
        "set_operation_barrier_maintained": barrier_maintained,
        "distinct_cte_remerged": distinct_remerged,
    }
    required = [producer_starts_ok, repeated_removed]
    if expected.get("consumer") == "ANTI_EXISTENCE":
        required.append(anti_present)
    if expected.get("merge_barrier") == "SET_OPERATION":
        required.append(barrier_maintained)
    if strategy_id == "NOT_EXISTS_DISTINCT_KEY_ANTI":
        required.append(not distinct_remerged)

    reason_codes: list[str] = []
    reason_codes.append("PRODUCER_STARTS_TARGET_MET" if producer_starts_ok else "PRODUCER_STARTS_NOT_REDUCED")
    reason_codes.append("REPEATED_SUBTREE_REMOVED" if repeated_removed else "REPEATED_SUBTREE_REMAINS")
    if expected.get("consumer") == "ANTI_EXISTENCE":
        reason_codes.append("ANTI_CONSUMER_PRESENT" if anti_present else "ANTI_CONSUMER_NOT_FOUND")
    if expected.get("merge_barrier") == "SET_OPERATION":
        reason_codes.append("SET_OPERATION_BARRIER_MAINTAINED" if barrier_maintained else "SET_OPERATION_BARRIER_NOT_FOUND")
    if distinct_remerged:
        reason_codes.append("DISTINCT_CTE_REMERGED")
    verified = all(required)
    anti_evidence = anti_nodes[0] if anti_nodes else None
    evidence = {
        "node_match": matched,
        "producer": {
            "object": object_name,
            "before_node_id": before_node["id"],
            "after_node_id": after_node["id"],
            "before_starts": before_node.get("starts"),
            "after_starts": after_node.get("starts"),
        },
        "repeated_subtree": {
            "before_max_starts": before_max_starts,
            "after_max_starts": after_max_starts,
            "corresponding_descendants": _matching_descendant_evidence(
                before_descendants, after_descendants, object_name
            ),
        },
        "set_operation_barrier": {
            "operations": [operation for operation in ("SORT UNIQUE", "UNION-ALL") if operation in ancestor_operations],
        },
        "anti_consumer": {
            "node_id": anti_evidence["id"] if anti_evidence else None,
            "operation": anti_evidence["operation"] if anti_evidence else None,
            "starts": anti_evidence.get("starts") if anti_evidence else None,
        },
    }
    return {
        "status": "VERIFIED" if verified else "REJECTED",
        "verdict_reason": "OPTIMIZER_INTENT_VERIFIED" if verified else "OPTIMIZER_INTENT_NOT_MET",
        **common,
        "checks": checks,
        "evidence": evidence,
        "reason_codes": reason_codes,
        "allow_downstream_evaluation": verified,
        "report_reason_ko": (
            "후보의 구조적 Optimizer 의도가 실제 After XPLAN에서 확인됐습니다."
            if verified else
            "후보가 기대한 Starts 감소 또는 plan 구조를 만들지 못해 결과 동등성/성능 판정 전에 거절했습니다."
        ),
    }


def evaluate_candidate_after_optimizer_intent(
    intent_result: dict[str, Any],
    before_runs: list[dict[str, Any]],
    after_runs: list[dict[str, Any]],
    workload: str,
) -> dict[str, Any]:
    """Optimizer intent를 fail-closed 선행 gate로 적용한 뒤에만 digest/성능 비교를 수행한다."""
    intent_status = str(intent_result.get("status") or "").upper()
    intent_verdict = str(intent_result.get("verdict_reason") or "INSUFFICIENT_PLAN_EVIDENCE")
    if intent_status != "VERIFIED" or intent_result.get("allow_downstream_evaluation") is not True:
        return {
            "status": "BLOCKED",
            "verdict_reason": intent_verdict,
            "optimizer_intent_status": intent_status or "BLOCKED",
            "optimizer_intent_verdict": intent_verdict,
            "optimizer_intent_reason_codes": list(intent_result.get("reason_codes") or []),
            "candidate_evaluation_allowed": False,
            "digest_evaluated": False,
            "performance_evaluated": False,
            "semantic_equivalent": False,
            "report_reason_ko": intent_result.get("report_reason_ko") or (
                "Optimizer 의도 증거가 부족하여 결과 동등성/성능 판정 전에 차단했습니다."
            ),
        }

    # 순환 import와 runtime 자동 연결을 피하면서 기존 deterministic 비교 계약을 재사용한다.
    from tools.run_asta_prompt_abc_adb import compare_repeated

    comparison = compare_repeated(before_runs, after_runs, workload)
    return {
        "status": "EVALUATED",
        "verdict_reason": "CANDIDATE_EVALUATION_COMPLETED",
        "optimizer_intent_status": intent_status,
        "optimizer_intent_verdict": intent_verdict,
        "optimizer_intent_reason_codes": list(intent_result.get("reason_codes") or []),
        "candidate_evaluation_allowed": True,
        "digest_evaluated": True,
        "performance_evaluated": True,
        "report_reason_ko": intent_result.get("report_reason_ko"),
        **comparison,
    }
