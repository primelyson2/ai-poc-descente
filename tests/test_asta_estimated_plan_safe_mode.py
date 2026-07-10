from pathlib import Path

from app.routers.asta_proxy import _coerce_payload


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_proxy_defaults_to_no_source_execution_and_accepts_explicit_opt_in():
    assert _coerce_payload({"sql": "select 1 from dual"})["execute_source_sql"] is False
    assert _coerce_payload({"sql": "select 1 from dual", "execute_source_sql": True})["execute_source_sql"] is True
    assert _coerce_payload({"sql": "select 1 from dual", "options": {"execute_source_sql": "yes"}})["execute_source_sql"] is True


def test_ui_exposes_unchecked_explicit_source_execution_checkbox():
    ui = read("static/js/extensions/tuning_assistant.js")
    assert 'id="asta-execute-source-sql" type="checkbox"' in ui
    assert 'id="asta-execute-source-sql" type="checkbox" checked' not in ui
    assert ui.count("execute_source_sql: Boolean(executeSourceSqlInput?.checked)") == 2
    assert "EXPLAIN PLAN 예상 실행계획과 객체 통계·인덱스만 수집" in ui


def test_source_estimated_plan_path_never_opens_or_fetches_input_select():
    source = read("db/source/asta_source_pkg.sql")
    start = source.index("FUNCTION run_estimated_evidence(")
    body = source[start:source.index("END run_estimated_evidence;", start)]
    assert "EXPLAIN PLAN SET STATEMENT_ID" in body
    assert "DBMS_XPLAN.DISPLAY('PLAN_TABLE'" in body
    assert "p_plan_table_owner" in body
    assert "l_plan_table_name := 'PLAN_TABLE'" in body
    assert "ALTER SESSION SET CURRENT_SCHEMA" in body
    assert "collect_estimated_object_info" in body
    assert "source_sql_executed\":false" in body
    assert "EXECUTE IMMEDIATE l_explain_sql" in body
    assert "OPEN " not in body
    assert "FETCH " not in body
    assert "build_exec_sql" not in body
    assert "build_full_count_sql" not in body
    assert "build_full_digest_sql" not in body
    assert "run_advisor_opt" not in body


def test_adb_safe_mode_uses_estimated_plan_for_original_and_candidate_and_skips_full_gate():
    main = read("db/adb/asta_pkg.sql")
    assert "JSON_VALUE(p_body_json, '$.execute_source_sql'" in main
    assert "l_execute_source_sql  VARCHAR2(1) := 'N'" in main
    assert "l_candidate_result_mode := CASE" in main
    assert "WHEN l_execute_source_sql = 'N' THEN 'ESTIMATED_PLAN'" in main
    assert "l_candidate_screen_reason := 'ESTIMATED_PLAN_ONLY_RUNTIME_NOT_EXECUTED'" in main
    assert '"screen_mode":' in main
    assert '"source_sql_executed":' in main


def test_estimated_plan_candidate_uses_analysis_only_api_contract():
    main = read("db/adb/asta_pkg.sql")
    report = read("db/adb/asta_report_pkg.sql")

    estimated_start = main.index("ELSIF l_candidate_screen_rejected = 'Y' AND l_execute_source_sql = 'N' THEN")
    plan_only_start = main.index("ELSIF l_candidate_screen_rejected = 'Y' THEN", estimated_start)
    estimated_branch = main[estimated_start:plan_only_start]
    assert '"verdict":"ANALYSIS_ONLY"' in estimated_branch
    assert '"analysis_mode":"ESTIMATED_PLAN_ONLY"' in estimated_branch
    assert '"execution_mode":"SOURCE_SQL_NOT_EXECUTED"' in estimated_branch
    assert '"source_runtime_metrics_status":"NOT_MEASURED"' in estimated_branch
    assert '"before_after_xplan_status":"NOT_AVAILABLE"' in estimated_branch
    assert '"repeat_performance_status":"NOT_MEASURED"' in estimated_branch
    assert '"verdict":"NOT_IMPROVED"' not in estimated_branch

    response_start = report.index("FUNCTION build_response_json(")
    response = report[response_start:report.index("END build_response_json;", response_start)]
    for field in (
        '"analysis_mode":',
        '"execution_mode":',
        '"source_sql_executed":',
        '"runtime_verification_status":',
    ):
        assert field in response


