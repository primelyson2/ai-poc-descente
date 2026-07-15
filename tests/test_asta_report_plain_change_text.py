"""Report text must not expose backend HTML entities in SQL change explanations."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_report_keeps_parentheses_and_arrows_as_plain_text():
    source = (ROOT / "db/adb/asta_report_pkg.sql").read_text(encoding="utf-8")
    helper = source.split("FUNCTION safe_vector_text(p_val IN VARCHAR2) RETURN VARCHAR2 IS", 1)[1].split(
        "END safe_vector_text;", 1
    )[0]

    for entity in ("&amp;", "&lt;", "&gt;", "&#40;", "&#41;"):
        assert entity not in helper
    assert "CHR(0)" in helper
    assert "CHR(13)" in helper
    assert "CHR(10)" in helper


def test_report_uses_one_core_explanation_instead_of_history_target_table():
    source = (ROOT / "db/adb/asta_report_pkg.sql").read_text(encoding="utf-8")
    diagnosis = source.split("PROCEDURE append_bottleneck_diagnosis(", 1)[1].split(
        "END append_bottleneck_diagnosis;", 1
    )[0]

    assert "핵심 병목 설명" in diagnosis
    assert "후보 SQL 변경 주석" not in diagnosis
