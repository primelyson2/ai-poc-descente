"""단계 5 반복 측정, 순서 편향과 실행예산의 결정론적 행동 테스트."""

import json
from copy import deepcopy
from pathlib import Path

from tools.asta_execution_budget import (
    build_execution_schedule,
    check_execution_budget,
    evaluate_measurement_campaign,
    resolve_execution_policy,
    summarize_measurements,
)
from tools.asta_optimizer_intent import verify_optimizer_intent
from tools.asta_quality_agent import classify_failure, link_dominant_plan_node_to_sql, normalize_result
from tools.asta_result_equivalence import build_full_result_evidence
from tools.asta_strategy_planner import plan_tuning_strategies


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / "tests/fixtures/asta_customer_01_measurement_campaign.json").read_text(encoding="utf-8"))
BEFORE_PLAN = (ROOT / "tests/fixtures/asta_customer_01_dominant_xplan.txt").read_text(encoding="utf-8")
FAILED_PLAN = (ROOT / "tests/fixtures/asta_customer_01_distinct_merged_xplan.txt").read_text(encoding="utf-8")
SUCCESS_PLAN = (ROOT / "tests/fixtures/asta_customer_01_union_barrier_xplan.txt").read_text(encoding="utf-8")
CUSTOMER_SQL = (ROOT / "tests/fixtures/asta_customer_01_style_not_exists.sql").read_text(encoding="utf-8")


def policy(**overrides):
    value = {
        "warmup_runs_per_target": 1,
        "measurement_runs_per_target": 3,
        "max_candidates": 4,
        "max_total_runs": 20,
        "max_total_wall_time_ms": 600_000,
        "max_candidate_runs": 4,
        "max_candidate_wall_time_ms": 10_000,
        "per_run_timeout_ms": 180_000,
        "max_noise_pct": 20.0,
    }
    value.update(overrides)
    return value


def test_workload_policy_resolver_applies_overrides_without_mutating_config():
    config = {
        "defaults": policy(),
        "workloads": {
            "OLTP": {"per_run_timeout_ms": 180_000, "measurement_runs_per_target": 3},
            "BATCH": {"per_run_timeout_ms": 600_000, "max_total_wall_time_ms": 1_800_000},
        },
    }
    snapshot = deepcopy(config)

    oltp = resolve_execution_policy(config, "oltp")
    batch = resolve_execution_policy(config, "BATCH")

    assert oltp["per_run_timeout_ms"] == 180_000
    assert oltp["measurement_runs_per_target"] == 3
    assert batch["per_run_timeout_ms"] == 600_000
    assert batch["max_total_wall_time_ms"] == 1_800_000
    assert config == snapshot


def intent(strategy_id: str, after_plan: str) -> dict:
    link = link_dominant_plan_node_to_sql(CUSTOMER_SQL, BEFORE_PLAN)
    strategies = plan_tuning_strategies(link)["strategies"]
    strategy = next(item for item in strategies if item["strategy_id"] == strategy_id)
    return verify_optimizer_intent(BEFORE_PLAN, after_plan, strategy)


def full_equivalence_evidence():
    columns = [
        {"name": "STYLE_CD", "oracle_type": "VARCHAR2", "max_length": 30},
        {"name": "QTY", "oracle_type": "NUMBER", "precision": 12, "scale": 0},
    ]
    rows = [["S1", 10], ["S2", None], ["S2", None]]
    evidence = build_full_result_evidence(CUSTOMER_SQL, columns, rows)
    return {
        "sql_text": CUSTOMER_SQL,
        "before_runs": [{"status": "COMPLETED", **evidence}],
        "after_runs": [{"status": "COMPLETED", **evidence}],
    }


def test_full_equivalence_gate_runs_after_intent_and_before_measurement_budget():
    verified = intent("NOT_EXISTS_UNION_DISTINCT_BARRIER", SUCCESS_PLAN)
    result = evaluate_measurement_campaign(
        FIXTURE["candidate_id"], verified, FIXTURE["before_runs"], FIXTURE["after_runs"],
        "OLTP", policy(), equivalence_evidence=full_equivalence_evidence(),
    )

    assert result["status"] == "ACCEPTED"
    assert result["equivalence_verdict"] == "RESULT_EQUIVALENCE_VERIFIED"
    assert result["semantic_equivalent"] is True
    assert result["budget"]["usage"]["total_runs"] == 8