def test_llm_and_report_explicitly_treat_estimated_plan_as_unmeasured():
    llm = read("db/adb/asta_llm_pkg.sql")
    report = read("db/adb/asta_report_pkg.sql")
    assert "the Source SQL was NOT executed" in llm
    assert "Do not claim measured A-Time, Buffers, Starts" in llm
    assert "ESTIMATED_PLAN_ONLY_RUNTIME_NOT_EXECUTED" in report
    assert "Source SQL 미실행 안전 모드" in report
    assert "예상 Plan 기반 튜닝 후보 SQL — 실행·동등성 미검증" in report


def test_estimated_plan_candidate_report_does_not_claim_runtime_non_improvement():
    report = read("db/adb/asta_report_pkg.sql")
    start = report.index("FUNCTION build_report(\n")
    build = report[start:report.index("END build_report;", start)]
    stage_start = report.index("PROCEDURE append_stage_check(")
    stage_check = report[stage_start:report.index("END append_stage_check;", stage_start)]

    assert build.index("IF l_estimated_candidate THEN") < build.index("ELSIF l_verdict = 'NOT_IMPROVED'")
    assert "튜닝 후보 SQL이 생성되었습니다. Source DB에서는 원본·후보 SQL을 실행하지 않았으므로 실제 성능, 결과 동등성, 채택 여부는 판정하지 않았습니다." in build
    assert "ANALYSIS_ONLY" in build
    assert "튜닝 후보 제안/분석 완료, 성능 개선 여부 미검증" in build
    assert "확보된 근거: 정적 SQL 분석, EXPLAIN PLAN 예상계획, 객체 통계·인덱스 정보, Vector/LLM 분석 결과" in build
    assert "미확보 근거: Source runtime metrics, Before/After 실제 XPLAN, result equivalence, 반복 성능 측정" in build
    assert "실행시간: 미측정 (Source DB에서 원본·후보 SQL 미실행)" in build
    assert "예상 병목(EXPLAIN PLAN 기반)" in build
    assert "Buffer Gets, Disk Reads, A-Time, Starts는 실측되지 않았습니다." in build
    assert "실제 개선 판정을 수행하지 않았습니다." in build
    assert "표의 DONE은 해당 단계 완료를 뜻하며 업무 SQL 실행 완료를 뜻하지 않습니다." in build
    assert "Source SQL 미실행; 원본 EXPLAIN PLAN 예상계획 및 객체정보 수집" in stage_check
    assert "후보 SQL 미실행; 후보 EXPLAIN PLAN 예상계획 수집" in stage_check
    assert "실제 성능·결과 동등성·채택 여부 미평가" in stage_check


def test_estimated_plan_report_is_routed_to_ui_tabs_and_report_includes_run_id():
    tabs = read("static/js/extensions/asta_report_tabs.js")
    report = read("db/adb/asta_report_pkg.sql")
    assert '[2, "튜닝전 예상 plan", "before"]' in tabs
    assert '[2, "튜닝후 예상 plan", "after"]' in tabs
    assert "'- Run ID: `' || p_run_id || '`'" in report


def test_ui_distinguishes_analysis_only_from_rejected_failure():
    ui = read("static/js/extensions/tuning_assistant.js")
    tabs = read("static/js/extensions/asta_report_tabs.js")

    assert 'function isEstimatedPlanAnalysisOnly(data)' in ui
    assert 'verdict === "ANALYSIS_ONLY"' in ui
    assert 'return "ACCEPTED"' in ui[ui.index('function astaWorkflowOutcome(data)'):ui.index('function redactAstaReportForUi(report)')]
    assert "ASTA 미실행 분석이 완료되었습니다. 성능 개선 여부는 미검증입니다." in ui
    assert "미실행 분석 모드" in ui
    assert "성능·동등성 미검증" in ui
    assert "ANALYSIS_ONLY" in tabs
    assert "튜닝 후보 제안/분석 완료, 성능 개선 여부 미검증" in tabs
