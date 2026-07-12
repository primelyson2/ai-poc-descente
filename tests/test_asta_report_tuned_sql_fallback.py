"""IMPROVED reports must retain stored tuned SQL when LLM artifact is incomplete."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_report_uses_persisted_tuned_sql_only_for_improved_fallback():
    report = (ROOT / "db/adb/asta_report_pkg.sql").read_text()
    section = report.split("FUNCTION effective_candidate_sql(", 1)[1].split("END effective_candidate_sql;", 1)[0]
    assert "json_vc(p_comparison_json, '$.verdict', '') = 'IMPROVED'" in section
    assert "SELECT DBMS_LOB.SUBSTR(tuned_sql, 32767, 1)" in section
    assert "FROM asta_runs" in section
    assert report.count("effective_candidate_sql(p_run_id, p_llm_json, p_comparison_json)") == 2


def test_improved_report_and_response_do_not_require_legacy_llm_candidate_field():
    report = (ROOT / "db/adb/asta_report_pkg.sql").read_text()
    build_report = report.split("FUNCTION build_report(", 1)[1].split("END build_report;", 1)[0]
    response = report.split("FUNCTION build_response_json(", 1)[1].split("END build_response_json;", 1)[0]
    adopted = build_report.split("l_candidate_adopted :=", 1)[1].split(";", 1)[0]
    response_gate = response.split("-- Keep rejected SQL only in the raw LLM audit artifact.", 1)[1].split("DBMS_LOB.CREATETEMPORARY", 1)[0]

    assert "l_verdict = 'IMPROVED'" in adopted
    assert "l_candidate_sql_vc IS NOT NULL" in adopted
    assert "llm_has_improved_sql" not in adopted
    assert "IF l_verdict = 'IMPROVED' THEN" in response_gate
    assert "effective_candidate_sql(p_run_id, p_llm_json, p_comparison_json)" in response_gate
    assert "llm_has_improved_sql" not in response_gate


def test_report_conclusion_always_exposes_machine_readable_verdict_for_ui_help():
    report = (ROOT / "db/adb/asta_report_pkg.sql").read_text()
    build_report = report.split("FUNCTION build_report(", 1)[1].split("END build_report;", 1)[0]

    assert "'- 최종 판정: `' || l_verdict || '`'" in build_report
    assert build_report.index("'- 최종 판정: `' || l_verdict") < build_report.index("'- 실행 유형: '")


def test_pipeline_persists_tuned_sql_before_report_assembly():
    main = (ROOT / "db/adb/asta_pkg.sql").read_text()
    update = "UPDATE asta_runs SET tuned_sql = l_tuned_sql WHERE run_id = l_run_id;"
    first_report = main.index("l_report_markdown := asta_report_pkg.build_report(")
    assert main.index(update) < first_report
