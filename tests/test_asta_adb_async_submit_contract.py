"""ASTA ADB 단일 제출·Scheduler 실행 계약을 검증한다."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_repository_persists_async_request_and_idempotency_metadata():
    repository = read("db/asta/001_asta_repository.sql")
    migration = read("db/asta/005_asta_async_run_columns.sql")
    for token in ("request_json", "idempotency_key", "job_name", "submitted_at"):
        assert token in repository.lower()
        assert token in migration.lower()
    assert "IS JSON" in repository
    assert "ASTA_RUNS_IDEMPOTENCY_UK" in repository


def test_public_package_exposes_submit_and_scheduler_entrypoints():
    package = read("db/adb/asta_pkg.sql")
    spec = package[: package.index("CREATE OR REPLACE PACKAGE BODY")]
    assert "FUNCTION submit_run(p_body_json IN CLOB) RETURN CLOB;" in spec
    assert "PROCEDURE execute_run(p_run_id IN VARCHAR2);" in spec
    assert "FUNCTION analyze_sql(p_body_json IN CLOB) RETURN CLOB;" in spec


def test_submit_persists_queued_run_before_creating_scheduler_job():
    package = read("db/adb/asta_pkg.sql")
    submit_start = package.index("FUNCTION submit_run(p_body_json IN CLOB) RETURN CLOB IS")
    execute_start = package.index("PROCEDURE execute_run(p_run_id IN VARCHAR2) IS", submit_start)
    submit = package[submit_start:execute_start]
    queued_pos = submit.index("'QUEUED'")
    commit_pos = submit.index("COMMIT;", queued_pos)
    scheduler_pos = submit.index("DBMS_SCHEDULER.CREATE_JOB", commit_pos)
    assert queued_pos < commit_pos < scheduler_pos
    assert "execution_mode\":\"ADB_SCHEDULER" in submit
    assert "idempotency_key" in submit
    assert "request_json" in submit
    assert "DBMS_LOB.COMPARE(l_existing_request, p_body_json)" in submit
    assert "IDEMPOTENCY_CONFLICT" in submit
    assert "l_existing_status" in submit


def test_execute_claims_queued_run_and_invokes_internal_pipeline():
    package = read("db/adb/asta_pkg.sql")
    execute_start = package.index("PROCEDURE execute_run(p_run_id IN VARCHAR2) IS")
    execute_end = package.index("END execute_run;", execute_start)
    execute = package[execute_start:execute_end]
    assert "FOR UPDATE" in execute
    assert "status IN ('QUEUED', 'RETRY')" in execute
    assert "request_json" in execute
    assert "run_pipeline(" in execute
    assert "SKIP_LOCKED" not in execute


def test_analyze_is_backward_compatible_submit_alias():
    package = read("db/adb/asta_pkg.sql")
    analyze_start = package.index("FUNCTION analyze_sql(p_body_json IN CLOB) RETURN CLOB IS")
    analyze_end = package.index("END analyze_sql;", analyze_start)
    analyze = package[analyze_start:analyze_end]
    assert "RETURN submit_run(p_body_json);" in analyze
    assert "run_source_evidence" not in analyze


def test_ords_analyze_calls_submit_not_long_running_pipeline():
    ords = read("db/ords/asta_ords_module.sql")
    analyze_handler = ords[ords.index("p_pattern     => 'analyze'"): ords.index("p_pattern     => 'profiles'")]
    assert "ASTA_PKG.SUBMIT_RUN(:body_text)" in analyze_handler
    assert "ASTA_PKG.ANALYZE_SQL(:body_text)" not in analyze_handler


def test_deployer_applies_async_column_migration_before_packages():
    deployer = read("tools/asta_deploy_adb.py")
    assert '"db/asta/005_asta_async_run_columns.sql"' in deployer
    migration_pos = deployer.index('"db/asta/005_asta_async_run_columns.sql"')
    package_pos = deployer.index("for rel in DEPLOY_PACKAGE_ORDER")
    assert migration_pos < package_pos


def test_get_run_returns_persisted_queue_or_running_status_before_report_exists():
    package = read("db/adb/asta_pkg.sql")
    start = package.index("FUNCTION get_run(p_run_id IN VARCHAR2) RETURN CLOB IS")
    end = package.index("END get_run;", start)
    get_run = package[start:end]
    assert "SELECT status, response_json" in get_run
    assert "json_str(l_status)" in get_run
    assert '\"status\":\"UNKNOWN\"' not in get_run


def test_submit_failure_never_overwrites_preexisting_run_and_handles_unique_race():
    package = read("db/adb/asta_pkg.sql")
    start = package.index("FUNCTION submit_run(p_body_json IN CLOB) RETURN CLOB IS")
    end = package.index("END submit_run;", start)
    submit = package[start:end]
    assert "l_row_inserted BOOLEAN := FALSE" in submit
    assert "WHEN DUP_VAL_ON_INDEX THEN" in submit
    assert "IF l_row_inserted THEN" in submit
    assert "WHERE run_id=l_run_id AND job_name=l_job_name" in submit


def test_sqlplus_deploy_applies_async_migration_before_package_compile():
    deploy = read("db/deploy/02_adb_compile.sql")
    migration = deploy.index("@db/asta/005_asta_async_run_columns.sql")
    compile_packages = deploy.index("PROMPT Compiling ADB packages")
    assert migration < compile_packages


def test_report_lookup_exposes_status_and_readiness():
    package = read("db/adb/asta_pkg.sql")
    start = package.index("FUNCTION get_report(p_run_id IN VARCHAR2) RETURN CLOB IS")
    end = package.index("END get_report;", start)
    report = package[start:end]
    assert "SELECT status, detailed_report_md" in report
    assert "json_str(l_status)" in report
    assert '\"report_ready\":' in report


def test_async_exception_handlers_capture_sqlerrm_before_update_sql():
    package = read("db/adb/asta_pkg.sql")
    assert "error_message=SUBSTR(SQLERRM" not in package
    assert "l_submit_error := SUBSTR(SQLERRM" in package
    assert "l_execute_error := SUBSTR(SQLERRM" in package
