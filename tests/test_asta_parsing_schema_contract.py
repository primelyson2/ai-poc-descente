from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_ui_sends_sql_id_only_for_unchanged_collected_samples():
    ui = read("static/js/extensions/tuning_assistant.js")
    assert ui.count("sqlId:") == 1
    assert "formatSql(sample.sql) === formattedSql" in ui
    assert "source_sql_id: matchedSample?.sqlId || null" in ui
    assert "source_schema:" not in ui


def test_adb_forwards_source_sql_id_without_accepting_execution_schema():
    main = read("db/adb/asta_pkg.sql")
    bridge = read("db/adb/asta_source_bridge_pkg.sql")
    assert "'$.source_sql_id' RETURNING VARCHAR2(13)" in main
    assert main.count("p_source_sql_id    => l_source_sql_id") >= 3
    assert "FUNCTION validated_source_sql_id" in bridge
    assert ":source_sql_id, :out_json" in bridge
    assert "validated_schema_name" in bridge


def test_source_resolves_and_restores_awr_parsing_schema():
    source = read("db/source/asta_source_pkg.sql")
    assert "FUNCTION resolve_parsing_schema" in source
    assert "FROM dba_hist_sqlstat" in source
    assert "DBMS_ASSERT.SIMPLE_SQL_NAME" in source
    assert source.count("ALTER SESSION SET CURRENT_SCHEMA") >= 3
    assert '"parsing_schema_name":' in source
