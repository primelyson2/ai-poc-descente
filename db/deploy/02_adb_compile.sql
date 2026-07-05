-- db/deploy/02_adb_compile.sql
-- Run on ADB as the ASTA package/schema owner.
-- Secret-free; DB links, credentials, and AI profiles must already exist.

SET DEFINE OFF
SET SERVEROUTPUT ON SIZE UNLIMITED
WHENEVER SQLERROR EXIT SQL.SQLCODE

PROMPT == ASTA ADB repository/package compile ==
SHOW USER

PROMPT Creating repository tables if absent...
DECLARE
  l_count NUMBER;
BEGIN
  SELECT COUNT(*) INTO l_count FROM user_tables WHERE table_name = 'ASTA_RUNS';
  IF l_count = 0 THEN
    DBMS_OUTPUT.PUT_LINE('Installing 001_asta_repository.sql');
    EXECUTE IMMEDIATE 'CREATE TABLE asta_runs (
      run_id              VARCHAR2(64) PRIMARY KEY,
      status              VARCHAR2(30) NOT NULL,
      input_sql           CLOB,
      tuned_sql           CLOB,
      llm_profile         VARCHAR2(128),
      source_db_id        VARCHAR2(64),
      source_schema       VARCHAR2(128),
      source_db_link      VARCHAR2(128),
      created_at          TIMESTAMP DEFAULT SYSTIMESTAMP,
      started_at          TIMESTAMP,
      completed_at        TIMESTAMP,
      error_code          VARCHAR2(128),
      error_message       VARCHAR2(4000),
      detailed_report_md  CLOB,
      response_json       CLOB CHECK (response_json IS JSON)
    )';
  ELSE
    DBMS_OUTPUT.PUT_LINE('Skip: ASTA_RUNS already exists');
  END IF;

  SELECT COUNT(*) INTO l_count FROM user_tables WHERE table_name = 'ASTA_RUN_PROGRESS';
  IF l_count = 0 THEN
    EXECUTE IMMEDIATE 'CREATE TABLE asta_run_progress (
      run_id       VARCHAR2(64) NOT NULL,
      seq          NUMBER NOT NULL,
      code         VARCHAR2(64) NOT NULL,
      label        VARCHAR2(256),
      status       VARCHAR2(30),
      detail       VARCHAR2(4000),
      started_at   TIMESTAMP,
      completed_at TIMESTAMP,
      elapsed_ms   NUMBER,
      CONSTRAINT asta_run_progress_pk PRIMARY KEY (run_id, seq)
    )';
  ELSE
    DBMS_OUTPUT.PUT_LINE('Skip: ASTA_RUN_PROGRESS already exists');
  END IF;
END;
/

PROMPT Creating source allowlist table if absent...
DECLARE
  l_count NUMBER;
BEGIN
  SELECT COUNT(*) INTO l_count FROM user_tables WHERE table_name = 'ASTA_SOURCE_CONNECTIONS';
  IF l_count = 0 THEN
    EXECUTE IMMEDIATE 'CREATE TABLE asta_source_connections (
      source_db_id   VARCHAR2(64)  NOT NULL,
      db_link_name   VARCHAR2(128) NOT NULL,
      source_schema  VARCHAR2(128),
      description    VARCHAR2(512),
      enabled        VARCHAR2(1)   DEFAULT ''Y'' NOT NULL
                       CONSTRAINT asta_src_conn_en_ck CHECK (enabled IN (''Y'', ''N'')),
      created_at     TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL,
      updated_at     TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL,
      CONSTRAINT asta_source_conn_pk PRIMARY KEY (source_db_id)
    )';
  ELSE
    DBMS_OUTPUT.PUT_LINE('Skip: ASTA_SOURCE_CONNECTIONS already exists');
  END IF;
END;
/

@db/asta/003_asta_runs_source_db_id.sql
@db/asta/005_asta_async_run_columns.sql
@db/asta/006_asta_llm_call_log.sql
@db/asta/007_asta_llm_repair_log_stage.sql

PROMPT Creating vector KB tables if absent...
DECLARE
  l_count NUMBER;