def test_historical_bounded_customer_digest_is_blocked_before_measurement_budget():
    historical = {
        "sql_text": CUSTOMER_SQL,
        "before_runs": [FIXTURE["before_runs"][1]],
        "after_runs": [FIXTURE["after_runs"][1]],
    }
    result = evaluate_measurement_campaign(
        FIXTURE["candidate_id"], intent("NOT_EXISTS_UNION_DISTINCT_BARRIER", SUCCESS_PLAN),
        FIXTURE["before_runs"], FIXTURE["after_runs"], "OLTP", policy(),
        equivalence_evidence=historical,
    )

    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "FULL_RESULT_EVIDENCE_REQUIRED"
    assert result["processed_run_count"] == 0
    assert result["state"]["used_total_runs"] == 0
    assert result["performance_evaluated"] is False


def test_schedule_separates_warmup_and_rotates_measured_candidate_order():
    result = build_execution_schedule(["BARRIER", "GROUP_BY"], policy(), rotation=1)

    assert result["status"] == "PLANNED"
    assert result["warmup_event_count"] == 3
    assert result["measurement_event_count"] == 9
    assert result["total_planned_runs"] == 12
    assert [event["target_id"] for event in result["events"][:3]] == ["BEFORE", "GROUP_BY", "BARRIER"]
    measured = [event for event in result["events"] if event["phase"] == "MEASURE"]
    assert [event["target_id"] for event in measured[:3]] == ["BEFORE", "GROUP_BY", "BARRIER"]
    assert [event["target_id"] for event in measured[3:6]] == ["BEFORE", "BARRIER", "GROUP_BY"]
    assert build_execution_schedule(["BARRIER", "GROUP_BY"], policy(), rotation=1) == result


def test_schedule_preflight_blocks_run_budgets_before_creating_events():
    total = build_execution_schedule(["BARRIER", "GROUP_BY"], policy(max_total_runs=11), rotation=0)
    candidate = build_execution_schedule(["BARRIER"], policy(max_candidate_runs=3), rotation=0)

    assert total["status"] == "BLOCKED"
    assert total["reason_code"] == "TOTAL_RUN_BUDGET_EXCEEDED"
    assert total["events"] == []
    assert candidate["status"] == "BLOCKED"
    assert candidate["reason_code"] == "CANDIDATE_RUN_BUDGET_EXCEEDED"
    assert candidate["events"] == []


def test_customer_summary_excludes_warmup_and_uses_three_measured_runs():
    before = summarize_measurements(FIXTURE["before_runs"], policy())
    after = summarize_measurements(FIXTURE["after_runs"], policy())

    assert before["status"] == "COMPLETE"
    assert before["warmup_count"] == 1
    assert before["measurement_count"] == 3
    assert before["median_elapsed_us"] == 124_498_199
    assert before["median_buffer_gets"] == 9_159_788
    assert before["elapsed_noise_pct"] == 15.04
    assert after["status"] == "COMPLETE"
    assert after["median_elapsed_us"] == 1_641_880
    assert after["median_buffer_gets"] == 1_079_324
    assert after["elapsed_noise_pct"] == 1.758
    assert after["noise_gate_passed"] is True


def test_customer_campaign_fits_total_and_candidate_run_time_budgets():
    result = check_execution_budget(
        FIXTURE["candidate_id"], FIXTURE["before_runs"], FIXTURE["after_runs"], policy()
    )

    assert result["status"] == "WITHIN_BUDGET"
    assert result["reason_code"] is None
    assert result["usage"]["total_runs"] == 8
    assert result["usage"]["total_wall_time_ms"] == 527_659
    assert result["usage"]["candidate_runs"] == 4
    assert result["usage"]["candidate_wall_time_ms"] == 6_603
    assert result["remaining"]["total_runs"] == 12
    assert result["remaining"]["candidate_runs"] == 0


def test_each_budget_limit_has_a_deterministic_reason_code():
    cases = [
        (policy(max_total_runs=7), "TOTAL_RUN_BUDGET_EXCEEDED"),
        (policy(max_total_wall_time_ms=500_000), "TOTAL_TIME_BUDGET_EXCEEDED"),
        (policy(max_candidate_runs=3), "CANDIDATE_RUN_BUDGET_EXCEEDED"),
        (policy(max_candidate_wall_time_ms=6_000), "CANDIDATE_TIME_BUDGET_EXCEEDED"),
    ]

    for limited_policy, expected_reason in cases:
        result = check_execution_budget(
            FIXTURE["candidate_id"], FIXTURE["before_runs"], FIXTURE["after_runs"], limited_policy
        )
        assert result["status"] == "BLOCKED"
        assert result["reason_code"] == expected_reason
        assert result["additional_runs_allowed"] is False


