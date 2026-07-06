import json
from copy import deepcopy
from pathlib import Path

from tools.asta_bind_plan_stability import (
    evaluate_bind_campaign,
    evaluate_bind_plan_stability,
    summarize_plan_sample,
    validate_representative_bind_set,
)
from tools.asta_result_equivalence import build_full_result_evidence


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads(
    (ROOT / "tests/fixtures/asta_customer_01_bind_cases.json").read_text(encoding="utf-8")
)
SUCCESS_PLAN = (ROOT / "tests/fixtures/asta_customer_01_union_barrier_xplan.txt").read_text(encoding="utf-8")
FAILED_PLAN = (ROOT / "tests/fixtures/asta_customer_01_distinct_merged_xplan.txt").read_text(encoding="utf-8")
MEASUREMENTS = json.loads(
    (ROOT / "tests/fixtures/asta_customer_01_measurement_campaign.json").read_text(encoding="utf-8")
)
CUSTOMER_SQL = (ROOT / "tests/fixtures/asta_customer_01_style_not_exists.sql").read_text(encoding="utf-8")


def verified_cases():
    cases = deepcopy(FIXTURE["cases"])
    broad_plan = SUCCESS_PLAN.replace("SORT UNIQUE", "HASH GROUP BY")
    for case in cases:
        case["optimizer_intent"] = {
            "status": "VERIFIED", "allow_downstream_evaluation": True,
            "verdict_reason": "OPTIMIZER_INTENT_VERIFIED",
        }
        case["equivalence"] = {
            "status": "VERIFIED", "allow_performance_measurement": True,
            "reason_code": "RESULT_EQUIVALENCE_VERIFIED",
        }
        plan = broad_plan if case["selectivity_bucket"] == "BROAD" else SUCCESS_PLAN
        case["before_plan_samples"] = [FAILED_PLAN, FAILED_PLAN]
        case["after_plan_samples"] = [plan, plan]
    return cases


def stability_policy():
    return {
        **FIXTURE["policy"],
        "min_plan_samples_per_bind": 2,
        "target_object": "VIF_WHOLESALE_S",
        "expected_plan_families": {
            "NULL": ["SET_OPERATION_BARRIER"],
            "SELECTIVE": ["SET_OPERATION_BARRIER"],
            "BROAD": ["ANTI_SINGLE_PRODUCER"],
        },
    }


def execution_policy(**overrides):
    value = {
        "warmup_runs_per_target": 1,
        "measurement_runs_per_target": 3,
        "max_candidates": 4,
        "max_total_runs": 30,
        "max_total_wall_time_ms": 1_700_000,
        "max_candidate_runs": 12,
        "max_candidate_wall_time_ms": 30_000,
        "per_run_timeout_ms": 180_000,
        "max_noise_pct": 20.0,
    }
    value.update(overrides)
    return value


def campaign_cases():
    cases = verified_cases()
    columns = [{"name": "STYLE_CD", "oracle_type": "VARCHAR2", "max_length": 30}]
    for index, case in enumerate(cases):
        rows = [[f"STYLE-{index}"], [f"STYLE-{index}"]]
        evidence = build_full_result_evidence(CUSTOMER_SQL, columns, rows)
        case["equivalence_evidence"] = {
            "sql_text": CUSTOMER_SQL,
            "before_runs": [{"status": "COMPLETED", **evidence}],
            "after_runs": [{"status": "COMPLETED", **evidence}],
        }
        case["before_runs"] = deepcopy(MEASUREMENTS["before_runs"])
        case["after_runs"] = deepcopy(MEASUREMENTS["after_runs"])
    return cases


def test_representative_bind_set_covers_name_position_type_null_and_selectivity_without_values():
    result = validate_representative_bind_set(FIXTURE["cases"], FIXTURE["policy"])

    assert result["status"] == "VERIFIED"
    assert result["reason_code"] == "BIND_COVERAGE_VERIFIED"
    assert result["bind_case_count"] == 3
    assert result["covered_selectivity_buckets"] == ["BROAD", "NULL", "SELECTIVE"]
    assert result["bind_signature"] == [
        {"name": ":P_STYLE", "position": 1, "oracle_type": "VARCHAR2"}
    ]
    assert result["raw_bind_values_retained"] is False


def test_bind_raw_value_metadata_mismatch_and_before_after_set_mismatch_fail_closed():
    raw = deepcopy(FIXTURE["cases"])
    raw[0]["bindings"][0]["value"] = "customer-secret"
    changed_type = deepcopy(FIXTURE["cases"])
    changed_type[1]["bindings"][0]["oracle_type"] = "NUMBER"
    changed_set = deepcopy(FIXTURE["cases"])
    changed_set[2]["after_bind_fingerprint"] = "sha256:different-bind"
    unsafe_fingerprint = deepcopy(FIXTURE["cases"])
    unsafe_fingerprint[1]["bindings"][0]["value_fingerprint"] = "sha256:customer-secret"

    cases = [
        (raw, "RAW_BIND_VALUE_FORBIDDEN"),
        (changed_type, "BIND_METADATA_MISMATCH"),
        (changed_set, "BEFORE_AFTER_BIND_SET_MISMATCH"),
        (unsafe_fingerprint, "BIND_FINGERPRINT_FORMAT_INVALID"),
    ]
    for bind_cases, expected in cases:
        result = validate_representative_bind_set(bind_cases, FIXTURE["policy"])
        assert result["status"] == "BLOCKED"
        assert result["reason_code"] == expected
        assert result["evaluation_allowed"] is False