BEGIN
  SELECT COUNT(*) INTO l_count FROM user_tables WHERE table_name = 'ASTA_TUNING_CASES';
  IF l_count = 0 THEN
    EXECUTE IMMEDIATE 'CREATE TABLE asta_tuning_cases (
      case_id          VARCHAR2(64)   PRIMARY KEY,
      source_sql       CLOB,
      tuned_sql        CLOB,
      report_markdown  CLOB,
      metadata_json    CLOB           CHECK (metadata_json IS JSON),
      sql_fingerprint  VARCHAR2(64),
      created_at       TIMESTAMP      DEFAULT SYSTIMESTAMP NOT NULL
    )';
  ELSE
    DBMS_OUTPUT.PUT_LINE('Skip: ASTA_TUNING_CASES already exists');
  END IF;

  SELECT COUNT(*) INTO l_count FROM user_indexes WHERE index_name = 'ATC_FINGERPRINT_IDX';
  IF l_count = 0 THEN
    EXECUTE IMMEDIATE 'CREATE INDEX atc_fingerprint_idx ON asta_tuning_cases(sql_fingerprint)';
  END IF;

  SELECT COUNT(*) INTO l_count FROM user_tables WHERE table_name = 'ASTA_TUNING_CASE_CHUNKS';
  IF l_count = 0 THEN
    EXECUTE IMMEDIATE 'CREATE TABLE asta_tuning_case_chunks (
      chunk_id    NUMBER            GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      case_id     VARCHAR2(64)      NOT NULL,
      chunk_type  VARCHAR2(64),
      chunk_text  CLOB,
      created_at  TIMESTAMP         DEFAULT SYSTIMESTAMP NOT NULL,
      CONSTRAINT atcc_case_fk FOREIGN KEY (case_id)
        REFERENCES asta_tuning_cases(case_id) ON DELETE CASCADE
    )';
  ELSE
    DBMS_OUTPUT.PUT_LINE('Skip: ASTA_TUNING_CASE_CHUNKS already exists');
  END IF;

  SELECT COUNT(*) INTO l_count FROM user_indexes WHERE index_name = 'ATCC_CASE_IDX';
  IF l_count = 0 THEN
    EXECUTE IMMEDIATE 'CREATE INDEX atcc_case_idx ON asta_tuning_case_chunks(case_id)';
  END IF;
END;
/

PROMPT Compiling ADB packages...
@db/adb/asta_sql_guard_pkg.sql
SHOW ERRORS PACKAGE asta_sql_guard_pkg
SHOW ERRORS PACKAGE BODY asta_sql_guard_pkg

@db/adb/asta_source_bridge_pkg.sql
SHOW ERRORS PACKAGE asta_source_bridge_pkg
SHOW ERRORS PACKAGE BODY asta_source_bridge_pkg

@db/adb/asta_vector_pkg.sql
SHOW ERRORS PACKAGE asta_vector_pkg
SHOW ERRORS PACKAGE BODY asta_vector_pkg

@db/adb/asta_llm_pkg.sql
SHOW ERRORS PACKAGE asta_llm_pkg
SHOW ERRORS PACKAGE BODY asta_llm_pkg

@db/adb/asta_report_pkg.sql
SHOW ERRORS PACKAGE asta_report_pkg
SHOW ERRORS PACKAGE BODY asta_report_pkg

@db/adb/asta_pkg.sql
SHOW ERRORS PACKAGE asta_pkg
SHOW ERRORS PACKAGE BODY asta_pkg

PROMPT Checking invalid ASTA objects...
DECLARE
  l_invalid NUMBER;
BEGIN
  SELECT COUNT(*)
  INTO   l_invalid
  FROM   user_objects
  WHERE  object_name IN (
           'ASTA_SQL_GUARD_PKG', 'ASTA_SOURCE_BRIDGE_PKG', 'ASTA_VECTOR_PKG',
           'ASTA_LLM_PKG', 'ASTA_REPORT_PKG', 'ASTA_PKG'
         )
  AND    status <> 'VALID';

  IF l_invalid > 0 THEN
    FOR r IN (
      SELECT object_name, object_type, status
      FROM user_objects
      WHERE object_name LIKE 'ASTA%'
      AND status <> 'VALID'
      ORDER BY object_name, object_type
    ) LOOP
      DBMS_OUTPUT.PUT_LINE('INVALID: ' || r.object_type || ' ' || r.object_name || ' ' || r.status);
    END LOOP;
    RAISE_APPLICATION_ERROR(-20902, 'One or more ASTA objects are invalid');
  END IF;
  DBMS_OUTPUT.PUT_LINE('OK: ASTA ADB packages valid');
END;
/

PROMPT ADB compile complete. Insert/update ASTA_SOURCE_CONNECTIONS allowlist row before analyze smoke.
