from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_candidate_guard_blocks_ora_25156_before_source_execution():
    guard = read("db/adb/asta_sql_guard_pkg.sql")
    llm = read("db/adb/asta_llm_pkg.sql")
    assert "PROCEDURE assert_candidate_compatible(p_sql IN CLOB)" in guard
    assert "mixed ANSI JOIN and old-style outer join (+)" in guard
    assert "ORA-25156 preflight" in llm
    assert llm.count("asta_sql_guard_pkg.assert_candidate_compatible") >= 4


def test_source_and_bridge_support_true_plan_only_without_digest_pass():
    source = read("db/source/asta_source_pkg.sql")
    bridge = read("db/adb/asta_source_bridge_pkg.sql")
    assert "('ESTIMATED_PLAN', 'PLAN_ONLY', 'BOUNDED', 'FULL_RESULT')" in source
    assert "IF l_evidence_mode = 'PLAN_ONLY' THEN" in source
    assert "l_result_scope := 'PLAN_ONLY'" in source
    assert "l_digest_status := 'SKIPPED'" in source
    assert "ELSIF l_evidence_mode = 'FULL_RESULT' THEN" in source
    assert "('ESTIMATED_PLAN', 'PLAN_ONLY', 'BOUNDED', 'FULL_RESULT')" in bridge


def test_stage7_screens_once_then_runs_full_repeat_only_after_pass():
    main = read("db/adb/asta_pkg.sql")
    screen = main.index("p_run_id           => l_run_id || '-TUNED-SCREEN'")
    final = main.index("p_run_id           => l_run_id || '-TUNED-FINAL'")
    baseline = main.index("p_run_id           => l_run_id || '-BASELINE-FINAL'")
    gate = main.index("l_candidate_screen_reason := candidate_plan_screen_reason")
    assert screen < gate < baseline < final
    screen_call = main[screen:screen + 600]
    assert "p_repeat_policy    => 'ONCE'" in screen_call
    assert "p_result_evidence_mode => l_candidate_result_mode" in screen_call
    final_call = main[final:final + 600]
    assert "p_repeat_policy    => 'AUTO'" in final_call
    assert "p_result_evidence_mode => 'FULL_RESULT'" in final_call
    assert '"full_result_executed":false' in main
    assert "PLAN_SCREEN_BUFFER_GETS_NOT_IMPROVED" in main


def test_watchdog_budget_counts_passes_and_records_remote_cancel_unavailable():
    main = read("db/adb/asta_pkg.sql")
    source = read("db/source/asta_source_pkg.sql")
    bridge = read("db/adb/asta_source_bridge_pkg.sql")
    assert "p_expected_executions IN PLS_INTEGER DEFAULT 1" in main
    assert "l_executions * 1.2" in main
    assert "candidate_timeout_seconds(l_source_json, 6, 90)" in main
    assert "candidate_timeout_seconds(l_after_json, 6, 90)" in main
    assert "LEAST(" in main and "1800" in main
    assert "FUNCTION cancel_run_vc(p_run_id IN VARCHAR2) RETURN VARCHAR2" in source
    assert "ALTER SYSTEM CANCEL SQL" not in source
    assert "SOURCE_CANCEL_NOT_AVAILABLE" in source
    assert "FUNCTION cancel_source_run(" in bridge
    assert "asta_source_bridge_pkg.cancel_source_run(" in main
    assert "cancelled SQL count=" in main
