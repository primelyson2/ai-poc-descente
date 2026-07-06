from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal

from tools.asta_result_equivalence import (
    build_full_result_evidence,
    detect_result_order_mode,
    verify_result_equivalence,
)


COLUMNS = [
    {"name": "ID", "oracle_type": "NUMBER", "precision": 10, "scale": 0},
    {"name": "VALUE", "oracle_type": "VARCHAR2", "max_length": 30},
]


def test_top_level_order_by_is_detected_without_comment_string_or_analytic_false_positive():
    assert detect_result_order_mode("select id from t order by id") == "ORDERED_ROWS"
    assert detect_result_order_mode("select row_number() over (order by id) rn from t") == "UNORDERED_MULTISET"
    assert detect_result_order_mode("select 'order by x' v from t /* order by y */") == "UNORDERED_MULTISET"


def test_ordered_digest_preserves_row_order_but_unordered_digest_uses_multiset_semantics():
    rows = [[1, "A"], [2, "B"], [2, "B"]]
    ordered_a = build_full_result_evidence("select id, value from t order by id", COLUMNS, rows)
    ordered_b = build_full_result_evidence("select id, value from t order by id", COLUMNS, list(reversed(rows)))
    unordered_a = build_full_result_evidence("select id, value from t", COLUMNS, rows)
    unordered_b = build_full_result_evidence("select id, value from t", COLUMNS, list(reversed(rows)))
    without_duplicate = build_full_result_evidence("select id, value from t", COLUMNS, rows[:-1])

    assert ordered_a["result_digest"] != ordered_b["result_digest"]
    assert unordered_a["result_digest"] == unordered_b["result_digest"]
    assert unordered_a["result_digest"] != without_duplicate["result_digest"]
    assert unordered_a["result_digest_mode"] == "UNORDERED_MULTISET"
    assert unordered_a["result_total_rows"] == 3


def test_null_and_number_value_are_typed_and_metadata_precision_is_part_of_digest_contract():
    base = build_full_result_evidence("select id, value from t", COLUMNS, [[Decimal("1.0"), None]])
    non_null = build_full_result_evidence("select id, value from t", COLUMNS, [[Decimal("1.0"), ""]])
    changed_columns = deepcopy(COLUMNS)
    changed_columns[0]["scale"] = 2
    changed_metadata = build_full_result_evidence(
        "select id, value from t", changed_columns, [[Decimal("1.0"), None]]
    )

    assert base["result_digest"] != non_null["result_digest"]
    assert base["result_metadata_digest"] != changed_metadata["result_metadata_digest"]
    assert base["result_digest_scope"] == "FULL_RESULT"
    assert base["result_evidence_complete"] is True


def _run(evidence):
    return {"status": "COMPLETED", **evidence}


def test_full_ordered_and_unordered_evidence_verify_only_under_sql_order_semantics():
    ordered_sql = "select id, value from t order by id"
    unordered_sql = "select id, value from t"
    rows = [[1, "A"], [2, "B"], [2, "B"]]

    ordered = verify_result_equivalence(
        ordered_sql,
        [_run(build_full_result_evidence(ordered_sql, COLUMNS, rows))],
        [_run(build_full_result_evidence(ordered_sql, COLUMNS, rows))],
    )
    unordered = verify_result_equivalence(
        unordered_sql,
        [_run(build_full_result_evidence(unordered_sql, COLUMNS, rows))],
        [_run(build_full_result_evidence(unordered_sql, COLUMNS, list(reversed(rows))))],
    )

    assert ordered["status"] == "VERIFIED"
    assert unordered["status"] == "VERIFIED"
    assert ordered["result_digest_mode"] == "ORDERED_ROWS"
    assert unordered["result_digest_mode"] == "UNORDERED_MULTISET"
    assert unordered["allow_performance_measurement"] is True


def test_order_duplicate_and_null_differences_are_non_equivalent():
    ordered_sql = "select id, value from t order by id"
    unordered_sql = "select id, value from t"
    rows = [[1, None], [2, "B"], [2, "B"]]
    cases = [
        (
            ordered_sql,
            build_full_result_evidence(ordered_sql, COLUMNS, rows),
            build_full_result_evidence(ordered_sql, COLUMNS, list(reversed(rows))),
        ),
        (
            unordered_sql,
            build_full_result_evidence(unordered_sql, COLUMNS, rows),
            build_full_result_evidence(unordered_sql, COLUMNS, rows[:-1]),
        ),
        (
            unordered_sql,
            build_full_result_evidence(unordered_sql, COLUMNS, rows),
            build_full_result_evidence(unordered_sql, COLUMNS, [[1, ""], [2, "B"], [2, "B"]]),
        ),
    ]

    results = [verify_result_equivalence(sql, [_run(before)], [_run(after)]) for sql, before, after in cases]
    assert [result["status"] for result in results] == ["NON_EQUIVALENT"] * 3
    assert results[0]["reason_code"] == "RESULT_DIGEST_MISMATCH"
    assert results[1]["reason_code"] == "RESULT_ROW_COUNT_MISMATCH"
    assert results[2]["reason_code"] == "RESULT_DIGEST_MISMATCH"
    assert all(result["allow_performance_measurement"] is False for result in results)


