import asyncio
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_source_runtime_produces_full_result_and_redacted_child_cursor_evidence():
    source = (ROOT / "db/source/asta_source_pkg.sql").read_text(encoding="utf-8")

    assert "l_result_scope := 'FULL_RESULT'" in source
    assert '"result_digest_mode":' in source
    assert '"result_total_rows":' in source
    assert '"result_evidence_complete":' in source
    assert '"result_truncated":false' in source
    assert "UNORDERED_MULTISET" in source
    assert "ORDERED_ROWS" in source
    assert "collect_child_cursor_evidence" in source
    assert "is_bind_sensitive" in source
    assert "is_bind_aware" in source
    assert "value_fingerprint" in source
    assert '"raw_bind_values_retained":false' in source
    assert '"bind_coverage_status":"BLOCKED"' in source
    assert '"value_string":' not in source


def test_adb_bridge_requests_full_result_without_breaking_public_callers():
    bridge = (ROOT / "db/adb/asta_source_bridge_pkg.sql").read_text(encoding="utf-8")

    assert "p_result_evidence_mode" in bridge
    assert "p_result_max_rows" in bridge
    assert "FULL_RESULT" in bridge
    assert "100000" in bridge


def test_adb_comparison_is_fail_closed_before_performance_and_exposes_gate_fields():
    main = (ROOT / "db/adb/asta_pkg.sql").read_text(encoding="utf-8")
    comparison = main[main.index("FUNCTION build_comparison_json("):main.index("END build_comparison_json;")]

    assert "FULL_RESULT_EVIDENCE_REQUIRED" in comparison
    assert "RESULT_DIGEST_MODE_MISMATCH" in comparison
    assert "RESULT_METADATA_MISMATCH" in comparison
    assert "optimizer_intent_status" in comparison
    assert "bind_stability_status" in comparison
    assert "measurement_status" in comparison
    assert comparison.index("FULL_RESULT_EVIDENCE_REQUIRED") < comparison.index("OLTP_LATENCY_TARGET_NOT_MET")


def test_proxy_runtime_adapter_preserves_terminal_failure_and_never_invents_success():
    from app.asta_runtime_gates import apply_runtime_gates

    payload = {
        "run_id": "OADT2-ASTA-contract",
        "status": "COMPLETED",
        "comparison": {
            "verdict": "IMPROVED",
            "optimizer_intent_status": "VERIFIED",
            "equivalence_status": "VERIFIED",
            "result_digest_scope": "FULL_RESULT",
            "result_digest_mode": "UNORDERED_MULTISET",
            "bind_stability_status": "BLOCKED",
            "bind_stability_reason": "BIND_COVERAGE_INSUFFICIENT",
        },
    }

    gated = apply_runtime_gates(payload)

    assert gated["status"] == "BLOCKED"
    assert gated["workflow_state"]["current_stage"] == "BIND_PLAN_STABILITY"
    assert gated["workflow_state"]["reason_code"] == "BIND_COVERAGE_INSUFFICIENT"
    assert gated["vector_learning"]["classification"] == "REJECTED_OBSERVATION"
    assert gated["vector_learning"]["positive_eligible"] is False


def test_proxy_runtime_adapter_treats_bind_not_applicable_as_verified_non_bind_stage():
    from app.asta_runtime_gates import apply_runtime_gates

    payload = {
        "run_id": "OADT2-ASTA-bindless",
        "status": "COMPLETED",
        "comparison": {
            "verdict": "IMPROVED",
            "optimizer_intent_status": "VERIFIED",
            "optimizer_intent_reason": "OPTIMIZER_INTENT_VERIFIED",
            "equivalence_status": "VERIFIED",
            "equivalence_reason": "RESULT_EQUIVALENCE_VERIFIED",
            "result_digest_scope": "FULL_RESULT",
            "result_digest_mode": "ORDERED_ROWS",
            "bind_stability_status": "NOT_APPLICABLE",
            "bind_stability_reason": "BIND_NOT_APPLICABLE",
            "measurement_status": "ACCEPTED",
            "measurement_reason": "MEASUREMENT_ACCEPTED",
        },
    }

    gated = apply_runtime_gates(payload)

    assert gated["status"] == "COMPLETED"
    assert gated["workflow_state"]["overall_status"] == "ACCEPTED"
    bind_stage = next(stage for stage in gated["workflow_state"]["stages"] if stage["stage"] == "BIND_PLAN_STABILITY")
    assert bind_stage["status"] == "VERIFIED"
    assert bind_stage["reason_code"] == "BIND_NOT_APPLICABLE"
    assert bind_stage["evidence"]["applicability"] == "NOT_APPLICABLE"


def test_source_auto_measurement_contract_is_one_warmup_plus_three_measures():
    source = (ROOT / "db/source/asta_source_pkg.sql").read_text(encoding="utf-8")
    assert "IF l_policy = 'AUTO' THEN\n      RETURN 4;" in source
    for token in (
        '"warmup_count":', '"measurement_count":', '"measurement_status":',
        '"median_elapsed_time_us":', '"median_buffer_gets":',
        '"elapsed_noise_pct":', '"measurement_runs":',
    ):
        assert token in source
    assert "l_elapsed_noise_pct <= 20" in source
    loop = source[source.index("FOR i IN 1..l_repeats LOOP"):source.index("END LOOP;", source.index("FOR i IN 1..l_repeats LOOP"))]
    assert "l_elapsed_us := NULL" in loop
    assert "l_cr_buffer_gets := NULL" in loop


def test_adb_bindless_gate_requires_before_and_after_source_evidence():
    main = (ROOT / "db/adb/asta_pkg.sql").read_text(encoding="utf-8")
    comparison = main[main.index("FUNCTION build_comparison_json("):main.index("END build_comparison_json;")]

    assert "$.child_cursor_evidence.bind_coverage_status" in comparison
    assert "l_before_bind_coverage_status" in comparison
    assert "l_after_bind_coverage_status" in comparison
    assert "l_before_bind_coverage_status, 'BLOCKED'" in comparison
    assert "l_after_bind_coverage_status, 'BLOCKED'" in comparison


def test_proxy_runtime_adapter_is_deterministic_and_masks_original_error():
    from app.asta_runtime_gates import apply_runtime_gates

    payload = {
        "run_id": "OADT2-ASTA-ora",
        "status": "FAILED",
        "comparison": {
            "verdict": "CANDIDATE_FAILED",
            "optimizer_intent_status": "FAILED",
            "verdict_reason": "CANDIDATE_ORACLE_ERROR",
        },
        "error": {"message": "ORA-00933 SELECT * FROM SECRET_T WHERE C='SECRET'"},
    }

    first = apply_runtime_gates(payload)
    second = apply_runtime_gates(payload)

    assert first == second
    assert "ORA-00933" in first["workflow_state"]["original_error"]
    assert "SECRET_T" not in first["workflow_state"]["original_error"]


def test_ui_cache_buster_marks_report_tabs_runtime_asset():
    index = (ROOT / "static/index.html").read_text(encoding="utf-8")
    assert "asta_report_tabs.js?v=20260706_samples14_improved1" in index
    assert "tuning_assistant.js?v=20260706_samples14_improved1" in index
