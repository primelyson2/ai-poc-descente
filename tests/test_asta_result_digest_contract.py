"""Source 실제 결과 digest와 OLTP gate의 정적 계약."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_source_digest_hashes_ordered_actual_rows_with_metadata_and_nulls():
    source = read("db/source/asta_source_pkg.sql")
    assert "FUNCTION build_digest_sql(" in source
    assert "JSON_ARRAYAGG(row_doc FORMAT JSON ORDER BY row_no RETURNING CLOB)" in source
    assert "JSON_OBJECT(t.* NULL ON NULL RETURNING CLOB)" in source
    assert "DBMS_SQL.DESCRIBE_COLUMNS2" in source
    for field in ("col_name", "col_type", "col_precision", "col_scale", "col_charsetid", "col_charsetform"):
        assert field in source
    assert "SHA256_CHAINED_ORDERED_JSON_V1" in source
    assert "BOUNDED_ORDERED_FIRST_N" in source


def test_digest_failure_is_explicit_and_never_becomes_shape_equivalence():
    source = read("db/source/asta_source_pkg.sql")
    quality = read("tools/asta_quality_agent.py")
    runner = read("tools/run_asta_prompt_abc_adb.py")
    assert "l_digest_status := 'FAILED'" in source
    assert "l_result_digest := NULL" in source
    assert '\',"result_digest":null,"result_digest_status":"FAILED"\'' in source
    assert "verify_result_equivalence" in runner
    assert 'semantic_equivalent = equivalence.get("status") == "VERIFIED"' in runner
    assert '"SHAPE_ONLY"' in runner
    assert 'equivalent = comparison.get("semantic_equivalent") is True' in quality


def test_oltp_comparison_has_no_absolute_three_second_latency_guard():
    adb = read("db/adb/asta_pkg.sql")
    comparison = adb[adb.index("FUNCTION build_comparison_json("):adb.index("END build_comparison_json;")]
    assert "ELSIF l_after_elapsed > 3000000 THEN" not in comparison
    assert "OLTP_LATENCY_TARGET_NOT_MET" not in comparison
    assert "ELSIF l_after_elapsed <= l_before_elapsed AND l_gets_pct >= 5 THEN" in comparison


def test_adb_comparison_requires_matching_result_digest_before_performance():
    adb = read("db/adb/asta_pkg.sql")
    comparison = adb[adb.index("FUNCTION build_comparison_json("):adb.index("END build_comparison_json;")]
    required = adb.index("RESULT_DIGEST_REQUIRED")
    mismatch = adb.index("RESULT_DIGEST_MISMATCH")
    performance = adb.index("OLTP_BUFFER_READS_IMPROVED")
    assert required < performance
    assert mismatch < performance
    assert "result_digest_matches" in adb
