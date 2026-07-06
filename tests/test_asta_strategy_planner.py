"""단계 2 link 결과를 입력으로 받는 결정론적 단계 3 전략 planner 계약."""

from pathlib import Path

from tools.asta_quality_agent import link_dominant_plan_node_to_sql
from tools.asta_strategy_planner import plan_tuning_strategies


ROOT = Path(__file__).resolve().parents[1]
PLAN = (ROOT / "tests/fixtures/asta_customer_01_dominant_xplan.txt").read_text(encoding="utf-8")
CUSTOMER_SQL = (ROOT / "tests/fixtures/asta_customer_01_style_not_exists.sql").read_text(encoding="utf-8")


def linked(pattern_type: str, construct: str = "INLINE_VIEW") -> dict:
    return {
        "status": "LINKED",
        "query_block": "MAIN",
        "cte_name": None,
        "construct": construct,
        "pattern_type": pattern_type,
        "referenced_object": "DSNT.FACT_TABLE",
        "referenced_alias": "F",
        "source_span": {"start_offset": 10, "end_offset": 80, "start_line": 1, "start_column": 11,
                        "end_line": 1, "end_column": 81},
        "confidence": 0.95,
        "reason_codes": ["UNIQUE_OBJECT_STRUCTURE_MATCH"],
        "rewrite_allowed": True,
    }


def test_customer_not_exists_produces_three_ordered_structured_strategies():
    link = link_dominant_plan_node_to_sql(CUSTOMER_SQL, PLAN)

    result = plan_tuning_strategies(link)

    assert result["status"] == "PLANNED"
    assert result["pattern_type"] == "CORRELATED_NOT_EXISTS"
    assert [item["strategy_id"] for item in result["strategies"]] == [
        "NOT_EXISTS_DISTINCT_KEY_ANTI",
        "NOT_EXISTS_GROUP_BY_KEY_ANTI",
        "NOT_EXISTS_UNION_DISTINCT_BARRIER",
    ]
    for priority, item in enumerate(result["strategies"], start=1):
        assert item["priority"] == priority
        assert item["target"] == {
            "source_span": link["source_span"],
            "query_block": "STYLE",
            "object": "DSNT.VIF_WHOLESALE_S",
        }
        assert item["transformation_summary"]
        assert item["expected_plan_effect"]["producer_starts"] == 1
        assert item["semantic_constraints"]
        assert item["prerequisites"]
        assert item["risk"]
        assert item["blocked_reason"] is None
        assert item["executable"] is True
        assert "sql" not in item
        assert "candidate_sql" not in item
    assert result["sql_execution_allowed"] is False


def test_distinct_merge_failure_skips_repeat_and_promotes_barrier_first():
    link = link_dominant_plan_node_to_sql(CUSTOMER_SQL, PLAN)
    feedback = [{
        "strategy_id": "NOT_EXISTS_DISTINCT_KEY_ANTI",
        "reason_code": "DISTINCT_CTE_MERGED",
    }]

    result = plan_tuning_strategies(link, failure_feedback=feedback)
    ids = [item["strategy_id"] for item in result["strategies"]]

    assert ids[0] == "NOT_EXISTS_UNION_DISTINCT_BARRIER"
    assert "NOT_EXISTS_DISTINCT_KEY_ANTI" not in ids
    assert result["applied_feedback"] == feedback


def test_blocked_link_returns_zero_candidates_with_link_reasons():
    blocked = {
        "status": "BLOCKED", "rewrite_allowed": False, "confidence": 0.0,
        "reason_codes": ["AMBIGUOUS_SQL_FRAGMENT"],
    }

    result = plan_tuning_strategies(blocked)

    assert result["status"] == "BLOCKED"
    assert result["strategies"] == []
    assert result["blocked_reason"] == "LINK_REWRITE_NOT_ALLOWED"
    assert result["reason_codes"] == ["AMBIGUOUS_SQL_FRAGMENT"]


def test_unsupported_construct_is_explicitly_blocked():
    result = plan_tuning_strategies(linked("UNSUPPORTED_PATTERN", "INLINE_VIEW"))

    assert result["status"] == "BLOCKED"
    assert result["strategies"] == []
    assert result["blocked_reason"] == "UNSUPPORTED_CONSTRUCT"
    assert result["reason_codes"] == ["UNSUPPORTED_PATTERN:INLINE_VIEW"]


def test_same_link_and_feedback_produce_identical_plan():
    link = link_dominant_plan_node_to_sql(CUSTOMER_SQL, PLAN)
    feedback = [{"strategy_id": "NOT_EXISTS_DISTINCT_KEY_ANTI", "reason_code": "DISTINCT_CTE_MERGED"}]
    original_link = dict(link)
    original_feedback = [dict(item) for item in feedback]

    assert plan_tuning_strategies(link, failure_feedback=feedback) == plan_tuning_strategies(
        link, failure_feedback=feedback
    )
    assert link == original_link
    assert feedback == original_feedback


def test_scalar_aggregate_selects_scalar_preaggregation_family():
    result = plan_tuning_strategies(linked("SCALAR_AGGREGATE", "SCALAR_SUBQUERY"))

    assert result["status"] == "PLANNED"
    assert result["strategy_family"] == "SCALAR_AGGREGATE"
    assert all(item["strategy_id"].startswith("SCALAR_AGG_") for item in result["strategies"])


def test_correlated_exists_selects_semiexistence_family():
    exists_link = linked("CORRELATED_EXISTS", "EXISTS")
    exists_link["correlated_outer_aliases"] = ["A"]

    result = plan_tuning_strategies(exists_link)

    assert result["status"] == "PLANNED"
    assert result["strategy_family"] == "CORRELATED_EXISTS"
    assert all(item["expected_plan_effect"]["consumer"] == "SEMI_EXISTENCE" for item in result["strategies"])


def test_repeated_fact_scan_selects_single_pass_fact_family():
    result = plan_tuning_strategies(linked("REPEATED_FACT_SCAN"))

    assert result["status"] == "PLANNED"
    assert result["strategy_family"] == "REPEATED_FACT_SCAN"
    assert result["strategies"][0]["expected_plan_effect"]["fact_scan_starts"] == 1


def test_composite_in_selects_keyset_semijoin_family():
    result = plan_tuning_strategies(linked("COMPOSITE_IN", "IN_SUBQUERY"))

    assert result["status"] == "PLANNED"
    assert result["strategy_family"] == "COMPOSITE_IN"
    assert result["strategies"][0]["expected_plan_effect"]["composite_key_producer_starts"] == 1
