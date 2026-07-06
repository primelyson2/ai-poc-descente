"""ASTA 결과 품질 agent의 고객 SQL gate와 evidence 선택 테스트."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.asta_quality_agent import (
    apply_workload_overrides,
    calculate_stats,
    choose_variant,
    classify_failure,
    normalize_result,
    report_markdown,
)
from tools.asta_result_equivalence import build_full_result_evidence
from tools.run_asta_prompt_abc_adb import (
    build_ora_retry_prompt,
    build_tuning_context,
    compare_repeated,
    declared_candidate_error,
    generate,
    rotate_modes,
)
from tools.run_asta_prompt_abc import load_samples
import yaml


def config():
    return {
        "quality": {
            "customer_sample_id": "asta-awr-01",
            "customer_min_runs": 3,
            "customer_min_success_rate": 1.0,
            "history_cycles": 5,
            "min_batch_elapsed_reduction_pct": 5,
            "min_oltp_buffer_reduction_pct": 5,
            "max_oltp_elapsed_time_us": 3_000_000,
            "max_oltp_elapsed_increase_us": 300_000,
        },
        "variants": [
            {"id": "A", "evidence": "SQL"},
            {"id": "B", "evidence": "SQL + XPLAN"},
            {"id": "C", "evidence": "FULL"},
        ],
    }


def result(mode: str, elapsed_after: int = 80, equivalent: bool = True):
    return {
        "sample_id": "asta-awr-01",
        "mode": mode,
        "candidate_generated": True,
        "prompt_chars": 1000,
        "comparison": {
            "runtime_shape_equivalent": equivalent,
            "semantic_equivalent": equivalent,
            "equivalence_strength": "RESULT_DIGEST",
            "before_elapsed_time_us": 100,
            "after_elapsed_time_us": elapsed_after,
            "before_buffer_gets": 1000,
            "after_buffer_gets": 900,
        },
    }


def normalized(mode: str, cycle: int, elapsed_after: int = 80, equivalent: bool = True):
    return normalize_result(result(mode, elapsed_after, equivalent), {"asta-awr-01": "OLTP"}, f"cycle-{cycle}")


def test_customer_sql_requires_every_configured_repeat_to_improve():
    rows = [normalized("B", 1), normalized("B", 2), normalized("B", 3, equivalent=False)]
    stats = calculate_stats(rows, config())
    b = next(item for item in stats if item.variant_id == "B")
    assert b.customer_successes == 2
    assert not b.customer_gate_passed
    assert choose_variant(stats) is None


def test_choose_lowest_evidence_variant_that_passes_customer_gate():
    rows = [normalized(mode, cycle) for mode in ("B", "C") for cycle in range(1, 4)]
    stats = calculate_stats(rows, config())
    assert choose_variant(stats).variant_id == "B"


def test_non_equivalent_candidate_never_counts_as_improvement():
    rows = [normalized("A", cycle, equivalent=False) for cycle in range(1, 4)]
    a = calculate_stats(rows, config())[0]
    assert a.customer_successes == 0
    assert not a.customer_gate_passed


def test_customer_oltp_rejects_103_second_candidate_despite_buffer_reduction():
    row = normalize_result({
        "sample_id": "asta-awr-01", "mode": "B", "candidate_generated": True,
        "comparison": {
            "semantic_equivalent": True, "equivalence_strength": "RESULT_DIGEST",
            "before_buffer_gets": 9_160_303, "after_buffer_gets": 3_716_585,
            "before_elapsed_time_us": 126_880_112, "after_elapsed_time_us": 103_026_603,
        },
    }, {"asta-awr-01": "OLTP"}, "legacy")
    stats = calculate_stats([row], config())[1]
    assert row["workload"] == "OLTP"
    assert row["buffer_reduction_pct"] == 59.4273
    assert row["latency_guard_passed"] is False
    assert stats.customer_successes == 0


def test_customer_oltp_accepts_buffer_reduction_only_inside_latency_guard():
    row = normalize_result({
        "sample_id": "asta-awr-01", "mode": "B", "candidate_generated": True,
        "comparison": {
            "semantic_equivalent": True, "equivalence_strength": "RESULT_DIGEST",
            "before_buffer_gets": 1_000_000, "after_buffer_gets": 700_000,
            "before_elapsed_time_us": 1_700_000, "after_elapsed_time_us": 1_500_000,
        },
    }, {"asta-awr-01": "OLTP"}, "target")
    assert row["latency_guard_passed"] is True
    assert calculate_stats([row], config())[1].customer_successes == 1


def test_oltp_three_second_hard_guard_accepts_2_5s_and_rejects_3_1s():
    def quality_row(after_elapsed: int):
        return normalize_result({
            "sample_id": "asta-awr-01", "mode": "B", "candidate_generated": True,
            "comparison": {
                "semantic_equivalent": True, "equivalence_strength": "RESULT_DIGEST",
                "before_buffer_gets": 1_000_000, "after_buffer_gets": 700_000,
                "before_elapsed_time_us": 10_000_000, "after_elapsed_time_us": after_elapsed,
            },
        }, {"asta-awr-01": "OLTP"}, "three-second-boundary")

    def runner_comparison(after_elapsed: int):
        common = {"status": "COMPLETED", "row_count": 1, "last_output_rows": 1, "result_digest": "same"}
        return compare_repeated(
            [{**common, "last_elapsed_time_us": 10_000_000, "last_cr_buffer_gets": 1_000_000}],
            [{**common, "last_elapsed_time_us": after_elapsed, "last_cr_buffer_gets": 700_000}],
            "OLTP",
        )

    assert quality_row(2_500_000)["latency_guard_passed"] is True
    assert quality_row(3_100_000)["latency_guard_passed"] is False
    assert runner_comparison(2_500_000)["latency_guard_passed"] is True
    assert runner_comparison(2_500_000)["oltp_latency_target_us"] == 3_000_000
    assert runner_comparison(3_100_000)["latency_guard_passed"] is False


def test_customer_workload_sources_and_execution_context_are_all_oltp():
    for name in ("asta-quality-agent.yaml", "asta-quality-agent.yaml.example"):
        payload = yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))
        assert payload["sample_workloads"]["asta-awr-01"] == "OLTP"
        assert payload["quality"]["max_oltp_elapsed_time_us"] == 3_000_000
        assert payload["execution_budget"]["defaults"]["warmup_runs_per_target"] == 1
        assert payload["execution_budget"]["defaults"]["measurement_runs_per_target"] == 3
        assert payload["execution_budget"]["defaults"]["max_candidates"] == 4
        assert payload["execution_budget"]["workloads"]["OLTP"]["per_run_timeout_ms"] == 180_000
        assert payload["equivalence_budget"]["max_rows"] == 1_000_000
        assert payload["equivalence_budget"]["max_canonical_bytes"] == 268_435_456
        assert payload["equivalence_budget"]["require_full_result"] is True
        assert payload["bind_stability"]["min_bind_cases"] == 3
        assert payload["bind_stability"]["required_selectivity_buckets"] == ["NULL", "SELECTIVE", "BROAD"]
        assert payload["bind_stability"]["min_plan_samples_per_bind"] == 2
        assert payload["bind_stability"]["max_failed_bind_cases"] == 0
        assert payload["bind_stability"]["retain_raw_bind_values"] is False
    sample = load_samples({"asta-awr-01"})[0]
    assert sample["sqlId"] == "7rcw6d3us86r7"
    assert sample["workload"] == "OLTP"
    context = build_tuning_context("C", sample["workload"], "DOMINANT_NOT_EXISTS")
    assert context["workload_type"] == "OLTP"
    assert context["optimization_goal"] == "MINIMIZE_BUFFER_READS"
    assert context["candidate_strategy"] == "DOMINANT_NOT_EXISTS"


def test_historical_batch_label_is_reinterpreted_with_corrected_oltp_gate():
    legacy = {
        "sample_id": "asta-awr-01", "workload": "BATCH", "candidate_generated": True,
        "semantic_equivalent": True, "equivalent": True,
        "buffer_reduction_pct": 59.4273, "elapsed_reduction_pct": 18.8,
        "before_elapsed_time_us": 126_880_112, "after_elapsed_time_us": 103_026_603,
    }
    row = apply_workload_overrides([legacy], {"asta-awr-01": "OLTP"}, config()["quality"])[0]
    assert row["workload"] == "OLTP"
    assert row["primary_reduction_pct"] == 59.4273
    assert row["latency_guard_passed"] is False
    assert row["failure_category"] == "PERFORMANCE_NOT_IMPROVED"


def test_report_is_review_only_and_blocks_deploy_without_customer_gate():
    rows = [normalized("A", 1)]
    stats = calculate_stats(rows, config())
    report = report_markdown(stats, rows, config(), "cycle-1")
    assert "EXPERIMENT_MORE" in report
    assert "배포하면 안 됩니다" in report
    assert "자동 적용: **없음**" in report
    assert "실패 분류" in report
    assert "PERFORMANCE_NOT_IMPROVED" in report


def test_variant_order_rotates_to_reduce_cache_warming_bias():
    modes = ["A", "B", "C"]
    assert rotate_modes(modes, sample_index=0, cycle_rotation=0) == ["A", "B", "C"]
    assert rotate_modes(modes, sample_index=0, cycle_rotation=1) == ["B", "C", "A"]
    assert rotate_modes(modes, sample_index=1, cycle_rotation=2) == ["A", "B", "C"]


def test_long_prompt_is_bound_as_clob(monkeypatch):
    class Bind:
        value = None

        def setvalue(self, index, value):
            assert index == 0
            self.value = value

    class Cursor:
        def __init__(self):
            self.bind = Bind()
            self.params = None

        def var(self, db_type):
            assert db_type is not None
            return self.bind

        def execute(self, sql, **params):
            self.params = params

        def fetchone(self):
            return ["candidate"]

    cursor = Cursor()
    raw, attempts, _ = generate(cursor, "x" * 40000, "ASTA_TEST", max_attempts=1)
    assert raw == "candidate"
    assert attempts == 1
    assert cursor.bind.value == "x" * 40000
    assert cursor.params["p"] is cursor.bind


def test_json_refusal_preserves_declared_reason_instead_of_empty_candidate():
    raw = '{"candidate_sql":null,"candidate_error":"NO_SAFE_EFFECTIVE_REWRITE"}'
    assert declared_candidate_error(raw) == "NO_SAFE_EFFECTIVE_REWRITE"


def test_oracle_retry_prompt_contains_exact_error_and_failed_sql():
    prompt = build_ora_retry_prompt(
        "original prompt",
        "SELECT broken FROM",
        "ORA-00936: missing expression",
    )
    assert "ORA-00936: missing expression" in prompt
    assert "SELECT broken FROM" in prompt
    assert "Return only one complete executable Oracle SELECT or WITH statement" in prompt


def test_repeated_batch_comparison_uses_median_and_flags_noise():
    before = [
        {"status": "COMPLETED", "row_count": 100, "last_output_rows": 1,
         "last_elapsed_time_us": value, "last_cr_buffer_gets": 1000}
        for value in (100, 101, 99)
    ]
    after = [
        {"status": "COMPLETED", "row_count": 100, "last_output_rows": 1,
         "last_elapsed_time_us": value, "last_cr_buffer_gets": 800}
        for value in (70, 80, 130)
    ]
    comparison = compare_repeated(before, after, workload="BATCH", max_noise_pct=20)
    assert comparison["before_elapsed_time_us"] == 100
    assert comparison["after_elapsed_time_us"] == 80
    assert comparison["elapsed_time_reduction_pct"] == 20.0
    assert comparison["measurement_noisy"] is True
    assert comparison["equivalence_strength"] == "SHAPE_ONLY"
    assert comparison["semantic_equivalent"] is False


def test_runner_with_sql_requires_phase6_full_result_evidence_not_legacy_bounded_digest():
    sql = "select id from t"
    base = {"status": "COMPLETED", "last_elapsed_time_us": 100, "last_cr_buffer_gets": 100}
    legacy = {**base, "result_digest": "same", "row_count": 1, "last_output_rows": 1}
    evidence = build_full_result_evidence(
        sql, [{"name": "ID", "oracle_type": "NUMBER", "precision": 10, "scale": 0}], [[1]]
    )
    full = {**base, **evidence}

    blocked = compare_repeated([legacy], [legacy], workload="OLTP", sql_text=sql)
    verified = compare_repeated([full], [full], workload="OLTP", sql_text=sql)

    assert blocked["semantic_equivalent"] is False
    assert blocked["equivalence_verdict"] == "FULL_RESULT_EVIDENCE_REQUIRED"
    assert verified["semantic_equivalent"] is True
    assert verified["equivalence_verdict"] == "RESULT_EQUIVALENCE_VERIFIED"


def test_failure_classifier_covers_required_customer_sql_failure_families():
    assert classify_failure({"candidate_generated": False, "candidate_error": "EMPTY_CANDIDATE"}) == "CANDIDATE_GENERATION_FAILURE"
    assert classify_failure({"candidate_generated": False, "candidate_error": "ORA-00936: missing expression"}) == "ORACLE_SYNTAX_OR_EXECUTION_ERROR"
    assert classify_failure({"candidate_generated": True, "semantic_equivalent": False}) == "SEMANTIC_EQUIVALENCE_FAILURE"
    assert classify_failure({"candidate_generated": True, "semantic_equivalent": True,
                             "measurement_noisy": True}) == "MEASUREMENT_NOISE"
    assert classify_failure({"candidate_generated": True, "semantic_equivalent": True,
                             "measurement_noisy": False, "primary_reduction_pct": -1}) == "PERFORMANCE_NOT_IMPROVED"
    assert classify_failure({"candidate_generated": True, "semantic_equivalent": False,
                             "reported_equivalent": True}) == "REPORT_DECISION_ERROR"


def test_phase6_equivalence_reasons_are_preserved_and_classified_before_performance():
    blocked = {
        "status": "BLOCKED",
        "reason_code": "FULL_RESULT_EVIDENCE_REQUIRED",
        "equivalence_status": "BLOCKED",
        "equivalence_verdict": "FULL_RESULT_EVIDENCE_REQUIRED",
        "equivalence_evidence": {"side": "BEFORE", "run_index": 0},
        "semantic_equivalent": False,
        "performance_evaluated": False,
    }
    normalized = normalize_result(
        {"sample_id": "asta-awr-01", "mode": "C", "candidate_generated": True,
         "comparison": blocked},
        {"asta-awr-01": "OLTP"}, "phase6",
    )

    assert normalized["equivalence_status"] == "BLOCKED"
    assert normalized["equivalence_verdict"] == "FULL_RESULT_EVIDENCE_REQUIRED"
    assert normalized["equivalence_evidence"]["side"] == "BEFORE"
    assert normalized["failure_category"] == "INSUFFICIENT_EQUIVALENCE_EVIDENCE"
    assert classify_failure({
        "candidate_generated": True,
        "equivalence_verdict": "EQUIVALENCE_BUDGET_EXCEEDED",
    }) == "EQUIVALENCE_BUDGET_EXCEEDED"
    assert classify_failure({
        "candidate_generated": True,
        "equivalence_verdict": "RESULT_METADATA_MISMATCH",
    }) == "SEMANTIC_EQUIVALENCE_FAILURE"


def test_phase7_bind_plan_stability_fields_and_failures_survive_quality_normalization():
    comparison = {
        "status": "BLOCKED",
        "reason_code": "PLAN_FLIP_DETECTED",
        "all_representative_binds_passed": False,
        "bind_case_count": 3,
        "successful_bind_count": 1,
        "failed_bind_case_id": "STYLE_SELECTIVE",
        "worst_after_elapsed_us": 3_100_000,
        "bind_results": [{"bind_case_id": "STYLE_NULL", "status": "ACCEPTED"}],
        "performance_evaluated": False,
    }
    normalized = normalize_result(
        {"sample_id": "asta-awr-01", "mode": "C", "candidate_generated": True,
         "comparison": comparison},
        {"asta-awr-01": "OLTP"}, "phase7",
    )

    assert normalized["bind_stability_status"] == "BLOCKED"
    assert normalized["bind_stability_reason"] == "PLAN_FLIP_DETECTED"
    assert normalized["failed_bind_case_id"] == "STYLE_SELECTIVE"
    assert normalized["bind_results"][0]["bind_case_id"] == "STYLE_NULL"
    assert normalized["failure_category"] == "BIND_PLAN_INSTABILITY"
    assert classify_failure({
        "candidate_generated": True, "reason_code": "BIND_COVERAGE_INSUFFICIENT"
    }) == "BIND_COVERAGE_FAILURE"
    assert classify_failure({
        "candidate_generated": True, "reason_code": "BIND_CASE_LATENCY_REGRESSION"
    }) == "BIND_PERFORMANCE_REGRESSION"
