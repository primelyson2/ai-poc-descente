from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _section(text: str, start: str, end: str) -> str:
    begin = text.index(start)
    return text[begin:text.index(end, begin)]


def test_blocked_candidate_with_after_evidence_remains_visible_but_unadopted():
    report = (ROOT / "db/adb/asta_report_pkg.sql").read_text(encoding="utf-8")
    build = _section(report, "FUNCTION build_report(\n", "END build_report;")

    assert "IF l_verdict <> 'IMPROVED' THEN\n      l_candidate_sql_vc := NULL;" not in build
    assert "현재 적용하지 마세요" in build
    assert "append_xplan_raw_section(l_report, '튜닝 후 XPLAN', p_after_evidence_json);" in build


def test_optimizer_intent_status_is_derived_instead_of_permanently_blocked():
    main = (ROOT / "db/adb/asta_pkg.sql").read_text(encoding="utf-8")
    comparison = _section(main, "FUNCTION build_comparison_json(", "END build_comparison_json;")

    assert "l_optimizer_intent_status VARCHAR2(30) := 'BLOCKED';" not in comparison
    assert "OPTIMIZER_INTENT_RUNTIME_EVIDENCE_REQUIRED" not in comparison
    assert "OPTIMIZER_INTENT_VERIFIED" in comparison


def test_bindless_sql_is_not_blocked_for_missing_bind_replay():
    source = (ROOT / "db/source/asta_source_pkg.sql").read_text(encoding="utf-8")
    child_evidence = _section(
        source,
        "FUNCTION collect_child_cursor_evidence(",
        "END collect_child_cursor_evidence;",
    )

    assert "BIND_NOT_APPLICABLE" in child_evidence
    assert "bind_placeholder_count" in child_evidence


def test_measurement_status_is_derived_from_runtime_repeats_not_hardcoded():
    main = (ROOT / "db/adb/asta_pkg.sql").read_text(encoding="utf-8")
    comparison = _section(main, "FUNCTION build_comparison_json(", "END build_comparison_json;")

    assert "l_measurement_status VARCHAR2(30) := 'BLOCKED';" not in comparison
    for path in ("$.repeat_count", "$.elapsed_wall_ms"):
        assert path in comparison
    assert "MEASUREMENT_EVIDENCE_INCOMPLETE" in comparison
