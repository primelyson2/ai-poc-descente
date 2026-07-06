"""단계 4 Before/After XPLAN 기반 Optimizer 의도 검증 행동 테스트."""

from pathlib import Path

from tools.asta_optimizer_intent import (
    evaluate_candidate_after_optimizer_intent,
    match_semantic_plan_nodes,
    verify_optimizer_intent,
)
from tools.asta_quality_agent import classify_failure, link_dominant_plan_node_to_sql, normalize_result
from tools.asta_strategy_planner import plan_tuning_strategies


ROOT = Path(__file__).resolve().parents[1]
BEFORE = (ROOT / "tests/fixtures/asta_customer_01_dominant_xplan.txt").read_text(encoding="utf-8")
DISTINCT_MERGED = (ROOT / "tests/fixtures/asta_customer_01_distinct_merged_xplan.txt").read_text(encoding="utf-8")
UNION_BARRIER = (ROOT / "tests/fixtures/asta_customer_01_union_barrier_xplan.txt").read_text(encoding="utf-8")
CUSTOMER_SQL = (ROOT / "tests/fixtures/asta_customer_01_style_not_exists.sql").read_text(encoding="utf-8")


def customer_strategy(strategy_id: str) -> dict:
    link = link_dominant_plan_node_to_sql(CUSTOMER_SQL, BEFORE)
    planned = plan_tuning_strategies(link)
    return next(item for item in planned["strategies"] if item["strategy_id"] == strategy_id)


def test_semantic_node_match_uses_object_operation_and_tree_not_plan_hash():
    result = match_semantic_plan_nodes(BEFORE, UNION_BARRIER, "DSNT.VIF_WHOLESALE_S")

    assert result["status"] == "MATCHED"
    assert result["before_plan_hash"] == 1663017477
    assert result["after_plan_hash"] == 101251183
    assert result["plan_hash_changed"] is True
    assert result["before_node"]["id"] == 28
    assert result["before_node"]["operation"] == "VIEW"
    assert result["before_node"]["starts"] == 845
    assert result["after_node"]["id"] == 31
    assert result["after_node"]["operation"] == "VIEW"
    assert result["after_node"]["starts"] == 1
    assert result["match_basis"] == ["OBJECT_NAME", "OPERATION_FAMILY", "ACTIVE_EXECUTION"]


def test_failed_distinct_cte_is_rejected_when_repeated_subtree_remains():
    result = verify_optimizer_intent(
        BEFORE,
        DISTINCT_MERGED,
        customer_strategy("NOT_EXISTS_DISTINCT_KEY_ANTI"),
    )

    assert result["status"] == "REJECTED"
    assert result["verdict_reason"] == "OPTIMIZER_INTENT_NOT_MET"
    assert result["allow_downstream_evaluation"] is False
    assert result["evidence"]["producer"]["before_starts"] == 845
    assert result["evidence"]["producer"]["after_starts"] == 845
    assert result["evidence"]["repeated_subtree"]["after_max_starts"] == 845
    assert result["checks"]["producer_starts_1"] is False
    assert result["checks"]["repeated_subtree_removed"] is False
    assert result["checks"]["distinct_cte_remerged"] is True
    assert "DISTINCT_CTE_REMERGED" in result["reason_codes"]


def test_union_distinct_barrier_verifies_all_expected_plan_effects():
    result = verify_optimizer_intent(
        BEFORE,
        UNION_BARRIER,
        customer_strategy("NOT_EXISTS_UNION_DISTINCT_BARRIER"),
    )

    assert result["status"] == "VERIFIED"
    assert result["verdict_reason"] == "OPTIMIZER_INTENT_VERIFIED"
    assert result["allow_downstream_evaluation"] is True
    assert result["checks"] == {
        "producer_starts_1": True,
        "repeated_subtree_removed": True,
        "anti_consumer_present": True,
        "set_operation_barrier_maintained": True,
        "distinct_cte_remerged": False,
    }
    assert result["evidence"]["producer"]["after_node_id"] == 31
    assert result["evidence"]["producer"]["after_starts"] == 1
    assert result["evidence"]["repeated_subtree"]["after_max_starts"] == 1
    assert result["evidence"]["set_operation_barrier"]["operations"] == ["SORT UNIQUE", "UNION-ALL"]
    assert result["evidence"]["anti_consumer"]["operation"] == "NESTED LOOPS ANTI"


