-- db/adb/asta_pkg.sql
-- Main ADB ASTA orchestration package exposed by ORDS.

CREATE OR REPLACE PACKAGE asta_pkg AUTHID DEFINER AS
  FUNCTION analyze_sql(p_body_json IN CLOB) RETURN CLOB;
  FUNCTION list_profiles RETURN CLOB;
  FUNCTION get_run(p_run_id IN VARCHAR2) RETURN CLOB;
  FUNCTION get_progress(p_run_id IN VARCHAR2) RETURN CLOB;
  FUNCTION get_report(p_run_id IN VARCHAR2) RETURN CLOB;
END asta_pkg;
/

CREATE OR REPLACE PACKAGE BODY asta_pkg AS
  C_DEFAULT_LLM_PROFILE CONSTANT VARCHAR2(128) := 'ASTA_GPT5_PROFILE';
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
      l_chunk := DBMS_LOB.SUBSTR(p_val, 32767, l_offset);
      DBMS_LOB.WRITEAPPEND(p_out, LENGTH(l_chunk), l_chunk);
      l_offset := l_offset + 32767;
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
      RETURN NVL(l_message, l_error_message);
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
      RETURN 'SQL Tuning Advisor intentionally skipped; set run_advisor/use_sqltune=true to request Source DBMS_SQLTUNE';
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
        ELSE 'SQL Tuning Advisor intentionally skipped'
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

  FUNCTION build_comparison_json(p_before_json IN CLOB, p_after_json IN CLOB) RETURN CLOB IS
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
    l_row_match        VARCHAR2(5);
    l_output_match     VARCHAR2(5);
    l_gets_delta       NUMBER;
    l_gets_pct         NUMBER;
    l_reads_delta      NUMBER;
    l_elapsed_delta    NUMBER;
  BEGIN
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
           JSON_VALUE(p_after_json, '$.last_elapsed_time_us' RETURNING NUMBER NULL ON ERROR)
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
           l_after_elapsed
    FROM   dual;

    IF UPPER(NVL(l_before_status, 'COMPLETED')) = 'FAILED'
       OR UPPER(NVL(l_after_status, 'COMPLETED')) = 'FAILED'
       OR l_before_error IS NOT NULL
       OR l_after_error IS NOT NULL THEN
      RETURN TO_CLOB(
        '{"status":"FAILED","code":"BEFORE_AFTER_COMPARISON","contract_version":"asta.v1","execution_boundary":"ADB_COMPARISON_PLSQL","message":' ||
        json_str(NVL(l_after_error, l_before_error)) || '}'
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

    RETURN TO_CLOB(
      '{"status":"COMPLETED","code":"BEFORE_AFTER_COMPARISON","contract_version":"asta.v1","execution_boundary":"ADB_COMPARISON_PLSQL"' ||
      ',"row_count_matches":'          || l_row_match ||
      ',"output_rows_match":'          || l_output_match ||
      ',"before_row_count":'           || json_num(l_before_rows) ||
      ',"after_row_count":'            || json_num(l_after_rows) ||
      ',"before_output_rows":'         || json_num(l_before_output) ||
      ',"after_output_rows":'          || json_num(l_after_output) ||
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
      '}'
    );
  EXCEPTION
    WHEN OTHERS THEN
      RETURN TO_CLOB(
        '{"status":"FAILED","code":"BEFORE_AFTER_COMPARISON","contract_version":"asta.v1","execution_boundary":"ADB_COMPARISON_PLSQL","message":' ||
        json_str(SUBSTR(SQLERRM, 1, 4000)) || '}'
      );
  END build_comparison_json;

  FUNCTION llm_original_fallback_json(p_sql IN CLOB, p_reason IN VARCHAR2) RETURN CLOB IS
    l_out CLOB;
  BEGIN
    DBMS_LOB.CREATETEMPORARY(l_out, TRUE);
    clob_app(l_out, '{"status":"COMPLETED","code":"LLM_TUNE","contract_version":"asta.v1","execution_boundary":"ADB_DBMS_CLOUD_AI"');
    clob_app(l_out, ',"response_contract":"JSON_ONLY","candidate_guard_policy":"SELECT_WITH_SINGLE_STATEMENT"');
    clob_app(l_out, ',"candidate_sql":');
    clob_app_json_str(l_out, p_sql);
    clob_app(l_out, ',"change_reason":"LLM candidate failed executable validation"');
    clob_app(l_out, ',"change_summary":"원본 SQL 유지"');
    clob_app(l_out, ',"change_location":"변경 없음"');
    clob_app(l_out, ',"candidate_error":');
    clob_app(l_out, json_str(SUBSTR(p_reason, 1, 4000)));
    clob_app(l_out, ',"raw_response":null}');
    RETURN l_out;
  END llm_original_fallback_json;

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

  FUNCTION analyze_sql(p_body_json IN CLOB) RETURN CLOB IS
    l_run_id              VARCHAR2(64);
    l_sql_vc              VARCHAR2(32767);
    l_sql                 CLOB;
    l_tuned_sql_vc        VARCHAR2(32767);
    l_tuned_sql           CLOB;
    l_llm_profile         VARCHAR2(128);
    l_source_db_id        VARCHAR2(64);
    l_source_schema       VARCHAR2(128);
    l_source_db_link      VARCHAR2(128);
    l_source_connection_json CLOB;
    l_source_error        VARCHAR2(4000);
    l_use_llm_raw         VARCHAR2(30);
    l_use_llm             VARCHAR2(1);
    l_run_advisor_raw     VARCHAR2(30);
    l_run_advisor         VARCHAR2(1) := 'N';
    l_fetch_rows          NUMBER := 100;
    l_vector_top_k        NUMBER := 3;
    l_sqltune_time_limit  NUMBER := 1800;
    l_context_json        CLOB;
    l_source_json         CLOB;
    l_after_json          CLOB;
    l_before_after_json   CLOB;
    l_comparison_json     CLOB;
    l_vector_json         CLOB;
    l_llm_json            CLOB;
    l_sql_only_llm_json   CLOB;
    l_sql_only_sql_vc     VARCHAR2(32767);
    l_sql_only_sql        CLOB;
    l_final_review_json   CLOB;
    l_vector_save_json    CLOB;
    l_report_markdown     CLOB;
    l_progress_json       CLOB;
    l_response_json       CLOB;
    l_error_json          CLOB;
    l_error_message       VARCHAR2(4000);
    l_status              VARCHAR2(30) := 'COMPLETED';
  BEGIN
    l_run_id := COALESCE(
      JSON_VALUE(p_body_json, '$.run_id' RETURNING VARCHAR2(64) NULL ON ERROR),
      JSON_VALUE(p_body_json, '$.client_run_id' RETURNING VARCHAR2(64) NULL ON ERROR),
      'OADT2-ASTA-' || LOWER(RAWTOHEX(SYS_GUID()))
    );
    l_run_id := normalize_run_id(l_run_id);

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
           JSON_QUERY(p_body_json, '$.tuning_context' RETURNING CLOB NULL ON ERROR)
    INTO   l_sql_vc,
           l_llm_profile,
           l_source_db_id,
           l_use_llm_raw,
           l_fetch_rows,
           l_vector_top_k,
           l_sqltune_time_limit,
           l_run_advisor_raw,
           l_context_json
    FROM   dual;

    l_sql := TO_CLOB(l_sql_vc);
    l_source_db_id := normalize_source_db_id(l_source_db_id);
    l_fetch_rows := normalized_fetch_rows(l_fetch_rows);
    l_vector_top_k := normalized_vector_top_k(l_vector_top_k);
    l_sqltune_time_limit := normalized_sqltune_time_limit(l_sqltune_time_limit);
    l_run_advisor := normalized_run_advisor(l_run_advisor_raw);
    l_use_llm := CASE
      WHEN LOWER(TRIM(l_use_llm_raw)) IN ('false', '0', 'n', 'no') THEN 'N'
      ELSE 'Y'
    END;

    INSERT INTO asta_runs(
      run_id,
      status,
      input_sql,
      llm_profile,
      source_db_id,
      source_schema,
      source_db_link,
      created_at,
      started_at
    ) VALUES (
      l_run_id,
      'RUNNING',
      l_sql,
      l_llm_profile,
      l_source_db_id,
      l_source_schema,
      l_source_db_link,
      SYSTIMESTAMP,
      SYSTIMESTAMP
    );
    COMMIT;

    record_progress(l_run_id, 3, 'SQL_GUARD', 'ADB SQL guard', 'RUNNING');
    asta_sql_guard_pkg.assert_safe_select(l_sql);
    record_progress(l_run_id, 3, 'SQL_GUARD', 'ADB SQL guard', 'DONE');

    record_progress(l_run_id, 4, 'BEFORE_EVIDENCE', 'Source evidence via DB Link', 'RUNNING');
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
      p_repeat_policy    => 'AUTO',
      p_run_advisor      => l_run_advisor,
      p_sqltune_time_sec => l_sqltune_time_limit
    );
    l_source_error := source_response_error_message(l_source_json);
    IF l_source_error IS NOT NULL THEN
      record_progress(l_run_id, 4, 'BEFORE_EVIDENCE', 'Source evidence via DB Link', 'FAILED', SUBSTR(l_source_error, 1, 1000));
      RAISE_APPLICATION_ERROR(-20002, 'ASTA_PKG: Source evidence failed: ' || SUBSTR(l_source_error, 1, 1000));
    END IF;
    record_progress(l_run_id, 4, 'BEFORE_EVIDENCE', 'Source evidence via DB Link', 'DONE');
    record_progress(
      l_run_id,
      5,
      'SQL_TUNING_ADVISOR',
      'SQL Tuning Advisor',
      advisor_progress_status(l_source_json),
      advisor_progress_detail(l_source_json, l_run_advisor)
    );

    record_progress(l_run_id, 6, 'VECTOR_KB', 'ADB Vector KB search', 'RUNNING');
    l_vector_json := asta_vector_pkg.search_similar_cases(l_sql, l_vector_top_k);
    record_progress(l_run_id, 6, 'VECTOR_KB', 'ADB Vector KB search', progress_status_from_json(l_vector_json));

    record_progress(l_run_id, 7, 'LLM_REWRITE', 'ADB DBMS_CLOUD_AI tuning', 'RUNNING');
    l_llm_json := asta_llm_pkg.generate_tuning(
      p_sql                  => l_sql,
      p_llm_profile          => l_llm_profile,
      p_source_evidence_json => l_source_json,
      p_vector_json          => l_vector_json,
      p_tuning_context_json  => l_context_json,
      p_use_llm              => l_use_llm
    );
    record_progress(l_run_id, 7, 'LLM_REWRITE', 'ADB DBMS_CLOUD_AI tuning', progress_status_from_json(l_llm_json));

    BEGIN
      SELECT JSON_VALUE(l_llm_json, '$.candidate_sql' RETURNING VARCHAR2(32767) NULL ON ERROR)
      INTO   l_tuned_sql_vc
      FROM   dual;
    EXCEPTION
      WHEN OTHERS THEN
        l_tuned_sql_vc := NULL;
    END;
    IF l_tuned_sql_vc IS NULL THEN
      l_tuned_sql := NULL;
    ELSE
      l_tuned_sql := TO_CLOB(l_tuned_sql_vc);
    END IF;

    IF l_use_llm = 'Y' AND (
      sql_needs_sql_only_retry(l_sql, l_tuned_sql)
      OR LOWER(TRIM(REGEXP_REPLACE(NVL(l_tuned_sql_vc, ''), '[[:space:]]+', ' '))) = LOWER(TRIM(REGEXP_REPLACE(NVL(l_sql_vc, ''), '[[:space:]]+', ' ')))
    ) THEN
      l_sql_only_llm_json := asta_llm_pkg.generate_sql_only_tuning(
        p_sql         => l_sql,
        p_llm_profile => l_llm_profile,
        p_use_llm     => l_use_llm
      );
      BEGIN
        SELECT JSON_VALUE(l_sql_only_llm_json, '$.candidate_sql' RETURNING VARCHAR2(32767) NULL ON ERROR)
        INTO   l_sql_only_sql_vc
        FROM   dual;
      EXCEPTION
        WHEN OTHERS THEN
          l_sql_only_sql_vc := NULL;
      END;
      IF l_sql_only_sql_vc IS NOT NULL THEN
        l_sql_only_sql := TO_CLOB(l_sql_only_sql_vc);
        IF NOT sql_needs_sql_only_retry(l_sql, l_sql_only_sql) THEN
          l_tuned_sql := l_sql_only_sql;
          l_llm_json := l_sql_only_llm_json;
        END IF;
      END IF;
    END IF;

    IF l_tuned_sql IS NOT NULL THEN
      record_progress(l_run_id, 8, 'AFTER_EVIDENCE', 'Tuned SQL evidence', 'RUNNING');
      l_after_json := asta_source_bridge_pkg.run_source_evidence(
        p_source_db_id     => l_source_db_id,
        p_sql              => l_tuned_sql,
        p_run_id           => l_run_id || '-TUNED',
        p_fetch_rows       => l_fetch_rows,
        p_repeat_policy    => 'AUTO',
        p_run_advisor      => 'N',
        p_sqltune_time_sec => l_sqltune_time_limit
      );

      l_source_error := source_response_error_message(l_after_json);
      IF l_source_error IS NOT NULL THEN
        -- The LLM can return syntactically invalid Oracle SQL for complex inputs
        -- even after passing the lightweight SELECT/WITH guard. Do not leave the
        -- run half-failed; retain the original SQL as the executable safe
        -- candidate and preserve the invalid-candidate error in LLM metadata.
        l_llm_json := llm_original_fallback_json(l_sql, 'Invalid LLM candidate: ' || l_source_error);
        l_tuned_sql := l_sql;
        l_after_json := asta_source_bridge_pkg.run_source_evidence(
          p_source_db_id     => l_source_db_id,
          p_sql              => l_tuned_sql,
          p_run_id           => l_run_id || '-SAFE',
          p_fetch_rows       => l_fetch_rows,
          p_repeat_policy    => 'AUTO',
          p_run_advisor      => 'N',
          p_sqltune_time_sec => l_sqltune_time_limit
        );
        l_source_error := source_response_error_message(l_after_json);
      END IF;

      IF l_source_error IS NULL THEN
        record_progress(l_run_id, 8, 'AFTER_EVIDENCE', 'Tuned SQL evidence', 'DONE');
      ELSE
        record_progress(l_run_id, 8, 'AFTER_EVIDENCE', 'Tuned SQL evidence', 'FAILED', SUBSTR(l_source_error, 1, 1000));
      END IF;

      record_progress(l_run_id, 9, 'LLM_FINAL_REVIEW', 'Before/After comparison', 'RUNNING');
      l_comparison_json := build_comparison_json(l_source_json, l_after_json);
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

      l_final_review_json := asta_llm_pkg.final_review(
        p_before_after_json => l_before_after_json,
        p_llm_profile       => l_llm_profile,
        p_use_llm           => l_use_llm
      );
      record_progress(l_run_id, 9, 'LLM_FINAL_REVIEW', 'Before/After comparison', progress_status_from_json(l_final_review_json));
    ELSE
      record_progress(l_run_id, 8, 'AFTER_EVIDENCE', 'Tuned SQL evidence', 'SKIPPED', 'No safe candidate_sql returned by ASTA LLM');
      record_progress(l_run_id, 9, 'LLM_FINAL_REVIEW', 'Before/After comparison', 'SKIPPED', 'No safe candidate_sql returned by ASTA LLM');
    END IF;

    record_progress(l_run_id, 10, 'FINAL_REPORT', 'Final report synthesis', 'RUNNING');
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

    record_progress(l_run_id, 11, 'VECTOR_SAVE', 'ADB Vector KB save', 'RUNNING');
    l_vector_save_json := asta_vector_pkg.save_case(
      p_run_id          => l_run_id,
      p_sql             => l_sql,
      p_tuned_sql       => l_tuned_sql,
      p_report_markdown => l_report_markdown,
      p_metadata_json   => l_llm_json
    );
    record_progress(l_run_id, 11, 'VECTOR_SAVE', 'ADB Vector KB save', progress_status_from_json(l_vector_save_json));
    l_progress_json := build_progress_array_json(l_run_id);

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
      l_error_json := error_json('ASTA_PKG', l_error_message);
      record_progress(l_run_id, 11, 'FINAL_REPORT', 'Final report synthesis', 'FAILED', SUBSTR(l_error_message, 1, 1000));
      l_progress_json := build_progress_array_json(l_run_id);

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
        p_final_review_json    => l_final_review_json
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
               error_code = 'ASTA_PKG',
               error_message = l_error_message,
               detailed_report_md = l_report_markdown,
               response_json = l_response_json
        WHERE  run_id = l_run_id;
        COMMIT;
      EXCEPTION
        WHEN OTHERS THEN
          ROLLBACK;
      END;

      RETURN l_response_json;
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
  BEGIN
    l_run_id := normalize_run_id(p_run_id);

    SELECT response_json
    INTO   l_response
    FROM   asta_runs
    WHERE  run_id = l_run_id;

    RETURN NVL(
      l_response,
      TO_CLOB('{"run_id":') || json_str(l_run_id) ||
      TO_CLOB(',"status":"UNKNOWN","source":"ADB_ORDS","architecture":"ADB_ORDS_PLSQL","contract_version":"asta.v1",') ||
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

  FUNCTION get_progress(p_run_id IN VARCHAR2) RETURN CLOB IS
    l_status       VARCHAR2(30);
    l_started_at   TIMESTAMP;
    l_completed_at TIMESTAMP;
    l_out          CLOB;
    l_run_id       VARCHAR2(64);
  BEGIN
    l_run_id := normalize_run_id(p_run_id);

    SELECT status, started_at, completed_at
    INTO   l_status, l_started_at, l_completed_at
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
    clob_app(l_out, ',"started_at":');
    clob_app(l_out, json_ts(l_started_at));
    clob_app(l_out, ',"completed_at":');
    clob_app(l_out, json_ts(l_completed_at));
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

  FUNCTION get_report(p_run_id IN VARCHAR2) RETURN CLOB IS
    l_report CLOB;
    l_out    CLOB;
    l_run_id VARCHAR2(64);
  BEGIN
    l_run_id := normalize_run_id(p_run_id);

    SELECT detailed_report_md
    INTO   l_report
    FROM   asta_runs
    WHERE  run_id = l_run_id;

    DBMS_LOB.CREATETEMPORARY(l_out, TRUE);
    clob_app(l_out, '{"run_id":');
    clob_app(l_out, json_str(l_run_id));
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
