-- db/adb/asta_vector_pkg.sql
-- ADB Vector KB facade for ASTA. Uses dynamic SQL so the package can be
-- installed before the final Vector table shape is confirmed.

CREATE OR REPLACE PACKAGE asta_vector_pkg AUTHID DEFINER AS
  FUNCTION search_similar_cases(
    p_sql   IN CLOB,
    p_top_k IN NUMBER DEFAULT 3
  ) RETURN CLOB;

  -- Bounded user-facing preview; full SQL remains only in the case artifact.
  FUNCTION sql_preview(p_sql IN CLOB) RETURN VARCHAR2;

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
  C_SQL_PREVIEW_CHARS CONSTANT PLS_INTEGER := 500;
  C_SQL_PREVIEW_LINES CONSTANT PLS_INTEGER := 10;

  FUNCTION sql_preview(p_sql IN CLOB) RETURN VARCHAR2 IS
    l_text    VARCHAR2(32767);
    l_masked  VARCHAR2(32767) := '';
    l_out     VARCHAR2(32767);
    l_line    VARCHAR2(32767);
    l_i       PLS_INTEGER := 1;
    l_len     PLS_INTEGER;
    l_q_open  VARCHAR2(1);
    l_q_close VARCHAR2(1);
    l_marker  CONSTANT VARCHAR2(30) := '... (이하 생략)';
    l_candidate VARCHAR2(32767);
    l_last_break PLS_INTEGER;
    l_truncated BOOLEAN := FALSE;
  BEGIN
    IF p_sql IS NULL THEN RETURN NULL; END IF;
    l_text := DBMS_LOB.SUBSTR(p_sql, 32767, 1);
    l_len := LENGTH(l_text);
    -- Lex before applying numeric masking: remove line/block comments and mask
    -- ordinary and q-quoted literals ([], {}, (), <>, or same delimiter).
    WHILE l_i <= l_len LOOP
      IF SUBSTR(l_text, l_i, 2) = '--' THEN
        WHILE l_i <= l_len AND SUBSTR(l_text, l_i, 1) NOT IN (CHR(10), CHR(13)) LOOP l_i := l_i + 1; END LOOP;
      ELSIF SUBSTR(l_text, l_i, 2) = '/*' THEN
        l_i := l_i + 2;
        WHILE l_i <= l_len AND SUBSTR(l_text, l_i, 2) <> '*/' LOOP
          IF SUBSTR(l_text, l_i, 1) IN (CHR(10), CHR(13)) THEN l_masked := l_masked || SUBSTR(l_text, l_i, 1); END IF;
          l_i := l_i + 1;
        END LOOP;
        l_i := LEAST(l_i + 2, l_len + 1);
      ELSIF LOWER(SUBSTR(l_text, l_i, 1)) = 'q' AND SUBSTR(l_text, l_i + 1, 1) = '''' AND l_i + 2 <= l_len THEN
        l_q_open := SUBSTR(l_text, l_i + 2, 1);
        l_q_close := CASE l_q_open WHEN '[' THEN ']' WHEN '{' THEN '}' WHEN '(' THEN ')' WHEN '<' THEN '>' ELSE l_q_open END;
        l_masked := l_masked || '''?'''; -- q-quoted literal
        l_i := l_i + 3;
        WHILE l_i <= l_len AND NOT (SUBSTR(l_text, l_i, 1) = l_q_close AND SUBSTR(l_text, l_i + 1, 1) = '''') LOOP l_i := l_i + 1; END LOOP;
        l_i := LEAST(l_i + 2, l_len + 1);
      ELSIF SUBSTR(l_text, l_i, 1) = '''' THEN
        l_masked := l_masked || '''?''';
        l_i := l_i + 1;
        WHILE l_i <= l_len LOOP
          IF SUBSTR(l_text, l_i, 1) = '''' THEN
            IF SUBSTR(l_text, l_i + 1, 1) = '''' THEN l_i := l_i + 2; ELSE l_i := l_i + 1; EXIT; END IF;
          ELSE l_i := l_i + 1; END IF;
        END LOOP;
      ELSE
        l_masked := l_masked || SUBSTR(l_text, l_i, 1);
        l_i := l_i + 1;
      END IF;
    END LOOP;
    l_masked := REGEXP_REPLACE(l_masked, '(^|[^[:alnum:]_$])([0-9]+([.][0-9]+)?)([^[:alnum:]_$]|$)', '\1?\4');
    FOR i IN 1 .. C_SQL_PREVIEW_LINES + 1 LOOP
      l_line := REGEXP_SUBSTR(l_masked, '[^' || CHR(10) || CHR(13) || ']+', 1, i);
      EXIT WHEN l_line IS NULL;
      IF i > C_SQL_PREVIEW_LINES THEN l_truncated := TRUE; EXIT; END IF;
      l_candidate := CASE WHEN l_out IS NULL THEN l_line ELSE l_out || CHR(10) || l_line END;
      IF LENGTH(l_candidate) > C_SQL_PREVIEW_CHARS THEN
        l_truncated := TRUE;
        -- Preserve prior complete lines. Only an oversized first line may be
        -- shortened, and then only at whitespace or SQL punctuation.
        IF l_out IS NULL THEN
          l_line := SUBSTR(l_line, 1, C_SQL_PREVIEW_CHARS - LENGTH(l_marker) - 1);
          l_last_break := LENGTH(l_line);
          WHILE l_last_break > 0 AND NOT REGEXP_LIKE(SUBSTR(l_line, l_last_break, 1), '[[:space:],.;:()]') LOOP
            l_last_break := l_last_break - 1;
          END LOOP;
          IF l_last_break > 0 THEN l_out := RTRIM(SUBSTR(l_line, 1, l_last_break)); END IF;
        END IF;
        EXIT;
      END IF;
      l_out := l_candidate;
    END LOOP;
    IF l_truncated THEN
      WHILE l_out IS NOT NULL AND LENGTH(l_out) + 1 + LENGTH(l_marker) > C_SQL_PREVIEW_CHARS LOOP
        l_out := REGEXP_REPLACE(l_out, CHR(10) || '[^' || CHR(10) || ']*$', '');
      END LOOP;
      RETURN CASE WHEN l_out IS NULL THEN l_marker ELSE l_out || CHR(10) || l_marker END;
    END IF;
    RETURN l_out;
  EXCEPTION WHEN OTHERS THEN
    -- A preview must fail closed: never return unmasked source SQL.
    RETURN '[SQL preview redacted]';
  END sql_preview;

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

  FUNCTION json_vc(p_json IN CLOB, p_path IN VARCHAR2, p_default IN VARCHAR2 DEFAULT NULL) RETURN VARCHAR2 IS
    l_val VARCHAR2(4000);
  BEGIN
    EXECUTE IMMEDIATE 'SELECT JSON_VALUE(:j, ''' || REPLACE(p_path, '''', '''''') ||
      ''' RETURNING VARCHAR2(4000) NULL ON ERROR) FROM dual' INTO l_val USING p_json;
    RETURN NVL(l_val, p_default);
  EXCEPTION WHEN OTHERS THEN RETURN p_default;
  END json_vc;

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
                   'run_id' VALUE case_id,
                   'learning_class' VALUE learning_class,
                   'verdict' VALUE verdict,
                   'workload_type' VALUE workload_type,
                   'primary_metric' VALUE primary_metric,
                   'change_summary' VALUE CASE WHEN TRIM(change_summary) IN ('[]', 'null', '') THEN '-' ELSE NVL(change_summary, '-') END,
                   'before_buffer_gets' VALUE before_buffer_gets,
                   'after_buffer_gets' VALUE after_buffer_gets,
                   'before_elapsed_time_us' VALUE before_elapsed_time_us,
                   'after_elapsed_time_us' VALUE after_elapsed_time_us,
                   'sql_preview' VALUE sql_preview,
                   'report_ref' VALUE '/api/asta/runs/' || case_id || '/report',
                   'matched_fingerprint' VALUE matched_fingerprint,
                   'source_fingerprint' VALUE sql_fingerprint
                   RETURNING CLOB
                 )
                 RETURNING CLOB
               ),
               TO_CLOB('[]')
             )
      FROM (
        SELECT case_id, sql_fingerprint, matched_fingerprint, sql_preview, learning_class,
               workload_type, primary_metric, verdict, change_summary,
               before_buffer_gets, after_buffer_gets,
               before_elapsed_time_us, after_elapsed_time_us
        FROM (
          SELECT c.case_id,
                 c.sql_fingerprint,
                 asta_vector_pkg.sql_preview(c.source_sql) sql_preview,
                 JSON_VALUE(c.metadata_json, '$.workload_type' RETURNING VARCHAR2(30) NULL ON ERROR) workload_type,
                 JSON_VALUE(c.metadata_json, '$.primary_metric' RETURNING VARCHAR2(30) NULL ON ERROR) primary_metric,
                 JSON_VALUE(c.metadata_json, '$.verdict' RETURNING VARCHAR2(30) NULL ON ERROR) verdict,
                 JSON_VALUE(c.metadata_json, '$.learning_class' RETURNING VARCHAR2(30) NULL ON ERROR) learning_class,
                 JSON_VALUE(c.metadata_json, '$.change_summary' RETURNING VARCHAR2(1000) NULL ON ERROR) change_summary,
                 JSON_VALUE(c.metadata_json, '$.before_buffer_gets' RETURNING NUMBER NULL ON ERROR) before_buffer_gets,
                 JSON_VALUE(c.metadata_json, '$.after_buffer_gets' RETURNING NUMBER NULL ON ERROR) after_buffer_gets,
                 JSON_VALUE(c.metadata_json, '$.before_elapsed_time_us' RETURNING NUMBER NULL ON ERROR) before_elapsed_time_us,
                 JSON_VALUE(c.metadata_json, '$.after_elapsed_time_us' RETURNING NUMBER NULL ON ERROR) after_elapsed_time_us,
                 CASE WHEN c.sql_fingerprint = :query_fp_match THEN 'Y' ELSE 'N' END AS matched_fingerprint
          FROM   asta_tuning_cases c
          -- Chunks remain searchable storage; UX result is deliberately one row per case.
          -- Legacy relation: JOIN asta_tuning_cases c ON c.case_id = ch.case_id
          WHERE  EXISTS (SELECT 1 FROM asta_tuning_case_chunks ch WHERE ch.case_id = c.case_id)
          AND    JSON_VALUE(c.metadata_json, '$.learning_class' RETURNING VARCHAR2(30) NULL ON ERROR) = 'POSITIVE_VERIFIED'
          ORDER  BY CASE WHEN c.sql_fingerprint = :query_fp_order THEN 0 ELSE 1 END,
                    c.created_at DESC,
                    c.case_id
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
    l_learning_class VARCHAR2(30);
    l_rejection_reason VARCHAR2(4000);
    l_safe_metadata CLOB;
    l_redacted_sql CLOB;
    l_report_ref CLOB;
  BEGIN
    l_case_id := validated_case_id(p_run_id);
    l_source_fingerprint := sql_fingerprint(p_sql);

    IF NOT object_exists('ASTA_TUNING_CASES')
       OR NOT object_exists('ASTA_TUNING_CASE_CHUNKS') THEN
      RETURN not_configured('SAVE_CASE', p_sql);
    END IF;

    l_learning_class := CASE
      WHEN json_vc(p_metadata_json, '$.learning_class') = 'POSITIVE_VERIFIED'
       AND json_vc(p_metadata_json, '$.verdict') = 'IMPROVED'
       AND json_vc(p_metadata_json, '$.optimizer_intent_status') = 'VERIFIED'
       AND json_vc(p_metadata_json, '$.result_digest_scope') = 'FULL_RESULT'
       AND json_vc(p_metadata_json, '$.equivalence_status') = 'VERIFIED'
       AND json_vc(p_metadata_json, '$.bind_stability_status') = 'VERIFIED'
       AND LOWER(json_vc(p_metadata_json, '$.all_representative_binds_passed')) = 'true'
       AND json_vc(p_metadata_json, '$.measurement_status') = 'ACCEPTED'
      THEN 'POSITIVE_VERIFIED'
      ELSE 'REJECTED_OBSERVATION'
    END;
    l_rejection_reason := CASE WHEN l_learning_class = 'POSITIVE_VERIFIED' THEN NULL ELSE
      json_vc(p_metadata_json, '$.verdict_reason', 'VECTOR_POSITIVE_GATE_INCOMPLETE') END;
    IF l_rejection_reason IS NOT NULL
       AND NOT REGEXP_LIKE(l_rejection_reason, '^[A-Z][A-Z0-9_:-]{0,127}$') THEN
      l_rejection_reason := 'REJECTION_REASON_REDACTED';
    END IF;
    IF REGEXP_LIKE(p_report_markdown, '^/api/asta/runs/[A-Za-z0-9][A-Za-z0-9_.:-]*/report$') THEN
      l_report_ref := p_report_markdown;
    END IF;
    l_safe_metadata := TO_CLOB(
      '{"learning_class":' || json_str(l_learning_class) ||
      ',"verdict":' || json_str(json_vc(p_metadata_json, '$.verdict')) ||
      ',"verdict_reason":' || json_str(CASE WHEN l_learning_class = 'POSITIVE_VERIFIED' THEN
        json_vc(p_metadata_json, '$.verdict_reason') ELSE l_rejection_reason END) ||
      ',"workload_type":' || json_str(json_vc(p_metadata_json, '$.workload_type')) ||
      ',"primary_metric":' || json_str(json_vc(p_metadata_json, '$.primary_metric')) ||
      ',"optimizer_intent_status":' || json_str(json_vc(p_metadata_json, '$.optimizer_intent_status')) ||
      ',"result_digest_scope":' || json_str(json_vc(p_metadata_json, '$.result_digest_scope')) ||
      ',"equivalence_status":' || json_str(json_vc(p_metadata_json, '$.equivalence_status')) ||
      ',"bind_stability_status":' || json_str(json_vc(p_metadata_json, '$.bind_stability_status')) ||
      ',"all_representative_binds_passed":' || json_str(json_vc(p_metadata_json, '$.all_representative_binds_passed')) ||
      ',"measurement_status":' || json_str(json_vc(p_metadata_json, '$.measurement_status')) ||
      ',"before_buffer_gets":' || json_str(json_vc(p_metadata_json, '$.before_buffer_gets')) ||
      ',"after_buffer_gets":' || json_str(json_vc(p_metadata_json, '$.after_buffer_gets')) ||
      ',"before_elapsed_time_us":' || json_str(json_vc(p_metadata_json, '$.before_elapsed_time_us')) ||
      ',"after_elapsed_time_us":' || json_str(json_vc(p_metadata_json, '$.after_elapsed_time_us')) ||
      ',"before_plan_hash_value":' || json_str(json_vc(p_metadata_json, '$.before_plan_hash_value')) ||
      ',"after_plan_hash_value":' || json_str(json_vc(p_metadata_json, '$.after_plan_hash_value')) ||
      ',"rewrite_type":' || json_str(json_vc(p_metadata_json, '$.rewrite_type')) || '}'
    );

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
    USING l_case_id, l_redacted_sql, l_redacted_sql, l_report_ref, l_safe_metadata, l_source_fingerprint;

    IF l_learning_class = 'POSITIVE_VERIFIED' THEN
      l_chunks_saved := l_chunks_saved + save_case_chunk(l_case_id, 'VERIFIED_OUTCOME',
        TO_CLOB('verdict=IMPROVED; intent=VERIFIED; equivalence=VERIFIED; binds=VERIFIED; measurement=ACCEPTED'));
      l_chunks_saved := l_chunks_saved + save_case_chunk(l_case_id, 'PLAN_EVIDENCE',
        TO_CLOB('plans=') || TO_CLOB(json_vc(l_safe_metadata, '$.before_plan_hash_value', '-')) ||
        TO_CLOB(' -> ') || TO_CLOB(json_vc(l_safe_metadata, '$.after_plan_hash_value', '-')));
      l_chunks_saved := l_chunks_saved + save_case_chunk(l_case_id, 'METRICS',
        TO_CLOB('buffer_gets=') || TO_CLOB(json_vc(l_safe_metadata, '$.before_buffer_gets', '-')) ||
        TO_CLOB(' -> ') || TO_CLOB(json_vc(l_safe_metadata, '$.after_buffer_gets', '-')) ||
        TO_CLOB('; elapsed_us=') || TO_CLOB(json_vc(l_safe_metadata, '$.before_elapsed_time_us', '-')) ||
        TO_CLOB(' -> ') || TO_CLOB(json_vc(l_safe_metadata, '$.after_elapsed_time_us', '-')));
    ELSE
      l_chunks_saved := l_chunks_saved + save_case_chunk(l_case_id, 'REJECTED_OBSERVATION',
        TO_CLOB('learning_class=REJECTED_OBSERVATION; gate evidence retained without SQL or bind literals'));
      l_chunks_saved := l_chunks_saved + save_case_chunk(l_case_id, 'REJECTION_REASON',
        TO_CLOB(l_rejection_reason));
    END IF;

    RETURN TO_CLOB(
      '{"status":"COMPLETED","code":"VECTOR_KB","operation":"SAVE_CASE","case_id":' ||
      json_str(l_case_id) ||
      ',"contract_version":"asta.v1"' ||
      ',"execution_boundary":"ADB_VECTOR_PLSQL"' ||
      ',"search_strategy":' || json_str(C_SEARCH_STRATEGY) ||
      ',"learning_class":' || json_str(l_learning_class) ||
      ',"rejection_reason":' || json_str(l_rejection_reason) ||
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
