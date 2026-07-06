#!/usr/bin/env python3
"""ASTA 단계 2 link 결과를 결정론적인 구조화 rewrite 전략 계획으로 변환한다.

이 모듈은 SQL/LLM/DB를 호출하지 않으며 기존 runtime 경로에서 import하지 않는다.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


_COMMON_ANTI_CONSTRAINTS = [
    "원본 correlation key와 비교식을 그대로 보존한다.",
    "NULL 비교 결과와 NOT EXISTS anti-existence 의미를 보존한다.",
    "key producer 중복이 outer row multiplicity를 늘리지 않게 한다.",
]


STRATEGY_REGISTRY: dict[str, list[dict[str, Any]]] = {
    "CORRELATED_NOT_EXISTS": [
        {
            "strategy_id": "NOT_EXISTS_DISTINCT_KEY_ANTI",
            "transformation_summary": "상관 NOT EXISTS source의 제외 key를 DISTINCT producer로 한 번 계산해 anti-existence에 사용한다.",
            "expected_plan_effect": {"producer_starts": 1, "consumer": "ANTI_EXISTENCE"},
            "semantic_constraints": _COMMON_ANTI_CONSTRAINTS,
            "prerequisites": ["모든 correlation key 식별", "DISTINCT key가 NOT EXISTS 비교 grain과 정확히 일치"],
            "risk": "Optimizer가 DISTINCT CTE를 merge하면 반복 Starts가 유지될 수 있다.",
        },
        {
            "strategy_id": "NOT_EXISTS_GROUP_BY_KEY_ANTI",
            "transformation_summary": "제외 key를 동일 grain GROUP BY producer로 만들고 원래 consumer에서 anti-existence로 적용한다.",
            "expected_plan_effect": {"producer_starts": 1, "consumer": "ANTI_EXISTENCE"},
            "semantic_constraints": _COMMON_ANTI_CONSTRAINTS,
            "prerequisites": ["모든 correlation key 식별", "GROUP BY expression과 원래 비교 expression의 datatype 일치"],
            "risk": "GROUP BY view merge 또는 datatype 변환이 plan과 NULL 의미를 바꿀 수 있다.",
        },
        {
            "strategy_id": "NOT_EXISTS_UNION_DISTINCT_BARRIER",
            "transformation_summary": "UNION DISTINCT와 항상 빈 동일 projection branch로 set-operation barrier를 만들고 제외 key를 anti-existence에 사용한다.",
            "expected_plan_effect": {"producer_starts": 1, "consumer": "ANTI_EXISTENCE", "merge_barrier": "SET_OPERATION"},
            "semantic_constraints": _COMMON_ANTI_CONSTRAINTS,
            "prerequisites": ["양 branch projection/형식 일치", "빈 branch가 결과 row를 추가하지 않음"],
            "risk": "Set-operation sort 비용이 추가되며 projection datatype이 달라지면 의미가 변할 수 있다.",
        },
    ],
    "CORRELATED_EXISTS": [
        {
            "strategy_id": "EXISTS_DISTINCT_KEY_SEMI",
            "transformation_summary": "상관 EXISTS source의 존재 key를 DISTINCT producer로 한 번 계산해 semi-existence에 사용한다.",
            "expected_plan_effect": {"producer_starts": 1, "consumer": "SEMI_EXISTENCE"},
            "semantic_constraints": ["correlation key와 NULL 비교를 보존한다.", "outer row multiplicity를 보존한다."],
            "prerequisites": ["모든 correlation key 식별", "존재 여부 외 inner column을 소비하지 않음"],
            "risk": "CTE merge 시 반복 Starts가 유지될 수 있다.",
        },
        {
            "strategy_id": "EXISTS_GROUP_BY_KEY_SEMI",
            "transformation_summary": "존재 key를 GROUP BY producer로 만들고 원래 consumer에서 semi-existence로 적용한다.",
            "expected_plan_effect": {"producer_starts": 1, "consumer": "SEMI_EXISTENCE"},
            "semantic_constraints": ["correlation key와 NULL 비교를 보존한다.", "GROUP BY grain을 key와 동일하게 유지한다."],
            "prerequisites": ["모든 correlation key 식별"],
            "risk": "불필요한 group expression은 존재 의미나 비용을 바꿀 수 있다.",
        },
        {
            "strategy_id": "EXISTS_UNION_DISTINCT_BARRIER",
            "transformation_summary": "set-operation barrier를 가진 존재 key producer를 한 번 계산해 semi-existence에 사용한다.",
            "expected_plan_effect": {"producer_starts": 1, "consumer": "SEMI_EXISTENCE", "merge_barrier": "SET_OPERATION"},
            "semantic_constraints": ["빈 branch가 key를 추가하지 않는다.", "projection datatype과 NULL 의미를 보존한다."],
            "prerequisites": ["양 branch projection/형식 일치"],
            "risk": "Set-operation sort 비용이 추가된다.",
        },
    ],
    "SCALAR_AGGREGATE": [
        {
            "strategy_id": "SCALAR_AGG_PREAGGREGATE_JOIN",
            "transformation_summary": "상관 scalar aggregate를 correlation grain으로 사전 집계하고 원래 immediate consumer에서 단일 row로 연결한다.",
            "expected_plan_effect": {"aggregate_producer_starts": 1, "scalar_subquery_starts": 0},
            "semantic_constraints": ["scalar aggregate empty-input 결과 보존", "NULL과 datatype 보존", "outer row grain/중복 보존"],
            "prerequisites": ["aggregate와 correlation grain 식별", "consumer당 최대 한 aggregate row 보장"],
            "risk": "잘못된 grain이나 COALESCE는 empty-input NULL 의미를 바꾼다.",
        },
        {
            "strategy_id": "SCALAR_AGG_GROUPING_SETS",
            "transformation_summary": "정확/와일드카드 correlation grain을 GROUPING SETS로 사전 집계해 단일 row로 연결한다.",
            "expected_plan_effect": {"aggregate_producer_starts": 1, "scalar_subquery_starts": 0},
            "semantic_constraints": ["GROUPING flag로 실제 NULL과 집계 NULL 구분", "empty-input aggregate 의미 보존"],
            "prerequisites": ["와일드카드 DECODE/CASE grain 확인", "consumer당 최대 한 row 보장"],
            "risk": "GROUPING flag 또는 wildcard grain 오류는 중복/NULL 의미를 바꾼다.",
        },
    ],
    "REPEATED_FACT_SCAN": [
        {
            "strategy_id": "FACT_SCAN_FILTERED_KEYSET",
            "transformation_summary": "반복 fact scan의 필터/key producer를 한 번 계산하고 모든 consumer가 재사용하게 한다.",
            "expected_plan_effect": {"fact_scan_starts": 1, "producer_reuse": True},
            "semantic_constraints": ["원본 fact filter 전부 보존", "UNION ALL branch와 duplicate multiplicity 보존"],
            "prerequisites": ["반복 scan boundary와 consumer 식별", "재사용 key grain 확인"],
            "risk": "과도한 materialization이나 잘못된 key 축소는 temp 비용 또는 결과 손실을 만든다.",
        },
        {
            "strategy_id": "FACT_SCAN_PREAGGREGATE_ONCE",
            "transformation_summary": "fact를 원래 소비 grain으로 한 번 사전 집계해 반복 scan/aggregate를 제거한다.",
            "expected_plan_effect": {"fact_scan_starts": 1, "aggregate_restarts": 0},
            "semantic_constraints": ["원본 aggregate grain/NULL/중복 보존", "branch별 filter 보존"],
            "prerequisites": ["모든 consumer grain이 호환됨"],
            "risk": "grain 불일치 시 합계와 중복 수가 달라진다.",
        },
    ],
    "COMPOSITE_IN": [
        {
            "strategy_id": "COMPOSITE_IN_DISTINCT_KEY_SEMI",
            "transformation_summary": "복합 IN subquery의 tuple key를 DISTINCT producer로 한 번 계산해 semi-join 형태로 연결한다.",
            "expected_plan_effect": {"composite_key_producer_starts": 1, "inlist_restarts_reduced": True},
            "semantic_constraints": ["tuple column 순서/datatype 보존", "IN의 NULL/UNKNOWN 의미 보존", "outer duplicate 보존"],
            "prerequisites": ["tuple 양쪽 column 수/순서 확인", "NULL 가능성 확인"],
            "risk": "ANSI join 치환은 nullable tuple에서 IN 의미를 바꿀 수 있다.",
        },
        {
            "strategy_id": "COMPOSITE_IN_GROUPED_KEY_JOIN",
            "transformation_summary": "복합 tuple key를 동일 column 순서로 GROUP BY해 한 번 만들고 안전한 semi-existence로 소비한다.",
            "expected_plan_effect": {"composite_key_producer_starts": 1, "range_scan_starts_reduced": True},
            "semantic_constraints": ["tuple NULL/UNKNOWN 의미 보존", "GROUP BY grain을 전체 tuple과 동일하게 유지"],
            "prerequisites": ["전체 tuple key 식별", "nullable key 처리 증명"],
            "risk": "부분 key group이나 일반 join은 duplicate multiplicity를 늘린다.",
        },
    ],
}


def _pattern_type(link_result: dict[str, Any]) -> str | None:
    explicit = str(link_result.get("pattern_type") or "").upper()
    if explicit:
        return explicit
    construct = str(link_result.get("construct") or "").upper()
    correlated = bool(link_result.get("correlated_outer_aliases"))
    if construct == "NOT EXISTS" and correlated:
        return "CORRELATED_NOT_EXISTS"
    if construct == "EXISTS" and correlated:
        return "CORRELATED_EXISTS"
    aggregate_functions = link_result.get("aggregate_functions") or []
    if construct == "SCALAR_SUBQUERY" and aggregate_functions:
        return "SCALAR_AGGREGATE"
    if construct == "IN_SUBQUERY" and int(link_result.get("composite_key_count") or 0) > 1:
        return "COMPOSITE_IN"
    plan_reasons = set((link_result.get("dominant_plan_node") or {}).get("reason_codes") or [])
    if "REPEATED_SUBTREE_ROOT" in plan_reasons or "REPEATED_WORK" in plan_reasons:
        return "REPEATED_FACT_SCAN"
    return None


def _blocked(reason: str, reason_codes: list[str]) -> dict[str, Any]:
    return {
        "status": "BLOCKED",
        "pattern_type": None,
        "strategy_family": None,
        "strategies": [],
        "blocked_reason": reason,
        "reason_codes": list(reason_codes),
        "applied_feedback": [],
        "sql_execution_allowed": False,
    }


def plan_tuning_strategies(
    link_result: dict[str, Any], failure_feedback: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """안전하게 연결된 병목에 SQL이 아닌 구조화 strategy plan만 생성한다."""
    if link_result.get("status") != "LINKED" or link_result.get("rewrite_allowed") is not True:
        return _blocked("LINK_REWRITE_NOT_ALLOWED", list(link_result.get("reason_codes") or []))
    if float(link_result.get("confidence") or 0.0) < 0.8:
        return _blocked("LINK_CONFIDENCE_TOO_LOW", ["LINK_CONFIDENCE_BELOW_0_8"])

    pattern = _pattern_type(link_result)
    if pattern not in STRATEGY_REGISTRY:
        construct = str(link_result.get("construct") or "UNKNOWN").upper()
        explicit = str(link_result.get("pattern_type") or "UNKNOWN").upper()
        return _blocked("UNSUPPORTED_CONSTRUCT", [f"{explicit}:{construct}"])

    feedback = deepcopy(failure_feedback or [])
    failed_ids = {str(item.get("strategy_id") or "") for item in feedback}
    merge_failure = any(
        item.get("strategy_id") == "NOT_EXISTS_DISTINCT_KEY_ANTI"
        and str(item.get("reason_code") or "").upper() in {"DISTINCT_CTE_MERGED", "OPTIMIZER_MERGED_DISTINCT_CTE"}
        for item in feedback
    )
    definitions = deepcopy(STRATEGY_REGISTRY[pattern])
    definitions = [item for item in definitions if item["strategy_id"] not in failed_ids]
    if merge_failure:
        definitions.sort(key=lambda item: 0 if item["strategy_id"] == "NOT_EXISTS_UNION_DISTINCT_BARRIER" else 1)
    if not definitions:
        result = _blocked("STRATEGIES_EXHAUSTED", ["ALL_REGISTERED_STRATEGIES_FAILED"])
        result["pattern_type"] = pattern
        result["strategy_family"] = pattern
        result["applied_feedback"] = feedback
        return result

    target = {
        "source_span": deepcopy(link_result.get("source_span")),
        "query_block": link_result.get("query_block"),
        "object": link_result.get("referenced_object"),
    }
    strategies: list[dict[str, Any]] = []
    for priority, definition in enumerate(definitions, start=1):
        definition.update({
            "strategy_family": pattern,
            "priority": priority,
            "target": deepcopy(target),
            "blocked_reason": None,
            "executable": True,
        })
        strategies.append(definition)
    return {
        "status": "PLANNED",
        "pattern_type": pattern,
        "strategy_family": pattern,
        "strategies": strategies,
        "blocked_reason": None,
        "reason_codes": ["DETERMINISTIC_STRATEGY_REGISTRY", "LINK_TARGET_REWRITE_ALLOWED"],
        "applied_feedback": feedback,
        "sql_execution_allowed": False,
    }
