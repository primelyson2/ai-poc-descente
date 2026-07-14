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
    assert "p_from_date IN VARCHAR2 DEFAULT NULL" in src
    assert "p_to_date IN VARCHAR2 DEFAULT NULL" in src
    assert "p_verdict IN VARCHAR2 DEFAULT NULL" in src
    section = src.rsplit("FUNCTION list_history(\n    p_search", 1)[1].split("END list_history;", 1)[0]
    assert "DBMS_LOB.SUBSTR(input_sql, 500, 1) AS sql_preview" in section
    assert "WHERE ROWNUM <= l_limit" in section
    assert '"report_ready"' in section
    assert '"verdict"' in section
    assert "INSTR(UPPER(run_id), UPPER(l_search)) > 0" in section
    assert "DBMS_LOB.INSTR(UPPER(input_sql), UPPER(l_search), 1, 1) > 0" in section
    assert "SYSTIMESTAMP AT TIME ZONE 'Asia/Seoul'" in section
    assert "created_at >= l_from_at" in section
    assert "created_at < l_to_at" in section
    assert "l_verdict = 'ALL'" in section
    assert '"date_from"' in section and '"date_to"' in section and '"verdict"' in section
    assert "FUNCTION get_input_sql(p_run_id IN VARCHAR2) RETURN CLOB;" in src
    assert "clob_app_json_str(l_out, l_sql);" in src


def test_ords_and_proxy_expose_a_dedicated_history_endpoint_before_run_id_route():
    ords = (ROOT / "db/ords/asta_ords_module.sql").read_text()
    proxy = (ROOT / "app/routers/asta_proxy.py").read_text()
    assert "p_pattern     => 'history'" in ords
    assert "p_from_date => :from_date" in ords
    assert "p_to_date => :to_date" in ords
    assert "p_verdict => :verdict" in ords
    assert "X-ASTA-History-Search" in ords
    assert "ASTA_PKG.GET_INPUT_SQL(:run_id)" in ords
    assert '@router.get("/history")' in proxy
    assert proxy.index('@router.get("/history")') < proxy.index('@router.get("/runs/{run_id}")')


def test_history_and_input_sql_handlers_individually_enforce_sensitive_clob_contracts():
    """각 신규 endpoint가 다른 handler의 헤더/스트리밍 구현에 기대어 통과하지 못하게 한다."""
    ords = (ROOT / "db/ords/asta_ords_module.sql").read_text()
    expected_calls = {
        "history": "p_verdict => :verdict",
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
    for header, bind in (("X-ASTA-History-From", "from_date"), ("X-ASTA-History-To", "to_date"), ("X-ASTA-History-Verdict", "verdict")):
        assert f"p_name => '{header}'" in parameter
        assert f"p_bind_variable_name => '{bind}'" in parameter


def test_ui_has_history_menu_and_report_viewer_actions():
    menu = (ROOT / "static/js/extensions/app_extensions.js").read_text()
    view = (ROOT / "static/js/extensions/tuning_assistant.js").read_text()
    assert 'label: "Tuning History"' in menu
    assert 'window.Views.tuningHistory' in view
    assert '`${DEFAULT_ORDS_BASE_URL}/history${suffix}`' in view
    assert "/report/view" in view
    assert "결과서 열기" in view
    assert 'timeZone: "Asia/Seoul"' in view
    assert "조회 시작일" in view and "조회 종료일" in view
    assert "IMPROVED" in view and "전체 결과" in view
    assert "let currentFrom = kstDate(-6);" in view
    assert "date_from: currentFrom" in view and "verdict: currentVerdict" in view
    assert "요청일:" in view
    assert "asta-history-row-actions" in view
    assert "const parseAstaTimestamp" in view
    assert "`${raw}Z`" in view
    assert "const filteredRuns" not in view
    assert "const runs = (Array.isArray(data?.runs) ? data.runs : []).filter" in view
    assert 'document.getElementById("asta-history-detail")' not in view
