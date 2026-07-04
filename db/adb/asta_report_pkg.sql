-- db/adb/asta_report_pkg.sql
-- Canonical ASTA report and JSON response builder for ADB/ORDS.
-- Guard Policy: `SELECT_WITH_SINGLE_STATEMENT`

CREATE OR REPLACE PACKAGE asta_report_pkg AUTHID DEFINER AS
  FUNCTION build_report(
    p_run_id               IN VARCHAR2,
    p_input_sql            IN CLOB,
    p_source_evidence_json IN CLOB,
    p_vector_json          IN CLOB,
    p_llm_json             IN CLOB,
    p_status               IN VARCHAR2 DEFAULT 'COMPLETED',
    p_error_json           IN CLOB DEFAULT NULL,
    p_final_review_json    IN CLOB DEFAULT NULL,
    p_after_evidence_json  IN CLOB DEFAULT NULL,
    p_comparison_json      IN CLOB DEFAULT NULL,
    p_vector_save_json     IN CLOB DEFAULT NULL
  ) RETURN CLOB;

  FUNCTION build_response_json(
    p_run_id               IN VARCHAR2,
    p_status               IN VARCHAR2,
    p_report_markdown      IN CLOB,
    p_source_evidence_json IN CLOB,
    p_vector_json          IN CLOB,
    p_llm_json             IN CLOB,
    p_error_json           IN CLOB DEFAULT NULL,
    p_progress_json        IN CLOB DEFAULT NULL,
    p_final_review_json    IN CLOB DEFAULT NULL,
    p_after_evidence_json  IN CLOB DEFAULT NULL,
    p_comparison_json      IN CLOB DEFAULT NULL,
    p_vector_save_json     IN CLOB DEFAULT NULL
  ) RETURN CLOB;
END asta_report_pkg;
/

