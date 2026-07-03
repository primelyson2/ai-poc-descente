from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_sql_guard_character_buffers_allow_al32utf8_characters():
    for relative_path in (
        "db/adb/asta_sql_guard_pkg.sql",
        "db/source/asta_source_pkg.sql",
    ):
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "l_c1  VARCHAR2(1);" not in source
        assert "l_c2  VARCHAR2(2);" not in source
        assert "l_c1  VARCHAR2(4);" in source
        assert source.count("l_c2  VARCHAR2(8);") >= 2


def test_source_large_object_info_uses_clob_append_path():
    source = (ROOT / "db/source/asta_source_pkg.sql").read_text(encoding="utf-8")
    assert "PROCEDURE clob_app_clob" in source
    assert "clob_app_clob(l_result, l_object_info);" in source
    assert "clob_app(l_result, l_object_info);" not in source
