from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_llm_call_log_schema_preserves_full_clob_payloads():
    ddl = read("db/asta/006_asta_llm_call_log.sql")
    assert "CREATE TABLE asta_llm_call_log" in ddl
    assert "prompt_clob      CLOB" in ddl
    assert "response_clob    CLOB" in ddl
    assert "stage IN ('DIAGNOSIS', 'CANDIDATE_SQL', 'REPAIR_SQL')" in ddl
    assert "call_status IN ('SENT', 'RECEIVED', 'FAILED')" in ddl
    assert "asta_llm_call_run_ix" in ddl


def test_two_stage_llm_calls_audit_prompt_before_call_and_exact_response_after_call():
    llm = read("db/adb/asta_llm_pkg.sql")
    section = llm[llm.index("FUNCTION generate_sql_only_tuning(", llm.index("PACKAGE BODY")):llm.index("END generate_sql_only_tuning;")]

    assert "PRAGMA AUTONOMOUS_TRANSACTION" in llm
    assert "p_prompt, NVL(DBMS_LOB.GETLENGTH(p_prompt), 0)" in llm
    assert "response_clob = p_response" in llm
    assert "p_stage        => 'DIAGNOSIS'" in section
    assert "p_prompt       => l_diagnosis_prompt" in section
    assert "p_stage        => 'CANDIDATE_SQL'" in section
    assert "p_prompt       => l_candidate_prompt" in section

    diagnosis_begin = section.index("l_diagnosis_call_id := begin_llm_call_log")
    diagnosis_call = section.index("INTO l_diagnosis_response")
    diagnosis_finish = section.index("p_response    => l_diagnosis_response")
    diagnosis_normalize = section.index("l_diagnosis_response := normalize_json_response")
    assert diagnosis_begin < diagnosis_call < diagnosis_finish < diagnosis_normalize

    candidate_begin = section.index("l_candidate_call_id := begin_llm_call_log")
    candidate_call = section.index("INTO l_candidate_response", candidate_begin)
    candidate_finish = section.index("p_response    => l_candidate_response", candidate_call)
    candidate_normalize = section.index("l_candidate_response IS NULL", candidate_finish)
    assert candidate_begin < candidate_call < candidate_finish < candidate_normalize


def test_pipeline_passes_run_id_and_deploys_log_schema_before_packages():
    pipeline = read("db/adb/asta_pkg.sql")
    deployer = read("tools/asta_deploy_adb.py")
    compile_sql = read("db/deploy/02_adb_compile.sql")

    call_start = pipeline.index("l_llm_json := asta_llm_pkg.generate_sql_only_tuning(")
    call_end = pipeline.index(");", call_start)
    assert "p_run_id               => l_run_id" in pipeline[call_start:call_end]

    migration_pos = deployer.index('run_script(cur, "db/asta/006_asta_llm_call_log.sql")')
    package_pos = deployer.index("for rel in DEPLOY_PACKAGE_ORDER")
    assert migration_pos < package_pos
    assert "@db/asta/006_asta_llm_call_log.sql" in compile_sql
    assert "@db/asta/007_asta_llm_repair_log_stage.sql" in compile_sql
