"""Regression contracts for the 2026-06-30 independent Claude review."""
from pathlib import Path
import importlib.util
import re

ROOT = Path(__file__).resolve().parents[1]
REPORT = (ROOT / "db/adb/asta_report_pkg.sql").read_text()
LLM = (ROOT / "db/adb/asta_llm_pkg.sql").read_text()
PKG = (ROOT / "db/adb/asta_pkg.sql").read_text()


def body(source: str, start: str, end: str) -> str:
    return source[source.index(start):source.index(end, source.index(start))]


def test_c1_report_stage_table_matches_canonical_order():
    section = body(REPORT, "PROCEDURE append_stage_check(", "END append_stage_check;")
    sequences = re.findall(r"append_stage_row\(p_out,\s*(\d+),", section)
    assert sequences == [str(value) for value in range(1, 12)]
    for label in [
        "요청 접수", "ORDS 호출", "SQL Guard", "SQL Tuning Advisor",
        "LLM SQL-only 구조 재작성", "Vector KB 조회", "Final report", "Vector KB 저장",
    ]:
        assert label in section
    assert "CASE WHEN l_estimated_plan_only THEN '원본 SQL/예상 Plan' ELSE '원본 SQL/XPLAN/metrics' END" in section
    assert "CASE WHEN l_estimated_plan_only THEN '후보 SQL/예상 Plan' ELSE '후보 SQL evidence' END" in section
    assert "CASE WHEN l_estimated_plan_only THEN '예상 Plan 범위 비교' ELSE 'Before/After deterministic 비교' END" in section
    assert "p_comparison_json" in section


def test_c2_sql_only_arrays_are_preserved_and_vector_metadata_is_searchable():
    section = body(LLM, "FUNCTION generate_sql_only_tuning(\n", "END generate_sql_only_tuning;")
    assert "JSON_QUERY(l_diagnosis_response, '$.change_summary'" in section
    assert "JSON_QUERY(l_diagnosis_response, '$.semantic_risks'" in section
    assert '\\"change_summary\\":[]' not in section
    metadata = body(PKG, "FUNCTION build_vector_metadata(", "END build_vector_metadata;")
    assert "JSON_QUERY(p_llm_json, '$.change_summary'" in metadata
    assert "FORMAT JSON" in metadata
    assert "JSON_VALUE(p_llm_json, '$.change_summary'" not in metadata


def test_c2b_candidate_syntax_repair_preserves_failure_evidence_and_before_metrics():
    assert "FUNCTION repair_sql_candidate(" in LLM
    assert "Rewrite the rejected candidate into one complete executable Oracle SELECT or WITH statement" in LLM
    assert "ORIGINAL SQL (semantic contract):" in LLM
    orchestration = body(PKG, "FUNCTION run_pipeline(", "END run_pipeline;")
    assert "asta_llm_pkg.repair_sql_candidate(" in orchestration
    assert "l_run_id || '-REPAIRED-SCREEN'" in orchestration
    assert '"rejected_candidate_sql":' in PKG
    assert '"generation":' in PKG
    failure = orchestration[orchestration.index('"verdict":"CANDIDATE_FAILED"'):]
    assert '"before_buffer_gets":' in failure
    assert '"before_elapsed_time_us":' in failure


def test_c2c_response_isolates_malformed_json_artifacts():
    report = (ROOT / "db/adb/asta_report_pkg.sql").read_text(encoding="utf-8")
    helper = body(report, "PROCEDURE clob_app_json_or_null(", "END clob_app_json_or_null;")
    assert "p_val IS JSON" in helper
    assert "INVALID_JSON_ARTIFACT" in helper
    assert "p_artifact_name" in helper
    assert "artifacts.llm" in report
    orchestration = body(PKG, "FUNCTION run_pipeline(", "END run_pipeline;")
    assert "'$.message' RETURNING VARCHAR2(1000)" in orchestration


def test_c2d_candidate_execution_has_adaptive_watchdog():
    assert "PROCEDURE enforce_candidate_timeout(p_run_id IN VARCHAR2);" in PKG
    assert "FUNCTION candidate_timeout_seconds" in PKG
    assert "p_expected_executions IN PLS_INTEGER DEFAULT 1" in PKG
    assert "1800" in PKG
    assert "ASTA_PKG.ENFORCE_CANDIDATE_TIMEOUT" in PKG
    orchestration = body(PKG, "FUNCTION run_pipeline(", "END run_pipeline;")
    assert "arm_candidate_watchdog(" in orchestration
    assert "disarm_candidate_watchdog(" in orchestration
    assert "PLAN_ONLY candidate screen timeout:" in orchestration
    assert "AUTO + FULL_RESULT timeout:" in orchestration
    assert "CANDIDATE_RUNTIME_LIMIT" in PKG


def test_c3_candidate_failure_verdict_survives_original_fallback():
    orchestration = body(PKG, "FUNCTION analyze_sql(", "END analyze_sql;")
    marker = "-- Preserve the failed candidate verdict"
    failure = orchestration[orchestration.index(marker):orchestration.index("END IF;", orchestration.index(marker)) + 7]
    assert "CANDIDATE_FAILED" in failure
    assert '\"equivalence_status\":\"UNKNOWN\"' in failure
    assert '\"retain_original_sql\":true' in failure
    compare_assignment = "l_comparison_json := build_comparison_json(l_source_json, l_after_json, l_workload_type);"
    assert "IF l_candidate_failed <> 'Y' AND l_candidate_screen_rejected <> 'Y' THEN\n        " + compare_assignment in orchestration


def test_c4_smoke_accepts_sql_only_code_mode_or_prompt_mode():
    spec = importlib.util.spec_from_file_location("smoke", ROOT / "tools/asta_smoke_adb.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    base = {"progress": [{"code": c, "status": "SKIPPED" if c in {"AFTER_EVIDENCE", "BEFORE_AFTER_COMPARE"} else "DONE"} for c in module.WORKFLOW],
            "comparison": {"verdict": "NO_REWRITE"}, "final_review": {"status": "SKIPPED", "reason": "DETERMINISTIC_COMPARISON"},
            "detailed_report_markdown": "개선 SQL 없음"}
    for llm in ({"code": "SQL_ONLY_REWRITE"}, {"mode": "SQL_ONLY_STRUCTURAL_REWRITE"}, {"prompt_mode": "SQL_ONLY_STRUCTURAL_REWRITE"}):
        module.validate_workflow_contract({**base, "llm_artifact": llm}, {})


def test_c5_public_candidate_requires_improved_comparison():
    section = body(REPORT, "FUNCTION build_response_json(\n", "END build_response_json;")
    assert "$.verdict" in section
    assert "= 'IMPROVED'" in section


def test_i1_i2_and_message_contracts():
    orchestration = body(PKG, "FUNCTION analyze_sql(", "END analyze_sql;")
    assert "record_progress(l_run_id, 11, 'FINAL_REPORT'" not in orchestration
    assert orchestration.count("asta_llm_pkg.generate_sql_only_tuning(") == 1
    sql_only = body(LLM, "FUNCTION generate_sql_only_tuning(\n", "END generate_sql_only_tuning;")
    assert '"message":"LLM disabled"' in sql_only
