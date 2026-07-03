"""작성자: 도상훈
파일 용도: ASTA ORDS/ADB 마이그레이션 계약과 회귀 조건을 정적/단위 테스트로 검증한다."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASTA_PRODUCTION_PATHS = [
    "app/routers/asta_proxy.py",
    "static/js/extensions/tuning_assistant.js",
    "db/source/asta_source_pkg.sql",
    "db/adb/asta_source_bridge_pkg.sql",
    "db/adb/asta_sql_guard_pkg.sql",
    "db/adb/asta_vector_pkg.sql",
    "db/adb/asta_llm_pkg.sql",
    "db/adb/asta_report_pkg.sql",
    "db/adb/asta_pkg.sql",
    "db/ords/asta_ords_module.sql",
]

PYTHON_THIN_PROXY_PATHS = [
    "app/routers/asta_proxy.py",
]


ADB_PACKAGE_FILES = {
    "db/source/asta_source_pkg.sql": [
        "CREATE OR REPLACE PACKAGE asta_source_pkg",
        "FUNCTION run_evidence",
        "FUNCTION scrub_guard_text",
        "FUNCTION normalize_run_id",
        "FUNCTION normalize_repeat_policy",
        "FUNCTION normalize_repeat_count",
        "C_MAX_SQL_CHARS  CONSTANT PLS_INTEGER := 32767",
        "Statement terminator is not allowed",
        "l_created_task := DBMS_SQLTUNE.CREATE_TUNING_TASK",
        "DBMS_XPLAN.DISPLAY_CURSOR",
        '"status":"COMPLETED"',
        '"status":"FAILED"',
        '"contract_version":"asta.v1"',
        '"execution_boundary":"SOURCE_BASEDB_DBLINK_ONLY"',
        '"timing_scope":"repeat_loop_total"',
        '"elapsed_wall_ms_per_exec":',
        '"advisor_requested":',
        '"sqltune_time_limit_sec":',
        ',"repeat_policy":',
        "FUNCTION normalize_run_advisor",
        "FUNCTION normalize_sqltune_time_sec",
        "DBMS_LOB.SUBSTR(l_advisor_report, 13, 1) = 'SQLTUNE_ERROR'",
        ',"repeat_count":',
        "ORDER  BY last_active_time DESC NULLS LAST",
        "SQL*Plus slash terminator is not allowed",
        "DBMS_SQLTUNE",
        "NLS_NUMERIC_CHARACTERS=.,",
    ],
    "db/adb/asta_sql_guard_pkg.sql": [
        "CREATE OR REPLACE PACKAGE asta_sql_guard_pkg",
        "PROCEDURE assert_safe_select",
        "FUNCTION scrub_guard_text",
        "FUNCTION extract_candidate_sql",
        "FUNCTION inspect_sql",
        "C_MAX_SQL_CHARS CONSTANT PLS_INTEGER := 32767",
        "Statement terminator is not allowed",
        "SQL*Plus slash terminator is not allowed",
        "$.candidate_sql",
        "ASTA_SQL_GUARD",
        '"contract_version":"asta.v1"',
        '"execution_boundary":"ADB_SQL_GUARD_PLSQL"',
    ],
    "db/adb/asta_source_bridge_pkg.sql": [
        "CREATE OR REPLACE PACKAGE asta_source_bridge_pkg",
        "FUNCTION run_source_evidence",
        "FUNCTION get_connection_json",
        "asta_source_connections",
        "FUNCTION validated_db_link_name",
        "FUNCTION validated_schema_name",
        "FUNCTION validated_source_db_id",
        "FUNCTION normalized_fetch_rows",
        "FUNCTION normalized_repeat_policy",
        "FUNCTION normalized_run_advisor",
        "FUNCTION normalized_sqltune_time_sec",
        "source_db_id = l_source_db_id",
        "asta_sql_guard_pkg.assert_safe_select(p_sql)",
        "asta_source_pkg.run_evidence_store_proc@",
        "Source helper returned empty chunked response",
        '"status":"COMPLETED","code":"SOURCE_CONNECTION"',
        '"connection_source":"ASTA_SOURCE_CONNECTIONS"',
        '"execution_boundary":"ADB_SOURCE_BRIDGE_DBLINK"',
        '"contract_version":"asta.v1"',
    ],
    "db/adb/asta_vector_pkg.sql": [
        "CREATE OR REPLACE PACKAGE asta_vector_pkg",
        "FUNCTION search_similar_cases",
        "FUNCTION save_case",
        "FUNCTION object_exists",
        "FUNCTION sql_fingerprint",
        "FUNCTION normalized_top_k",
        "FUNCTION validated_case_id",
        "user_objects",
        "STANDARD_HASH",
        "query_fingerprint",
        "source_fingerprint",
        '"contract_version":"asta.v1"',
        '"execution_boundary":"ADB_VECTOR_PLSQL"',
        "l_query_fingerprint VARCHAR2(128) := sql_fingerprint(p_sql)",
        "ASTA_TUNING_CASE",
    ],
    "db/adb/asta_llm_pkg.sql": [
        "CREATE OR REPLACE PACKAGE asta_llm_pkg",
        "FUNCTION build_tuning_prompt",
        "FUNCTION generate_tuning",
        "FUNCTION validated_profile_name",
        "FUNCTION final_review",
        "FUNCTION generate_sql_only_tuning",
        "Tune this Oracle SQL using the supplied runtime evidence",
        "SQL_ONLY_REWRITE",
        "ASTA_GROK_GENAI_PROFILE",
        "ASTA_DB_GENAI_TEST",
        "candidate_sql must be a single safe Oracle SELECT or WITH statement",
        "Return JSON only; do not wrap the response in Markdown fences.",
        "asta_sql_guard_pkg.assert_safe_select(p_sql)",
        "asta_sql_guard_pkg.extract_candidate_sql",
        "candidate_error",
        "LLM_FINAL_REVIEW",
        "ADB_DBMS_CLOUD_AI",
        '"contract_version":"asta.v1"',
        "profile_name must start with ASTA",
        "DBMS_CLOUD_AI.GENERATE",
    ],
    "db/adb/asta_report_pkg.sql": [
        "CREATE OR REPLACE PACKAGE asta_report_pkg",
        "FUNCTION build_report",
        "FUNCTION build_response_json",
        "p_progress_json",
        "p_final_review_json",
        "p_after_evidence_json",
        "p_comparison_json",
        "p_vector_save_json",
        "clob_app_clob(l_out, p_progress_json)",
        "튜닝 SQL",
        "## 튜닝 후 SQL",
        "튜닝 전/후 수치 비교",
        "## 튜닝 결과",
        "### Before/After 핵심 비교",
        "## LLM 튜닝 요약",
        "raw_response 원문은 API artifacts.llm에만 보존",
        "ADB_REPORT_PLSQL",
        '"contract_version":"asta.v1"',
        '"report_source":"ADB_REPORT_PLSQL"',
        "migration_boundary",
        "ORDS_PROXY_ONLY",
        "SOURCE_BASEDB_DBLINK_ONLY",
        '"candidate_sql":',
        ',"runtime_evidence":',
        ',"after_evidence":',
        ',"comparison":',
        ',"vector_save":',
        ',"final_review":',
        "ADB_ORDS_PLSQL",
    ],
    "db/adb/asta_pkg.sql": [
        "CREATE OR REPLACE PACKAGE asta_pkg",
        "FUNCTION analyze_sql",
        "FUNCTION list_profiles",
        "FUNCTION get_progress",
        "FUNCTION normalize_source_db_id",
        "FUNCTION normalize_run_id",
        "FUNCTION migration_boundary_json",
        "FUNCTION normalized_fetch_rows",
        "FUNCTION normalized_vector_top_k",
        "FUNCTION normalized_sqltune_time_limit",
        "FUNCTION build_comparison_json",
        "FUNCTION build_progress_array_json",
        "FUNCTION source_response_error_message",
        "advisor_progress_status",
        "progress_status_from_json",
        "BEFORE_AFTER_COMPARISON",
        "ADB_COMPARISON_PLSQL",
        "elapsed_ms_between",
        "source_db_id",
        "No structural rewrite candidate",
        "l_comparison_json := build_comparison_json(l_source_json, l_after_json, l_workload_type)",
        "asta_source_bridge_pkg.get_connection_json",
        "asta_source_bridge_pkg.run_source_evidence",
        "asta_llm_pkg.generate_sql_only_tuning",
        "DETERMINISTIC_COMPARISON",
        "asta_report_pkg.build_response_json",
        "p_after_evidence_json  => l_after_json",
        "p_comparison_json      => l_comparison_json",
        "p_vector_save_json     => l_vector_save_json",
        "p_progress_json        => l_progress_json",
        "p_final_review_json    => l_final_review_json",
        "RUN_LOOKUP",
        "PROGRESS_LOOKUP",
        "REPORT_LOOKUP",
        '"contract_version":"asta.v1"',
    ],
    "db/ords/asta_ords_module.sql": [
        "ORDS.DELETE_MODULE",
        "ORDS.DEFINE_MODULE",
        "ORDS.DEFINE_HANDLER",
        "ASTA_PKG.SUBMIT_RUN(:body_text)",
        "ASTA_PKG.LIST_PROFILES",
        "ASTA_PKG.GET_RUN(:run_id)",
        "ASTA_PKG.GET_PROGRESS(:run_id)",
        "ASTA_PKG.GET_REPORT(:run_id)",
        "Pragma: no-cache",
        "X-Content-Type-Options: nosniff",
        "X-ASTA-Execution-Boundary: ADB_ORDS_PLSQL",
        "X-ASTA-Api-Version: asta.v1",
        "X-ASTA-Contract-Version: asta.v1",
        "X-ASTA-Response-Mode: CLOB_CHUNKED_JSON",
    ],
}

ADB_DDL_FILES = {
    "db/asta/001_asta_repository.sql": [
        "CREATE TABLE asta_runs",
        "source_db_id        VARCHAR2(64)",
        "CREATE TABLE asta_run_progress",
        "CONSTRAINT asta_run_progress_pk PRIMARY KEY",
    ],
    "db/asta/002_asta_source_connections.sql": [
        "CREATE TABLE asta_source_connections",
        "CONSTRAINT asta_source_conn_pk PRIMARY KEY",
        "CHECK (enabled IN ('Y', 'N'))",
    ],
    "db/asta/003_asta_runs_source_db_id.sql": [
        "ALTER TABLE asta_runs ADD (source_db_id VARCHAR2(64))",
        "user_tab_cols",
        "SOURCE_DB_ID",
    ],
    "db/asta/004_asta_vector_tables.sql": [
        "CREATE TABLE asta_tuning_cases",
        "sql_fingerprint",
        "CHECK (metadata_json IS JSON)",
        "CREATE TABLE asta_tuning_case_chunks",
        "CONSTRAINT atcc_case_fk FOREIGN KEY",
        "ON DELETE CASCADE",
        "CREATE INDEX atc_fingerprint_idx",
        "CREATE INDEX atcc_case_idx",
    ],
}

EXPECTED_PROGRESS_CODES = [
    "REQUEST_RECEIVED",
    "ORDS_DISPATCH",
    "SQL_GUARD",
    "BEFORE_EVIDENCE",
    "SQL_TUNING_ADVISOR",
    "LLM_REWRITE",
    "AFTER_EVIDENCE",
    "BEFORE_AFTER_COMPARE",
    "VECTOR_KB",
    "FINAL_REPORT",
    "VECTOR_SAVE",
]


def _read(rel_path: str) -> str:
    """ASTA 내부 처리 보조 함수: read."""
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_asta_proxy_should_not_reference_source_runtime_subprocess_after_migration():
    """ASTA 계약/회귀 조건을 검증한다: asta proxy should not reference source runtime subprocess after migration."""
    src = _read("app/routers/asta_proxy.py")
    assert "source_runtime_xplan.py" not in src
    assert "subprocess.run" not in src
    assert "ASTA_SOURCE_DB_PASSWORD" not in src
    assert "SOURCE_DB_SECRET_FILE" not in src


def test_asta_proxy_should_call_ords_analyze_after_migration():
    """ASTA 계약/회귀 조건을 검증한다: asta proxy should call ords analyze after migration."""
    src = _read("app/routers/asta_proxy.py")
    assert "ORDS" in src or "ords" in src
    assert "analyze_path" in src
    assert "profiles_path" in src
    assert "ADB_ORDS" in src
    assert "db.fetch_all" not in src
    assert "USER_CLOUD_AI_PROFILES" not in src
    assert "_fetch_local_profiles" not in src


def test_plsql_artifact_files_exist_for_asta_adb_ords_migration():
    """ASTA 계약/회귀 조건을 검증한다: plsql artifact files exist for asta adb ords migration."""
    for rel_path in [*ADB_DDL_FILES, *ADB_PACKAGE_FILES]:
        assert (ROOT / rel_path).is_file(), rel_path
    assert (ROOT / "db/source/README.md").is_file()
    assert (ROOT / "db/adb/README.md").is_file()


def test_plsql_artifact_contracts_are_present():
    """ASTA 계약/회귀 조건을 검증한다: plsql artifact contracts are present."""
    for rel_path, expected_fragments in {**ADB_DDL_FILES, **ADB_PACKAGE_FILES}.items():
        src = _read(rel_path)
        for fragment in expected_fragments:
            assert fragment in src, f"{fragment!r} missing from {rel_path}"


def test_ords_handlers_cover_required_asta_routes():
    """ASTA 계약/회귀 조건을 검증한다: ords handlers cover required asta routes."""
    src = _read("db/ords/asta_ords_module.sql")
    for fragment in [
        "p_base_path      => 'asta/'",
        "p_pattern     => 'analyze'",
        "p_method      => 'POST'",
        "p_pattern     => 'profiles'",
        "p_pattern     => 'runs/:run_id'",
        "p_pattern     => 'runs/:run_id/progress'",
        "ASTA_PKG.GET_PROGRESS(:run_id)",
        "p_pattern     => 'runs/:run_id/report'",
        "HTP.prn(l_chunk)",
    ]:
        assert fragment in src
    assert src.count("X-Content-Type-Options: nosniff") == 5
    assert src.count("X-ASTA-Execution-Boundary: ADB_ORDS_PLSQL") == 5
    assert src.count("X-ASTA-Api-Version: asta.v1") == 5
    assert src.count("X-ASTA-Contract-Version: asta.v1") == 5
    assert src.count("X-ASTA-Response-Mode: CLOB_CHUNKED_JSON") == 5


def test_plsql_progress_codes_match_ui_contract():
    """ASTA 계약/회귀 조건을 검증한다: plsql progress codes match ui contract."""
    adb_main = _read("db/adb/asta_pkg.sql")
    report = _read("db/adb/asta_report_pkg.sql")
    ui = _read("static/js/extensions/tuning_assistant.js")
    for code in EXPECTED_PROGRESS_CODES:
        assert code in adb_main, f"{code!r} missing from db/adb/asta_pkg.sql"
    # Task 7에서 report/UI 표시 계약은 별도로 갱신한다.
    for code in [c for c in EXPECTED_PROGRESS_CODES if c != "BEFORE_AFTER_COMPARE"]:
        assert code in report, f"{code!r} missing from db/adb/asta_report_pkg.sql"
        assert code in ui, f"{code!r} missing from tuning assistant DEFAULT_STEPS"


def test_ords_progress_handler_does_not_reuse_full_run_payload():
    """ASTA 계약/회귀 조건을 검증한다: ords progress handler does not reuse full run payload."""
    src = _read("db/ords/asta_ords_module.sql")
    progress_section = src.split("p_pattern     => 'runs/:run_id/progress'", 1)[1]
    progress_section = progress_section.split("p_pattern     => 'runs/:run_id/report'", 1)[0]
    assert "ASTA_PKG.GET_PROGRESS(:run_id)" in progress_section
    assert "ASTA_PKG.GET_RUN(:run_id)" not in progress_section


def test_adb_main_resolves_source_connection_from_allowlist():
    """ASTA 계약/회귀 조건을 검증한다: adb main resolves source connection from allowlist."""
    src = _read("db/adb/asta_pkg.sql")
    lookup_pos = src.index("l_source_connection_json := asta_source_bridge_pkg.get_connection_json(l_source_db_id)")
    run_pos = src.index("l_source_json := asta_source_bridge_pkg.run_source_evidence")
    assert lookup_pos < run_pos
    assert "p_source_db_id     => l_source_db_id" in src
    assert "ASTA_PKG: Source connection lookup did not return db_link_name" in src
    assert "JSON_VALUE(p_body_json, '$.source_schema'" not in src
    assert "JSON_VALUE(p_body_json, '$.source_db_link'" not in src
    assert "C_DEFAULT_SOURCE_SCHEMA" not in src
    assert "C_DEFAULT_SOURCE_DB_LINK" not in src
    assert "l_source_schema := JSON_VALUE(l_source_connection_json, '$.source_schema'" in src
    assert "l_source_db_link := JSON_VALUE(l_source_connection_json, '$.db_link_name'" in src


def test_source_helper_captures_sqltune_task_name_and_validates_repeat_policy():
    """ASTA 계약/회귀 조건을 검증한다: source helper captures sqltune task name and validates repeat policy."""
    src = _read("db/source/asta_source_pkg.sql")
    assert src.count("l_created_task := DBMS_SQLTUNE.CREATE_TUNING_TASK") == 2
    assert "DBMS_SQLTUNE.EXECUTE_TUNING_TASK(task_name => l_task)" in src
    assert "FUNCTION normalize_run_advisor(p_run_advisor IN VARCHAR2) RETURN VARCHAR2" in src
    assert "FUNCTION normalize_sqltune_time_sec(p_sqltune_time_sec IN NUMBER) RETURN PLS_INTEGER" in src
    assert "l_run_advisor := normalize_run_advisor(p_run_advisor)" in src
    assert "l_sqltune_time_sec := normalize_sqltune_time_sec(p_sqltune_time_sec)" in src
    assert ',"advisor_requested":' in src
    assert ',"sqltune_time_limit_sec":' in src
    assert "DBMS_LOB.SUBSTR(l_advisor_report, 13, 1) = 'SQLTUNE_ERROR'" in src
    assert "REGEXP_LIKE(l_policy, '^REPEAT:[0-9]+$')" in src
    assert "ASTA_SOURCE: invalid repeat_policy" in src
    assert "l_guard    := scrub_guard_text(l_head)" in src
    assert "REGEXP_LIKE(l_guard" in src


def test_adb_guard_extracts_candidate_sql_only_after_guard_validation():
    """ASTA 계약/회귀 조건을 검증한다: adb guard extracts candidate sql only after guard validation."""
    src = _read("db/adb/asta_sql_guard_pkg.sql")
    assert "FUNCTION extract_candidate_sql(p_llm_text IN CLOB) RETURN CLOB" in src
    assert "JSON_VALUE(" in src
    assert "$.candidate_sql" in src
    assert "DBMS_LOB.INSTR(p_llm_text, l_marker" in src
    assert "JSON-looking text with literal newlines" in src
    assert "DBMS_LOB.INSTR(p_llm_text, '\",\"change_reason\"'" in src
    assert "l_candidate_vc := REPLACE(l_candidate_vc, '\\n', CHR(10))" in src
    assert "assert_safe_select(l_candidate)" in src
    assert '"execution_boundary":"ADB_SQL_GUARD_PLSQL"' in src
    assert '"contract_version":"asta.v1"' in src


def test_vector_and_llm_packages_emit_boundary_and_json_only_contracts():
    """ASTA 계약/회귀 조건을 검증한다: vector and llm packages emit boundary and json only contracts."""
    vector = _read("db/adb/asta_vector_pkg.sql")
    llm = _read("db/adb/asta_llm_pkg.sql")
    assert vector.count('"execution_boundary":"ADB_VECTOR_PLSQL"') >= 5
    assert vector.count('"contract_version":"asta.v1"') >= 5
    assert llm.count("Return JSON only; do not wrap the response in Markdown fences.") == 3
    assert '"execution_boundary":"ADB_DBMS_CLOUD_AI"' in llm
    assert '"contract_version":"asta.v1"' in llm


def test_plsql_sql_guard_length_matches_varchar_scrub_window():
    """ASTA 계약/회귀 조건을 검증한다: plsql sql guard length matches varchar scrub window."""
    for rel_path in ["db/source/asta_source_pkg.sql", "db/adb/asta_sql_guard_pkg.sql"]:
        src = _read(rel_path)
        assert "C_MAX_SQL_CHARS" in src
        assert "32767" in src
        assert "DBMS_LOB.SUBSTR(p_sql, 32767, 1)" in src
        assert "C_MAX_SQL_CHARS CONSTANT PLS_INTEGER := 65535" not in src
        assert "C_MAX_SQL_CHARS  CONSTANT PLS_INTEGER := 65535" not in src
        assert "SQL*Plus slash terminator is not allowed" in src


def test_adb_main_and_bridge_clamp_request_controlled_runtime_limits():
    """ASTA 계약/회귀 조건을 검증한다: adb main and bridge clamp request controlled runtime limits."""
    bridge = _read("db/adb/asta_source_bridge_pkg.sql")
    main = _read("db/adb/asta_pkg.sql")

    for fragment in [
        '"execution_boundary":"ADB_SOURCE_BRIDGE_DBLINK"',
        '"connection_source":"ASTA_SOURCE_CONNECTIONS"',
        '"contract_version":"asta.v1"',
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

    parse_pos = main.index("JSON_VALUE(p_body_json, '$.sqltune_time_limit'")
    normalize_pos = main.index("l_sqltune_time_limit := normalized_sqltune_time_limit(l_sqltune_time_limit)")
    source_pos = main.index("l_source_json := asta_source_bridge_pkg.run_source_evidence")
    assert parse_pos < normalize_pos < source_pos


def test_analyze_response_uses_persisted_progress_rows():
    """ASTA 계약/회귀 조건을 검증한다: analyze response uses persisted progress rows."""
    main = _read("db/adb/asta_pkg.sql")
    report = _read("db/adb/asta_report_pkg.sql")
    assert "FUNCTION build_progress_array_json(p_run_id IN VARCHAR2) RETURN CLOB" in main
    assert "FROM   asta_run_progress" in main
    assert "clob_app_clob(l_out, build_progress_array_json(l_run_id))" in main
    assert "p_progress_json        IN CLOB DEFAULT NULL" in report
    assert "IF p_progress_json IS NULL OR NVL(DBMS_LOB.GETLENGTH(p_progress_json), 0) = 0 THEN" in report
    assert "clob_app_clob(l_out, p_progress_json)" in report
    assert main.count("p_progress_json        => l_progress_json") == 2

    final_done_pos = main.index("record_progress(l_run_id, 10, 'FINAL_REPORT', 'Final report synthesis', 'DONE')")
    vector_save_pos = main.index("l_vector_save_json := asta_vector_pkg.save_case(")
    progress_pos = main.index("l_progress_json := build_progress_array_json(l_run_id)")
    response_pos = main.index("p_progress_json        => l_progress_json")
    assert vector_save_pos < final_done_pos < progress_pos < response_pos


def test_adb_public_run_lookup_contracts_are_validated_and_boundary_tagged():
    """ASTA 계약/회귀 조건을 검증한다: adb public run lookup contracts are validated and boundary tagged."""
    src = _read("db/adb/asta_pkg.sql")
    assert "FUNCTION normalize_run_id(p_run_id IN VARCHAR2) RETURN VARCHAR2" in src
    assert "ASTA_PKG: invalid run_id" in src
    # 조회 3개, Scheduler 실행, candidate-timeout watchdog 진입점이 동일한 검증을 사용한다.
    assert src.count("l_run_id := normalize_run_id(p_run_id)") == 5
    assert "FUNCTION migration_boundary_json RETURN VARCHAR2" in src
    assert '"contract_version":"asta.v1"' in src
    assert '"architecture":"ADB_ORDS_PLSQL"' in src
    assert '"migration_boundary":{"fastapi_role":"ORDS_PROXY_ONLY"' in src
    assert '"python_local_asta":false' in src
    assert "RUN_LOOKUP" in src
    assert "PROGRESS_LOOKUP" in src
    assert "REPORT_LOOKUP" in src


def test_adb_main_uses_llm_candidate_for_tuned_evidence_without_python_runtime():
    """ASTA 계약/회귀 조건을 검증한다: adb main uses llm candidate for tuned evidence without python runtime."""
    src = _read("db/adb/asta_pkg.sql")
    llm_pos = src.index("l_llm_json := asta_llm_pkg.generate_sql_only_tuning")
    extract_pos = src.index("SELECT JSON_VALUE(l_llm_json, '$.candidate_sql'")
    after_pos = src.index("l_after_json := asta_source_bridge_pkg.run_source_evidence")
    comparison_pos = src.index("l_comparison_json := build_comparison_json")
    assert llm_pos < extract_pos < after_pos < comparison_pos
    assert "asta_llm_pkg.final_review(" not in src
    assert "p_run_id           => l_run_id || '-TUNED'" in src
    assert "p_run_advisor      => 'N'" in src


def test_adb_main_builds_canonical_before_after_comparison_in_plsql():
    """ASTA 계약/회귀 조건을 검증한다: adb main builds canonical before after comparison in plsql."""
    src = _read("db/adb/asta_pkg.sql")
    report = _read("db/adb/asta_report_pkg.sql")
    assert "FUNCTION build_comparison_json(p_before_json IN CLOB, p_after_json IN CLOB," in src
    assert "JSON_VALUE(p_before_json, '$.last_cr_buffer_gets' RETURNING NUMBER NULL ON ERROR)" in src
    assert "JSON_VALUE(p_after_json, '$.last_cr_buffer_gets' RETURNING NUMBER NULL ON ERROR)" in src
    assert '"buffer_gets_reduction_pct":' in src
    assert '"row_count_matches":' in src
    assert '"disk_reads_delta":' in src
    assert '"execution_boundary":"ADB_COMPARISON_PLSQL"' in src
    assert '"contract_version":"asta.v1"' in src
    assert "DBMS_LOB.CREATETEMPORARY(l_before_after_json, TRUE)" in src

    after_pos = src.index("l_after_json := asta_source_bridge_pkg.run_source_evidence")
    comparison_pos = src.index("l_comparison_json := build_comparison_json(l_source_json, l_after_json, l_workload_type)")
    vector_pos = src.index("l_vector_json := asta_vector_pkg.search_similar_cases")
    llm_pos = src.index("l_llm_json := asta_llm_pkg.generate_sql_only_tuning")
    assert vector_pos < llm_pos < after_pos < comparison_pos

    assert "p_after_evidence_json  => l_after_json" in src
    assert "p_comparison_json      => l_comparison_json" in src
    assert "p_vector_save_json     => l_vector_save_json" in src
    assert src.count("p_comparison_json      => l_comparison_json") == 4
    assert '"report_source":"ADB_REPORT_PLSQL"' in report
    assert '"contract_version":"asta.v1"' in report
    assert '"contract_version":"asta.v1"' in report
    assert '"report_source":"ADB_REPORT_PLSQL"' in report
    assert ',"runtime_evidence":' in report
    assert ',"after_evidence":' in report
    assert ',"comparison":' in report
    assert ',"vector_save":' in report

    for path in ["$.before_disk_reads", "$.after_disk_reads"]:
        assert f"json_vc(p_comparison_json, '{path}')" in report


def test_production_asta_paths_forbid_python_local_runtime_strings():
    """ASTA 계약/회귀 조건을 검증한다: production asta paths forbid python local runtime strings."""
    forbidden = [
        "source_runtime_xplan.py",
        "subprocess.run",
        "ASTA_SOURCE_DB_PASSWORD",
        "SOURCE_DB_SECRET_FILE",
        "PYTHON_ASTA_STREAM",
        "BASEDB_SOURCE_DIRECT",
        "oracledb.connect",
    ]
    for rel_path in ASTA_PRODUCTION_PATHS:
        src = _read(rel_path)
        for fragment in forbidden:
            assert fragment not in src, f"{fragment!r} leaked into {rel_path}"


def test_fastapi_asta_surface_forbids_python_local_runtime_strings():
    """ASTA 계약/회귀 조건을 검증한다: fastapi asta surface forbids python local runtime strings."""
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
        "USER_CLOUD_AI_PROFILES",
        "db.fetch_all",
        "_fetch_local_profiles",
    ]
    for rel_path in ["app/routers/asta_proxy.py", "static/js/extensions/tuning_assistant.js"]:
        src = _read(rel_path)
        for fragment in forbidden:
            assert fragment not in src, f"{fragment!r} leaked into {rel_path}"
    proxy = _read("app/routers/asta_proxy.py")
    ui = _read("static/js/extensions/tuning_assistant.js")
    assert '"source_schema":' not in proxy
    assert '"source_db_link":' not in proxy
    assert 'out.pop("source_schema", None)' in proxy
    assert 'out.pop("source_db_link", None)' in proxy
    assert "source_schema" not in ui
    assert "source_db_link" not in ui


def test_python_thin_proxy_forbids_database_runtime_responsibilities():
    """ASTA 계약/회귀 조건을 검증한다: python thin proxy forbids database runtime responsibilities."""
    forbidden = [
        "DBMS_XPLAN",
        "DBMS_SQLTUNE",
        "V$SQL",
        "V$SQL_PLAN_STATISTICS_ALL",
        "USER_CLOUD_AI_PROFILES",
        "DBMS_CLOUD_AI",
        "db.fetch_all",
        "_fetch_local_profiles",
        "source_runtime_xplan",
    ]
    for rel_path in PYTHON_THIN_PROXY_PATHS:
        src = _read(rel_path)
        for fragment in forbidden:
            assert fragment not in src, f"{fragment!r} leaked into {rel_path}"
