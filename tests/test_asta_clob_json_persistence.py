from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_multibyte_clob_copy_advances_by_actual_characters():
    for relative in ("db/adb/asta_report_pkg.sql", "db/adb/asta_pkg.sql"):
        source = read(relative)
        helper = source[source.index("PROCEDURE clob_app_clob"):source.index("END clob_app_clob;")]
        assert "DBMS_LOB.SUBSTR(p_val, 8000, l_offset)" in helper
        assert "l_offset := l_offset + LENGTH(l_chunk)" in helper
        assert "EXIT WHEN l_chunk IS NULL" in helper
        assert "l_offset := l_offset + 32767" not in helper


def test_response_persistence_failure_cannot_leave_run_running():
    source = read("db/adb/asta_pkg.sql")
    fallback = source[source.index("l_persist_error := SUBSTR(SQLERRM"):source.index("RETURN l_response_json;", source.index("l_persist_error := SUBSTR(SQLERRM"))]
    assert "status = 'FAILED'" in fallback
    assert "error_code = 'ASTA_PERSIST'" in fallback
    assert "response_json = NULL" in fallback
    assert "COMMIT;" in fallback
