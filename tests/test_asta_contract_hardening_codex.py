"""작성자: 도상훈
파일 용도: ASTA ORDS/ADB 마이그레이션 계약과 회귀 조건을 정적/단위 테스트로 검증한다."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    """ASTA 내부 처리 보조 함수: read."""
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_source_helper_emits_evidence_method_and_metric_source_contracts():
    """ASTA 계약/회귀 조건을 검증한다: source helper emits evidence method and metric source contracts."""
    src = _read("db/source/asta_source_pkg.sql")
    assert '"evidence_method":"BOUNDED_ORDERED_JSON_GATHER_PLAN_STATS"' in src
    assert '"metrics_source":"V$SQL_PLAN_STATISTICS_ALL_LAST"' in src
    assert src.count('"evidence_method":"BOUNDED_ORDERED_JSON_GATHER_PLAN_STATS"') == 2
    assert src.count('"metrics_source":"V$SQL_PLAN_STATISTICS_ALL_LAST"') == 2
    assert '"execution_boundary":"SOURCE_BASEDB_DBLINK_ONLY"' in src


def test_adb_bridge_validates_run_marker_and_clamps_repeat_policy_before_dblink_call():
    """ASTA 계약/회귀 조건을 검증한다: adb bridge validates run marker and clamps repeat policy before dblink call."""
    src = _read("db/adb/asta_source_bridge_pkg.sql")
    assert "C_MAX_REPEATS CONSTANT PLS_INTEGER := 5" in src
    assert "FUNCTION validated_run_id(p_run_id IN VARCHAR2) RETURN VARCHAR2" in src
    assert "ASTA_SOURCE_BRIDGE: invalid run_id marker" in src
    assert "RETURN 'REPEAT:' || TO_CHAR(LEAST(GREATEST(l_repeat, 1), C_MAX_REPEATS))" in src

    resolve_pos = src.index("resolve_connection(p_source_db_id, l_db_link_name, l_source_schema)")
    guard_pos = src.index("asta_sql_guard_pkg.assert_safe_select(p_sql)")
    run_id_pos = src.index("l_run_id := validated_run_id(p_run_id)")
    repeat_pos = src.index("l_repeat_policy := normalized_repeat_policy(p_repeat_policy)")
    stmt_pos = src.index("l_stmt :=")
    bind_pos = src.index("IN  l_run_id,")
    exec_pos = src.index("EXECUTE IMMEDIATE l_stmt")
    assert resolve_pos < guard_pos < run_id_pos < repeat_pos < stmt_pos < exec_pos < bind_pos
    assert "IN  p_run_id," not in src


def test_llm_prompts_keep_candidate_sql_inside_guardable_single_statement_contract():
    """ASTA 계약/회귀 조건을 검증한다: llm prompts keep candidate sql inside guardable single statement contract."""
    src = _read("db/adb/asta_llm_pkg.sql")
    assert "candidate_sql must not include a semicolon or standalone SQL*Plus slash terminator." in src
    assert "Use only the provided before/after JSON metrics; do not invent Source runtime evidence." in src
    assert "asta_sql_guard_pkg.extract_candidate_sql(l_response)" in src
    assert "asta_sql_guard_pkg.assert_safe_select(p_sql)" in src


def test_operational_sql_xplan_path_never_silently_truncates_evidence():
    llm = _read("db/adb/asta_llm_pkg.sql")
    operational = llm[llm.index("FUNCTION generate_sql_only_tuning("):llm.index("END generate_sql_only_tuning;")]
    assert operational.count("clob_app_clob(l_diagnosis_prompt, l_plan_text)") == 1
    assert operational.count("clob_app_clob(l_candidate_prompt, l_plan_text)") == 1
    assert "clob_app_limited(l_diagnosis_prompt" not in operational
    assert "clob_app_limited(l_candidate_prompt" not in operational
    assert 'DBMS_XPLAN (full CLOB; no truncation)' in operational
    assert ',"xplan_truncated":false' in operational


def test_operational_diagnosis_localizes_one_dominant_awr_01_rewrite():
    llm = _read("db/adb/asta_llm_pkg.sql")
    operational = llm[llm.index("FUNCTION generate_sql_only_tuning("):llm.index("END generate_sql_only_tuning;")]
    diagnosis = operational[:operational.index("-- Stage 2: request SQL text only")]
    contract = "Rank XPLAN operations by measured A-Time and Buffers, using Starts to identify repeated work"
    assert contract in diagnosis
    assert "choose exactly one dominant repeated-work operation" in diagnosis
    assert "query block, object, original correlation keys, immediate consumer, and one localized rewrite boundary" in diagnosis
    assert "Do not propose a rewrite when those details cannot be established from the supplied SQL and XPLAN." in diagnosis
    assert diagnosis.index(contract) < diagnosis.index("clob_app_clob(l_diagnosis_prompt, l_plan_text)")


def test_candidate_length_boundary_fails_closed_instead_of_using_a_truncated_sql():
    llm = _read("db/adb/asta_llm_pkg.sql")
    main = _read("db/adb/asta_pkg.sql")
    operational = llm[llm.index("FUNCTION generate_sql_only_tuning("):llm.index("END generate_sql_only_tuning;")]
    assert "FEATURE_LIMITED: candidate SQL exceeds the 32767-character SQL validation boundary" in operational
    assert "truncated SQL is never executed" in operational
    assert "JSON_VALUE(l_llm_json, '$.candidate_sql' RETURNING CLOB NULL ON ERROR)" in main
    assert "l_tuned_sql_vc" not in main


def test_every_direct_llm_prompt_uses_clob_without_32k_prompt_truncation():
    llm = _read("db/adb/asta_llm_pkg.sql")
    proxy = _read("app/routers/asta_proxy.py")
    assert "l_prompt_vc       CLOB;" in llm
    assert "l_prompt_vc := l_prompt;" in llm
    assert "l_prompt_vc := DBMS_LOB.SUBSTR(l_prompt, 32767, 1)" not in llm
    assert "prompt_clob = cur.var(oracledb.DB_TYPE_CLOB)" in proxy
    assert "prompt_clob.setvalue(0, prompt_text)" in proxy
    assert '"prompt": prompt_bind' in proxy
    assert "[truncated for SQL-only LLM prompt]" not in proxy
    assert "sql too long for SQL-only LLM call" not in proxy


def test_sql_normalizer_never_uses_keywords_inside_change_comment_as_sql_start():
    llm = _read("db/adb/asta_llm_pkg.sql")
    normalizer = llm[llm.index("FUNCTION normalize_sql_response("):llm.index("END normalize_sql_response;")]
    assert "l_comment_end" in normalizer
    assert "l_comment_end + 2" in normalizer
    assert "preserve the validated leading change annotation" in normalizer
    assert "IF l_comment_end > 0 AND l_start > l_comment_end THEN" in normalizer


def test_sql_normalizer_drops_model_prose_between_header_and_line_start_sql():
    llm = _read("db/adb/asta_llm_pkg.sql")
    normalizer = llm[llm.index("FUNCTION normalize_sql_response("):llm.index("END normalize_sql_response;")]

    assert "l_header" in normalizer
    assert "drop non-SQL prose between the validated header and executable SQL" in normalizer
    assert "CHR(10) || ')[[:space:]]*WITH[[:space:]]'" in normalizer
    assert "CHR(10) || ')[[:space:]]*SELECT[[:space:]]'" in normalizer
    assert "l_header || CHR(10) || LTRIM(SUBSTR(l_text, l_start))" in normalizer


def test_operational_prompts_treat_ui_user_notes_as_hard_scope():
    llm = _read("db/adb/asta_llm_pkg.sql")
    operational = llm[llm.index("FUNCTION generate_sql_only_tuning("):llm.index("END generate_sql_only_tuning;")]
    assert operational.count("clob_app_clob(l_diagnosis_prompt, p_tuning_context_json)") == 1
    assert operational.count("clob_app_clob(l_candidate_prompt, p_tuning_context_json)") == 1
    assert "Diagnose only the bottleneck named in user_notes and do not add unrelated rewrites" in operational
    assert "Implement only the localized rewrite requested in user_notes; copy every unrelated SQL fragment verbatim" in operational


def test_ords_handlers_emit_runtime_ownership_headers_for_all_json_routes():
    """ASTA 계약/회귀 조건을 검증한다: ords handlers emit runtime ownership headers for all json routes."""
    src = _read("db/ords/asta_ords_module.sql")
    for header in [
        "X-ASTA-Execution-Boundary: ADB_ORDS_PLSQL",
        "X-ASTA-FastAPI-Role: ORDS_PROXY_ONLY",
        "X-ASTA-Source-Runtime: SOURCE_BASEDB_DBLINK_ONLY",
        "X-ASTA-Guard-Policy: SELECT_WITH_SINGLE_STATEMENT",
        "X-ASTA-Api-Version: asta.v1",
        "X-ASTA-Contract-Version: asta.v1",
        "X-ASTA-Response-Mode: CLOB_CHUNKED_JSON",
    ]:
        assert src.count(header) == 6, f"{header!r} must be emitted by every ORDS JSON handler"


def test_fastapi_and_ui_surfaces_still_forbid_python_local_asta_runtime_terms():
    """ASTA 계약/회귀 조건을 검증한다: fastapi and ui surfaces still forbid python local asta runtime terms."""
    forbidden = [
        "source_runtime_xplan.py",
        "subprocess.run",
        "ASTA_SOURCE_DB_PASSWORD",
        "SOURCE_DB_SECRET_FILE",
        "PYTHON_ASTA_STREAM",
        "BASEDB_SOURCE_DIRECT",
        "oracledb.connect",
        "cx_Oracle.connect",
        "DBMS_XPLAN",
        "DBMS_SQLTUNE",
        "V$SQL",
        "V$SQL_PLAN_STATISTICS_ALL",
        "DBMS_CLOUD_AI",
        "USER_CLOUD_AI_PROFILES",
        "db.fetch_all",
        "_fetch_local_profiles",
    ]
    for rel_path in ["app/routers/asta_proxy.py", "static/js/extensions/tuning_assistant.js"]:
        src = _read(rel_path)
        for fragment in forbidden:
            # The customer-visible developer manual names the real Oracle owner
            # APIs as inert text.  They remain forbidden in FastAPI and in the
            # UI execution handler; only the manual code-map constants may name them.
            if rel_path.endswith("tuning_assistant.js") and fragment in {"DBMS_XPLAN", "DBMS_SQLTUNE", "DBMS_CLOUD_AI"}:
                runtime = src[src.index('document.getElementById("asta-run").addEventListener'):]
                assert fragment not in runtime
                continue
            assert fragment not in src, f"{fragment!r} leaked into {rel_path}"


def test_guard_and_response_contract_markers_cross_plsql_and_ords_boundaries():
    """ASTA 계약/회귀 조건을 검증한다: guard and response contract markers cross plsql and ords boundaries."""
    source = _read("db/source/asta_source_pkg.sql")
    guard = _read("db/adb/asta_sql_guard_pkg.sql")
    bridge = _read("db/adb/asta_source_bridge_pkg.sql")
    llm = _read("db/adb/asta_llm_pkg.sql")
    report = _read("db/adb/asta_report_pkg.sql")
    main = _read("db/adb/asta_pkg.sql")
    ords = _read("db/ords/asta_ords_module.sql")

    assert "C_GUARD_POLICY" in source
    assert source.count(',"guard_policy":') == 3
    assert "C_GUARD_POLICY" in guard
    assert guard.count(',"guard_policy":') == 2
    assert '"guard_policy":' in bridge
    assert '"candidate_guard_policy":"SELECT_WITH_SINGLE_STATEMENT"' in llm
    assert '"response_contract":"JSON_ONLY"' in llm
    assert "Guard Policy: `" in report
    assert ',"response_contract":' in report
    assert '"guard_policy":"SELECT_WITH_SINGLE_STATEMENT"' in report
    assert '"response_contract":"CLOB_CHUNKED_JSON"' in report
    assert '"guard_policy":"SELECT_WITH_SINGLE_STATEMENT"' in main
    assert '"response_contract":"CLOB_CHUNKED_JSON"' in main
    assert ords.count("X-ASTA-Guard-Policy: SELECT_WITH_SINGLE_STATEMENT") == 6


def test_vector_kb_saves_searchable_chunks_and_searches_fingerprint_first():
    """ASTA 계약/회귀 조건을 검증한다: vector kb saves searchable chunks and searches fingerprint first."""
    src = _read("db/adb/asta_vector_pkg.sql")
    ddl = _read("db/asta/004_asta_vector_tables.sql")

    for fragment in [
        "C_SEARCH_STRATEGY CONSTANT VARCHAR2(40) := 'FINGERPRINT_FIRST_CHUNK_SCAN'",
        "FUNCTION chunk_clob(p_val IN CLOB) RETURN CLOB",
        "FUNCTION save_case_chunk(",
        "INSERT INTO asta_tuning_case_chunks(",
        "save_case_chunk(l_case_id, 'VERIFIED_OUTCOME'",
        "save_case_chunk(l_case_id, 'PLAN_EVIDENCE'",
        "save_case_chunk(l_case_id, 'METRICS'",
        "save_case_chunk(l_case_id, 'REJECTED_OBSERVATION'",
        "save_case_chunk(l_case_id, 'REJECTION_REASON'",
        "JOIN asta_tuning_cases c ON c.case_id = ch.case_id",
        "CASE WHEN c.sql_fingerprint = :query_fp_order THEN 0 ELSE 1 END",
        "'matched_fingerprint' VALUE matched_fingerprint",
        "'source_fingerprint' VALUE sql_fingerprint",
        ',"search_strategy":',
        ',"chunks_saved":',
        "SAVEPOINT asta_vector_save_case",
        "ROLLBACK TO asta_vector_save_case",
    ]:
        assert fragment in src

    assert "fingerprint-first chunk scan" in ddl
    assert "POSITIVE_VERIFIED" in ddl
    assert "REJECTED_OBSERVATION" in ddl
    assert "raw SQL" in ddl
    assert "save_case_chunk(l_case_id, 'SOURCE_SQL', p_sql)" not in src
    assert "save_case_chunk(l_case_id, 'TUNED_SQL', p_tuned_sql)" not in src
