-- db/adb/asta_llm_pkg.sql
-- DBMS_CLOUD_AI orchestration for ASTA. FastAPI must not build or call ASTA
-- LLM workflows locally.

CREATE OR REPLACE PACKAGE asta_llm_pkg AUTHID DEFINER AS
  FUNCTION build_tuning_prompt(
    p_sql                  IN CLOB,
    p_source_evidence_json IN CLOB,
    p_vector_json          IN CLOB,
    p_tuning_context_json  IN CLOB DEFAULT NULL
  ) RETURN CLOB;

  FUNCTION generate_tuning(
    p_sql                  IN CLOB,
    p_llm_profile          IN VARCHAR2,
    p_source_evidence_json IN CLOB,
    p_vector_json          IN CLOB,
    p_tuning_context_json  IN CLOB DEFAULT NULL,
    p_use_llm              IN VARCHAR2 DEFAULT 'Y'
  ) RETURN CLOB;

  FUNCTION generate_sql_only_tuning(
    p_sql                  IN CLOB,
    p_llm_profile          IN VARCHAR2,
    p_workload_type        IN VARCHAR2 DEFAULT 'OLTP',
    p_source_evidence_json IN CLOB DEFAULT NULL,
    p_vector_json          IN CLOB DEFAULT NULL,
    p_tuning_context_json  IN CLOB DEFAULT NULL,
    p_use_llm              IN VARCHAR2 DEFAULT 'Y',
    p_run_id               IN VARCHAR2 DEFAULT NULL
  ) RETURN CLOB;

  FUNCTION repair_sql_candidate(
    p_original_sql       IN CLOB,
    p_rejected_candidate IN CLOB,
    p_error_message      IN VARCHAR2,
    p_llm_profile        IN VARCHAR2,
    p_run_id             IN VARCHAR2 DEFAULT NULL,
    p_source_evidence_json IN CLOB DEFAULT NULL
  ) RETURN CLOB;

  FUNCTION final_review(
    p_before_after_json IN CLOB,
    p_llm_profile       IN VARCHAR2,
    p_use_llm           IN VARCHAR2 DEFAULT 'Y'
  ) RETURN CLOB;
END asta_llm_pkg;
/

