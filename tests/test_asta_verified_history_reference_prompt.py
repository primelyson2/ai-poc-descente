"""Safe verified-history reference prompt contracts."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "db/adb/asta_llm_pkg.sql"


def test_only_positive_verified_same_workload_metadata_is_compacted_for_prompt_reference():
    src = LLM.read_text()
    section = src.split("FUNCTION compact_verified_history_references(", 1)[1].split("END compact_verified_history_references;", 1)[0]
    assert "verdict = 'IMPROVED'" in section
    assert "learning_class = 'POSITIVE_VERIFIED'" in section
    assert "UPPER(workload_type) = UPPER(p_workload_type)" in section
    assert "sql_preview" not in section
    assert "VERIFIED_HISTORY_PATTERN_REFERENCE_NO_RAW_SQL" in section


def test_reference_is_prompted_only_for_executed_source_and_cannot_override_current_evidence():
    src = LLM.read_text()
    run = src.split("FUNCTION generate_sql_only_tuning(", 1)[1].split("END generate_sql_only_tuning;", 1)[0]
    assert "IF l_source_executed = 'Y' THEN" in run
    assert "VERIFIED_HISTORY_PATTERN_REFERENCE policy" in run
    assert "Current SQL/XPLAN evidence always wins" in run
    assert "Never copy identifiers, literals, predicates, joins, or SQL text" in run
    assert '"verified_history_references_included"' in run
    assert '"verified_history_reference_summary"' in run
    assert "clob_app_clob(l_result, NVL(l_history_references" in run
