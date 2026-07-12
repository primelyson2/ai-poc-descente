"""Customer-facing ASTA Tuning History static contracts."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _ords_handler(source: str, pattern: str) -> str:
    """Return exactly one handler definition, stopping before the next template."""
    template = f"p_pattern     => '{pattern}'"
    template_pos = source.index(template)
    handler_pos = source.index("ORDS.DEFINE_HANDLER(", template_pos)
    next_template = source.find("ORDS.DEFINE_TEMPLATE(", handler_pos)
    return source[handler_pos:next_template if next_template >= 0 else len(source)]


def test_adb_history_returns_bounded_run_summaries_without_full_sql():
    src = (ROOT / "db/adb/asta_pkg.sql").read_text()
    assert "FUNCTION list_history(p_search IN VARCHAR2 DEFAULT NULL, p_limit IN NUMBER DEFAULT 50) RETURN CLOB;" in src
    section = src.split("FUNCTION list_history(p_search IN VARCHAR2 DEFAULT NULL, p_limit IN NUMBER DEFAULT 50) RETURN CLOB IS", 1)[1].split("END list_history;", 1)[0]
    assert "DBMS_LOB.SUBSTR(input_sql, 500, 1) AS sql_preview" in section
    assert "WHERE ROWNUM <= l_limit" in section
    assert '"report_ready"' in section
    assert '"verdict"' in section
    assert "INSTR(UPPER(run_id), UPPER(l_search)) > 0" in section
    assert "DBMS_LOB.INSTR(UPPER(input_sql), UPPER(l_search), 1, 1) > 0" in section
    assert "FUNCTION get_input_sql(p_run_id IN VARCHAR2) RETURN CLOB;" in src
    assert "clob_app_json_str(l_out, l_sql);" in src


def test_ords_and_proxy_expose_a_dedicated_history_endpoint_before_run_id_route():
    ords = (ROOT / "db/ords/asta_ords_module.sql").read_text()
    proxy = (ROOT / "app/routers/asta_proxy.py").read_text()
    assert "p_pattern     => 'history'" in ords
    assert "ASTA_PKG.LIST_HISTORY(p_search => :search)" in ords
    assert "X-ASTA-History-Search" in ords
    assert "ASTA_PKG.GET_INPUT_SQL(:run_id)" in ords
    assert '@router.get("/history")' in proxy
    assert proxy.index('@router.get("/history")') < proxy.index('@router.get("/runs/{run_id}")')


def test_history_and_input_sql_handlers_individually_enforce_sensitive_clob_contracts():
    """각 신규 endpoint가 다른 handler의 헤더/스트리밍 구현에 기대어 통과하지 못하게 한다."""
    ords = (ROOT / "db/ords/asta_ords_module.sql").read_text()
    expected_calls = {
        "history": "ASTA_PKG.LIST_HISTORY(p_search => :search)",
        "runs/:run_id/input-sql": "ASTA_PKG.GET_INPUT_SQL(:run_id)",
    }
    for pattern, package_call in expected_calls.items():
        handler = _ords_handler(ords, pattern)
        assert "p_method      => 'GET'" in handler
        assert "p_source_type => ORDS.source_type_plsql" in handler
        assert package_call in handler
        assert "application/json; charset=utf-8" in handler
        assert "Cache-Control: no-store" in handler
        assert "Pragma: no-cache" in handler
        assert "X-Content-Type-Options: nosniff" in handler
        assert "X-ASTA-Response-Mode: CLOB_CHUNKED_JSON" in handler
        assert "WHILE l_offset <= NVL(DBMS_LOB.GETLENGTH(l_response), 0) LOOP" in handler
        assert "DBMS_LOB.SUBSTR(l_response, 2000, l_offset)" in handler
        assert "HTP.prn(l_chunk)" in handler
        assert "l_offset := l_offset + 2000" in handler

    history = _ords_handler(ords, "history")
    assert "GET_INPUT_SQL" not in history
    input_sql = _ords_handler(ords, "runs/:run_id/input-sql")
    assert "LIST_HISTORY" not in input_sql

    parameter = ords[ords.index("ORDS.DEFINE_PARAMETER("):]
    assert "p_pattern     => 'history'" in parameter
    assert "p_name        => 'X-ASTA-History-Search'" in parameter
    assert "p_bind_variable_name => 'search'" in parameter
    assert "p_source_type => 'HEADER'" in parameter
    assert "p_access_method => 'IN'" in parameter


def test_ui_has_history_menu_and_report_viewer_actions():
    menu = (ROOT / "static/js/extensions/app_extensions.js").read_text()
    view = (ROOT / "static/js/extensions/tuning_assistant.js").read_text()
    assert 'label: "Tuning History"' in menu
    assert 'window.Views.tuningHistory' in view
    assert '`${DEFAULT_ORDS_BASE_URL}/history${suffix}`' in view
    assert "/report/view" in view
    assert "결과서 열기" in view
    assert 'timeZone: "Asia/Seoul"' in view
    assert "Run ID 또는 SQL 키워드로 검색" in view
    assert "?q=${encodeURIComponent(currentSearch)}" in view
    assert "/input-sql" in view
    assert "요청 SQL 전체" in view
