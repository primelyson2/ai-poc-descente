from pathlib import Path

VECTOR = (Path(__file__).resolve().parents[1] / "db/adb/asta_vector_pkg.sql").read_text(encoding="utf-8")


def test_sql_preview_truncates_only_at_safe_boundaries_with_marker():
    start = VECTOR.index("FUNCTION sql_preview(p_sql", VECTOR.index("PACKAGE BODY"))
    section = VECTOR[start:VECTOR.index("END sql_preview;", start)]
    assert "... (이하 생략)" in section
    assert "l_last_break" in section
    assert "RETURN SUBSTR(l_out, 1, C_SQL_PREVIEW_CHARS)" not in section
    assert "C_SQL_PREVIEW_LINES + 1" in section
