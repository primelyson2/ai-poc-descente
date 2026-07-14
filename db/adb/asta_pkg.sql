-- db/adb/asta_pkg.sql
-- Main ADB ASTA orchestration package exposed by ORDS.

CREATE OR REPLACE PACKAGE asta_pkg AUTHID DEFINER AS
  FUNCTION submit_run(p_body_json IN CLOB) RETURN CLOB;
  PROCEDURE execute_run(p_run_id IN VARCHAR2);
  PROCEDURE enforce_candidate_timeout(p_run_id IN VARCHAR2);
  FUNCTION analyze_sql(p_body_json IN CLOB) RETURN CLOB;
  FUNCTION list_profiles RETURN CLOB;
  FUNCTION list_history(
    p_search IN VARCHAR2 DEFAULT NULL,
    p_limit IN NUMBER DEFAULT 50,
    p_from_date IN VARCHAR2 DEFAULT NULL,
    p_to_date IN VARCHAR2 DEFAULT NULL,
    p_verdict IN VARCHAR2 DEFAULT NULL
  ) RETURN CLOB;
  FUNCTION get_input_sql(p_run_id IN VARCHAR2) RETURN CLOB;
  FUNCTION get_run(p_run_id IN VARCHAR2) RETURN CLOB;
  FUNCTION get_progress(p_run_id IN VARCHAR2) RETURN CLOB;
  FUNCTION get_llm_call(p_run_id IN VARCHAR2, p_call_id IN NUMBER) RETURN CLOB;
  FUNCTION get_report(p_run_id IN VARCHAR2) RETURN CLOB;
END asta_pkg;
/