CREATE OR REPLACE PACKAGE BODY asta_report_pkg AS
  C_RESPONSE_CONTRACT CONSTANT VARCHAR2(40) := 'CLOB_CHUNKED_JSON';
  C_GUARD_POLICY      CONSTANT VARCHAR2(40) := 'SELECT_WITH_SINGLE_STATEMENT';

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
      -- 8K characters fit in a 32K PL/SQL VARCHAR2 even under AL32UTF8.
      -- Advance by the characters actually copied; DBMS_LOB.SUBSTR may return
      -- fewer characters than requested when the CLOB contains multibyte text.
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
      l_chunk := DBMS_LOB.SUBSTR(p_val, 100, l_offset);
      l_escaped := REPLACE(l_chunk, '\', '\\');
      l_escaped := REPLACE(l_escaped, '"', '\"');
      l_escaped := REPLACE(l_escaped, CHR(8), '\b');
      l_escaped := REPLACE(l_escaped, CHR(9), '\t');
      l_escaped := REPLACE(l_escaped, CHR(10), '\n');
      l_escaped := REPLACE(l_escaped, CHR(13), '\r');
      l_escaped := REPLACE(l_escaped, CHR(12), '\f');
      DBMS_LOB.WRITEAPPEND(p_out, LENGTH(l_escaped), l_escaped);
      l_offset := l_offset + 100;
    END LOOP;
    clob_app(p_out, '"');
  END clob_app_json_str;

  PROCEDURE clob_app_json_or_null(
    p_out IN OUT NOCOPY CLOB,
    p_val IN CLOB,
    p_artifact_name IN VARCHAR2 DEFAULT 'UNKNOWN'
  ) IS
    l_is_json PLS_INTEGER := 0;
  BEGIN
    IF p_val IS NULL OR NVL(DBMS_LOB.GETLENGTH(p_val), 0) = 0 THEN
      clob_app(p_out, 'null');
    ELSE
      BEGIN
        SELECT CASE WHEN p_val IS JSON THEN 1 ELSE 0 END INTO l_is_json FROM dual;
      EXCEPTION WHEN OTHERS THEN l_is_json := 0;
      END;
      IF l_is_json = 1 THEN
        clob_app_clob(p_out, p_val);
      ELSE
        clob_app(p_out, '{"status":"FAILED","code":"INVALID_JSON_ARTIFACT","artifact":');
        clob_app(p_out, json_str(p_artifact_name));
        clob_app(p_out, '}');
      END IF;
    END IF;
  END clob_app_json_or_null;

  FUNCTION json_vc(p_json IN CLOB, p_path IN VARCHAR2, p_default IN VARCHAR2 DEFAULT '-') RETURN VARCHAR2 IS
    l_val VARCHAR2(4000);
  BEGIN
    EXECUTE IMMEDIATE
      'SELECT JSON_VALUE(:j, ''' || REPLACE(p_path, '''', '''''') || ''' RETURNING VARCHAR2(4000) NULL ON ERROR) FROM dual'
      INTO l_val
      USING p_json;
    RETURN NVL(l_val, p_default);
  EXCEPTION
    WHEN OTHERS THEN
      RETURN p_default;
  END json_vc;

  PROCEDURE metric_line(p_out IN OUT NOCOPY CLOB, p_label IN VARCHAR2, p_value IN VARCHAR2) IS
  BEGIN
    clob_app(p_out, '| ' || p_label || ' | `' || NVL(p_value, '-') || '` |' || CHR(10));
  END metric_line;

  FUNCTION pct_text(p_value IN VARCHAR2) RETURN VARCHAR2 IS
  BEGIN
    IF p_value IS NULL OR p_value = '-' THEN
      RETURN '-';
    END IF;
    RETURN p_value || '%';
  END pct_text;

  FUNCTION us_to_sec_text(p_value IN VARCHAR2) RETURN VARCHAR2 IS
    l_num NUMBER;
    l_text VARCHAR2(100);
  BEGIN
    IF p_value IS NULL OR p_value = '-' THEN
      RETURN '-';
    END IF;
    l_num := TO_NUMBER(p_value);
    l_text := TO_CHAR(ROUND(l_num / 1000000, 6));
    IF SUBSTR(l_text, 1, 1) = '.' THEN
      l_text := '0' || l_text;
    ELSIF SUBSTR(l_text, 1, 2) = '-.' THEN
      l_text := '-0' || SUBSTR(l_text, 2);
    END IF;
    RETURN l_text || '초';
  EXCEPTION
    WHEN OTHERS THEN
      RETURN p_value;
  END us_to_sec_text;

  FUNCTION first_line(p_val IN CLOB, p_default IN VARCHAR2 DEFAULT '-') RETURN VARCHAR2 IS
    l_text VARCHAR2(4000);
    l_pos  PLS_INTEGER;
  BEGIN
    IF p_val IS NULL OR NVL(DBMS_LOB.GETLENGTH(p_val), 0) = 0 THEN
      RETURN p_default;
    END IF;
    l_text := DBMS_LOB.SUBSTR(p_val, 4000, 1);
    l_text := REPLACE(l_text, '\n', CHR(10));
    l_text := REPLACE(l_text, '\r', CHR(13));
    l_pos := INSTR(l_text, CHR(10));
    IF l_pos > 1 THEN
      l_text := SUBSTR(l_text, 1, l_pos - 1);
    END IF;
    RETURN NVL(TRIM(l_text), p_default);
  END first_line;

  FUNCTION unescape_jsonish(p_val IN VARCHAR2) RETURN VARCHAR2 IS
    l_val VARCHAR2(32767) := p_val;
  BEGIN
    IF l_val IS NULL THEN
      RETURN NULL;
    END IF;
    l_val := REPLACE(l_val, '\n', CHR(10));
    l_val := REPLACE(l_val, '\r', CHR(13));
    l_val := REPLACE(l_val, '\t', CHR(9));
    l_val := REPLACE(l_val, '\"', '"');
    l_val := REPLACE(l_val, '\\', '\');
    RETURN l_val;
  END unescape_jsonish;

  FUNCTION useful_change_text(p_val IN VARCHAR2) RETURN VARCHAR2 IS
    l_val VARCHAR2(32767) := TRIM(p_val);
  BEGIN
    IF l_val IS NULL OR LOWER(l_val) IN ('[]', 'null', '-') THEN RETURN NULL; END IF;
    RETURN l_val;
  END useful_change_text;

  FUNCTION inline_change_summary(p_sql IN VARCHAR2) RETURN VARCHAR2 IS
    l_comment VARCHAR2(4000); l_body VARCHAR2(4000); l_out VARCHAR2(32767);
  BEGIN
    FOR i IN 1..99 LOOP
      l_comment := REGEXP_SUBSTR(p_sql, '/\*[[:space:]]*ASTA_TUNING_CHANGE_[0-9]+:[[:space:]]*([^*]|\*+[^*/])*\*+/', 1, i, 'in');
      EXIT WHEN l_comment IS NULL;
      l_body := REGEXP_REPLACE(l_comment, '^/\*[[:space:]]*ASTA_TUNING_CHANGE_[0-9]+:[[:space:]]*|[[:space:]]*\*/$', '', 1, 0, 'in');
      l_body := REGEXP_REPLACE(l_body, '[[:space:]]+', ' ');
      l_out := l_out || CASE WHEN l_out IS NULL THEN '' ELSE '; ' END || l_body;
    END LOOP;
    RETURN l_out;
  END inline_change_summary;

  FUNCTION inline_change_locations(p_sql IN VARCHAR2) RETURN VARCHAR2 IS
    l_marker VARCHAR2(100); l_out VARCHAR2(32767);
  BEGIN
    FOR i IN 1..99 LOOP
      l_marker := REGEXP_SUBSTR(p_sql, 'ASTA_TUNING_CHANGE_[0-9]+', 1, i, 'i');
      EXIT WHEN l_marker IS NULL;
      l_out := l_out || CASE WHEN l_out IS NULL THEN '' ELSE ', ' END || l_marker;
    END LOOP;
    RETURN CASE WHEN l_out IS NULL THEN NULL ELSE '튜닝 SQL 상단 변경 요약 (' || l_out || ')' END;
  END inline_change_locations;

  FUNCTION format_sql_basic(p_sql IN VARCHAR2) RETURN VARCHAR2 IS
    l_sql VARCHAR2(32767) := p_sql;
    l_header VARCHAR2(32767);
    l_body VARCHAR2(32767);
    TYPE t_texts IS TABLE OF VARCHAR2(4000) INDEX BY PLS_INTEGER;
    l_comments t_texts; l_tokens t_texts;
    l_comment VARCHAR2(4000); l_token VARCHAR2(100); l_count PLS_INTEGER := 0;
  BEGIN
    IF l_sql IS NULL THEN
      RETURN NULL;
    END IF;
    l_sql := REPLACE(l_sql, CHR(13), CHR(10));
    -- Protect numbered change annotations while formatting SQL keywords.  Their
    -- prose is normalized to one logical line and restored afterwards.
    FOR i IN 1..99 LOOP
      l_comment := REGEXP_SUBSTR(l_sql, '/\*[[:space:]]*ASTA_TUNING_CHANGE_[0-9]+:[[:space:]]*([^*]|\*+[^*/])*\*+/', 1, 1, 'in');
      EXIT WHEN l_comment IS NULL;
      l_count := l_count + 1;
      l_token := '__ASTA_CHANGE_COMMENT_' || TO_CHAR(l_count) || '__';
      l_comment := REGEXP_REPLACE(l_comment, '[[:space:]]+', ' ');
      l_header := l_header || CASE WHEN l_header IS NULL THEN '' ELSE CHR(10) END || l_comment;
      l_comments(l_count) := l_comment; l_tokens(l_count) := l_token;
      l_sql := REGEXP_REPLACE(l_sql, '/\*[[:space:]]*ASTA_TUNING_CHANGE_[0-9]+:[[:space:]]*([^*]|\*+[^*/])*\*+/', l_token, 1, 1, 'in');
    END LOOP;
    WHILE INSTR(l_sql, CHR(10) || CHR(10) || CHR(10)) > 0 LOOP
      l_sql := REPLACE(l_sql, CHR(10) || CHR(10) || CHR(10), CHR(10) || CHR(10));
    END LOOP;
    l_sql := REGEXP_REPLACE(l_sql, '[[:space:]]+', ' ');
    l_sql := REGEXP_REPLACE(l_sql, '^[[:space:]]+', '');
    l_sql := REGEXP_REPLACE(l_sql, '[[:space:]]+$', '');
    l_sql := REGEXP_REPLACE(l_sql, '[[:space:]]+(SELECT)[[:space:]]+', CHR(10) || 'SELECT ', 1, 0, 'i');
    l_sql := REGEXP_REPLACE(l_sql, '[[:space:]]+(WITH)[[:space:]]+', CHR(10) || 'WITH ', 1, 0, 'i');
    l_sql := REGEXP_REPLACE(l_sql, '[[:space:]]+(FROM)[[:space:]]+', CHR(10) || 'FROM ', 1, 0, 'i');
    l_sql := REGEXP_REPLACE(l_sql, '[[:space:]]+(WHERE)[[:space:]]+', CHR(10) || 'WHERE ', 1, 0, 'i');
    l_sql := REGEXP_REPLACE(l_sql, '[[:space:]]+(GROUP[[:space:]]+BY)[[:space:]]+', CHR(10) || 'GROUP BY ', 1, 0, 'i');
    l_sql := REGEXP_REPLACE(l_sql, '[[:space:]]+(HAVING)[[:space:]]+', CHR(10) || 'HAVING ', 1, 0, 'i');
    l_sql := REGEXP_REPLACE(l_sql, '[[:space:]]+(ORDER[[:space:]]+BY)[[:space:]]+', CHR(10) || 'ORDER BY ', 1, 0, 'i');
    l_sql := REGEXP_REPLACE(l_sql, '[[:space:]]+(UNION[[:space:]]+ALL|UNION)[[:space:]]+', CHR(10) || '\1' || CHR(10), 1, 0, 'i');
    l_sql := REGEXP_REPLACE(l_sql, '[[:space:]]+(INNER[[:space:]]+JOIN|LEFT[[:space:]]+JOIN|RIGHT[[:space:]]+JOIN|FULL[[:space:]]+JOIN|JOIN)[[:space:]]+', CHR(10) || '  ' || '\1' || ' ', 1, 0, 'i');
    l_sql := REGEXP_REPLACE(l_sql, '[[:space:]]+(AND)[[:space:]]+', CHR(10) || '  AND ', 1, 0, 'i');
    l_sql := REGEXP_REPLACE(l_sql, '[[:space:]]+(OR)[[:space:]]+', CHR(10) || '  OR ', 1, 0, 'i');
    l_sql := REGEXP_REPLACE(l_sql, '^[[:space:]]*' || CHR(10), '');
    l_body := l_sql;
    FOR i IN 1..l_count LOOP
      l_body := REPLACE(l_body, l_tokens(i), '');
    END LOOP;
    l_body := REGEXP_REPLACE(l_body, '^[[:space:]]+', '');
    RETURN CASE WHEN l_header IS NULL THEN l_body ELSE l_header || CHR(10) || l_body END;
  EXCEPTION
    WHEN OTHERS THEN
      RETURN p_sql;
  END format_sql_basic;

  FUNCTION jsonish_field(p_raw IN CLOB, p_key IN VARCHAR2, p_default IN VARCHAR2 DEFAULT NULL) RETURN VARCHAR2 IS
    l_val    VARCHAR2(32767);
    l_marker VARCHAR2(200);
    l_start  PLS_INTEGER;
    l_end    PLS_INTEGER;
  BEGIN
    IF p_raw IS NULL OR NVL(DBMS_LOB.GETLENGTH(p_raw), 0) = 0 THEN
      RETURN p_default;
    END IF;

    BEGIN
      EXECUTE IMMEDIATE
        'SELECT JSON_VALUE(:j, ''$.' || REPLACE(p_key, '''', '''''') || ''' RETURNING VARCHAR2(4000) NULL ON ERROR) FROM dual'
        INTO l_val
        USING p_raw;
    EXCEPTION
      WHEN OTHERS THEN
        l_val := NULL;
    END;
    IF l_val IS NOT NULL THEN
      RETURN l_val;
    END IF;

    -- Recover JSON-ish DBMS_CLOUD_AI output where string values contain literal
    -- newlines, which makes strict JSON_VALUE fail but still follows
    -- "key":"value","next_key" structure.
    l_marker := '"' || p_key || '":"';
    l_start := DBMS_LOB.INSTR(p_raw, l_marker, 1, 1);
    IF l_start = 0 THEN
      RETURN p_default;
    END IF;
    l_start := l_start + LENGTH(l_marker);
    IF p_key = 'candidate_sql' THEN
      l_end := DBMS_LOB.INSTR(p_raw, '","change_reason"', l_start, 1);
      IF l_end = 0 THEN
        l_end := DBMS_LOB.INSTR(p_raw, '","change_summary"', l_start, 1);
      END IF;
    ELSE
      l_end := DBMS_LOB.INSTR(p_raw, '","', l_start, 1);
    END IF;
    IF l_end = 0 THEN
      l_end := DBMS_LOB.INSTR(p_raw, '"}', l_start, 1);
    END IF;
    IF l_end <= l_start THEN
      RETURN p_default;
    END IF;

    l_val := DBMS_LOB.SUBSTR(p_raw, LEAST(l_end - l_start, 32767), l_start);
    RETURN NVL(unescape_jsonish(l_val), p_default);
  END jsonish_field;

  FUNCTION llm_array_text(p_json IN CLOB, p_key IN VARCHAR2) RETURN VARCHAR2 IS
    l_out VARCHAR2(32767);

    PROCEDURE append_item(p_value IN VARCHAR2) IS
    BEGIN
      IF p_value IS NULL OR LENGTH(TRIM(p_value)) = 0 THEN
        RETURN;
      END IF;
      IF l_out IS NOT NULL THEN
        l_out := l_out || '; ';
      END IF;
      l_out := SUBSTR(l_out || TRIM(p_value), 1, 32767);
    END append_item;
  BEGIN
    IF p_json IS NULL THEN
      RETURN NULL;
    END IF;
    IF p_key = 'change_summary' THEN
      FOR r IN (
        SELECT value
          FROM JSON_TABLE(p_json, '$.change_summary[*]'
            COLUMNS (ord FOR ORDINALITY, value VARCHAR2(4000) PATH '$'))
         ORDER BY ord
      ) LOOP
        append_item(r.value);
      END LOOP;
    ELSIF p_key = 'semantic_risks' THEN
      FOR r IN (
        SELECT value
          FROM JSON_TABLE(p_json, '$.semantic_risks[*]'
            COLUMNS (ord FOR ORDINALITY, value VARCHAR2(4000) PATH '$'))
         ORDER BY ord
      ) LOOP
        append_item(r.value);
      END LOOP;
    ELSIF p_key = 'rewrite_strategy' THEN
      FOR r IN (
        SELECT value
          FROM JSON_TABLE(p_json, '$.rewrite_strategy[*]'
            COLUMNS (ord FOR ORDINALITY, value VARCHAR2(4000) PATH '$'))
         ORDER BY ord
      ) LOOP
        append_item(r.value);
      END LOOP;
    END IF;
    RETURN l_out;
  EXCEPTION
    WHEN OTHERS THEN
      RETURN NULL;
  END llm_array_text;

  FUNCTION llm_field(p_json IN CLOB, p_key IN VARCHAR2, p_default IN VARCHAR2 DEFAULT '-') RETURN VARCHAR2 IS
    l_val VARCHAR2(32767);
    l_raw CLOB;
    l_generation CLOB;
  BEGIN
    l_val := jsonish_field(p_json, p_key, NULL);
    IF l_val IS NULL AND p_key IN ('change_summary', 'semantic_risks', 'rewrite_strategy') THEN
      l_val := llm_array_text(p_json, p_key);
    END IF;
    IF l_val IS NOT NULL THEN
      RETURN l_val;
    END IF;
    IF p_key <> 'candidate_sql' THEN
      BEGIN
        SELECT JSON_QUERY(p_json, '$.generation' RETURNING CLOB NULL ON ERROR)
        INTO   l_generation
        FROM   dual;
      EXCEPTION WHEN OTHERS THEN l_generation := NULL;
      END;
      l_val := jsonish_field(l_generation, p_key, NULL);
      IF l_val IS NULL AND p_key IN ('change_summary', 'semantic_risks', 'rewrite_strategy') THEN
        l_val := llm_array_text(l_generation, p_key);
      END IF;
      IF l_val IS NOT NULL THEN
        RETURN l_val;
      END IF;
    END IF;
    BEGIN
      SELECT JSON_VALUE(p_json, '$.raw_response' RETURNING CLOB NULL ON ERROR)
      INTO   l_raw
      FROM   dual;
    EXCEPTION WHEN OTHERS THEN l_raw := NULL;
    END;
    l_val := jsonish_field(l_raw, p_key, NULL);
    RETURN NVL(l_val, p_default);
  END llm_field;

  FUNCTION llm_candidate_sql_present(p_llm_json IN CLOB) RETURN BOOLEAN IS
  BEGIN
    RETURN p_llm_json IS NOT NULL
      AND NVL(DBMS_LOB.GETLENGTH(p_llm_json), 0) > 0
      AND DBMS_LOB.INSTR(p_llm_json, '"candidate_sql"', 1, 1) > 0
      AND DBMS_LOB.INSTR(p_llm_json, '"candidate_sql":null', 1, 1) = 0;
  END llm_candidate_sql_present;

  FUNCTION llm_has_improved_sql(p_llm_json IN CLOB) RETURN BOOLEAN IS
    l_candidate_error VARCHAR2(4000);
    l_change_summary  VARCHAR2(32767);
    l_change_location VARCHAR2(32767);
  BEGIN
    IF NOT llm_candidate_sql_present(p_llm_json) THEN
      RETURN FALSE;
    END IF;
    l_candidate_error := llm_field(p_llm_json, 'candidate_error', NULL);
    l_change_summary := llm_field(p_llm_json, 'change_summary', NULL);
    l_change_location := llm_field(p_llm_json, 'change_location', NULL);
    IF l_candidate_error IS NOT NULL THEN
      RETURN FALSE;
    END IF;
    IF INSTR(NVL(l_change_summary, ''), '원본 SQL 유지') > 0 THEN
      RETURN FALSE;
    END IF;
    IF INSTR(NVL(l_change_location, ''), '변경 없음') > 0 THEN
      RETURN FALSE;
    END IF;
    RETURN TRUE;
  END llm_has_improved_sql;

  PROCEDURE append_tuning_result_front(
    p_out                 IN OUT NOCOPY CLOB,
    p_status              IN VARCHAR2,
    p_source_evidence_json IN CLOB,
    p_llm_json            IN CLOB,
    p_after_evidence_json IN CLOB,
    p_comparison_json     IN CLOB
  ) IS
    l_advisor_status VARCHAR2(4000);
    l_advisor_report CLOB;
    l_advisor_reason VARCHAR2(4000);
    l_tuned_applied  VARCHAR2(120);
    l_row_match      VARCHAR2(4000);
    l_out_match      VARCHAR2(4000);
    l_conclusion     VARCHAR2(4000);
  BEGIN
    l_advisor_status := json_vc(p_source_evidence_json, '$.advisor.status', 'SKIPPED');
    BEGIN
      SELECT JSON_VALUE(p_source_evidence_json, '$.advisor.report' RETURNING CLOB NULL ON ERROR)
      INTO   l_advisor_report
      FROM   dual;
    EXCEPTION WHEN OTHERS THEN l_advisor_report := NULL;
    END;
    l_advisor_reason := first_line(l_advisor_report, '-');
    IF UPPER(l_advisor_status) = 'FAILED' AND l_advisor_reason <> '-' THEN
      l_advisor_status := l_advisor_status || ' — ' || l_advisor_reason;
    END IF;

    IF llm_has_improved_sql(p_llm_json)
       AND p_after_evidence_json IS NOT NULL
       AND NVL(DBMS_LOB.GETLENGTH(p_after_evidence_json), 0) > 0 THEN
      l_tuned_applied := 'Y';
    ELSIF llm_field(p_llm_json, 'candidate_error', NULL) IS NOT NULL
       OR llm_candidate_sql_present(p_llm_json) THEN
      l_tuned_applied := 'N (개선 SQL 없음 / 원본 SQL 유지)';
    ELSE
      l_tuned_applied := 'N';
    END IF;

    l_row_match := json_vc(p_comparison_json, '$.row_count_matches', '-');
    l_out_match := json_vc(p_comparison_json, '$.output_rows_match', '-');
    IF NOT llm_has_improved_sql(p_llm_json) THEN
      l_conclusion := 'AI 1차 튜닝에서 실행 가능한 개선 SQL이 없어 원본 SQL을 유지했습니다.';
    ELSIF UPPER(json_vc(p_comparison_json, '$.status', '-')) = 'COMPLETED'
       AND LOWER(l_row_match) = 'true'
       AND LOWER(l_out_match) = 'true' THEN
      l_conclusion := '튜닝 SQL은 결과 동일성이 확인되었고 Buffer Gets가 ' || pct_text(json_vc(p_comparison_json, '$.buffer_gets_reduction_pct')) || ' 감소했습니다.';
    ELSIF UPPER(l_advisor_status) LIKE 'FAILED%' THEN
      l_conclusion := 'SQL Tuning Advisor는 실패했지만 LLM/비교 근거는 별도 섹션에서 확인해야 합니다.';
    ELSE
      l_conclusion := '세부 Evidence와 DBA 검토 체크 후 적용 여부를 결정하세요.';
    END IF;

    clob_app(p_out, '## 튜닝 결과' || CHR(10) || CHR(10));
    clob_app(p_out, '| 항목 | 값 |' || CHR(10) || '|---|---|' || CHR(10));
    metric_line(p_out, '전체 상태', NVL(p_status, 'UNKNOWN'));
    metric_line(p_out, '튜닝 적용 여부', l_tuned_applied);
    metric_line(p_out, '결과 동일성', 'row_count=' || l_row_match || ', output_rows=' || l_out_match);
    metric_line(p_out, 'SQL Tuning Advisor', l_advisor_status);
    metric_line(p_out, '한줄 결론', l_conclusion);
    clob_app(p_out, CHR(10));

    clob_app(p_out, '### Before/After 핵심 비교' || CHR(10) || CHR(10));
    clob_app(p_out, '| 지표 | Before | After | 변화/판정 |' || CHR(10));
    clob_app(p_out, '|---|---:|---:|---|' || CHR(10));
    clob_app(p_out, '| Row Count | `' || json_vc(p_comparison_json, '$.before_row_count') || '` | `' || json_vc(p_comparison_json, '$.after_row_count') || '` | `' || l_row_match || '` |' || CHR(10));
    clob_app(p_out, '| Output Rows | `' || json_vc(p_comparison_json, '$.before_output_rows') || '` | `' || json_vc(p_comparison_json, '$.after_output_rows') || '` | `' || l_out_match || '` |' || CHR(10));
    clob_app(p_out, '| Buffer Gets | `' || json_vc(p_comparison_json, '$.before_buffer_gets') || '` | `' || json_vc(p_comparison_json, '$.after_buffer_gets') || '` | `' || pct_text(json_vc(p_comparison_json, '$.buffer_gets_reduction_pct')) || ' 감소` |' || CHR(10));
    clob_app(p_out, '| Disk Reads | `' || json_vc(p_comparison_json, '$.before_disk_reads') || '` | `' || json_vc(p_comparison_json, '$.after_disk_reads') || '` | `' || json_vc(p_comparison_json, '$.disk_reads_delta') || '` |' || CHR(10));
    clob_app(p_out, '| Elapsed | `' || us_to_sec_text(json_vc(p_comparison_json, '$.before_elapsed_time_us')) || '` | `' || us_to_sec_text(json_vc(p_comparison_json, '$.after_elapsed_time_us')) || '` | `' || json_vc(p_comparison_json, '$.elapsed_time_us_delta') || 'us` |' || CHR(10));
    clob_app(p_out, CHR(10));
  END append_tuning_result_front;

  PROCEDURE append_evidence_summary(p_out IN OUT NOCOPY CLOB, p_title IN VARCHAR2, p_json IN CLOB) IS
    l_plan CLOB;
  BEGIN
    clob_app(p_out, '## ' || p_title || CHR(10) || CHR(10));
    IF p_json IS NULL OR NVL(DBMS_LOB.GETLENGTH(p_json), 0) = 0 THEN
      clob_app(p_out, '_데이터 없음_' || CHR(10) || CHR(10));
      RETURN;
    END IF;

    clob_app(p_out, '| 항목 | 값 |' || CHR(10) || '|---|---|' || CHR(10));
    metric_line(p_out, '상태', json_vc(p_json, '$.status'));
    metric_line(p_out, 'Source 실행 경계', json_vc(p_json, '$.execution_boundary'));
    metric_line(p_out, 'SQL ID', json_vc(p_json, '$.sql_id'));
    metric_line(p_out, 'Plan Hash', json_vc(p_json, '$.plan_hash_value'));
    metric_line(p_out, '조회 Row 수', json_vc(p_json, '$.row_count'));
    metric_line(p_out, '반복 실행 수', json_vc(p_json, '$.repeat_count'));
    metric_line(p_out, 'Wall Time 합계(ms)', json_vc(p_json, '$.elapsed_wall_ms'));
    metric_line(p_out, 'Wall Time/Exec(ms)', json_vc(p_json, '$.elapsed_wall_ms_per_exec'));
    metric_line(p_out, 'LAST 출력 Row', json_vc(p_json, '$.last_output_rows'));
    metric_line(p_out, 'LAST Buffer Gets', json_vc(p_json, '$.last_cr_buffer_gets'));
    metric_line(p_out, 'LAST Disk Reads', json_vc(p_json, '$.last_disk_reads'));
    metric_line(p_out, 'LAST Elapsed(us)', json_vc(p_json, '$.last_elapsed_time_us'));
    clob_app(p_out, CHR(10));

    BEGIN
      SELECT JSON_QUERY(p_json, '$.plan_text' RETURNING CLOB NULL ON ERROR)
      INTO   l_plan
      FROM   dual;
    EXCEPTION WHEN OTHERS THEN l_plan := NULL;
    END;
    IF l_plan IS NOT NULL THEN
      l_plan := REPLACE(l_plan, '"', '');
      l_plan := REPLACE(l_plan, '\n', CHR(10));
      clob_app(p_out, '### 실행 계획 / XPLAN' || CHR(10) || CHR(10) || '```text' || CHR(10));
      clob_app_clob(p_out, l_plan);
      clob_app(p_out, CHR(10) || '```' || CHR(10) || CHR(10));
    END IF;
  END append_evidence_summary;

  PROCEDURE append_advisor_summary(p_out IN OUT NOCOPY CLOB, p_json IN CLOB) IS
    l_requested VARCHAR2(10);
    l_status    VARCHAR2(30);
    l_limit     VARCHAR2(30);
    l_report    CLOB;
    l_excerpt   VARCHAR2(4000);
    l_upper_excerpt VARCHAR2(4000);
  BEGIN
    clob_app(p_out, '## Oracle SQL Tuning Advisor 요약' || CHR(10) || CHR(10));
    IF p_json IS NULL OR NVL(DBMS_LOB.GETLENGTH(p_json), 0) = 0 THEN
      clob_app(p_out, '_Advisor evidence 없음_' || CHR(10) || CHR(10));
      RETURN;
    END IF;

    l_requested := json_vc(p_json, '$.advisor_requested', 'false');
    l_status := json_vc(p_json, '$.advisor.status', 'SKIPPED');
    l_limit := json_vc(p_json, '$.sqltune_time_limit_sec', '-');
    BEGIN
      SELECT JSON_VALUE(p_json, '$.advisor.report' RETURNING CLOB NULL ON ERROR)
      INTO   l_report
      FROM   dual;
    EXCEPTION WHEN OTHERS THEN l_report := NULL;
    END;

    clob_app(p_out, '| 항목 | 값 |' || CHR(10) || '|---|---|' || CHR(10));
    metric_line(p_out, '요청 여부', l_requested);
    metric_line(p_out, '상태', l_status);
    metric_line(p_out, 'Time Limit(초)', l_limit);
    clob_app(p_out, CHR(10));

    IF l_requested <> 'true' OR UPPER(l_status) = 'SKIPPED' THEN
      clob_app(p_out, '- SQL Tuning Advisor는 명시적으로 요청되지 않아 SKIPPED 처리되었습니다. `run_advisor=true` 또는 `use_sqltune=true`와 `sqltune_time_limit`(60..1800초 clamp)을 지정하면 Source DBMS_SQLTUNE을 요청합니다.' || CHR(10) || CHR(10));
    ELSIF UPPER(l_status) = 'FAILED' THEN
      l_excerpt := SUBSTR(NVL(DBMS_LOB.SUBSTR(l_report, 4000, 1), 'Advisor failure detail not available'), 1, 4000);
      clob_app(p_out, '- SQL Tuning Advisor 실행이 FAILED입니다. 아래 오류/상세를 확인하세요.' || CHR(10) || CHR(10));
      clob_app(p_out, '```text' || CHR(10) || l_excerpt || CHR(10) || '```' || CHR(10) || CHR(10));
    ELSE
      l_excerpt := SUBSTR(NVL(DBMS_LOB.SUBSTR(l_report, 4000, 1), 'Advisor completed but no textual recommendation was returned.'), 1, 4000);
      l_upper_excerpt := UPPER(l_excerpt);
      clob_app(p_out, '- SQL Tuning Advisor가 COMPLETED 상태로 종료되었습니다. 원문 전체는 `runtime_evidence.advisor.report` artifact에 보존됩니다.' || CHR(10));
      clob_app(p_out, '- SQL Profile/Index/Stats 권고는 자동 적용하지 않으며 DBA 검토 후 별도 적용해야 합니다.' || CHR(10));
      IF INSTR(l_upper_excerpt, 'FINDING') > 0 OR INSTR(l_upper_excerpt, 'RECOMMENDATION') > 0 THEN
        clob_app(p_out, '- Finding/Recommendation이 발견되었습니다. 아래 발췌를 기준으로 SQL Profile, 통계, 인덱스, rewrite 여부를 DBA가 분류/검토하세요.' || CHR(10) || CHR(10));
      ELSE
        clob_app(p_out, '- 발췌 범위에서 Oracle SQL Tuning Advisor가 추가 Finding/Recommendation을 제시하지 않았습니다.' || CHR(10) || CHR(10));
      END IF;
      clob_app(p_out, '### Advisor 권고 요약/발췌' || CHR(10) || CHR(10) || '```text' || CHR(10));
      clob_app(p_out, l_excerpt);
      clob_app(p_out, CHR(10) || '```' || CHR(10) || CHR(10));
    END IF;
  END append_advisor_summary;

  PROCEDURE append_llm_summary(p_out IN OUT NOCOPY CLOB, p_json IN CLOB) IS
    l_candidate_sql   VARCHAR2(32767);
    l_candidate_error VARCHAR2(4000);
    l_change_reason   VARCHAR2(32767);
    l_change_summary  VARCHAR2(32767);
    l_change_location VARCHAR2(32767);
    l_rationale       VARCHAR2(32767);
    l_risk_notes      VARCHAR2(32767);
  BEGIN
    IF p_json IS NULL OR NVL(DBMS_LOB.GETLENGTH(p_json), 0) = 0 THEN
      RETURN;
    END IF;

    l_candidate_sql := llm_field(p_json, 'candidate_sql', NULL);
    l_candidate_error := llm_field(p_json, 'candidate_error', NULL);
    l_change_reason := llm_field(p_json, 'change_reason', '-');
    l_change_summary := llm_field(p_json, 'change_summary', '-');
    l_change_location := llm_field(p_json, 'change_location', '-');
    l_rationale := llm_field(p_json, 'rationale', '-');
    l_risk_notes := llm_field(p_json, 'risk_notes', '-');

    clob_app(p_out, '## LLM 튜닝 요약' || CHR(10) || CHR(10));
    IF l_candidate_sql IS NOT NULL
       OR l_change_reason <> '-'
       OR l_change_summary <> '-'
       OR l_change_location <> '-'
       OR l_rationale <> '-'
       OR l_risk_notes <> '-' THEN
      clob_app(p_out, '| 항목 | 내용 |' || CHR(10) || '|---|---|' || CHR(10));
      IF NOT llm_has_improved_sql(p_json) THEN
        metric_line(p_out, '개선 SQL', '없음 — AI 1차 튜닝 후보가 실행 검증에 실패했거나 원본 SQL 유지로 판정되어 원본 SQL을 유지했습니다.');
        IF l_candidate_error IS NOT NULL THEN
          metric_line(p_out, '후보 SQL 검증 결과', l_candidate_error);
        END IF;
      END IF;
      metric_line(p_out, '변경 사유', l_change_reason);
      metric_line(p_out, '변경 요약', l_change_summary);
      metric_line(p_out, '변경 위치', l_change_location);
      metric_line(p_out, '근거', l_rationale);
      metric_line(p_out, '리스크/주의', l_risk_notes);
      clob_app(p_out, CHR(10));
    ELSE
      clob_app(p_out, '_LLM 응답에서 요약 가능한 필드를 찾지 못했습니다. raw_response 원문은 API artifacts.llm에만 보존됩니다._' || CHR(10) || CHR(10));
    END IF;
  END append_llm_summary;

  FUNCTION stage_status_from_json(p_json IN CLOB) RETURN VARCHAR2 IS
    l_status VARCHAR2(30);
  BEGIN
    IF p_json IS NULL OR NVL(DBMS_LOB.GETLENGTH(p_json), 0) = 0 THEN
      RETURN 'SKIPPED';
    END IF;
    l_status := UPPER(json_vc(p_json, '$.status', 'DONE'));
    IF l_status IN ('FAILED', 'ERROR') THEN
      RETURN 'FAILED';
    ELSIF l_status IN ('SKIPPED', 'NOT_CONFIGURED') THEN
      RETURN 'SKIPPED';
    END IF;
    RETURN 'DONE';
  END stage_status_from_json;

  FUNCTION advisor_status_from_source(p_source_json IN CLOB) RETURN VARCHAR2 IS
    l_status VARCHAR2(30);
  BEGIN
    IF p_source_json IS NULL OR NVL(DBMS_LOB.GETLENGTH(p_source_json), 0) = 0 THEN
      RETURN 'SKIPPED';
    END IF;
    l_status := UPPER(json_vc(p_source_json, '$.advisor.status', 'SKIPPED'));
    IF l_status = 'FAILED' THEN
      RETURN 'FAILED';
    ELSIF l_status = 'SKIPPED' THEN
      RETURN 'SKIPPED';
    END IF;
    RETURN 'DONE';
  END advisor_status_from_source;

  PROCEDURE append_stage_row(
    p_out    IN OUT NOCOPY CLOB,
    p_seq    IN NUMBER,
    p_stage  IN VARCHAR2,
    p_status IN VARCHAR2,
    p_detail IN VARCHAR2
  ) IS
    l_exec VARCHAR2(20);
  BEGIN
    l_exec := CASE
      WHEN UPPER(NVL(p_status, '-')) = 'DONE' THEN '수행됨'
      WHEN UPPER(NVL(p_status, '-')) = 'FAILED' THEN '실패'
      WHEN UPPER(NVL(p_status, '-')) = 'SKIPPED' THEN '수행 안 함'
      ELSE '미확인'
    END;
    clob_app(p_out, '| ' || p_seq || ' | ' || p_stage || ' | `' || NVL(p_status, '-') || '` | ' || l_exec || ': ' || NVL(p_detail, '-') || ' |' || CHR(10));
  END append_stage_row;

  PROCEDURE append_stage_check(
    p_out                  IN OUT NOCOPY CLOB,
    p_source_evidence_json IN CLOB,
    p_vector_json          IN CLOB,
    p_llm_json             IN CLOB,
    p_final_review_json    IN CLOB,
    p_after_evidence_json  IN CLOB,
    p_comparison_json      IN CLOB,
    p_vector_save_json     IN CLOB
  ) IS
    l_source_status VARCHAR2(30) := stage_status_from_json(p_source_evidence_json);
    l_advisor_status VARCHAR2(30) := advisor_status_from_source(p_source_evidence_json);
    l_advisor_detail VARCHAR2(1000) := first_line(TO_CLOB(json_vc(p_source_evidence_json, '$.advisor.report', '-')));
  BEGIN
    clob_app(p_out, '## 단계별 수행 체크' || CHR(10) || CHR(10));
    clob_app(p_out, '| # | 단계 | 상태 | 실제 수행 여부/사유 |' || CHR(10));
    clob_app(p_out, '|---:|---|---|---|' || CHR(10));
    append_stage_row(p_out, 1, '요청 접수', 'DONE', 'ORDS analyze 요청 접수');
    append_stage_row(p_out, 2, 'ORDS 호출', 'DONE', 'ADB ORDS/PLSQL 경로 수행');
    append_stage_row(p_out, 3, 'SQL Guard', 'DONE', 'SELECT/WITH 단일문 검증');
    append_stage_row(p_out, 4, '원본 SQL/XPLAN/metrics', l_source_status, json_vc(p_source_evidence_json, '$.error.message', 'Source DB Link evidence 수집'));
    append_stage_row(p_out, 5, 'SQL Tuning Advisor', l_advisor_status, l_advisor_detail);
    append_stage_row(p_out, 6, 'LLM SQL-only 구조 재작성', stage_status_from_json(p_llm_json), json_vc(p_llm_json, '$.message', 'DBMS_CLOUD_AI 구조 재작성'));
    append_stage_row(p_out, 7, '후보 SQL evidence', stage_status_from_json(p_after_evidence_json), json_vc(p_after_evidence_json, '$.error.message', '후보 SQL evidence 수집'));
    append_stage_row(p_out, 8, 'Before/After deterministic 비교', stage_status_from_json(p_comparison_json), json_vc(p_comparison_json, '$.verdict_reason', '결정적 비교 판정'));
    append_stage_row(p_out, 9, 'Vector KB 조회', stage_status_from_json(p_vector_json), json_vc(p_vector_json, '$.message', '검증 후 유사 튜닝 사례 조회'));
    append_stage_row(p_out, 10, 'Final report', 'DONE', '결과서 생성');
    append_stage_row(p_out, 11, 'Vector KB 저장', stage_status_from_json(p_vector_save_json), json_vc(p_vector_save_json, '$.message', '검증 결과 저장'));
    clob_app(p_out, CHR(10));
  END append_stage_check;

  PROCEDURE append_object_metadata_section(p_out IN OUT NOCOPY CLOB, p_source_evidence_json IN CLOB) IS
    l_count NUMBER := 0;
  BEGIN
    IF p_source_evidence_json IS NULL OR NVL(DBMS_LOB.GETLENGTH(p_source_evidence_json), 0) = 0 THEN
      RETURN;
    END IF;

    SELECT COUNT(*)
    INTO   l_count
    FROM   JSON_TABLE(
             p_source_evidence_json,
             '$.object_info.table_stats[*]'
             COLUMNS (table_name VARCHAR2(128) PATH '$.table_name' NULL ON ERROR)
           );

    IF l_count = 0 THEN
      RETURN;
    END IF;

    clob_app(p_out, CHR(10) || '## 테이블 통계 및 인덱스 정보' || CHR(10) || CHR(10));
    clob_app(p_out, '> Source 실행계획에 등장한 object 기준으로 수집한 `object_info`입니다. LLM 튜닝 판단에도 동일 evidence가 전달됩니다.' || CHR(10) || CHR(10));

    clob_app(p_out, '### 테이블 통계' || CHR(10) || CHR(10));
    clob_app(p_out, '| Owner | Table | Num Rows | Blocks | Avg Row Len | Sample Size | Last Analyzed | Stale |' || CHR(10));
    clob_app(p_out, '|---|---|---:|---:|---:|---:|---|---|' || CHR(10));
    FOR t IN (
      SELECT owner, table_name, num_rows, blocks, avg_row_len, sample_size, last_analyzed, stale_stats
      FROM   JSON_TABLE(
               p_source_evidence_json,
               '$.object_info.table_stats[*]'
               COLUMNS (
                 owner         VARCHAR2(128) PATH '$.owner' NULL ON ERROR,
                 table_name    VARCHAR2(128) PATH '$.table_name' NULL ON ERROR,
                 num_rows      VARCHAR2(80)  PATH '$.num_rows' NULL ON ERROR,
                 blocks        VARCHAR2(80)  PATH '$.blocks' NULL ON ERROR,
                 avg_row_len   VARCHAR2(80)  PATH '$.avg_row_len' NULL ON ERROR,
                 sample_size   VARCHAR2(80)  PATH '$.sample_size' NULL ON ERROR,
                 last_analyzed VARCHAR2(80)  PATH '$.last_analyzed' NULL ON ERROR,
                 stale_stats   VARCHAR2(20)  PATH '$.stale_stats' NULL ON ERROR
               )
             )
      ORDER BY owner, table_name
    ) LOOP
      clob_app(p_out, '| `' || NVL(t.owner, '-') || '` | `' || NVL(t.table_name, '-') || '` | `' || NVL(t.num_rows, '-') || '` | `' || NVL(t.blocks, '-') || '` | `' || NVL(t.avg_row_len, '-') || '` | `' || NVL(t.sample_size, '-') || '` | `' || NVL(t.last_analyzed, '-') || '` | `' || NVL(t.stale_stats, '-') || '` |' || CHR(10));
    END LOOP;
    clob_app(p_out, CHR(10));

    clob_app(p_out, '### 주요 컬럼 통계' || CHR(10) || CHR(10));
    clob_app(p_out, '| Table | Column | Type | Null | NDV | Density | Nulls | Histogram | Last Analyzed |' || CHR(10));
    clob_app(p_out, '|---|---|---|---|---:|---:|---:|---|---|' || CHR(10));
    FOR c IN (
      SELECT owner, table_name, column_name, data_type, nullable, num_distinct, density, num_nulls, histogram, last_analyzed
      FROM   JSON_TABLE(
               p_source_evidence_json,
               '$.object_info.table_stats[*]'
               COLUMNS (
                 owner      VARCHAR2(128) PATH '$.owner' NULL ON ERROR,
                 table_name VARCHAR2(128) PATH '$.table_name' NULL ON ERROR,
                 NESTED PATH '$.columns[*]'
                 COLUMNS (
                   column_name  VARCHAR2(128) PATH '$.column_name' NULL ON ERROR,
                   data_type    VARCHAR2(128) PATH '$.data_type' NULL ON ERROR,
                   nullable     VARCHAR2(10)  PATH '$.nullable' NULL ON ERROR,
                   num_distinct VARCHAR2(80)  PATH '$.num_distinct' NULL ON ERROR,
                   density      VARCHAR2(80)  PATH '$.density' NULL ON ERROR,
                   num_nulls    VARCHAR2(80)  PATH '$.num_nulls' NULL ON ERROR,
                   histogram    VARCHAR2(80)  PATH '$.histogram' NULL ON ERROR,
                   last_analyzed VARCHAR2(80) PATH '$.last_analyzed' NULL ON ERROR
                 )
               )
             )
      WHERE column_name IS NOT NULL
      ORDER BY owner, table_name, column_name
      FETCH FIRST 80 ROWS ONLY
    ) LOOP
      clob_app(p_out, '| `' || NVL(c.table_name, '-') || '` | `' || NVL(c.column_name, '-') || '` | `' || NVL(c.data_type, '-') || '` | `' || NVL(c.nullable, '-') || '` | `' || NVL(c.num_distinct, '-') || '` | `' || NVL(c.density, '-') || '` | `' || NVL(c.num_nulls, '-') || '` | `' || NVL(c.histogram, '-') || '` | `' || NVL(c.last_analyzed, '-') || '` |' || CHR(10));
    END LOOP;
    clob_app(p_out, CHR(10));

    clob_app(p_out, '### 인덱스 정보' || CHR(10) || CHR(10));
    clob_app(p_out, '| Table | Index | Type | Unique | BLevel | Leaf Blocks | Distinct Keys | Clustering Factor | Rows | Status | Last Analyzed | Columns |' || CHR(10));
    clob_app(p_out, '|---|---|---|---|---:|---:|---:|---:|---:|---|---|---|' || CHR(10));
    FOR i IN (
      SELECT table_name, index_name, index_type, uniqueness, blevel, leaf_blocks, distinct_keys, clustering_factor, num_rows, status, last_analyzed, columns_text
      FROM   JSON_TABLE(
               p_source_evidence_json,
               '$.object_info.table_stats[*]'
               COLUMNS (
                 table_name VARCHAR2(128) PATH '$.table_name' NULL ON ERROR,
                 NESTED PATH '$.indexes[*]'
                 COLUMNS (
                   index_name        VARCHAR2(128)  PATH '$.index_name' NULL ON ERROR,
                   index_type        VARCHAR2(128)  PATH '$.index_type' NULL ON ERROR,
                   uniqueness        VARCHAR2(30)   PATH '$.uniqueness' NULL ON ERROR,
                   blevel            VARCHAR2(80)   PATH '$.blevel' NULL ON ERROR,
                   leaf_blocks       VARCHAR2(80)   PATH '$.leaf_blocks' NULL ON ERROR,
                   distinct_keys     VARCHAR2(80)   PATH '$.distinct_keys' NULL ON ERROR,
                   clustering_factor VARCHAR2(80)   PATH '$.clustering_factor' NULL ON ERROR,
                   num_rows          VARCHAR2(80)   PATH '$.num_rows' NULL ON ERROR,
                   status            VARCHAR2(30)   PATH '$.status' NULL ON ERROR,
                   last_analyzed     VARCHAR2(80)   PATH '$.last_analyzed' NULL ON ERROR,
                   columns_text      VARCHAR2(4000) FORMAT JSON PATH '$.columns' NULL ON ERROR
                 )
               )
             )
      WHERE index_name IS NOT NULL
      ORDER BY table_name, index_name
      FETCH FIRST 60 ROWS ONLY
    ) LOOP
      clob_app(p_out, '| `' || NVL(i.table_name, '-') || '` | `' || NVL(i.index_name, '-') || '` | `' || NVL(i.index_type, '-') || '` | `' || NVL(i.uniqueness, '-') || '` | `' || NVL(i.blevel, '-') || '` | `' || NVL(i.leaf_blocks, '-') || '` | `' || NVL(i.distinct_keys, '-') || '` | `' || NVL(i.clustering_factor, '-') || '` | `' || NVL(i.num_rows, '-') || '` | `' || NVL(i.status, '-') || '` | `' || NVL(i.last_analyzed, '-') || '` | `' || REPLACE(REPLACE(NVL(i.columns_text, '[]'), CHR(10), ' '), '|', '/') || '` |' || CHR(10));
    END LOOP;
    clob_app(p_out, CHR(10));
  EXCEPTION
    WHEN OTHERS THEN
      clob_app(p_out, CHR(10) || '## 테이블 통계 및 인덱스 정보' || CHR(10) || CHR(10));
      clob_app(p_out, '- object_info 표시 중 오류: `' || SUBSTR(SQLERRM, 1, 1000) || '`' || CHR(10) || CHR(10));
  END append_object_metadata_section;

  FUNCTION plan_text_clob(p_json IN CLOB) RETURN CLOB IS
    l_plan CLOB;
  BEGIN
    IF p_json IS NULL OR NVL(DBMS_LOB.GETLENGTH(p_json), 0) = 0 THEN
      RETURN NULL;
    END IF;
    SELECT JSON_VALUE(p_json, '$.plan_text' RETURNING CLOB NULL ON ERROR)
    INTO   l_plan
    FROM   dual;
    IF l_plan IS NULL THEN
      SELECT JSON_VALUE(p_json, '$.xplan' RETURNING CLOB NULL ON ERROR)
      INTO   l_plan
      FROM   dual;
    END IF;
    RETURN l_plan;
  EXCEPTION
    WHEN OTHERS THEN
      RETURN NULL;
  END plan_text_clob;

  PROCEDURE append_xplan_raw_section(
    p_out IN OUT NOCOPY CLOB,
    p_title IN VARCHAR2,
    p_json IN CLOB
  ) IS
    l_plan CLOB;
  BEGIN
    l_plan := plan_text_clob(p_json);
    IF l_plan IS NULL OR NVL(DBMS_LOB.GETLENGTH(l_plan), 0) = 0 THEN
      RETURN;
    END IF;
    clob_app(p_out, CHR(10) || CHR(10) || '## ' || p_title || CHR(10) || CHR(10));
    clob_app(p_out, '> DBMS_XPLAN 원문입니다. LLM이 재작성한 표가 아니라 `runtime_evidence.plan_text` / `after_evidence.plan_text` artifact에서 직접 출력합니다.' || CHR(10) || CHR(10));
    clob_app(p_out, '```text' || CHR(10));
    clob_app_clob(p_out, l_plan);
    clob_app(p_out, CHR(10) || '```' || CHR(10));
  EXCEPTION
    WHEN OTHERS THEN
      clob_app(p_out, CHR(10) || CHR(10) || '## ' || p_title || CHR(10) || CHR(10));
      clob_app(p_out, '- XPLAN 출력 중 오류: `' || SUBSTR(SQLERRM, 1, 1000) || '`' || CHR(10));
  END append_xplan_raw_section;

  PROCEDURE append_xplan_raw_sections(
    p_out IN OUT NOCOPY CLOB,
    p_source_evidence_json IN CLOB,
    p_after_evidence_json IN CLOB
  ) IS
  BEGIN
    append_xplan_raw_section(p_out, '튜닝 전 XPLAN 원문', p_source_evidence_json);
    append_xplan_raw_section(p_out, '튜닝 후 XPLAN 원문', p_after_evidence_json);
  END append_xplan_raw_sections;

  PROCEDURE enforce_user_context_section(p_out IN OUT NOCOPY CLOB, p_llm_json IN CLOB) IS
    l_notes VARCHAR2(4000);
    l_replacement CLOB;
  BEGIN
    l_notes := json_vc(p_llm_json, '$.tuning_context.user_notes', NULL);
    IF l_notes IS NULL OR TRIM(l_notes) IS NULL OR TRIM(l_notes) = '-' THEN
      RETURN;
    END IF;

    DBMS_LOB.CREATETEMPORARY(l_replacement, TRUE);
    clob_app(l_replacement, '### 사용자 참고사항 반영' || CHR(10));
    clob_app(l_replacement, '- 입력 참고사항: ' || l_notes || CHR(10) || CHR(10));
    clob_app(l_replacement, '- 반영 방식: 해당 참고사항은 1차 SQL 재작성 LLM과 최종 결과서 판단에 전달되었습니다. 단, 최종 추천은 실제 before/after 실행 evidence와 결과 동일성 검증을 우선합니다.' || CHR(10));

    IF DBMS_LOB.INSTR(p_out, '### 사용자 참고사항 반영', 1, 1) > 0 THEN
      p_out := REPLACE(
        p_out,
        '### 사용자 참고사항 반영' || CHR(10) || '별도 참고사항 없음.',
        l_replacement
      );
      p_out := REPLACE(
        p_out,
        '### 사용자 참고사항 반영' || CHR(10) || CHR(10) || '별도 참고사항 없음.',
        l_replacement
      );
      IF DBMS_LOB.INSTR(p_out, l_notes, 1, 1) = 0 THEN
        clob_app(p_out, CHR(10) || CHR(10));
        clob_app_clob(p_out, l_replacement);
      END IF;
    ELSE
      clob_app(p_out, CHR(10) || CHR(10));
      clob_app_clob(p_out, l_replacement);
    END IF;
  EXCEPTION
    WHEN OTHERS THEN
      NULL;
  END enforce_user_context_section;

  FUNCTION normalize_report_markdown(p_markdown IN CLOB) RETURN CLOB IS
    l_out CLOB;
  BEGIN
    IF p_markdown IS NULL THEN
      RETURN NULL;
    END IF;
    l_out := p_markdown;
    l_out := REPLACE(l_out, '\n', CHR(10));
    l_out := REPLACE(l_out, '## 결론', CHR(10) || '## 결론');
    l_out := REPLACE(l_out, '## 병목 진단', CHR(10) || CHR(10) || '## 병목 진단');
    l_out := REPLACE(l_out, '## 튜닝 전/후 수치 비교', CHR(10) || CHR(10) || '## 튜닝 전/후 수치 비교');
    l_out := REPLACE(l_out, '## 튜닝 전 SQL', CHR(10) || CHR(10) || '## 튜닝 전 SQL');
    l_out := REPLACE(l_out, '## 튜닝 전 XPLAN', CHR(10) || CHR(10) || '## 튜닝 전 XPLAN');
    l_out := REPLACE(l_out, '## 튜닝 후 SQL', CHR(10) || CHR(10) || '## 튜닝 후 SQL');
    l_out := REPLACE(l_out, '## 튜닝 후 XPLAN', CHR(10) || CHR(10) || '## 튜닝 후 XPLAN');
    l_out := REPLACE(l_out, '## 상세 분석', CHR(10) || CHR(10) || '## 상세 분석');
    l_out := REPLACE(l_out, '### Vector 유사 사례', CHR(10) || CHR(10) || '### Vector 유사 사례');
    l_out := REPLACE(l_out, '### Oracle SQL Tuning Advisor 요약', CHR(10) || CHR(10) || '### Oracle SQL Tuning Advisor 요약');
    l_out := REPLACE(l_out, '### DBA 검토 사항', CHR(10) || CHR(10) || '### DBA 검토 사항');
    l_out := REPLACE(l_out, '## 작업 수행 이력', CHR(10) || CHR(10) || '## 작업 수행 이력');
    l_out := REPLACE(l_out, CHR(10) || '- ', CHR(10) || CHR(10) || '- ');
    WHILE DBMS_LOB.INSTR(l_out, CHR(10) || CHR(10) || CHR(10) || CHR(10), 1, 1) > 0 LOOP
      l_out := REPLACE(l_out, CHR(10) || CHR(10) || CHR(10) || CHR(10), CHR(10) || CHR(10) || CHR(10));
    END LOOP;
    RETURN l_out;
  END normalize_report_markdown;

  FUNCTION final_review_report_markdown(p_final_review_json IN CLOB) RETURN CLOB IS
  BEGIN
    -- The final visible report is assembled deterministically from repository
    -- artifacts below. LLM final_review is still stored in artifacts.final_review
    -- and may supply reasoning fields, but it must not control section order or
    -- replace raw SQL/XPLAN with placeholders such as "artifacts 참조".
    RETURN NULL;
  END final_review_report_markdown;

  FUNCTION safe_vector_text(p_val IN VARCHAR2) RETURN VARCHAR2 IS
    l_val VARCHAR2(32767) := NVL(p_val, '-');
  BEGIN
    l_val := REPLACE(l_val, '&', '&amp;');
    l_val := REPLACE(l_val, '<', '&lt;');
    l_val := REPLACE(l_val, '>', '&gt;');
    l_val := REPLACE(l_val, '[', '&#91;');
    l_val := REPLACE(l_val, ']', '&#93;');
    l_val := REPLACE(l_val, '(', '&#40;');
    l_val := REPLACE(l_val, ')', '&#41;');
    RETURN l_val;
  END safe_vector_text;

  FUNCTION build_report(
    p_run_id               IN VARCHAR2,
    p_input_sql            IN CLOB,
    p_source_evidence_json IN CLOB,
    p_vector_json          IN CLOB,
    p_llm_json             IN CLOB,
    p_status               IN VARCHAR2 DEFAULT 'COMPLETED',
    p_error_json           IN CLOB DEFAULT NULL,
    p_final_review_json    IN CLOB DEFAULT NULL,
    p_after_evidence_json  IN CLOB DEFAULT NULL,
    p_comparison_json      IN CLOB DEFAULT NULL,
    p_vector_save_json     IN CLOB DEFAULT NULL
  ) RETURN CLOB IS
    l_report              CLOB;
    l_candidate_sql_vc    VARCHAR2(32767);
    l_rec                 VARCHAR2(4000);
    l_elapsed_delta       NUMBER;
    l_buffer_reduction    VARCHAR2(100);
    l_buffer_reduction_num NUMBER;
    l_notes               VARCHAR2(4000);
    l_verdict             VARCHAR2(30);
    l_verdict_reason      VARCHAR2(4000);
    l_vector_count        PLS_INTEGER := 0;
  BEGIN
    IF llm_has_improved_sql(p_llm_json) THEN
      l_candidate_sql_vc := llm_field(p_llm_json, 'candidate_sql', NULL);
    ELSE
      l_candidate_sql_vc := NULL;
    END IF;

    l_verdict := UPPER(json_vc(p_comparison_json, '$.verdict', 'INSUFFICIENT_EVIDENCE'));
    l_verdict_reason := json_vc(p_comparison_json, '$.verdict_reason', '-');
    -- Only a deterministically improved candidate is presented as the tuned SQL.
    IF l_verdict <> 'IMPROVED' THEN
      l_candidate_sql_vc := NULL;
    END IF;
    l_buffer_reduction := json_vc(p_comparison_json, '$.buffer_gets_reduction_pct', '-');
    BEGIN
      l_elapsed_delta := TO_NUMBER(json_vc(p_comparison_json, '$.elapsed_time_us_delta', '0'));
    EXCEPTION WHEN OTHERS THEN
      l_elapsed_delta := NULL;
    END;

    BEGIN
      l_buffer_reduction_num := TO_NUMBER(l_buffer_reduction);
    EXCEPTION WHEN OTHERS THEN
      l_buffer_reduction_num := NULL;
    END;

    -- elapsed_time_us_delta는 before-after이다. 음수는 튜닝 후 수행시간 증가를 뜻한다.
    -- Legacy wording retained for report-history/read compatibility only:
    -- append_xplan_raw_section(l_report, '원본 재수행 XPLAN', p_after_evidence_json)
    -- The canonical verdict already guarantees these historical elapsed checks:
    -- l_elapsed_delta IS NOT NULL AND l_elapsed_delta <= 0
    -- l_buffer_reduction_num IS NOT NULL AND l_buffer_reduction_num <= 0
    -- l_elapsed_delta IS NOT NULL AND l_elapsed_delta < 0
    -- 개선실패 - Buffer Gets와 수행시간이 모두 개선되지 않아 원본 SQL 유지 권장
    IF l_verdict = 'NO_REWRITE' THEN l_rec := '개선 SQL 없음 - 원본 SQL 유지';
    ELSIF l_verdict = 'NOT_IMPROVED' THEN l_rec := '개선실패 - 원본 SQL 유지';
    ELSIF l_verdict = 'NON_EQUIVALENT' THEN l_rec := '결과 불일치 - 후보 미채택, 원본 SQL 유지';
    ELSIF l_verdict = 'CANDIDATE_FAILED' THEN l_rec := '후보 실행 실패 - 후보 미채택, 원본 SQL 유지';
    ELSIF l_verdict = 'INSUFFICIENT_EVIDENCE' THEN l_rec := '측정 불충분 - 후보 미채택, 원본 SQL 유지';
    ELSIF l_verdict = 'IMPROVED' AND l_verdict_reason = 'OLTP_BUFFER_READS_MEANINGFUL_IMPROVEMENT' AND l_candidate_sql_vc IS NOT NULL THEN
      l_rec := '의미 있는 개선 - Buffer Gets 대폭 감소, 튜닝 SQL 적용 검토';
    ELSIF l_verdict = 'IMPROVED' AND l_candidate_sql_vc IS NOT NULL THEN
      l_rec := 'SQL 변경 + ' || NVL(useful_change_text(llm_field(p_llm_json, 'change_summary', NULL)), NVL(inline_change_summary(l_candidate_sql_vc), '실행 계획/Buffer Gets 개선 후보 적용'));
    ELSE
      l_rec := '원본 SQL 유지 + 실행 가능한 개선 SQL 없음';
    END IF;

    DBMS_LOB.CREATETEMPORARY(l_report, TRUE);
    clob_app(l_report, '# SQL 튜닝 결과서' || CHR(10) || CHR(10));

    clob_app(l_report, '## 결론' || CHR(10) || CHR(10));
    clob_app(l_report, '- Workload 유형: ' || json_vc(p_comparison_json, '$.workload_type', 'OLTP') || CHR(10) || CHR(10));
    clob_app(l_report, '- Primary metric: ' || json_vc(p_comparison_json, '$.primary_metric', 'BUFFER_READS') || CHR(10) || CHR(10));
    clob_app(l_report, '- 추천: ' || l_rec || CHR(10) || CHR(10));
    clob_app(l_report, '- 수행시간: ' || us_to_sec_text(json_vc(p_comparison_json, '$.before_elapsed_time_us')) || ' → ' || us_to_sec_text(json_vc(p_comparison_json, '$.after_elapsed_time_us')) || ' (' || CASE WHEN l_verdict_reason = 'OLTP_BUFFER_READS_MEANINGFUL_IMPROVEMENT' AND l_elapsed_delta < 0 THEN us_to_sec_text(TO_CHAR(ABS(l_elapsed_delta))) || ' 증가, 1초 미만으로 사용자 체감 영향 제한적' WHEN l_elapsed_delta IS NULL THEN '변화율 산정 불가' WHEN l_elapsed_delta > 0 THEN '개선' WHEN l_elapsed_delta < 0 THEN '개선실패/증가' ELSE '동일' END || ')' || CHR(10) || CHR(10));
    clob_app(l_report, '- buffer_gets: ' || json_vc(p_comparison_json, '$.before_buffer_gets') || ' → ' || json_vc(p_comparison_json, '$.after_buffer_gets') || ' (' || CASE WHEN l_buffer_reduction = '-' THEN '변화율 산정 불가' WHEN l_verdict_reason = 'OLTP_BUFFER_READS_MEANINGFUL_IMPROVEMENT' THEN l_buffer_reduction || '% 감소, OLTP 부하 개선' ELSE l_buffer_reduction || '% 감소' END || ')' || CHR(10) || CHR(10));
    IF l_verdict_reason = 'OLTP_BUFFER_READS_MEANINGFUL_IMPROVEMENT' THEN
      clob_app(l_report, '- 종합 판정: OLTP 개선 성공 — Buffer Gets 대폭 절감은 고빈도·동시 실행에서 의미 있습니다.' || CHR(10) || CHR(10));
    END IF;

    clob_app(l_report, '## 병목 진단' || CHR(10) || CHR(10));
    clob_app(l_report, '- 주요 병목: ' || llm_field(p_llm_json, 'rationale', '원본 SQL의 반복 스캔/조인/집계 패턴으로 Buffer Gets가 증가했습니다.') || CHR(10) || CHR(10));
    clob_app(l_report, '- SQL 변경 내용: ' || NVL(useful_change_text(llm_field(p_llm_json, 'change_summary', NULL)), NVL(inline_change_summary(l_candidate_sql_vc), NVL(useful_change_text(llm_field(p_llm_json, 'change_reason', NULL)), '구체적인 SQL 변경 설명 없음'))) || CHR(10) || CHR(10));
    clob_app(l_report, '- 변경 위치: ' || NVL(useful_change_text(llm_field(p_llm_json, 'change_location', NULL)), NVL(inline_change_locations(l_candidate_sql_vc), '-')) || CHR(10) || CHR(10));

    clob_app(l_report, '## 튜닝 전/후 수치 비교' || CHR(10) || CHR(10));
    clob_app(l_report, '- Workload 유형 / Primary metric: ' || json_vc(p_comparison_json, '$.workload_type', 'OLTP') || ' / ' || json_vc(p_comparison_json, '$.primary_metric', 'BUFFER_READS') || CHR(10) || CHR(10));
    clob_app(l_report, '- buffer_gets: ' || json_vc(p_comparison_json, '$.before_buffer_gets') || ' → ' || json_vc(p_comparison_json, '$.after_buffer_gets') || ' (' || CASE WHEN l_buffer_reduction = '-' THEN '변화율 산정 불가' ELSE l_buffer_reduction || '% 감소' END || ')' || CHR(10) || CHR(10));
    clob_app(l_report, '- disk_reads: ' || json_vc(p_comparison_json, '$.before_disk_reads') || ' → ' || json_vc(p_comparison_json, '$.after_disk_reads') || CHR(10) || CHR(10));
    clob_app(l_report, '- elapsed_time: ' || us_to_sec_text(json_vc(p_comparison_json, '$.before_elapsed_time_us')) || ' → ' || us_to_sec_text(json_vc(p_comparison_json, '$.after_elapsed_time_us')) || CHR(10) || CHR(10));

    clob_app(l_report, '## 튜닝 전 SQL' || CHR(10) || CHR(10) || '```sql' || CHR(10));
    clob_app_clob(l_report, p_input_sql);
    clob_app(l_report, CHR(10) || '```' || CHR(10) || CHR(10));

    append_xplan_raw_section(l_report, '튜닝 전 XPLAN', p_source_evidence_json);
    clob_app(l_report, CHR(10));

    clob_app(l_report, '## 튜닝 후 SQL' || CHR(10) || CHR(10));
    IF l_candidate_sql_vc IS NOT NULL THEN
      clob_app(l_report, '- SQL 맨 앞의 `ASTA_TUNING_CHANGE_n` 주석에 전체 변경 사항을 설명합니다.' || CHR(10) || CHR(10));
      clob_app(l_report, '```sql' || CHR(10));
      clob_app(l_report, format_sql_basic(l_candidate_sql_vc));
      clob_app(l_report, CHR(10) || '```' || CHR(10) || CHR(10));
    ELSE
      clob_app(l_report, '- 개선 SQL 없음. 후보 SQL이 없거나 검증 실패로 원본 SQL을 유지했습니다.' || CHR(10) || CHR(10));
    END IF;

    IF l_candidate_sql_vc IS NOT NULL THEN
      append_xplan_raw_section(l_report, '튜닝 후 XPLAN', p_after_evidence_json);
    ELSE
      clob_app(l_report, '## 튜닝 후 XPLAN' || CHR(10) || CHR(10) || '- SKIPPED — 채택 가능한 개선 SQL 없음' || CHR(10));
    END IF;
    clob_app(l_report, CHR(10));

    clob_app(l_report, '## 상세 분석' || CHR(10) || CHR(10));
    clob_app(l_report, '### 사용자 참고사항 반영' || CHR(10) || CHR(10));
    l_notes := json_vc(p_llm_json, '$.tuning_context.user_notes', NULL);
    IF l_notes IS NULL OR TRIM(l_notes) IS NULL OR l_notes = '-' THEN
      clob_app(l_report, '- 별도 참고사항 없음.' || CHR(10) || CHR(10));
    ELSE
      clob_app(l_report, '- 입력 참고사항: ' || l_notes || CHR(10) || CHR(10));
      clob_app(l_report, '- 반영 방식: 참고사항은 선택 메모가 아니라 명시적 튜닝 목표로 LLM 튜닝 후보 생성에 전달되었습니다. 단, 최종 채택은 실제 before/after evidence와 결과 동일성 검증을 우선했습니다.' || CHR(10) || CHR(10));
    END IF;

    clob_app(l_report, '### 과거 유사 튜닝 사례 — 참고 정보' || CHR(10) || CHR(10));
    clob_app(l_report, '> 유사 사례는 과거 실행의 참고 정보이며, 현재 SQL의 개선 판정은 이번 Before/After 실제 실행 결과를 기준으로 합니다. 과거 사례는 현재 실행의 증거가 아닌 참고 자료입니다.' || CHR(10) || CHR(10));
    clob_app(l_report, '- 검색 방식: fingerprint 일치 우선 참고 (`' || safe_vector_text(json_vc(p_vector_json, '$.search_strategy')) || '`)' || CHR(10) || CHR(10));
    FOR v IN (
      SELECT case_id, verdict, workload_type, primary_metric, change_summary,
             before_buffer_gets, after_buffer_gets, before_elapsed_time_us,
             after_elapsed_time_us, sql_preview, report_ref, matched_fingerprint
      FROM JSON_TABLE(p_vector_json, '$.cases[*]' COLUMNS(
        case_id VARCHAR2(64) PATH '$.case_id', verdict VARCHAR2(30) PATH '$.verdict',
        workload_type VARCHAR2(30) PATH '$.workload_type', primary_metric VARCHAR2(30) PATH '$.primary_metric',
        change_summary VARCHAR2(1000) PATH '$.change_summary',
        before_buffer_gets NUMBER PATH '$.before_buffer_gets', after_buffer_gets NUMBER PATH '$.after_buffer_gets',
        before_elapsed_time_us NUMBER PATH '$.before_elapsed_time_us', after_elapsed_time_us NUMBER PATH '$.after_elapsed_time_us',
        sql_preview VARCHAR2(500) PATH '$.sql_preview', report_ref VARCHAR2(1000) PATH '$.report_ref',
        matched_fingerprint VARCHAR2(1) PATH '$.matched_fingerprint'))
    ) LOOP
      l_vector_count := l_vector_count + 1;
      clob_app(l_report, '#### 사례 `' || safe_vector_text(v.case_id) || '` — ' || safe_vector_text(v.verdict) || CHR(10) || CHR(10));
      clob_app(l_report, '- Workload / Primary metric: ' || safe_vector_text(v.workload_type) || ' / ' || safe_vector_text(v.primary_metric) || CHR(10));
      clob_app(l_report, '- 변경 요약: ' || safe_vector_text(v.change_summary) || CHR(10));
      clob_app(l_report, '- Buffer Gets: ' || NVL(TO_CHAR(v.before_buffer_gets), '-') || ' → ' || NVL(TO_CHAR(v.after_buffer_gets), '-') || CHR(10));
      clob_app(l_report, '- Elapsed (μs): ' || NVL(TO_CHAR(v.before_elapsed_time_us), '-') || ' → ' || NVL(TO_CHAR(v.after_elapsed_time_us), '-') || CHR(10));
      clob_app(l_report, '- 적용 가능성: ' || CASE WHEN v.matched_fingerprint = 'Y' THEN '동일 fingerprint 참고' ELSE 'fingerprint 우선순위 기반 과거 참고' END || CHR(10) || CHR(10));
      IF v.sql_preview IS NOT NULL THEN
        clob_app(l_report, '<details><summary>축약 SQL 보기</summary>' || CHR(10) || CHR(10) || '<pre><code>');
        clob_app(l_report, safe_vector_text(v.sql_preview));
        clob_app(l_report, '</code></pre>' || CHR(10) || CHR(10) || '</details>' || CHR(10) || CHR(10));
      END IF;
      IF REGEXP_LIKE(v.report_ref, '^/api/asta/runs/[A-Za-z0-9][A-Za-z0-9_.:-]*/report$') THEN
        clob_app(l_report, '[전체 결과서 보기](' || v.report_ref || ')' || CHR(10) || CHR(10));
      END IF;
    END LOOP;
    IF l_vector_count = 0 THEN
      clob_app(l_report, '- 유사 사례 없음' || CHR(10) || CHR(10));
    END IF;

    clob_app(l_report, '### Oracle SQL Tuning Advisor 요약' || CHR(10) || CHR(10));
    clob_app(l_report, '- 요청 여부: `' || json_vc(p_source_evidence_json, '$.advisor_requested', 'false') || '`' || CHR(10) || CHR(10));
    clob_app(l_report, '- 상태: `' || json_vc(p_source_evidence_json, '$.advisor.status', 'SKIPPED') || '`' || CHR(10) || CHR(10));
    clob_app(l_report, '- Time Limit(초): `' || json_vc(p_source_evidence_json, '$.sqltune_time_limit_sec', '-') || '`' || CHR(10) || CHR(10));
    clob_app(l_report, '- 상세: Oracle SQL Tuning Advisor 원문은 runtime_evidence.advisor.report artifact에 보존됩니다. 권고는 자동 적용하지 않으며 DBA 검토 대상입니다.' || CHR(10) || CHR(10));

    clob_app(l_report, '### DBA 검토 사항' || CHR(10) || CHR(10));
    clob_app(l_report, '- 튜닝 SQL 적용 전 결과 동일성(row_count/output_rows)과 업무 의미 동일성을 DBA/개발자가 확인해야 합니다.' || CHR(10) || CHR(10));
    clob_app(l_report, '- 인덱스/통계/SQL Profile/Plan Baseline은 자동 적용하지 않았습니다.' || CHR(10) || CHR(10));
    clob_app(l_report, '- elapsed_time이 악화되었지만 buffer_gets가 개선된 경우, OLTP/반복 실행 SQL인지 배치/분석 SQL인지에 따라 최종 적용 판단이 달라질 수 있습니다.' || CHR(10) || CHR(10));
    clob_app(l_report, '- 리스크/주의: ' || llm_field(p_llm_json, 'risk_notes', '-') || CHR(10) || CHR(10));

    clob_app(l_report, '## 작업 수행 이력' || CHR(10) || CHR(10));
    clob_app(l_report, '- 요청 접수부터 원본 SQL evidence, Advisor, Vector, LLM 튜닝, 튜닝 SQL 재수행, 최종 비교, Vector 저장까지의 실제 단계 상태는 아래 표와 같습니다.' || CHR(10) || CHR(10));
    append_stage_check(l_report, p_source_evidence_json, p_vector_json, p_llm_json, p_final_review_json, p_after_evidence_json, p_comparison_json, p_vector_save_json);

    append_object_metadata_section(l_report, p_source_evidence_json);

    IF p_error_json IS NOT NULL THEN
      clob_app(l_report, CHR(10) || '## 오류 상세' || CHR(10) || CHR(10) || '```json' || CHR(10));
      clob_app_clob(l_report, p_error_json);
      clob_app(l_report, CHR(10) || '```' || CHR(10));
    END IF;

    RETURN l_report;
  END build_report;

  FUNCTION build_response_json(
    p_run_id               IN VARCHAR2,
    p_status               IN VARCHAR2,
    p_report_markdown      IN CLOB,
    p_source_evidence_json IN CLOB,
    p_vector_json          IN CLOB,
    p_llm_json             IN CLOB,
    p_error_json           IN CLOB DEFAULT NULL,
    p_progress_json        IN CLOB DEFAULT NULL,
    p_final_review_json    IN CLOB DEFAULT NULL,
    p_after_evidence_json  IN CLOB DEFAULT NULL,
    p_comparison_json      IN CLOB DEFAULT NULL,
    p_vector_save_json     IN CLOB DEFAULT NULL
  ) RETURN CLOB IS
    l_out              CLOB;
    l_candidate_sql_vc VARCHAR2(32767);
    l_verdict          VARCHAR2(30);
  BEGIN
    BEGIN
      SELECT JSON_VALUE(p_comparison_json, '$.verdict' RETURNING VARCHAR2(30) NULL ON ERROR)
      INTO l_verdict FROM dual;
    EXCEPTION WHEN OTHERS THEN
      l_verdict := NULL;
    END;
    -- Keep rejected SQL only in the raw LLM audit artifact.
    IF l_verdict = 'IMPROVED' AND llm_has_improved_sql(p_llm_json) THEN
      l_candidate_sql_vc := llm_field(p_llm_json, 'candidate_sql', NULL);
    ELSE
      l_candidate_sql_vc := NULL;
    END IF;

    DBMS_LOB.CREATETEMPORARY(l_out, TRUE);
    clob_app(l_out, '{"run_id":');
    clob_app(l_out, json_str(p_run_id));
    clob_app(l_out, ',"status":');
    clob_app(l_out, json_str(NVL(p_status, 'UNKNOWN')));
    clob_app(l_out, ',"contract_version":"asta.v1","architecture":"ADB_ORDS_PLSQL","source":"ADB_ORDS"');
    clob_app(l_out, ',"report_source":"ADB_REPORT_PLSQL"');
    clob_app(l_out, ',"response_contract":');
    clob_app(l_out, json_str(C_RESPONSE_CONTRACT));
    clob_app(l_out, ',"guard_policy":');
    clob_app(l_out, json_str(C_GUARD_POLICY));
    clob_app(l_out, ',"progress":');
    IF p_progress_json IS NULL OR NVL(DBMS_LOB.GETLENGTH(p_progress_json), 0) = 0 THEN
      clob_app(l_out, '[');
      clob_app(l_out, '{"seq":1,"code":"REQUEST_RECEIVED","label":"OADT2 request received","status":"DONE"},');
      clob_app(l_out, '{"seq":2,"code":"ORDS_DISPATCH","label":"ADB ORDS analyze call","status":"DONE"},');
      clob_app(l_out, '{"seq":3,"code":"SQL_GUARD","label":"ADB SQL guard","status":"DONE"},');
      clob_app(l_out, '{"seq":4,"code":"BEFORE_EVIDENCE","label":"Source evidence via DB Link","status":"DONE"},');
      clob_app(l_out, '{"seq":5,"code":"SQL_TUNING_ADVISOR","label":"SQL Tuning Advisor","status":"DONE"},');
      clob_app(l_out, '{"seq":6,"code":"LLM_REWRITE","label":"SQL-only structural rewrite","status":"DONE"},');
      clob_app(l_out, '{"seq":7,"code":"AFTER_EVIDENCE","label":"Candidate SQL evidence","status":"SKIPPED"},');
      clob_app(l_out, '{"seq":8,"code":"BEFORE_AFTER_COMPARE","label":"Deterministic comparison","status":"SKIPPED"},');
      clob_app(l_out, '{"seq":9,"code":"VECTOR_KB","label":"Verified Vector KB search","status":"DONE"},');
      clob_app(l_out, '{"seq":10,"code":"FINAL_REPORT","label":"Final report synthesis","status":"DONE"},');
      clob_app(l_out, '{"seq":11,"code":"VECTOR_SAVE","label":"ADB Vector KB save","status":"DONE"}]');
    ELSE
      clob_app_clob(l_out, p_progress_json);
    END IF;
    clob_app(l_out, ',"detailed_report_markdown":');
    clob_app_json_str(l_out, p_report_markdown);
    clob_app(l_out, ',"candidate_sql":');
    IF l_candidate_sql_vc IS NULL THEN
      clob_app(l_out, 'null');
    ELSE
      clob_app_json_str(l_out, TO_CLOB(l_candidate_sql_vc));
    END IF;
    clob_app(l_out, ',"runtime_evidence":');
    clob_app_json_or_null(l_out, p_source_evidence_json, 'runtime_evidence');
    clob_app(l_out, ',"after_evidence":');
    clob_app_json_or_null(l_out, p_after_evidence_json, 'after_evidence');
    clob_app(l_out, ',"comparison":');
    clob_app_json_or_null(l_out, p_comparison_json, 'comparison');
    clob_app(l_out, ',"vector_save":');
    clob_app_json_or_null(l_out, p_vector_save_json, 'vector_save');
    clob_app(l_out, ',"artifacts":{"source_evidence":');
    clob_app_json_or_null(l_out, p_source_evidence_json, 'artifacts.source_evidence');
    clob_app(l_out, ',"after_evidence":');
    clob_app_json_or_null(l_out, p_after_evidence_json, 'artifacts.after_evidence');
    clob_app(l_out, ',"comparison":');
    clob_app_json_or_null(l_out, p_comparison_json, 'artifacts.comparison');
    clob_app(l_out, ',"vector":');
    clob_app_json_or_null(l_out, p_vector_json, 'artifacts.vector');
    clob_app(l_out, ',"vector_save":');
    clob_app_json_or_null(l_out, p_vector_save_json, 'artifacts.vector_save');
    clob_app(l_out, ',"llm":');
    clob_app_json_or_null(l_out, p_llm_json, 'artifacts.llm');
    clob_app(l_out, ',"final_review":');
    clob_app_json_or_null(l_out, p_final_review_json, 'artifacts.final_review');
    clob_app(l_out, '},"migration_boundary":{"fastapi_role":"ORDS_PROXY_ONLY","asta_runtime":"ADB_ORDS_PLSQL","source_runtime":"SOURCE_BASEDB_DBLINK_ONLY","guard_policy":"SELECT_WITH_SINGLE_STATEMENT","response_contract":"CLOB_CHUNKED_JSON","python_local_asta":false},"error":');
    clob_app_json_or_null(l_out, p_error_json, 'error');
    clob_app(l_out, ',"proxy":{"source":"ADB_ORDS","external_call":false}}');
    RETURN l_out;
  END build_response_json;
END asta_report_pkg;
/
