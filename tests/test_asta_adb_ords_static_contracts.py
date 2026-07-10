"""작성자: 도상훈
파일 용도: ASTA ORDS/ADB 마이그레이션 계약과 회귀 조건을 정적/단위 테스트로 검증한다."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    """ASTA 내부 처리 보조 함수: read."""
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_source_helper_reports_repeat_count_and_uses_latest_marker_cursor():
    """ASTA 계약/회귀 조건을 검증한다: source helper reports repeat count and uses lamarker cursor."""
    src = _read("db/source/asta_source_pkg.sql")
    assert ',"repeat_count":' in src
    assert ',"repeat_policy":' in src
    assert ',"advisor_requested":' in src
    assert ',"sqltune_time_limit_sec":' in src
    assert "FUNCTION normalize_repeat_policy(p_repeat_policy IN VARCHAR2) RETURN VARCHAR2" in src
    assert "FUNCTION normalize_run_advisor(p_run_advisor IN VARCHAR2) RETURN VARCHAR2" in src
    assert "FUNCTION normalize_sqltune_time_sec(p_sqltune_time_sec IN NUMBER) RETURN PLS_INTEGER" in src
    assert "DBMS_LOB.SUBSTR(l_advisor_report, 13, 1) = 'SQLTUNE_ERROR'" in src
    assert '"contract_version":"asta.v1"' in src
    assert '"execution_boundary":"SOURCE_BASEDB_DBLINK_ONLY"' in src
    assert '"timing_scope":"repeat_loop_total"' in src
    assert '"elapsed_wall_ms_per_exec":' in src
    assert "ORDER  BY last_active_time DESC NULLS LAST, child_number DESC" in src
    assert "WHERE  ROWNUM = 1" in src


def test_source_and_adb_guards_reject_sqlplus_slash_terminator():
    """ASTA 계약/회귀 조건을 검증한다: source and adb guards reject sqlplus slash terminator."""
    for rel_path in ["db/source/asta_source_pkg.sql", "db/adb/asta_sql_guard_pkg.sql"]:
        src = _read(rel_path)
        assert "Statement terminator is not allowed" in src
        assert "SQL*Plus slash terminator is not allowed" in src
        assert "REGEXP_LIKE(l_guard, '(^|' || CHR(10) || ')[[:space:]]*/[[:space:]]*($|' || CHR(10) || ')')" in src
    adb_guard = _read("db/adb/asta_sql_guard_pkg.sql")
    assert '"contract_version":"asta.v1"' in adb_guard
    assert '"execution_boundary":"ADB_SQL_GUARD_PLSQL"' in adb_guard


def test_bridge_and_llm_validate_sql_before_runtime_boundaries():
    """ASTA 계약/회귀 조건을 검증한다: bridge and llm validate sql before runtime boundaries."""
    bridge = _read("db/adb/asta_source_bridge_pkg.sql")
    guard_pos = bridge.index("asta_sql_guard_pkg.assert_safe_select(p_sql)")
    stmt_pos = bridge.index("l_stmt :=")
    assert guard_pos < stmt_pos
    for fragment in [
        '"execution_boundary":"ADB_SOURCE_BRIDGE_DBLINK"',
        '"connection_source":"ASTA_SOURCE_CONNECTIONS"',
        '"contract_version":"asta.v1"',
        '"status":"COMPLETED","code":"SOURCE_CONNECTION"',
        "FUNCTION normalized_fetch_rows(p_fetch_rows IN NUMBER) RETURN PLS_INTEGER",
        "FUNCTION normalized_repeat_policy(p_repeat_policy IN VARCHAR2) RETURN VARCHAR2",
        "FUNCTION normalized_run_advisor(p_run_advisor IN VARCHAR2) RETURN VARCHAR2",
        "FUNCTION normalized_sqltune_time_sec(p_sqltune_time_sec IN NUMBER) RETURN PLS_INTEGER",
        "l_fetch_rows := normalized_fetch_rows(p_fetch_rows)",
        "l_repeat_policy := normalized_repeat_policy(p_repeat_policy)",
        "l_run_advisor := normalized_run_advisor(p_run_advisor)",
        "l_sqltune_time_sec := normalized_sqltune_time_sec(p_sqltune_time_sec)",
    ]:
        assert fragment in bridge

    llm = _read("db/adb/asta_llm_pkg.sql")
    llm_guard_pos = llm.index("asta_sql_guard_pkg.assert_safe_select(p_sql)")
    prompt_pos = llm.index("l_prompt := build_tuning_prompt")
    cloud_ai_pos = llm.index("DBMS_CLOUD_AI.GENERATE")
    assert llm_guard_pos < prompt_pos < cloud_ai_pos
    assert "candidate_sql must be a single safe Oracle SELECT or WITH statement" in llm
    assert "Use only the supplied input for prompt mode" in llm
    assert llm.count("Return JSON only; do not wrap the response in Markdown fences.") == 3
    assert '"contract_version":"asta.v1"' in llm
    assert '"execution_boundary":"ADB_DBMS_CLOUD_AI"' in llm


def test_llm_prompt_modes_separate_sql_metrics_and_full_evidence():
    """A/B/C 실험은 후보 실행 경로를 유지하면서 LLM 입력 정보량만 변경한다."""
    llm = _read("db/adb/asta_llm_pkg.sql")
    assert "FUNCTION prompt_mode(p_context_json IN CLOB) RETURN VARCHAR2" in llm
    assert "'$.prompt_mode'" in llm
    assert "Prompt mode A: SQL text and user objective only" in llm
    assert "Prompt mode B: SQL plus compact runtime metrics only" in llm
    assert "Prompt mode C: current ASTA compact full evidence" in llm
    assert "compact_source_metrics(p_source_evidence_json)" in llm
    assert "compact_source_evidence(p_source_evidence_json)" in llm
    assert "compact_vector_evidence(p_vector_json)" in llm
    assert ',\"prompt_mode\":' in llm
    main = _read("db/adb/asta_pkg.sql")
    assert main.count("asta_llm_pkg.generate_sql_only_tuning(") == 1
    assert "l_sql_only_llm_json" not in main


def test_source_bridge_does_not_rollback_caller_owned_run_persistence():
    """ASTA 계약/회귀 조건을 검증한다: source bridge does not rollback caller owned run persistence."""
    bridge = _read("db/adb/asta_source_bridge_pkg.sql")
    source = _read("db/source/asta_source_pkg.sql")

    helper_call_pos = bridge.index("asta_source_pkg.run_evidence_store_proc@")
    chunk_read_pos = bridge.index("asta_source_pkg.get_result_chunk@")
    bridge_body = bridge[helper_call_pos:chunk_read_pos]
    assert not re.search(r"\bROLLBACK\s*;", bridge_body, re.IGNORECASE)
    assert not re.search(r"\bCOMMIT\s*;", bridge_body, re.IGNORECASE)
    assert "Source helper owns its storage transaction" in bridge

    body_pos = source.index("CREATE OR REPLACE PACKAGE BODY asta_source_pkg")
    store_pos = source.index("  FUNCTION run_evidence_store_vc", body_pos)
    commit_pos = source.index("COMMIT;", store_pos)
    proc_pos = source.index("  PROCEDURE run_evidence_store_proc", store_pos)
    assert store_pos < commit_pos < proc_pos


def test_source_bridge_uses_multibyte_safe_chunks_below_32k_boundary():
    """DB link VARCHAR2 chunks must stay far below 32KB bytes for Korean/escaped JSON."""
    bridge = _read("db/adb/asta_source_bridge_pkg.sql")
    source = _read("db/source/asta_source_pkg.sql")

    assert "l_chunk_size    PLS_INTEGER := 8000" in bridge
    assert "p_amount IN NUMBER DEFAULT 8000" in source
    assert "LEAST(GREATEST(NVL(p_amount, 8000), 1), 8000)" in source


def test_adb_smoke_verifies_analyze_run_persistence_endpoints():
    """ASTA 계약/회귀 조건을 검증한다: adb smoke verifies analyze run persistence endpoints."""
    smoke = _read("tools/asta_smoke_adb.py")
    assert "begin :out := asta_pkg.analyze_sql(:body); end;" in smoke
    assert "begin :out := asta_pkg.get_run(:run_id); end;" in smoke
    assert "begin :out := asta_pkg.get_progress(:run_id); end;" in smoke
    assert "begin :out := asta_pkg.get_report(:run_id); end;" in smoke
    assert "require_run_retrievable(out, run_id)" in smoke


def test_adb_report_lookup_escapes_large_markdown_without_small_varchar_buffer():
    """ASTA 계약/회귀 조건을 검증한다: adb report lookup escapes large markdown without small varchar buffer."""
    main = _read("db/adb/asta_pkg.sql")
    proc_pos = main.index("PROCEDURE clob_app_json_str")
    report_pos = main.index("FUNCTION get_report", proc_pos)
    escape_proc = main[proc_pos:report_pos]
    assert "l_chunk   VARCHAR2(32767)" in escape_proc
    assert "l_escaped VARCHAR2(32767)" in escape_proc
    assert "DBMS_LOB.SUBSTR(p_val, 200, l_offset)" in escape_proc
    assert "l_offset := l_offset + 200" in escape_proc


def test_vector_facade_normalizes_inputs_and_keeps_fingerprints_on_errors():
    """ASTA 계약/회귀 조건을 검증한다: vector facade normalizes inputs and keeps fingerprints on errors."""
    src = _read("db/adb/asta_vector_pkg.sql")
    assert "FUNCTION normalized_top_k(p_top_k IN NUMBER) RETURN PLS_INTEGER" in src
    assert "FUNCTION validated_case_id(p_run_id IN VARCHAR2) RETURN VARCHAR2" in src
    assert "RAISE_APPLICATION_ERROR(-20004, 'ASTA_VECTOR: invalid case_id')" in src
    assert "l_top_k PLS_INTEGER := normalized_top_k(p_top_k)" in src
    assert "l_query_fingerprint VARCHAR2(128) := sql_fingerprint(p_sql)" in src
    assert src.count("source_fingerprint") >= 3
    assert ',"source_fingerprint":' in src
    assert src.count('"contract_version":"asta.v1"') >= 5
    assert src.count('"execution_boundary":"ADB_VECTOR_PLSQL"') >= 5
    failure_pos = src.index('"status":"FAILED","code":"VECTOR_KB","operation":"SEARCH_SIMILAR_CASES"')
    failure_fp_pos = src.index(',"query_fingerprint":', failure_pos)
    assert failure_pos < failure_fp_pos


def test_report_and_main_carry_final_review_json_artifact():
    """ASTA 계약/회귀 조건을 검증한다: report and main carry final review json artifact."""
    report = _read("db/adb/asta_report_pkg.sql")
    main = _read("db/adb/asta_pkg.sql")
    assert "p_final_review_json    IN CLOB DEFAULT NULL" in report
    assert "p_after_evidence_json  IN CLOB DEFAULT NULL" in report
    assert "p_comparison_json      IN CLOB DEFAULT NULL" in report
    assert "p_vector_save_json     IN CLOB DEFAULT NULL" in report
    assert "# SQL 튜닝 결과서" in report
    for section in [
        "## 결론",
        "## 병목 진단",
        "## 튜닝 전/후 수치 비교",
        "## 튜닝 전 SQL",
        "## 튜닝 전 XPLAN",
        "## 튜닝 후 SQL",
        "## 튜닝 후 XPLAN",
        "원본 재수행 XPLAN",
        "## 상세 분석",
        "### 과거 유사 튜닝 사례 — 참고 정보",
        "### Oracle SQL Tuning Advisor 요약",
        "### DBA 검토 사항",
        "## 작업 수행 이력",
    ]:
        assert section in report
    assert "format_sql_basic(l_candidate_sql_vc)" in report
    assert "FUNCTION format_sql_basic" in report
    assert "REGEXP_REPLACE(l_sql, '[[:space:]]+(FROM)[[:space:]]+'" in report
    assert "REGEXP_REPLACE(l_sql, '[[:space:]]+(WHERE)[[:space:]]+'" in report
    assert "clob_app(l_report, l_candidate_sql_vc)" not in report
    assert "FUNCTION final_review_report_markdown(" in report
    assert "RETURN NULL;" in report
    assert "replace raw SQL/XPLAN with placeholders" in report
    llm = _read("db/adb/asta_llm_pkg.sql")
    assert "Return JSON only with report_markdown" in llm
    assert "# SQL 튜닝 결과서" in llm
    assert "Put a blank line between report sections and between bullet/list items" in llm
    assert "Format SQL inside fenced ```sql blocks with readable line breaks" in llm
    assert "do not paste or recreate raw DBMS_XPLAN table output" in llm
    assert "Never output duplicated XPLAN headers" in llm
    assert "metrics_package_excerpt" not in llm
    assert "full before/after plan_text is preserved" in llm
    assert "If an XPLAN is too long, include a concise non-duplicated excerpt" not in llm
    assert ',"report_markdown":' in llm
    assert "## 테이블 통계 및 인덱스 정보" in report
    assert "PROCEDURE enforce_user_context_section" in report
    assert "$.tuning_context.user_notes" in report
    assert "별도 참고사항 없음." in report
    assert "append_object_metadata_section(l_report, p_source_evidence_json)" in report
    assert "FUNCTION plan_text_clob" in report
    assert "## ' || p_title" in report
    assert "$.object_info.table_stats[*]" in report
    assert "$.indexes[*]" in report
    assert "## 결과 요약" not in report
    assert "### LLM 원문 요약/응답" not in report
    assert "raw_response 원문은 API artifacts.llm에만 보존" in report
    assert "## Final Review JSON" not in report
    assert "## Candidate SQL" not in report
    assert "## Vector KB 저장 결과" not in report
    assert '"contract_version":"asta.v1"' in report
    assert '"report_source":"ADB_REPORT_PLSQL"' in report
    assert '"migration_boundary":{"fastapi_role":"ORDS_PROXY_ONLY"' in report
    assert '"source_runtime":"SOURCE_BASEDB_DBLINK_ONLY"' in report
    assert ',"final_review":' in report
    assert ',"runtime_evidence":' in report
    assert ',"after_evidence":' in report
    assert ',"comparison":' in report
    assert ',"vector_save":' in report
    assert "clob_app_json_or_null(l_out, p_final_review_json)" in report
    assert main.count("p_final_review_json    => l_final_review_json") == 4
    assert main.count("p_comparison_json      => l_comparison_json") == 4
    for fragment in [
        "FUNCTION normalized_fetch_rows(p_fetch_rows IN NUMBER) RETURN PLS_INTEGER",
        "FUNCTION normalized_vector_top_k(p_vector_top_k IN NUMBER) RETURN PLS_INTEGER",
        "FUNCTION normalized_sqltune_time_limit(p_sqltune_time_limit IN NUMBER) RETURN PLS_INTEGER",
        "FUNCTION normalize_run_id(p_run_id IN VARCHAR2) RETURN VARCHAR2",
        "FUNCTION migration_boundary_json RETURN VARCHAR2",
        "l_fetch_rows := normalized_fetch_rows(l_fetch_rows)",
        "l_vector_top_k := normalized_vector_top_k(l_vector_top_k)",
        "l_sqltune_time_limit := normalized_sqltune_time_limit(l_sqltune_time_limit)",
    ]:
        assert fragment in main

def test_vector_evidence_is_collected_before_llm_and_comparison_uses_runtime_metrics():
    """Vector 사례는 LLM 입력이며 deterministic 비교는 후보 실행 뒤 수행한다."""
    src = _read("db/adb/asta_pkg.sql")
    assert "FUNCTION build_comparison_json(p_before_json IN CLOB, p_after_json IN CLOB," in src
    assert "JSON_VALUE(p_before_json, '$.last_cr_buffer_gets' RETURNING NUMBER NULL ON ERROR)" in src
    assert "JSON_VALUE(p_after_json, '$.last_elapsed_time_us' RETURNING NUMBER NULL ON ERROR)" in src
    assert '"buffer_gets_delta":' in src
    assert '"buffer_gets_reduction_pct":' in src
    assert '"disk_reads_delta":' in src
    assert '"elapsed_time_us_delta":' in src
    assert '"execution_boundary":"ADB_COMPARISON_PLSQL"' in src
    assert '"contract_version":"asta.v1"' in src
    after_pos = src.index("l_after_json := asta_source_bridge_pkg.run_source_evidence")
    comparison_pos = src.index("l_comparison_json := build_comparison_json(l_source_json, l_after_json, l_workload_type)")
    vector_pos = src.index("l_vector_json := asta_vector_pkg.search_similar_cases")
    llm_pos = src.index("l_llm_json := asta_llm_pkg.generate_sql_only_tuning")
    assert vector_pos < llm_pos < after_pos < comparison_pos
    assert "asta_llm_pkg.final_review(" not in src


def test_report_reads_canonical_comparison_json_fields():
    """ASTA 계약/회귀 조건을 검증한다: report reads canonical comparison json fields."""
    report = _read("db/adb/asta_report_pkg.sql")
    for path in [
        "$.row_count_matches",
        "$.output_rows_match",
        "$.before_row_count",
        "$.after_row_count",
        "$.before_output_rows",
        "$.after_output_rows",
        "$.before_buffer_gets",
        "$.after_buffer_gets",
        "$.buffer_gets_reduction_pct",
        "$.before_disk_reads",
        "$.after_disk_reads",
        "$.before_elapsed_time_us",
        "$.after_elapsed_time_us",
        "$.elapsed_time_us_delta",
    ]:
        assert f"json_vc(p_comparison_json, '{path}" in report
    for stale_path in ["$.before.status", "$.after.status", "$.row_count_equal"]:
        assert stale_path not in report

def test_vector_save_receives_report_ref_before_final_report_generation():
    """Vector stores a stable ref; final report receives actual save status."""
    src = _read("db/adb/asta_pkg.sql")
    report_pos = src.index("l_report_markdown := asta_report_pkg.build_report(")
    save_pos = src.index("l_vector_save_json := asta_vector_pkg.save_case(")
    response_pos = src.index("l_response_json := asta_report_pkg.build_response_json(")
    assert save_pos < report_pos < response_pos
    assert "generate_sql_only_tuning" in src
    assert "sql_needs_sql_only_retry" in src
    assert src.count("asta_llm_pkg.generate_sql_only_tuning(") == 1
    assert "l_llm_json := l_sql_only_llm_json" not in src
    assert ',"tuning_context":' in src
    assert "p_report_markdown => TO_CLOB('/api/asta/runs/')" in src
    assert "p_report_markdown => NULL" not in src


def test_ords_json_handlers_set_cache_and_content_type_headers():
    """ASTA 계약/회귀 조건을 검증한다: ords json handlers set cache and content type headers."""
    src = _read("db/ords/asta_ords_module.sql")
    assert src.count("Cache-Control: no-store") == 6
    assert src.count("Pragma: no-cache") == 6
    assert src.count("X-Content-Type-Options: nosniff") == 6
    assert src.count("X-ASTA-Execution-Boundary: ADB_ORDS_PLSQL") == 6
    assert src.count("X-ASTA-Api-Version: asta.v1") == 6
    assert src.count("X-ASTA-Contract-Version: asta.v1") == 6
    assert src.count("X-ASTA-Response-Mode: CLOB_CHUNKED_JSON") == 6


def test_adb_public_lookup_endpoints_validate_run_id_and_emit_boundary_metadata():
    """ASTA 계약/회귀 조건을 검증한다: adb public lookup endpoints validate run id and emit boundary metadata."""
    src = _read("db/adb/asta_pkg.sql")
    assert "FUNCTION normalize_run_id(p_run_id IN VARCHAR2) RETURN VARCHAR2" in src
    assert "ASTA_PKG: invalid run_id" in src
    # 조회 3개와 Scheduler 실행 진입점 1개가 동일한 run_id 검증을 사용한다.
    assert src.count("l_run_id := normalize_run_id(p_run_id)") == 6
    assert "IF p_status IN ('DONE', 'FAILED', 'SKIPPED') THEN\n      l_elapsed_ms := NULL;" in src
    assert "JSON_VALUE(p_body_json, '$.run_id' RETURNING VARCHAR2(64) NULL ON ERROR)" in src
    assert "l_run_id := normalize_run_id(l_run_id);" in src
    assert "AND    status = 'RUNNING';" in src
    assert "ASTA_PKG: run was not claimed for execution" in src
    assert "COMMIT;\n\n    record_progress(l_run_id, 3, 'SQL_GUARD'" in src
    assert "FUNCTION migration_boundary_json RETURN VARCHAR2" in src
    assert '"contract_version":"asta.v1"' in src
    assert '"architecture":"ADB_ORDS_PLSQL"' in src
    assert '"migration_boundary":{"fastapi_role":"ORDS_PROXY_ONLY"' in src
    assert '"python_local_asta":false' in src
    for code in ["RUN_LOOKUP", "PROGRESS_LOOKUP", "REPORT_LOOKUP"]:
        assert code in src


def test_asta_python_proxy_remains_thin_ords_only():
    """ASTA 계약/회귀 조건을 검증한다: asta python proxy remains thin ords only."""
    src = _read("app/routers/asta_proxy.py")
    forbidden = [
        "source_runtime_xplan.py",
        "subprocess.run",
        "ASTA_SOURCE_DB_PASSWORD",
        "SOURCE_DB_SECRET_FILE",
        "PYTHON_ASTA_STREAM",
        "BASEDB_SOURCE_DIRECT",
        "oracledb.connect",
        "DBMS_XPLAN",
        "DBMS_SQLTUNE",
        "V$SQL_PLAN_STATISTICS_ALL",
        "DBMS_CLOUD_AI",
    ]
    for fragment in forbidden:
        assert fragment not in src, f"{fragment!r} leaked into app/routers/asta_proxy.py"
    assert '"source_schema":' not in src
    assert '"source_db_link":' not in src
    assert 'out.pop("source_schema", None)' in src
    assert 'out.pop("source_db_link", None)' in src


def test_browser_and_adb_main_do_not_trust_source_link_payload_fields():
    """ASTA 계약/회귀 조건을 검증한다: browser and adb main do not trust source link payload fields."""
    proxy = _read("app/routers/asta_proxy.py")
    ui = _read("static/js/extensions/tuning_assistant.js")
    main = _read("db/adb/asta_pkg.sql")

    assert '"source_schema":' not in proxy
    assert '"source_db_link":' not in proxy
    assert "source_schema" not in ui
    assert "source_db_link" not in ui
    assert "JSON_VALUE(p_body_json, '$.source_schema'" not in main
    assert "JSON_VALUE(p_body_json, '$.source_db_link'" not in main
    assert "C_DEFAULT_SOURCE_SCHEMA" not in main
    assert "C_DEFAULT_SOURCE_DB_LINK" not in main
    assert "l_source_connection_json := asta_source_bridge_pkg.get_connection_json(l_source_db_id)" in main
    assert "l_source_schema := JSON_VALUE(l_source_connection_json, '$.source_schema'" in main
    assert "l_source_db_link := JSON_VALUE(l_source_connection_json, '$.db_link_name'" in main


def test_source_helper_guards_and_normalizes_before_exec_boundary():
    """SQL guard and run_id normalization must both precede build_exec_sql in source pkg."""
    src = _read("db/source/asta_source_pkg.sql")
    guard_pos = src.index("assert_safe_select(p_sql);")
    runid_pos = src.index("l_run_id := normalize_run_id(p_run_id);")
    exec_pos = src.index("l_exec_sql := build_exec_sql(p_sql, l_run_id, l_fetch_rows)")
    assert guard_pos < exec_pos, "SQL guard must precede build_exec_sql"
    assert runid_pos < exec_pos, "run_id normalization must precede build_exec_sql"


def test_source_helper_collects_object_metadata_for_llm_evidence():
    """Source evidence must carry table/column stats and index metadata for LLM tuning."""
    src = _read("db/source/asta_source_pkg.sql")
    llm = _read("db/adb/asta_llm_pkg.sql")

    for fragment in [
        "FUNCTION collect_object_info(",
        "v$sql_plan_statistics_all",
        "dba_tab_statistics",
        "dba_tab_columns",
        "dba_ind_columns",
        "dba_indexes",
        '"object_info":',
        '"table_stats"',
        '"columns"',
        '"indexes"',
        '"num_rows":',
        '"last_analyzed":',
        '"stale_stats":',
        "IF SUBSTR(l_text, 1, 1) = '.' THEN",
        "l_text := '0' || l_text;",
    ]:
        assert fragment in src

    for visibility_limited_view in (
        "all_tab_statistics", "all_tab_columns", "all_ind_columns", "all_indexes"
    ):
        assert visibility_limited_view not in src

    metrics_pos = src.index("collect_metrics(")
    object_pos = src.index("l_object_info := collect_object_info(l_sql_id, l_child_number)")
    json_pos = src.index(',"object_info":', object_pos)
    assert metrics_pos < object_pos < json_pos

    assert "Object metadata JSON for table/column statistics and indexes" in llm
    assert "User tuning context JSON" in llm
    assert "사용자 참고사항" in llm
    assert "user_notes" in llm
    assert "hard optimization objective" in llm
    assert "CORRELATED_SCALAR_SUBQUERIES_REPEATING_FACT_TABLE" in llm
    assert "UNION_ALL_REPEATED_FACT_TABLE_AGGREGATION" in llm
    assert "REPEATED_EXISTS_OR_SEMIJOIN_FACT_PATTERN" in llm
    assert "fact-table pre-aggregation CTE" in llm
    assert "single fact scan" not in llm or "one base CTE/fact scan" in llm
    assert "l_offset := l_offset + 1000;" in llm
    assert "l_offset := l_offset + 500;\n    END LOOP;\n    clob_app(p_out, '\"');" not in llm
    assert "object_info_excerpt" in llm
    assert "JSON_QUERY(p_json, '$.object_info'" in llm


def test_report_elapsed_judgement_and_original_rerun_xplan_wording():
    """ASTA 계약/회귀 조건을 검증한다: report elapsed judgement and original rerun xplan wording."""
    report = _read("db/adb/asta_report_pkg.sql")
    # elapsed_time_us_delta는 before-after이므로 음수이면 튜닝 후 수행시간 증가다.
    assert "l_elapsed_delta IS NOT NULL AND l_elapsed_delta < 0" in report
    assert "l_buffer_reduction_num IS NOT NULL AND l_buffer_reduction_num <= 0" in report
    assert "개선실패 - Buffer Gets와 수행시간이 모두 개선되지 않아 원본 SQL 유지 권장" in report
    assert "WHEN l_elapsed_delta > 0 THEN '빨라짐'" in report
    assert "WHEN l_elapsed_delta < 0 THEN '느려짐'" in report
    assert "ELSE '동일'" in report
    assert "- SQL 변경 내용: " in report
    assert "- 변경 위치: " in report
    assert "append_xplan_raw_section(l_report, '원본 재수행 XPLAN', p_after_evidence_json)" in report
    assert "선택 메모가 아니라 명시적 튜닝 목표" in report


def test_llm_report_explanations_are_requested_in_korean():
    """보고서 설명 필드는 모두 한국어로 생성하도록 프롬프트에서 강제한다."""
    llm = _read("db/adb/asta_llm_pkg.sql")
    assert "rationale (Korean), and risk_notes (Korean)" in llm
    assert "All explanatory text fields must be written in Korean" in llm


def test_bridge_resolves_allowlist_before_dynamic_sql_and_execute_immediate():
    """resolve_connection (allowlist) must precede SQL guard and EXECUTE IMMEDIATE in bridge."""
    src = _read("db/adb/asta_source_bridge_pkg.sql")
    resolve_pos = src.index("resolve_connection(p_source_db_id, l_db_link_name, l_source_schema)")
    guard_pos = src.index("asta_sql_guard_pkg.assert_safe_select(p_sql)")
    stmt_pos = src.index("l_stmt :=")
    exec_pos = src.index("EXECUTE IMMEDIATE l_stmt")
    assert resolve_pos < guard_pos < stmt_pos < exec_pos


def test_asta_pkg_failure_path_sets_failed_and_persists_artifacts():
    """analyze_sql EXCEPTION path must mark the run FAILED and persist report/error to asta_runs."""
    src = _read("db/adb/asta_pkg.sql")
    # Both success and failure paths call build_report and build_response_json
    assert src.count("l_report_markdown := asta_report_pkg.build_report(") == 2
    assert src.count("l_response_json := asta_report_pkg.build_response_json(") == 2
    # Failure path sets FAILED status and captures the error
    assert "l_status := 'FAILED'" in src
    assert "error_json('ASTA_PKG'" in src
    # asta_runs UPDATE in failure path persists error_code and error_message
    assert "error_code = 'ASTA_PKG'" in src
    assert "error_message = l_error_message" in src


def test_vector_tables_ddl_schema_contracts():
    """004_asta_vector_tables.sql must define both KB tables with fingerprint index and FK cascade."""
    src = _read("db/asta/004_asta_vector_tables.sql")
    assert "CREATE TABLE asta_tuning_cases" in src
    assert "sql_fingerprint  VARCHAR2(64)" in src
    assert "CHECK (metadata_json IS JSON)" in src
    assert "CREATE TABLE asta_tuning_case_chunks" in src
    assert "GENERATED ALWAYS AS IDENTITY PRIMARY KEY" in src
    assert "CONSTRAINT atcc_case_fk FOREIGN KEY (case_id)" in src
    assert "REFERENCES asta_tuning_cases(case_id) ON DELETE CASCADE" in src
    assert "CREATE INDEX atc_fingerprint_idx ON asta_tuning_cases(sql_fingerprint)" in src
    assert "CREATE INDEX atcc_case_idx ON asta_tuning_case_chunks(case_id)" in src


def test_vector_pkg_save_inserts_sql_fingerprint_matching_ddl():
    """save_case INSERT must store sql_fingerprint to align with 004_asta_vector_tables.sql DDL."""
    src = _read("db/adb/asta_vector_pkg.sql")
    # fingerprint is computed before any INSERT
    fp_compute_pos = src.index("l_source_fingerprint := sql_fingerprint(p_sql)")
    insert_pos = src.index("INSERT INTO asta_tuning_cases(")
    assert fp_compute_pos < insert_pos, "fingerprint must be computed before INSERT"
    # INSERT must include the sql_fingerprint column
    col_end = src.index(") VALUES (", insert_pos)
    insert_cols = src[insert_pos:col_end]
    assert "sql_fingerprint," in insert_cols, "sql_fingerprint column missing from INSERT"
    # USING clause must pass l_source_fingerprint as a bind
    using_pos = src.index("USING l_case_id,", insert_pos)
    using_clause = src[using_pos : using_pos + 300]
    assert "l_source_fingerprint" in using_clause, "l_source_fingerprint bind missing from USING clause"


def test_sqltune_advisor_explicit_policy_and_report_contract():
    """ASTA 계약/회귀 조건을 검증한다: sqltune advisor explicit policy and report contract."""
    main = _read("db/adb/asta_pkg.sql")
    source = _read("db/source/asta_source_pkg.sql")
    report = _read("db/adb/asta_report_pkg.sql")

    assert "FUNCTION normalized_run_advisor(p_run_advisor IN VARCHAR2) RETURN VARCHAR2" in main
    assert "JSON_VALUE(p_body_json, '$.run_advisor' RETURNING VARCHAR2(30) NULL ON ERROR)" in main
    assert "JSON_VALUE(p_body_json, '$.use_sqltune' RETURNING VARCHAR2(30) NULL ON ERROR)" in main
    assert "RETURN LEAST(GREATEST(NVL(p_sqltune_time_limit, 1800), 60), 1800)" in main
    assert "l_run_advisor := normalized_run_advisor(l_run_advisor_raw)" in main
    before_pos = main.index("l_source_json := asta_source_bridge_pkg.run_source_evidence")
    before_call = main[before_pos : before_pos + 500]
    assert "p_run_advisor      => l_run_advisor" in before_call
    after_pos = main.index("l_after_json := asta_source_bridge_pkg.run_source_evidence")
    after_call = main[after_pos : after_pos + 500]
    assert "p_run_advisor      => 'N'" in after_call
    assert "advisor_progress_detail(l_source_json, l_run_advisor)" in main
    assert "run_advisor/use_sqltune=true" in main

    assert "l_advisor_fragment CLOB" in source
    assert "json_str(DBMS_LOB.SUBSTR(l_advisor_report, 30000, 1))" not in source
    assert "clob_app_json_str(l_advisor_fragment, l_advisor_report)" in source
    assert "No Source DB direct fallback was attempted" in source
    assert "cannot be executed safely through the ADB DB Link path" in source
    assert "SOURCE_BASEDB_HELPER_DIRECT_RESTRICTED_FALLBACK" not in source

    assert "PROCEDURE append_advisor_summary" in report
    assert "## Oracle SQL Tuning Advisor 요약" in report
    assert "runtime_evidence.advisor.report" in report
    assert "PROCEDURE append_stage_check" in report
    assert "## 단계별 수행 체크" in report
    assert "SQL Tuning Advisor" in report
    assert "실제 수행 여부/사유" in report
    assert "sqltune_time_limit`(60..1800초 clamp)" in report


def test_ords_handlers_use_safe_clob_chunking_loop():
    """All 6 ORDS handlers must use conservative chunks below the OWA 32KB response boundary."""
    src = _read("db/ords/asta_ords_module.sql")
    loop_pattern = "WHILE l_offset <= NVL(DBMS_LOB.GETLENGTH(l_response), 0) LOOP"
    chunk_read = "l_chunk := DBMS_LOB.SUBSTR(l_response, 2000, l_offset)"
    chunk_write = "HTP.prn(l_chunk)"
    advance = "l_offset := l_offset + 2000"
    assert src.count(loop_pattern) == 6, f"expected 6 CLOB chunking loops, got {src.count(loop_pattern)}"
    assert src.count(chunk_read) == 6, f"expected 6 DBMS_LOB.SUBSTR reads, got {src.count(chunk_read)}"
    assert src.count(chunk_write) == 6, f"expected 6 HTP.prn writes, got {src.count(chunk_write)}"
    assert src.count(advance) == 6, f"expected 6 offset advances, got {src.count(advance)}"


def test_adb_reports_use_json_escaping_helpers_for_long_text_artifacts():
    """Long markdown/advisor/source text must be JSON-escaped as CLOB chunks, never VARCHAR concat."""
    main = _read("db/adb/asta_pkg.sql")
    report = _read("db/adb/asta_report_pkg.sql")
    for src in [main, report]:
        assert "PROCEDURE clob_app_json_str" in src
        assert "DBMS_LOB.SUBSTR(p_val, 100" in src or "DBMS_LOB.SUBSTR(p_val, 200" in src
        assert "DBMS_LOB.SUBSTR(p_val, 8000, l_offset)" in src
        assert "l_offset := l_offset + LENGTH(l_chunk)" in src
    assert "clob_app_json_str(l_out, p_report_markdown)" in report
    assert "JSON_VALUE(p_json, '$.advisor.report' RETURNING CLOB NULL ON ERROR)" in report
    assert "clob_app_json_str(l_advisor_fragment, l_advisor_report)" in _read("db/source/asta_source_pkg.sql")


def test_source_pkg_xplan_format_covers_allstats_and_filter_plans():
    """XPLAN must use ALLSTATS LAST format; output rows from MAX(id IN (0,1)) for FILTER/scalar plans."""
    src = _read("db/source/asta_source_pkg.sql")
    assert "'ALLSTATS LAST +PREDICATE +PEEKED_BINDS +OUTLINE +NOTE'" in src
    # FILTER/scalar-subquery-safe: output rows from max of id 0 and 1
    assert "CASE WHEN id IN (0, 1) THEN last_output_rows" in src
    # Per-execution metrics from plan root row (id=0)
    assert "CASE WHEN id = 0      THEN last_cr_buffer_gets" in src
    assert "CASE WHEN id = 0      THEN last_disk_reads" in src
    assert "CASE WHEN id = 0      THEN last_elapsed_time" in src
    assert "v$sql_plan_statistics_all" in src
    assert "FROM v$sql_plan_statistics_all" in src


def test_source_pkg_build_exec_sql_rownum_bounded_with_plan_marker():
    """build_exec_sql wraps SQL in COUNT(*)/ROWNUM<=N with gather_plan_statistics hint and ASTA_RUN_ID marker."""
    src = _read("db/source/asta_source_pkg.sql")
    assert "FUNCTION build_exec_sql(" in src
    assert "gather_plan_statistics" in src
    assert "/* ASTA_RUN_ID=" in src
    assert "COUNT(*) FROM (" in src
    assert "WHERE ROWNUM <=" in src
    assert "TO_CLOB(l_header) || p_sql || TO_CLOB(l_footer)" in src


def test_adb_main_record_progress_uses_autonomous_transaction():
    """record_progress must use PRAGMA AUTONOMOUS_TRANSACTION so progress rows commit immediately."""
    src = _read("db/adb/asta_pkg.sql")
    assert "PROCEDURE record_progress(" in src
    assert "PRAGMA AUTONOMOUS_TRANSACTION" in src
    pragma_pos = src.index("PRAGMA AUTONOMOUS_TRANSACTION")
    insert_progress_pos = src.index("INSERT INTO asta_run_progress(")
    assert pragma_pos < insert_progress_pos


def test_adb_main_early_progress_precedes_run_insert():
    """Steps 1,2 (REQUEST_RECEIVED, ORDS_DISPATCH) are recorded via autonomous tx before INSERT INTO asta_runs."""
    src = _read("db/adb/asta_pkg.sql")
    analyze_start = src.index("FUNCTION analyze_sql(p_body_json IN CLOB) RETURN CLOB")
    req_recv_pos = src.index("record_progress(l_run_id, 1, 'REQUEST_RECEIVED'", analyze_start)
    ords_pos = src.index("record_progress(l_run_id, 2, 'ORDS_DISPATCH'", analyze_start)
    insert_run_pos = src.index("INSERT INTO asta_runs(", analyze_start)
    assert req_recv_pos < insert_run_pos, "REQUEST_RECEIVED must be recorded before INSERT INTO asta_runs"
    assert ords_pos < insert_run_pos, "ORDS_DISPATCH must be recorded before INSERT INTO asta_runs"


def test_asta_run_progress_intentionally_has_no_fk_to_allow_autonomous_progress():
    """asta_run_progress must NOT FK-reference asta_runs; autonomous-tx progress rows must commit before the run row."""
    src = _read("db/asta/001_asta_repository.sql")
    assert "CREATE TABLE asta_run_progress" in src
    progress_start = src.index("CREATE TABLE asta_run_progress")
    progress_end = src.index(");", progress_start)
    progress_ddl = src[progress_start:progress_end]
    assert "REFERENCES asta_runs" not in progress_ddl


def test_bridge_dynamic_sql_uses_bind_variables_for_clob_args():
    """Bridge must use bind variables for SQL CLOB and all other sensitive args, not string concat."""
    src = _read("db/adb/asta_source_bridge_pkg.sql")
    assert ":sql_text, :run_id, :fetch_rows, :repeat_policy, :run_advisor, :sqltune_time_sec" in src
    assert "OUT l_status_vc" in src
    assert "USING OUT l_chunk," in src
    assert "IN  l_sql_vc," in src
    assert "l_run_id := validated_run_id(p_run_id)" in src
    assert "IN  l_run_id," in src
    assert "IN  p_run_id," not in src
    # DB link and schema go into l_stmt string but are allowlist-validated identifiers
    assert "validated_db_link_name" in src
    assert "validated_schema_name" in src


def test_response_json_carries_proxy_source_and_external_call_fields():
    """Canonical analyze response must carry proxy.source=ADB_ORDS and external_call=false."""
    src = _read("db/adb/asta_report_pkg.sql")
    assert '"proxy":{"source":"ADB_ORDS","external_call":false}' in src


def test_source_pkg_sqltune_returns_failed_when_source_db_is_restricted():
    """Restricted Source DBs must not try Source-direct/current-session SQLTUNE; fail advisor clearly via DB Link."""
    src = _read("db/source/asta_source_pkg.sql")
    assert "l_source_logins = 'RESTRICTED'" in src
    restricted_pos = src.index("IF l_source_logins = 'RESTRICTED' THEN")
    normal_pos = src.index("l_job_name := 'ASTA_ADV_'", restricted_pos)
    restricted_block = src[restricted_pos:normal_pos]
    assert "l_advisor_status := 'FAILED'" in restricted_block
    assert "No Source DB direct fallback was attempted" in restricted_block
    assert "l_advisor_report := run_advisor_opt(" not in restricted_block
    assert "SOURCE_BASEDB_HELPER_DIRECT_RESTRICTED_FALLBACK" not in restricted_block
    bridge = _read("db/adb/asta_source_bridge_pkg.sql")
    assert "IF l_run_advisor = 'Y' AND l_db_link_name IS NOT NULL AND l_run_id IS NOT NULL THEN" in bridge
    assert "asta_source_pkg.get_result_chunk@" in bridge
    assert "RETURN l_result" in bridge
    assert "DBMS_SCHEDULER.RUN_JOB(job_name => l_job_name, use_current_session => FALSE)" in src


def test_source_pkg_elapsed_per_exec_and_advisor_task_sanitized():
    """Wall-clock per-exec elapsed formula and sanitized SQLTUNE task name must be present."""
    src = _read("db/source/asta_source_pkg.sql")
    # Wall-clock elapsed decomposition
    assert "EXTRACT(DAY    FROM (l_end - l_start)) * 86400000" in src
    assert "EXTRACT(HOUR   FROM (l_end - l_start)) * 3600000" in src
    assert "EXTRACT(MINUTE FROM (l_end - l_start)) * 60000" in src
    assert "EXTRACT(SECOND FROM (l_end - l_start)) * 1000" in src
    # Per-execution elapsed in response JSON
    assert "ROUND(l_elapsed_ms / l_repeats)" in src
    assert ',"elapsed_wall_ms_per_exec":' in src
    # Advisor task name sanitizes the run_id before embedding in Oracle task name
    assert "REGEXP_REPLACE(UPPER(p_run_id), '[^A-Z0-9_$#]', '')" in src
    assert "'ASTA_' || SUBSTR(" in src
    # Return value of CREATE_TUNING_TASK is captured and used (not the derived name)
    assert "l_task := NVL(l_created_task, l_task)" in src
    # Cleanup always runs (prevents task accumulation)
    assert "DBMS_SQLTUNE.DROP_TUNING_TASK(task_name => l_task)" in src


def test_source_sql_deploy_creates_store_chunk_repository_tables():
    """ASTA 계약/회귀 조건을 검증한다: source sql deploy creates store chunk repository tables."""
    src = _read("db/deploy/01_source_compile.sql")
    assert "CREATE TABLE asta_source_results" in src
    assert "response_json CLOB CHECK (response_json IS JSON)" in src
    assert "CREATE INDEX asta_source_results_created_idx" in src
    assert "CREATE TABLE asta_source_advisor_results" in src
    assert "report     CLOB" in src
    assert "CREATE INDEX asta_src_adv_results_created_idx" in src
    assert "Source helper repository tables verified" in src
    assert "cleanup policy" in src


def test_source_smoke_validates_store_chunk_asta_v1_json():
    """ASTA 계약/회귀 조건을 검증한다: source smoke validates store chunk asta v1 json."""
    src = _read("db/deploy/04_source_smoke.sql")
    assert "asta_source_pkg.run_evidence(" in src
    assert "asta_source_pkg.run_evidence_store_proc(" in src
    assert "p_status_json      => :store_status" in src
    assert "l_store_status <> 'STORED'" in src
    assert "asta_source_pkg.get_result_chunk(" in src
    assert "p_amount => l_chunk_size" in src
    assert "JSON_VALUE(l_result_json, '$.contract_version'" in src
    assert "l_contract <> 'asta.v1'" in src
    assert "store/chunk smoke reconstructed asta.v1 JSON" in src


def test_source_docs_and_reports_pin_devdo_dblink_contract():
    """ASTA 계약/회귀 조건을 검증한다: source docs and reports pin devdo dblink contract."""
    source_readme = _read("db/source/README.md")
    deploy_readme = _read("db/deploy/README.md")
    latest_report = _read("reports/asta_source_contract_latest.md")
    deploy_tool = _read("tools/asta_deploy_adb.py")

    for src in [source_readme, deploy_readme, latest_report]:
        assert "run_evidence_store_proc" in src
        assert "get_result_chunk" in src
        assert "asta.v1" in src

    assert "DB0903_LINK" in deploy_readme
    assert "DEVDO" in deploy_readme
    assert "Older readiness notes" in deploy_readme
    assert "Source helper schema `ADMIN` was pre-fix" in latest_report
    assert "DB0903_LINK/DEVDO" in deploy_tool
    assert "DB0903_LINK/ADMIN" not in deploy_tool


def test_evidence_aware_workflow_order_and_no_production_final_review():
    """Source/Vector evidence를 모은 뒤 LLM을 호출하며 production 2차 LLM은 호출하지 않는다."""
    src = _read("db/adb/asta_pkg.sql")
    analyze = src[src.index("FUNCTION analyze_sql(p_body_json IN CLOB) RETURN CLOB"):]
    markers = ["'BEFORE_EVIDENCE'", "'SQL_TUNING_ADVISOR'", "'VECTOR_KB'", "'LLM_REWRITE'",
               "'AFTER_EVIDENCE'", "'BEFORE_AFTER_COMPARE'",
               "'FINAL_REPORT'", "'VECTOR_SAVE'"]
    positions = [analyze.index(marker) for marker in markers]
    assert positions == sorted(positions)
    assert "asta_llm_pkg.final_review(" not in analyze
    assert analyze.index("asta_vector_pkg.search_similar_cases(") < analyze.index("asta_llm_pkg.generate_sql_only_tuning(")


def test_canonical_rewrite_call_receives_source_vector_and_user_context():
    src = _read("db/adb/asta_pkg.sql")
    pos = src.index("l_llm_json := asta_llm_pkg.generate_sql_only_tuning(")
    call = src[pos:src.index(");", pos)]
    assert "p_source_evidence_json => l_source_json" in call
    assert "p_vector_json          => l_vector_json" in call
    assert "p_tuning_context_json  => l_context_json" in call


def test_no_candidate_skips_only_after_and_compare_then_continues():
    src = _read("db/adb/asta_pkg.sql")
    vector = src.index("asta_vector_pkg.search_similar_cases(")
    no_candidate = src.index("'No structural rewrite candidate'")
    save = src.index("asta_vector_pkg.save_case(", no_candidate)
    report = src.index("asta_report_pkg.build_report(", save)
    assert vector < no_candidate < save < report
    window = src[no_candidate - 700:no_candidate + 700]
    assert "'AFTER_EVIDENCE'" in window
    assert "'BEFORE_AFTER_COMPARE'" in window


def test_sql_only_prompt_and_deterministic_verdict_contracts():
    llm = _read("db/adb/asta_llm_pkg.sql")
    main = _read("db/adb/asta_pkg.sql")
    for field in ['\"rewrite_available\"', '\"candidate_sql\"', '\"change_summary\"', '\"semantic_risks\"']:
        assert field in llm
    for prohibition in ["인덱스", "옵티마이저 힌트", "DDL", "통계", "SQL Profile"]:
        assert prohibition in llm
    assert "FUNCTION structural_sql_key" in llm
    assert "NO_REWRITE" in llm
    for verdict in ["IMPROVED", "ANALYSIS_ONLY", "NOT_IMPROVED", "NON_EQUIVALENT", "CANDIDATE_FAILED", "NO_REWRITE", "INSUFFICIENT_EVIDENCE"]:
        assert verdict in main
    for field in ['\"verdict\"', '\"verdict_reason\"', '\"equivalence_status\"', '\"retain_original_sql\"']:
        assert field in main
    assert "l_after_elapsed > l_before_elapsed" in main


def test_vector_cases_return_verified_summary_and_internal_report_reference():
    vector = _read("db/adb/asta_vector_pkg.sql")
    for field in ["'case_id' VALUE", "'verdict' VALUE", "'change_summary' VALUE",
                  "'before_buffer_gets' VALUE", "'after_buffer_gets' VALUE",
                  "'before_elapsed_time_us' VALUE", "'after_elapsed_time_us' VALUE",
                  "'report_ref' VALUE"]:
        assert field in vector
    assert "'/api/asta/runs/' || case_id || '/report'" in vector
    assert "http://" not in vector.lower() and "https://" not in vector.lower()


def test_vector_case_ux_is_summary_first_and_never_returns_full_artifacts():
    vector = _read("db/adb/asta_vector_pkg.sql")
    report = _read("db/adb/asta_report_pkg.sql")
    for field in ["'run_id' VALUE", "'workload_type' VALUE", "'primary_metric' VALUE",
                  "'sql_preview' VALUE"]:
        assert field in vector
    assert "C_SQL_PREVIEW_CHARS CONSTANT PLS_INTEGER := 500" in vector
    assert "C_SQL_PREVIEW_LINES CONSTANT PLS_INTEGER := 10" in vector
    search_json = vector[vector.index("FUNCTION search_similar_cases("):vector.index("END search_similar_cases;")]
    assert "'source_sql' VALUE" not in search_json
    assert "'report_markdown' VALUE" not in search_json
    assert "'chunk_text' VALUE" not in search_json
    assert "REGEXP_REPLACE" in vector and "sql_preview" in vector

    assert "### 과거 유사 튜닝 사례 — 참고 정보" in report
    assert "유사 사례는 과거 실행의 참고 정보이며, 현재 SQL의 개선 판정은 이번 Before/After 실제 실행 결과를 기준으로 합니다." in report
    assert "<details><summary>축약 SQL 보기</summary>" in report
    assert "[전체 결과서 보기]" in report
    assert "유사 사례 없음" in report
    assert "REGEXP_LIKE(v.report_ref, '^/api/asta/runs/" in report


def test_vector_save_metadata_and_semantic_chunks_cover_all_verdicts():
    vector = _read("db/adb/asta_vector_pkg.sql")
    main = _read("db/adb/asta_pkg.sql")
    for path in ["$.verdict", "$.equivalence_status", "$.before_buffer_gets",
                 "$.after_buffer_gets", "$.before_elapsed_time_us",
                 "$.after_elapsed_time_us", "$.before_plan_hash_value",
                 "$.after_plan_hash_value", "$.rewrite_type"]:
        assert path in vector
    for chunk in ["VERIFIED_OUTCOME", "PLAN_EVIDENCE", "METRICS", "ANALYSIS_OBSERVATION", "ANALYSIS_SCOPE", "REJECTED_OBSERVATION", "REJECTION_REASON"]:
        assert f"'{chunk}'" in vector
    assert "'POSITIVE_VERIFIED'" in vector
    assert "'ANALYSIS_OBSERVATION'" in vector
    assert '"observation_reason":' in vector
    assert "$.learning_class" in vector
    assert "build_vector_metadata(" in main
    assert "p_metadata_json   => l_vector_metadata_json" in main


def test_report_conclusion_is_deterministic_and_vector_is_reference_only():
    report = _read("db/adb/asta_report_pkg.sql")
    assert "json_vc(p_comparison_json, '$.verdict'" in report
    for verdict in ["IMPROVED", "ANALYSIS_ONLY", "NOT_IMPROVED", "NON_EQUIVALENT", "CANDIDATE_FAILED", "NO_REWRITE", "INSUFFICIENT_EVIDENCE"]:
        assert verdict in report
    assert "개선 SQL 없음" in report
    assert "튜닝 후 XPLAN" in report and "SKIPPED" in report
    assert "report_ref" in report
    assert "참고 자료" in report
    assert "final_review_report_markdown(p_final_review_json)" not in report
