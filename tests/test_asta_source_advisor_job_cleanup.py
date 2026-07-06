"""Source SQL Tuning Advisor Scheduler job 정리 계약."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "db/source/asta_source_pkg.sql"
SMOKE = ROOT / "tools/asta_advisor_job_cleanup_smoke.py"


def source_text() -> str:
    return SOURCE.read_text(encoding="utf-8")


def helper_block(src: str) -> str:
    start = src.index("PROCEDURE cleanup_advisor_scheduler_job(")
    end = src.index("END cleanup_advisor_scheduler_job;", start)
    return src[start:end]


def store_block(src: str) -> str:
    start = src.index("FUNCTION run_evidence_store_vc(", src.index("CREATE OR REPLACE PACKAGE BODY"))
    end = src.index("END run_evidence_store_vc;", start)
    return src[start:end]


def test_cleanup_helper_drops_only_created_inactive_job_without_force():
    src = source_text()
    helper = helper_block(src)
    assert "IF p_job_name IS NULL THEN" in helper
    assert "p_cleanup_status := 'NOT_CREATED'" in helper
    assert "FROM user_scheduler_running_jobs" in helper
    assert "p_cleanup_status := 'SKIPPED_RUNNING'" in helper
    assert "FROM user_scheduler_jobs" in helper
    assert "p_cleanup_status := 'ALREADY_REMOVED'" in helper
    assert "DBMS_SCHEDULER.DROP_JOB(job_name => p_job_name, force => FALSE)" in helper
    assert "p_cleanup_status := 'DROPPED'" in helper
    assert "p_cleanup_status := 'DROP_FAILED'" in helper
    assert "WHEN OTHERS THEN" in helper
    assert "DBMS_SCHEDULER.STOP_JOB" not in helper
    assert "force => TRUE" not in helper
    assert helper.count("job_name = UPPER(p_job_name)") == 2
    assert "LIKE 'ASTA_ADV_%'" not in helper


def test_store_cleans_success_failed_timeout_and_exception_paths_additively():
    src = source_text()
    store = store_block(src)
    call = "cleanup_advisor_scheduler_job(l_job_name, l_cleanup_status, l_cleanup_detail)"
    # Normal polling completion covers both COMPLETED and Advisor FAILED rows;
    # timeout also reaches the same call. Inner and outer exception paths call it again.
    assert store.count(call) == 3
    timeout = store.index("advisor scheduler job did not finish before timeout")
    normal_cleanup = store.index(call)
    normal_fragment = store.index("DBMS_LOB.CREATETEMPORARY(l_advisor_fragment", normal_cleanup)
    assert timeout < normal_cleanup < normal_fragment
    inner_exception = store.index("EXCEPTION\n        WHEN OTHERS THEN", normal_fragment)
    inner_cleanup = store.index(call, inner_exception)
    assert inner_exception < inner_cleanup
    outer_exception = store.rindex("EXCEPTION\n    WHEN OTHERS THEN")
    outer_cleanup = store.index(call, outer_exception)
    assert outer_exception < outer_cleanup
    assert ',"cleanup_status":' in store
    assert ',"cleanup_detail":' in store
    assert '"advisor_job_cleanup":{"status":' in store
    assert "l_job_name := 'ASTA_ADV_'" in store
    assert "DROP_JOB" not in store  # deletion policy stays centralized in the helper


def test_existing_sqltune_task_cleanup_remains_in_place():
    src = source_text()
    advisor_start = src.index("FUNCTION run_advisor_opt(")
    advisor_end = src.index("END run_advisor_opt;", advisor_start)
    advisor = src[advisor_start:advisor_end]
    assert advisor.count("DBMS_SQLTUNE.DROP_TUNING_TASK(task_name => l_task)") == 2


def test_targeted_smoke_preserves_legacy_jobs_and_tasks():
    smoke = SMOKE.read_text(encoding="utf-8")
    assert '"ASTA_SOURCE_BRIDGE_PKG.RUN_SOURCE_EVIDENCE"' in smoke
    assert '[SOURCE_DB_ID, sql, run_id, 10, "ONCE", "Y", 60, None, "BOUNDED", 100]' in smoke
    assert 'cleanup_status not in {"DROPPED", "ALREADY_REMOVED"}' in smoke
    assert "jobs_after != jobs_before" in smoke
    assert "tasks_after != tasks_before" in smoke
    assert "DROP_JOB" not in smoke
    assert "DELETE FROM" not in smoke.upper()