CREATE OR REPLACE PACKAGE BODY asta_llm_pkg AS
  C_RESPONSE_CONTRACT       CONSTANT VARCHAR2(30) := 'JSON_ONLY';
  C_CANDIDATE_GUARD_POLICY  CONSTANT VARCHAR2(40) := 'SELECT_WITH_SINGLE_STATEMENT';

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

  FUNCTION validated_profile_name(p_profile_name IN VARCHAR2) RETURN VARCHAR2 IS
    l_profile_name VARCHAR2(128) := UPPER(TRIM(p_profile_name));
  BEGIN
    IF l_profile_name IS NULL
       OR NOT REGEXP_LIKE(l_profile_name, '^ASTA[A-Z0-9_$#.-]{0,124}$') THEN
      RAISE_APPLICATION_ERROR(-20003, 'ASTA_LLM: profile_name must start with ASTA');
    END IF;
    RETURN l_profile_name;
  END validated_profile_name;

  FUNCTION available_fallback_profile(
    p_primary_profile IN VARCHAR2,
    p_ordinal         IN PLS_INTEGER
  ) RETURN VARCHAR2 IS
    l_seen PLS_INTEGER := 0;
    l_primary VARCHAR2(128) := UPPER(TRIM(p_primary_profile));
  BEGIN
    IF NVL(p_ordinal, 0) < 1 THEN
      RETURN NULL;
    END IF;
    FOR r IN (
      SELECT UPPER(profile_name) profile_name
      FROM   user_cloud_ai_profiles
      WHERE  UPPER(profile_name) LIKE 'ASTA%'
      ORDER  BY CASE UPPER(profile_name)
                  -- GPT5.4 is currently the strongest fallback for failed SQL
                  -- generation/repair. Keep the caller's primary profile first
                  -- by excluding it below, then prefer GPT5.4 before the rest.
                  WHEN 'ASTA_GPT54_PROFILE' THEN 10
                  WHEN 'ASTA_GROK_REASONING_PROFILE' THEN 20
                  WHEN 'ASTA_GROK_GENAI_PROFILE' THEN 30
                  WHEN 'ASTA_GEMINI_PROFILE' THEN 40
                  WHEN 'ASTA_GPT52_PROFILE' THEN 50
                  WHEN 'ASTA_GPT51_PROFILE' THEN 60
                  WHEN 'ASTA_GPT54_MINI_PROFILE' THEN 70
                  WHEN 'ASTA_GPT54_NANO_PROFILE' THEN 80
                  ELSE 100
                END,
                UPPER(profile_name)
    ) LOOP
      IF r.profile_name <> l_primary THEN
        l_seen := l_seen + 1;
        IF l_seen = p_ordinal THEN
          RETURN r.profile_name;
        END IF;
      END IF;
    END LOOP;
    RETURN NULL;
  EXCEPTION
    WHEN OTHERS THEN
      RETURN NULL;
  END available_fallback_profile;

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
      l_chunk := DBMS_LOB.SUBSTR(p_val, 1000, l_offset);
      DBMS_LOB.WRITEAPPEND(p_out, LENGTH(l_chunk), l_chunk);
      l_offset := l_offset + 1000;
    END LOOP;
  END clob_app_clob;

  FUNCTION begin_llm_call_log(
    p_run_id       IN VARCHAR2,
    p_stage        IN VARCHAR2,
    p_attempt_no   IN PLS_INTEGER,
    p_profile_name IN VARCHAR2,
    p_prompt       IN CLOB
  ) RETURN NUMBER IS
    PRAGMA AUTONOMOUS_TRANSACTION;
    l_call_id NUMBER;
  BEGIN
    IF p_run_id IS NULL THEN
      RETURN NULL;
    END IF;

    INSERT INTO asta_llm_call_log(
      run_id, stage, attempt_no, profile_name, call_status,
      prompt_clob, prompt_chars, started_at
    ) VALUES (
      p_run_id, p_stage, p_attempt_no, p_profile_name, 'SENT',
      p_prompt, NVL(DBMS_LOB.GETLENGTH(p_prompt), 0), SYSTIMESTAMP
    )
    RETURNING call_id INTO l_call_id;
    COMMIT;
    RETURN l_call_id;
  EXCEPTION
    WHEN OTHERS THEN
      ROLLBACK;
      RETURN NULL;
  END begin_llm_call_log;

  PROCEDURE finish_llm_call_log(
    p_call_id       IN NUMBER,
    p_response      IN CLOB,
    p_call_status   IN VARCHAR2,
    p_error_code    IN NUMBER DEFAULT NULL,
    p_error_message IN VARCHAR2 DEFAULT NULL
  ) IS
    PRAGMA AUTONOMOUS_TRANSACTION;
  BEGIN
    IF p_call_id IS NULL THEN
      RETURN;
    END IF;

    UPDATE asta_llm_call_log
    SET    call_status = p_call_status,
           response_clob = p_response,
           response_chars = NVL(DBMS_LOB.GETLENGTH(p_response), 0),
           error_code = p_error_code,
           error_message = SUBSTR(p_error_message, 1, 4000),
           completed_at = SYSTIMESTAMP
    WHERE  call_id = p_call_id;
    COMMIT;
  EXCEPTION
    WHEN OTHERS THEN
      ROLLBACK;
  END finish_llm_call_log;

  PROCEDURE clob_app_limited(p_out IN OUT NOCOPY CLOB, p_val IN CLOB, p_max_chars IN PLS_INTEGER) IS
    l_offset  PLS_INTEGER := 1;
    l_len     PLS_INTEGER;
    l_limit   PLS_INTEGER;
    l_chunk   VARCHAR2(32767);
  BEGIN
    IF p_val IS NULL THEN
      RETURN;
    END IF;
    l_len := NVL(DBMS_LOB.GETLENGTH(p_val), 0);
    l_limit := LEAST(l_len, GREATEST(NVL(p_max_chars, 0), 0));
    WHILE l_offset <= l_limit LOOP
      l_chunk := DBMS_LOB.SUBSTR(p_val, LEAST(500, l_limit - l_offset + 1), l_offset);
      DBMS_LOB.WRITEAPPEND(p_out, LENGTH(l_chunk), l_chunk);
      l_offset := l_offset + 500;
    END LOOP;
    IF l_len > l_limit THEN
      clob_app(p_out, CHR(10));
      clob_app(p_out, '[ASTA_FIELD_EXCERPT original_chars=');
      clob_app(p_out, TO_CHAR(l_len));
      clob_app(p_out, ' kept_chars=');
      clob_app(p_out, TO_CHAR(l_limit));
      clob_app(p_out, ']');
      clob_app(p_out, CHR(10));
    END IF;
  END clob_app_limited;

  PROCEDURE clob_app_json_str(p_out IN OUT NOCOPY CLOB, p_val IN CLOB);

  FUNCTION json_vc(p_json IN CLOB, p_path IN VARCHAR2, p_default IN VARCHAR2 DEFAULT NULL) RETURN VARCHAR2 IS
    l_val VARCHAR2(32767);
  BEGIN
    CASE p_path
      WHEN '$.status' THEN
        SELECT JSON_VALUE(p_json, '$.status' RETURNING VARCHAR2(32767) NULL ON ERROR) INTO l_val FROM dual;
      WHEN '$.execution_boundary' THEN
        SELECT JSON_VALUE(p_json, '$.execution_boundary' RETURNING VARCHAR2(32767) NULL ON ERROR) INTO l_val FROM dual;
      WHEN '$.evidence_method' THEN
        SELECT JSON_VALUE(p_json, '$.evidence_method' RETURNING VARCHAR2(32767) NULL ON ERROR) INTO l_val FROM dual;
      WHEN '$.row_count' THEN
        SELECT JSON_VALUE(p_json, '$.row_count' RETURNING VARCHAR2(32767) NULL ON ERROR) INTO l_val FROM dual;
      WHEN '$.last_output_rows' THEN
        SELECT JSON_VALUE(p_json, '$.last_output_rows' RETURNING VARCHAR2(32767) NULL ON ERROR) INTO l_val FROM dual;
      WHEN '$.last_cr_buffer_gets' THEN
        SELECT JSON_VALUE(p_json, '$.last_cr_buffer_gets' RETURNING VARCHAR2(32767) NULL ON ERROR) INTO l_val FROM dual;
      WHEN '$.last_cu_buffer_gets' THEN
        SELECT JSON_VALUE(p_json, '$.last_cu_buffer_gets' RETURNING VARCHAR2(32767) NULL ON ERROR) INTO l_val FROM dual;
      WHEN '$.last_disk_reads' THEN
        SELECT JSON_VALUE(p_json, '$.last_disk_reads' RETURNING VARCHAR2(32767) NULL ON ERROR) INTO l_val FROM dual;
      WHEN '$.last_elapsed_time_us' THEN
        SELECT JSON_VALUE(p_json, '$.last_elapsed_time_us' RETURNING VARCHAR2(32767) NULL ON ERROR) INTO l_val FROM dual;
      WHEN '$.advisor.status' THEN
        SELECT JSON_VALUE(p_json, '$.advisor.status' RETURNING VARCHAR2(32767) NULL ON ERROR) INTO l_val FROM dual;
      WHEN '$.advisor.report' THEN
        SELECT JSON_VALUE(p_json, '$.advisor.report' RETURNING VARCHAR2(32767) NULL ON ERROR) INTO l_val FROM dual;
      WHEN '$.search_strategy' THEN
        SELECT JSON_VALUE(p_json, '$.search_strategy' RETURNING VARCHAR2(32767) NULL ON ERROR) INTO l_val FROM dual;
      WHEN '$.xplan' THEN
        SELECT JSON_VALUE(p_json, '$.xplan' RETURNING VARCHAR2(32767) NULL ON ERROR) INTO l_val FROM dual;
      WHEN '$.plan_text' THEN
        SELECT JSON_VALUE(p_json, '$.plan_text' RETURNING VARCHAR2(32767) NULL ON ERROR) INTO l_val FROM dual;
      WHEN '$.comparison.status' THEN
        SELECT JSON_VALUE(p_json, '$.comparison.status' RETURNING VARCHAR2(32767) NULL ON ERROR) INTO l_val FROM dual;
      WHEN '$.comparison.row_count_matches' THEN
        SELECT JSON_VALUE(p_json, '$.comparison.row_count_matches' RETURNING VARCHAR2(32767) NULL ON ERROR) INTO l_val FROM dual;
      WHEN '$.comparison.output_rows_match' THEN
        SELECT JSON_VALUE(p_json, '$.comparison.output_rows_match' RETURNING VARCHAR2(32767) NULL ON ERROR) INTO l_val FROM dual;
      WHEN '$.comparison.before_row_count' THEN
        SELECT JSON_VALUE(p_json, '$.comparison.before_row_count' RETURNING VARCHAR2(32767) NULL ON ERROR) INTO l_val FROM dual;
      WHEN '$.comparison.after_row_count' THEN
        SELECT JSON_VALUE(p_json, '$.comparison.after_row_count' RETURNING VARCHAR2(32767) NULL ON ERROR) INTO l_val FROM dual;
      WHEN '$.comparison.before_buffer_gets' THEN
        SELECT JSON_VALUE(p_json, '$.comparison.before_buffer_gets' RETURNING VARCHAR2(32767) NULL ON ERROR) INTO l_val FROM dual;
      WHEN '$.comparison.after_buffer_gets' THEN
        SELECT JSON_VALUE(p_json, '$.comparison.after_buffer_gets' RETURNING VARCHAR2(32767) NULL ON ERROR) INTO l_val FROM dual;
      WHEN '$.comparison.buffer_gets_reduction_pct' THEN
        SELECT JSON_VALUE(p_json, '$.comparison.buffer_gets_reduction_pct' RETURNING VARCHAR2(32767) NULL ON ERROR) INTO l_val FROM dual;
      WHEN '$.comparison.before_disk_reads' THEN
        SELECT JSON_VALUE(p_json, '$.comparison.before_disk_reads' RETURNING VARCHAR2(32767) NULL ON ERROR) INTO l_val FROM dual;
      WHEN '$.comparison.after_disk_reads' THEN
        SELECT JSON_VALUE(p_json, '$.comparison.after_disk_reads' RETURNING VARCHAR2(32767) NULL ON ERROR) INTO l_val FROM dual;
      WHEN '$.comparison.before_elapsed_time_us' THEN
        SELECT JSON_VALUE(p_json, '$.comparison.before_elapsed_time_us' RETURNING VARCHAR2(32767) NULL ON ERROR) INTO l_val FROM dual;
      WHEN '$.comparison.after_elapsed_time_us' THEN
        SELECT JSON_VALUE(p_json, '$.comparison.after_elapsed_time_us' RETURNING VARCHAR2(32767) NULL ON ERROR) INTO l_val FROM dual;
      WHEN '$.candidate_sql' THEN
        SELECT JSON_VALUE(p_json, '$.candidate_sql' RETURNING VARCHAR2(32767) NULL ON ERROR) INTO l_val FROM dual;
      ELSE
        l_val := NULL;
    END CASE;
    RETURN NVL(l_val, p_default);
  EXCEPTION
    WHEN OTHERS THEN
      RETURN p_default;
  END json_vc;

  FUNCTION json_query_clob(p_json IN CLOB, p_path IN VARCHAR2) RETURN CLOB IS
    l_val CLOB;
  BEGIN
    IF p_path = '$.object_info' THEN
      SELECT JSON_QUERY(p_json, '$.object_info' RETURNING CLOB NULL ON ERROR) INTO l_val FROM dual;
    ELSIF p_path = '$.plan_text' THEN
      SELECT JSON_VALUE(p_json, '$.plan_text' RETURNING CLOB NULL ON ERROR) INTO l_val FROM dual;
    ELSE
      l_val := NULL;
    END IF;
    RETURN l_val;
  EXCEPTION
    WHEN OTHERS THEN
      RETURN NULL;
  END json_query_clob;

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

  FUNCTION structural_sql_key(p_sql IN CLOB) RETURN VARCHAR2 IS
    l_v           VARCHAR2(32767);
    l_out         VARCHAR2(32767);
    -- VARCHAR2 length is bytes in this ADB session. Reserve four bytes for a
    -- single AL32UTF8 character and flush the scanner chunk below its byte
    -- capacity so Korean SQL text cannot raise ORA-06502 during comparison.
    l_chunk       VARCHAR2(4096);
    l_char        VARCHAR2(4);
    l_next        VARCHAR2(4);
    l_state       VARCHAR2(20) := 'NORMAL';
    l_pos         PLS_INTEGER := 1;
    l_len         PLS_INTEGER;

    PROCEDURE append_char(p_char IN VARCHAR2) IS
    BEGIN
      l_chunk := l_chunk || p_char;
      IF LENGTH(l_chunk) >= 1000 THEN
        l_out := l_out || l_chunk;
        l_chunk := NULL;
      END IF;
    END append_char;
  BEGIN
    IF p_sql IS NULL THEN RETURN NULL; END IF;
    l_v := DBMS_LOB.SUBSTR(p_sql, 32767, 1);
    l_len := LENGTH(l_v);

    -- 주석과 optimizer hint만 다른 후보는 구조 변경이 아니다. 긴 SQL에
    -- 중첩 정규식을 적용하면 catastrophic backtracking이 발생할 수 있으므로
    -- 문자열/quoted identifier를 보존하는 단일 순회 scanner로 주석을 제거한다.
    WHILE l_pos <= l_len LOOP
      l_char := SUBSTR(l_v, l_pos, 1);
      l_next := CASE WHEN l_pos < l_len THEN SUBSTR(l_v, l_pos + 1, 1) END;

      IF l_state = 'NORMAL' THEN
        IF l_char = '''' THEN
          append_char(l_char);
          l_state := 'STRING';
        ELSIF l_char = '"' THEN
          append_char(l_char);
          l_state := 'QUOTED_IDENTIFIER';
        ELSIF l_char = '/' AND l_next = '*' THEN
          append_char(' ');
          l_state := 'BLOCK_COMMENT';
          l_pos := l_pos + 1;
        ELSIF l_char = '-' AND l_next = '-' THEN
          append_char(' ');
          l_state := 'LINE_COMMENT';
          l_pos := l_pos + 1;
        ELSE
          append_char(l_char);
        END IF;
      ELSIF l_state = 'STRING' THEN
        append_char(l_char);
        IF l_char = '''' THEN
          IF l_next = '''' THEN
            append_char(l_next);
            l_pos := l_pos + 1;
          ELSE
            l_state := 'NORMAL';
          END IF;
        END IF;
      ELSIF l_state = 'QUOTED_IDENTIFIER' THEN
        append_char(l_char);
        IF l_char = '"' THEN
          IF l_next = '"' THEN
            append_char(l_next);
            l_pos := l_pos + 1;
          ELSE
            l_state := 'NORMAL';
          END IF;
        END IF;
      ELSIF l_state = 'LINE_COMMENT' THEN
        IF l_char IN (CHR(10), CHR(13)) THEN
          append_char(l_char);
          l_state := 'NORMAL';
        END IF;
      ELSIF l_state = 'BLOCK_COMMENT' THEN
        IF l_char = '*' AND l_next = '/' THEN
          l_state := 'NORMAL';
          l_pos := l_pos + 1;
        ELSIF l_char IN (CHR(10), CHR(13)) THEN
          append_char(l_char);
        END IF;
      END IF;
      l_pos := l_pos + 1;
    END LOOP;
    l_out := l_out || l_chunk;
    RETURN LOWER(TRIM(REGEXP_REPLACE(l_out, '[[:space:]]+', ' ')));
  END structural_sql_key;

  FUNCTION leading_change_annotation_count(p_sql IN CLOB) RETURN PLS_INTEGER IS
    l_text VARCHAR2(32767);
  BEGIN
    IF p_sql IS NULL THEN RETURN 0; END IF;
    l_text := DBMS_LOB.SUBSTR(p_sql, 32767, 1);
    RETURN REGEXP_COUNT(l_text, '/\*[[:space:]]*ASTA_TUNING_CHANGE_[0-9]+:');
  EXCEPTION
    WHEN OTHERS THEN RETURN 0;
  END leading_change_annotation_count;

  FUNCTION prepend_generated_change_annotation(p_sql IN CLOB) RETURN CLOB IS
    l_out CLOB;
  BEGIN
    IF p_sql IS NULL THEN
      RETURN NULL;
    END IF;
    DBMS_LOB.CREATETEMPORARY(l_out, TRUE);
    clob_app(l_out, '/* ASTA_TUNING_CHANGE_1: 실행계획과 실행 통계에 근거한 구조 재작성 후보 -> 모델이 제안한 SQL 구조를 보존하고 ASTA가 설명 헤더를 보완 -> 후보 실행 및 Before/After 검증 예정 */' || CHR(10));
    clob_app_clob(l_out, p_sql);
    RETURN l_out;
  END prepend_generated_change_annotation;

  FUNCTION normalize_json_response(p_response IN CLOB) RETURN CLOB IS
    l_out        CLOB;
    l_fence_pos  PLS_INTEGER;
    l_start_pos  PLS_INTEGER;
    l_end_pos    PLS_INTEGER;
    l_amount     PLS_INTEGER;
  BEGIN
    IF p_response IS NULL THEN RETURN NULL; END IF;
    l_fence_pos := DBMS_LOB.INSTR(p_response, '```', 1, 1);
    IF l_fence_pos < 1 OR l_fence_pos > 2000 THEN RETURN p_response; END IF;
    l_start_pos := DBMS_LOB.INSTR(p_response, CHR(10), l_fence_pos, 1) + 1;
    l_end_pos := DBMS_LOB.INSTR(p_response, '```', l_start_pos, 1);
    IF l_start_pos <= 1 OR l_end_pos <= l_start_pos THEN RETURN p_response; END IF;
    l_amount := l_end_pos - l_start_pos;
    DBMS_LOB.CREATETEMPORARY(l_out, TRUE);
    DBMS_LOB.COPY(l_out, p_response, l_amount, 1, l_start_pos);
    RETURN l_out;
  END normalize_json_response;

  FUNCTION normalize_sql_response(p_response IN CLOB) RETURN CLOB IS
    l_text       VARCHAR2(32767);
    l_fence      PLS_INTEGER;
    l_line_end   PLS_INTEGER;
    l_close      PLS_INTEGER;
    l_select_pos PLS_INTEGER;
    l_with_pos   PLS_INTEGER;
    l_start      PLS_INTEGER;
    l_comment_end PLS_INTEGER;
    l_header     VARCHAR2(32767);
  BEGIN
    IF p_response IS NULL OR NVL(DBMS_LOB.GETLENGTH(p_response), 0) > 32767 THEN
      RETURN p_response;
    END IF;
    l_text := TRIM(DBMS_LOB.SUBSTR(p_response, 32767, 1));
    l_fence := INSTR(l_text, '```');
    IF l_fence > 0 THEN
      l_line_end := INSTR(l_text, CHR(10), l_fence);
      l_close := INSTR(l_text, '```', GREATEST(l_line_end + 1, l_fence + 3));
      IF l_line_end > 0 AND l_close > l_line_end THEN
        l_text := TRIM(SUBSTR(l_text, l_line_end + 1, l_close - l_line_end - 1));
      END IF;
    END IF;
    -- A required ASTA_TUNING_CHANGE header can itself contain words such as
    -- "with" or "select". Never mistake a keyword inside that comment for
    -- the executable SQL start.
    l_comment_end := CASE WHEN SUBSTR(l_text, 1, 2) = '/*' THEN INSTR(l_text, '*/', 3) ELSE 0 END;
    l_select_pos := REGEXP_INSTR(l_text, '(^|' || CHR(10) || ')[[:space:]]*SELECT[[:space:]]',
                                 CASE WHEN l_comment_end > 0 THEN l_comment_end + 2 ELSE 1 END,
                                 1, 0, 'i');
    l_with_pos := REGEXP_INSTR(l_text, '(^|' || CHR(10) || ')[[:space:]]*WITH[[:space:]]',
                               CASE WHEN l_comment_end > 0 THEN l_comment_end + 2 ELSE 1 END,
                               1, 0, 'i');
    IF l_select_pos = 0 AND l_with_pos = 0 THEN
      l_select_pos := REGEXP_INSTR(l_text, '(^|[[:space:]])SELECT[[:space:]]',
                                   CASE WHEN l_comment_end > 0 THEN l_comment_end + 2 ELSE 1 END,
                                   1, 0, 'i');
      l_with_pos := REGEXP_INSTR(l_text, '(^|[[:space:]])WITH[[:space:]]',
                                 CASE WHEN l_comment_end > 0 THEN l_comment_end + 2 ELSE 1 END,
                                 1, 0, 'i');
    END IF;
    IF l_with_pos > 0 AND (l_select_pos = 0 OR l_with_pos < l_select_pos) THEN
      l_start := l_with_pos;
    ELSE
      l_start := l_select_pos;
    END IF;
    IF l_comment_end > 0 AND l_start > l_comment_end THEN
      -- preserve the validated leading change annotation, but drop non-SQL prose between the validated header and executable SQL.
      -- INSTR returns the position of '*' in the closing '*/'. Include the
      -- following slash or the normalized annotation becomes malformed.
      l_header := RTRIM(SUBSTR(l_text, 1, l_comment_end + 1));
      l_text := l_header || CHR(10) || LTRIM(SUBSTR(l_text, l_start));
      l_start := 1;
    END IF;
    IF l_start > 1 THEN l_text := LTRIM(SUBSTR(l_text, l_start)); END IF;
    IF SUBSTR(RTRIM(l_text), -1) = ';' THEN
      l_text := RTRIM(SUBSTR(RTRIM(l_text), 1, LENGTH(RTRIM(l_text)) - 1));
    END IF;
    RETURN TO_CLOB(l_text);
  END normalize_sql_response;

  PROCEDURE append_json_pair_vc(p_out IN OUT NOCOPY CLOB, p_key IN VARCHAR2, p_val IN VARCHAR2, p_first IN OUT BOOLEAN) IS
  BEGIN
    IF NOT p_first THEN
      clob_app(p_out, ',');
    END IF;
    p_first := FALSE;
    clob_app(p_out, json_str(p_key));
    clob_app(p_out, ':');
    clob_app(p_out, json_str(p_val));
  END append_json_pair_vc;

  PROCEDURE append_json_pair_num(p_out IN OUT NOCOPY CLOB, p_key IN VARCHAR2, p_val IN VARCHAR2, p_first IN OUT BOOLEAN) IS
  BEGIN
    IF p_val IS NULL THEN
      RETURN;
    END IF;
    IF NOT p_first THEN
      clob_app(p_out, ',');
    END IF;
    p_first := FALSE;
    clob_app(p_out, json_str(p_key));
    clob_app(p_out, ':');
    clob_app(p_out, p_val);
  END append_json_pair_num;

  FUNCTION compact_source_evidence(p_json IN CLOB) RETURN CLOB IS
    l_out   CLOB;
    l_first BOOLEAN := TRUE;
  BEGIN
    DBMS_LOB.CREATETEMPORARY(l_out, TRUE);
    clob_app(l_out, '{');
    append_json_pair_vc(l_out, 'status', json_vc(p_json, '$.status'), l_first);
    append_json_pair_vc(l_out, 'execution_boundary', json_vc(p_json, '$.execution_boundary'), l_first);
    append_json_pair_vc(l_out, 'evidence_method', json_vc(p_json, '$.evidence_method'), l_first);
    append_json_pair_vc(l_out, 'source_sql_executed', json_vc(p_json, '$.source_sql_executed'), l_first);
    append_json_pair_vc(l_out, 'plan_kind', json_vc(p_json, '$.plan_kind'), l_first);
    append_json_pair_num(l_out, 'row_count', json_vc(p_json, '$.row_count'), l_first);
    append_json_pair_num(l_out, 'last_output_rows', json_vc(p_json, '$.last_output_rows'), l_first);
    append_json_pair_num(l_out, 'last_cr_buffer_gets', json_vc(p_json, '$.last_cr_buffer_gets'), l_first);
    append_json_pair_num(l_out, 'last_cu_buffer_gets', json_vc(p_json, '$.last_cu_buffer_gets'), l_first);
    append_json_pair_num(l_out, 'last_disk_reads', json_vc(p_json, '$.last_disk_reads'), l_first);
    append_json_pair_num(l_out, 'last_elapsed_time_us', json_vc(p_json, '$.last_elapsed_time_us'), l_first);
    append_json_pair_vc(l_out, 'advisor_status', json_vc(p_json, '$.advisor.status'), l_first);
    append_json_pair_vc(l_out, 'advisor_report_excerpt', SUBSTR(json_vc(p_json, '$.advisor.report'), 1, 1500), l_first);
    append_json_pair_vc(l_out, 'xplan_excerpt', DBMS_LOB.SUBSTR(json_query_clob(p_json, '$.plan_text'), 5000, 1), l_first);
    append_json_pair_vc(l_out, 'object_info_excerpt', DBMS_LOB.SUBSTR(json_query_clob(p_json, '$.object_info'), 2500, 1), l_first);
    clob_app(l_out, '}');
    RETURN l_out;
  END compact_source_evidence;

  -- Provide only authoritative base-object column names and lightweight type
  -- metadata to SQL generation/repair. Exclude statistics and indexes, and
  -- keep the JSON bounded so long SQL prompts do not grow without limit.
  FUNCTION compact_column_dictionary(p_source_json IN CLOB) RETURN CLOB IS
    l_out           CLOB;
    l_prev_owner    VARCHAR2(128);
    l_prev_table    VARCHAR2(128);
    l_first_table   BOOLEAN := TRUE;
    l_first_column  BOOLEAN := TRUE;
    l_table_open    BOOLEAN := FALSE;
    l_table_count   PLS_INTEGER := 0;
    l_column_count  PLS_INTEGER := 0;
    l_truncated     VARCHAR2(1) := 'N';
  BEGIN
    DBMS_LOB.CREATETEMPORARY(l_out, TRUE);
    clob_app(l_out, '{"status":"COMPLETED","source":"SOURCE_OBJECT_INFO_COLUMNS","tables":[');

    FOR r IN (
      SELECT owner_name, table_name, column_ordinal,
             column_name, data_type, nullable
        FROM JSON_TABLE(
               p_source_json,
               '$.object_info.table_stats[*]'
               COLUMNS(
                 owner_name VARCHAR2(128) PATH '$.owner',
                 table_name VARCHAR2(128) PATH '$.table_name',
                 NESTED PATH '$.columns[*]'
                   COLUMNS(
                     column_ordinal FOR ORDINALITY,
                     column_name VARCHAR2(128) PATH '$.column_name',
                     data_type VARCHAR2(128) PATH '$.data_type',
                     nullable VARCHAR2(1) PATH '$.nullable'
                   )
               )
             )
       WHERE owner_name IS NOT NULL
         AND table_name IS NOT NULL
       ORDER BY owner_name, table_name, column_ordinal
    ) LOOP
      IF l_prev_owner IS NULL
         OR l_prev_owner <> r.owner_name
         OR l_prev_table <> r.table_name THEN
        IF l_table_count >= 30 THEN
          l_truncated := 'Y';
          EXIT;
        END IF;
        IF l_table_open THEN
          clob_app(l_out, ']}');
        END IF;
        IF NOT l_first_table THEN clob_app(l_out, ','); END IF;
        l_first_table := FALSE;
        l_first_column := TRUE;
        l_table_open := TRUE;
        l_table_count := l_table_count + 1;
        l_prev_owner := r.owner_name;
        l_prev_table := r.table_name;
        clob_app(l_out, '{"owner":' || json_str(r.owner_name) ||
          ',"table_name":' || json_str(r.table_name) || ',"columns":[');
      END IF;

      IF r.column_name IS NOT NULL THEN
        IF l_column_count >= 600 THEN
          l_truncated := 'Y';
          EXIT;
        END IF;
        IF NOT l_first_column THEN clob_app(l_out, ','); END IF;
        l_first_column := FALSE;
        l_column_count := l_column_count + 1;
        clob_app(l_out, '{"column_name":' || json_str(r.column_name) ||
          ',"data_type":' || json_str(r.data_type) ||
          ',"nullable":' || json_str(r.nullable) || '}');
      END IF;
    END LOOP;

    IF l_table_open THEN clob_app(l_out, ']}'); END IF;
    clob_app(l_out, '],"table_count":' || TO_CHAR(l_table_count) ||
      ',"column_count":' || TO_CHAR(l_column_count) ||
      ',"limits":{"max_tables":30,"max_columns":600}' ||
      ',"truncated":' || CASE WHEN l_truncated = 'Y' THEN 'true' ELSE 'false' END || '}');
    RETURN l_out;
  EXCEPTION
    WHEN OTHERS THEN
      RETURN TO_CLOB('{"status":"FAILED","source":"SOURCE_OBJECT_INFO_COLUMNS","tables":[]}');
  END compact_column_dictionary;

  FUNCTION compact_source_metrics(p_json IN CLOB) RETURN CLOB IS
    l_out   CLOB;
    l_first BOOLEAN := TRUE;
  BEGIN
    DBMS_LOB.CREATETEMPORARY(l_out, TRUE);
    clob_app(l_out, '{');
    append_json_pair_vc(l_out, 'status', json_vc(p_json, '$.status'), l_first);
    append_json_pair_vc(l_out, 'execution_boundary', json_vc(p_json, '$.execution_boundary'), l_first);
    append_json_pair_num(l_out, 'row_count', json_vc(p_json, '$.row_count'), l_first);
    append_json_pair_num(l_out, 'last_output_rows', json_vc(p_json, '$.last_output_rows'), l_first);
    append_json_pair_num(l_out, 'last_cr_buffer_gets', json_vc(p_json, '$.last_cr_buffer_gets'), l_first);
    append_json_pair_num(l_out, 'last_cu_buffer_gets', json_vc(p_json, '$.last_cu_buffer_gets'), l_first);
    append_json_pair_num(l_out, 'last_disk_reads', json_vc(p_json, '$.last_disk_reads'), l_first);
    append_json_pair_num(l_out, 'last_elapsed_time_us', json_vc(p_json, '$.last_elapsed_time_us'), l_first);
    clob_app(l_out, '}');
    RETURN l_out;
  END compact_source_metrics;

  FUNCTION prompt_mode(p_context_json IN CLOB) RETURN VARCHAR2 IS
    l_mode VARCHAR2(1);
  BEGIN
    SELECT UPPER(JSON_VALUE(p_context_json, '$.prompt_mode' RETURNING VARCHAR2(1) NULL ON ERROR))
    INTO l_mode
    FROM dual;
    IF l_mode NOT IN ('A', 'B', 'C') THEN
      RETURN 'C';
    END IF;
    RETURN l_mode;
  EXCEPTION
    WHEN OTHERS THEN
      RETURN 'C';
  END prompt_mode;

  FUNCTION compact_vector_evidence(p_json IN CLOB) RETURN CLOB IS
    l_out CLOB;
  BEGIN
    DBMS_LOB.CREATETEMPORARY(l_out, TRUE);
    IF p_json IS NULL OR (
         DBMS_LOB.INSTR(p_json, '"verdict":"IMPROVED"', 1, 1) = 0
         AND DBMS_LOB.INSTR(p_json, '"verdict": "IMPROVED"', 1, 1) = 0
       ) THEN
      clob_app(l_out, '{"status":"SKIPPED","reason":"NO_POSITIVE_VECTOR_CASES"}');
      RETURN l_out;
    END IF;
    clob_app(l_out, '{"status":');
    clob_app(l_out, json_str(json_vc(p_json, '$.status')));
    clob_app(l_out, ',"search_strategy":');
    clob_app(l_out, json_str(json_vc(p_json, '$.search_strategy')));
    clob_app(l_out, ',"top_k_excerpt":');
    clob_app_json_str(l_out, TO_CLOB(DBMS_LOB.SUBSTR(p_json, 3000, 1)));
    clob_app(l_out, '}');
    RETURN l_out;
  END compact_vector_evidence;

  FUNCTION compact_verified_history_references(
    p_json          IN CLOB,
    p_workload_type IN VARCHAR2
  ) RETURN CLOB IS
    l_cases CLOB;
    l_out   CLOB;
  BEGIN
    DBMS_LOB.CREATETEMPORARY(l_out, TRUE);
    IF p_json IS NULL THEN
      RETURN TO_CLOB('{"status":"SKIPPED","reason":"NO_VERIFIED_HISTORY_REFERENCES","cases":[]}');
    END IF;
    SELECT COALESCE(
      JSON_ARRAYAGG(
        JSON_OBJECT(
          'case_id' VALUE case_id,
          'matched_fingerprint' VALUE matched_fingerprint,
          'workload_type' VALUE workload_type,
          'primary_metric' VALUE primary_metric,
          'change_summary' VALUE change_summary,
          'before_buffer_gets' VALUE before_buffer_gets,
          'after_buffer_gets' VALUE after_buffer_gets,
          'before_elapsed_time_us' VALUE before_elapsed_time_us,
          'after_elapsed_time_us' VALUE after_elapsed_time_us
          RETURNING CLOB
        ) RETURNING CLOB
      ), TO_CLOB('[]')
    ) INTO l_cases
    FROM JSON_TABLE(p_json, '$.cases[*]'
      COLUMNS (
        case_id VARCHAR2(64) PATH '$.case_id',
        matched_fingerprint VARCHAR2(1) PATH '$.matched_fingerprint',
        workload_type VARCHAR2(30) PATH '$.workload_type',
        primary_metric VARCHAR2(30) PATH '$.primary_metric',
        change_summary VARCHAR2(2000) PATH '$.change_summary',
        before_buffer_gets NUMBER PATH '$.before_buffer_gets',
        after_buffer_gets NUMBER PATH '$.after_buffer_gets',
        before_elapsed_time_us NUMBER PATH '$.before_elapsed_time_us',
        after_elapsed_time_us NUMBER PATH '$.after_elapsed_time_us',
        verdict VARCHAR2(30) PATH '$.verdict',
        learning_class VARCHAR2(30) PATH '$.learning_class'
      )
    )
    WHERE verdict = 'IMPROVED'
      AND learning_class = 'POSITIVE_VERIFIED'
      AND UPPER(workload_type) = UPPER(p_workload_type);
    clob_app(l_out, '{"status":"REFERENCE_ONLY","policy":"VERIFIED_HISTORY_PATTERN_REFERENCE_NO_RAW_SQL","cases":');
    clob_app_clob(l_out, l_cases);
    clob_app(l_out, '}');
    RETURN l_out;
  EXCEPTION
    WHEN OTHERS THEN
      RETURN TO_CLOB('{"status":"SKIPPED","reason":"VERIFIED_HISTORY_REFERENCE_UNAVAILABLE","cases":[]}');
  END compact_verified_history_references;

  FUNCTION compact_before_after(p_json IN CLOB) RETURN CLOB IS
    l_out CLOB;
    l_first BOOLEAN := TRUE;
  BEGIN
    DBMS_LOB.CREATETEMPORARY(l_out, TRUE);
    clob_app(l_out, '{');
    append_json_pair_vc(l_out, 'comparison', json_vc(p_json, '$.comparison.status'), l_first);
    append_json_pair_vc(l_out, 'row_count_matches', json_vc(p_json, '$.comparison.row_count_matches'), l_first);
    append_json_pair_vc(l_out, 'output_rows_match', json_vc(p_json, '$.comparison.output_rows_match'), l_first);
    append_json_pair_num(l_out, 'before_row_count', json_vc(p_json, '$.comparison.before_row_count'), l_first);
    append_json_pair_num(l_out, 'after_row_count', json_vc(p_json, '$.comparison.after_row_count'), l_first);
    append_json_pair_num(l_out, 'before_buffer_gets', json_vc(p_json, '$.comparison.before_buffer_gets'), l_first);
    append_json_pair_num(l_out, 'after_buffer_gets', json_vc(p_json, '$.comparison.after_buffer_gets'), l_first);
    append_json_pair_num(l_out, 'buffer_gets_reduction_pct', json_vc(p_json, '$.comparison.buffer_gets_reduction_pct'), l_first);
    append_json_pair_num(l_out, 'before_disk_reads', json_vc(p_json, '$.comparison.before_disk_reads'), l_first);
    append_json_pair_num(l_out, 'after_disk_reads', json_vc(p_json, '$.comparison.after_disk_reads'), l_first);
    append_json_pair_num(l_out, 'before_elapsed_time_us', json_vc(p_json, '$.comparison.before_elapsed_time_us'), l_first);
    append_json_pair_num(l_out, 'after_elapsed_time_us', json_vc(p_json, '$.comparison.after_elapsed_time_us'), l_first);
    append_json_pair_vc(l_out, 'candidate_sql_excerpt', json_vc(p_json, '$.candidate_sql'), l_first);
    append_json_pair_vc(l_out, 'user_notes', json_vc(p_json, '$.tuning_context.user_notes'), l_first);
    append_json_pair_vc(l_out, 'user_context_source', json_vc(p_json, '$.tuning_context.source'), l_first);
    append_json_pair_vc(l_out, 'xplan_policy', 'Do not reproduce raw DBMS_XPLAN tables in the final report. Summarize key operations only; full before/after plan_text is preserved in runtime_evidence.plan_text and after_evidence.plan_text artifacts.', l_first);
    clob_app(l_out, '}');
    RETURN l_out;
  END compact_before_after;

  PROCEDURE clob_app_json_str(p_out IN OUT NOCOPY CLOB, p_val IN CLOB) IS
    l_offset  PLS_INTEGER := 1;
    l_len     PLS_INTEGER;
    l_chunk   VARCHAR2(32767);
    l_escaped VARCHAR2(12000);
  BEGIN
    IF p_val IS NULL THEN
      clob_app(p_out, 'null');
      RETURN;
    END IF;

    l_len := NVL(DBMS_LOB.GETLENGTH(p_val), 0);
    clob_app(p_out, '"');
    WHILE l_offset <= l_len LOOP
      l_chunk := DBMS_LOB.SUBSTR(p_val, 1000, l_offset);
      l_escaped := REPLACE(l_chunk, '\', '\\');
      l_escaped := REPLACE(l_escaped, '"', '\"');
      l_escaped := REPLACE(l_escaped, CHR(8), '\b');
      l_escaped := REPLACE(l_escaped, CHR(9), '\t');
      l_escaped := REPLACE(l_escaped, CHR(10), '\n');
      l_escaped := REPLACE(l_escaped, CHR(13), '\r');
      l_escaped := REPLACE(l_escaped, CHR(12), '\f');
      DBMS_LOB.WRITEAPPEND(p_out, LENGTH(l_escaped), l_escaped);
      l_offset := l_offset + 1000;
    END LOOP;
    clob_app(p_out, '"');
  END clob_app_json_str;

  FUNCTION build_tuning_prompt(
    p_sql                  IN CLOB,
    p_source_evidence_json IN CLOB,
    p_vector_json          IN CLOB,
    p_tuning_context_json  IN CLOB DEFAULT NULL
  ) RETURN CLOB IS
    l_prompt CLOB;
    l_mode   VARCHAR2(1) := prompt_mode(p_tuning_context_json);
  BEGIN
    DBMS_LOB.CREATETEMPORARY(l_prompt, TRUE);
    clob_app(l_prompt, 'Semantic equivalence is mandatory: preserve the output column order, aliases and datatypes; preserve row grain, duplicate multiplicity, outer-join null extension, GROUP BY keys, analytic PARTITION BY keys, and scalar-aggregate empty-input behavior. Pre-aggregate only at the original correlation or join-key grain.' || CHR(10));
    clob_app(l_prompt, 'Identifier safety is mandatory: use only base-table column names present for that same source in the input SQL or supplied object metadata; never guess abbreviated column names. Every introduced CTE or inline view must project each column referenced downstream from a valid source expression.' || CHR(10));
    clob_app(l_prompt, 'CTE interface preservation is mandatory: for every existing CTE or inline view touched by the rewrite, keep each original output column under its original alias so every unchanged downstream alias.column reference remains valid. Add derived values under new aliases instead of renaming or replacing an original output column; before returning, reject the candidate if any unchanged downstream reference (for example XX.SALE_QTY) is absent from that producer projection.' || CHR(10));
    clob_app(l_prompt, 'Projection safety is mandatory: never use SELECT * in a UNION, INTERSECT, or MINUS; spell out the same number of expressions in the same semantic order with compatible datatypes in every branch, using typed zero or NULL placeholders where a measure is absent. Before returning candidate_sql, build an ordinal projection ledger for each set-operation branch after expanding every wildcard and reject the candidate unless every branch count exactly matches the first branch; this preflight must prevent ORA-01789. If the selected rewrite target is outside a set expression, copy that entire set expression verbatim instead of rebuilding its branches. After joining sources, qualify every referenced column with its source alias.' || CHR(10));
    clob_app(l_prompt, 'Executable completeness preflight is mandatory: expand every omitted section and never emit ellipses (... or …), TODO text, "unchanged" shorthand, or placeholder comments in candidate_sql. Then trace every alias.column reference in SELECT, JOIN, WHERE, GROUP BY, HAVING, and ORDER BY to a column projected by that exact CTE or inline-view alias before returning the SQL.' || CHR(10));
    clob_app(l_prompt, 'Correlated-aggregate lift safety is mandatory: build each helper CTE only from the original inner tables and LEFT JOIN it from the original immediate outer consumer. Preserve every non-wildcard correlation key. When an outer DECODE makes ''-'' match all inner COLOR_CD or SIZE_CD values, preserve the scalar MIN/SUM semantics by pre-aggregating every required exact and wildcard grain with GROUPING SETS plus GROUPING flags, then ANSI LEFT JOIN exactly one matching aggregate row. Never join detail-grain helper rows through wildcard predicates because that multiplies consumer rows. Never attach helper aliases with legacy (+) predicates; use ANSI LEFT JOINs, isolating pre-existing (+) joins in an unchanged inline view first when necessary, so multiple helpers cannot raise ORA-01416. Never join a helper producer to a pre-existing CTE as a substitute for the immediate outer consumer; return no candidate when this localized lift is not possible.' || CHR(10));
    clob_app(l_prompt, 'Legacy outer-join compatibility preflight is mandatory: if the query block where a helper would be joined contains any (+) predicate, add no ANSI JOIN to that block. Instead, put the original immediate consumer (for example XX) and its helper ANSI LEFT JOINs in a new nested inline view that projects the consumer''s original columns plus only the replacement aggregate values; leave the parent comma-separated sources and every (+) predicate verbatim. Immediately before returning candidate_sql, inspect every query block independently and reject the candidate if one block contains both an ANSI JOIN keyword and a (+) predicate, because Oracle raises ORA-25156 even when the ANSI-joined sources precede a comma-separated legacy outer join. Return no candidate if this syntax isolation cannot be completed.' || CHR(10));
    clob_app(l_prompt, 'Structural effectiveness preflight is mandatory: candidate_sql must actually implement its stated rewrite and eliminate at least one repeated base-table access, correlated subquery execution, UNION branch scan, or equivalent expensive operation. Adding or removing only a redundant predicate, optimizer hint, or comment is not a structural rewrite; return no candidate when no safe effective rewrite can be completed.' || CHR(10));
    clob_app(l_prompt, 'Evidence focus is mandatory when XPLAN is supplied: rank operations by measured Buffers and A-Time, using Starts to identify repeated work, and rewrite exactly one pattern containing the dominant measured operation. Do not select a low-buffer scalar subquery or another cheap operation while a different operation dominates measured work; return no candidate if that dominant pattern cannot be rewritten safely.' || CHR(10));
    clob_app(l_prompt, 'Dominant correlated anti-existence restart: when a correlated NOT EXISTS producer is the dominant repeated operation, materialize one DISTINCT helper CTE containing only its original correlation keys and inner predicates, then replace only that NOT EXISTS producer with an anti-existence check against the helper from the same immediate consumer. Preserve NOT EXISTS and NULL semantics verbatim. Treat unrelated scalar aggregates, UNION ALL branches, and legacy (+) joins in other query blocks as out of scope, not as reasons to refuse this isolated rewrite.' || CHR(10));
    IF NVL(DBMS_LOB.GETLENGTH(p_sql), 0) >= 12000 THEN
      clob_app(l_prompt, 'Long-SQL rewrite boundary: target exactly one repeated-access pattern. This is a semantic scope, not a one-CTE or one-query-block edit limit: within only the producer and consumer blocks participating in that pattern, add the helper CTEs and change projections, joins, GROUP BY expressions, and correlated references required to replace every occurrence safely. Preserve the original correlation or join-key grain and project every key needed downstream. Other repeated-access patterns elsewhere do not block an isolated rewrite: correlated scalar MIN or SUM lookups may be pre-aggregated by their existing correlation keys and LEFT JOINed only into their immediate consumer while unrelated UNION ALL producers remain unchanged. Copy every unrelated query block, CTE, UNION ALL branch, join, predicate, and select-list expression verbatim from the input. Do not decompose or rebuild the full statement into a new CTE architecture. In particular, do not change any UNION ALL branch projection count or reference a grouping key after it has been removed by aggregation.' || CHR(10));
    END IF;
    IF l_mode IN ('A', 'B') THEN
      clob_app(l_prompt, '다음 Oracle SQL을 더 효율적인 단일 SELECT/WITH SQL로 재작성하세요. SQL 의미를 유지하세요.' || CHR(10) || CHR(10));
      clob_app_clob(l_prompt, p_sql);
      IF l_mode = 'B' THEN
        clob_app(l_prompt, CHR(10) || CHR(10) || '참고할 핵심 실행 메트릭(JSON):' || CHR(10));
        clob_app_clob(l_prompt, compact_source_metrics(p_source_evidence_json));
      END IF;
      IF p_tuning_context_json IS NOT NULL THEN
        clob_app(l_prompt, CHR(10) || CHR(10) || 'User tuning context JSON: workload_type, optimization_goal, and user_notes are mandatory rewrite objectives.' || CHR(10));
        clob_app_clob(l_prompt, p_tuning_context_json);
      END IF;
      RETURN l_prompt;
    END IF;
    clob_app(l_prompt, 'You are ASTA running inside Oracle ADB PL/SQL.' || CHR(10));
    clob_app(l_prompt, 'Return concise JSON with candidate_sql, change_reason (Korean), change_summary (Korean), change_location (Korean), rationale (Korean), and risk_notes (Korean).' || CHR(10));
    clob_app(l_prompt, 'All explanatory text fields must be written in Korean. Keep only SQL identifiers, Oracle keywords, object names, and metric field names in their original form.' || CHR(10));
    clob_app(l_prompt, 'Return JSON only; do not wrap the response in Markdown fences.' || CHR(10));
    clob_app(l_prompt, 'candidate_sql must be a single safe Oracle SELECT or WITH statement; do not return DML, DDL, PL/SQL, or statement terminators.' || CHR(10));
    clob_app(l_prompt, 'candidate_sql must not include a semicolon or standalone SQL*Plus slash terminator.' || CHR(10));
    clob_app(l_prompt, 'Prepend candidate_sql with a SQL comment block: -- change_reason: <Korean>, -- change_summary: <Korean>, -- change_location: <Korean>.' || CHR(10));
    clob_app(l_prompt, 'Do not auto-apply DDL, SQL Profiles, or DBMS_STATS; tuning recommendation only.' || CHR(10));
    IF l_mode <> 'A' THEN
      clob_app(l_prompt, 'If disk_reads > 0 in supplied metrics, prioritize buffer_gets reduction over elapsed_time improvement.' || CHR(10));
    END IF;
    clob_app(l_prompt, 'Use only the supplied input for prompt mode ' || l_mode || '; do not invent runtime metrics.' || CHR(10));
    clob_app(l_prompt, 'If User tuning context JSON contains user_notes, treat it as a hard optimization objective, not an optional hint. Use it to focus rewrite choices and mention how it affected or did not affect the recommendation. Evidence wins when user_notes conflicts with measured runtime evidence.' || CHR(10));
    IF l_mode = 'C' THEN
      clob_app(l_prompt, 'If user_notes asks to reduce reads/accesses of a specific table, explicitly inspect the SQL text and Source XPLAN for repeated accesses to that table. Prefer a candidate_sql that reduces that table access count, or explain why such a rewrite is impossible in candidate_error/risk_notes.' || CHR(10));
    ELSE
      clob_app(l_prompt, 'If user_notes asks to reduce reads/accesses of a specific table, inspect the SQL text for repeated accesses to that table and prefer a structural rewrite that reduces them.' || CHR(10));
    END IF;
    clob_app(l_prompt, 'Recognize these rewrite families and apply them when the input SQL matches:' || CHR(10));
    clob_app(l_prompt, '- CORRELATED_SCALAR_SUBQUERIES_REPEATING_FACT_TABLE: replace repeated correlated scalar subqueries with a fact-table pre-aggregation CTE grouped by the correlation key, then LEFT JOIN it to the driving table. For year/count metrics, join the dimension once and use conditional aggregation.' || CHR(10));
    clob_app(l_prompt, '- UNION_ALL_REPEATED_FACT_TABLE_AGGREGATION: replace multiple UNION ALL aggregate branches over the same fact table with one base CTE/fact scan plus conditional aggregation, then unpivot/UNION the already-computed aggregate row only if the output shape requires buckets.' || CHR(10));
    clob_app(l_prompt, '- REPEATED_EXISTS_OR_SEMIJOIN_FACT_PATTERN: preserve EXISTS semantics with semi-joins or DISTINCT key CTEs so joins do not multiply fact rows.' || CHR(10));
    clob_app(l_prompt, '- CORRELATED_EXISTS_VIEW_RESTART: when XPLAN shows that a view or subquery below EXISTS or NOT EXISTS has Starts greater than 1 and dominates measured Buffers or A-Time, evaluate that producer once in a DISTINCT CTE containing only the original correlation keys and inner predicates, then semi-join or anti-join it only from the immediate consumer. Preserve EXISTS versus NOT EXISTS and NULL semantics, and leave every unrelated query block unchanged.' || CHR(10));
    clob_app(l_prompt, 'When applying these rewrites, preserve output columns, ordering semantics, NULL behavior, COUNT(DISTINCT ...) semantics, and aggregate results. Do not replace a table-read reduction objective with mere hints unless a structural rewrite is impossible.' || CHR(10));
    IF l_mode = 'C' THEN
      clob_app(l_prompt, 'Object metadata JSON for table/column statistics and indexes is included in Source evidence as object_info_excerpt; use it to reason about stale stats, cardinality, column selectivity, and available indexes, but do not recommend auto-applying DBMS_STATS or DDL.' || CHR(10));
    END IF;
    clob_app(l_prompt, 'Input SQL (full CLOB, chunked; not truncated):' || CHR(10));
    clob_app_clob(l_prompt, p_sql);
    IF l_mode = 'A' THEN
      clob_app(l_prompt, CHR(10) || 'Prompt mode A: SQL text and user objective only. XPLAN, runtime metrics, object metadata, Advisor, and Vector evidence are intentionally withheld.' || CHR(10));
    ELSIF l_mode = 'B' THEN
      clob_app(l_prompt, CHR(10) || 'Prompt mode B: SQL plus compact runtime metrics only. Raw XPLAN, object metadata, Advisor report, and Vector cases are intentionally withheld.' || CHR(10));
      clob_app_clob(l_prompt, compact_source_metrics(p_source_evidence_json));
    ELSE
      clob_app(l_prompt, CHR(10) || 'Prompt mode C: current ASTA compact full evidence.' || CHR(10));
      clob_app(l_prompt, 'Compact Source evidence JSON (raw evidence remains preserved outside the prompt):' || CHR(10));
      clob_app_clob(l_prompt, compact_source_evidence(p_source_evidence_json));
      clob_app(l_prompt, CHR(10) || 'Compact Vector KB evidence JSON (raw vector result remains preserved outside the prompt):' || CHR(10));
      clob_app_clob(l_prompt, compact_vector_evidence(p_vector_json));
    END IF;
    IF p_tuning_context_json IS NOT NULL THEN
      clob_app(l_prompt, CHR(10) || 'User tuning context JSON:' || CHR(10));
      clob_app_clob(l_prompt, p_tuning_context_json);
    END IF;
    RETURN l_prompt;
  END build_tuning_prompt;

  FUNCTION generate_tuning(
    p_sql                  IN CLOB,
    p_llm_profile          IN VARCHAR2,
    p_source_evidence_json IN CLOB,
    p_vector_json          IN CLOB,
    p_tuning_context_json  IN CLOB DEFAULT NULL,
    p_use_llm              IN VARCHAR2 DEFAULT 'Y'
  ) RETURN CLOB IS
    l_prompt          CLOB;
    l_prompt_vc       CLOB;
    l_response        CLOB;
    l_result          CLOB;
    l_candidate_sql   CLOB;
    l_candidate_error VARCHAR2(4000);
    l_profile         VARCHAR2(128);
    l_llm_call_count  PLS_INTEGER := 0;
  BEGIN
    IF UPPER(NVL(p_use_llm, 'Y')) <> 'Y' THEN
      RETURN TO_CLOB(
        '{"status":"SKIPPED","code":"LLM_TUNE","contract_version":"asta.v1","execution_boundary":"ADB_DBMS_CLOUD_AI","response_contract":"JSON_ONLY","candidate_guard_policy":"SELECT_WITH_SINGLE_STATEMENT","message":"LLM disabled","candidate_sql":null}'
      );
    END IF;

    IF p_llm_profile IS NULL THEN
      RETURN TO_CLOB(
        '{"status":"SKIPPED","code":"LLM_TUNE","contract_version":"asta.v1","execution_boundary":"ADB_DBMS_CLOUD_AI","response_contract":"JSON_ONLY","candidate_guard_policy":"SELECT_WITH_SINGLE_STATEMENT","message":"No ASTA LLM profile selected","candidate_sql":null}'
      );
    END IF;
    l_profile := validated_profile_name(p_llm_profile);
    asta_sql_guard_pkg.assert_safe_select(p_sql);

    l_prompt := build_tuning_prompt(
      p_sql,
      p_source_evidence_json,
      p_vector_json,
      p_tuning_context_json
    );
    -- Keep the complete SQL/evidence prompt as CLOB. Never collapse the
    -- combined prompt into VARCHAR2(32767) before DBMS_CLOUD_AI.
    l_prompt_vc := l_prompt;

    FOR i IN 1..3 LOOP
      l_response := NULL;
      l_llm_call_count := i;
      EXECUTE IMMEDIATE
        'SELECT DBMS_CLOUD_AI.GENERATE(prompt => :in_prompt, profile_name => :in_profile, action => ''chat'') FROM dual'
        INTO l_response
        USING IN l_prompt_vc, IN l_profile;
      EXIT WHEN l_response IS NOT NULL AND NVL(DBMS_LOB.GETLENGTH(l_response), 0) > 0;
    END LOOP;

    BEGIN
      l_candidate_sql := asta_sql_guard_pkg.extract_candidate_sql(l_response);
    EXCEPTION
      WHEN OTHERS THEN
        l_candidate_error := SUBSTR(SQLERRM, 1, 4000);
        l_candidate_sql := NULL;
    END;

    IF l_candidate_sql IS NULL THEN
      l_candidate_sql := p_sql;
      IF l_candidate_error IS NULL THEN
        l_candidate_error := 'LLM response did not expose a parseable safe candidate_sql; original SQL retained for after-evidence comparison.';
      END IF;
    END IF;

    DBMS_LOB.CREATETEMPORARY(l_result, TRUE);
    clob_app(l_result, '{"status":"COMPLETED","code":"LLM_TUNE","contract_version":"asta.v1","execution_boundary":"ADB_DBMS_CLOUD_AI","profile":');
    clob_app(l_result, json_str(l_profile));
    clob_app(l_result, ',"prompt_mode":');
    clob_app(l_result, json_str(prompt_mode(p_tuning_context_json)));
    clob_app(l_result, ',"prompt_chars":' || TO_CHAR(NVL(DBMS_LOB.GETLENGTH(l_prompt), 0)));
    clob_app(l_result, ',"llm_call_count":' || TO_CHAR(l_llm_call_count));
    clob_app(l_result, ',"response_contract":');
    clob_app(l_result, json_str(C_RESPONSE_CONTRACT));
    clob_app(l_result, ',"candidate_guard_policy":');
    clob_app(l_result, json_str(C_CANDIDATE_GUARD_POLICY));
    clob_app(l_result, ',"raw_response":');
    clob_app_json_str(l_result, l_response);
    clob_app(l_result, ',"candidate_sql":');
    clob_app_json_str(l_result, l_candidate_sql);
    clob_app(l_result, ',"tuning_context":');
    clob_app_clob(l_result, NVL(p_tuning_context_json, TO_CLOB('null')));
    clob_app(l_result, ',"candidate_error":');
    clob_app(l_result, json_str(l_candidate_error));
    clob_app(l_result, '}');
    RETURN l_result;
  EXCEPTION
    WHEN OTHERS THEN
      RETURN TO_CLOB(
        '{"status":"FAILED","code":"LLM_TUNE","contract_version":"asta.v1","execution_boundary":"ADB_DBMS_CLOUD_AI","profile":' ||
        json_str(p_llm_profile) || ',"message":' ||
        json_str(SUBSTR(SQLERRM || CHR(10) || DBMS_UTILITY.FORMAT_ERROR_BACKTRACE, 1, 4000)) ||
        ',"response_contract":"JSON_ONLY","candidate_guard_policy":"SELECT_WITH_SINGLE_STATEMENT","candidate_sql":null}'
      );
  END generate_tuning;

  FUNCTION generate_sql_only_tuning(
    p_sql                  IN CLOB,
    p_llm_profile          IN VARCHAR2,
    p_workload_type        IN VARCHAR2 DEFAULT 'OLTP',
    p_source_evidence_json IN CLOB DEFAULT NULL,
    p_vector_json          IN CLOB DEFAULT NULL,
    p_tuning_context_json  IN CLOB DEFAULT NULL,
    p_use_llm              IN VARCHAR2 DEFAULT 'Y',
    p_run_id               IN VARCHAR2 DEFAULT NULL
  ) RETURN CLOB IS
    l_diagnosis_prompt   CLOB;
    l_candidate_prompt   CLOB;
    l_diagnosis_response CLOB;
    l_candidate_response CLOB;
    l_result             CLOB;
    l_candidate_sql      CLOB;
    l_plan_text          CLOB;
    l_column_dictionary  CLOB;
    l_change_summary     CLOB;
    l_semantic_risks     CLOB;
    l_candidate_error    VARCHAR2(4000);
    l_profile            VARCHAR2(128);
    l_try_profile        VARCHAR2(128);
    l_diagnosis_profile  VARCHAR2(128);
    l_profile_errors     CLOB;
    l_error_count        PLS_INTEGER := 0;
    l_diagnosis_ok       VARCHAR2(1) := 'N';
    l_candidate_ok       VARCHAR2(1) := 'N';
    l_response_is_json   PLS_INTEGER := 0;
    l_annotation_added   VARCHAR2(1) := 'N';
    l_workload_type      VARCHAR2(10) := CASE WHEN UPPER(TRIM(p_workload_type)) = 'BATCH' THEN 'BATCH' ELSE 'OLTP' END;
    l_optimization_goal VARCHAR2(40);
    l_annotation_count PLS_INTEGER := 0;
    l_diagnosis_call_id NUMBER;
    l_candidate_call_id NUMBER;
    l_guard_rejected_candidate CLOB;
    l_guard_repair_candidate CLOB;
    l_guard_error VARCHAR2(2000);
    l_guard_repair_attempted VARCHAR2(1) := 'N';
    l_candidate_source VARCHAR2(40);
    l_source_executed VARCHAR2(1);
    l_history_references CLOB;
    l_history_references_included VARCHAR2(1) := 'N';
  BEGIN
    l_optimization_goal := CASE WHEN l_workload_type = 'BATCH' THEN 'MINIMIZE_ELAPSED_TIME' ELSE 'MINIMIZE_BUFFER_READS' END;
    IF UPPER(NVL(p_use_llm, 'Y')) <> 'Y' THEN
      RETURN TO_CLOB(
        '{"status":"SKIPPED","code":"SQL_ONLY_REWRITE","contract_version":"asta.v1","execution_boundary":"ADB_DBMS_CLOUD_AI","response_contract":"JSON_ONLY","candidate_guard_policy":"SELECT_WITH_SINGLE_STATEMENT","message":"LLM disabled","candidate_sql":null}'
      );
    END IF;

    l_profile := validated_profile_name(p_llm_profile);
    asta_sql_guard_pkg.assert_safe_select(p_sql);
    l_plan_text := json_query_clob(p_source_evidence_json, '$.plan_text');
    l_column_dictionary := compact_column_dictionary(p_source_evidence_json);
    l_source_executed := CASE WHEN LOWER(NVL(json_vc(p_source_evidence_json, '$.source_sql_executed'), 'true')) = 'false' THEN 'N' ELSE 'Y' END;
    IF l_source_executed = 'Y' THEN
      l_history_references := compact_verified_history_references(p_vector_json, l_workload_type);
      IF DBMS_LOB.INSTR(l_history_references, '"case_id"', 1, 1) > 0 THEN
        l_history_references_included := 'Y';
      END IF;
    ELSE
      l_history_references := TO_CLOB('{"status":"SKIPPED","reason":"SOURCE_SQL_NOT_EXECUTED","cases":[]}');
    END IF;
    DBMS_LOB.CREATETEMPORARY(l_profile_errors, TRUE);
    clob_app(l_profile_errors, '[');

    -- Stage 1: SQL + focused XPLAN only. Produce a compact diagnosis JSON,
    -- never a long candidate SQL embedded inside JSON.
    DBMS_LOB.CREATETEMPORARY(l_diagnosis_prompt, TRUE);
    clob_app(l_diagnosis_prompt, 'Tune this Oracle SQL using the supplied runtime evidence: analyze it using only SQL and DBMS_XPLAN.' || CHR(10));
    clob_app(l_diagnosis_prompt, 'Return JSON only; do not wrap the response in Markdown fences.' || CHR(10));
    clob_app(l_diagnosis_prompt, 'Return JSON only with rewrite_strategy(array), change_summary(array), semantic_risks(array), target_operations(array). Do not return candidate_sql.' || CHR(10));
    clob_app(l_diagnosis_prompt, 'Identify the safest structural rewrite for repeated scans, correlated MIN/SUM, UNION ALL, nested loops and temp transformations. ASTA will execute and compare the candidate later. Explanations must be Korean.' || CHR(10));
    -- Workload-specific priority: OLTP optimizes buffer reads, BATCH optimizes elapsed time.
    IF l_workload_type = 'BATCH' THEN
      clob_app(l_diagnosis_prompt, 'WORKLOAD_PRIORITY (BATCH, optimization_goal=MINIMIZE_ELAPSED_TIME): rank the dominant bottleneck primarily by elapsed time / wall-clock duration and temp-heavy work (large sorts, hash joins, TEMP spills); buffer gets is a supporting metric only. Do not add hints or index DDL; keep the rewrite purely structural.' || CHR(10));
    ELSE
      clob_app(l_diagnosis_prompt, 'WORKLOAD_PRIORITY (OLTP, optimization_goal=MINIMIZE_BUFFER_READS): rank the dominant bottleneck primarily by logical buffer reads (last_cr_buffer_gets per execution) and random table lookups (single-row index/rowid access under nested loops); elapsed time / wall-clock duration is a supporting metric only. Do not add hints or index DDL; keep the rewrite purely structural.' || CHR(10));
    END IF;
    IF l_source_executed = 'N' THEN
      clob_app(l_diagnosis_prompt, 'Safety mode is active: the Source SQL was NOT executed. DBMS_XPLAN is an estimated EXPLAIN PLAN only. Do not claim measured A-Time, Buffers, Starts, elapsed time, row counts, or result equivalence. Rank likely cost/cardinality and structural risks from estimated operations and object statistics, clearly labeling every conclusion as an estimate.' || CHR(10));
    ELSE
      clob_app(l_diagnosis_prompt, 'Rank XPLAN operations by measured A-Time and Buffers, using Starts to identify repeated work; choose exactly one dominant repeated-work operation, and record its query block, object, original correlation keys, immediate consumer, and one localized rewrite boundary in target_operations and rewrite_strategy. Do not propose a rewrite when those details cannot be established from the supplied SQL and XPLAN.' || CHR(10));
      clob_app(l_diagnosis_prompt, 'DOMINANT_TARGET_CONTRACT: target_operations must contain exactly one selected target with operation_id, query_block, object, original_correlation_or_join_keys, immediate_consumer, localized_rewrite_boundary, measured_buffers, measured_a_time, and starts. The selected target must be the highest measured repeated-work opportunity that can be safely rewritten; do not select a cheaper operation or combine multiple unrelated targets. If any field cannot be evidenced from the supplied SQL and XPLAN, return an empty target_operations array and no rewrite strategy.' || CHR(10));
      IF l_history_references_included = 'Y' THEN
        clob_app(l_diagnosis_prompt, 'VERIFIED_HISTORY_PATTERN_REFERENCE policy: the following are past IMPROVED/FULL_RESULT patterns for the same workload, not evidence or SQL templates. Never copy identifiers, literals, predicates, joins, or SQL text from a reference. Use a reference only when the current SQL and measured XPLAN independently prove the same dominant repeated-work shape, correlation/join grain, and immediate consumer. Current SQL/XPLAN evidence always wins; references cannot select a target, justify a candidate, or change the final verdict.' || CHR(10));
        clob_app(l_diagnosis_prompt, 'VERIFIED_HISTORY_PATTERN_REFERENCES (safe metadata only):' || CHR(10));
        clob_app_clob(l_diagnosis_prompt, l_history_references);
        clob_app(l_diagnosis_prompt, CHR(10));
      END IF;
    END IF;
    IF p_tuning_context_json IS NOT NULL THEN
      clob_app(l_diagnosis_prompt, 'User tuning context JSON is a hard scope constraint. Diagnose only the bottleneck named in user_notes and do not add unrelated rewrites:' || CHR(10));
      clob_app_clob(l_diagnosis_prompt, p_tuning_context_json);
      clob_app(l_diagnosis_prompt, CHR(10));
    END IF;
    clob_app(l_diagnosis_prompt, 'SQL:' || CHR(10));
    clob_app_clob(l_diagnosis_prompt, p_sql);
    clob_app(l_diagnosis_prompt, CHR(10) || 'DBMS_XPLAN (full CLOB; no truncation):' || CHR(10));
    clob_app_clob(l_diagnosis_prompt, l_plan_text);

    FOR i IN 1..2 LOOP
      l_try_profile := CASE i
        WHEN 1 THEN l_profile
        ELSE available_fallback_profile(l_profile, 1)
      END;
      IF l_try_profile IS NULL THEN
        CONTINUE;
      END IF;
      IF i > 1 AND l_try_profile = l_profile THEN
        CONTINUE;
      END IF;
      l_diagnosis_call_id := begin_llm_call_log(
        p_run_id       => p_run_id,
        p_stage        => 'DIAGNOSIS',
        p_attempt_no   => i,
        p_profile_name => l_try_profile,
        p_prompt       => l_diagnosis_prompt
      );
      BEGIN
        EXECUTE IMMEDIATE
          'SELECT DBMS_CLOUD_AI.GENERATE(prompt => :in_prompt, profile_name => :in_profile, action => ''chat'') FROM dual'
          INTO l_diagnosis_response
          USING IN l_diagnosis_prompt, IN l_try_profile;
        finish_llm_call_log(
          p_call_id     => l_diagnosis_call_id,
          p_response    => l_diagnosis_response,
          p_call_status => 'RECEIVED'
        );
      EXCEPTION
        WHEN OTHERS THEN
          finish_llm_call_log(
            p_call_id       => l_diagnosis_call_id,
            p_response      => NULL,
            p_call_status   => 'FAILED',
            p_error_code    => SQLCODE,
            p_error_message => SQLERRM
          );
          -- Preserve a non-sensitive profile/stage diagnostic without raw exception text
          -- because provider errors can contain request or endpoint details.
          IF l_error_count > 0 THEN clob_app(l_profile_errors, ','); END IF;
          clob_app(l_profile_errors, '{"profile":' || json_str(l_try_profile) ||
            ',"stage":"DIAGNOSIS","error_code":' || TO_CHAR(SQLCODE) || ',"message":"profile invocation failed"}');
          l_error_count := l_error_count + 1;
          CONTINUE;
      END;
      l_diagnosis_response := normalize_json_response(l_diagnosis_response);
      SELECT CASE WHEN l_diagnosis_response IS JSON THEN 1 ELSE 0 END INTO l_response_is_json FROM dual;
      IF l_response_is_json = 0 THEN
        IF l_error_count > 0 THEN clob_app(l_profile_errors, ','); END IF;
        clob_app(l_profile_errors, '{"profile":' || json_str(l_try_profile) ||
          ',"stage":"DIAGNOSIS","error_code":null,"message":"malformed diagnosis JSON"}');
        l_error_count := l_error_count + 1;
        CONTINUE;
      END IF;
      l_diagnosis_ok := 'Y';
      l_diagnosis_profile := l_try_profile;
      EXIT;
    END LOOP;

    -- Stage 2: request SQL text only. This avoids JSON escaping/truncation for
    -- 10K+ character candidates and lets ASTA own the response metadata.
    DBMS_LOB.CREATETEMPORARY(l_candidate_prompt, TRUE);
    clob_app(l_candidate_prompt, 'Return only one complete executable Oracle SELECT or WITH statement. No JSON, Markdown, prose, DDL, DML, PL/SQL, new hints, semicolon, or slash.' || CHR(10));
    clob_app(l_candidate_prompt, 'Use the diagnosis and XPLAN to produce the safest testable structural rewrite. Preserve columns, datatypes, order, NULL and COUNT(DISTINCT) semantics, including aggregate behavior. ASTA will execute and compare results, so put uncertainty in the diagnosis rather than refusing.' || CHR(10));
    clob_app(l_candidate_prompt, 'Before returning SQL, perform a semantic preflight against the original: preserve every output expression in the same order with the same alias and datatype; preserve all filter predicates, join conditions, outer-join null extension, row grain, and duplicate multiplicity; preserve GROUP BY and analytic PARTITION BY grains plus scalar-aggregate empty-input behavior. Trace every alias.column reference to a column projected by that exact source, CTE, or inline view; never invent a column, drop a UNION ALL branch, or replace an original expression with a placeholder. Return NO_REWRITE if any check cannot be satisfied.' || CHR(10));
    clob_app(l_candidate_prompt, 'Oracle syntax preflight is mandatory before returning SQL: balance every parenthesis; keep every SELECT/FROM/JOIN/WHERE/GROUP BY and set-operation branch syntactically complete; ensure each CTE has one unique name; never give a CTE the same name as a referenced base table or view; update every consumer to the exact new CTE name; prohibit accidental self-reference or recursive WITH; and trace every alias and column to a declared source. Return NO_REWRITE instead of SQL that could raise ORA-00904, ORA-00918, ORA-00942, ORA-01789, ORA-32039, or another Oracle parse/name-resolution error.' || CHR(10));
    clob_app(l_candidate_prompt, 'ORA-25156 preflight: never mix ANSI JOIN syntax with the old-style Oracle outer-join operator (+) in a candidate. Preserve one join style consistently; return NO_REWRITE if a safe conversion is uncertain.' || CHR(10));
    clob_app(l_candidate_prompt, 'For a correlated MIN or SUM whose outer DECODE maps ''-'' to all inner COLOR_CD or SIZE_CD values, pre-aggregate separate exact and wildcard grains with GROUPING SETS and GROUPING flags, then LEFT JOIN at most one aggregate row from the original immediate consumer. Preserve the scalar aggregate result of one NULL value when no inner row matches; never use a detail-grain wildcard join or COALESCE that changes this empty-input result. Return NO_REWRITE if these semantics cannot be preserved.' || CHR(10));
    clob_app(l_candidate_prompt, 'CANDIDATE_ACCEPTANCE_CHECKLIST: implement only the one DOMINANT_TARGET_CONTRACT target from DIAGNOSIS. Before returning SQL, verify internally that (1) the candidate removes or evaluates once the target repeated base-table access/subquery, (2) every original correlation or join key preserves the original result grain, NULL behavior, duplicate multiplicity, and COUNT(DISTINCT) semantics, (3) each helper join can match at most one aggregate/key row for its immediate consumer, and (4) the leading ASTA change annotation states the removed repeated operation and the evidence-based expected Buffer Gets effect. Return exactly NO_REWRITE if any check fails; never substitute an unrelated rewrite, full-query redesign, or hint-only change.' || CHR(10));
    IF l_history_references_included = 'Y' THEN
      clob_app(l_candidate_prompt, 'VERIFIED_HISTORY_PATTERN_REFERENCE candidate rule: references are non-authoritative structural ideas only. Do not copy any reference SQL/object/column/literal/predicate. Apply an idea only after the current DIAGNOSIS and XPLAN prove the same target shape and safety keys; otherwise ignore it. The current candidate must independently pass CANDIDATE_ACCEPTANCE_CHECKLIST and ASTA deterministic validation.' || CHR(10));
      clob_app(l_candidate_prompt, 'VERIFIED_HISTORY_PATTERN_REFERENCES (safe metadata only):' || CHR(10));
      clob_app_clob(l_candidate_prompt, l_history_references);
      clob_app(l_candidate_prompt, CHR(10));
    END IF;
    IF NVL(DBMS_LOB.GETLENGTH(p_sql), 0) >= 12000 THEN
      clob_app(l_candidate_prompt, 'Long-SQL candidate boundary: rewrite exactly one repeated-access pattern completely across its producer and consumer blocks. Add every helper CTE, projected join key, GROUP BY expression, join, and correlated-reference change required for that one pattern, while copying every unrelated CTE, UNION ALL branch, predicate, and select-list expression verbatim. Do not redesign the full statement, change any set-operation branch projection count, or reference a grouping key after aggregation removed it.' || CHR(10));
    END IF;
    clob_app(l_candidate_prompt, 'No DDL, new hints, statistics changes, indexes, optimizer hints, SQL Profile, or Plan Baseline proposals. 인덱스, 옵티마이저 힌트, DDL, 통계, SQL Profile 제안은 금지합니다.' || CHR(10));
    clob_app(l_candidate_prompt, 'AUTHORITATIVE SOURCE COLUMN DICTIONARY JSON follows. For every listed owner.table, use only column_name values present in that table entry; never copy a correlation key from a similar table. An empty or absent table entry means unknown and is not permission to invent a column. Preserve unchanged view/query-block text when its columns are not listed.' || CHR(10));
    clob_app_clob(l_candidate_prompt, l_column_dictionary);
    clob_app(l_candidate_prompt, CHR(10));
    clob_app(l_candidate_prompt, 'For a changed SQL, prepend: /* ASTA_TUNING_CHANGE_1: existing issue -> structural rewrite -> expected buffer/elapsed effect */. Keep all numbered change comments in the leading header; ASTA will add it if omitted.' || CHR(10));
    clob_app(l_candidate_prompt, 'If absolutely no candidate can be written, return exactly NO_REWRITE.' || CHR(10));
    IF p_tuning_context_json IS NOT NULL THEN
      clob_app(l_candidate_prompt, 'User tuning context JSON is a hard scope constraint. Implement only the localized rewrite requested in user_notes; copy every unrelated SQL fragment verbatim:' || CHR(10));
      clob_app_clob(l_candidate_prompt, p_tuning_context_json);
      clob_app(l_candidate_prompt, CHR(10));
    END IF;
    clob_app(l_candidate_prompt, 'DIAGNOSIS:' || CHR(10));
    IF l_diagnosis_ok = 'Y' THEN clob_app_clob(l_candidate_prompt, l_diagnosis_response); ELSE clob_app(l_candidate_prompt, '{}'); END IF;
    clob_app(l_candidate_prompt, CHR(10) || 'SQL:' || CHR(10));
    clob_app_clob(l_candidate_prompt, p_sql);
    clob_app(l_candidate_prompt, CHR(10) || 'DBMS_XPLAN (full CLOB; no truncation):' || CHR(10));
    clob_app_clob(l_candidate_prompt, l_plan_text);

    FOR i IN 1..4 LOOP
      l_try_profile := CASE i
        WHEN 1 THEN NVL(l_diagnosis_profile, l_profile)
        ELSE available_fallback_profile(NVL(l_diagnosis_profile, l_profile), i - 1)
      END;
      IF l_try_profile IS NULL THEN CONTINUE; END IF;
      IF i > 1 AND l_try_profile = NVL(l_diagnosis_profile, l_profile) THEN CONTINUE; END IF;
      l_candidate_response := NULL;
      l_candidate_call_id := begin_llm_call_log(
        p_run_id       => p_run_id,
        p_stage        => 'CANDIDATE_SQL',
        p_attempt_no   => i,
        p_profile_name => l_try_profile,
        p_prompt       => l_candidate_prompt
      );
      BEGIN
        EXECUTE IMMEDIATE
          'SELECT DBMS_CLOUD_AI.GENERATE(prompt => :in_prompt, profile_name => :in_profile, action => ''chat'') FROM dual'
          INTO l_candidate_response
          USING IN l_candidate_prompt, IN l_try_profile;
        finish_llm_call_log(
          p_call_id     => l_candidate_call_id,
          p_response    => l_candidate_response,
          p_call_status => 'RECEIVED'
        );
      EXCEPTION
        WHEN OTHERS THEN
          finish_llm_call_log(
            p_call_id       => l_candidate_call_id,
            p_response      => NULL,
            p_call_status   => 'FAILED',
            p_error_code    => SQLCODE,
            p_error_message => SQLERRM
          );
          -- Preserve a non-sensitive profile/stage diagnostic without raw exception text
          -- because provider errors can contain request or endpoint details.
          IF l_error_count > 0 THEN clob_app(l_profile_errors, ','); END IF;
          clob_app(l_profile_errors, '{"profile":' || json_str(l_try_profile) ||
            ',"stage":"CANDIDATE_SQL","error_code":' || TO_CHAR(SQLCODE) || ',"message":"profile invocation failed"}');
          l_error_count := l_error_count + 1;
          CONTINUE;
      END;
      IF l_candidate_response IS NULL OR NVL(DBMS_LOB.GETLENGTH(l_candidate_response), 0) = 0 THEN
        IF l_error_count > 0 THEN clob_app(l_profile_errors, ','); END IF;
        clob_app(l_profile_errors, '{"profile":' || json_str(l_try_profile) ||
          ',"stage":"CANDIDATE_SQL","error_code":null,"message":"empty response"}');
        l_error_count := l_error_count + 1;
        CONTINUE;
      END IF;
      IF NVL(DBMS_LOB.GETLENGTH(l_candidate_response), 0) > 32767 THEN
        l_candidate_error := 'FEATURE_LIMITED: candidate SQL exceeds the 32767-character SQL validation boundary; truncated SQL is never executed';
        l_candidate_sql := NULL;
        EXIT;
      END IF;
      IF UPPER(TRIM(DBMS_LOB.SUBSTR(l_candidate_response, 100, 1))) = 'NO_REWRITE' THEN CONTINUE; END IF;
      l_candidate_sql := normalize_sql_response(l_candidate_response);
      IF structural_sql_key(p_sql) = structural_sql_key(l_candidate_sql) THEN
        l_candidate_error := 'NO_REWRITE: identical, comment-only, or hint-only candidate';
        l_candidate_sql := NULL;
        CONTINUE;
      END IF;
      BEGIN
        asta_sql_guard_pkg.assert_candidate_compatible(l_candidate_sql);
        IF leading_change_annotation_count(l_candidate_sql) < 1 THEN
          l_candidate_sql := prepend_generated_change_annotation(l_candidate_sql);
          l_annotation_added := 'Y';
        END IF;
        asta_sql_guard_pkg.assert_candidate_compatible(l_candidate_sql);
        l_candidate_ok := 'Y';
        l_candidate_error := NULL;
        l_candidate_source := 'LLM_GENERATED';
        l_profile := l_try_profile;
        EXIT;
      EXCEPTION
        WHEN OTHERS THEN
          l_guard_error := SUBSTR(SQLERRM, 1, 2000);
          l_guard_rejected_candidate := l_candidate_sql;
          IF l_guard_repair_attempted = 'N' THEN
            l_guard_repair_attempted := 'Y';
            l_guard_repair_candidate := repair_sql_candidate(
              p_original_sql         => p_sql,
              p_rejected_candidate   => l_guard_rejected_candidate,
              p_error_message        => l_guard_error,
              p_llm_profile          => l_try_profile,
              p_run_id               => p_run_id,
              p_source_evidence_json => p_source_evidence_json
            );
            IF l_guard_repair_candidate IS NOT NULL THEN
              asta_sql_guard_pkg.assert_candidate_compatible(l_guard_repair_candidate);
              l_candidate_sql := l_guard_repair_candidate;
              l_candidate_ok := 'Y';
              l_candidate_error := NULL;
              l_candidate_source := 'GUARD_REPAIR';
              l_profile := l_try_profile;
              EXIT;
            END IF;
          END IF;
          l_candidate_error := 'NO_REWRITE: candidate failed structural safety validation: ' || SUBSTR(l_guard_error, 1, 1000);
          l_candidate_sql := NULL;
      END;
    END LOOP;
    clob_app(l_profile_errors, ']');

    DBMS_LOB.CREATETEMPORARY(l_result, TRUE);
    clob_app(l_result, '{"status":' || json_str(CASE WHEN l_diagnosis_ok = 'Y' OR l_candidate_ok = 'Y' THEN 'COMPLETED' ELSE 'FAILED' END) || ',"code":"SQL_ONLY_REWRITE","contract_version":"asta.v1","execution_boundary":"ADB_DBMS_CLOUD_AI","response_contract":"TWO_STAGE_DIAGNOSIS_JSON_AND_SQL_CLOB","candidate_guard_policy":"SELECT_WITH_SINGLE_STATEMENT"');
    clob_app(l_result, ',"llm_profile":' || json_str(l_profile));
    clob_app(l_result, ',"diagnosis_profile":' || json_str(l_diagnosis_profile));
    clob_app(l_result, ',"workload_type":' || json_str(l_workload_type));
    clob_app(l_result, ',"optimization_goal":' || json_str(l_optimization_goal));
    clob_app(l_result, ',"prompt_mode":"SQL_XPLAN_TWO_STAGE"');
    clob_app(l_result, ',"diagnosis_prompt_chars":' || TO_CHAR(NVL(DBMS_LOB.GETLENGTH(l_diagnosis_prompt), 0)));
    clob_app(l_result, ',"prompt_chars":' || TO_CHAR(NVL(DBMS_LOB.GETLENGTH(l_candidate_prompt), 0)));
    clob_app(l_result, ',"xplan_chars":' || TO_CHAR(NVL(DBMS_LOB.GETLENGTH(l_plan_text), 0)));
    clob_app(l_result, ',"xplan_truncated":false');
    clob_app(l_result, ',"source_evidence_included":' || CASE WHEN p_source_evidence_json IS NULL THEN 'false' ELSE 'true' END);
    clob_app(l_result, ',"vector_evidence_included":false');
    clob_app(l_result, ',"verified_history_references_included":' || CASE WHEN l_history_references_included = 'Y' THEN 'true' ELSE 'false' END);
    -- This is the same SQL-free metadata supplied to the two LLM prompts.  Keep it
    -- in the run artifact so the report can state exactly what additional context
    -- was provided without exposing a prior customer's SQL text.
    clob_app(l_result, ',"verified_history_reference_summary":');
    clob_app_clob(l_result, NVL(l_history_references, TO_CLOB('{"status":"SKIPPED","reason":"NO_VERIFIED_HISTORY_REFERENCES","cases":[]}')));
    IF l_candidate_sql IS NOT NULL AND structural_sql_key(p_sql) = structural_sql_key(l_candidate_sql) THEN
      l_candidate_sql := NULL;
      l_candidate_error := 'NO_REWRITE: identical, comment-only, or hint-only candidate';
    END IF;
    l_annotation_count := leading_change_annotation_count(l_candidate_sql);
    clob_app(l_result, ',"rewrite_available":' || CASE WHEN l_candidate_sql IS NULL THEN 'false' ELSE 'true' END);
    clob_app(l_result, ',"candidate_source":' || json_str(l_candidate_source));
    clob_app(l_result, ',"guard_repair_attempted":' || CASE WHEN l_guard_repair_attempted = 'Y' THEN 'true' ELSE 'false' END);
    clob_app(l_result, ',"leading_change_annotations_present":' || CASE WHEN l_annotation_count > 0 THEN 'true' ELSE 'false' END);
    clob_app(l_result, ',"leading_change_annotation_count":' || TO_CHAR(l_annotation_count));
    clob_app(l_result, ',"annotation_note":' || json_str(CASE WHEN l_annotation_added = 'Y' THEN 'ASTA added the required leading change annotation' END));
    clob_app(l_result, ',"candidate_sql":');
    clob_app_json_str(l_result, l_candidate_sql);
    -- Stage-1 diagnosis owns explanatory arrays; candidate SQL is plain CLOB.
    SELECT JSON_QUERY(l_diagnosis_response, '$.change_summary' RETURNING CLOB NULL ON ERROR),
           JSON_QUERY(l_diagnosis_response, '$.semantic_risks' RETURNING CLOB NULL ON ERROR)
    INTO l_change_summary, l_semantic_risks FROM dual;
    clob_app(l_result, ',"change_summary":');
    clob_app_clob(l_result, NVL(l_change_summary, TO_CLOB('[]')));
    clob_app(l_result, ',"semantic_risks":');
    clob_app_clob(l_result, NVL(l_semantic_risks, TO_CLOB('[]')));
    clob_app(l_result, ',"diagnosis":');
    IF l_diagnosis_ok = 'Y' THEN clob_app_clob(l_result, l_diagnosis_response); ELSE clob_app(l_result, 'null'); END IF;
    clob_app(l_result, ',"candidate_error":');
    clob_app(l_result, json_str(CASE
      WHEN l_candidate_ok = 'Y' THEN l_candidate_error
      WHEN l_diagnosis_ok = 'N' THEN 'INVALID_RESPONSE: diagnosis profiles failed or returned malformed JSON'
      ELSE NVL(l_candidate_error, 'NO_REWRITE: two-stage candidate generation returned no safe SQL')
    END));
    clob_app(l_result, ',"profile_errors":');
    clob_app_clob(l_result, l_profile_errors);
    clob_app(l_result, ',"raw_response":');
    clob_app_json_str(l_result, l_candidate_response);
    clob_app(l_result, '}');
    RETURN l_result;
  EXCEPTION
    WHEN OTHERS THEN
      RETURN TO_CLOB(
        '{"status":"FAILED","code":"SQL_ONLY_REWRITE","contract_version":"asta.v1","execution_boundary":"ADB_DBMS_CLOUD_AI","response_contract":"JSON_ONLY","message":' ||
        json_str(SUBSTR(SQLERRM, 1, 4000)) || ',"candidate_sql":null}'
      );
  END generate_sql_only_tuning;

  FUNCTION repair_sql_candidate(
    p_original_sql       IN CLOB,
    p_rejected_candidate IN CLOB,
    p_error_message      IN VARCHAR2,
    p_llm_profile        IN VARCHAR2,
    p_run_id             IN VARCHAR2 DEFAULT NULL,
    p_source_evidence_json IN CLOB DEFAULT NULL
  ) RETURN CLOB IS
    l_prompt       CLOB;
    l_response     CLOB;
    l_candidate    CLOB;
    l_column_dictionary CLOB;
    l_profile      VARCHAR2(128);
    l_try_profile  VARCHAR2(128);
    l_call_id      NUMBER;
  BEGIN
    IF p_rejected_candidate IS NULL THEN
      RETURN NULL;
    END IF;
    l_profile := validated_profile_name(p_llm_profile);
    asta_sql_guard_pkg.assert_safe_select(p_original_sql);
    l_column_dictionary := compact_column_dictionary(p_source_evidence_json);
    DBMS_LOB.CREATETEMPORARY(l_prompt, TRUE);
    clob_app(l_prompt, 'Rewrite the rejected candidate into one complete executable Oracle SELECT or WITH statement that resolves the exact ORA error below.' || CHR(10));
    clob_app(l_prompt, 'Use ORIGINAL SQL as the semantic contract and REJECTED CANDIDATE as the intended optimization. Preserve the original output columns, aliases, datatypes, ordering, filters, joins, row grain, duplicate multiplicity, NULL behavior, aggregates and COUNT(DISTINCT) semantics. Apply the intended optimization only when it can be expressed as valid Oracle SQL.' || CHR(10));
    clob_app(l_prompt, 'Perform a full Oracle syntax and name-resolution preflight: balance parentheses; make every clause and UNION branch complete; ensure CTE names are unique and do not collide with referenced base table/view names; replace all stale consumer references after a CTE rename; prohibit accidental recursive WITH; and ensure every alias.column resolves to a declared projection. Do not return the same failing SQL. Return NO_REWRITE only if no safe executable repair is possible.' || CHR(10));
    clob_app(l_prompt, 'ORA-32039 rule: Oracle can treat a CTE as recursive when its name equals a schema-qualified base table or view read inside that CTE (for example WITH VIF_WHOLESALE_S AS (... FROM DSNT.VIF_WHOLESALE_S ...)). Rename the CTE to a distinct helper name such as WHOLESALE_STYLE_KEYS and update every consumer to that exact helper name; do not add a recursive column alias list unless the original SQL intentionally uses recursion.' || CHR(10));
    clob_app(l_prompt, 'ORA-25156 rule: never mix ANSI JOIN syntax with the old-style Oracle outer-join operator (+). Preserve one join style consistently across the repaired candidate.' || CHR(10));
    clob_app(l_prompt, 'No JSON, Markdown, prose, DDL, DML, PL/SQL, new hints, semicolon, or slash. Keep the leading ASTA_TUNING_CHANGE comments.' || CHR(10));
    clob_app(l_prompt, 'AUTHORITATIVE SOURCE COLUMN DICTIONARY JSON follows. For every listed owner.table, use only column_name values present in that table entry. Remove or remap an invalid identifier only from ORIGINAL SQL evidence and this dictionary; never copy a key from a similar table or invent a replacement column.' || CHR(10));
    clob_app_clob(l_prompt, l_column_dictionary);
    clob_app(l_prompt, CHR(10));
    clob_app(l_prompt, 'Oracle execution error to resolve exactly: ' || SUBSTR(p_error_message, 1, 2000) || CHR(10));
    clob_app(l_prompt, 'ORIGINAL SQL (semantic contract):' || CHR(10));
    clob_app_clob(l_prompt, p_original_sql);
    clob_app(l_prompt, CHR(10) || 'REJECTED CANDIDATE (rewrite this into valid SQL):' || CHR(10));
    clob_app_clob(l_prompt, p_rejected_candidate);

    FOR i IN 1..2 LOOP
      l_try_profile := CASE i
        WHEN 1 THEN l_profile
        ELSE available_fallback_profile(l_profile, 1)
      END;
      IF l_try_profile IS NULL THEN CONTINUE; END IF;
      IF i > 1 AND l_try_profile = l_profile THEN CONTINUE; END IF;
      l_call_id := begin_llm_call_log(
        p_run_id       => p_run_id,
        p_stage        => 'REPAIR_SQL',
        p_attempt_no   => i,
        p_profile_name => l_try_profile,
        p_prompt       => l_prompt
      );
      l_response := NULL;
      BEGIN
        EXECUTE IMMEDIATE
          'SELECT DBMS_CLOUD_AI.GENERATE(prompt => :in_prompt, profile_name => :in_profile, action => ''chat'') FROM dual'
          INTO l_response
          USING IN l_prompt, IN l_try_profile;
        finish_llm_call_log(
          p_call_id     => l_call_id,
          p_response    => l_response,
          p_call_status => 'RECEIVED'
        );
        l_candidate := normalize_sql_response(l_response);
        IF l_candidate IS NULL
           OR UPPER(TRIM(DBMS_LOB.SUBSTR(l_candidate, 100, 1))) = 'NO_REWRITE'
           OR structural_sql_key(p_original_sql) = structural_sql_key(l_candidate) THEN
          CONTINUE;
        END IF;
        asta_sql_guard_pkg.assert_candidate_compatible(l_candidate);
        IF leading_change_annotation_count(l_candidate) < 1 THEN
          l_candidate := prepend_generated_change_annotation(l_candidate);
        END IF;
        asta_sql_guard_pkg.assert_candidate_compatible(l_candidate);
        RETURN l_candidate;
      EXCEPTION WHEN OTHERS THEN
        IF l_response IS NULL THEN
          finish_llm_call_log(
            p_call_id       => l_call_id,
            p_response      => NULL,
            p_call_status   => 'FAILED',
            p_error_code    => SQLCODE,
            p_error_message => SQLERRM
          );
        END IF;
        l_candidate := NULL;
      END;
    END LOOP;
    RETURN NULL;
  EXCEPTION WHEN OTHERS THEN
    RETURN NULL;
  END repair_sql_candidate;

  FUNCTION final_review(
    p_before_after_json IN CLOB,
    p_llm_profile       IN VARCHAR2,
    p_use_llm           IN VARCHAR2 DEFAULT 'Y'
  ) RETURN CLOB IS
    l_prompt          CLOB;
    l_response        CLOB;
    l_result          CLOB;
    l_profile         VARCHAR2(128);
    l_report_markdown CLOB;
  BEGIN
    IF UPPER(NVL(p_use_llm, 'Y')) <> 'Y' THEN
      RETURN TO_CLOB(
        '{"status":"SKIPPED","code":"LLM_FINAL_REVIEW","contract_version":"asta.v1","execution_boundary":"ADB_DBMS_CLOUD_AI","response_contract":"JSON_ONLY","message":"LLM disabled"}'
      );
    END IF;

    IF p_llm_profile IS NULL THEN
      RETURN TO_CLOB(
        '{"status":"SKIPPED","code":"LLM_FINAL_REVIEW","contract_version":"asta.v1","execution_boundary":"ADB_DBMS_CLOUD_AI","response_contract":"JSON_ONLY","message":"No ASTA LLM profile selected"}'
      );
    END IF;
    l_profile := validated_profile_name(p_llm_profile);

    DBMS_LOB.CREATETEMPORARY(l_prompt, TRUE);
    clob_app(l_prompt, 'You are ASTA running inside Oracle ADB PL/SQL.' || CHR(10));
    clob_app(l_prompt, 'Compare before and after SQL evidence and write the final Korean SQL tuning report.' || CHR(10));
    clob_app(l_prompt, 'All explanatory text fields must be written in Korean. Keep only SQL identifiers, Oracle keywords, object names, and metric field names in their original form.' || CHR(10));
    clob_app(l_prompt, 'Return JSON only; do not wrap the response in Markdown fences.' || CHR(10));
    clob_app(l_prompt, 'Use only the provided before/after JSON metrics; do not invent Source runtime evidence.' || CHR(10));
    clob_app(l_prompt, 'Return JSON only with report_markdown, equivalence_risk, performance_readout, and recommendation.' || CHR(10));
    clob_app(l_prompt, 'report_markdown must exactly follow this section format and use only supplied evidence:' || CHR(10));
    clob_app(l_prompt, '# SQL 튜닝 결과서' || CHR(10));
    clob_app(l_prompt, '## 결론' || CHR(10));
    clob_app(l_prompt, '- 추천: <SQL 변경/원본 유지 + 핵심 이유>' || CHR(10));
    clob_app(l_prompt, '- 수행시간: <before> 초 → <after> 초 (<개선율 또는 악화율>)' || CHR(10));
    clob_app(l_prompt, '- buffer_gets: <before> → <after> (<개선율 또는 악화율>)' || CHR(10));
    clob_app(l_prompt, '## 병목 진단' || CHR(10));
    clob_app(l_prompt, '## 튜닝 전/후 수치 비교' || CHR(10));
    clob_app(l_prompt, '## 튜닝 전 SQL' || CHR(10));
    clob_app(l_prompt, '## 튜닝 전 XPLAN' || CHR(10));
    clob_app(l_prompt, '## 튜닝 후 SQL' || CHR(10));
    clob_app(l_prompt, '## 튜닝 후 XPLAN' || CHR(10));
    clob_app(l_prompt, '## 상세 분석' || CHR(10));
    clob_app(l_prompt, '### 사용자 참고사항 반영' || CHR(10));
    clob_app(l_prompt, '### Vector 유사 사례' || CHR(10));
    clob_app(l_prompt, '### Oracle SQL Tuning Advisor 요약' || CHR(10));
    clob_app(l_prompt, '### DBA 검토 사항' || CHR(10));
    clob_app(l_prompt, 'DBA 검토 사항 must not be generic boilerplate. Use only supplied advisor status/recommendation type, comparison verdict/equivalence/actual metrics, and object stats/index evidence. For each recommended physical change state the prechecks, impact scope, DBA approval, test, and rollback conditions. State that automatic application was not performed. If evidence is absent, say it is unavailable; do not invent it. Do not dump the raw Advisor report.' || CHR(10));
    clob_app(l_prompt, '## 작업 수행 이력' || CHR(10));
    clob_app(l_prompt, 'Use actual before/after SQL, XPLAN, metrics, object metadata, vector/advisor status, and progress details when present. Do not invent missing runtime metrics. If candidate SQL was rejected or equivalence failed, say 후보 SQL rejected/원본 SQL 유지.' || CHR(10));
    clob_app(l_prompt, 'If compact JSON includes user_notes, include subsection ### 사용자 참고사항 반영 and explain whether/how the notes affected the tuning recommendation. If no user_notes were supplied, say 별도 참고사항 없음.' || CHR(10));
    clob_app(l_prompt, 'Put a blank line between report sections and between bullet/list items so each item is visually separated.' || CHR(10));
    clob_app(l_prompt, 'Format SQL inside fenced ```sql blocks with readable line breaks and indentation: SELECT columns on separate lines, FROM/JOIN/WHERE/GROUP BY/ORDER BY on separate lines, and no single-line minified SQL.' || CHR(10));
    clob_app(l_prompt, 'For XPLAN sections, do not paste or recreate raw DBMS_XPLAN table output. Write a short non-duplicated summary of key operations only, and state that the full XPLAN is preserved in runtime_evidence.plan_text and after_evidence.plan_text artifacts.' || CHR(10));
    clob_app(l_prompt, 'Never output duplicated XPLAN headers, repeated operation rows, half-lines, or mixed SQL/XPLAN fragments.' || CHR(10));
    clob_app(l_prompt, 'If the source evidence has truncated or malformed XPLAN text, do not try to reconstruct missing rows; summarize the available stable operations and point to artifacts for full raw evidence.' || CHR(10));
    clob_app(l_prompt, 'If disk_reads > 0, judge by buffer_gets/consistent_gets reduction rather than elapsed_time.' || CHR(10));
    clob_app(l_prompt, 'Compact before/after package JSON (raw before/after evidence remains preserved outside the prompt):' || CHR(10));
    clob_app_clob(l_prompt, compact_before_after(p_before_after_json));

    EXECUTE IMMEDIATE q'[
      BEGIN
        :out_response := DBMS_CLOUD_AI.GENERATE(
          :in_prompt,
          profile_name => :in_profile,
          action       => 'chat'
        );
      END;
    ]'
    USING OUT l_response, IN l_prompt, IN l_profile;

    BEGIN
      SELECT JSON_VALUE(l_response, '$.report_markdown' RETURNING CLOB NULL ON ERROR)
      INTO   l_report_markdown
      FROM   dual;
    EXCEPTION WHEN OTHERS THEN
      l_report_markdown := NULL;
    END;

    DBMS_LOB.CREATETEMPORARY(l_result, TRUE);
    clob_app(l_result, '{"status":"COMPLETED","code":"LLM_FINAL_REVIEW","contract_version":"asta.v1","execution_boundary":"ADB_DBMS_CLOUD_AI","profile":');
    clob_app(l_result, json_str(l_profile));
    clob_app(l_result, ',"response_contract":');
    clob_app(l_result, json_str(C_RESPONSE_CONTRACT));
    clob_app(l_result, ',"raw_response":');
    clob_app_json_str(l_result, l_response);
    clob_app(l_result, ',"report_markdown":');
    clob_app_json_str(l_result, l_report_markdown);
    clob_app(l_result, '}');
    RETURN l_result;
  EXCEPTION
    WHEN OTHERS THEN
      RETURN TO_CLOB(
        '{"status":"FAILED","code":"LLM_FINAL_REVIEW","contract_version":"asta.v1","execution_boundary":"ADB_DBMS_CLOUD_AI","profile":' ||
        json_str(p_llm_profile) || ',"message":' ||
        json_str(SUBSTR(SQLERRM || CHR(10) || DBMS_UTILITY.FORMAT_ERROR_BACKTRACE, 1, 4000)) ||
        ',"response_contract":"JSON_ONLY"}'
      );
  END final_review;
END asta_llm_pkg;
/
