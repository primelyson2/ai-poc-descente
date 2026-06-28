-- db/adb/asta_sql_guard_pkg.sql
-- ADB-side SQL guard for ASTA. FastAPI must not perform this validation.

CREATE OR REPLACE PACKAGE asta_sql_guard_pkg AUTHID DEFINER AS
  PROCEDURE assert_safe_select(p_sql IN CLOB);
  FUNCTION extract_candidate_sql(p_llm_text IN CLOB) RETURN CLOB;
  FUNCTION inspect_sql(p_sql IN CLOB) RETURN CLOB;
END asta_sql_guard_pkg;
/

CREATE OR REPLACE PACKAGE BODY asta_sql_guard_pkg AS
  C_MAX_SQL_CHARS CONSTANT PLS_INTEGER := 32767;
  C_GUARD_POLICY  CONSTANT VARCHAR2(40) := 'SELECT_WITH_SINGLE_STATEMENT';

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

  FUNCTION strip_leading_comments(p_sql IN VARCHAR2) RETURN VARCHAR2 IS
    l_pos PLS_INTEGER := 1;
    l_len PLS_INTEGER := NVL(LENGTH(p_sql), 0);
    l_c2  VARCHAR2(2);
    l_nl  PLS_INTEGER;
    l_end PLS_INTEGER;
  BEGIN
    LOOP
      WHILE l_pos <= l_len
        AND SUBSTR(p_sql, l_pos, 1) IN (' ', CHR(9), CHR(10), CHR(13))
      LOOP
        l_pos := l_pos + 1;
      END LOOP;

      EXIT WHEN l_pos > l_len;
      l_c2 := SUBSTR(p_sql, l_pos, 2);

      IF l_c2 = '/*' THEN
        l_end := INSTR(p_sql, '*/', l_pos + 2);
        IF l_end = 0 THEN
          RETURN '';
        END IF;
        l_pos := l_end + 2;
      ELSIF l_c2 = '--' THEN
        l_nl := INSTR(p_sql, CHR(10), l_pos + 2);
        l_pos := CASE WHEN l_nl = 0 THEN l_len + 1 ELSE l_nl + 1 END;
      ELSE
        EXIT;
      END IF;
    END LOOP;
    RETURN SUBSTR(p_sql, l_pos);
  END strip_leading_comments;

  FUNCTION scrub_guard_text(p_sql IN VARCHAR2) RETURN VARCHAR2 IS
    l_pos PLS_INTEGER := 1;
    l_len PLS_INTEGER := NVL(LENGTH(p_sql), 0);
    l_out VARCHAR2(32767);
    l_c1  VARCHAR2(1);
    l_c2  VARCHAR2(2);
    l_nl  PLS_INTEGER;
    l_end PLS_INTEGER;
  BEGIN
    WHILE l_pos <= l_len LOOP
      l_c1 := SUBSTR(p_sql, l_pos, 1);
      l_c2 := SUBSTR(p_sql, l_pos, 2);

      IF l_c2 = '/*' THEN
        l_end := INSTR(p_sql, '*/', l_pos + 2);
        IF l_end = 0 THEN
          l_out := l_out || ' ';
          EXIT;
        END IF;
        l_out := l_out || ' ';
        l_pos := l_end + 2;
      ELSIF l_c2 = '--' THEN
        l_nl := INSTR(p_sql, CHR(10), l_pos + 2);
        l_out := l_out || CHR(10);
        l_pos := CASE WHEN l_nl = 0 THEN l_len + 1 ELSE l_nl + 1 END;
      ELSIF l_c1 = '''' THEN
        l_out := l_out || ' ';
        l_pos := l_pos + 1;
        WHILE l_pos <= l_len LOOP
          IF SUBSTR(p_sql, l_pos, 1) = '''' THEN
            IF SUBSTR(p_sql, l_pos + 1, 1) = '''' THEN
              l_pos := l_pos + 2;
            ELSE
              l_pos := l_pos + 1;
              EXIT;
            END IF;
          ELSE
            l_pos := l_pos + 1;
          END IF;
        END LOOP;
      ELSE
        l_out := l_out || l_c1;
        l_pos := l_pos + 1;
      END IF;
    END LOOP;
    RETURN l_out;
  END scrub_guard_text;

  PROCEDURE assert_safe_select(p_sql IN CLOB) IS
    l_head      VARCHAR2(32767);
    l_stripped  VARCHAR2(32767);
    l_guard     VARCHAR2(32767);
    l_first     VARCHAR2(30);
    TYPE t_kw IS TABLE OF VARCHAR2(20);
    l_forbidden t_kw := t_kw(
      'INSERT', 'UPDATE', 'DELETE', 'MERGE',
      'DROP', 'ALTER', 'TRUNCATE', 'CREATE',
      'GRANT', 'REVOKE', 'COMMIT', 'ROLLBACK',
      'EXECUTE', 'BEGIN', 'DECLARE', 'CALL'
    );
  BEGIN
    IF p_sql IS NULL OR NVL(DBMS_LOB.GETLENGTH(p_sql), 0) = 0 THEN
      RAISE_APPLICATION_ERROR(-20001, 'ASTA_SQL_GUARD: SQL is empty');
    END IF;

    IF DBMS_LOB.GETLENGTH(p_sql) > C_MAX_SQL_CHARS THEN
      RAISE_APPLICATION_ERROR(
        -20001,
        'ASTA_SQL_GUARD: SQL exceeds maximum length (' || C_MAX_SQL_CHARS || ' chars)'
      );
    END IF;

    l_head := DBMS_LOB.SUBSTR(p_sql, 32767, 1);
    l_stripped := strip_leading_comments(l_head);
    l_guard := scrub_guard_text(l_head);
    l_first := UPPER(REGEXP_SUBSTR(l_stripped, '^\w+'));

    IF l_first NOT IN ('SELECT', 'WITH') THEN
      RAISE_APPLICATION_ERROR(
        -20001,
        'ASTA_SQL_GUARD: First keyword must be SELECT or WITH; found: ' ||
        NVL('"' || l_first || '"', '(empty)')
      );
    END IF;

    IF INSTR(l_guard, ';') > 0 THEN
      RAISE_APPLICATION_ERROR(
        -20001,
        'ASTA_SQL_GUARD: Statement terminator is not allowed'
      );
    END IF;

    IF REGEXP_LIKE(l_guard, '(^|' || CHR(10) || ')[[:space:]]*/[[:space:]]*($|' || CHR(10) || ')') THEN
      RAISE_APPLICATION_ERROR(
        -20001,
        'ASTA_SQL_GUARD: SQL*Plus slash terminator is not allowed'
      );
    END IF;

    FOR i IN 1..l_forbidden.COUNT LOOP
      IF REGEXP_LIKE(l_guard, '(^|\W)' || l_forbidden(i) || '(\W|$)', 'i') THEN
        RAISE_APPLICATION_ERROR(
          -20001,
          'ASTA_SQL_GUARD: Forbidden keyword detected: ' || l_forbidden(i)
        );
      END IF;
    END LOOP;
  END assert_safe_select;

  FUNCTION extract_candidate_sql(p_llm_text IN CLOB) RETURN CLOB IS
    l_candidate_vc VARCHAR2(32767);
    l_candidate    CLOB;
    l_start        PLS_INTEGER;
    l_end          PLS_INTEGER;
    l_marker       VARCHAR2(30);
  BEGIN
    IF p_llm_text IS NULL OR NVL(DBMS_LOB.GETLENGTH(p_llm_text), 0) = 0 THEN
      RETURN NULL;
    END IF;

    BEGIN
      SELECT JSON_VALUE(
               p_llm_text,
               '$.candidate_sql'
               RETURNING VARCHAR2(4000)
               NULL ON ERROR
             )
      INTO   l_candidate_vc
      FROM   dual;
    EXCEPTION
      WHEN OTHERS THEN
        l_candidate_vc := NULL;
    END;

    -- DBMS_CLOUD_AI occasionally returns JSON-looking text with literal newlines
    -- inside candidate_sql, which is not strict JSON and makes JSON_VALUE return
    -- NULL. Recover the candidate from the JSON-ish envelope before falling
    -- back to fenced SQL extraction; otherwise the caller reruns the original
    -- SQL and the before/after loop looks successful but never tests the LLM SQL.
    IF l_candidate_vc IS NULL THEN
      l_marker := '"candidate_sql":"';
      l_start := DBMS_LOB.INSTR(p_llm_text, l_marker, 1, 1);
      IF l_start > 0 THEN
        l_start := l_start + LENGTH(l_marker);
        l_end := DBMS_LOB.INSTR(p_llm_text, '","change_reason"', l_start, 1);
        IF l_end = 0 THEN
          l_end := DBMS_LOB.INSTR(p_llm_text, '","change_summary"', l_start, 1);
        END IF;
        IF l_end > l_start THEN
          l_candidate_vc := DBMS_LOB.SUBSTR(
            p_llm_text,
            LEAST(l_end - l_start, 32767),
            l_start
          );
          l_candidate_vc := REPLACE(l_candidate_vc, '\n', CHR(10));
          l_candidate_vc := REPLACE(l_candidate_vc, '\r', CHR(13));
          l_candidate_vc := REPLACE(l_candidate_vc, '\t', CHR(9));
          l_candidate_vc := REPLACE(l_candidate_vc, '\"', '"');
          l_candidate_vc := REPLACE(l_candidate_vc, '\\', '\');
        END IF;
      END IF;
    END IF;

    IF l_candidate_vc IS NULL THEN
      l_marker := '```sql';
      l_start := DBMS_LOB.INSTR(p_llm_text, l_marker, 1, 1);
      IF l_start = 0 THEN
        l_marker := '```SQL';
        l_start := DBMS_LOB.INSTR(p_llm_text, l_marker, 1, 1);
      END IF;
      IF l_start > 0 THEN
        l_start := l_start + LENGTH(l_marker);
        l_end := DBMS_LOB.INSTR(p_llm_text, '```', l_start, 1);
        IF l_end > l_start THEN
          l_candidate_vc := DBMS_LOB.SUBSTR(
            p_llm_text,
            LEAST(l_end - l_start, 32767),
            l_start
          );
        END IF;
      END IF;
    END IF;

    IF l_candidate_vc IS NULL THEN
      RETURN NULL;
    END IF;

    l_candidate := TO_CLOB(TRIM(CHR(10) FROM TRIM(CHR(13) FROM TRIM(l_candidate_vc))));
    WHILE DBMS_LOB.GETLENGTH(l_candidate) > 0 AND DBMS_LOB.SUBSTR(l_candidate, 1, DBMS_LOB.GETLENGTH(l_candidate)) = ';' LOOP
      l_candidate := TO_CLOB(TRIM(TRAILING ';' FROM DBMS_LOB.SUBSTR(l_candidate, 32767, 1)));
    END LOOP;
    assert_safe_select(l_candidate);
    RETURN l_candidate;
  END extract_candidate_sql;

  FUNCTION inspect_sql(p_sql IN CLOB) RETURN CLOB IS
  BEGIN
    assert_safe_select(p_sql);
    RETURN TO_CLOB(
      '{"status":"OK","code":"SQL_GUARD","contract_version":"asta.v1","execution_boundary":"ADB_SQL_GUARD_PLSQL","guard_policy":' ||
      json_str(C_GUARD_POLICY) || ',"message":"SELECT/WITH SQL accepted"}'
    );
  EXCEPTION
    WHEN OTHERS THEN
      RETURN TO_CLOB(
        '{"status":"FAILED","code":"SQL_GUARD","contract_version":"asta.v1","execution_boundary":"ADB_SQL_GUARD_PLSQL","error_code":' ||
        TO_CHAR(SQLCODE) || ',"guard_policy":' ||
        json_str(C_GUARD_POLICY) || ',"message":' ||
        json_str(SUBSTR(SQLERRM, 1, 4000)) || '}'
      );
  END inspect_sql;
END asta_sql_guard_pkg;
/
