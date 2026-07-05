from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_candidate_prompt_requires_oracle_syntax_and_name_resolution_preflight():
    source = read("db/adb/asta_llm_pkg.sql")
    section = source[source.index("DBMS_LOB.CREATETEMPORARY(l_candidate_prompt"):source.index("FOR i IN 1..4 LOOP")]
    assert "Oracle syntax preflight is mandatory" in section
    assert "never give a CTE the same name as a referenced base table or view" in section
    assert "update every consumer to the exact new CTE name" in section
    for code in ("ORA-00904", "ORA-00918", "ORA-00942", "ORA-01789", "ORA-32039"):
        assert code in section


def test_repair_receives_original_rejected_sql_and_exact_ora_error():
    source = read("db/adb/asta_llm_pkg.sql")
    section = source[source.index("FUNCTION repair_sql_candidate(", source.index("PACKAGE BODY")):source.index("END repair_sql_candidate;")]
    assert "ORIGINAL SQL (semantic contract):" in section
    assert "clob_app_clob(l_prompt, p_original_sql)" in section
    assert "REJECTED CANDIDATE (rewrite this into valid SQL):" in section
    assert "clob_app_clob(l_prompt, p_rejected_candidate)" in section
    assert "Oracle execution error to resolve exactly:" in section
    assert "Do not return the same failing SQL" in section
    assert "ORA-32039 rule:" in section
    assert "WITH VIF_WHOLESALE_S AS (... FROM DSNT.VIF_WHOLESALE_S ...)" in section
    assert "p_stage        => 'REPAIR_SQL'" in section
    assert "p_response    => l_response" in section


def test_pipeline_correlates_repair_log_with_run_id():
    source = read("db/adb/asta_pkg.sql")
    call = source[source.index("l_repaired_candidate := asta_llm_pkg.repair_sql_candidate"):]
    call = call[:call.index(");")]
    assert "p_error_message      => l_source_error" in call
    assert "p_run_id             => l_run_id" in call
    assert source.count("asta_llm_pkg.repair_sql_candidate(") == 2
    assert "l_run_id || '-REPAIRED2'" in source
    assert "SUCCESS_ROUND_2" in source


def test_repair_stage_migration_is_deployed_before_packages():
    migration = read("db/asta/007_asta_llm_repair_log_stage.sql")
    deployer = read("tools/asta_deploy_adb.py")
    assert "'REPAIR_SQL'" in migration
    assert "DROP CONSTRAINT asta_llm_call_stage_ck" in migration
    assert deployer.index('run_script(cur, "db/asta/007_asta_llm_repair_log_stage.sql")') < deployer.index("for rel in DEPLOY_PACKAGE_ORDER")


def test_completed_candidate_failure_shows_ora_message_in_ui():
    source = read("static/js/extensions/tuning_assistant.js")
    assert "data?.artifacts?.llm?.candidate_error" in source
    assert "data?.comparison?.verdict_reason" in source
    assert "/ORA-\\d{5}/i.test(value)" in source
    assert "tuning-ora-banner" in source
    assert "Oracle SQL 오류" in source
