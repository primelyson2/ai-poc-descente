from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _section(text: str, start: str, end: str) -> str:
    begin = text.index(start)
    return text[begin:text.index(end, begin)]


def test_blocked_candidate_with_after_evidence_remains_visible_but_unadopted():
    report = (ROOT / "db/adb/asta_report_pkg.sql").read_text(encoding="utf-8")
    build = _section(report, "FUNCTION build_report(\n", "END build_report;")

    assert "IF l_verdict <> 'IMPROVED' THEN\n      l_candidate_sql_vc := NULL;" not in build
    assert "l_candidate_sql_vc := llm_field(p_llm_json, 'candidate_sql', NULL);" in build
    assert "l_candidate_executed := l_candidate_sql_vc IS NOT NULL" in build
    assert "현재 적용하지 마세요" in build
    assert "PLAN_ONLY 선별 탈락 후보 SQL — 적용하지 마세요" in build
    assert "append_xplan_raw_section(l_report," in build
    assert "THEN '튜닝 후 예상 Plan' ELSE '튜닝 후 XPLAN' END" in build
    assert "채택되지 않은 후보의 실제 Source PLAN_ONLY 실행 artifact" in build


def test_plan_only_rejection_report_explains_metrics_scope_and_retention_reason():
    report = (ROOT / "db/adb/asta_report_pkg.sql").read_text(encoding="utf-8")
    build = _section(report, "FUNCTION build_report(\n", "END build_report;")

    assert "l_verdict_reason = 'PLAN_SCREEN_OLTP_LATENCY_TARGET_NOT_MET'" not in build
    assert "l_verdict_reason LIKE 'PLAN_SCREEN_%'" in build
    assert "l_rec := l_friendly_reason || ' 전체 결과 동등성은 검증하지 않았으므로 원본 SQL을 계속 사용하세요.'" in build
    assert "전체 결과 동등성은 검증하지 않았으므로 원본 SQL을 계속 사용하세요." in build
    assert "PLAN_ONLY 1회 선별 수치이며 반복 측정과 전체 결과 동등성 검증은 수행하지 않았습니다." in build
    assert "full_result_executed=false" in build
    assert "ROUND((l_before_gets - l_after_gets) * 100 / l_before_gets, 2)" in build


def test_top_level_candidate_contract_still_exposes_only_adopted_sql():
    report = (ROOT / "db/adb/asta_report_pkg.sql").read_text(encoding="utf-8")
    response = _section(report, "FUNCTION build_response_json(\n", "END build_response_json;")

    assert "IF l_verdict = 'IMPROVED' AND llm_has_improved_sql(p_llm_json) THEN" in response
    assert "Keep rejected SQL only in the raw LLM audit artifact" in response


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
