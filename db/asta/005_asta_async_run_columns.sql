-- 기존 ASTA_RUNS에 ADB Scheduler 제출 메타데이터를 추가한다.
DECLARE
  PROCEDURE add_column_if_missing(p_column IN VARCHAR2, p_ddl IN VARCHAR2) IS
    l_count NUMBER;
  BEGIN
    SELECT COUNT(*) INTO l_count FROM user_tab_columns
    WHERE table_name = 'ASTA_RUNS' AND column_name = UPPER(p_column);
    IF l_count = 0 THEN EXECUTE IMMEDIATE p_ddl; END IF;
  END;
BEGIN
  add_column_if_missing('REQUEST_JSON', 'ALTER TABLE asta_runs ADD (request_json CLOB CHECK (request_json IS JSON))');
  add_column_if_missing('IDEMPOTENCY_KEY', 'ALTER TABLE asta_runs ADD (idempotency_key VARCHAR2(128))');
  add_column_if_missing('JOB_NAME', 'ALTER TABLE asta_runs ADD (job_name VARCHAR2(128))');
  add_column_if_missing('SUBMITTED_AT', 'ALTER TABLE asta_runs ADD (submitted_at TIMESTAMP)');
END;
/

DECLARE
  l_count NUMBER;
BEGIN
  SELECT COUNT(*) INTO l_count FROM user_indexes WHERE index_name = 'ASTA_RUNS_IDEMPOTENCY_UK';
  IF l_count = 0 THEN
    EXECUTE IMMEDIATE 'CREATE UNIQUE INDEX asta_runs_idempotency_uk ON asta_runs(idempotency_key)';
  END IF;
END;
/