CREATE OR REPLACE PACKAGE BODY asta_pkg AS
  C_DEFAULT_LLM_PROFILE CONSTANT VARCHAR2(128) := 'ASTA_GROK_REASONING_PROFILE';
  C_DEFAULT_SOURCE_DB_ID CONSTANT VARCHAR2(64) := 'DB0903_TESTDB';

  FUNCTION json_str(p_val IN VARCHAR2) RETURN VARCHAR2 IS
    l_v VARCHAR2(32767) := p_val;
  BEGIN
    IF l_v IS NULL THEN
      RETURN 'null';
    END IF;
    l_v := REPLACE(l_v, '\', '\\');
    l_v := REPLACE(l_v, '"', '\"');
    l_v := REPLACE(l_v, CHR(8), '\b');
    l_v := REPLACE(l_v, CHR(9), '\t');
    l_v := REPLACE(l_v, CHR(10), '\n');
    l_v := REPLACE(l_v, CHR(13), '\r');
    l_v := REPLACE(l_v, CHR(12), '\f');
    RETURN '"' || l_v || '"';
  END json_str;

  FUNCTION json_num(p_val IN NUMBER) RETURN VARCHAR2 IS
  BEGIN
    RETURN NVL(TO_CHAR(p_val, 'TM9', 'NLS_NUMERIC_CHARACTERS=.,'), 'null');
  END json_num;

  FUNCTION json_ts(p_val IN TIMESTAMP) RETURN VARCHAR2 IS
  BEGIN
    IF p_val IS NULL THEN
      RETURN 'null';
    END IF;
    RETURN json_str(TO_CHAR(p_val, 'YYYY-MM-DD"T"HH24:MI:SS.FF3'));
  END json_ts;

  FUNCTION migration_boundary_json RETURN VARCHAR2 IS
  BEGIN
    RETURN
      '"migration_boundary":{"fastapi_role":"ORDS_PROXY_ONLY",' ||
      '"asta_runtime":"ADB_ORDS_PLSQL",' ||
      '"source_runtime":"SOURCE_BASEDB_DBLINK_ONLY",' ||
      '"guard_policy":"SELECT_WITH_SINGLE_STATEMENT",' ||
      '"response_contract":"CLOB_CHUNKED_JSON",' ||
      '"python_local_asta":false}';
  END migration_boundary_json;

  PROCEDURE clob_app(p_out IN OUT NOCOPY CLOB, p_str IN VARCHAR2) IS
  BEGIN
    IF p_str IS NOT NULL AND LENGTH(p_str) > 0 THEN
      DBMS_LOB.WRITEAPPEND(p_out, LENGTH(p_str), p_str);
    END IF;
  END clob_app;

  PROCEDURE clob_app_clob(p_out IN OUT NOCOPY CLOB, p_val IN CLOB) IS
    l_offset PLS_INTEGER := 1;
    l_len    PLS_INTEGER;
    l_chunk  VARCHAR2(32767);
  BEGIN
    IF p_val IS NULL THEN
      RETURN;
    END IF;

    l_len := NVL(DBMS_LOB.GETLENGTH(p_val), 0);
    WHILE l_offset <= l_len LOOP
      -- Use a character-safe chunk under AL32UTF8 and never skip characters
      -- when DBMS_LOB.SUBSTR returns less than the requested amount.
      l_chunk := DBMS_LOB.SUBSTR(p_val, 8000, l_offset);
      EXIT WHEN l_chunk IS NULL;
      DBMS_LOB.WRITEAPPEND(p_out, LENGTH(l_chunk), l_chunk);
      l_offset := l_offset + LENGTH(l_chunk);
    END LOOP;
  END clob_app_clob;

  PROCEDURE clob_app_json_str(p_out IN OUT NOCOPY CLOB, p_val IN CLOB) IS
    l_offset  PLS_INTEGER := 1;
    l_len     PLS_INTEGER;
    l_chunk   VARCHAR2(32767);
    l_escaped VARCHAR2(32767);
  BEGIN
    IF p_val IS NULL THEN
      clob_app(p_out, 'null');
      RETURN;
    END IF;

    l_len := NVL(DBMS_LOB.GETLENGTH(p_val), 0);
    clob_app(p_out, '"');
    WHILE l_offset <= l_len LOOP
      l_chunk := DBMS_LOB.SUBSTR(p_val, 200, l_offset);
      l_escaped := REPLACE(l_chunk, '\', '\\');
      l_escaped := REPLACE(l_escaped, '"', '\"');
      l_escaped := REPLACE(l_escaped, CHR(8), '\b');
      l_escaped := REPLACE(l_escaped, CHR(9), '\t');
      l_escaped := REPLACE(l_escaped, CHR(10), '\n');
      l_escaped := REPLACE(l_escaped, CHR(13), '\r');
      l_escaped := REPLACE(l_escaped, CHR(12), '\f');
      DBMS_LOB.WRITEAPPEND(p_out, LENGTH(l_escaped), l_escaped);
      l_offset := l_offset + 200;
    END LOOP;
    clob_app(p_out, '"');
  END clob_app_json_str;

  FUNCTION elapsed_ms_between(p_start IN TIMESTAMP, p_end IN TIMESTAMP) RETURN NUMBER IS
    l_delta INTERVAL DAY TO SECOND;
  BEGIN
    IF p_start IS NULL OR p_end IS NULL THEN
      RETURN NULL;
    END IF;

    l_delta := p_end - p_start;
    RETURN ROUND(
        EXTRACT(DAY    FROM l_delta) * 86400000
      + EXTRACT(HOUR   FROM l_delta) * 3600000
      + EXTRACT(MINUTE FROM l_delta) * 60000
      + EXTRACT(SECOND FROM l_delta) * 1000
    );
  END elapsed_ms_between;

  PROCEDURE record_progress(
    p_run_id IN VARCHAR2,
    p_seq    IN NUMBER,
    p_code   IN VARCHAR2,
    p_label  IN VARCHAR2,
    p_status IN VARCHAR2,
    p_detail IN VARCHAR2 DEFAULT NULL
  ) IS
    PRAGMA AUTONOMOUS_TRANSACTION;
    l_now          TIMESTAMP := SYSTIMESTAMP;
    l_completed_at TIMESTAMP := CASE
      WHEN p_status IN ('DONE', 'FAILED', 'SKIPPED') THEN l_now
      ELSE NULL
    END;
    l_elapsed_ms NUMBER;
  BEGIN
    IF p_status IN ('DONE', 'FAILED', 'SKIPPED') THEN
      l_elapsed_ms := NULL;
    ELSE
      l_elapsed_ms := elapsed_ms_between(l_now, l_completed_at);
    END IF;
    INSERT INTO asta_run_progress(
      run_id,
      seq,
      code,
      label,
      status,
      detail,
      started_at,
      completed_at,
      elapsed_ms
    ) VALUES (
      p_run_id,
      p_seq,
      p_code,
      p_label,
      p_status,
      p_detail,
      l_now,
      l_completed_at,
      l_elapsed_ms
    );
    COMMIT;
  EXCEPTION
    WHEN DUP_VAL_ON_INDEX THEN
      UPDATE asta_run_progress
      SET    status = p_status,
             detail = p_detail,
             completed_at = CASE
               WHEN p_status IN ('DONE', 'FAILED', 'SKIPPED') THEN l_now
               ELSE completed_at
             END,
             elapsed_ms = CASE
               WHEN p_status IN ('DONE', 'FAILED', 'SKIPPED') THEN
                 ROUND(
                     EXTRACT(DAY    FROM (l_now - started_at)) * 86400000
                   + EXTRACT(HOUR   FROM (l_now - started_at)) * 3600000
                   + EXTRACT(MINUTE FROM (l_now - started_at)) * 60000
                   + EXTRACT(SECOND FROM (l_now - started_at)) * 1000
                 )
               ELSE elapsed_ms
             END
      WHERE  run_id = p_run_id
      AND    seq = p_seq;
      COMMIT;
    WHEN OTHERS THEN
      ROLLBACK;
  END record_progress;

  FUNCTION error_json(p_code IN VARCHAR2, p_message IN VARCHAR2) RETURN CLOB IS
  BEGIN
    RETURN TO_CLOB(
      '{"code":' || json_str(p_code) ||
      ',"message":' || json_str(p_message) || '}'
    );
  END error_json;

  FUNCTION classify_error_code(p_message IN VARCHAR2, p_sqlcode IN NUMBER DEFAULT NULL) RETURN VARCHAR2 IS
    l_message VARCHAR2(4000) := UPPER(NVL(p_message, ''));
  BEGIN
    RETURN CASE
      WHEN p_sqlcode = -20001 OR INSTR(l_message, 'ASTA_SQL_GUARD') > 0 THEN 'SQL_GUARD_REJECTED'
      WHEN INSTR(l_message, 'SQL IS REQUIRED') > 0 THEN 'SQL_REQUIRED'
      WHEN INSTR(l_message, 'INVALID RUN_ID') > 0 THEN 'INVALID_RUN_ID'
      WHEN INSTR(l_message, 'INVALID SOURCE_DB_ID') > 0 THEN 'INVALID_SOURCE_DB'
      WHEN INSTR(l_message, 'RUN_ID_CONFLICT') > 0 THEN 'RUN_ID_CONFLICT'
      WHEN INSTR(l_message, 'IDEMPOTENCY_CONFLICT') > 0 THEN 'IDEMPOTENCY_CONFLICT'
      WHEN INSTR(l_message, 'ORA-00942') > 0 THEN 'SOURCE_OBJECT_NOT_FOUND'
      WHEN INSTR(l_message, 'ORA-01031') > 0 THEN 'SOURCE_PRIVILEGE_DENIED'
      WHEN INSTR(l_message, 'ORA-00904') > 0 THEN 'SQL_INVALID_IDENTIFIER'
      WHEN INSTR(l_message, 'ORA-00918') > 0 THEN 'SQL_AMBIGUOUS_COLUMN'
      WHEN INSTR(l_message, 'ORA-00900') > 0
        OR INSTR(l_message, 'ORA-00905') > 0
        OR INSTR(l_message, 'ORA-00907') > 0
        OR INSTR(l_message, 'ORA-00911') > 0
        OR INSTR(l_message, 'ORA-00933') > 0
        OR INSTR(l_message, 'ORA-00936') > 0 THEN 'SQL_SYNTAX_ERROR'
      WHEN INSTR(l_message, 'ORA-01789') > 0 THEN 'SQL_SET_SHAPE_MISMATCH'
      WHEN INSTR(l_message, 'ORA-32039') > 0 THEN 'SQL_RECURSIVE_WITH_INVALID'
      WHEN INSTR(l_message, 'ORA-01476') > 0 THEN 'SQL_DIVIDE_BY_ZERO'
      WHEN INSTR(l_message, 'ORA-01722') > 0 THEN 'SQL_INVALID_NUMBER'
      WHEN INSTR(l_message, 'ORA-01861') > 0 OR INSTR(l_message, 'ORA-01843') > 0 THEN 'SQL_INVALID_DATE'
      WHEN INSTR(l_message, 'ORA-02019') > 0
        OR INSTR(l_message, 'ORA-12154') > 0
        OR INSTR(l_message, 'ORA-12514') > 0
        OR INSTR(l_message, 'ORA-12541') > 0
        OR INSTR(l_message, 'ORA-03150') > 0 THEN 'SOURCE_DBLINK_UNAVAILABLE'
      WHEN INSTR(l_message, 'ORA-01013') > 0 OR INSTR(l_message, 'ORA-00028') > 0 THEN 'EXECUTION_CANCELLED'
      WHEN INSTR(l_message, 'ORA-00054') > 0 OR INSTR(l_message, 'ORA-04021') > 0 THEN 'RESOURCE_BUSY'
      WHEN INSTR(l_message, 'ORA-01555') > 0 THEN 'SNAPSHOT_TOO_OLD'
      WHEN INSTR(l_message, 'ORA-01652') > 0 OR INSTR(l_message, 'ORA-01653') > 0 THEN 'SPACE_EXHAUSTED'
      WHEN INSTR(l_message, 'ORA-06502') > 0 OR INSTR(l_message, 'ORA-22828') > 0 THEN 'PAYLOAD_LIMIT'
      WHEN INSTR(l_message, 'ORA-04061') > 0 OR INSTR(l_message, 'ORA-04068') > 0 THEN 'PACKAGE_INVALIDATED'
      WHEN INSTR(l_message, 'ORA-00001') > 0 THEN 'DUPLICATE_KEY'
      WHEN INSTR(l_message, 'ORA-02290') > 0 THEN 'REPOSITORY_CONSTRAINT'
      WHEN INSTR(l_message, 'ORA-274') > 0 THEN 'SCHEDULER_SUBMIT_FAILED'
      ELSE 'ASTA_PKG'
    END;
  END classify_error_code;

  FUNCTION normalize_source_db_id(p_source_db_id IN VARCHAR2) RETURN VARCHAR2 IS
    l_id VARCHAR2(64) := UPPER(TRIM(NVL(p_source_db_id, C_DEFAULT_SOURCE_DB_ID)));
  BEGIN
    IF l_id IS NULL
       OR NOT REGEXP_LIKE(l_id, '^[A-Z0-9][A-Z0-9_.:-]{0,63}$') THEN
      RAISE_APPLICATION_ERROR(-20002, 'ASTA_PKG: invalid source_db_id');
    END IF;
    RETURN l_id;
  END normalize_source_db_id;

  FUNCTION normalize_run_id(p_run_id IN VARCHAR2) RETURN VARCHAR2 IS
    l_run_id VARCHAR2(64) := TRIM(p_run_id);
  BEGIN
    IF l_run_id IS NULL
       OR LENGTH(l_run_id) > 64
       OR NOT REGEXP_LIKE(l_run_id, '^[A-Za-z0-9][A-Za-z0-9_.:-]*$') THEN
      RAISE_APPLICATION_ERROR(-20002, 'ASTA_PKG: invalid run_id');
    END IF;
    RETURN l_run_id;
  END normalize_run_id;

  FUNCTION normalized_fetch_rows(p_fetch_rows IN NUMBER) RETURN PLS_INTEGER IS
  BEGIN
    RETURN LEAST(GREATEST(NVL(p_fetch_rows, 100), 1), 10000);
  END normalized_fetch_rows;

  FUNCTION normalized_vector_top_k(p_vector_top_k IN NUMBER) RETURN PLS_INTEGER IS
  BEGIN
    RETURN LEAST(GREATEST(NVL(p_vector_top_k, 3), 1), 20);
  END normalized_vector_top_k;

  FUNCTION normalized_sqltune_time_limit(p_sqltune_time_limit IN NUMBER) RETURN PLS_INTEGER IS
  BEGIN
    RETURN LEAST(GREATEST(NVL(p_sqltune_time_limit, 1800), 60), 1800);
  END normalized_sqltune_time_limit;

  FUNCTION normalized_run_advisor(p_run_advisor IN VARCHAR2) RETURN VARCHAR2 IS
  BEGIN
    RETURN CASE
      WHEN LOWER(TRIM(NVL(p_run_advisor, 'false'))) IN ('true', '1', 'y', 'yes') THEN 'Y'
      ELSE 'N'
    END;
  END normalized_run_advisor;

  FUNCTION normalized_before_evidence_mode(p_mode IN VARCHAR2) RETURN VARCHAR2 IS
    l_mode VARCHAR2(30) := UPPER(TRIM(NVL(p_mode, 'MINIMAL')));
  BEGIN
    RETURN CASE
      WHEN l_mode IN ('MINIMAL', 'FAST_PLAN', 'THOROUGH') THEN l_mode
      ELSE 'MINIMAL'
    END;
  END normalized_before_evidence_mode;

  FUNCTION normalize_workload_type(p_workload_type IN VARCHAR2) RETURN VARCHAR2 IS
  BEGIN
    RETURN CASE WHEN UPPER(TRIM(p_workload_type)) = 'BATCH' THEN 'BATCH' ELSE 'OLTP' END;
  END normalize_workload_type;

  FUNCTION source_response_error_message(p_json IN CLOB) RETURN VARCHAR2 IS
    l_status        VARCHAR2(30);
    l_message       VARCHAR2(4000);
    l_error_message VARCHAR2(4000);
  BEGIN
    IF p_json IS NULL OR NVL(DBMS_LOB.GETLENGTH(p_json), 0) = 0 THEN
      RETURN 'Source evidence returned an empty response';
    END IF;

    SELECT JSON_VALUE(p_json, '$.status' RETURNING VARCHAR2(30) NULL ON ERROR),
           JSON_VALUE(p_json, '$.message' RETURNING VARCHAR2(4000) NULL ON ERROR),
           JSON_VALUE(p_json, '$.error.message' RETURNING VARCHAR2(4000) NULL ON ERROR)
    INTO   l_status, l_message, l_error_message
    FROM   dual;

    IF UPPER(NVL(l_status, 'OK')) = 'FAILED' THEN
      -- Source package의 error.message에는 SQLERRM(ORA-xxxxx)이 들어 있다.
      -- 상위 adapter의 일반 message보다 이를 우선해 고객 화면과 run 이력에
      -- 실제 Oracle 원인이 보존되도록 한다.
      RETURN NVL(l_error_message, l_message);
    END IF;
    IF l_error_message IS NOT NULL THEN
      RETURN l_error_message;
    END IF;
    RETURN NULL;
  EXCEPTION
    WHEN OTHERS THEN
      RETURN 'Source evidence returned unreadable JSON: ' || SUBSTR(SQLERRM, 1, 1000);
  END source_response_error_message;

  FUNCTION advisor_progress_status(p_source_json IN CLOB) RETURN VARCHAR2 IS
    l_status VARCHAR2(30);
  BEGIN
    SELECT JSON_VALUE(p_source_json, '$.advisor.status' RETURNING VARCHAR2(30) NULL ON ERROR)
    INTO   l_status
    FROM   dual;

    IF UPPER(l_status) = 'FAILED' THEN
      RETURN 'FAILED';
    ELSIF UPPER(l_status) = 'SKIPPED' THEN
      RETURN 'SKIPPED';
    END IF;
    RETURN 'DONE';
  EXCEPTION
    WHEN OTHERS THEN
      RETURN 'DONE';
  END advisor_progress_status;

  FUNCTION advisor_progress_detail(p_source_json IN CLOB, p_run_advisor IN VARCHAR2) RETURN VARCHAR2 IS
    l_status VARCHAR2(30);
    l_report VARCHAR2(1000);
  BEGIN
    IF NVL(p_run_advisor, 'N') <> 'Y' THEN
      RETURN 'SQL Tuning Advisor 실행 생략: 고객 DB 적용 시 run_advisor/use_sqltune=true로 활성화';
    END IF;
    SELECT JSON_VALUE(p_source_json, '$.advisor.status' RETURNING VARCHAR2(30) NULL ON ERROR),
           JSON_VALUE(p_source_json, '$.advisor.report' RETURNING VARCHAR2(1000) NULL ON ERROR)
    INTO   l_status, l_report
    FROM   dual;
    IF UPPER(l_status) = 'FAILED' THEN
      RETURN SUBSTR(NVL(l_report, 'SQL Tuning Advisor failed without detail'), 1, 1000);
    ELSIF UPPER(l_status) = 'SKIPPED' THEN
      RETURN 'Source evidence returned SQL_TUNING_ADVISOR SKIPPED';
    END IF;
    RETURN 'Source DBMS_SQLTUNE requested explicitly; status=' || NVL(l_status, 'COMPLETED');
  EXCEPTION
    WHEN OTHERS THEN
      RETURN CASE
        WHEN NVL(p_run_advisor, 'N') = 'Y' THEN 'SQL Tuning Advisor requested but progress detail could not be parsed'
        ELSE 'SQL Tuning Advisor 실행 생략'
      END;
  END advisor_progress_detail;

  FUNCTION progress_status_from_json(p_json IN CLOB) RETURN VARCHAR2 IS
    l_status VARCHAR2(30);
  BEGIN
    SELECT JSON_VALUE(p_json, '$.status' RETURNING VARCHAR2(30) NULL ON ERROR)
    INTO   l_status
    FROM   dual;

    IF UPPER(l_status) = 'FAILED' THEN
      RETURN 'FAILED';
    ELSIF UPPER(l_status) IN ('SKIPPED', 'NOT_CONFIGURED') THEN
      RETURN 'SKIPPED';
    END IF;
    RETURN 'DONE';
  EXCEPTION
    WHEN OTHERS THEN
      RETURN 'DONE';
  END progress_status_from_json;

  FUNCTION build_comparison_json(p_before_json IN CLOB, p_after_json IN CLOB,
    p_workload_type IN VARCHAR2 DEFAULT 'OLTP') RETURN CLOB IS
    l_before_status    VARCHAR2(30);
    l_after_status     VARCHAR2(30);
    l_before_error     VARCHAR2(4000);
    l_after_error      VARCHAR2(4000);
    l_before_rows      NUMBER;
    l_after_rows       NUMBER;
    l_before_output    NUMBER;
    l_after_output     NUMBER;
    l_before_gets      NUMBER;
    l_after_gets       NUMBER;
    l_before_reads     NUMBER;
    l_after_reads      NUMBER;
    l_before_elapsed   NUMBER;
    l_after_elapsed    NUMBER;
    l_before_digest    VARCHAR2(64);
    l_after_digest     VARCHAR2(64);
    l_before_digest_status VARCHAR2(30);
    l_after_digest_status  VARCHAR2(30);
    l_before_digest_scope VARCHAR2(30);
    l_after_digest_scope  VARCHAR2(30);
    l_before_digest_mode VARCHAR2(30);
    l_after_digest_mode  VARCHAR2(30);
    l_before_metadata_digest VARCHAR2(64);
    l_after_metadata_digest VARCHAR2(64);
    l_before_total_rows NUMBER;
    l_after_total_rows NUMBER;
    l_before_digest_rows NUMBER;
    l_after_digest_rows NUMBER;
    l_before_complete VARCHAR2(10);
    l_after_complete VARCHAR2(10);
    l_before_bind_coverage_status VARCHAR2(30);
    l_after_bind_coverage_status VARCHAR2(30);
    l_before_bind_coverage_reason VARCHAR2(100);
    l_after_bind_coverage_reason VARCHAR2(100);
    l_bind_coverage_status VARCHAR2(30);
    l_bind_coverage_reason VARCHAR2(100);
    l_optimizer_intent_status VARCHAR2(30);
    l_optimizer_intent_reason VARCHAR2(100);
    l_intent_object VARCHAR2(128);
    l_before_target_starts NUMBER;
    l_after_target_starts NUMBER;
    l_before_target_buffers NUMBER;
    l_after_target_buffers NUMBER;
    l_after_anti_semi VARCHAR2(10);
    l_before_plan_hash NUMBER;
    l_after_plan_hash NUMBER;
    l_before_measurement_status VARCHAR2(30);
    l_after_measurement_status VARCHAR2(30);
    l_before_measurement_reason VARCHAR2(100);
    l_after_measurement_reason VARCHAR2(100);
    l_before_measurement_count NUMBER;
    l_after_measurement_count NUMBER;
    l_before_median_elapsed NUMBER;
    l_after_median_elapsed NUMBER;
    l_before_median_gets NUMBER;
    l_after_median_gets NUMBER;
    l_before_median_reads NUMBER;
    l_after_median_reads NUMBER;
    l_before_noise_pct NUMBER;
    l_after_noise_pct NUMBER;
    l_before_repeat_count NUMBER;
    l_after_repeat_count NUMBER;
    l_before_elapsed_wall_ms NUMBER;
    l_after_elapsed_wall_ms NUMBER;
    l_measurement_status VARCHAR2(30);
    l_measurement_reason VARCHAR2(100);
    l_row_match        VARCHAR2(5);
    l_output_match     VARCHAR2(5);
    l_gets_delta       NUMBER;
    l_gets_pct         NUMBER;
    l_reads_delta      NUMBER;
    l_elapsed_delta    NUMBER;
    l_elapsed_increase NUMBER;
    l_after_under_1s   VARCHAR2(5);
    l_latency_risk     VARCHAR2(10);
    l_verdict          VARCHAR2(30);
    l_verdict_reason   VARCHAR2(4000);
    l_equivalence      VARCHAR2(30);
    l_retain_original  VARCHAR2(5);
    l_workload_type    VARCHAR2(10) := normalize_workload_type(p_workload_type);
    l_primary_metric   VARCHAR2(30);
    l_optimization_goal VARCHAR2(40);
  BEGIN
    l_primary_metric := CASE WHEN l_workload_type = 'BATCH' THEN 'ELAPSED_TIME' ELSE 'BUFFER_READS' END;
    l_optimization_goal := CASE WHEN l_workload_type = 'BATCH' THEN 'MINIMIZE_ELAPSED_TIME' ELSE 'MINIMIZE_BUFFER_READS' END;
    IF p_before_json IS NULL OR NVL(DBMS_LOB.GETLENGTH(p_before_json), 0) = 0 THEN
      RETURN TO_CLOB(
        '{"status":"SKIPPED","code":"BEFORE_AFTER_COMPARISON","contract_version":"asta.v1","execution_boundary":"ADB_COMPARISON_PLSQL","message":"Before evidence is not available"}'
      );
    END IF;
    IF p_after_json IS NULL OR NVL(DBMS_LOB.GETLENGTH(p_after_json), 0) = 0 THEN
      RETURN TO_CLOB(
        '{"status":"SKIPPED","code":"BEFORE_AFTER_COMPARISON","contract_version":"asta.v1","execution_boundary":"ADB_COMPARISON_PLSQL","message":"After evidence is not available"}'
      );
    END IF;

    SELECT JSON_VALUE(p_before_json, '$.status' RETURNING VARCHAR2(30) NULL ON ERROR),
           JSON_VALUE(p_after_json, '$.status' RETURNING VARCHAR2(30) NULL ON ERROR),
           JSON_VALUE(p_before_json, '$.error.message' RETURNING VARCHAR2(4000) NULL ON ERROR),
           JSON_VALUE(p_after_json, '$.error.message' RETURNING VARCHAR2(4000) NULL ON ERROR),
           JSON_VALUE(p_before_json, '$.row_count' RETURNING NUMBER NULL ON ERROR),
           JSON_VALUE(p_after_json, '$.row_count' RETURNING NUMBER NULL ON ERROR),
           JSON_VALUE(p_before_json, '$.last_output_rows' RETURNING NUMBER NULL ON ERROR),
           JSON_VALUE(p_after_json, '$.last_output_rows' RETURNING NUMBER NULL ON ERROR),
           JSON_VALUE(p_before_json, '$.last_cr_buffer_gets' RETURNING NUMBER NULL ON ERROR),
           JSON_VALUE(p_after_json, '$.last_cr_buffer_gets' RETURNING NUMBER NULL ON ERROR),
           JSON_VALUE(p_before_json, '$.last_disk_reads' RETURNING NUMBER NULL ON ERROR),
           JSON_VALUE(p_after_json, '$.last_disk_reads' RETURNING NUMBER NULL ON ERROR),
           JSON_VALUE(p_before_json, '$.last_elapsed_time_us' RETURNING NUMBER NULL ON ERROR),
           JSON_VALUE(p_after_json, '$.last_elapsed_time_us' RETURNING NUMBER NULL ON ERROR),
           JSON_VALUE(p_before_json, '$.result_digest' RETURNING VARCHAR2(64) NULL ON ERROR),
           JSON_VALUE(p_after_json, '$.result_digest' RETURNING VARCHAR2(64) NULL ON ERROR),
           JSON_VALUE(p_before_json, '$.result_digest_status' RETURNING VARCHAR2(30) NULL ON ERROR),
           JSON_VALUE(p_after_json, '$.result_digest_status' RETURNING VARCHAR2(30) NULL ON ERROR),
           JSON_VALUE(p_before_json, '$.result_digest_scope' RETURNING VARCHAR2(30) NULL ON ERROR),
           JSON_VALUE(p_after_json, '$.result_digest_scope' RETURNING VARCHAR2(30) NULL ON ERROR),
           JSON_VALUE(p_before_json, '$.result_digest_mode' RETURNING VARCHAR2(30) NULL ON ERROR),
           JSON_VALUE(p_after_json, '$.result_digest_mode' RETURNING VARCHAR2(30) NULL ON ERROR),
           JSON_VALUE(p_before_json, '$.result_metadata_digest' RETURNING VARCHAR2(64) NULL ON ERROR),
           JSON_VALUE(p_after_json, '$.result_metadata_digest' RETURNING VARCHAR2(64) NULL ON ERROR),
           JSON_VALUE(p_before_json, '$.result_total_rows' RETURNING NUMBER NULL ON ERROR),
           JSON_VALUE(p_after_json, '$.result_total_rows' RETURNING NUMBER NULL ON ERROR),
           JSON_VALUE(p_before_json, '$.result_digest_rows' RETURNING NUMBER NULL ON ERROR),
           JSON_VALUE(p_after_json, '$.result_digest_rows' RETURNING NUMBER NULL ON ERROR),
           JSON_VALUE(p_before_json, '$.result_evidence_complete' RETURNING VARCHAR2(10) NULL ON ERROR),
           JSON_VALUE(p_after_json, '$.result_evidence_complete' RETURNING VARCHAR2(10) NULL ON ERROR),
           JSON_VALUE(p_before_json, '$.child_cursor_evidence.bind_coverage_status' RETURNING VARCHAR2(30) NULL ON ERROR),
           JSON_VALUE(p_after_json, '$.child_cursor_evidence.bind_coverage_status' RETURNING VARCHAR2(30) NULL ON ERROR),
           JSON_VALUE(p_before_json, '$.child_cursor_evidence.bind_coverage_reason' RETURNING VARCHAR2(100) NULL ON ERROR),
           JSON_VALUE(p_after_json, '$.child_cursor_evidence.bind_coverage_reason' RETURNING VARCHAR2(100) NULL ON ERROR)
    INTO   l_before_status,
           l_after_status,
           l_before_error,
           l_after_error,
           l_before_rows,
           l_after_rows,
           l_before_output,
           l_after_output,
           l_before_gets,
           l_after_gets,
           l_before_reads,
           l_after_reads,
           l_before_elapsed,
           l_after_elapsed,
           l_before_digest,
           l_after_digest,
           l_before_digest_status,
           l_after_digest_status,
           l_before_digest_scope,
           l_after_digest_scope,
           l_before_digest_mode,
           l_after_digest_mode,
           l_before_metadata_digest,
           l_after_metadata_digest,
           l_before_total_rows,
           l_after_total_rows,
           l_before_digest_rows,
           l_after_digest_rows,
           l_before_complete,
           l_after_complete,
           l_before_bind_coverage_status,
           l_after_bind_coverage_status,
           l_before_bind_coverage_reason,
           l_after_bind_coverage_reason
    FROM   dual;

    IF UPPER(NVL(l_before_bind_coverage_status, 'BLOCKED')) = 'NOT_APPLICABLE'
       AND UPPER(NVL(l_after_bind_coverage_status, 'BLOCKED')) = 'NOT_APPLICABLE' THEN
      l_bind_coverage_status := 'NOT_APPLICABLE';
      l_bind_coverage_reason := 'BIND_NOT_APPLICABLE';
    ELSIF UPPER(NVL(l_before_bind_coverage_status, 'BLOCKED')) = 'VERIFIED'
          AND UPPER(NVL(l_after_bind_coverage_status, 'BLOCKED')) = 'VERIFIED' THEN
      l_bind_coverage_status := 'VERIFIED';
      l_bind_coverage_reason := 'REPRESENTATIVE_BIND_COVERAGE_VERIFIED';
    ELSE
      l_bind_coverage_status := 'BLOCKED';
      l_bind_coverage_reason := COALESCE(
        NULLIF(l_after_bind_coverage_reason, 'BIND_NOT_APPLICABLE'),
        NULLIF(l_before_bind_coverage_reason, 'BIND_NOT_APPLICABLE'),
        'BIND_COVERAGE_INSUFFICIENT'
      );
    END IF;

    SELECT JSON_VALUE(p_before_json, '$.measurement_status' RETURNING VARCHAR2(30) NULL ON ERROR),
           JSON_VALUE(p_after_json, '$.measurement_status' RETURNING VARCHAR2(30) NULL ON ERROR),
           JSON_VALUE(p_before_json, '$.measurement_reason' RETURNING VARCHAR2(100) NULL ON ERROR),
           JSON_VALUE(p_after_json, '$.measurement_reason' RETURNING VARCHAR2(100) NULL ON ERROR),
           JSON_VALUE(p_before_json, '$.measurement_count' RETURNING NUMBER NULL ON ERROR),
           JSON_VALUE(p_after_json, '$.measurement_count' RETURNING NUMBER NULL ON ERROR),
           JSON_VALUE(p_before_json, '$.median_elapsed_time_us' RETURNING NUMBER NULL ON ERROR),
           JSON_VALUE(p_after_json, '$.median_elapsed_time_us' RETURNING NUMBER NULL ON ERROR),
           JSON_VALUE(p_before_json, '$.median_buffer_gets' RETURNING NUMBER NULL ON ERROR),
           JSON_VALUE(p_after_json, '$.median_buffer_gets' RETURNING NUMBER NULL ON ERROR),
           JSON_VALUE(p_before_json, '$.median_disk_reads' RETURNING NUMBER NULL ON ERROR),
           JSON_VALUE(p_after_json, '$.median_disk_reads' RETURNING NUMBER NULL ON ERROR),
           JSON_VALUE(p_before_json, '$.elapsed_noise_pct' RETURNING NUMBER NULL ON ERROR),
           JSON_VALUE(p_after_json, '$.elapsed_noise_pct' RETURNING NUMBER NULL ON ERROR),
           JSON_VALUE(p_before_json, '$.repeat_count' RETURNING NUMBER NULL ON ERROR),
           JSON_VALUE(p_after_json, '$.repeat_count' RETURNING NUMBER NULL ON ERROR),
           JSON_VALUE(p_before_json, '$.elapsed_wall_ms' RETURNING NUMBER NULL ON ERROR),
           JSON_VALUE(p_after_json, '$.elapsed_wall_ms' RETURNING NUMBER NULL ON ERROR)
    INTO   l_before_measurement_status, l_after_measurement_status,
           l_before_measurement_reason, l_after_measurement_reason,
           l_before_measurement_count, l_after_measurement_count,
           l_before_median_elapsed, l_after_median_elapsed,
           l_before_median_gets, l_after_median_gets,
           l_before_median_reads, l_after_median_reads,
           l_before_noise_pct, l_after_noise_pct,
           l_before_repeat_count, l_after_repeat_count,
           l_before_elapsed_wall_ms, l_after_elapsed_wall_ms
    FROM dual;

    l_intent_object := JSON_VALUE(
      p_before_json,
      '$.optimizer_intent_evidence.dominant_repeated_object' RETURNING VARCHAR2(128) NULL ON ERROR
    );
    l_before_target_starts := JSON_VALUE(
      p_before_json,
      '$.optimizer_intent_evidence.dominant_repeated_starts' RETURNING NUMBER NULL ON ERROR
    );
    l_after_anti_semi := JSON_VALUE(
      p_after_json,
      '$.optimizer_intent_evidence.anti_semi_present' RETURNING VARCHAR2(10) NULL ON ERROR
    );
    l_before_plan_hash := JSON_VALUE(p_before_json, '$.plan_hash_value' RETURNING NUMBER NULL ON ERROR);
    l_after_plan_hash := JSON_VALUE(p_after_json, '$.plan_hash_value' RETURNING NUMBER NULL ON ERROR);
    IF l_intent_object IS NULL THEN
      BEGIN
        SELECT b.object_name, b.starts, b.buffers
        INTO l_intent_object, l_before_target_starts, l_before_target_buffers
        FROM JSON_TABLE(p_before_json, '$.optimizer_intent_evidence.nodes[*]'
          COLUMNS(
            object_name VARCHAR2(128) PATH '$.object_name' NULL ON ERROR,
            starts NUMBER PATH '$.starts' NULL ON ERROR,
            buffers NUMBER PATH '$.buffers' NULL ON ERROR
          )) b
        JOIN JSON_TABLE(p_after_json, '$.optimizer_intent_evidence.nodes[*]'
          COLUMNS(object_name VARCHAR2(128) PATH '$.object_name' NULL ON ERROR)) a
          ON UPPER(a.object_name) = UPPER(b.object_name)
        WHERE b.object_name IS NOT NULL AND b.buffers IS NOT NULL
        ORDER BY b.buffers DESC
        FETCH FIRST 1 ROW ONLY;
      EXCEPTION WHEN OTHERS THEN
        BEGIN
          SELECT object_name, starts, buffers
          INTO l_intent_object, l_before_target_starts, l_before_target_buffers
          FROM JSON_TABLE(p_before_json, '$.optimizer_intent_evidence.nodes[*]'
            COLUMNS(
              object_name VARCHAR2(128) PATH '$.object_name' NULL ON ERROR,
              starts NUMBER PATH '$.starts' NULL ON ERROR,
              buffers NUMBER PATH '$.buffers' NULL ON ERROR
            ))
          WHERE object_name IS NOT NULL AND buffers IS NOT NULL
          ORDER BY buffers DESC
          FETCH FIRST 1 ROW ONLY;
        EXCEPTION WHEN OTHERS THEN NULL;
        END;
      END;
    ELSE
      SELECT MAX(buffers)
      INTO l_before_target_buffers
      FROM JSON_TABLE(p_before_json, '$.optimizer_intent_evidence.nodes[*]'
        COLUMNS(
          object_name VARCHAR2(128) PATH '$.object_name' NULL ON ERROR,
          buffers NUMBER PATH '$.buffers' NULL ON ERROR
        ))
      WHERE UPPER(object_name) = UPPER(l_intent_object);
    END IF;
    BEGIN
      SELECT MAX(starts), MAX(buffers)
      INTO l_after_target_starts, l_after_target_buffers
      FROM JSON_TABLE(p_after_json, '$.optimizer_intent_evidence.nodes[*]'
        COLUMNS(
          object_name VARCHAR2(128) PATH '$.object_name' NULL ON ERROR,
          starts NUMBER PATH '$.starts' NULL ON ERROR,
          buffers NUMBER PATH '$.buffers' NULL ON ERROR
        ))
      WHERE UPPER(object_name) = UPPER(l_intent_object);
    EXCEPTION WHEN OTHERS THEN l_after_target_starts := NULL;
    END;
    IF l_intent_object IS NOT NULL
       AND (
         (l_before_target_starts > 1 AND l_after_target_starts IS NOT NULL AND l_after_target_starts <= 1)
         OR
         (l_before_target_buffers > 0 AND l_after_target_buffers IS NOT NULL
          AND l_after_target_buffers <= l_before_target_buffers * 0.8)
         OR
         (l_before_target_buffers > 0 AND l_after_target_buffers IS NULL
          AND l_before_gets > 0 AND l_after_gets <= l_before_gets * 0.8)
         OR
         (l_before_plan_hash IS NOT NULL AND l_after_plan_hash IS NOT NULL
          AND l_before_plan_hash <> l_after_plan_hash
          AND l_before_gets > 0 AND l_after_gets <= l_before_gets * 0.8)
       ) THEN
      l_optimizer_intent_status := 'VERIFIED';
      l_optimizer_intent_reason := CASE
        WHEN LOWER(NVL(l_after_anti_semi, 'false')) = 'true'
          THEN 'OPTIMIZER_INTENT_VERIFIED'
        WHEN l_before_target_starts > 1 AND l_after_target_starts <= 1
          THEN 'REPEATED_PRODUCER_ELIMINATED'
        WHEN l_after_target_buffers IS NULL
          THEN 'TARGET_OPERATION_ELIMINATED'
        WHEN l_before_plan_hash <> l_after_plan_hash
          THEN 'PLAN_SHAPE_BUFFER_REDUCTION_VERIFIED'
        ELSE 'TARGET_ACCESS_PATH_BUFFERS_REDUCED'
      END;
    ELSE
      l_optimizer_intent_status := 'BLOCKED';
      l_optimizer_intent_reason := 'OPTIMIZER_INTENT_EVIDENCE_INCOMPLETE';
    END IF;

    IF UPPER(NVL(l_before_measurement_status, 'BLOCKED')) = 'ACCEPTED'
       AND UPPER(NVL(l_after_measurement_status, 'BLOCKED')) = 'ACCEPTED'
       AND l_before_measurement_count = 3 AND l_after_measurement_count = 3 THEN
      l_measurement_status := 'ACCEPTED';
      l_measurement_reason := 'MEASUREMENT_ACCEPTED';
      l_before_elapsed := l_before_median_elapsed;
      l_after_elapsed := l_after_median_elapsed;
      l_before_gets := l_before_median_gets;
      l_after_gets := l_after_median_gets;
      l_before_reads := l_before_median_reads;
      l_after_reads := l_after_median_reads;
    ELSE
      l_measurement_status := 'BLOCKED';
      l_measurement_reason := COALESCE(
        NULLIF(l_after_measurement_reason, 'MEASUREMENT_ACCEPTED'),
        NULLIF(l_before_measurement_reason, 'MEASUREMENT_ACCEPTED'),
        'MEASUREMENT_EVIDENCE_INCOMPLETE'
      );
    END IF;

    IF UPPER(NVL(l_before_status, 'COMPLETED')) = 'FAILED'
       OR UPPER(NVL(l_after_status, 'COMPLETED')) = 'FAILED'
       OR l_before_error IS NOT NULL
       OR l_after_error IS NOT NULL THEN
      RETURN TO_CLOB(
        '{"status":"FAILED","code":"BEFORE_AFTER_COMPARISON","contract_version":"asta.v1","execution_boundary":"ADB_COMPARISON_PLSQL","verdict":"CANDIDATE_FAILED","verdict_reason":' ||
        json_str(NVL(l_after_error, l_before_error)) || ',"equivalence_status":"UNKNOWN","retain_original_sql":true}'
      );
    END IF;

    l_row_match := CASE
      WHEN l_before_rows IS NULL OR l_after_rows IS NULL THEN 'null'
      WHEN l_before_rows = l_after_rows THEN 'true'
      ELSE 'false'
    END;
    l_output_match := CASE
      WHEN l_before_output IS NULL OR l_after_output IS NULL THEN 'null'
      WHEN l_before_output = l_after_output THEN 'true'
      ELSE 'false'
    END;
    l_gets_delta := CASE
      WHEN l_before_gets IS NULL OR l_after_gets IS NULL THEN NULL
      ELSE l_before_gets - l_after_gets
    END;
    l_gets_pct := CASE
      WHEN l_before_gets IS NULL OR l_after_gets IS NULL OR l_before_gets = 0 THEN NULL
      ELSE ROUND(((l_before_gets - l_after_gets) / l_before_gets) * 100, 2)
    END;
    l_reads_delta := CASE
      WHEN l_before_reads IS NULL OR l_after_reads IS NULL THEN NULL
      ELSE l_before_reads - l_after_reads
    END;
    l_elapsed_delta := CASE
      WHEN l_before_elapsed IS NULL OR l_after_elapsed IS NULL THEN NULL
      ELSE l_before_elapsed - l_after_elapsed
    END;
    l_elapsed_increase := CASE
      WHEN l_before_elapsed IS NULL OR l_after_elapsed IS NULL THEN NULL
      ELSE l_after_elapsed - l_before_elapsed
    END;
    l_after_under_1s := CASE WHEN l_after_elapsed IS NOT NULL AND l_after_elapsed <= 1000000 THEN 'true' ELSE 'false' END;
    l_latency_risk := CASE
      WHEN l_after_elapsed IS NULL OR l_before_elapsed IS NULL THEN 'UNKNOWN'
      WHEN l_after_elapsed <= l_before_elapsed THEN 'LOW'
      WHEN l_after_elapsed <= 1000000 OR (l_after_elapsed - l_before_elapsed) <= 300000 THEN 'LIMITED'
      ELSE 'HIGH'
    END;

    IF l_optimizer_intent_status <> 'VERIFIED' THEN
      l_verdict := 'INSUFFICIENT_EVIDENCE'; l_verdict_reason := l_optimizer_intent_reason; l_equivalence := 'UNKNOWN';
    ELSIF l_before_digest_scope <> 'FULL_RESULT' OR l_after_digest_scope <> 'FULL_RESULT' THEN
      l_verdict := 'INSUFFICIENT_EVIDENCE'; l_verdict_reason := 'FULL_RESULT_EVIDENCE_REQUIRED'; l_equivalence := 'UNKNOWN';
    ELSIF l_before_digest_mode IS NULL OR l_after_digest_mode IS NULL OR l_before_digest_mode <> l_after_digest_mode THEN
      l_verdict := 'INSUFFICIENT_EVIDENCE'; l_verdict_reason := 'RESULT_DIGEST_MODE_MISMATCH'; l_equivalence := 'UNKNOWN';
    ELSIF l_before_metadata_digest IS NULL OR l_after_metadata_digest IS NULL
          OR l_before_metadata_digest <> l_after_metadata_digest THEN
      l_verdict := 'NON_EQUIVALENT'; l_verdict_reason := 'RESULT_METADATA_MISMATCH'; l_equivalence := 'NON_EQUIVALENT';
    ELSIF LOWER(NVL(l_before_complete, 'false')) <> 'true'
          OR LOWER(NVL(l_after_complete, 'false')) <> 'true'
          OR l_before_total_rows IS NULL OR l_after_total_rows IS NULL
          OR l_before_digest_rows <> l_before_total_rows
          OR l_after_digest_rows <> l_after_total_rows THEN
      l_verdict := 'INSUFFICIENT_EVIDENCE'; l_verdict_reason := 'RESULT_EVIDENCE_INCOMPLETE'; l_equivalence := 'UNKNOWN';
    ELSIF UPPER(NVL(l_before_digest_status, 'MISSING')) <> 'COMPLETED'
       OR UPPER(NVL(l_after_digest_status, 'MISSING')) <> 'COMPLETED'
       OR l_before_digest IS NULL OR l_after_digest IS NULL THEN
      l_verdict := 'INSUFFICIENT_EVIDENCE'; l_verdict_reason := 'RESULT_DIGEST_REQUIRED'; l_equivalence := 'UNKNOWN';
    ELSIF l_before_digest <> l_after_digest THEN
      l_verdict := 'NON_EQUIVALENT'; l_verdict_reason := 'RESULT_DIGEST_MISMATCH'; l_equivalence := 'NON_EQUIVALENT';
    ELSIF l_row_match = 'false' OR l_output_match = 'false' THEN
      l_verdict := 'NON_EQUIVALENT'; l_verdict_reason := 'Result equivalence signals differ'; l_equivalence := 'NON_EQUIVALENT';
    ELSIF l_row_match = 'null' OR l_output_match = 'null' OR l_before_elapsed IS NULL OR l_after_elapsed IS NULL THEN
      l_verdict := 'INSUFFICIENT_EVIDENCE'; l_verdict_reason := 'Required comparison evidence is missing'; l_equivalence := 'UNKNOWN';
    ELSIF UPPER(NVL(l_bind_coverage_status, 'BLOCKED')) NOT IN ('VERIFIED', 'NOT_APPLICABLE') THEN
      l_verdict := 'INSUFFICIENT_EVIDENCE'; l_verdict_reason := NVL(l_bind_coverage_reason, 'BIND_COVERAGE_INSUFFICIENT'); l_equivalence := 'VERIFIED';
    ELSIF l_measurement_status <> 'ACCEPTED' THEN
      l_verdict := 'INSUFFICIENT_EVIDENCE'; l_verdict_reason := l_measurement_reason; l_equivalence := 'VERIFIED';
    ELSIF l_workload_type = 'BATCH' AND l_after_elapsed >= l_before_elapsed THEN
      l_verdict := 'NOT_IMPROVED'; l_verdict_reason := 'BATCH_ELAPSED_TIME_NOT_IMPROVED'; l_equivalence := 'VERIFIED';
    ELSIF l_workload_type = 'BATCH' THEN
      l_verdict := 'IMPROVED'; l_verdict_reason := 'BATCH_ELAPSED_TIME_IMPROVED'; l_equivalence := 'VERIFIED';
    ELSIF l_before_gets IS NULL OR l_after_gets IS NULL OR l_before_gets = 0 THEN
      l_verdict := 'INSUFFICIENT_EVIDENCE'; l_verdict_reason := 'OLTP buffer gets evidence is missing'; l_equivalence := 'UNKNOWN';
    ELSIF l_after_elapsed <= l_before_elapsed AND l_gets_pct >= 5 THEN
      l_verdict := 'IMPROVED'; l_verdict_reason := 'OLTP_BUFFER_READS_IMPROVED'; l_equivalence := 'VERIFIED';
    ELSIF l_gets_pct >= 20 AND l_after_elapsed > l_before_elapsed
          AND (l_after_elapsed <= 1000000 OR (l_after_elapsed - l_before_elapsed) <= 300000) THEN
      l_verdict := 'IMPROVED'; l_verdict_reason := 'OLTP_BUFFER_READS_MEANINGFUL_IMPROVEMENT'; l_equivalence := 'VERIFIED';
    ELSIF l_gets_pct >= 20 AND l_after_elapsed > l_before_elapsed THEN
      l_verdict := 'NOT_IMPROVED'; l_verdict_reason := 'OLTP_BUFFER_READS_IMPROVED_LATENCY_TRADEOFF_TOO_LARGE'; l_equivalence := 'VERIFIED';
    ELSE
      l_verdict := 'NOT_IMPROVED'; l_verdict_reason := 'OLTP_BUFFER_READS_NOT_IMPROVED'; l_equivalence := 'VERIFIED';
    END IF;
    l_retain_original := CASE WHEN l_verdict = 'IMPROVED' THEN 'false' ELSE 'true' END;

    RETURN TO_CLOB(
      '{"status":"COMPLETED","code":"BEFORE_AFTER_COMPARISON","contract_version":"asta.v1","execution_boundary":"ADB_COMPARISON_PLSQL"' ||
      ',"verdict":' || json_str(l_verdict) ||
      ',"workload_type":' || json_str(l_workload_type) ||
      ',"primary_metric":' || json_str(l_primary_metric) ||
      ',"optimization_goal":' || json_str(l_optimization_goal) ||
      ',"verdict_reason":' || json_str(l_verdict_reason) ||
      ',"equivalence_status":' || json_str(l_equivalence) ||
      ',"equivalence_reason":' || json_str(CASE WHEN l_equivalence = 'VERIFIED' THEN 'RESULT_EQUIVALENCE_VERIFIED' ELSE l_verdict_reason END) ||
      ',"equivalence_strength":' || json_str(CASE WHEN l_equivalence = 'VERIFIED' THEN 'FULL_RESULT_DIGEST' ELSE 'NONE' END) ||
      ',"optimizer_intent_status":' || json_str(l_optimizer_intent_status) ||
      ',"optimizer_intent_reason":' || json_str(l_optimizer_intent_reason) ||
      ',"optimizer_intent_object":' || json_str(l_intent_object) ||
      ',"producer_starts_before":' || json_num(l_before_target_starts) ||
      ',"producer_starts_after":' || json_num(l_after_target_starts) ||
      ',"result_digest_scope":' || json_str(l_after_digest_scope) ||
      ',"result_digest_mode":' || json_str(l_after_digest_mode) ||
      ',"bind_stability_status":' || json_str(UPPER(NVL(l_bind_coverage_status, 'BLOCKED'))) ||
      ',"bind_stability_reason":' || json_str(NVL(l_bind_coverage_reason, 'BIND_COVERAGE_INSUFFICIENT')) ||
      ',"all_representative_binds_passed":' || CASE WHEN UPPER(NVL(l_bind_coverage_status, 'BLOCKED')) IN ('VERIFIED', 'NOT_APPLICABLE') THEN 'true' ELSE 'false' END ||
      ',"measurement_status":' || json_str(l_measurement_status) ||
      ',"measurement_reason":' || json_str(l_measurement_reason) ||
      ',"measurement_count":' || json_num(LEAST(l_before_measurement_count, l_after_measurement_count)) ||
      ',"before_median_elapsed_us":' || json_num(l_before_median_elapsed) ||
      ',"after_median_elapsed_us":' || json_num(l_after_median_elapsed) ||
      ',"before_median_buffer_gets":' || json_num(l_before_median_gets) ||
      ',"after_median_buffer_gets":' || json_num(l_after_median_gets) ||
      ',"before_elapsed_noise_pct":' || json_num(l_before_noise_pct) ||
      ',"after_elapsed_noise_pct":' || json_num(l_after_noise_pct) ||
      ',"noise_pct":' || json_num(GREATEST(l_before_noise_pct, l_after_noise_pct)) ||
      ',"retain_original_sql":' || l_retain_original ||
      ',"row_count_matches":'          || l_row_match ||
      ',"output_rows_match":'          || l_output_match ||
      ',"before_row_count":'           || json_num(l_before_rows) ||
      ',"after_row_count":'            || json_num(l_after_rows) ||
      ',"before_output_rows":'         || json_num(l_before_output) ||
      ',"after_output_rows":'          || json_num(l_after_output) ||
      ',"before_result_digest":'       || json_str(l_before_digest) ||
      ',"after_result_digest":'        || json_str(l_after_digest) ||
      ',"result_digest_matches":'      || CASE WHEN l_before_digest IS NOT NULL AND l_before_digest = l_after_digest THEN 'true' ELSE 'false' END ||
      ',"before_buffer_gets":'         || json_num(l_before_gets) ||
      ',"after_buffer_gets":'          || json_num(l_after_gets) ||
      ',"buffer_gets_delta":'          || json_num(l_gets_delta) ||
      ',"buffer_gets_reduction_pct":'  || json_num(l_gets_pct) ||
      ',"before_disk_reads":'          || json_num(l_before_reads) ||
      ',"after_disk_reads":'           || json_num(l_after_reads) ||
      ',"disk_reads_delta":'           || json_num(l_reads_delta) ||
      ',"before_elapsed_time_us":'     || json_num(l_before_elapsed) ||
      ',"after_elapsed_time_us":'      || json_num(l_after_elapsed) ||
      ',"elapsed_time_us_delta":'      || json_num(l_elapsed_delta) ||
      ',"elapsed_delta_us":'           || json_num(l_elapsed_increase) ||
      ',"after_elapsed_under_1s":'      || l_after_under_1s ||
      ',"user_perceptible_latency_risk":' || json_str(l_latency_risk) ||
      '}'
    );
  EXCEPTION
    WHEN OTHERS THEN
      RETURN TO_CLOB(
        '{"status":"FAILED","code":"BEFORE_AFTER_COMPARISON","contract_version":"asta.v1","execution_boundary":"ADB_COMPARISON_PLSQL","message":' ||
        json_str(SUBSTR(SQLERRM, 1, 4000)) || '}'
      );
  END build_comparison_json;

  FUNCTION inline_change_summary(p_llm_json IN CLOB) RETURN VARCHAR2 IS
    l_sql CLOB; l_comment VARCHAR2(4000); l_body VARCHAR2(4000); l_out VARCHAR2(4000);
  BEGIN
    SELECT JSON_VALUE(p_llm_json, '$.candidate_sql' RETURNING CLOB NULL ON ERROR) INTO l_sql FROM dual;
    FOR i IN 1..50 LOOP
      l_comment := REGEXP_SUBSTR(DBMS_LOB.SUBSTR(l_sql, 32767, 1), '/\*[[:space:]]*ASTA_TUNING_CHANGE_[0-9]+:[[:space:]]*([^*]|\*+[^*/])*\*+/', 1, i, 'in');
      EXIT WHEN l_comment IS NULL;
      l_body := REGEXP_REPLACE(l_comment, '^/\*[[:space:]]*ASTA_TUNING_CHANGE_[0-9]+:[[:space:]]*|[[:space:]]*\*/$', '', 1, 0, 'in');
      l_body := REGEXP_REPLACE(l_body, '[[:space:]]+', ' ');
      l_out := l_out || CASE WHEN l_out IS NULL THEN '' ELSE '; ' END || l_body;
    END LOOP;
    RETURN l_out;
  EXCEPTION WHEN OTHERS THEN RETURN NULL;
  END inline_change_summary;

  FUNCTION build_vector_metadata(
    p_comparison_json IN CLOB, p_before_json IN CLOB, p_after_json IN CLOB,
    p_llm_json IN CLOB
  ) RETURN CLOB IS
    l_out CLOB;
    l_inline_summary VARCHAR2(4000);
  BEGIN
    l_inline_summary := inline_change_summary(p_llm_json);
    SELECT JSON_OBJECT(
      'verdict' VALUE JSON_VALUE(p_comparison_json, '$.verdict' NULL ON ERROR),
      'learning_class' VALUE CASE
        WHEN JSON_VALUE(p_comparison_json, '$.verdict' RETURNING VARCHAR2(30) NULL ON ERROR) = 'IMPROVED'
         AND JSON_VALUE(p_comparison_json, '$.optimizer_intent_status' RETURNING VARCHAR2(30) NULL ON ERROR) = 'VERIFIED'
         AND JSON_VALUE(p_comparison_json, '$.result_digest_scope' RETURNING VARCHAR2(30) NULL ON ERROR) = 'FULL_RESULT'
         AND JSON_VALUE(p_comparison_json, '$.equivalence_status' RETURNING VARCHAR2(30) NULL ON ERROR) = 'VERIFIED'
         AND JSON_VALUE(p_comparison_json, '$.bind_stability_status' RETURNING VARCHAR2(30) NULL ON ERROR) IN ('VERIFIED', 'NOT_APPLICABLE')
         AND JSON_VALUE(p_comparison_json, '$.all_representative_binds_passed' RETURNING VARCHAR2(10) NULL ON ERROR) = 'true'
         AND JSON_VALUE(p_comparison_json, '$.measurement_status' RETURNING VARCHAR2(30) NULL ON ERROR) = 'ACCEPTED'
        THEN 'POSITIVE_VERIFIED'
        WHEN JSON_VALUE(p_comparison_json, '$.verdict' RETURNING VARCHAR2(30) NULL ON ERROR) = 'ANALYSIS_ONLY'
        THEN 'ANALYSIS_OBSERVATION'
        ELSE 'REJECTED_OBSERVATION'
      END,
      'workload_type' VALUE JSON_VALUE(p_comparison_json, '$.workload_type' NULL ON ERROR),
      'primary_metric' VALUE JSON_VALUE(p_comparison_json, '$.primary_metric' NULL ON ERROR),
      'verdict_reason' VALUE JSON_VALUE(p_comparison_json, '$.verdict_reason' NULL ON ERROR),
      'equivalence_status' VALUE JSON_VALUE(p_comparison_json, '$.equivalence_status' NULL ON ERROR),
      'optimizer_intent_status' VALUE JSON_VALUE(p_comparison_json, '$.optimizer_intent_status' NULL ON ERROR),
      'result_digest_scope' VALUE JSON_VALUE(p_comparison_json, '$.result_digest_scope' NULL ON ERROR),
      'bind_stability_status' VALUE JSON_VALUE(p_comparison_json, '$.bind_stability_status' NULL ON ERROR),
      'all_representative_binds_passed' VALUE JSON_VALUE(p_comparison_json, '$.all_representative_binds_passed' NULL ON ERROR),
      'measurement_status' VALUE JSON_VALUE(p_comparison_json, '$.measurement_status' NULL ON ERROR),
      'before_buffer_gets' VALUE JSON_VALUE(p_comparison_json, '$.before_buffer_gets' RETURNING NUMBER NULL ON ERROR),
      'after_buffer_gets' VALUE JSON_VALUE(p_comparison_json, '$.after_buffer_gets' RETURNING NUMBER NULL ON ERROR),
      'before_elapsed_time_us' VALUE JSON_VALUE(p_comparison_json, '$.before_elapsed_time_us' RETURNING NUMBER NULL ON ERROR),
      'after_elapsed_time_us' VALUE JSON_VALUE(p_comparison_json, '$.after_elapsed_time_us' RETURNING NUMBER NULL ON ERROR),
      'before_disk_reads' VALUE JSON_VALUE(p_comparison_json, '$.before_disk_reads' RETURNING NUMBER NULL ON ERROR),
      'after_disk_reads' VALUE JSON_VALUE(p_comparison_json, '$.after_disk_reads' RETURNING NUMBER NULL ON ERROR),
      'before_plan_hash_value' VALUE JSON_VALUE(p_before_json, '$.plan_hash_value' NULL ON ERROR),
      'after_plan_hash_value' VALUE JSON_VALUE(p_after_json, '$.plan_hash_value' NULL ON ERROR),
      'rewrite_type' VALUE JSON_VALUE(p_llm_json, '$.rewrite_type' NULL ON ERROR),
      'change_summary' VALUE COALESCE(
        NULLIF(JSON_SERIALIZE(JSON_QUERY(p_llm_json, '$.change_summary' RETURNING CLOB NULL ON ERROR) RETURNING VARCHAR2(4000)), '[]'),
        l_inline_summary, '-'
      ),
      'change_summary_items' VALUE COALESCE(
        JSON_QUERY(p_llm_json, '$.change_summary' RETURNING CLOB NULL ON ERROR),
        TO_CLOB('[]')
      ) FORMAT JSON,
      'advisor_summary' VALUE JSON_VALUE(p_before_json, '$.advisor.status' NULL ON ERROR)
      RETURNING CLOB) INTO l_out FROM dual;
    RETURN l_out;
  EXCEPTION WHEN OTHERS THEN
    RETURN TO_CLOB('{"verdict":"INSUFFICIENT_EVIDENCE","verdict_reason":"metadata assembly failed"}');
  END build_vector_metadata;

  FUNCTION llm_original_fallback_json(
    p_candidate_sql      IN CLOB,
    p_reason             IN VARCHAR2,
    p_rejected_candidate IN CLOB,
    p_generation_json    IN CLOB,
    p_repair_status      IN VARCHAR2,
    p_candidate_source   IN VARCHAR2 DEFAULT NULL
  ) RETURN CLOB IS
    l_out CLOB;
  BEGIN
    DBMS_LOB.CREATETEMPORARY(l_out, TRUE);
    clob_app(l_out, '{"status":"COMPLETED","code":"SQL_ONLY_REWRITE","contract_version":"asta.v1","execution_boundary":"ADB_DBMS_CLOUD_AI"');
    clob_app(l_out, ',"response_contract":"TWO_STAGE_DIAGNOSIS_JSON_AND_SQL_CLOB","candidate_guard_policy":"SELECT_WITH_SINGLE_STATEMENT"');
    clob_app(l_out, ',"candidate_sql":');
    clob_app_json_str(l_out, p_candidate_sql);
    clob_app(l_out, ',"rewrite_available":' || CASE WHEN p_candidate_sql IS NULL THEN 'false' ELSE 'true' END);
    clob_app(l_out, ',"repair_status":' || json_str(p_repair_status));
    clob_app(l_out, ',"candidate_source":' || json_str(p_candidate_source));
    clob_app(l_out, ',"candidate_error":');
    clob_app(l_out, json_str(SUBSTR(p_reason, 1, 4000)));
    clob_app(l_out, ',"rejected_candidate_sql":');
    clob_app_json_str(l_out, p_rejected_candidate);
    clob_app(l_out, ',"generation":');
    clob_app_clob(l_out, NVL(p_generation_json, TO_CLOB('null')));
    clob_app(l_out, '}');
    RETURN l_out;
  END llm_original_fallback_json;

  FUNCTION verified_history_candidate(
    p_sql               IN CLOB,
    p_current_run_id    IN VARCHAR2,
    p_source_db_id      IN VARCHAR2,
    p_workload_type     IN VARCHAR2,
    p_history_run_id    OUT VARCHAR2
  ) RETURN CLOB IS
    l_candidate CLOB;
  BEGIN
    p_history_run_id := NULL;
    FOR r IN (
      SELECT run_id, input_sql, tuned_sql
      FROM   asta_runs
      WHERE  run_id <> p_current_run_id
      AND    status = 'COMPLETED'
      AND    tuned_sql IS NOT NULL
      AND    DBMS_LOB.GETLENGTH(input_sql) = DBMS_LOB.GETLENGTH(p_sql)
      AND    source_db_id = p_source_db_id
      AND    UPPER(JSON_VALUE(response_json, '$.comparison.workload_type' RETURNING VARCHAR2(10) NULL ON ERROR)) = UPPER(p_workload_type)
      AND    UPPER(JSON_VALUE(response_json, '$.comparison.verdict' RETURNING VARCHAR2(30) NULL ON ERROR)) = 'IMPROVED'
      AND    UPPER(JSON_VALUE(response_json, '$.comparison.optimizer_intent_status' RETURNING VARCHAR2(30) NULL ON ERROR)) = 'VERIFIED'
      AND    UPPER(JSON_VALUE(response_json, '$.comparison.result_digest_scope' RETURNING VARCHAR2(30) NULL ON ERROR)) = 'FULL_RESULT'
      AND    UPPER(JSON_VALUE(response_json, '$.comparison.equivalence_status' RETURNING VARCHAR2(30) NULL ON ERROR)) = 'VERIFIED'
      AND    UPPER(JSON_VALUE(response_json, '$.comparison.measurement_status' RETURNING VARCHAR2(30) NULL ON ERROR)) = 'ACCEPTED'
      ORDER  BY completed_at DESC NULLS LAST
    ) LOOP
      IF DBMS_LOB.COMPARE(r.input_sql, p_sql) = 0
         AND DBMS_LOB.COMPARE(r.tuned_sql, p_sql) <> 0 THEN
        BEGIN
          asta_sql_guard_pkg.assert_candidate_compatible(r.tuned_sql);
          l_candidate := r.tuned_sql;
          p_history_run_id := r.run_id;
          RETURN l_candidate;
        EXCEPTION
          WHEN OTHERS THEN NULL;
        END;
      END IF;
    END LOOP;
    RETURN NULL;
  EXCEPTION
    WHEN OTHERS THEN
      p_history_run_id := NULL;
      RETURN NULL;
  END verified_history_candidate;

  FUNCTION candidate_timeout_seconds(
    p_source_json IN CLOB,
    p_expected_executions IN PLS_INTEGER DEFAULT 1,
    p_overhead_seconds IN PLS_INTEGER DEFAULT 30
  ) RETURN PLS_INTEGER IS
    l_elapsed_us NUMBER;
    l_executions PLS_INTEGER := LEAST(GREATEST(NVL(p_expected_executions, 1), 1), 10);
  BEGIN
    SELECT JSON_VALUE(p_source_json, '$.last_elapsed_time_us' RETURNING NUMBER NULL ON ERROR)
      INTO l_elapsed_us FROM dual;
    RETURN GREATEST(
      60,
      LEAST(
        1800,
        CEIL(NVL(l_elapsed_us, 10000000) / 1000000 * l_executions * 1.2 +
             GREATEST(NVL(p_overhead_seconds, 30), 0))
      )
    );
  EXCEPTION WHEN OTHERS THEN
    RETURN 300;
  END candidate_timeout_seconds;

  FUNCTION candidate_plan_screen_reason(
    p_before_json IN CLOB,
    p_screen_json IN CLOB,
    p_workload_type IN VARCHAR2
  ) RETURN VARCHAR2 IS
    l_before_elapsed NUMBER;
    l_after_elapsed NUMBER;
    l_before_gets NUMBER;
    l_after_gets NUMBER;
    l_intent_status VARCHAR2(30);
    l_screen_comparison CLOB;
    l_source_error VARCHAR2(4000);
  BEGIN
    l_source_error := source_response_error_message(p_screen_json);
    IF l_source_error IS NOT NULL THEN
      RETURN 'PLAN_SCREEN_SOURCE_ERROR: ' || SUBSTR(l_source_error, 1, 900);
    END IF;
    SELECT JSON_VALUE(p_before_json, '$.last_elapsed_time_us' RETURNING NUMBER NULL ON ERROR),
           JSON_VALUE(p_screen_json, '$.last_elapsed_time_us' RETURNING NUMBER NULL ON ERROR),
           JSON_VALUE(p_before_json, '$.last_cr_buffer_gets' RETURNING NUMBER NULL ON ERROR),
           JSON_VALUE(p_screen_json, '$.last_cr_buffer_gets' RETURNING NUMBER NULL ON ERROR)
      INTO l_before_elapsed, l_after_elapsed, l_before_gets, l_after_gets
      FROM dual;
    IF l_before_elapsed IS NULL OR l_after_elapsed IS NULL THEN
      RETURN 'PLAN_SCREEN_METRICS_MISSING';
    END IF;
    l_screen_comparison := build_comparison_json(
      p_before_json, p_screen_json, p_workload_type
    );
    l_intent_status := JSON_VALUE(
      l_screen_comparison,
      '$.optimizer_intent_status' RETURNING VARCHAR2(30) NULL ON ERROR
    );
    IF UPPER(NVL(l_intent_status, 'BLOCKED')) <> 'VERIFIED' THEN
      RETURN 'PLAN_SCREEN_OPTIMIZER_INTENT_NOT_VERIFIED';
    END IF;
    IF normalize_workload_type(p_workload_type) = 'BATCH' THEN
      IF l_after_elapsed >= l_before_elapsed * 0.95 THEN
        RETURN 'PLAN_SCREEN_ELAPSED_NOT_IMPROVED';
      END IF;
    ELSE
      IF l_before_gets IS NULL OR l_after_gets IS NULL OR l_before_gets <= 0 THEN
        RETURN 'PLAN_SCREEN_BUFFER_GETS_MISSING';
      ELSIF l_after_gets > l_before_gets * 0.95 THEN
        RETURN 'PLAN_SCREEN_BUFFER_GETS_NOT_IMPROVED';
      END IF;
    END IF;
    RETURN NULL;
  EXCEPTION
    WHEN OTHERS THEN
      RETURN 'PLAN_SCREEN_EVALUATION_FAILED: ' || SUBSTR(SQLERRM, 1, 800);
  END candidate_plan_screen_reason;

  PROCEDURE arm_candidate_watchdog(
    p_run_id IN VARCHAR2,
    p_timeout_seconds IN PLS_INTEGER,
    p_watchdog_job OUT VARCHAR2
  ) IS
  BEGIN
    p_watchdog_job := 'ASTA_WD_' || SUBSTR(UPPER(RAWTOHEX(SYS_GUID())), 1, 20);
    DBMS_SCHEDULER.CREATE_JOB(
      job_name            => p_watchdog_job,
      job_type            => 'STORED_PROCEDURE',
      job_action          => 'ASTA_PKG.ENFORCE_CANDIDATE_TIMEOUT',
      number_of_arguments => 1,
      start_date          => SYSTIMESTAMP + NUMTODSINTERVAL(p_timeout_seconds, 'SECOND'),
      enabled             => FALSE,
      auto_drop           => TRUE
    );
    DBMS_SCHEDULER.SET_JOB_ARGUMENT_VALUE(p_watchdog_job, 1, p_run_id);
    DBMS_SCHEDULER.ENABLE(p_watchdog_job);
  END arm_candidate_watchdog;

  PROCEDURE disarm_candidate_watchdog(p_watchdog_job IN OUT VARCHAR2) IS
  BEGIN
    IF p_watchdog_job IS NOT NULL THEN
      DBMS_SCHEDULER.DROP_JOB(p_watchdog_job, force => TRUE);
      p_watchdog_job := NULL;
    END IF;
  EXCEPTION WHEN OTHERS THEN
    p_watchdog_job := NULL;
  END disarm_candidate_watchdog;

  PROCEDURE enforce_candidate_timeout(p_run_id IN VARCHAR2) IS
    l_run_id VARCHAR2(64);
    l_parent_job VARCHAR2(128);
    l_source_db_id VARCHAR2(64);
    l_cancel_result CLOB;
    l_cancelled_count PLS_INTEGER := 0;
    l_detail VARCHAR2(4000) :=
      '후보 SQL 검증 시간이 초과되었습니다. 원본 SQL은 변경되지 않았습니다. ' ||
      '같은 테스트를 바로 반복하지 말고 Run ID를 담당자에게 전달해 주세요.';
  BEGIN
    l_run_id := normalize_run_id(p_run_id);
    SELECT job_name, source_db_id INTO l_parent_job, l_source_db_id
      FROM asta_runs
     WHERE run_id = l_run_id AND status = 'RUNNING';
    FOR i IN 1..5 LOOP
      BEGIN
        l_cancel_result := asta_source_bridge_pkg.cancel_source_run(
          l_source_db_id,
          l_run_id || CASE i
            WHEN 1 THEN '-TUNED-SCREEN'
            WHEN 2 THEN '-REPAIRED-SCREEN'
            WHEN 3 THEN '-REPAIRED2-SCREEN'
            WHEN 4 THEN '-BASELINE-FINAL'
            ELSE '-TUNED-FINAL'
          END
        );
        l_cancelled_count := l_cancelled_count + NVL(
          JSON_VALUE(l_cancel_result, '$.cancelled_sql_count' RETURNING NUMBER NULL ON ERROR),
          0
        );
      EXCEPTION WHEN OTHERS THEN NULL;
      END;
    END LOOP;
    l_detail := l_detail || ' Source cancel requests completed; cancelled SQL count=' ||
      TO_CHAR(l_cancelled_count) || '.';
    UPDATE asta_run_progress
       SET status='FAILED', detail=l_detail, completed_at=SYSTIMESTAMP
     WHERE run_id=l_run_id AND seq=7 AND status='RUNNING';
    UPDATE asta_runs
       SET status='FAILED', completed_at=SYSTIMESTAMP,
           error_code='CANDIDATE_RUNTIME_LIMIT', error_message=l_detail
     WHERE run_id=l_run_id AND status='RUNNING';
    COMMIT;
    DBMS_SCHEDULER.STOP_JOB(l_parent_job, force => TRUE);
  EXCEPTION
    WHEN NO_DATA_FOUND THEN NULL;
    WHEN OTHERS THEN ROLLBACK;
  END enforce_candidate_timeout;

  FUNCTION sql_compare_key(p_sql IN CLOB) RETURN VARCHAR2 IS
    l_v VARCHAR2(32767);
  BEGIN
    IF p_sql IS NULL THEN
      RETURN NULL;
    END IF;
    l_v := DBMS_LOB.SUBSTR(p_sql, 32767, 1);
    l_v := REGEXP_REPLACE(l_v, '(^|' || CHR(10) || ')[[:space:]]*--[^' || CHR(10) || ']*', ' ');
    l_v := LOWER(TRIM(REGEXP_REPLACE(l_v, '[[:space:]]+', ' ')));
    RETURN l_v;
  EXCEPTION
    WHEN OTHERS THEN
      RETURN LOWER(TRIM(DBMS_LOB.SUBSTR(p_sql, 32767, 1)));
  END sql_compare_key;

  FUNCTION sql_needs_sql_only_retry(p_input_sql IN CLOB, p_candidate_sql IN CLOB) RETURN BOOLEAN IS
  BEGIN
    IF p_candidate_sql IS NULL OR NVL(DBMS_LOB.GETLENGTH(p_candidate_sql), 0) = 0 THEN
      RETURN TRUE;
    END IF;
    RETURN sql_compare_key(p_input_sql) = sql_compare_key(p_candidate_sql);
  END sql_needs_sql_only_retry;

  FUNCTION build_progress_array_json(p_run_id IN VARCHAR2) RETURN CLOB IS
    l_out   CLOB;
    l_first BOOLEAN := TRUE;
  BEGIN
    DBMS_LOB.CREATETEMPORARY(l_out, TRUE);
    clob_app(l_out, '[');

    FOR r IN (
      SELECT seq, code, label, status, detail, started_at, completed_at, elapsed_ms
      FROM   asta_run_progress
      WHERE  run_id = p_run_id
      ORDER  BY seq
    ) LOOP
      IF NOT l_first THEN
        clob_app(l_out, ',');
      END IF;
      l_first := FALSE;
      clob_app(l_out, '{"seq":' || json_num(r.seq));
      clob_app(l_out, ',"code":' || json_str(r.code));
      clob_app(l_out, ',"label":' || json_str(r.label));
      clob_app(l_out, ',"status":' || json_str(r.status));
      clob_app(l_out, ',"detail":' || json_str(r.detail));
      clob_app(l_out, ',"started_at":' || json_ts(r.started_at));
      clob_app(l_out, ',"completed_at":' || json_ts(r.completed_at));
      clob_app(l_out, ',"elapsed_ms":' || json_num(r.elapsed_ms) || '}');
    END LOOP;

    clob_app(l_out, ']');
    RETURN l_out;
  EXCEPTION
    WHEN OTHERS THEN
      RETURN TO_CLOB('[]');
  END build_progress_array_json;

  FUNCTION build_llm_calls_json(p_run_id IN VARCHAR2) RETURN CLOB IS
    l_out   CLOB;
    l_first BOOLEAN := TRUE;
  BEGIN
    DBMS_LOB.CREATETEMPORARY(l_out, TRUE);
    clob_app(l_out, '[');

    FOR r IN (
      SELECT call_id,
             stage,
             attempt_no,
             profile_name,
             call_status,
             prompt_chars,
             response_chars,
             error_code,
             started_at,
             completed_at
      FROM   asta_llm_call_log
      WHERE  run_id = p_run_id
      ORDER  BY call_id
    ) LOOP
      IF NOT l_first THEN
        clob_app(l_out, ',');
      END IF;
      l_first := FALSE;
      clob_app(l_out, '{"call_id":' || json_num(r.call_id));
      clob_app(l_out, ',"stage":' || json_str(r.stage));
      clob_app(l_out, ',"attempt_no":' || json_num(r.attempt_no));
      clob_app(l_out, ',"profile_name":' || json_str(r.profile_name));
      clob_app(l_out, ',"call_status":' || json_str(r.call_status));
      clob_app(l_out, ',"prompt_chars":' || json_num(r.prompt_chars));
      clob_app(l_out, ',"response_chars":' || json_num(r.response_chars));
      clob_app(l_out, ',"error_code":' || json_num(r.error_code));
      clob_app(l_out, ',"started_at":' || json_ts(r.started_at));
      clob_app(l_out, ',"completed_at":' || json_ts(r.completed_at));
      clob_app(l_out, ',"elapsed_ms":' || json_num(elapsed_ms_between(r.started_at, NVL(r.completed_at, LOCALTIMESTAMP))));
      clob_app(l_out, ',"detail_available":true}');
    END LOOP;

    clob_app(l_out, ']');
    RETURN l_out;
  EXCEPTION
    WHEN OTHERS THEN
      RETURN TO_CLOB('[]');
  END build_llm_calls_json;

  FUNCTION run_pipeline(p_body_json IN CLOB, p_forced_run_id IN VARCHAR2) RETURN CLOB IS
    l_run_id              VARCHAR2(64);
    l_sql_vc              VARCHAR2(32767);
    l_sql                 CLOB;
    l_tuned_sql           CLOB;
    l_validation_candidate_sql CLOB;
    l_history_candidate_sql CLOB;
    l_history_run_id      VARCHAR2(64);
    l_llm_profile         VARCHAR2(128);
    l_source_db_id        VARCHAR2(64);
    l_source_sql_id       VARCHAR2(13);
    l_source_schema       VARCHAR2(128);
    l_source_db_link      VARCHAR2(128);
    l_source_connection_json CLOB;
    l_source_error        VARCHAR2(4000);
    l_use_llm_raw         VARCHAR2(30);
    l_use_llm             VARCHAR2(1);
    l_run_advisor_raw     VARCHAR2(30);
    l_run_advisor         VARCHAR2(1) := 'N';
    l_execute_source_sql_raw VARCHAR2(30);
    l_execute_source_sql  VARCHAR2(1) := 'N';
    l_before_evidence_mode VARCHAR2(30) := 'MINIMAL';
    l_before_repeat_policy VARCHAR2(30) := 'ONCE';
    l_before_result_mode  VARCHAR2(30) := 'FULL_RESULT';
    l_candidate_result_mode VARCHAR2(30) := 'ESTIMATED_PLAN';
    l_fetch_rows          NUMBER := 100;
    l_vector_top_k        NUMBER := 3;
    l_sqltune_time_limit  NUMBER := 1800;
    l_context_json        CLOB;
    l_workload_type      VARCHAR2(10) := 'OLTP';
    l_prompt_mode_explicit VARCHAR2(1) := 'N';
    l_source_json         CLOB;
    l_baseline_final_json CLOB;
    l_after_json          CLOB;
    l_before_after_json   CLOB;
    l_comparison_json     CLOB;
    l_vector_json         CLOB;
    l_llm_json            CLOB;
    l_generation_json     CLOB;
    l_rejected_candidate  CLOB;
    l_repaired_candidate  CLOB;
    l_second_repaired_candidate CLOB;
    l_candidate_failed    VARCHAR2(1) := 'N';
    l_candidate_screen_rejected VARCHAR2(1) := 'N';
    l_candidate_screen_reason VARCHAR2(1000);
    l_candidate_timeout   PLS_INTEGER;
    l_candidate_full_timeout PLS_INTEGER;
    l_candidate_watchdog  VARCHAR2(128);
    l_final_review_json   CLOB;
    l_vector_save_json    CLOB;
    l_vector_metadata_json CLOB;
    l_report_markdown     CLOB;
    l_progress_json       CLOB;
    l_pipeline_elapsed_ms NUMBER;
    l_run_started_at      TIMESTAMP;
    l_response_json       CLOB;
    l_error_json          CLOB;
    l_error_message       VARCHAR2(4000);
    l_failure_code        VARCHAR2(128);
    l_persist_error       VARCHAR2(4000);
    l_status              VARCHAR2(30) := 'COMPLETED';
  BEGIN
    l_run_id := COALESCE(
      p_forced_run_id,
      JSON_VALUE(p_body_json, '$.run_id' RETURNING VARCHAR2(64) NULL ON ERROR),
      JSON_VALUE(p_body_json, '$.client_run_id' RETURNING VARCHAR2(64) NULL ON ERROR),
      'OADT2-ASTA-' || LOWER(RAWTOHEX(SYS_GUID()))
    );
    l_run_id := normalize_run_id(l_run_id);

    SELECT JSON_VALUE(
             p_body_json,
             '$.validation_candidate_sql' RETURNING CLOB NULL ON ERROR
           )
    INTO l_validation_candidate_sql
    FROM dual;
    IF l_validation_candidate_sql IS NOT NULL THEN
      asta_sql_guard_pkg.assert_safe_select(l_validation_candidate_sql);
    END IF;

    record_progress(l_run_id, 1, 'REQUEST_RECEIVED', 'OADT2 request received', 'DONE');
    record_progress(l_run_id, 2, 'ORDS_DISPATCH', 'ADB ORDS analyze call', 'DONE');

    SELECT COALESCE(
             JSON_VALUE(p_body_json, '$.sql' RETURNING VARCHAR2(32767) NULL ON ERROR),
             JSON_VALUE(p_body_json, '$.sql_text' RETURNING VARCHAR2(32767) NULL ON ERROR)
           ),
           COALESCE(
             JSON_VALUE(p_body_json, '$.llm_profile' RETURNING VARCHAR2(128) NULL ON ERROR),
             JSON_VALUE(p_body_json, '$.ai_profile' RETURNING VARCHAR2(128) NULL ON ERROR),
             C_DEFAULT_LLM_PROFILE
           ),
           COALESCE(
             JSON_VALUE(p_body_json, '$.source_db_id' RETURNING VARCHAR2(64) NULL ON ERROR),
             C_DEFAULT_SOURCE_DB_ID
           ),
           COALESCE(
             JSON_VALUE(p_body_json, '$.use_llm' RETURNING VARCHAR2(30) NULL ON ERROR),
             'true'
           ),
           COALESCE(
             JSON_VALUE(p_body_json, '$.fetch_rows' RETURNING NUMBER NULL ON ERROR),
             100
           ),
           COALESCE(
             JSON_VALUE(p_body_json, '$.vector_top_k' RETURNING NUMBER NULL ON ERROR),
             3
           ),
           COALESCE(
             JSON_VALUE(p_body_json, '$.sqltune_time_limit' RETURNING NUMBER NULL ON ERROR),
             1800
           ),
           COALESCE(
             JSON_VALUE(p_body_json, '$.run_advisor' RETURNING VARCHAR2(30) NULL ON ERROR),
             JSON_VALUE(p_body_json, '$.use_sqltune' RETURNING VARCHAR2(30) NULL ON ERROR),
             'false'
           ),
           COALESCE(
             JSON_VALUE(p_body_json, '$.before_evidence_mode' RETURNING VARCHAR2(30) NULL ON ERROR),
             'MINIMAL'
           ),
           COALESCE(
             JSON_VALUE(p_body_json, '$.execute_source_sql' RETURNING VARCHAR2(30) NULL ON ERROR),
             'false'
           ),
           JSON_QUERY(p_body_json, '$.tuning_context' RETURNING CLOB NULL ON ERROR)
    INTO   l_sql_vc,
           l_llm_profile,
           l_source_db_id,
           l_use_llm_raw,
           l_fetch_rows,
           l_vector_top_k,
           l_sqltune_time_limit,
           l_run_advisor_raw,
           l_before_evidence_mode,
           l_execute_source_sql_raw,
           l_context_json
    FROM   dual;

    l_sql := TO_CLOB(l_sql_vc);
    l_source_sql_id := LOWER(TRIM(
      JSON_VALUE(p_body_json, '$.source_sql_id' RETURNING VARCHAR2(13) NULL ON ERROR)
    ));
    l_source_db_id := normalize_source_db_id(l_source_db_id);
    l_fetch_rows := normalized_fetch_rows(l_fetch_rows);
    l_vector_top_k := normalized_vector_top_k(l_vector_top_k);
    l_sqltune_time_limit := normalized_sqltune_time_limit(l_sqltune_time_limit);
    l_run_advisor := normalized_run_advisor(l_run_advisor_raw);
    l_execute_source_sql := CASE
      WHEN LOWER(TRIM(l_execute_source_sql_raw)) IN ('true', '1', 'y', 'yes') THEN 'Y'
      ELSE 'N'
    END;
    l_before_evidence_mode := normalized_before_evidence_mode(l_before_evidence_mode);
    l_before_repeat_policy := CASE WHEN l_before_evidence_mode = 'THOROUGH' THEN 'AUTO' ELSE 'ONCE' END;
    l_before_result_mode := CASE
      WHEN l_execute_source_sql = 'N' THEN 'ESTIMATED_PLAN'
      WHEN l_before_evidence_mode = 'FAST_PLAN' THEN 'BOUNDED'
      ELSE 'FULL_RESULT'
    END;
    l_candidate_result_mode := CASE
      WHEN l_execute_source_sql = 'N' THEN 'ESTIMATED_PLAN'
      ELSE 'PLAN_ONLY'
    END;
    IF l_execute_source_sql = 'N' THEN
      l_run_advisor := 'N';
    END IF;
    l_workload_type := normalize_workload_type(
      JSON_VALUE(p_body_json, '$.tuning_context.workload_type' RETURNING VARCHAR2(10) NULL ON ERROR)
    );
    IF JSON_VALUE(l_context_json, '$.prompt_mode' RETURNING VARCHAR2(1) NULL ON ERROR) IS NOT NULL THEN
      l_prompt_mode_explicit := 'Y';
    END IF;
    l_use_llm := CASE
      WHEN LOWER(TRIM(l_use_llm_raw)) IN ('false', '0', 'n', 'no') THEN 'N'
      ELSE 'Y'
    END;

    UPDATE asta_runs
    SET    status = 'RUNNING',
           input_sql = l_sql,
           llm_profile = l_llm_profile,
           source_db_id = l_source_db_id,
           source_schema = l_source_schema,
           source_db_link = l_source_db_link,
           started_at = SYSTIMESTAMP,
           completed_at = NULL,
           error_code = NULL,
           error_message = NULL
    WHERE  run_id = l_run_id
    AND    status = 'RUNNING';
    IF SQL%ROWCOUNT = 0 THEN
      RAISE_APPLICATION_ERROR(-20006, 'ASTA_PKG: run was not claimed for execution');
    END IF;
    COMMIT;

    record_progress(l_run_id, 3, 'SQL_GUARD', 'ADB SQL guard', 'RUNNING');
    asta_sql_guard_pkg.assert_safe_select(l_sql);
    record_progress(l_run_id, 3, 'SQL_GUARD', 'ADB SQL guard', 'DONE');

    record_progress(
      l_run_id, 4, 'BEFORE_EVIDENCE', 'Source evidence via DB Link', 'RUNNING',
      CASE WHEN l_execute_source_sql = 'N'
        THEN 'ESTIMATED_PLAN: Source SQL 미실행, 예상 Plan과 객체 정보 수집'
        ELSE 'MINIMAL: Source SQL 실제 실행 evidence 수집'
      END
    );
    l_source_connection_json := asta_source_bridge_pkg.get_connection_json(l_source_db_id);
    IF JSON_VALUE(l_source_connection_json, '$.status' RETURNING VARCHAR2(30) NULL ON ERROR) = 'FAILED' THEN
      record_progress(
        l_run_id,
        4,
        'BEFORE_EVIDENCE',
        'Source evidence via DB Link',
        'FAILED',
        SUBSTR(JSON_VALUE(l_source_connection_json, '$.message' RETURNING VARCHAR2(1000) NULL ON ERROR), 1, 1000)
      );
      RAISE_APPLICATION_ERROR(
        -20002,
        'ASTA_PKG: Source connection lookup failed: ' ||
        SUBSTR(
          JSON_VALUE(l_source_connection_json, '$.message' RETURNING VARCHAR2(1000) NULL ON ERROR),
          1,
          1000
        )
      );
    END IF;

    l_source_schema := JSON_VALUE(l_source_connection_json, '$.source_schema' RETURNING VARCHAR2(128) NULL ON ERROR);
    l_source_db_link := JSON_VALUE(l_source_connection_json, '$.db_link_name' RETURNING VARCHAR2(128) NULL ON ERROR);
    IF l_source_db_link IS NULL THEN
      record_progress(l_run_id, 4, 'BEFORE_EVIDENCE', 'Source evidence via DB Link', 'FAILED', 'Source connection lookup did not return db_link_name');
      RAISE_APPLICATION_ERROR(-20002, 'ASTA_PKG: Source connection lookup did not return db_link_name');
    END IF;

    UPDATE asta_runs
    SET    source_schema = l_source_schema,
           source_db_link = l_source_db_link
    WHERE  run_id = l_run_id;

    l_source_json := asta_source_bridge_pkg.run_source_evidence(
      p_source_db_id     => l_source_db_id,
      p_sql              => l_sql,
      p_run_id           => l_run_id,
      p_fetch_rows       => l_fetch_rows,
      p_repeat_policy    => l_before_repeat_policy,
      p_run_advisor      => l_run_advisor,
      p_sqltune_time_sec => l_sqltune_time_limit,
      p_source_sql_id    => l_source_sql_id,
      p_result_evidence_mode => l_before_result_mode
    );
    l_source_error := source_response_error_message(l_source_json);
    IF l_source_error IS NOT NULL THEN
      record_progress(l_run_id, 4, 'BEFORE_EVIDENCE', 'Source evidence via DB Link', 'FAILED', SUBSTR(l_source_error, 1, 1000));
      RAISE_APPLICATION_ERROR(-20002, 'ASTA_PKG: Source evidence failed: ' || SUBSTR(l_source_error, 1, 1000));
    END IF;
    record_progress(
      l_run_id, 4, 'BEFORE_EVIDENCE', 'Source evidence via DB Link', 'DONE',
      CASE WHEN l_execute_source_sql = 'N'
        THEN 'ESTIMATED_PLAN 완료: 실제 SQL·성능·결과 동등성 미검증'
        ELSE 'Source runtime evidence 수집 완료'
      END
    );
    record_progress(
      l_run_id,
      5,
      'SQL_TUNING_ADVISOR',
      'SQL Tuning Advisor',
      advisor_progress_status(l_source_json),
      advisor_progress_detail(l_source_json, l_run_advisor)
    );

    record_progress(l_run_id, 6, 'LLM_REWRITE', 'Evidence-aware structural rewrite', 'RUNNING',
      'Verified history pattern lookup and LLM structural rewrite');
    -- Historical-reference retrieval is part of LLM rewrite, not a separate
    -- user-visible progress stage. Only compact safe metadata reaches the prompt.
    l_vector_json := asta_vector_pkg.search_similar_cases(l_sql, l_vector_top_k);
    IF l_validation_candidate_sql IS NULL AND l_use_llm = 'Y' THEN
      l_history_candidate_sql := verified_history_candidate(
        p_sql            => l_sql,
        p_current_run_id => l_run_id,
        p_source_db_id   => l_source_db_id,
        p_workload_type  => l_workload_type,
        p_history_run_id => l_history_run_id
      );
    END IF;
    IF l_validation_candidate_sql IS NOT NULL THEN
      l_llm_json := llm_original_fallback_json(
        l_validation_candidate_sql, NULL, NULL, NULL,
        'VALIDATION_CANDIDATE', 'VALIDATION_CANDIDATE'
      );
    ELSIF l_history_candidate_sql IS NOT NULL THEN
      l_llm_json := llm_original_fallback_json(
        l_history_candidate_sql,
        NULL,
        NULL,
        NULL,
        'VERIFIED_HISTORY_REUSE',
        'VERIFIED_HISTORY_REUSE'
      );
    ELSE
      l_llm_json := asta_llm_pkg.generate_sql_only_tuning(
        p_sql                  => l_sql,
        p_llm_profile          => l_llm_profile,
        p_workload_type        => l_workload_type,
        p_source_evidence_json => l_source_json,
        p_vector_json          => l_vector_json,
        p_tuning_context_json  => l_context_json,
        p_use_llm              => l_use_llm,
        p_run_id               => l_run_id
      );
    END IF;
    record_progress(
      l_run_id, 6, 'LLM_REWRITE', 'Evidence-aware structural rewrite',
      progress_status_from_json(l_llm_json),
      CASE WHEN l_history_run_id IS NOT NULL
        THEN 'VERIFIED_HISTORY_REUSE: ' || l_history_run_id
        ELSE NULL
      END
    );

    BEGIN
      SELECT JSON_VALUE(l_llm_json, '$.candidate_sql' RETURNING CLOB NULL ON ERROR)
      INTO   l_tuned_sql
      FROM   dual;
    EXCEPTION
      WHEN OTHERS THEN
        l_tuned_sql := NULL;
    END;

    -- Make the completed LLM candidate available to the authenticated progress
    -- view before the slower Source validation/comparison stages finish.
    UPDATE asta_runs
    SET    tuned_sql = l_tuned_sql
    WHERE  run_id = l_run_id;
    COMMIT;

    IF l_tuned_sql IS NOT NULL THEN
      record_progress(l_run_id, 7, 'AFTER_EVIDENCE', 'Tuned SQL evidence', 'RUNNING');
      l_candidate_timeout := candidate_timeout_seconds(l_source_json, 1, 30);
      arm_candidate_watchdog(l_run_id, l_candidate_timeout, l_candidate_watchdog);
      record_progress(l_run_id, 7, 'AFTER_EVIDENCE', 'Tuned SQL evidence', 'RUNNING',
        'PLAN_ONLY candidate screen timeout: ' || TO_CHAR(l_candidate_timeout) || ' seconds');
      BEGIN
        asta_sql_guard_pkg.assert_candidate_compatible(l_tuned_sql);
        l_after_json := asta_source_bridge_pkg.run_source_evidence(
          p_source_db_id     => l_source_db_id,
          p_sql              => l_tuned_sql,
          p_run_id           => l_run_id || '-TUNED-SCREEN',
          p_fetch_rows       => l_fetch_rows,
          p_repeat_policy    => 'ONCE',
          p_run_advisor      => 'N',
          p_sqltune_time_sec => l_sqltune_time_limit,
          p_source_sql_id    => l_source_sql_id,
          p_result_evidence_mode => l_candidate_result_mode
        );
      EXCEPTION
        WHEN OTHERS THEN
          l_after_json := error_json(
            'CANDIDATE_PREFLIGHT',
            SUBSTR(SQLERRM, 1, 2000)
          );
      END;
      disarm_candidate_watchdog(l_candidate_watchdog);

      l_source_error := source_response_error_message(l_after_json);
      IF l_source_error IS NOT NULL THEN
        l_generation_json := l_llm_json;
        l_rejected_candidate := l_tuned_sql;
        l_repaired_candidate := asta_llm_pkg.repair_sql_candidate(
          p_original_sql       => l_sql,
          p_rejected_candidate => l_rejected_candidate,
          p_error_message      => l_source_error,
          p_llm_profile        => l_llm_profile,
          p_run_id             => l_run_id,
          p_source_evidence_json => l_source_json
        );
        IF l_repaired_candidate IS NOT NULL THEN
          arm_candidate_watchdog(l_run_id, l_candidate_timeout, l_candidate_watchdog);
          l_after_json := asta_source_bridge_pkg.run_source_evidence(
            p_source_db_id     => l_source_db_id,
            p_sql              => l_repaired_candidate,
            p_run_id           => l_run_id || '-REPAIRED-SCREEN',
            p_fetch_rows       => l_fetch_rows,
            p_repeat_policy    => 'ONCE',
            p_run_advisor      => 'N',
            p_sqltune_time_sec => l_sqltune_time_limit,
            p_source_sql_id    => l_source_sql_id,
            p_result_evidence_mode => l_candidate_result_mode
          );
          disarm_candidate_watchdog(l_candidate_watchdog);
          l_source_error := source_response_error_message(l_after_json);
          IF l_source_error IS NULL THEN
            l_tuned_sql := l_repaired_candidate;
            l_llm_json := llm_original_fallback_json(
              l_repaired_candidate, NULL, l_rejected_candidate,
              l_generation_json, 'SUCCESS'
            );
          END IF;
        END IF;

        -- If the first LLM repair still raises an ORA error on Source DB,
        -- send that exact failed repair and the new ORA message through one
        -- more complete rewrite round before retaining the original SQL.
        IF l_repaired_candidate IS NOT NULL AND l_source_error IS NOT NULL THEN
          l_second_repaired_candidate := asta_llm_pkg.repair_sql_candidate(
            p_original_sql       => l_sql,
            p_rejected_candidate => l_repaired_candidate,
            p_error_message      => l_source_error,
            p_llm_profile        => l_llm_profile,
            p_run_id             => l_run_id,
            p_source_evidence_json => l_source_json
          );
          IF l_second_repaired_candidate IS NOT NULL THEN
            arm_candidate_watchdog(l_run_id, l_candidate_timeout, l_candidate_watchdog);
            l_after_json := asta_source_bridge_pkg.run_source_evidence(
              p_source_db_id     => l_source_db_id,
              p_sql              => l_second_repaired_candidate,
              p_run_id           => l_run_id || '-REPAIRED2-SCREEN',
              p_fetch_rows       => l_fetch_rows,
              p_repeat_policy    => 'ONCE',
              p_run_advisor      => 'N',
              p_sqltune_time_sec => l_sqltune_time_limit,
              p_source_sql_id    => l_source_sql_id,
              p_result_evidence_mode => l_candidate_result_mode
            );
            disarm_candidate_watchdog(l_candidate_watchdog);
            l_source_error := source_response_error_message(l_after_json);
            IF l_source_error IS NULL THEN
              l_tuned_sql := l_second_repaired_candidate;
              l_repaired_candidate := l_second_repaired_candidate;
              l_llm_json := llm_original_fallback_json(
                l_second_repaired_candidate, NULL, l_rejected_candidate,
                l_generation_json, 'SUCCESS_ROUND_2'
              );
            ELSE
              l_repaired_candidate := l_second_repaired_candidate;
            END IF;
          END IF;
        END IF;
      END IF;

      IF l_source_error IS NULL THEN
        IF l_execute_source_sql = 'N' THEN
          l_candidate_screen_reason := 'ESTIMATED_PLAN_ONLY_RUNTIME_NOT_EXECUTED';
          l_candidate_screen_rejected := 'Y';
        ELSE
          l_candidate_screen_reason := candidate_plan_screen_reason(
            l_source_json, l_after_json, l_workload_type
          );
          IF l_candidate_screen_reason IS NOT NULL THEN
            l_candidate_screen_rejected := 'Y';
          ELSE
          l_candidate_full_timeout := candidate_timeout_seconds(l_source_json, 6, 90);
          arm_candidate_watchdog(l_run_id, l_candidate_full_timeout, l_candidate_watchdog);
          record_progress(
            l_run_id, 7, 'AFTER_EVIDENCE', 'Tuned SQL evidence', 'RUNNING',
            'PLAN_ONLY passed; baseline AUTO + FULL_RESULT timeout: ' ||
            TO_CHAR(l_candidate_full_timeout) || ' seconds'
          );
          l_baseline_final_json := asta_source_bridge_pkg.run_source_evidence(
            p_source_db_id     => l_source_db_id,
            p_sql              => l_sql,
            p_run_id           => l_run_id || '-BASELINE-FINAL',
            p_fetch_rows       => l_fetch_rows,
            p_repeat_policy    => 'AUTO',
            p_run_advisor      => 'N',
            p_sqltune_time_sec => l_sqltune_time_limit,
            p_source_sql_id    => l_source_sql_id,
            p_result_evidence_mode => 'FULL_RESULT'
          );
          disarm_candidate_watchdog(l_candidate_watchdog);
          l_source_error := source_response_error_message(l_baseline_final_json);
          IF l_source_error IS NULL THEN
            l_source_json := l_baseline_final_json;
          END IF;
          END IF;
        END IF;
        IF l_candidate_screen_rejected <> 'Y' AND l_source_error IS NULL THEN
          l_candidate_full_timeout := candidate_timeout_seconds(l_after_json, 6, 90);
          arm_candidate_watchdog(l_run_id, l_candidate_full_timeout, l_candidate_watchdog);
          record_progress(
            l_run_id, 7, 'AFTER_EVIDENCE', 'Tuned SQL evidence', 'RUNNING',
            'Baseline verified; candidate AUTO + FULL_RESULT timeout: ' ||
            TO_CHAR(l_candidate_full_timeout) || ' seconds'
          );
          l_after_json := asta_source_bridge_pkg.run_source_evidence(
            p_source_db_id     => l_source_db_id,
            p_sql              => l_tuned_sql,
            p_run_id           => l_run_id || '-TUNED-FINAL',
            p_fetch_rows       => l_fetch_rows,
            p_repeat_policy    => 'AUTO',
            p_run_advisor      => 'N',
            p_sqltune_time_sec => l_sqltune_time_limit,
            p_source_sql_id    => l_source_sql_id,
            p_result_evidence_mode => 'FULL_RESULT'
          );
          disarm_candidate_watchdog(l_candidate_watchdog);
          l_source_error := source_response_error_message(l_after_json);
        END IF;
      END IF;

      IF l_source_error IS NOT NULL THEN
        -- The LLM can return syntactically invalid Oracle SQL for complex inputs
        -- even after passing the lightweight SELECT/WITH guard. Do not leave the
        -- run half-failed; retain the original SQL as the executable safe
        -- candidate and preserve the invalid-candidate error in LLM metadata.
        -- Preserve the failed candidate verdict without re-running the original;
        -- the stage-4 evidence remains the safe fallback artifact.
        l_candidate_failed := 'Y';
        l_comparison_json := TO_CLOB(
          '{"status":"FAILED","code":"BEFORE_AFTER_COMPARISON","verdict":"CANDIDATE_FAILED",' ||
          '"verdict_reason":' || json_str('Candidate execution failed: ' || l_source_error) ||
          ',"equivalence_status":"UNKNOWN","retain_original_sql":true' ||
          ',"workload_type":' || json_str(l_workload_type) ||
          ',"primary_metric":' || json_str(CASE WHEN l_workload_type = 'BATCH' THEN 'ELAPSED_TIME' ELSE 'BUFFER_READS' END) ||
          ',"optimization_goal":' || json_str(CASE WHEN l_workload_type = 'BATCH' THEN 'MINIMIZE_ELAPSED_TIME' ELSE 'MINIMIZE_BUFFER_READS' END) ||
          ',"before_buffer_gets":' || COALESCE(JSON_VALUE(l_source_json, '$.last_cr_buffer_gets' RETURNING VARCHAR2(100) NULL ON ERROR), 'null') ||
          ',"after_buffer_gets":null' ||
          ',"before_disk_reads":' || COALESCE(JSON_VALUE(l_source_json, '$.last_disk_reads' RETURNING VARCHAR2(100) NULL ON ERROR), 'null') ||
          ',"after_disk_reads":null' ||
          ',"before_elapsed_time_us":' || COALESCE(JSON_VALUE(l_source_json, '$.last_elapsed_time_us' RETURNING VARCHAR2(100) NULL ON ERROR), 'null') ||
          ',"after_elapsed_time_us":null}'
        );
        l_llm_json := llm_original_fallback_json(
          NULL, 'Invalid LLM candidate after automatic syntax repair: ' || l_source_error,
          COALESCE(l_repaired_candidate, l_rejected_candidate), l_generation_json, 'FAILED'
        );
        l_tuned_sql := l_sql;
      ELSIF l_candidate_screen_rejected = 'Y' AND l_execute_source_sql = 'N' THEN
        l_rejected_candidate := l_tuned_sql;
        l_comparison_json := TO_CLOB(
          '{"status":"COMPLETED","code":"BEFORE_AFTER_COMPARISON","verdict":"ANALYSIS_ONLY",' ||
          '"verdict_reason":' || json_str(l_candidate_screen_reason) ||
          ',"equivalence_status":"NOT_EVALUATED","equivalence_reason":"SOURCE_SQL_NOT_EXECUTED","equivalence_strength":"NONE","retain_original_sql":true' ||
          ',"analysis_mode":"ESTIMATED_PLAN_ONLY","execution_mode":"SOURCE_SQL_NOT_EXECUTED"' ||
          ',"screen_mode":' || json_str(l_candidate_result_mode) || ',"full_result_executed":false' ||
          ',"source_sql_executed":false' ||
          ',"source_runtime_metrics_status":"NOT_MEASURED","before_after_xplan_status":"NOT_AVAILABLE"' ||
          ',"result_equivalence_status":"NOT_EVALUATED","repeat_performance_status":"NOT_MEASURED"' ||
          ',"workload_type":' || json_str(l_workload_type) ||
          ',"primary_metric":' || json_str(CASE WHEN l_workload_type = 'BATCH' THEN 'ELAPSED_TIME' ELSE 'BUFFER_READS' END) ||
          ',"optimization_goal":' || json_str(CASE WHEN l_workload_type = 'BATCH' THEN 'MINIMIZE_ELAPSED_TIME' ELSE 'MINIMIZE_BUFFER_READS' END) ||
          ',"before_buffer_gets":null,"after_buffer_gets":null' ||
          ',"before_disk_reads":null,"after_disk_reads":null' ||
          ',"before_elapsed_time_us":null,"after_elapsed_time_us":null}'
        );
        l_llm_json := llm_original_fallback_json(
          NULL,
          'Candidate generated from estimated plans only; runtime execution and equivalence verification were intentionally skipped',
          l_rejected_candidate,
          l_llm_json,
          'ANALYSIS_ONLY'
        );
        l_tuned_sql := l_sql;
      ELSIF l_candidate_screen_rejected = 'Y' THEN
        l_rejected_candidate := l_tuned_sql;
        l_comparison_json := TO_CLOB(
          '{"status":"COMPLETED","code":"BEFORE_AFTER_COMPARISON","verdict":"NOT_IMPROVED",' ||
          '"verdict_reason":' || json_str(l_candidate_screen_reason) ||
          ',"equivalence_status":"NOT_EVALUATED","retain_original_sql":true' ||
          ',"screen_mode":' || json_str(l_candidate_result_mode) || ',"full_result_executed":false' ||
          ',"source_sql_executed":' || CASE WHEN l_execute_source_sql = 'Y' THEN 'true' ELSE 'false' END ||
          ',"workload_type":' || json_str(l_workload_type) ||
          ',"before_buffer_gets":' || COALESCE(JSON_VALUE(l_source_json, '$.last_cr_buffer_gets' RETURNING VARCHAR2(100) NULL ON ERROR), 'null') ||
          ',"after_buffer_gets":' || COALESCE(JSON_VALUE(l_after_json, '$.last_cr_buffer_gets' RETURNING VARCHAR2(100) NULL ON ERROR), 'null') ||
          ',"before_elapsed_time_us":' || COALESCE(JSON_VALUE(l_source_json, '$.last_elapsed_time_us' RETURNING VARCHAR2(100) NULL ON ERROR), 'null') ||
          ',"after_elapsed_time_us":' || COALESCE(JSON_VALUE(l_after_json, '$.last_elapsed_time_us' RETURNING VARCHAR2(100) NULL ON ERROR), 'null') || '}'
        );
        l_llm_json := llm_original_fallback_json(
          NULL,
          'Candidate rejected by PLAN_ONLY screen: ' || l_candidate_screen_reason,
          l_rejected_candidate,
          l_llm_json,
          'PLAN_SCREEN_REJECTED'
        );
        l_tuned_sql := l_sql;
      END IF;

      IF l_candidate_screen_rejected = 'Y' THEN
        record_progress(
          l_run_id, 7, 'AFTER_EVIDENCE', 'Tuned SQL evidence', 'DONE',
          SUBSTR(l_candidate_screen_reason, 1, 1000)
        );
      ELSIF l_source_error IS NULL THEN
        record_progress(l_run_id, 7, 'AFTER_EVIDENCE', 'Tuned SQL evidence', 'DONE');
      ELSE
        record_progress(l_run_id, 7, 'AFTER_EVIDENCE', 'Tuned SQL evidence', 'FAILED', SUBSTR(l_source_error, 1, 1000));
      END IF;

      record_progress(l_run_id, 8, 'BEFORE_AFTER_COMPARE', 'Deterministic Before/After comparison', 'RUNNING');
      IF l_candidate_failed <> 'Y' AND l_candidate_screen_rejected <> 'Y' THEN
        l_comparison_json := build_comparison_json(l_source_json, l_after_json, l_workload_type);
      END IF;
      DBMS_LOB.CREATETEMPORARY(l_before_after_json, TRUE);
      clob_app(l_before_after_json, '{"candidate_sql":');
      clob_app_json_str(l_before_after_json, l_tuned_sql);
      clob_app(l_before_after_json, ',"before":');
      clob_app_clob(l_before_after_json, NVL(l_source_json, TO_CLOB('null')));
      clob_app(l_before_after_json, ',"after":');
      clob_app_clob(l_before_after_json, NVL(l_after_json, TO_CLOB('null')));
      clob_app(l_before_after_json, ',"comparison":');
      clob_app_clob(l_before_after_json, NVL(l_comparison_json, TO_CLOB('null')));
      clob_app(l_before_after_json, ',"tuning_context":');
      clob_app_clob(l_before_after_json, NVL(l_context_json, TO_CLOB('null')));
      clob_app(l_before_after_json, '}');

      l_final_review_json := TO_CLOB('{"status":"SKIPPED","reason":"DETERMINISTIC_COMPARISON"}');
      record_progress(l_run_id, 8, 'BEFORE_AFTER_COMPARE', 'Deterministic Before/After comparison',
        CASE WHEN l_candidate_failed = 'Y' THEN 'FAILED' ELSE progress_status_from_json(l_comparison_json) END,
        SUBSTR(JSON_VALUE(l_comparison_json, '$.message' RETURNING VARCHAR2(1000) NULL ON ERROR), 1, 1000));
    ELSE
      record_progress(l_run_id, 7, 'AFTER_EVIDENCE', 'Tuned SQL evidence', 'SKIPPED', 'No structural rewrite candidate');
      l_comparison_json := TO_CLOB(
        '{"status":"SKIPPED","code":"BEFORE_AFTER_COMPARISON","verdict":"NO_REWRITE",' ||
        '"verdict_reason":"No structural rewrite candidate","equivalence_status":"NOT_APPLICABLE","retain_original_sql":true' ||
        ',"screen_mode":' || json_str(CASE WHEN l_execute_source_sql = 'N' THEN 'ESTIMATED_PLAN' ELSE 'NONE' END) ||
        ',"source_sql_executed":' || CASE WHEN l_execute_source_sql = 'Y' THEN 'true' ELSE 'false' END ||
        ',"workload_type":' || json_str(l_workload_type) ||
        ',"primary_metric":' || json_str(CASE WHEN l_workload_type = 'BATCH' THEN 'ELAPSED_TIME' ELSE 'BUFFER_READS' END) ||
        ',"optimization_goal":' || json_str(CASE WHEN l_workload_type = 'BATCH' THEN 'MINIMIZE_ELAPSED_TIME' ELSE 'MINIMIZE_BUFFER_READS' END) ||
        ',"before_buffer_gets":' || COALESCE(JSON_VALUE(l_source_json, '$.last_cr_buffer_gets' RETURNING VARCHAR2(100) NULL ON ERROR), 'null') ||
        ',"after_buffer_gets":null' ||
        ',"before_disk_reads":' || COALESCE(JSON_VALUE(l_source_json, '$.last_disk_reads' RETURNING VARCHAR2(100) NULL ON ERROR), 'null') ||
        ',"after_disk_reads":null' ||
        ',"before_elapsed_time_us":' || COALESCE(JSON_VALUE(l_source_json, '$.last_elapsed_time_us' RETURNING VARCHAR2(100) NULL ON ERROR), 'null') ||
        ',"after_elapsed_time_us":null}'
      );
      record_progress(l_run_id, 8, 'BEFORE_AFTER_COMPARE', 'Deterministic Before/After comparison', 'SKIPPED', 'No structural rewrite candidate');
      l_final_review_json := TO_CLOB('{"status":"SKIPPED","reason":"DETERMINISTIC_COMPARISON"}');
    END IF;

    record_progress(l_run_id, 10, 'FINAL_REPORT', 'Final report synthesis', 'RUNNING');
    record_progress(l_run_id, 11, 'VECTOR_SAVE', 'ADB Vector KB save', 'RUNNING');
    l_vector_metadata_json := build_vector_metadata(l_comparison_json, l_source_json, l_after_json, l_llm_json);
    l_vector_save_json := asta_vector_pkg.save_case(
      p_run_id          => l_run_id,
      p_sql             => l_sql,
      p_tuned_sql       => l_tuned_sql,
      -- The Vector row stores a stable report reference, avoiding a report/save
      -- cycle.  The canonical report body remains in ASTA_RUNS.
      p_report_markdown => TO_CLOB('/api/asta/runs/') || TO_CLOB(l_run_id) || TO_CLOB('/report'),
      p_metadata_json   => l_vector_metadata_json
    );
    record_progress(l_run_id, 11, 'VECTOR_SAVE', 'ADB Vector KB save', progress_status_from_json(l_vector_save_json));

    -- Build only after stage 11 has an actual terminal artifact.  A FAILED
    -- save is data, not an orchestration exception, and is visible in report.
    -- Persist the adopted candidate before report assembly so the report/API
    -- can recover it when a legacy/fallback LLM artifact lacks candidate_sql.
    UPDATE asta_runs SET tuned_sql = l_tuned_sql WHERE run_id = l_run_id;
    l_report_markdown := asta_report_pkg.build_report(
      p_run_id               => l_run_id,
      p_input_sql            => l_sql,
      p_source_evidence_json => l_source_json,
      p_after_evidence_json  => l_after_json,
      p_comparison_json      => l_comparison_json,
      p_vector_json          => l_vector_json,
      p_vector_save_json     => l_vector_save_json,
      p_llm_json             => l_llm_json,
      p_status               => l_status,
      p_error_json           => NULL,
      p_final_review_json    => l_final_review_json
    );
    record_progress(l_run_id, 10, 'FINAL_REPORT', 'Final report synthesis', 'DONE');
    l_progress_json := build_progress_array_json(l_run_id);

    SELECT started_at
    INTO   l_run_started_at
    FROM   asta_runs
    WHERE  run_id = l_run_id;
    l_pipeline_elapsed_ms := elapsed_ms_between(l_run_started_at, SYSTIMESTAMP);

    -- Rebuild with the terminal stage-10/11 rows.  The first pass above is
    -- what stage 10 measures; this pass only injects those persisted timings.
    l_report_markdown :=
      asta_report_pkg.build_report(
        p_run_id               => l_run_id,
        p_input_sql            => l_sql,
        p_source_evidence_json => l_source_json,
        p_after_evidence_json  => l_after_json,
        p_comparison_json      => l_comparison_json,
        p_vector_json          => l_vector_json,
        p_vector_save_json     => l_vector_save_json,
        p_llm_json             => l_llm_json,
        p_status               => l_status,
        p_error_json           => NULL,
        p_final_review_json    => l_final_review_json,
        p_progress_json        => l_progress_json,
        p_pipeline_elapsed_ms  => l_pipeline_elapsed_ms
      );

    l_response_json := asta_report_pkg.build_response_json(
      p_run_id               => l_run_id,
      p_status               => l_status,
      p_report_markdown      => l_report_markdown,
      p_source_evidence_json => l_source_json,
      p_after_evidence_json  => l_after_json,
      p_comparison_json      => l_comparison_json,
      p_vector_json          => l_vector_json,
      p_vector_save_json     => l_vector_save_json,
      p_llm_json             => l_llm_json,
      p_error_json           => NULL,
      p_progress_json        => l_progress_json,
      p_final_review_json    => l_final_review_json
    );

    UPDATE asta_runs
    SET    status = l_status,
           tuned_sql = l_tuned_sql,
           completed_at = SYSTIMESTAMP,
           detailed_report_md = l_report_markdown,
           response_json = l_response_json
    WHERE  run_id = l_run_id;
    COMMIT;

    RETURN l_response_json;
  EXCEPTION
    WHEN OTHERS THEN
      l_status := 'FAILED';
      l_error_message := SUBSTR(SQLERRM, 1, 4000);
      l_failure_code := classify_error_code(l_error_message, SQLCODE);
      l_error_json := error_json(l_failure_code, l_error_message);
      record_progress(l_run_id, 10, 'FINAL_REPORT', 'Final report synthesis', 'FAILED', SUBSTR(l_error_message, 1, 1000));
      l_progress_json := build_progress_array_json(l_run_id);

      BEGIN
        SELECT started_at
        INTO   l_run_started_at
        FROM   asta_runs
        WHERE  run_id = l_run_id;
        l_pipeline_elapsed_ms := elapsed_ms_between(l_run_started_at, SYSTIMESTAMP);
      EXCEPTION
        WHEN OTHERS THEN
          l_pipeline_elapsed_ms := NULL;
      END;

      l_report_markdown := asta_report_pkg.build_report(
        p_run_id               => l_run_id,
        p_input_sql            => l_sql,
        p_source_evidence_json => l_source_json,
        p_after_evidence_json  => l_after_json,
        p_comparison_json      => l_comparison_json,
        p_vector_json          => l_vector_json,
        p_vector_save_json     => l_vector_save_json,
        p_llm_json             => l_llm_json,
        p_status               => l_status,
        p_error_json           => l_error_json,
        p_final_review_json    => l_final_review_json,
        p_progress_json        => l_progress_json,
        p_pipeline_elapsed_ms  => l_pipeline_elapsed_ms
      );

      l_response_json := asta_report_pkg.build_response_json(
        p_run_id               => l_run_id,
        p_status               => l_status,
        p_report_markdown      => l_report_markdown,
        p_source_evidence_json => l_source_json,
        p_after_evidence_json  => l_after_json,
        p_comparison_json      => l_comparison_json,
        p_vector_json          => l_vector_json,
        p_vector_save_json     => l_vector_save_json,
        p_llm_json             => l_llm_json,
        p_error_json           => l_error_json,
        p_progress_json        => l_progress_json,
        p_final_review_json    => l_final_review_json
      );

      BEGIN
        UPDATE asta_runs
        SET    status = l_status,
               completed_at = SYSTIMESTAMP,
               error_code = l_failure_code,
               error_message = l_error_message,
               detailed_report_md = l_report_markdown,
               response_json = l_response_json
        WHERE  run_id = l_run_id;
        COMMIT;
      EXCEPTION
        WHEN OTHERS THEN
          l_persist_error := SUBSTR(SQLERRM, 1, 2000);
          ROLLBACK;
          -- Never leave a finished Scheduler run stuck in RUNNING merely
          -- because the rich response artifact could not satisfy persistence.
          BEGIN
            UPDATE asta_runs
            SET    status = 'FAILED',
                   completed_at = SYSTIMESTAMP,
                   error_code = 'ASTA_PERSIST',
                   error_message = SUBSTR(
                     NVL(l_error_message, 'ASTA response persistence failed') ||
                     ' | persistence: ' || l_persist_error,
                     1,
                     4000
                   ),
                   detailed_report_md = l_report_markdown,
                   response_json = NULL
            WHERE  run_id = l_run_id;
            COMMIT;
          EXCEPTION
            WHEN OTHERS THEN
              ROLLBACK;
          END;
      END;

      RETURN l_response_json;
  END run_pipeline;

  FUNCTION submit_run(p_body_json IN CLOB) RETURN CLOB IS
    l_run_id VARCHAR2(64);
    l_idempotency_key VARCHAR2(128);
    l_existing_run_id VARCHAR2(64);
    l_existing_status VARCHAR2(30);
    l_existing_request CLOB;
    l_job_name VARCHAR2(128);
    l_sql_vc VARCHAR2(32767);
    l_submit_error VARCHAR2(4000);
    l_row_inserted BOOLEAN := FALSE;
  BEGIN
    l_run_id := normalize_run_id(COALESCE(
      JSON_VALUE(p_body_json, '$.run_id' RETURNING VARCHAR2(64) NULL ON ERROR),
      JSON_VALUE(p_body_json, '$.client_run_id' RETURNING VARCHAR2(64) NULL ON ERROR),
      'OADT2-ASTA-' || LOWER(RAWTOHEX(SYS_GUID()))));
    l_idempotency_key := TRIM(JSON_VALUE(p_body_json, '$.idempotency_key' RETURNING VARCHAR2(128) NULL ON ERROR));
    l_sql_vc := COALESCE(JSON_VALUE(p_body_json, '$.sql' RETURNING VARCHAR2(32767) NULL ON ERROR), JSON_VALUE(p_body_json, '$.sql_text' RETURNING VARCHAR2(32767) NULL ON ERROR));
    IF l_sql_vc IS NULL THEN RAISE_APPLICATION_ERROR(-20002, 'ASTA_PKG: sql is required'); END IF;
    asta_sql_guard_pkg.assert_safe_select(TO_CLOB(l_sql_vc));
    IF l_idempotency_key IS NOT NULL THEN
      BEGIN
        SELECT run_id, status, request_json
        INTO l_existing_run_id, l_existing_status, l_existing_request
        FROM asta_runs
        WHERE idempotency_key = l_idempotency_key;
        IF DBMS_LOB.COMPARE(l_existing_request, p_body_json) <> 0 THEN
          RAISE_APPLICATION_ERROR(-20007, 'IDEMPOTENCY_CONFLICT: key already used with a different request');
        END IF;
        RETURN TO_CLOB('{"run_id":' || json_str(l_existing_run_id) || ',"status":' || json_str(l_existing_status) || ',"idempotent_replay":true,"execution_mode":"ADB_SCHEDULER"}');
      EXCEPTION WHEN NO_DATA_FOUND THEN NULL; END;
    END IF;
    l_job_name := 'ASTA_RUN_' || SUBSTR(UPPER(REPLACE(RAWTOHEX(SYS_GUID()), '-', '')), 1, 26);
    BEGIN
      INSERT INTO asta_runs(run_id,status,input_sql,request_json,idempotency_key,job_name,created_at,submitted_at)
      VALUES(l_run_id,'QUEUED',TO_CLOB(l_sql_vc),p_body_json,l_idempotency_key,l_job_name,SYSTIMESTAMP,SYSTIMESTAMP);
      l_row_inserted := TRUE;
    EXCEPTION
      WHEN DUP_VAL_ON_INDEX THEN
        IF l_idempotency_key IS NULL THEN
          RAISE_APPLICATION_ERROR(-20008, 'RUN_ID_CONFLICT: run_id already exists');
        END IF;
        SELECT run_id, status, request_json
        INTO l_existing_run_id, l_existing_status, l_existing_request
        FROM asta_runs
        WHERE idempotency_key = l_idempotency_key;
        IF DBMS_LOB.COMPARE(l_existing_request, p_body_json) <> 0 THEN
          RAISE_APPLICATION_ERROR(-20007, 'IDEMPOTENCY_CONFLICT: key already used with a different request');
        END IF;
        RETURN TO_CLOB('{"run_id":' || json_str(l_existing_run_id) || ',"status":' || json_str(l_existing_status) || ',"idempotent_replay":true,"execution_mode":"ADB_SCHEDULER"}');
    END;
    COMMIT;
    DBMS_SCHEDULER.CREATE_JOB(job_name => l_job_name, job_type => 'STORED_PROCEDURE', job_action => 'ASTA_PKG.EXECUTE_RUN', number_of_arguments => 1, enabled => FALSE, auto_drop => TRUE);
    DBMS_SCHEDULER.SET_JOB_ARGUMENT_VALUE(job_name => l_job_name, argument_position => 1, argument_value => l_run_id);
    DBMS_SCHEDULER.ENABLE(l_job_name);
    RETURN TO_CLOB('{"run_id":' || json_str(l_run_id) || ',"status":"QUEUED","execution_mode":"ADB_SCHEDULER","job_name":' || json_str(l_job_name) || '}');
  EXCEPTION WHEN OTHERS THEN
    l_submit_error := SUBSTR(SQLERRM,1,4000);
    IF l_row_inserted THEN
      BEGIN
        UPDATE asta_runs
        SET status='FAILED', completed_at=SYSTIMESTAMP, error_code='SUBMIT_RUN', error_message=l_submit_error
        WHERE run_id=l_run_id AND job_name=l_job_name;
        COMMIT;
      EXCEPTION WHEN OTHERS THEN NULL;
      END;
    END IF;
    RETURN TO_CLOB('{"run_id":') || json_str(l_run_id) ||
      TO_CLOB(',"status":"FAILED","error_code":') ||
      json_str(classify_error_code(l_submit_error, SQLCODE)) ||
      TO_CLOB(',"error_message":') || json_str(l_submit_error) ||
      TO_CLOB(',"error":') || error_json(classify_error_code(l_submit_error, SQLCODE), l_submit_error) ||
      TO_CLOB('}');
  END submit_run;

  PROCEDURE execute_run(p_run_id IN VARCHAR2) IS
    l_run_id VARCHAR2(64); l_request_json CLOB; l_response CLOB; l_execute_error VARCHAR2(4000);
  BEGIN
    l_run_id := normalize_run_id(p_run_id);
    SELECT request_json INTO l_request_json FROM asta_runs WHERE run_id=l_run_id AND status IN ('QUEUED', 'RETRY') FOR UPDATE;
    UPDATE asta_runs SET status='RUNNING', started_at=SYSTIMESTAMP WHERE run_id=l_run_id; COMMIT;
    l_response := run_pipeline(l_request_json, l_run_id);
  EXCEPTION WHEN NO_DATA_FOUND THEN NULL; WHEN OTHERS THEN
    l_execute_error := SUBSTR(SQLERRM,1,4000);
    UPDATE asta_runs SET status='FAILED', completed_at=SYSTIMESTAMP, error_code='EXECUTE_RUN', error_message=l_execute_error WHERE run_id=l_run_id; COMMIT;
  END execute_run;

  FUNCTION analyze_sql(p_body_json IN CLOB) RETURN CLOB IS
  BEGIN
    RETURN submit_run(p_body_json);
  END analyze_sql;

  FUNCTION list_profiles RETURN CLOB IS
    l_out   CLOB;
    l_first BOOLEAN := TRUE;
  BEGIN
    DBMS_LOB.CREATETEMPORARY(l_out, TRUE);
    clob_app(l_out, '{"source":"ADB_ORDS","architecture":"ADB_ORDS_PLSQL","contract_version":"asta.v1",');
    clob_app(l_out, migration_boundary_json);
    clob_app(l_out, ',"asta_default":');
    clob_app(l_out, json_str(C_DEFAULT_LLM_PROFILE));
    clob_app(l_out, ',"profiles":[');

    FOR r IN (
      SELECT profile_name
      FROM   user_cloud_ai_profiles
      WHERE  UPPER(profile_name) LIKE 'ASTA%'
      ORDER  BY profile_name
    ) LOOP
      IF NOT l_first THEN
        clob_app(l_out, ',');
      END IF;
      l_first := FALSE;
      clob_app(l_out, '{"name":');
      clob_app(l_out, json_str(r.profile_name));
      clob_app(l_out, ',"profile_name":');
      clob_app(l_out, json_str(r.profile_name));
      clob_app(l_out, ',"display_name":');
      clob_app(l_out, json_str(r.profile_name));
      clob_app(l_out, ',"status":"ENABLED","selectable":true,"default":');
      clob_app(l_out, CASE WHEN r.profile_name = C_DEFAULT_LLM_PROFILE THEN 'true' ELSE 'false' END);
      clob_app(l_out, '}');
    END LOOP;

    clob_app(l_out, ']}');
    RETURN l_out;
  EXCEPTION
    WHEN OTHERS THEN
      RETURN TO_CLOB(
        '{"source":"ADB_ORDS","architecture":"ADB_ORDS_PLSQL","contract_version":"asta.v1",' ||
        migration_boundary_json ||
        ',"profiles":[],"error":{"code":"LIST_PROFILES","message":' ||
        json_str(SUBSTR(SQLERRM, 1, 4000)) || '}}'
      );
  END list_profiles;

  FUNCTION get_run(p_run_id IN VARCHAR2) RETURN CLOB IS
    l_response CLOB;
    l_run_id   VARCHAR2(64);
    l_status   VARCHAR2(30);
    l_error_code VARCHAR2(128);
    l_error_message VARCHAR2(4000);
  BEGIN
    l_run_id := normalize_run_id(p_run_id);

    SELECT status, response_json, error_code, error_message
    INTO   l_status, l_response, l_error_code, l_error_message
    FROM   asta_runs
    WHERE  run_id = l_run_id;

    RETURN NVL(
      l_response,
      TO_CLOB('{"run_id":') || json_str(l_run_id) ||
      TO_CLOB(',"status":') || json_str(l_status) ||
      TO_CLOB(',"error_code":') || json_str(l_error_code) ||
      TO_CLOB(',"error_message":') || json_str(l_error_message) ||
      TO_CLOB(',"error":') || CASE WHEN l_error_code IS NULL AND l_error_message IS NULL THEN TO_CLOB('null') ELSE error_json(l_error_code, l_error_message) END ||
      TO_CLOB(',"source":"ADB_ORDS","architecture":"ADB_ORDS_PLSQL","contract_version":"asta.v1",') ||
      migration_boundary_json || TO_CLOB('}')
    );
  EXCEPTION
    WHEN NO_DATA_FOUND THEN
      RETURN TO_CLOB(
        '{"run_id":' || json_str(NVL(l_run_id, p_run_id)) ||
        ',"status":"NOT_FOUND","source":"ADB_ORDS","architecture":"ADB_ORDS_PLSQL","contract_version":"asta.v1",' ||
        migration_boundary_json ||
        ',"error":{"code":"RUN_NOT_FOUND"}}'
      );
    WHEN OTHERS THEN
      RETURN TO_CLOB(
        '{"run_id":' || json_str(p_run_id) ||
        ',"status":"FAILED","source":"ADB_ORDS","architecture":"ADB_ORDS_PLSQL","contract_version":"asta.v1",' ||
        migration_boundary_json ||
        ',"error":{"code":"RUN_LOOKUP","message":' ||
        json_str(SUBSTR(SQLERRM, 1, 4000)) || '}}'
      );
  END get_run;

  FUNCTION get_input_sql(p_run_id IN VARCHAR2) RETURN CLOB IS
    l_run_id VARCHAR2(64);
    l_status VARCHAR2(30);
    l_sql    CLOB;
    l_out    CLOB;
  BEGIN
    l_run_id := normalize_run_id(p_run_id);
    SELECT status, input_sql INTO l_status, l_sql FROM asta_runs WHERE run_id = l_run_id;
    DBMS_LOB.CREATETEMPORARY(l_out, TRUE);
    clob_app(l_out, '{"run_id":' || json_str(l_run_id));
    clob_app(l_out, ',"status":' || json_str(l_status));
    clob_app(l_out, ',"source":"ADB_ORDS","architecture":"ADB_ORDS_PLSQL","contract_version":"asta.v1",');
    clob_app(l_out, migration_boundary_json);
    clob_app(l_out, ',"input_sql":');
    clob_app_json_str(l_out, l_sql);
    clob_app(l_out, '}');
    RETURN l_out;
  EXCEPTION
    WHEN NO_DATA_FOUND THEN
      RETURN TO_CLOB('{"run_id":') || json_str(NVL(l_run_id, p_run_id)) ||
        TO_CLOB(',"status":"NOT_FOUND","error":{"code":"RUN_NOT_FOUND"}}');
    WHEN OTHERS THEN
      RETURN TO_CLOB('{"run_id":') || json_str(p_run_id) ||
        TO_CLOB(',"status":"FAILED","error":{"code":"INPUT_SQL_LOOKUP","message":') ||
        json_str(SUBSTR(SQLERRM, 1, 4000)) || TO_CLOB('}}');
  END get_input_sql;

  FUNCTION list_history(
    p_search IN VARCHAR2 DEFAULT NULL,
    p_limit IN NUMBER DEFAULT 50,
    p_from_date IN VARCHAR2 DEFAULT NULL,
    p_to_date IN VARCHAR2 DEFAULT NULL,
    p_verdict IN VARCHAR2 DEFAULT NULL
  ) RETURN CLOB IS
    l_out   CLOB;
    l_limit PLS_INTEGER := LEAST(GREATEST(NVL(TRUNC(p_limit), 50), 1), 100);
    l_search VARCHAR2(200) := NULLIF(TRIM(SUBSTR(p_search, 1, 200)), '');
    l_today_kst DATE;
    l_from_date DATE;
    l_to_date DATE;
    l_from_at TIMESTAMP;
    l_to_at TIMESTAMP;
    l_verdict VARCHAR2(30) := UPPER(TRIM(NVL(p_verdict, 'ALL')));
    l_first BOOLEAN := TRUE;
  BEGIN
    l_today_kst := TRUNC(CAST(SYSTIMESTAMP AT TIME ZONE 'Asia/Seoul' AS DATE));
    l_from_date := l_today_kst - 6;
    l_to_date := l_today_kst;
    IF REGEXP_LIKE(TRIM(p_from_date), '^\d{4}-\d{2}-\d{2}$') THEN
      l_from_date := TO_DATE(TRIM(p_from_date), 'YYYY-MM-DD');
    END IF;
    IF REGEXP_LIKE(TRIM(p_to_date), '^\d{4}-\d{2}-\d{2}$') THEN
      l_to_date := TO_DATE(TRIM(p_to_date), 'YYYY-MM-DD');
    END IF;
    IF l_from_date > l_to_date THEN
      RAISE_APPLICATION_ERROR(-20001, 'ASTA history date range is invalid');
    END IF;
    l_from_at := CAST(FROM_TZ(CAST(l_from_date AS TIMESTAMP), 'Asia/Seoul') AT TIME ZONE 'UTC' AS TIMESTAMP);
    l_to_at := CAST(FROM_TZ(CAST(l_to_date + 1 AS TIMESTAMP), 'Asia/Seoul') AT TIME ZONE 'UTC' AS TIMESTAMP);
    IF l_verdict NOT IN ('ALL', 'IMPROVED', 'ANALYSIS_ONLY', 'NOT_IMPROVED', 'CANDIDATE_FAILED', 'NON_EQUIVALENT', 'NO_REWRITE', 'INSUFFICIENT_EVIDENCE') THEN
      l_verdict := 'ALL';
    END IF;
    DBMS_LOB.CREATETEMPORARY(l_out, TRUE);
    clob_app(l_out, '{"status":"COMPLETED","source":"ADB_ORDS","architecture":"ADB_ORDS_PLSQL","contract_version":"asta.v1",');
    clob_app(l_out, migration_boundary_json);
    clob_app(l_out, ',"runs":[');
    FOR r IN (
      SELECT run_id,
             status,
             llm_profile,
             source_db_id,
             created_at,
             started_at,
             completed_at,
             error_code,
             error_message,
             DBMS_LOB.SUBSTR(input_sql, 500, 1) AS sql_preview,
             JSON_VALUE(response_json, '$.comparison.verdict' RETURNING VARCHAR2(64) NULL ON ERROR) AS verdict,
             JSON_VALUE(response_json, '$.comparison.execution_mode' RETURNING VARCHAR2(64) NULL ON ERROR) AS execution_mode,
             CASE WHEN detailed_report_md IS NULL THEN 'false' ELSE 'true' END AS report_ready
      FROM (
        SELECT run_id,
               status,
               llm_profile,
               source_db_id,
               created_at,
               started_at,
               completed_at,
               error_code,
               error_message,
               input_sql,
               response_json,
               detailed_report_md
        FROM asta_runs
        WHERE created_at >= l_from_at
          AND created_at < l_to_at
          AND (l_search IS NULL
               OR INSTR(UPPER(run_id), UPPER(l_search)) > 0
               OR DBMS_LOB.INSTR(UPPER(input_sql), UPPER(l_search), 1, 1) > 0)
          AND (l_verdict = 'ALL'
               OR UPPER(NVL(JSON_VALUE(response_json, '$.comparison.verdict' RETURNING VARCHAR2(64) NULL ON ERROR), status)) = l_verdict)
        ORDER BY created_at DESC NULLS LAST, run_id DESC
      )
      WHERE ROWNUM <= l_limit
    ) LOOP
      IF NOT l_first THEN clob_app(l_out, ','); END IF;
      l_first := FALSE;
      clob_app(l_out, '{"run_id":' || json_str(r.run_id));
      clob_app(l_out, ',"status":' || json_str(r.status));
      clob_app(l_out, ',"llm_profile":' || json_str(r.llm_profile));
      clob_app(l_out, ',"source_db_id":' || json_str(r.source_db_id));
      clob_app(l_out, ',"created_at":' || json_ts(r.created_at));
      clob_app(l_out, ',"started_at":' || json_ts(r.started_at));
      clob_app(l_out, ',"completed_at":' || json_ts(r.completed_at));
      clob_app(l_out, ',"error_code":' || json_str(r.error_code));
      clob_app(l_out, ',"error_message":' || json_str(r.error_message));
      clob_app(l_out, ',"sql_preview":' || json_str(REGEXP_REPLACE(r.sql_preview, '[[:space:]]+', ' ')));
      clob_app(l_out, ',"verdict":' || json_str(r.verdict));
      clob_app(l_out, ',"execution_mode":' || json_str(r.execution_mode));
      clob_app(l_out, ',"report_ready":' || r.report_ready || '}');
    END LOOP;
    clob_app(l_out, '],"limit":' || json_num(l_limit) || ',"search":' || json_str(l_search) ||
      ',"date_from":' || json_str(TO_CHAR(l_from_date, 'YYYY-MM-DD')) ||
      ',"date_to":' || json_str(TO_CHAR(l_to_date, 'YYYY-MM-DD')) ||
      ',"verdict":' || json_str(l_verdict) || '}');
    RETURN l_out;
  EXCEPTION
    WHEN OTHERS THEN
      RETURN TO_CLOB('{"status":"FAILED","source":"ADB_ORDS","architecture":"ADB_ORDS_PLSQL","contract_version":"asta.v1",') ||
        migration_boundary_json || TO_CLOB(',"runs":[],"error":{"code":"HISTORY_LOOKUP","message":') ||
        json_str(SUBSTR(SQLERRM, 1, 4000)) || TO_CLOB('}}');
  END list_history;

  FUNCTION get_progress(p_run_id IN VARCHAR2) RETURN CLOB IS
    l_status       VARCHAR2(30);
    l_started_at   TIMESTAMP;
    l_completed_at TIMESTAMP;
    l_error_code    VARCHAR2(128);
    l_error_message VARCHAR2(4000);
    l_tuned_sql     CLOB;
    l_out          CLOB;
    l_run_id       VARCHAR2(64);
  BEGIN
    l_run_id := normalize_run_id(p_run_id);

    SELECT status, started_at, completed_at, error_code, error_message, tuned_sql
    INTO   l_status, l_started_at, l_completed_at, l_error_code, l_error_message, l_tuned_sql
    FROM   asta_runs
    WHERE  run_id = l_run_id;

    DBMS_LOB.CREATETEMPORARY(l_out, TRUE);
    clob_app(l_out, '{"run_id":');
    clob_app(l_out, json_str(l_run_id));
    clob_app(l_out, ',"status":');
    clob_app(l_out, json_str(l_status));
    clob_app(l_out, ',"source":"ADB_ORDS","architecture":"ADB_ORDS_PLSQL","contract_version":"asta.v1",');
    clob_app(l_out, migration_boundary_json);
    clob_app(l_out, ',"progress":');
    clob_app_clob(l_out, build_progress_array_json(l_run_id));
    clob_app(l_out, ',"llm_calls":');
    clob_app_clob(l_out, build_llm_calls_json(l_run_id));
    clob_app(l_out, ',"candidate_sql":');
    clob_app_json_str(l_out, l_tuned_sql);
    clob_app(l_out, ',"started_at":');
    clob_app(l_out, json_ts(l_started_at));
    clob_app(l_out, ',"completed_at":');
    clob_app(l_out, json_ts(l_completed_at));
    clob_app(l_out, ',"error_code":' || json_str(l_error_code));
    clob_app(l_out, ',"error_message":' || json_str(l_error_message));
    clob_app(l_out, ',"error":');
    IF l_error_code IS NULL AND l_error_message IS NULL THEN
      clob_app(l_out, 'null');
    ELSE
      clob_app_clob(l_out, error_json(l_error_code, l_error_message));
    END IF;
    clob_app(l_out, '}');
    RETURN l_out;
  EXCEPTION
    WHEN NO_DATA_FOUND THEN
      RETURN TO_CLOB(
        '{"run_id":' || json_str(NVL(l_run_id, p_run_id)) ||
        ',"status":"NOT_FOUND","source":"ADB_ORDS","architecture":"ADB_ORDS_PLSQL","contract_version":"asta.v1","progress":[],' ||
        migration_boundary_json ||
        ',"error":{"code":"RUN_NOT_FOUND"}}'
      );
    WHEN OTHERS THEN
      RETURN TO_CLOB(
        '{"run_id":' || json_str(p_run_id) ||
        ',"status":"FAILED","source":"ADB_ORDS","architecture":"ADB_ORDS_PLSQL","contract_version":"asta.v1","progress":[],' ||
        migration_boundary_json ||
        ',"error":{"code":"PROGRESS_LOOKUP","message":' ||
        json_str(SUBSTR(SQLERRM, 1, 4000)) || '}}'
      );
  END get_progress;

  FUNCTION get_llm_call(p_run_id IN VARCHAR2, p_call_id IN NUMBER) RETURN CLOB IS
    l_run_id        VARCHAR2(64);
    l_stage         VARCHAR2(30);
    l_attempt_no    NUMBER;
    l_profile_name  VARCHAR2(128);
    l_call_status   VARCHAR2(30);
    l_prompt        CLOB;
    l_response      CLOB;
    l_prompt_chars  NUMBER;
    l_response_chars NUMBER;
    l_error_code    NUMBER;
    l_error_message VARCHAR2(4000);
    l_started_at    TIMESTAMP;
    l_completed_at  TIMESTAMP;
    l_out           CLOB;
  BEGIN
    l_run_id := normalize_run_id(p_run_id);
    IF p_call_id IS NULL OR p_call_id < 1 OR p_call_id <> TRUNC(p_call_id) THEN
      RETURN TO_CLOB(
        '{"run_id":' || json_str(l_run_id) ||
        ',"status":"FAILED","error":{"code":"INVALID_LLM_CALL_ID"}}'
      );
    END IF;

    SELECT stage,
           attempt_no,
           profile_name,
           call_status,
           prompt_clob,
           response_clob,
           prompt_chars,
           response_chars,
           error_code,
           error_message,
           started_at,
           completed_at
    INTO   l_stage,
           l_attempt_no,
           l_profile_name,
           l_call_status,
           l_prompt,
           l_response,
           l_prompt_chars,
           l_response_chars,
           l_error_code,
           l_error_message,
           l_started_at,
           l_completed_at
    FROM   asta_llm_call_log
    WHERE  run_id = l_run_id
    AND    call_id = p_call_id;

    DBMS_LOB.CREATETEMPORARY(l_out, TRUE);
    clob_app(l_out, '{"run_id":' || json_str(l_run_id));
    clob_app(l_out, ',"status":"COMPLETED"');
    clob_app(l_out, ',"call_id":' || json_num(p_call_id));
    clob_app(l_out, ',"stage":' || json_str(l_stage));
    clob_app(l_out, ',"attempt_no":' || json_num(l_attempt_no));
    clob_app(l_out, ',"profile_name":' || json_str(l_profile_name));
    clob_app(l_out, ',"call_status":' || json_str(l_call_status));
    clob_app(l_out, ',"prompt_chars":' || json_num(l_prompt_chars));
    clob_app(l_out, ',"response_chars":' || json_num(l_response_chars));
    clob_app(l_out, ',"error_code":' || json_num(l_error_code));
    clob_app(l_out, ',"error_message":' || json_str(l_error_message));
    clob_app(l_out, ',"started_at":' || json_ts(l_started_at));
    clob_app(l_out, ',"completed_at":' || json_ts(l_completed_at));
    clob_app(l_out, ',"elapsed_ms":' || json_num(elapsed_ms_between(l_started_at, NVL(l_completed_at, LOCALTIMESTAMP))));
    clob_app(l_out, ',"sensitivity":"CONTAINS_OPERATIONAL_SQL_AND_XPLAN"');
    clob_app(l_out, ',"prompt":');
    clob_app_json_str(l_out, l_prompt);
    clob_app(l_out, ',"response":');
    clob_app_json_str(l_out, l_response);
    clob_app(l_out, '}');
    RETURN l_out;
  EXCEPTION
    WHEN NO_DATA_FOUND THEN
      RETURN TO_CLOB(
        '{"run_id":' || json_str(NVL(l_run_id, p_run_id)) ||
        ',"status":"NOT_FOUND","error":{"code":"LLM_CALL_NOT_FOUND"}}'
      );
    WHEN OTHERS THEN
      RETURN TO_CLOB(
        '{"run_id":' || json_str(p_run_id) ||
        ',"status":"FAILED","error":{"code":"LLM_CALL_LOOKUP","message":' ||
        json_str(SUBSTR(SQLERRM, 1, 4000)) || '}}'
      );
  END get_llm_call;

  FUNCTION get_report(p_run_id IN VARCHAR2) RETURN CLOB IS
    l_report CLOB;
    l_out    CLOB;
    l_run_id VARCHAR2(64);
    l_status VARCHAR2(30);
    l_error_code VARCHAR2(128);
    l_error_message VARCHAR2(4000);
  BEGIN
    l_run_id := normalize_run_id(p_run_id);

    SELECT status, detailed_report_md, error_code, error_message
    INTO   l_status, l_report, l_error_code, l_error_message
    FROM   asta_runs
    WHERE  run_id = l_run_id;

    DBMS_LOB.CREATETEMPORARY(l_out, TRUE);
    clob_app(l_out, '{"run_id":');
    clob_app(l_out, json_str(l_run_id));
    clob_app(l_out, ',"status":' || json_str(l_status));
    clob_app(l_out, ',"report_ready":' || CASE WHEN l_report IS NULL THEN 'false' ELSE 'true' END);
    clob_app(l_out, ',"error_code":' || json_str(l_error_code));
    clob_app(l_out, ',"error_message":' || json_str(l_error_message));
    clob_app(l_out, ',"error":');
    IF l_error_code IS NULL AND l_error_message IS NULL THEN
      clob_app(l_out, 'null');
    ELSE
      clob_app_clob(l_out, error_json(l_error_code, l_error_message));
    END IF;
    clob_app(l_out, ',"source":"ADB_ORDS","architecture":"ADB_ORDS_PLSQL","contract_version":"asta.v1",');
    clob_app(l_out, migration_boundary_json);
    clob_app(l_out, ',"detailed_report_markdown":');
    clob_app_json_str(l_out, l_report);
    clob_app(l_out, '}');
    RETURN l_out;
  EXCEPTION
    WHEN NO_DATA_FOUND THEN
      RETURN TO_CLOB(
        '{"run_id":' || json_str(NVL(l_run_id, p_run_id)) ||
        ',"status":"NOT_FOUND","source":"ADB_ORDS","architecture":"ADB_ORDS_PLSQL","contract_version":"asta.v1",' ||
        migration_boundary_json ||
        ',"error":{"code":"REPORT_NOT_FOUND"}}'
      );
    WHEN OTHERS THEN
      RETURN TO_CLOB(
        '{"run_id":' || json_str(p_run_id) ||
        ',"status":"FAILED","source":"ADB_ORDS","architecture":"ADB_ORDS_PLSQL","contract_version":"asta.v1",' ||
        migration_boundary_json ||
        ',"error":{"code":"REPORT_LOOKUP","message":' ||
        json_str(SUBSTR(SQLERRM, 1, 4000)) || '}}'
      );
  END get_report;
END asta_pkg;
/
