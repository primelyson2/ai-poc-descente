from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def section(source: str, start: str, end: str) -> str:
    offset = source.index(start)
    return source[offset:source.index(end, offset)]


def test_estimated_plan_object_info_collects_real_table_columns():
    source = read("db/source/asta_source_pkg.sql")
    helper = section(
        source,
        "FUNCTION collect_estimated_object_info(",
        "END collect_estimated_object_info;",
    )

    assert "FROM dba_tab_columns" in helper
    assert "owner=t.owner AND table_name=t.table_name" in helper
    assert "ORDER BY column_id" in helper
    assert "FETCH FIRST 120 ROWS ONLY" in helper
    assert "',\"columns\":['" in helper
    for field in ("column_name", "data_type", "nullable", "column_id"):
        assert f"',\"{field}\":'" in helper or f"'{{\"{field}\":'" in helper


def test_adb_builds_bounded_column_only_dictionary_from_source_object_info():
    llm = read("db/adb/asta_llm_pkg.sql")
    helper = section(
        llm,
        "FUNCTION compact_column_dictionary(",
        "END compact_column_dictionary;",
    )

    assert "'$.object_info.table_stats[*]'" in helper
    assert "NESTED PATH '$.columns[*]'" in helper
    assert "column_name VARCHAR2(128) PATH '$.column_name'" in helper
    assert '"max_tables":30' in helper
    assert '"max_columns":600' in helper
    assert "l_table_count >= 30" in helper
    assert "l_column_count >= 600" in helper
    assert "indexes" not in helper.lower()
    assert "num_rows" not in helper.lower()


def test_candidate_stage_receives_authoritative_column_dictionary_before_sql():
    llm = read("db/adb/asta_llm_pkg.sql")
    candidate = section(
        llm,
        "FUNCTION generate_sql_only_tuning(",
        "END generate_sql_only_tuning;",
    )

    assert "l_column_dictionary := compact_column_dictionary(p_source_evidence_json);" in candidate
    dictionary_prompt = candidate.index("AUTHORITATIVE SOURCE COLUMN DICTIONARY JSON follows")
    dictionary_value = candidate.index("clob_app_clob(l_candidate_prompt, l_column_dictionary)")
    original_sql = candidate.index("'SQL:' || CHR(10)", dictionary_value)
    assert dictionary_prompt < dictionary_value < original_sql
    assert "never copy a correlation key from a similar table" in candidate


def test_repair_stage_receives_same_dictionary_and_pipeline_passes_source_evidence():
    llm = read("db/adb/asta_llm_pkg.sql")
    main = read("db/adb/asta_pkg.sql")
    repair = section(
        llm,
        "FUNCTION repair_sql_candidate(",
        "END repair_sql_candidate;",
    )

    assert "p_source_evidence_json IN CLOB DEFAULT NULL" in repair
    assert "l_column_dictionary := compact_column_dictionary(p_source_evidence_json);" in repair
    dictionary_value = repair.index("clob_app_clob(l_prompt, l_column_dictionary)")
    ora_error = repair.index("Oracle execution error to resolve exactly")
    rejected_sql = repair.index("REJECTED CANDIDATE (rewrite this into valid SQL)")
    assert dictionary_value < ora_error < rejected_sql
    assert main.count("p_source_evidence_json => l_source_json") >= 2
    for call in main.split("asta_llm_pkg.repair_sql_candidate(")[1:]:
        assert "p_source_evidence_json => l_source_json" in call[:800]
