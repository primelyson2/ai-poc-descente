"""Independent review Important regressions (reference truth tables + source contracts)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = (ROOT / "db/adb/asta_pkg.sql").read_text()
VECTOR = (ROOT / "db/adb/asta_vector_pkg.sql").read_text()
LLM = (ROOT / "db/adb/asta_llm_pkg.sql").read_text()


def comparison_reference(workload, rows_equal, output_equal, before_gets, after_gets,
                         before_elapsed, after_elapsed):
    """Test oracle mirroring the documented PL/SQL decision contract, not production code."""
    if rows_equal is False or output_equal is False:
        return "NON_EQUIVALENT"
    if rows_equal is None or output_equal is None:
        return "INSUFFICIENT_EVIDENCE"
    if before_elapsed is None or after_elapsed is None:
        return "INSUFFICIENT_EVIDENCE"
    if workload == "BATCH":
        return "IMPROVED" if after_elapsed < before_elapsed else "NOT_IMPROVED"
    if before_gets is None or after_gets is None or before_gets == 0:
        return "INSUFFICIENT_EVIDENCE"
    pct = (before_gets - after_gets) / before_gets * 100
    if after_elapsed <= before_elapsed and pct >= 5:
        return "IMPROVED"
    if pct >= 20 and after_elapsed > before_elapsed:
        if after_elapsed <= 1_000_000 or after_elapsed - before_elapsed <= 300_000:
            return "IMPROVED"
    return "NOT_IMPROVED"


def test_workload_truth_table_and_batch_missing_gets():
    cases = [
        ("BATCH", True, True, None, None, 100, 99, "IMPROVED"),
        ("BATCH", True, True, None, None, 100, 100, "NOT_IMPROVED"),
        ("BATCH", True, True, None, None, None, 90, "INSUFFICIENT_EVIDENCE"),
        ("OLTP", True, True, 100, 95, 100, 100, "IMPROVED"),
        ("OLTP", True, True, None, None, 100, 90, "INSUFFICIENT_EVIDENCE"),
        ("OLTP", True, True, 37237, 4979, 635448, 917737, "IMPROVED"),
        ("OLTP", True, True, 100, 79, 1_000_000, 1_300_001, "NOT_IMPROVED"),
        ("BATCH", False, True, None, None, 100, 50, "NON_EQUIVALENT"),
    ]
    for row in cases:
        assert comparison_reference(*row[:-1]) == row[-1]
    start = PKG.index("FUNCTION build_comparison_json", PKG.index("PACKAGE BODY"))
    section = PKG[start:PKG.index("END build_comparison_json;", start)]
    batch_branch = section.index("IF l_workload_type = 'BATCH'")
    gets_requirement = section.index("l_before_gets IS NULL", batch_branch)
    assert batch_branch < gets_requirement


def test_vector_save_precedes_final_report_and_uses_real_report_ref():
    start = PKG.index("FUNCTION run_pipeline(", PKG.index("PACKAGE BODY"))
    section = PKG[start:PKG.index("END run_pipeline;", start)]
    save = section.index("asta_vector_pkg.save_case(")
    report = section.index("l_report_markdown := asta_report_pkg.build_report(", save)
    assert save < report
    assert "p_report_markdown => TO_CLOB('/api/asta/runs/') || TO_CLOB(l_run_id) || TO_CLOB('/report')" in section
    assert "p_vector_save_json     => l_vector_save_json" in section[report:]
    assert section.index("record_progress(l_run_id, 11, 'VECTOR_SAVE'", save) < report


def test_sql_preview_masks_q_quotes_and_comments_and_never_leaks_on_error():
    start = VECTOR.index("FUNCTION sql_preview(p_sql", VECTOR.index("PACKAGE BODY"))
    section = VECTOR[start:VECTOR.index("END sql_preview;", start)]
    for token in ["l_q_close", "--", "/*", "q-quoted literal", "C_SQL_PREVIEW_CHARS", "C_SQL_PREVIEW_LINES"]:
        assert token in section
    assert "RETURN '[SQL preview redacted]'" in section
    assert "RETURN SUBSTR(DBMS_LOB.SUBSTR(p_sql" not in section


def test_profile_fallback_isolates_each_call_and_records_safe_errors():
    start = LLM.index("FUNCTION generate_sql_only_tuning(", LLM.index("PACKAGE BODY"))
    section = LLM[start:LLM.index("END generate_sql_only_tuning;", start)]
    loop_start = section.index("FOR i IN 1..4 LOOP")
    loop = section[loop_start:section.index("clob_app(l_profile_errors, ']')", loop_start)]
    call = loop.index("DBMS_CLOUD_AI.GENERATE")
    assert loop.rfind("BEGIN", 0, call) >= 0
    assert loop.index("EXCEPTION", call) > call
    assert "CONTINUE;" in loop[loop.index("EXCEPTION", call):]
    diagnostic = loop[loop.index("Preserve a non-sensitive"):loop.index("CONTINUE;", call)]
    assert "profile_errors" in section and "SQLERRM" not in diagnostic
    assert "NO_REWRITE" in section
