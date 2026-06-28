-- db/asta/003_asta_runs_source_db_id.sql
-- Add SOURCE_DB_ID to existing ASTA_RUNS deployments.
-- Safe to run repeatedly on ADB ASTA schema.

DECLARE
  l_count NUMBER;
BEGIN
  SELECT COUNT(*)
  INTO   l_count
  FROM   user_tab_cols
  WHERE  table_name = 'ASTA_RUNS'
  AND    column_name = 'SOURCE_DB_ID';

  IF l_count = 0 THEN
    EXECUTE IMMEDIATE 'ALTER TABLE asta_runs ADD (source_db_id VARCHAR2(64))';
  END IF;
END;
/