def test_bounded_truncated_budget_mode_and_metadata_evidence_fail_closed():
    sql = "select id, value from t"
    complete = build_full_result_evidence(sql, COLUMNS, [[1, "A"], [2, "B"]])
    cases = []

    bounded = deepcopy(complete)
    bounded["result_digest_scope"] = "BOUNDED_ORDERED_FIRST_N"
    cases.append((bounded, "FULL_RESULT_EVIDENCE_REQUIRED"))

    truncated = deepcopy(complete)
    truncated["result_truncated"] = True
    truncated["result_evidence_complete"] = False
    cases.append((truncated, "RESULT_EVIDENCE_TRUNCATED"))

    budget = build_full_result_evidence(sql, COLUMNS, [[1, "A"], [2, "B"]], max_rows=1)
    cases.append((budget, "EQUIVALENCE_BUDGET_EXCEEDED"))

    wrong_mode = deepcopy(complete)
    wrong_mode["result_digest_mode"] = "ORDERED_ROWS"
    cases.append((wrong_mode, "RESULT_DIGEST_MODE_MISMATCH"))

    changed_columns = deepcopy(COLUMNS)
    changed_columns[0]["precision"] = 20
    changed_metadata = build_full_result_evidence(sql, changed_columns, [[1, "A"], [2, "B"]])
    metadata_result = verify_result_equivalence(sql, [_run(complete)], [_run(changed_metadata)])
    assert metadata_result["status"] == "NON_EQUIVALENT"
    assert metadata_result["reason_code"] == "RESULT_METADATA_MISMATCH"

    for evidence, expected_reason in cases:
        result = verify_result_equivalence(sql, [_run(complete)], [_run(evidence)])
        assert result["status"] == "BLOCKED"
        assert result["reason_code"] == expected_reason
        assert result["semantic_equivalent"] is False
        assert result["allow_performance_measurement"] is False


def test_repeat_digest_or_total_row_instability_is_insufficient_evidence():
    sql = "select id, value from t"
    first = build_full_result_evidence(sql, COLUMNS, [[1, "A"]])
    second = build_full_result_evidence(sql, COLUMNS, [[1, "A"], [2, "B"]])

    result = verify_result_equivalence(sql, [_run(first), _run(second)], [_run(first)])

    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "RESULT_EVIDENCE_UNSTABLE"


def test_chunk_size_does_not_change_full_stream_digest_and_empty_input_semantics_are_preserved():
    sql = "select id, value from t"
    rows = [[1, "A"], [2, "B"], [2, "B"]]
    one = build_full_result_evidence(sql, COLUMNS, rows, chunk_rows=1)
    two = build_full_result_evidence(sql, COLUMNS, rows, chunk_rows=2)
    empty = build_full_result_evidence(sql, COLUMNS, [])
    scalar_null = build_full_result_evidence(sql, COLUMNS, [[None, None]])

    assert one["result_digest"] == two["result_digest"]
    assert one["result_chunk_count"] == 3
    assert two["result_chunk_count"] == 2
    assert empty["result_total_rows"] == 0
    assert empty["result_digest"] != scalar_null["result_digest"]


def test_unsupported_datatype_returns_structured_incomplete_evidence():
    evidence = build_full_result_evidence(
        "select payload from t",
        [{"name": "PAYLOAD", "oracle_type": "BLOB"}],
        [[b"binary"]],
    )

    assert evidence["result_digest_status"] == "BLOCKED"
    assert evidence["result_digest_error"] == "UNSUPPORTED_RESULT_DATATYPE:BLOB"
    assert evidence["result_evidence_complete"] is False
    assert evidence["result_digest"] is None


def test_equivalence_byte_budget_and_nls_independent_temporal_values_fail_closed():
    temporal_columns = [
        {"name": "CREATED_AT", "oracle_type": "TIMESTAMP WITH TIME ZONE", "scale": 6}
    ]
    typed = build_full_result_evidence(
        "select created_at from t", temporal_columns,
        [[datetime(2026, 7, 5, 12, 34, 56, 123456, tzinfo=timezone.utc)]],
        max_bytes=1_000,
    )
    too_wide = build_full_result_evidence(
        "select value from t", [{"name": "VALUE", "oracle_type": "VARCHAR2"}],
        [["X" * 100]], max_bytes=20,
    )
    nls_text = build_full_result_evidence(
        "select created_at from t", temporal_columns, [["05-JUL-26 12.34.56"]]
    )

    assert typed["result_digest_status"] == "COMPLETED"
    assert typed["result_canonical_bytes"] > 0
    assert too_wide["result_digest_status"] == "BLOCKED"
    assert too_wide["result_digest_error"] == "EQUIVALENCE_BUDGET_EXCEEDED"
    assert nls_text["result_digest_status"] == "BLOCKED"
    assert nls_text["result_digest_error"] == "TEMPORAL_VALUE_REQUIRES_TYPED_INPUT"
