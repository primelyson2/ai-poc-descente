-- db/adb/asta_vector_pkg.sql
-- ADB Vector KB facade for ASTA. Uses dynamic SQL so the package can be
-- installed before the final Vector table shape is confirmed.

CREATE OR REPLACE PACKAGE asta_vector_pkg AUTHID DEFINER AS
  FUNCTION search_similar_cases(
    p_sql   IN CLOB,
    p_top_k IN NUMBER DEFAULT 3
  ) RETURN CLOB;

  FUNCTION save_case(
    p_run_id          IN VARCHAR2,
    p_sql             IN CLOB,
    p_tuned_sql       IN CLOB,
    p_report_markdown IN CLOB,
    p_metadata_json   IN CLOB DEFAULT NULL
  ) RETURN CLOB;
END asta_vector_pkg;
/

CREATE OR REPLACE PACKAGE BODY asta_vector_pkg AS
  C_SEARCH_STRATEGY CONSTANT VARCHAR2(40) := 'FINGERPRINT_FIRST_CHUNK_SCAN';
  C_CHUNK_CHARS     CONSTANT PLS_INTEGER := 4000;

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

  FUNCTION object_exists(p_object_name IN VARCHAR2) RETURN BOOLEAN IS
    l_count NUMBER;
  BEGIN
    SELECT COUNT(*)
    INTO   l_count
    FROM   user_objects
    WHERE  object_name = UPPER(p_object_name)
    AND    object_type IN ('TABLE', 'VIEW', 'SYNONYM');
    RETURN l_count > 0;
  END object_exists;

  FUNCTION sql_fingerprint(p_sql IN CLOB) RETURN VARCHAR2 IS
    l_hash VARCHAR2(128);
  BEGIN
    SELECT STANDARD_HASH(DBMS_LOB.SUBSTR(p_sql, 32767, 1), 'SHA256')
    INTO   l_hash
    FROM   dual;
    RETURN l_hash;
  EXCEPTION
    WHEN OTHERS THEN
      RETURN NULL;
  END sql_fingerprint;

  FUNCTION normalized_top_k(p_top_k IN NUMBER) RETURN PLS_INTEGER IS
  BEGIN
    RETURN LEAST(GREATEST(NVL(p_top_k, 3), 1), 20);
  END normalized_top_k;

  FUNCTION validated_case_id(p_run_id IN VARCHAR2) RETURN VARCHAR2 IS
    l_case_id VARCHAR2(64) := TRIM(p_run_id);
  BEGIN
    IF l_case_id IS NULL
       OR LENGTH(l_case_id) > 64
       OR NOT REGEXP_LIKE(l_case_id, '^[A-Za-z0-9][A-Za-z0-9_.:-]*$') THEN
      RAISE_APPLICATION_ERROR(-20004, 'ASTA_VECTOR: invalid case_id');
    END IF;
    RETURN l_case_id;
  END validated_case_id;

  FUNCTION chunk_clob(p_val IN CLOB) RETURN CLOB IS
    l_len PLS_INTEGER;
  BEGIN
    IF p_val IS NULL THEN
      RETURN NULL;
    END IF;
    l_len := NVL(DBMS_LOB.GETLENGTH(p_val), 0);
    IF l_len = 0 THEN
      RETURN NULL;
    END IF;
    RETURN TO_CLOB(DBMS_LOB.SUBSTR(p_val, LEAST(l_len, C_CHUNK_CHARS), 1));
  END chunk_clob;

  FUNCTION save_case_chunk(
    p_case_id    IN VARCHAR2,
    p_chunk_type IN VARCHAR2,
    p_chunk_text IN CLOB
  ) RETURN PLS_INTEGER IS
    l_chunk CLOB;
  BEGIN
    l_chunk := chunk_clob(p_chunk_text);
    IF l_chunk IS NULL THEN
      RETURN 0;
    END IF;

    EXECUTE IMMEDIATE q'[
      INSERT INTO asta_tuning_case_chunks(
        case_id,
        chunk_type,
        chunk_text,
        created_at
      ) VALUES (
        :case_id,
        :chunk_type,
        :chunk_text,
        SYSTIMESTAMP
      )
    ]'
    USING p_case_id, p_chunk_type, l_chunk;

    RETURN 1;
  END save_case_chunk;

  FUNCTION not_configured(p_operation IN VARCHAR2, p_sql IN CLOB DEFAULT NULL) RETURN CLOB IS
  BEGIN
    RETURN TO_CLOB(
      '{"status":"NOT_CONFIGURED","code":"VECTOR_KB","operation":' ||
      json_str(p_operation) ||
      ',"contract_version":"asta.v1"' ||
      ',"execution_boundary":"ADB_VECTOR_PLSQL"' ||
      ',"search_strategy":' || json_str(C_SEARCH_STRATEGY) ||
      ',"query_fingerprint":' || json_str(sql_fingerprint(p_sql)) ||
      ',"source_fingerprint":' || json_str(sql_fingerprint(p_sql)) ||
      ',"message":"ASTA vector KB tables are not installed yet","cases":[]}'
    );
  END not_configured;

  FUNCTION search_similar_cases(
    p_sql   IN CLOB,
    p_top_k IN NUMBER DEFAULT 3
  ) RETURN CLOB IS
    l_top_k PLS_INTEGER := normalized_top_k(p_top_k);
    l_cases CLOB;
    l_query_fingerprint VARCHAR2(128) := sql_fingerprint(p_sql);
  BEGIN
    IF NOT object_exists('ASTA_TUNING_CASES')
       OR NOT object_exists('ASTA_TUNING_CASE_CHUNKS') THEN
      RETURN not_configured('SEARCH_SIMILAR_CASES', p_sql);
    END IF;

    EXECUTE IMMEDIATE q'~
      SELECT COALESCE(
               JSON_ARRAYAGG(
                 JSON_OBJECT(
                   'case_id' VALUE case_id,
                   'chunk_id' VALUE chunk_id,
                   'chunk_type' VALUE chunk_type,
                   'matched_fingerprint' VALUE matched_fingerprint,
                   'source_fingerprint' VALUE sql_fingerprint,
                   'chunk_text' VALUE DBMS_LOB.SUBSTR(chunk_text, 2000, 1)
                   RETURNING CLOB
                 )
                 RETURNING CLOB
               ),
               TO_CLOB('[]')
             )
      FROM (
        SELECT case_id, chunk_id, chunk_type, chunk_text, sql_fingerprint, matched_fingerprint
        FROM (
          SELECT c.case_id,
                 ch.chunk_id,
                 ch.chunk_type,
                 ch.chunk_text,
                 c.sql_fingerprint,
                 CASE WHEN c.sql_fingerprint = :query_fp_match THEN 'Y' ELSE 'N' END AS matched_fingerprint
          FROM   asta_tuning_case_chunks ch
                 JOIN asta_tuning_cases c ON c.case_id = ch.case_id
          ORDER  BY CASE WHEN c.sql_fingerprint = :query_fp_order THEN 0 ELSE 1 END,
                    c.created_at DESC,
                    ch.chunk_id
        )
        WHERE  ROWNUM <= :top_k
      )
    ~'
    INTO l_cases
    USING l_query_fingerprint, l_query_fingerprint, l_top_k;

    RETURN TO_CLOB(
      '{"status":"COMPLETED","code":"VECTOR_KB","operation":"SEARCH_SIMILAR_CASES","top_k":' ||
      TO_CHAR(l_top_k) || ',"query_fingerprint":' || json_str(l_query_fingerprint) ||
      ',"contract_version":"asta.v1"' ||
      ',"execution_boundary":"ADB_VECTOR_PLSQL"' ||
      ',"search_strategy":' || json_str(C_SEARCH_STRATEGY) ||
      ',"source_fingerprint":' || json_str(l_query_fingerprint) ||
      ',"cases":'
    ) || NVL(l_cases, TO_CLOB('[]')) || TO_CLOB('}');
  EXCEPTION
    WHEN OTHERS THEN
      RETURN TO_CLOB(
        '{"status":"FAILED","code":"VECTOR_KB","operation":"SEARCH_SIMILAR_CASES","message":' ||
        json_str(SUBSTR(SQLERRM, 1, 4000)) ||
        ',"query_fingerprint":' || json_str(l_query_fingerprint) ||
        ',"contract_version":"asta.v1"' ||
        ',"execution_boundary":"ADB_VECTOR_PLSQL"' ||
        ',"search_strategy":' || json_str(C_SEARCH_STRATEGY) ||
        ',"source_fingerprint":' || json_str(l_query_fingerprint) ||
        ',"cases":[]}'
      );
  END search_similar_cases;

  FUNCTION save_case(
    p_run_id          IN VARCHAR2,
    p_sql             IN CLOB,
    p_tuned_sql       IN CLOB,
    p_report_markdown IN CLOB,
    p_metadata_json   IN CLOB DEFAULT NULL
  ) RETURN CLOB IS
    l_case_id VARCHAR2(64);
    l_source_fingerprint VARCHAR2(128);
    l_chunks_saved PLS_INTEGER := 0;
  BEGIN
    l_case_id := validated_case_id(p_run_id);
    l_source_fingerprint := sql_fingerprint(p_sql);

    IF NOT object_exists('ASTA_TUNING_CASES')
       OR NOT object_exists('ASTA_TUNING_CASE_CHUNKS') THEN
      RETURN not_configured('SAVE_CASE', p_sql);
    END IF;

    SAVEPOINT asta_vector_save_case;

    EXECUTE IMMEDIATE q'[
      INSERT INTO asta_tuning_cases(
        case_id,
        source_sql,
        tuned_sql,
        report_markdown,
        metadata_json,
        sql_fingerprint,
        created_at
      ) VALUES (
        :case_id,
        :source_sql,
        :tuned_sql,
        :report_markdown,
        :metadata_json,
        :sql_fp,
        SYSTIMESTAMP
      )
    ]'
    USING l_case_id, p_sql, p_tuned_sql, p_report_markdown, p_metadata_json, l_source_fingerprint;

    l_chunks_saved := l_chunks_saved + save_case_chunk(l_case_id, 'SOURCE_SQL', p_sql);
    l_chunks_saved := l_chunks_saved + save_case_chunk(l_case_id, 'TUNED_SQL', p_tuned_sql);
    l_chunks_saved := l_chunks_saved + save_case_chunk(l_case_id, 'REPORT_MARKDOWN', p_report_markdown);

    RETURN TO_CLOB(
      '{"status":"COMPLETED","code":"VECTOR_KB","operation":"SAVE_CASE","case_id":' ||
      json_str(l_case_id) ||
      ',"contract_version":"asta.v1"' ||
      ',"execution_boundary":"ADB_VECTOR_PLSQL"' ||
      ',"search_strategy":' || json_str(C_SEARCH_STRATEGY) ||
      ',"chunks_saved":' || TO_CHAR(l_chunks_saved) ||
      ',"source_fingerprint":' || json_str(l_source_fingerprint) || '}'
    );
  EXCEPTION
    WHEN OTHERS THEN
      BEGIN
        ROLLBACK TO asta_vector_save_case;
      EXCEPTION
        WHEN OTHERS THEN NULL;
      END;
      RETURN TO_CLOB(
        '{"status":"FAILED","code":"VECTOR_KB","operation":"SAVE_CASE","case_id":' ||
        json_str(p_run_id) ||
        ',"contract_version":"asta.v1"' ||
        ',"execution_boundary":"ADB_VECTOR_PLSQL"' ||
        ',"search_strategy":' || json_str(C_SEARCH_STRATEGY) ||
        ',"source_fingerprint":' || json_str(l_source_fingerprint) ||
        ',"message":' ||
        json_str(SUBSTR(SQLERRM, 1, 4000)) || '}'
      );
  END save_case;
END asta_vector_pkg;
/