def test_budget_state_accumulates_across_candidates_without_mutating_input():
    initial = {
        "used_total_runs": 2,
        "used_total_wall_time_ms": 1_000,
        "candidates": {},
        "terminal_candidates": {},
    }
    snapshot = json.loads(json.dumps(initial))

    result = check_execution_budget(
        FIXTURE["candidate_id"], FIXTURE["before_runs"], FIXTURE["after_runs"],
        policy(max_total_runs=12, max_total_wall_time_ms=600_000), initial,
    )

    assert result["status"] == "WITHIN_BUDGET"
    assert result["state"]["used_total_runs"] == 10
    assert result["state"]["used_total_wall_time_ms"] == 528_659
    assert initial == snapshot


def test_verified_customer_campaign_passes_full_equivalence_noise_and_oltp_guards():
    result = evaluate_measurement_campaign(
        FIXTURE["candidate_id"],
        intent("NOT_EXISTS_UNION_DISTINCT_BARRIER", SUCCESS_PLAN),
        FIXTURE["before_runs"],
        FIXTURE["after_runs"],
        "OLTP",
        policy(),
        equivalence_evidence=full_equivalence_evidence(),
    )

    assert result["status"] == "ACCEPTED"
    assert result["reason_code"] == "MEASUREMENT_ACCEPTED"
    assert result["optimizer_intent_verdict"] == "OPTIMIZER_INTENT_VERIFIED"
    assert result["digest_evaluated"] is True
    assert result["semantic_equivalent"] is True
    assert result["before_summary"]["median_elapsed_us"] == 124_498_199
    assert result["after_summary"]["median_elapsed_us"] == 1_641_880
    assert result["after_summary"]["elapsed_noise_pct"] == 1.758
    assert result["latency_guard_passed"] is True
    assert result["budget"]["usage"]["total_runs"] == 8


def test_unverified_optimizer_intent_blocks_before_consuming_measurement_budget():
    rejected_intent = intent("NOT_EXISTS_DISTINCT_KEY_ANTI", FAILED_PLAN)

    result = evaluate_measurement_campaign(
        FIXTURE["candidate_id"], rejected_intent, FIXTURE["before_runs"], FIXTURE["after_runs"],
        "OLTP", policy(),
    )

    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "OPTIMIZER_INTENT_NOT_VERIFIED"
    assert result["processed_run_count"] == 0
    assert result["digest_evaluated"] is False
    assert result["performance_evaluated"] is False
    assert result["state"]["used_total_runs"] == 0


def test_timeout_and_runaway_stop_candidate_and_require_session_check():
    verified = intent("NOT_EXISTS_UNION_DISTINCT_BARRIER", SUCCESS_PLAN)
    cases = [("TIMEOUT", "RUN_TIMEOUT"), ("RUNAWAY", "RUNAWAY_EXECUTION_DETECTED")]
    for status, reason in cases:
        after = deepcopy(FIXTURE["after_runs"])
        after[1]["status"] = status
        result = evaluate_measurement_campaign(
            FIXTURE["candidate_id"], verified, FIXTURE["before_runs"], after, "OLTP", policy(),
            equivalence_evidence=full_equivalence_evidence(),
        )
        assert result["status"] == "BLOCKED"
        assert result["reason_code"] == reason
        assert result["cancel_requested"] is True
        assert result["runaway_session_check_required"] is True
        assert result["additional_runs_allowed"] is False


def test_terminal_failed_candidate_cannot_consume_more_runs():
    after = deepcopy(FIXTURE["after_runs"])
    after[1]["status"] = "TIMEOUT"
    verified = intent("NOT_EXISTS_UNION_DISTINCT_BARRIER", SUCCESS_PLAN)
    first = evaluate_measurement_campaign(
        FIXTURE["candidate_id"], verified, FIXTURE["before_runs"], after, "OLTP", policy(),
        equivalence_evidence=full_equivalence_evidence(),
    )
    used = first["state"]["used_total_runs"]
    second = evaluate_measurement_campaign(
        FIXTURE["candidate_id"], verified, FIXTURE["before_runs"], FIXTURE["after_runs"],
        "OLTP", policy(), first["state"],
    )

    assert second["status"] == "BLOCKED"
    assert second["reason_code"] == "CANDIDATE_TERMINAL_FAILURE"
    assert second["processed_run_count"] == 0
    assert second["state"]["used_total_runs"] == used