def test_plan_hash_change_alone_never_makes_failed_plan_pass():
    changed_hash_same_shape = DISTINCT_MERGED.replace("Plan hash value: 1663017477", "Plan hash value: 999999999")

    result = verify_optimizer_intent(
        BEFORE,
        changed_hash_same_shape,
        customer_strategy("NOT_EXISTS_DISTINCT_KEY_ANTI"),
    )

    assert result["plan_hash_changed"] is True
    assert result["status"] == "REJECTED"
    assert result["verdict_reason"] == "OPTIMIZER_INTENT_NOT_MET"


def test_missing_or_ambiguous_required_nodes_fail_closed():
    strategy = customer_strategy("NOT_EXISTS_UNION_DISTINCT_BARRIER")
    missing = verify_optimizer_intent(BEFORE, "Plan hash value: 101251183", strategy)
    ambiguous_plan = UNION_BARRIER.replace(
        "|  43 |             VIEW                              | VIF_WHOLESALE_S   |      0 |",
        "|  43 |             VIEW                              | VIF_WHOLESALE_S   |      1 |",
    )
    ambiguous = verify_optimizer_intent(BEFORE, ambiguous_plan, strategy)

    for result in (missing, ambiguous):
        assert result["status"] == "BLOCKED"
        assert result["verdict_reason"] == "INSUFFICIENT_PLAN_EVIDENCE"
        assert result["allow_downstream_evaluation"] is False
    assert "TARGET_PLAN_NODE_MISSING" in missing["reason_codes"]
    assert "TARGET_PLAN_NODE_AMBIGUOUS" in ambiguous["reason_codes"]


def evidence_runs(elapsed: int, buffers: int) -> list[dict]:
    return [{
        "status": "COMPLETED",
        "last_elapsed_time_us": elapsed,
        "last_cr_buffer_gets": buffers,
        "row_count": 100,
        "last_output_rows": 100,
        "result_digest": "same-result",
    }]


def test_optimizer_rejection_blocks_digest_and_performance_evaluation_first():
    intent = verify_optimizer_intent(
        BEFORE,
        DISTINCT_MERGED,
        customer_strategy("NOT_EXISTS_DISTINCT_KEY_ANTI"),
    )

    result = evaluate_candidate_after_optimizer_intent(
        intent,
        evidence_runs(120_000_000, 9_000_000),
        evidence_runs(1_000_000, 100_000),
        "OLTP",
    )

    assert result["status"] == "BLOCKED"
    assert result["verdict_reason"] == "OPTIMIZER_INTENT_NOT_MET"
    assert result["candidate_evaluation_allowed"] is False
    assert result["digest_evaluated"] is False
    assert result["performance_evaluated"] is False
    assert result["semantic_equivalent"] is False
    assert "결과 동등성/성능 판정 전에 거절" in result["report_reason_ko"]
    assert classify_failure({"candidate_generated": True, **result}) == "OPTIMIZER_INTENT_NOT_MET"

    normalized = normalize_result(
        {"sample_id": "asta-awr-01", "mode": "C", "candidate_generated": True, "comparison": result},
        {"asta-awr-01": "OLTP"},
        "phase4",
    )
    assert normalized["optimizer_intent_verdict"] == "OPTIMIZER_INTENT_NOT_MET"
    assert normalized["candidate_evaluation_allowed"] is False
    assert normalized["failure_category"] == "OPTIMIZER_INTENT_NOT_MET"


def test_verified_intent_allows_existing_digest_and_performance_contract():
    intent = verify_optimizer_intent(
        BEFORE,
        UNION_BARRIER,
        customer_strategy("NOT_EXISTS_UNION_DISTINCT_BARRIER"),
    )

    result = evaluate_candidate_after_optimizer_intent(
        intent,
        evidence_runs(120_000_000, 9_000_000),
        evidence_runs(1_641_880, 1_079_324),
        "OLTP",
    )

    assert result["status"] == "EVALUATED"
    assert result["optimizer_intent_verdict"] == "OPTIMIZER_INTENT_VERIFIED"
    assert result["candidate_evaluation_allowed"] is True
    assert result["digest_evaluated"] is True
    assert result["performance_evaluated"] is True
    assert result["semantic_equivalent"] is True
    assert result["latency_guard_passed"] is True
