"""Prompt contracts learned from the verified Run 654959 improvement pattern."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_measured_diagnosis_requires_one_evidence_backed_dominant_target():
    source = (ROOT / "db/adb/asta_llm_pkg.sql").read_text()
    diagnosis = source.split("DBMS_LOB.CREATETEMPORARY(l_diagnosis_prompt", 1)[1].split("FOR i IN 1..2 LOOP", 1)[0]
    assert "DOMINANT_TARGET_CONTRACT" in diagnosis
    for field in (
        "operation_id", "query_block", "object", "original_correlation_or_join_keys",
        "immediate_consumer", "localized_rewrite_boundary", "measured_buffers",
        "measured_a_time", "starts",
    ):
        assert field in diagnosis
    assert "exactly one selected target" in diagnosis


def test_candidate_requires_single_target_acceptance_checklist():
    source = (ROOT / "db/adb/asta_llm_pkg.sql").read_text()
    candidate = source.split("DBMS_LOB.CREATETEMPORARY(l_candidate_prompt", 1)[1].split("FOR i IN 1..4 LOOP", 1)[0]
    assert "CANDIDATE_ACCEPTANCE_CHECKLIST" in candidate
    assert "each helper join can match at most one aggregate/key row" in candidate
    assert "expected Buffer Gets effect" in candidate
    assert "Return exactly NO_REWRITE if any check fails" in candidate