def test_incomplete_or_noisy_measurements_never_infer_success():
    verified = intent("NOT_EXISTS_UNION_DISTINCT_BARRIER", SUCCESS_PLAN)
    incomplete = evaluate_measurement_campaign(
        FIXTURE["candidate_id"], verified, FIXTURE["before_runs"], FIXTURE["after_runs"][:-1],
        "OLTP", policy(), equivalence_evidence=full_equivalence_evidence(),
    )
    noisy_after = deepcopy(FIXTURE["after_runs"])
    for run, elapsed in zip(noisy_after[1:], (1_000_000, 2_000_000, 5_000_000)):
        run["last_elapsed_time_us"] = elapsed
    noisy = evaluate_measurement_campaign(
        FIXTURE["candidate_id"], verified, FIXTURE["before_runs"], noisy_after,
        "OLTP", policy(max_candidate_wall_time_ms=20_000),
        equivalence_evidence=full_equivalence_evidence(),
    )

    assert incomplete["status"] == "BLOCKED"
    assert incomplete["reason_code"] == "MEASUREMENT_INCOMPLETE"
    assert noisy["status"] == "BLOCKED"
    assert noisy["reason_code"] == "MEASUREMENT_NOISE_TOO_HIGH"


def test_oltp_three_second_and_300ms_guards_are_fail_closed_on_medians():
    verified = intent("NOT_EXISTS_UNION_DISTINCT_BARRIER", SUCCESS_PLAN)
    over_three = deepcopy(FIXTURE["after_runs"])
    for run in over_three[1:]:
        run["last_elapsed_time_us"] = 3_100_000
    absolute = evaluate_measurement_campaign(
        "OVER_THREE", verified, FIXTURE["before_runs"], over_three, "OLTP",
        policy(max_candidate_wall_time_ms=20_000),
        equivalence_evidence=full_equivalence_evidence(),
    )
    before = deepcopy(FIXTURE["before_runs"])
    after = deepcopy(FIXTURE["after_runs"])
    for run in before[1:]:
        run["last_elapsed_time_us"] = 2_500_000
    for run in after[1:]:
        run["last_elapsed_time_us"] = 2_900_001
    increase = evaluate_measurement_campaign(
        "OVER_INCREASE", verified, before, after, "OLTP", policy(max_candidate_wall_time_ms=20_000),
        equivalence_evidence=full_equivalence_evidence(),
    )

    assert absolute["status"] == "REJECTED"
    assert absolute["reason_code"] == "OLTP_LATENCY_GUARD_NOT_MET"
    assert increase["status"] == "REJECTED"
    assert increase["reason_code"] == "OLTP_LATENCY_GUARD_NOT_MET"


def test_budget_and_measurement_failure_reasons_survive_quality_normalization():
    verified = intent("NOT_EXISTS_UNION_DISTINCT_BARRIER", SUCCESS_PLAN)
    budget_failure = evaluate_measurement_campaign(
        FIXTURE["candidate_id"], verified, FIXTURE["before_runs"], FIXTURE["after_runs"],
        "OLTP", policy(max_total_runs=7), equivalence_evidence=full_equivalence_evidence(),
    )
    normalized = normalize_result(
        {"sample_id": "asta-awr-01", "mode": "C", "candidate_generated": True,
         "comparison": budget_failure},
        {"asta-awr-01": "OLTP"}, "phase5",
    )

    assert normalized["measurement_reason_code"] == "TOTAL_RUN_BUDGET_EXCEEDED"
    assert normalized["failure_category"] == "EXECUTION_BUDGET_EXCEEDED"
    assert classify_failure({"candidate_generated": True, "reason_code": "RUN_TIMEOUT"}) == "EXECUTION_TIMEOUT"
    assert classify_failure({"candidate_generated": True, "reason_code": "RUNAWAY_EXECUTION_DETECTED"}) == "RUNAWAY_EXECUTION"
    assert classify_failure({"candidate_generated": True, "reason_code": "MEASUREMENT_INCOMPLETE"}) == "MEASUREMENT_INCOMPLETE"