def test_missing_bucket_null_semantics_and_minimum_coverage_fail_closed():
    missing_bucket = FIXTURE["cases"][:2]
    invalid_null = deepcopy(FIXTURE["cases"])
    invalid_null[0]["bindings"][0]["is_null"] = False

    coverage = validate_representative_bind_set(missing_bucket, FIXTURE["policy"])
    nulls = validate_representative_bind_set(invalid_null, FIXTURE["policy"])

    assert coverage["status"] == "BLOCKED"
    assert coverage["reason_code"] == "BIND_COVERAGE_INSUFFICIENT"
    assert set(coverage["missing_selectivity_buckets"]) == {"BROAD"}
    assert nulls["status"] == "BLOCKED"
    assert nulls["reason_code"] == "BIND_NULL_SEMANTICS_INVALID"


def test_expected_bind_sensitive_plan_family_variation_is_accepted():
    result = evaluate_bind_plan_stability(verified_cases(), stability_policy())

    assert result["status"] == "VERIFIED"
    assert result["reason_code"] == "BIND_SENSITIVE_PLAN_VARIATION_ACCEPTED"
    assert result["observed_plan_families"] == ["ANTI_SINGLE_PRODUCER", "SET_OPERATION_BARRIER"]
    assert result["plan_hash_only_success"] is False
    assert all(item["stable"] for item in result["bind_results"])


def test_same_plan_hash_with_shape_change_and_plan_flip_are_blocked():
    shape_change = verified_cases()
    shape_change[1]["after_plan_samples"][1] = SUCCESS_PLAN.replace(
        "INDEX FAST FULL SCAN", "TABLE ACCESS FULL   "
    )
    plan_flip = verified_cases()
    plan_flip[1]["after_plan_samples"][1] = FAILED_PLAN

    same_hash = evaluate_bind_plan_stability(shape_change, stability_policy())
    flipped = evaluate_bind_plan_stability(plan_flip, stability_policy())

    assert same_hash["status"] == "BLOCKED"
    assert same_hash["reason_code"] == "PLAN_SHAPE_UNSTABLE"
    assert same_hash["bind_case_id"] == "STYLE_SELECTIVE"
    assert flipped["status"] == "BLOCKED"
    assert flipped["reason_code"] == "PLAN_FLIP_DETECTED"


def test_unstable_starts_and_missing_plan_evidence_fail_closed_while_hash_change_same_shape_is_allowed():
    starts = verified_cases()
    starts[0]["after_plan_samples"][1] = SUCCESS_PLAN.replace(
        "|* 41 |              INDEX FAST FULL SCAN             | TGP_STYDE_L_PK    |      1 |",
        "|* 41 |              INDEX FAST FULL SCAN             | TGP_STYDE_L_PK    |      2 |",
    )
    missing = verified_cases()
    missing[2]["after_plan_samples"] = [SUCCESS_PLAN]
    hash_only_change = verified_cases()
    hash_only_change[0]["after_plan_samples"][1] = SUCCESS_PLAN.replace(
        "Plan hash value: 101251183", "Plan hash value: 909090909"
    )

    unstable = evaluate_bind_plan_stability(starts, stability_policy())
    insufficient = evaluate_bind_plan_stability(missing, stability_policy())
    allowed = evaluate_bind_plan_stability(hash_only_change, stability_policy())

    assert unstable["status"] == "BLOCKED"
    assert unstable["reason_code"] == "STARTS_SUBTREE_UNSTABLE"
    assert insufficient["status"] == "BLOCKED"
    assert insufficient["reason_code"] == "INSUFFICIENT_BIND_PLAN_EVIDENCE"
    assert allowed["status"] == "VERIFIED"
    assert "PLAN_HASH_VARIATION_SHAPE_STABLE" in allowed["reason_codes"]


def test_plan_sample_uses_shape_and_starts_not_plan_hash_as_stability_proof():
    sample = summarize_plan_sample(SUCCESS_PLAN, "VIF_WHOLESALE_S")

    assert sample["status"] == "COMPLETED"
    assert sample["plan_hash"] == 101251183
    assert sample["plan_family"] == "SET_OPERATION_BARRIER"
    assert sample["target_starts"] == 1
    assert sample["shape_signature"]
    assert sample["starts_signature"]


