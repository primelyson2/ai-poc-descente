from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = (ROOT / "db/adb/asta_source_bridge_pkg.sql").read_text(encoding="utf-8")
SOURCE = (ROOT / "db/source/asta_source_pkg.sql").read_text(encoding="utf-8")


def test_bridge_converts_sql_clob_with_byte_aware_chunks():
    assert "FUNCTION clob_to_dblink_varchar2(p_val IN CLOB) RETURN VARCHAR2" in BRIDGE
    assert "DBMS_LOB.SUBSTR(p_val, 4000, l_offset)" in BRIDGE
    assert "NVL(LENGTHB(l_out), 0) + LENGTHB(l_chunk) > 32767" in BRIDGE
    assert "l_sql_vc := clob_to_dblink_varchar2(p_sql);" in BRIDGE
    assert "l_sql_vc := DBMS_LOB.SUBSTR(p_sql, 32767, 1);" not in BRIDGE


def test_stage_four_errors_include_plsql_backtrace_without_sql_text():
    assert "DBMS_UTILITY.FORMAT_ERROR_BACKTRACE" in BRIDGE
    assert "error_json('SOURCE_BRIDGE', l_error_message, l_error_backtrace)" in BRIDGE
    assert "DBMS_UTILITY.FORMAT_ERROR_BACKTRACE" in SOURCE
    assert "',\u0022backtrace\u0022:' || json_str(l_error_backtrace)" in SOURCE
    assert "',\u0022backtrace\u0022:' || json_str(l_outer_error_backtrace)" in SOURCE


def test_source_sql_character_scanners_use_multibyte_safe_buffers():
    assert "l_char      VARCHAR2(4);" in SOURCE
    assert "l_next      VARCHAR2(4);" in SOURCE
    assert "l_q_close   VARCHAR2(4);" in SOURCE
    assert "l_ch VARCHAR2(4);" in SOURCE
    assert "l_char      VARCHAR2(1);" not in SOURCE
    assert "l_next      VARCHAR2(1);" not in SOURCE
