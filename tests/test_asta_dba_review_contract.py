from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _section(text: str, start: str, end: str) -> str:
    begin = text.index(start)
    return text[begin:text.index(end, begin)]


def test_dba_review_is_built_from_current_run_evidence_not_fixed_boilerplate():
    report = (ROOT / "db/adb/asta_report_pkg.sql").read_text(encoding="utf-8")
    assert "PROCEDURE append_dba_review(" in report
    helper = _section(report, "PROCEDURE append_dba_review(", "END append_dba_review;")

    for path in (
        "$.advisor_requested",
        "$.advisor.status",
        "$.advisor.report",
        "$.verdict",
        "$.verdict_reason",
        "$.equivalence_status",
        "$.workload_type",
        "$.primary_metric",
        "$.before_elapsed_time_us",
        "$.after_elapsed_time_us",
        "$.before_buffer_gets",
        "$.after_buffer_gets",
        "$.before_disk_reads",
        "$.after_disk_reads",
        "$.before_row_count",
        "$.after_row_count",
        "$.before_output_rows",
        "$.after_output_rows",
        "$.object_info.table_stats[*]",
        "$.indexes[*]",
        "$.stale_stats",
        "$.last_analyzed",
    ):
        assert path in helper

    for recommendation in ("SQL PROFILE", "INDEX", "STATISTICS", "PLAN BASELINE"):
        assert recommendation in helper
    for state in ("FAILED", "TIMEOUT", "SKIPPED", "COMPLETED"):
        assert state in helper
    for safeguard in ("자동 적용하지 않았음", "DBA 승인", "rollback", "적용 금지"):
        assert safeguard in helper

    assert "DBMS_LOB.SUBSTR(l_advisor_report, 8000, 1)" in helper
    assert "clob_app_clob(p_out, l_advisor_report)" not in helper
    assert "append_dba_review(l_report, p_source_evidence_json, p_comparison_json);" not in report
    assert "튜닝 SQL 적용 전 결과 동일성(row_count/output_rows)" not in report
    assert "elapsed_time이 악화되었지만 buffer_gets가 개선된 경우" not in report


def test_dba_review_prompt_requires_evidence_specific_approval_impact_and_rollback():
    llm = (ROOT / "db/adb/asta_llm_pkg.sql").read_text(encoding="utf-8")
    prompt = _section(llm, "Compare before and after SQL evidence", "Compact before/after package JSON")
    for phrase in (
        "generic boilerplate",
        "advisor status/recommendation type",
        "comparison verdict/equivalence/actual metrics",
        "object stats/index evidence",
        "impact scope",
        "approval",
        "rollback",
        "automatic application was not performed",
        "Do not dump the raw Advisor report",
    ):
        assert phrase in prompt


def test_dba_review_oracle19c_shapes_and_private_routine_order_are_compile_safe():
    report = (ROOT / "db/adb/asta_report_pkg.sql").read_text(encoding="utf-8")
    helper = _section(report, "PROCEDURE append_dba_review(", "END append_dba_review;")

    # JSON_TABLE nested columns are outer-joined to their parent in Oracle 19c;
    # COUNT(*) would count a null child row for a table with no indexes.
    assert "SELECT COUNT(index_name)" in helper
    assert "SELECT COUNT(*)\n      INTO   l_index_count" not in helper

    # PL/SQL BOOLEAN remains private procedural state and is assigned a Boolean
    # expression directly; it is never projected through SQL or JSON_TABLE.
    assert "l_has_profile        BOOLEAN := FALSE;" in helper
    assert "l_has_profile := INSTR(l_upper_excerpt, 'SQL PROFILE') > 0;" in helper
    assert "REGEXP_LIKE" not in helper

    # Existing Oracle 19c package idioms and routine ordering are preserved.
    assert "JSON_VALUE(p_source_evidence_json, '$.advisor.report' RETURNING CLOB NULL ON ERROR)" in helper
    assert "FROM   JSON_TABLE(p_source_evidence_json, '$.object_info.table_stats[*]'" in helper
    assert "COLUMNS(NESTED PATH '$.indexes[*]'" in helper
    assert report.index("FUNCTION json_vc(") < report.index("PROCEDURE append_dba_review(")
    assert report.index("PROCEDURE append_dba_review(") < report.index("FUNCTION build_report(", report.index("PACKAGE BODY"))