def test_all_representative_binds_must_pass_before_candidate_is_accepted():
    result = evaluate_bind_campaign(
        "NOT_EXISTS_UNION_DISTINCT_BARRIER", campaign_cases(), stability_policy(), execution_policy()
    )

    assert result["status"] == "ACCEPTED"
    assert result["reason_code"] == "BIND_PLAN_STABILITY_VERIFIED"
    assert result["bind_case_count"] == 3
    assert result["successful_bind_count"] == 3
    assert result["worst_after_elapsed_us"] == 1_641_880
    assert result["worst_after_noise_pct"] == 1.758
    assert result["budget_state"]["used_total_runs"] == 24
    assert result["performance_evaluated"] is True


def test_one_bind_latency_regression_rejects_the_whole_candidate():
    cases = campaign_cases()
    for run in cases[2]["after_runs"][1:]:
        run["last_elapsed_time_us"] = 3_100_000

    result = evaluate_bind_campaign(
        "NOT_EXISTS_UNION_DISTINCT_BARRIER", cases, stability_policy(), execution_policy()
    )

    assert result["status"] == "REJECTED"
    assert result["reason_code"] == "BIND_CASE_LATENCY_REGRESSION"
    assert result["failed_bind_case_id"] == "STYLE_BROAD"
    assert result["failed_bind_reason"] == "OLTP_LATENCY_GUARD_NOT_MET"
    assert result["all_representative_binds_passed"] is False


def test_bind_intent_equivalence_or_plan_failure_blocks_before_any_measurement():
    intent_failed = campaign_cases()
    intent_failed[0]["optimizer_intent"]["status"] = "REJECTED"
    equivalence_failed = campaign_cases()
    equivalence_failed[1]["equivalence"]["status"] = "NON_EQUIVALENT"
    plan_failed = campaign_cases()
    plan_failed[2]["after_plan_samples"][1] = FAILED_PLAN

    results = [
        evaluate_bind_campaign("CANDIDATE", cases, stability_policy(), execution_policy())
        for cases in (intent_failed, equivalence_failed, plan_failed)
    ]

    assert [result["reason_code"] for result in results] == [
        "BIND_OPTIMIZER_INTENT_NOT_VERIFIED",
        "BIND_EQUIVALENCE_NOT_VERIFIED",
        "PLAN_FLIP_DETECTED",
    ]
    assert all(result["processed_run_count"] == 0 for result in results)
    assert all(result["performance_evaluated"] is False for result in results)


def test_bind_execution_budget_is_preflighted_across_all_cases():
    result = evaluate_bind_campaign(
        "CANDIDATE", campaign_cases(), stability_policy(), execution_policy(max_total_runs=23)
    )

    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "BIND_EXECUTION_BUDGET_EXCEEDED"
    assert result["budget_reason"] == "TOTAL_RUN_BUDGET_EXCEEDED"
    assert result["processed_run_count"] == 0
    assert result["performance_evaluated"] is False


def test_before_plan_evidence_is_required_and_must_be_stable_independently_of_after_rewrite():
    missing = verified_cases()
    missing[0]["before_plan_samples"] = []
    unstable = verified_cases()
    unstable[1]["before_plan_samples"][1] = SUCCESS_PLAN

    no_before = evaluate_bind_plan_stability(missing, stability_policy())
    baseline_flip = evaluate_bind_plan_stability(unstable, stability_policy())

    assert no_before["status"] == "BLOCKED"
    assert no_before["reason_code"] == "INSUFFICIENT_BEFORE_BIND_PLAN_EVIDENCE"
    assert baseline_flip["status"] == "BLOCKED"
    assert baseline_flip["reason_code"] == "BEFORE_PLAN_UNSTABLE"


def test_bind_specific_equivalence_buffer_and_noise_failures_are_not_hidden_by_other_binds():
    equivalence = campaign_cases()
    equivalence[1]["equivalence_evidence"]["after_runs"][0]["result_digest"] = "different"
    buffers = campaign_cases()
    for run in buffers[1]["after_runs"][1:]:
        run["last_cr_buffer_gets"] = 9_159_788
    noise = campaign_cases()
    for run, elapsed in zip(noise[1]["after_runs"][1:], (1_000_000, 2_000_000, 5_000_000)):
        run["last_elapsed_time_us"] = elapsed

    mismatch = evaluate_bind_campaign("C1", equivalence, stability_policy(), execution_policy())
    regression = evaluate_bind_campaign("C2", buffers, stability_policy(), execution_policy())
    unstable = evaluate_bind_campaign("C3", noise, stability_policy(), execution_policy())

    assert mismatch["reason_code"] == "BIND_CASE_EQUIVALENCE_FAILED"
    assert mismatch["failed_bind_case_id"] == "STYLE_SELECTIVE"
    assert mismatch["processed_run_count"] == 0
    assert mismatch["stability_evaluated"] is False
    assert regression["reason_code"] == "BIND_CASE_PERFORMANCE_REGRESSION"
    assert regression["failed_bind_case_id"] == "STYLE_SELECTIVE"
    assert unstable["reason_code"] == "BIND_CASE_MEASUREMENT_UNSTABLE"
    assert unstable["failed_bind_case_id"] == "STYLE_SELECTIVE"
