-- ASTA two-stage LLM request/response audit log.
-- Each outbound prompt is committed before DBMS_CLOUD_AI is invoked, and the
-- exact provider response is committed independently from the pipeline run.
DECLARE
  l_count NUMBER;
BEGIN
  SELECT COUNT(*) INTO l_count
  FROM user_tables
  WHERE table_name = 'ASTA_LLM_CALL_LOG';

  IF l_count = 0 THEN
    EXECUTE IMMEDIATE q'[
      CREATE TABLE asta_llm_call_log (
        call_id          NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        run_id           VARCHAR2(64) NOT NULL,
        stage            VARCHAR2(30) NOT NULL,
        attempt_no       NUMBER NOT NULL,
        profile_name     VARCHAR2(128),
        call_status      VARCHAR2(30) NOT NULL,
        prompt_clob      CLOB,
        response_clob    CLOB,
        prompt_chars     NUMBER,
        response_chars   NUMBER,
        error_code       NUMBER,
        error_message    VARCHAR2(4000),
        started_at       TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
        completed_at     TIMESTAMP,
        CONSTRAINT asta_llm_call_stage_ck
          CHECK (stage IN ('DIAGNOSIS', 'CANDIDATE_SQL')),
        CONSTRAINT asta_llm_call_status_ck
          CHECK (call_status IN ('SENT', 'RECEIVED', 'FAILED'))
      )
    ]';
  END IF;
END;
/

DECLARE
  l_count NUMBER;
BEGIN
  SELECT COUNT(*) INTO l_count
  FROM user_indexes
  WHERE index_name = 'ASTA_LLM_CALL_RUN_IX';

  IF l_count = 0 THEN
    EXECUTE IMMEDIATE
      'CREATE INDEX asta_llm_call_run_ix ON asta_llm_call_log(run_id, stage, attempt_no)';
  END IF;
END;
/
