import json
from pathlib import Path

from tools.asta_vector_learning import classify_vector_learning
from tools.asta_workflow_state import reduce_workflow_events


ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = json.loads(
    (ROOT / "tests/fixtures/asta_phase8_workflow_scenarios.json").read_text(encoding="utf-8")
)


def test_gate_order_reduces_to_one_accepted_terminal_snapshot():
    result = reduce_workflow_events(SCENARIOS["accepted"], attempt_id="attempt-1")

    assert result["overall_status"] == "ACCEPTED"
    assert result["terminal"] is True
    assert result["current_stage"] == "FINAL_DECISION"
    assert result["reason_code"] == "ALL_GATES_VERIFIED"
    assert result["evidence_level"] == "FULL_RESULT_REPRESENTATIVE_BINDS_REPEATED"
    assert [item["status"] for item in result["stages"]] == [
        "VERIFIED", "VERIFIED", "VERIFIED", "ACCEPTED", "ACCEPTED"
    ]


def test_out_of_order_or_missing_gate_fails_closed_without_inventing_success():
    out_of_order = [SCENARIOS["accepted"][0], SCENARIOS["accepted"][2]]
    result = reduce_workflow_events(out_of_order, attempt_id="attempt-1")

    assert result["overall_status"] == "BLOCKED"
    assert result["reason_code"] == "STATE_TRANSITION_OUT_OF_ORDER"
    assert result["current_stage"] == "BIND_PLAN_STABILITY"
    assert result["terminal"] is True


def test_terminal_precedence_preserves_first_authoritative_failure_and_original_error():
    for scenario, expected in (
        ("intent_rejected", "OPTIMIZER_INTENT_NOT_MET"),
        ("bounded_digest", "FULL_RESULT_EVIDENCE_REQUIRED"),
        ("bind_unstable", "PLAN_FLIP_DETECTED"),
        ("timeout", "RUN_TIMEOUT"),
    ):
        events = [*SCENARIOS[scenario], *SCENARIOS["accepted"]]
        result = reduce_workflow_events(events, attempt_id=scenario)
        assert result["reason_code"] == expected
        assert result["overall_status"] in {"BLOCKED", "REJECTED", "FAILED"}
        assert result["terminal"] is True
    timeout = reduce_workflow_events(SCENARIOS["timeout"], attempt_id="timeout")
    assert timeout["original_error"] == "ORA-01013: user requested cancel of current operation"


def test_requery_is_deterministic_and_restart_requires_a_new_authorized_attempt():
    first = reduce_workflow_events(SCENARIOS["bind_unstable"], attempt_id="attempt-1")
    same = reduce_workflow_events(SCENARIOS["bind_unstable"], previous=first, attempt_id="attempt-1")
    unauthorized = reduce_workflow_events(
        SCENARIOS["accepted"], previous=first, attempt_id="attempt-2", restart_authorized=False
    )
    restarted = reduce_workflow_events(
        SCENARIOS["accepted"], previous=first, attempt_id="attempt-2", restart_authorized=True
    )

    assert same == first
    assert unauthorized["overall_status"] == "BLOCKED"
    assert unauthorized["reason_code"] == "RESTART_NOT_AUTHORIZED"
    assert restarted["overall_status"] == "ACCEPTED"
    assert restarted["attempt_id"] == "attempt-2"


def test_only_fully_accepted_workflow_is_positive_vector_eligible():
    accepted = reduce_workflow_events(SCENARIOS["accepted"], attempt_id="accepted")
    result = classify_vector_learning(
        accepted,
        {
            "case_fingerprint": "a" * 64,
            "workload": "OLTP",
            "strategy_id": "NOT_EXISTS_UNION_DISTINCT_BARRIER",
            "primary_reduction_pct": 88.2167,
            "median_elapsed_us": 1_641_880,
            "raw_sql": "select * from customer_secret where id='SECRET'",
            "bind_value": "SECRET",
        },
    )

    assert result["classification"] == "POSITIVE_VERIFIED"
    assert result["positive_eligible"] is True
    assert result["positive_record"]["reason_code"] == "ALL_GATES_VERIFIED"
    assert result["positive_record"]["evidence_level"] == "FULL_RESULT_REPRESENTATIVE_BINDS_REPEATED"
    assert result["rejected_record"] is None
    serialized = json.dumps(result, ensure_ascii=False)
    assert "customer_secret" not in serialized
    assert "SECRET" not in serialized
    assert "raw_sql" not in serialized
    assert "bind_value" not in serialized


def test_failed_or_insufficient_workflow_is_separate_rejected_observation_never_positive():
    for scenario in (
        "intent_rejected", "bounded_digest", "bind_unstable", "timeout",
        "no_candidate", "oracle_error", "non_equivalent",
    ):
        snapshot = reduce_workflow_events(SCENARIOS[scenario], attempt_id=scenario)
        result = classify_vector_learning(
            snapshot,
            {"case_fingerprint": "b" * 64, "raw_sql": "select 'SECRET' from dual", "bind_value": "SECRET"},
        )
        assert result["classification"] == "REJECTED_OBSERVATION"
        assert result["positive_eligible"] is False
        assert result["positive_record"] is None
        assert result["rejected_record"]["reason_code"] == snapshot["reason_code"]
        assert result["rejected_record"]["current_stage"] == snapshot["current_stage"]
        serialized = json.dumps(result, ensure_ascii=False)
        assert "select 'SECRET'" not in serialized
        assert "bind_value" not in serialized


def test_tampered_accepted_snapshot_or_invalid_fingerprint_fails_closed_for_vector():
    accepted = reduce_workflow_events(SCENARIOS["accepted"], attempt_id="accepted")
    tampered = json.loads(json.dumps(accepted))
    tampered["stages"][1]["status"] = "BLOCKED"

    incomplete = classify_vector_learning(tampered, {"case_fingerprint": "c" * 64})
    invalid_fp = classify_vector_learning(accepted, {"case_fingerprint": "raw-customer-id"})

    assert incomplete["classification"] == "REJECTED_OBSERVATION"
    assert incomplete["rejected_record"]["reason_code"] == "VECTOR_POSITIVE_GATE_INCOMPLETE"
    assert invalid_fp["classification"] == "REJECTED_OBSERVATION"
    assert invalid_fp["rejected_record"]["reason_code"] == "VECTOR_FINGERPRINT_INVALID"


def test_original_ora_is_preserved_but_embedded_sql_literals_and_bind_values_are_redacted():
    events = [{
        "sequence": 1,
        "stage": "OPTIMIZER_INTENT",
        "status": "FAILED",
        "reason_code": "CANDIDATE_ORACLE_ERROR",
        "error": "ORA-00933: SQL command not properly ended SELECT * FROM SECRET_T WHERE C='SECRET' AND :P_ID=991",
    }]

    snapshot = reduce_workflow_events(events, attempt_id="ora")
    serialized = json.dumps(snapshot, ensure_ascii=False)

    assert "ORA-00933" in snapshot["original_error"]
    assert "SQL_TEXT_REDACTED" in snapshot["original_error"]
    assert "SELECT * FROM" not in serialized
    assert "SECRET_T" not in serialized
    assert "'SECRET'" not in serialized
    assert "991" not in serialized
