"""XPLAN 실측치와 트리 관계 기반 지배 병목 랭킹 회귀 테스트."""

from pathlib import Path

from tools.asta_quality_agent import parse_xplan_operations, rank_xplan_bottlenecks


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/asta_customer_01_dominant_xplan.txt"


def customer_xplan() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def test_parse_xplan_preserves_metrics_and_parent_child_relationships():
    nodes = {node["id"]: node for node in parse_xplan_operations(customer_xplan())}

    assert nodes[28]["operation"] == "VIEW"
    assert nodes[28]["object_name"] == "VIF_WHOLESALE_S"
    assert nodes[28]["starts"] == 845
    assert nodes[28]["a_time_us"] == 124_900_000
    assert nodes[28]["buffers"] == 8_090_000
    assert nodes[28]["parent_id"] == 16
    assert nodes[28]["child_ids"] == [29]
    assert nodes[38]["parent_id"] == 34
    assert nodes[38]["actual_rows"] == 940_000_000


def test_customer_correlated_subtree_is_ranked_first_with_structured_evidence():
    result = rank_xplan_bottlenecks(customer_xplan(), limit=5)

    assert result["status"] == "COMPLETED"
    assert result["metric_source"] == "DBMS_XPLAN_ALLSTATS_LAST"
    assert result["dominant"]["node_id"] == 28
    assert result["dominant"]["parent_id"] == 16
    assert result["dominant"]["operation"] == "VIEW"
    assert result["dominant"]["object_name"] == "VIF_WHOLESALE_S"
    assert result["dominant"]["evidence"]["starts"] == 845
    assert result["dominant"]["evidence"]["buffers"] == 8_090_000
    assert result["dominant"]["evidence"]["subtree_max_actual_rows"] == 940_000_000
    assert "REPEATED_SUBTREE_ROOT" in result["dominant"]["reason_codes"]
    assert "DOMINANT_BUFFERS" in result["dominant"]["reason_codes"]
    assert "DOMINANT_A_TIME" in result["dominant"]["reason_codes"]


def test_ranking_is_deterministic_and_exposes_secondary_repeated_work():
    first = rank_xplan_bottlenecks(customer_xplan(), limit=10)
    second = rank_xplan_bottlenecks(customer_xplan(), limit=10)

    assert first == second
    assert [item["rank"] for item in first["rankings"]] == list(range(1, len(first["rankings"]) + 1))
    assert any(item["node_id"] == 70 and "REPEATED_WORK" in item["reason_codes"] for item in first["rankings"])


def test_missing_allstats_rows_returns_explicit_insufficient_evidence():
    result = rank_xplan_bottlenecks("Plan hash value: 1\nPredicate Information:")

    assert result == {
        "status": "INSUFFICIENT_EVIDENCE",
        "reason_code": "XPLAN_ALLSTATS_ROWS_NOT_FOUND",
        "metric_source": "DBMS_XPLAN_ALLSTATS_LAST",
        "rankings": [],
        "dominant": None,
    }
