-- db/deploy/01_source_compile.sql
-- Run on Source BaseDB as the Source helper owner.
-- Required DBA grants are documented in db/source/README.md.

SET DEFINE OFF
SET SERVEROUTPUT ON SIZE UNLIMITED
WHENEVER SQLERROR EXIT SQL.SQLCODE

PROMPT == ASTA Source helper compile ==
PROMPT Current user:
SHOW USER

PROMPT Checking Source helper prerequisites visible to this schema...
DECLARE
  l_dummy NUMBER;
BEGIN
  SELECT COUNT(*) INTO l_dummy FROM v$sql WHERE ROWNUM = 1;
  DBMS_OUTPUT.PUT_LINE('OK: SELECT on V$SQL');
EXCEPTION WHEN OTHERS THEN
  DBMS_OUTPUT.PUT_LINE('WARN: V$SQL check failed: ' || SQLERRM);
END;
/

DECLARE
  l_dummy NUMBER;
BEGIN
  SELECT COUNT(*) INTO l_dummy FROM v$sql_plan_statistics_all WHERE ROWNUM = 1;
  DBMS_OUTPUT.PUT_LINE('OK: SELECT on V$SQL_PLAN_STATISTICS_ALL');
EXCEPTION WHEN OTHERS THEN
  DBMS_OUTPUT.PUT_LINE('WARN: V$SQL_PLAN_STATISTICS_ALL check failed: ' || SQLERRM);
END;
/

PROMPT Creating/verifying Source helper repository tables...

DECLARE
  l_count NUMBER;
BEGIN
  SELECT COUNT(*)
  INTO   l_count
  FROM   user_tables
  WHERE  table_name = 'ASTA_SOURCE_RESULTS';

  IF l_count = 0 THEN
    EXECUTE IMMEDIATE q'[
      CREATE TABLE asta_source_results(
        run_id        VARCHAR2(128) PRIMARY KEY,
        response_json CLOB CHECK (response_json IS JSON),
        created_at    TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL
      )
    ]';
    DBMS_OUTPUT.PUT_LINE('OK: created ASTA_SOURCE_RESULTS');
  ELSE
    DBMS_OUTPUT.PUT_LINE('OK: ASTA_SOURCE_RESULTS exists');
  END IF;
END;
/

DECLARE
  l_count NUMBER;
BEGIN
  SELECT COUNT(*)
  INTO   l_count
  FROM   user_indexes
  WHERE  index_name = 'ASTA_SOURCE_RESULTS_CREATED_IDX';

  IF l_count = 0 THEN
    EXECUTE IMMEDIATE 'CREATE INDEX asta_source_results_created_idx ON asta_source_results(created_at)';
    DBMS_OUTPUT.PUT_LINE('OK: created ASTA_SOURCE_RESULTS_CREATED_IDX');
  ELSE
    DBMS_OUTPUT.PUT_LINE('OK: ASTA_SOURCE_RESULTS_CREATED_IDX exists');
  END IF;
END;
/

DECLARE
  l_count NUMBER;
BEGIN
  SELECT COUNT(*)
  INTO   l_count
  FROM   user_tables
  WHERE  table_name = 'ASTA_SOURCE_ADVISOR_RESULTS';

  IF l_count = 0 THEN
    EXECUTE IMMEDIATE q'[
      CREATE TABLE asta_source_advisor_results(
        run_id     VARCHAR2(128) PRIMARY KEY,
        status     VARCHAR2(30),
        report     CLOB,
        created_at TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL
      )
    ]';
    DBMS_OUTPUT.PUT_LINE('OK: created ASTA_SOURCE_ADVISOR_RESULTS');
  ELSE
    DBMS_OUTPUT.PUT_LINE('OK: ASTA_SOURCE_ADVISOR_RESULTS exists');
  END IF;
END;
/

DECLARE
  l_count NUMBER;
BEGIN
  SELECT COUNT(*)
  INTO   l_count
  FROM   user_indexes
  WHERE  index_name = 'ASTA_SRC_ADV_RESULTS_CREATED_IDX';

  IF l_count = 0 THEN
    EXECUTE IMMEDIATE 'CREATE INDEX asta_src_adv_results_created_idx ON asta_source_advisor_results(created_at)';
    DBMS_OUTPUT.PUT_LINE('OK: created ASTA_SRC_ADV_RESULTS_CREATED_IDX');
  ELSE
    DBMS_OUTPUT.PUT_LINE('OK: ASTA_SRC_ADV_RESULTS_CREATED_IDX exists');
  END IF;
END;
/

DECLARE
  l_missing NUMBER;
BEGIN
  SELECT COUNT(*)
  INTO   l_missing
  FROM   (
    SELECT 'ASTA_SOURCE_RESULTS' table_name FROM dual
    UNION ALL
    SELECT 'ASTA_SOURCE_ADVISOR_RESULTS' table_name FROM dual
  ) required
  WHERE  NOT EXISTS (
    SELECT 1
    FROM   user_tables t
    WHERE  t.table_name = required.table_name
  );

  IF l_missing > 0 THEN
    RAISE_APPLICATION_ERROR(-20900, 'Source helper repository table verification failed');
  END IF;
  DBMS_OUTPUT.PUT_LINE('OK: Source helper repository tables verified');
  DBMS_OUTPUT.PUT_LINE('INFO: cleanup policy: retain rows needed for DB-link chunk reads; purge old ASTA_SOURCE_RESULTS/ASTA_SOURCE_ADVISOR_RESULTS rows by created_at after ADB retrieval/report retention window.');
END;
/

PROMPT Compiling Source helper package...
@db/source/asta_source_pkg.sql

SHOW ERRORS PACKAGE asta_source_pkg
SHOW ERRORS PACKAGE BODY asta_source_pkg

DECLARE
  l_invalid NUMBER;
BEGIN
  SELECT COUNT(*)
  INTO   l_invalid
  FROM   user_objects
  WHERE  object_name = 'ASTA_SOURCE_PKG'
  AND    status <> 'VALID';

  IF l_invalid > 0 THEN
    RAISE_APPLICATION_ERROR(-20901, 'ASTA_SOURCE_PKG is invalid after compile');
  END IF;
  DBMS_OUTPUT.PUT_LINE('OK: ASTA_SOURCE_PKG valid');
END;
/

PROMPT Source helper compile complete.
