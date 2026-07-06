"""단계 1 dominant plan node와 SQL 구조의 안전한 연결 계약."""

from pathlib import Path

from tools.asta_quality_agent import link_dominant_plan_node_to_sql


ROOT = Path(__file__).resolve().parents[1]
PLAN = (ROOT / "tests/fixtures/asta_customer_01_dominant_xplan.txt").read_text(encoding="utf-8")
CUSTOMER_SQL = (ROOT / "tests/fixtures/asta_customer_01_style_not_exists.sql").read_text(encoding="utf-8")


def test_customer_dominant_view_links_to_style_correlated_not_exists():
    result = link_dominant_plan_node_to_sql(CUSTOMER_SQL, PLAN)

    assert result["status"] == "LINKED"
    assert result["dominant_plan_node"]["node_id"] == 28
    assert result["query_block"] == "STYLE"
    assert result["cte_name"] == "STYLE"
    assert result["construct"] == "NOT EXISTS"
    assert result["referenced_object"] == "DSNT.VIF_WHOLESALE_S"
    assert result["referenced_alias"] == "VWS"
    assert result["immediate_consumer"]["construct"] == "CTE_FILTER"
    assert result["immediate_consumer"]["query_block"] == "STYLE"
    assert result["correlated_outer_aliases"] == ["A"]
    assert result["predicate_evidence"]["aliases"] == ["A", "VWS"]
    assert result["source_span"]["start_offset"] < result["source_span"]["end_offset"]
    fragment = CUSTOMER_SQL[result["source_span"]["start_offset"]:result["source_span"]["end_offset"]]
    assert fragment.lstrip().startswith("NOT EXISTS")
    assert "FROM DSNT.VIF_WHOLESALE_S VWS" in fragment
    assert result["confidence"] >= 0.95
    assert "XPLAN_PREDICATE_ALIAS_MATCH" in result["reason_codes"]
    assert result["rewrite_allowed"] is True


def test_duplicate_object_subqueries_are_blocked_as_ambiguous():
    sql = """
    SELECT * FROM DSNT.TGP_STYLE_M A
     WHERE NOT EXISTS (SELECT 1 FROM DSNT.VIF_WHOLESALE_S VWS WHERE VWS.STYLE_CD=A.STYLE_CD)
       AND NOT EXISTS (SELECT 1 FROM DSNT.VIF_WHOLESALE_S VWS2 WHERE VWS2.STYLE_CD=A.STYLE_CD)
    """

    result = link_dominant_plan_node_to_sql(sql, PLAN)

    assert result["status"] == "BLOCKED"
    assert result["confidence"] == 0.0
    assert result["reason_codes"] == ["AMBIGUOUS_SQL_FRAGMENT"]
    assert result["candidate_count"] == 2
    assert result["rewrite_allowed"] is False


def test_keywords_and_objects_inside_comments_and_strings_are_not_candidates():
    sql = """
    WITH STYLE AS (
      SELECT A.STYLE_CD AS "NOT", A.COMP_CD AS "FROM"
        FROM DSNT.TGP_STYLE_M A
       WHERE 'NOT EXISTS (SELECT 1 FROM DSNT.VIF_WHOLESALE_S FAKE)' IS NOT NULL
         /* FROM DSNT.VIF_WHOLESALE_S COMMENT_ALIAS WHERE EXISTS (SELECT 1) */
         AND NOT EXISTS (
           SELECT 1 FROM DSNT.VIF_WHOLESALE_S VWS
            WHERE VWS.STYLE_CD = A.STYLE_CD
         )
    ) SELECT * FROM STYLE
    """

    result = link_dominant_plan_node_to_sql(sql, PLAN)

    assert result["status"] == "LINKED"
    assert result["referenced_alias"] == "VWS"
    assert result["candidate_count"] == 1
    assert result["rewrite_allowed"] is True


def test_missing_object_evidence_blocks_rewrite_without_guessing():
    result = link_dominant_plan_node_to_sql(
        "SELECT * FROM DSNT.TGP_STYLE_M A WHERE A.COMP_CD = '01'", PLAN
    )

    assert result["status"] == "BLOCKED"
    assert result["confidence"] == 0.0
    assert result["reason_codes"] == ["PLAN_OBJECT_NOT_FOUND_IN_SQL"]
    assert result["rewrite_allowed"] is False


def test_optimizer_alias_mismatch_blocks_unique_object_match():
    transformed_plan = PLAN.replace('"VWS"."STYLE_CD"="A"."STYLE_CD"', '"PX"."STYLE_CD"="QX"."STYLE_CD"')

    result = link_dominant_plan_node_to_sql(CUSTOMER_SQL, transformed_plan)

    assert result["status"] == "BLOCKED"
    assert result["confidence"] < 0.8
    assert "XPLAN_ALIAS_MISMATCH" in result["reason_codes"]
    assert result["rewrite_allowed"] is False


def test_unique_object_without_predicate_evidence_links_with_limited_confidence():
    plan_without_predicates = PLAN.split("Predicate Information", 1)[0]

    result = link_dominant_plan_node_to_sql(CUSTOMER_SQL, plan_without_predicates)

    assert result["status"] == "LINKED"
    assert 0.8 <= result["confidence"] < 0.95
    assert "UNIQUE_OBJECT_STRUCTURE_MATCH" in result["reason_codes"]
    assert "XPLAN_PREDICATE_UNAVAILABLE" in result["reason_codes"]
    assert result["rewrite_allowed"] is True


def test_scalar_subquery_and_inline_view_constructs_are_classified():
    no_predicate_plan = PLAN.split("Predicate Information", 1)[0]
    scalar = link_dominant_plan_node_to_sql(
        "SELECT (SELECT COUNT(*) FROM DSNT.VIF_WHOLESALE_S VWS) AS CNT FROM DUAL",
        no_predicate_plan,
    )
    inline = link_dominant_plan_node_to_sql(
        "SELECT X.STYLE_CD FROM (SELECT VWS.STYLE_CD FROM DSNT.VIF_WHOLESALE_S VWS) X",
        no_predicate_plan,
    )

    assert scalar["construct"] == "SCALAR_SUBQUERY"
    assert scalar["query_block"] == "MAIN"
    assert inline["construct"] == "INLINE_VIEW"
    assert inline["query_block"] == "MAIN"


def test_same_inputs_produce_identical_link_result():
    assert link_dominant_plan_node_to_sql(CUSTOMER_SQL, PLAN) == link_dominant_plan_node_to_sql(
        CUSTOMER_SQL, PLAN
    )
