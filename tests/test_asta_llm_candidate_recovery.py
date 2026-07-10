from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def section(text: str, start: str, end: str) -> str:
    begin = text.index(start)
    return text[begin:text.index(end, begin)]


def test_candidate_fallbacks_are_selected_only_from_existing_profiles():
    llm = (ROOT / "db/adb/asta_llm_pkg.sql").read_text(encoding="utf-8")
    helper = section(
        llm,
        "FUNCTION available_fallback_profile(",
        "END available_fallback_profile;",
    )
    generation = section(
        llm,
        "FUNCTION generate_sql_only_tuning(",
        "END generate_sql_only_tuning;",
    )

    assert "user_cloud_ai_profiles" in helper
    assert "p_ordinal" in helper
    assert helper.index("WHEN 'ASTA_GPT54_PROFILE' THEN 10") < helper.index("WHEN 'ASTA_GROK_REASONING_PROFILE' THEN 20")
    assert helper.index("WHEN 'ASTA_GPT54_PROFILE' THEN 10") < helper.index("WHEN 'ASTA_GROK_GENAI_PROFILE' THEN 30")
    assert "available_fallback_profile(NVL(l_diagnosis_profile, l_profile), i - 1)" in generation
    assert "IF l_try_profile IS NULL THEN CONTINUE; END IF;" in generation
    assert "ASTA_DB_GENAI_TEST" not in llm


def test_guard_rejected_candidate_gets_one_internal_repair_round():
    llm = (ROOT / "db/adb/asta_llm_pkg.sql").read_text(encoding="utf-8")
    generation = section(
        llm,
        "FUNCTION generate_sql_only_tuning(",
        "END generate_sql_only_tuning;",
    )

    assert "l_guard_repair_attempted VARCHAR2(1) := 'N'" in generation
    assert "l_guard_rejected_candidate := l_candidate_sql" in generation
    assert "l_guard_repair_candidate := repair_sql_candidate(" in generation
    assert "p_error_message        => l_guard_error" in generation
    assert "p_source_evidence_json => p_source_evidence_json" in generation
    assert "l_candidate_source := 'GUARD_REPAIR'" in generation
    assert ',"guard_repair_attempted":' in generation


def test_exact_gate_complete_history_is_reused_before_new_llm_generation():
    main = (ROOT / "db/adb/asta_pkg.sql").read_text(encoding="utf-8")
    lookup = section(
        main,
        "FUNCTION verified_history_candidate(",
        "END verified_history_candidate;",
    )
    pipeline = section(main, "FUNCTION run_pipeline(", "END run_pipeline;")

    for required in (
        "DBMS_LOB.GETLENGTH(input_sql) = DBMS_LOB.GETLENGTH(p_sql)",
        "DBMS_LOB.COMPARE(r.input_sql, p_sql) = 0",
        "$.comparison.verdict",
        "$.comparison.optimizer_intent_status",
        "$.comparison.result_digest_scope",
        "$.comparison.equivalence_status",
        "$.comparison.measurement_status",
        "asta_sql_guard_pkg.assert_candidate_compatible(r.tuned_sql)",
    ):
        assert required in lookup
    history = pipeline.index("l_history_candidate_sql := verified_history_candidate(")
    generation = pipeline.index("l_llm_json := asta_llm_pkg.generate_sql_only_tuning(")
    assert history < generation
    assert "'VERIFIED_HISTORY_REUSE'" in pipeline
    assert "p_candidate_source" in main


def test_reused_candidate_does_not_weaken_public_adoption_contract():
    report = (ROOT / "db/adb/asta_report_pkg.sql").read_text(encoding="utf-8")
    response = section(
        report,
        "FUNCTION build_response_json(",
        "END build_response_json;",
    )
    assert "IF l_verdict = 'IMPROVED' AND llm_has_improved_sql(p_llm_json) THEN" in response
