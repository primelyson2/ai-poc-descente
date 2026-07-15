"""Regression contract for preserving diagnosis data through candidate fallback."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_fallback_keeps_stage_one_diagnosis_at_report_contract_paths():
    source = (ROOT / "db/adb/asta_pkg.sql").read_text(encoding="utf-8")
    helper = source.split("FUNCTION llm_original_fallback_json(", 1)[1].split(
        "END llm_original_fallback_json;", 1
    )[0]

    for path in ("$.change_summary", "$.semantic_risks", "$.diagnosis"):
        assert f"JSON_QUERY(p_generation_json, '{path}'" in helper

    assert "clob_app(l_out, ',\"diagnosis\":');" in helper
    assert "clob_app(l_out, ',\"generation\":');" in helper
    assert helper.index(',"diagnosis":') < helper.index(',"generation":')


def test_verified_history_reuse_runs_current_sql_diagnosis_before_reusing_candidate():
    source = (ROOT / "db/adb/asta_pkg.sql").read_text(encoding="utf-8")
    branch = source.split("ELSIF l_history_candidate_sql IS NOT NULL THEN", 1)[1].split("ELSE", 1)[0]

    assert "l_generation_json := asta_llm_pkg.generate_sql_only_tuning(" in branch
    assert "p_source_evidence_json => l_source_json" in branch
    assert "l_history_candidate_sql" in branch
    assert "l_generation_json," in branch
