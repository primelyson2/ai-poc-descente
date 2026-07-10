-- db/source/asta_source_pkg.sql
-- OADT2 ASTA용 Source BaseDB 런타임 실행 근거 수집 도우미.
--
-- 아키텍처: Source BaseDB에만 설치한다.
--   ADB는 DB Link를 통해 이 패키지를 호출한다: asta_source_pkg.run_evidence@<db_link>(...)
--   Python/FastAPI는 이 패키지를 절대 직접 호출해서는 안 된다.
--
-- 필요 권한(Source BaseDB에서 DBA가 실행):
--   GRANT SELECT  ON v_$sql                     TO <owner>;
--   GRANT SELECT  ON v_$sql_plan_statistics_all TO <owner>;
--   GRANT EXECUTE ON dbms_xplan                 TO <owner>;
--   GRANT EXECUTE ON dbms_sqltune               TO <owner>;  -- p_run_advisor='Y'일 때만 필요
--
-- 호환 버전: Oracle 12.2 이상(Source BaseDB).
--   AUTHID CURRENT_USER를 사용한다. DB Link 원격 사용자와 패키지 소유자는
--   동일한 전용 Source helper 계정이어야 한다.
--
-- 설치 및 권한 부여 방법은 db/source/README.md를 참고한다.

CREATE OR REPLACE PACKAGE asta_source_pkg AUTHID CURRENT_USER AS

  -- SQL engine adapter for full CLOB row hashing. Returns only SHA-256 hex;
  -- callers never receive the row payload through this function.
  FUNCTION sha256_clob(p_value IN CLOB) RETURN VARCHAR2;

  PROCEDURE run_advisor_job(
    p_run_id   IN VARCHAR2,
    p_sql_id   IN VARCHAR2,
    p_sql_text IN VARCHAR2,
    p_time_sec IN NUMBER
  );

  /*
   * run_evidence
   *
   * Source BaseDB에서 p_sql을 안전하게 실행하고 실제 런타임 근거를 수집한 뒤,
   * 다음 항목을 포함한 JSON CLOB을 반환한다.
   *   run_id, sql_id, child_number, plan_hash_value,
   *   fetch_rows_limit, row_count, elapsed_wall_ms,
   *   last_output_rows, last_cr_buffer_gets, last_disk_reads, last_elapsed_time_us,
   *   plan_text  (DBMS_XPLAN.DISPLAY_CURSOR 형식),
   *   advisor    { status, report },
   *   error      { code, message } | null
   *
   * 매개변수:
   *   p_sql              입력 SQL. SELECT 또는 WITH 문만 허용한다.
   *   p_run_id           실행 SQL에 표식으로 삽입할 고유 실행 ID.
   *   p_fetch_rows       실행 범위를 제한할 최대 행 수(1~10000). 기본값: 100.
   *   p_repeat_policy    'AUTO'(warm-up 1회 + 측정 3회) | 'ONCE' | 'REPEAT:<n>'(n=1~5).
   *   p_result_evidence_mode 'ESTIMATED_PLAN'(SQL 미실행 EXPLAIN PLAN) | 'PLAN_ONLY' | 'BOUNDED' | 'FULL_RESULT'.
   *   p_run_advisor      DBMS_SQLTUNE 실행은 'Y', 생략은 'N'. 기본값: 'N'.
   *   p_sqltune_time_sec DBMS_SQLTUNE 제한시간(초, 60~1800). 기본값: 1800.
   */
  FUNCTION run_evidence(
    p_sql              IN CLOB,
    p_run_id           IN VARCHAR2,
    p_fetch_rows       IN NUMBER   DEFAULT 100,
    p_repeat_policy    IN VARCHAR2 DEFAULT 'AUTO',
    p_run_advisor      IN VARCHAR2 DEFAULT 'N',
    p_sqltune_time_sec IN NUMBER   DEFAULT 1800,
    p_source_sql_id    IN VARCHAR2 DEFAULT NULL,
    p_result_evidence_mode IN VARCHAR2 DEFAULT 'BOUNDED',
    p_result_max_rows  IN NUMBER DEFAULT 100000
  ) RETURN CLOB;

  FUNCTION run_evidence_store_vc(
    p_sql              IN VARCHAR2,
    p_run_id           IN VARCHAR2,
    p_fetch_rows       IN NUMBER   DEFAULT 100,
    p_repeat_policy    IN VARCHAR2 DEFAULT 'AUTO',
    p_run_advisor      IN VARCHAR2 DEFAULT 'N',
    p_sqltune_time_sec IN NUMBER   DEFAULT 1800,
    p_source_sql_id    IN VARCHAR2 DEFAULT NULL,
    p_result_evidence_mode IN VARCHAR2 DEFAULT 'BOUNDED',
    p_result_max_rows  IN NUMBER DEFAULT 100000
  ) RETURN VARCHAR2;

  PROCEDURE run_evidence_store_proc(
    p_sql              IN VARCHAR2,
    p_run_id           IN VARCHAR2,
    p_fetch_rows       IN NUMBER   DEFAULT 100,
    p_repeat_policy    IN VARCHAR2 DEFAULT 'AUTO',
    p_run_advisor      IN VARCHAR2 DEFAULT 'N',
    p_sqltune_time_sec IN NUMBER   DEFAULT 1800,
    p_source_sql_id    IN VARCHAR2 DEFAULT NULL,
    p_result_evidence_mode IN VARCHAR2 DEFAULT 'BOUNDED',
    p_result_max_rows  IN NUMBER DEFAULT 100000,
    p_status_json      OUT VARCHAR2
  );

  FUNCTION get_result_chunk(
    p_run_id IN VARCHAR2,
    p_offset IN NUMBER DEFAULT 1,
    p_amount IN NUMBER DEFAULT 8000
  ) RETURN VARCHAR2;

  FUNCTION cancel_run_vc(p_run_id IN VARCHAR2) RETURN VARCHAR2;

END asta_source_pkg;
/

CREATE OR REPLACE PACKAGE BODY asta_source_pkg AS

  C_MAX_FETCH_ROWS CONSTANT PLS_INTEGER := 10000;
  C_MAX_SQL_CHARS  CONSTANT PLS_INTEGER := 32767;
  C_MAX_REPEATS    CONSTANT PLS_INTEGER := 5;
  C_MAX_RUN_ID_CHARS CONSTANT PLS_INTEGER := 64;
  C_GUARD_POLICY   CONSTANT VARCHAR2(40) := 'SELECT_WITH_SINGLE_STATEMENT';

  FUNCTION sha256_clob(p_value IN CLOB) RETURN VARCHAR2 IS
    l_hash VARCHAR2(64) := RPAD('0', 64, '0');
    l_chunk VARCHAR2(16000);
    l_offset PLS_INTEGER := 1;
    l_length PLS_INTEGER := NVL(DBMS_LOB.GETLENGTH(p_value), 0);
  BEGIN
    WHILE l_offset <= l_length LOOP
      l_chunk := DBMS_LOB.SUBSTR(p_value, 8000, l_offset);
      SELECT LOWER(RAWTOHEX(STANDARD_HASH(
        l_hash || ':' || LENGTHB(l_chunk) || ':' || l_chunk, 'SHA256'
      ))) INTO l_hash FROM dual;
      l_offset := l_offset + LENGTH(l_chunk);
    END LOOP;
    SELECT LOWER(RAWTOHEX(STANDARD_HASH(
      l_hash || ':chars=' || TO_CHAR(l_length), 'SHA256'
    ))) INTO l_hash FROM dual;
    RETURN l_hash;
  END sha256_clob;

  -- =========================================================================
  -- JSON 처리 보조 함수
  -- =========================================================================

  -- VARCHAR2 값을 JSON 문자열 리터럴("...") 또는 null로 반환한다.
  FUNCTION json_str(p_val IN VARCHAR2) RETURN VARCHAR2 IS
    l_v VARCHAR2(32767) := p_val;
  BEGIN
    IF l_v IS NULL THEN RETURN 'null'; END IF;
    l_v := REPLACE(l_v, '\',  '\\');
    l_v := REPLACE(l_v, '"',  '\"');
    l_v := REPLACE(l_v, CHR(8),  '\b');
    l_v := REPLACE(l_v, CHR(9),  '\t');
    l_v := REPLACE(l_v, CHR(10), '\n');
    l_v := REPLACE(l_v, CHR(13), '\r');
    l_v := REPLACE(l_v, CHR(12), '\f');
    RETURN '"' || l_v || '"';
  END json_str;

  -- NUMBER 값을 JSON 숫자 리터럴 또는 null로 반환한다.
  FUNCTION json_num(p_val IN NUMBER) RETURN VARCHAR2 IS
    l_text VARCHAR2(100);
  BEGIN
    IF p_val IS NULL THEN
      RETURN 'null';
    END IF;
    l_text := TO_CHAR(p_val, 'TM9', 'NLS_NUMERIC_CHARACTERS=.,');
    IF SUBSTR(l_text, 1, 1) = '.' THEN
      l_text := '0' || l_text;
    ELSIF SUBSTR(l_text, 1, 2) = '-.' THEN
      l_text := '-0' || SUBSTR(l_text, 2);
    END IF;
    RETURN l_text;
  END json_num;

  -- VARCHAR2 조각을 CLOB에 추가한다(NULL 또는 빈 값이면 아무 작업도 하지 않는다).
  PROCEDURE clob_app(p_out IN OUT NOCOPY CLOB, p_str IN VARCHAR2) IS
  BEGIN
    IF p_str IS NOT NULL AND LENGTH(p_str) > 0 THEN
      DBMS_LOB.WRITEAPPEND(p_out, LENGTH(p_str), p_str);
    END IF;
  END clob_app;

  -- 원시 JSON처럼 이스케이프 없이 붙여야 하는 CLOB을 안전한 조각 크기로
  -- 추가한다. CLOB을 clob_app(VARCHAR2)에 넘기면 32KB 초과 시 ORA-06502가
  -- 발생하므로 대용량 object_info에는 반드시 이 경로를 사용한다.
  PROCEDURE clob_app_clob(p_out IN OUT NOCOPY CLOB, p_val IN CLOB) IS
    l_offset   PLS_INTEGER := 1;
    l_len      PLS_INTEGER;
    l_chunk_sz CONSTANT PLS_INTEGER := 8000;
    l_chunk    VARCHAR2(32767);
  BEGIN
    IF p_val IS NULL THEN
      RETURN;
    END IF;
    l_len := NVL(DBMS_LOB.GETLENGTH(p_val), 0);
    WHILE l_offset <= l_len LOOP
      l_chunk := DBMS_LOB.SUBSTR(p_val, l_chunk_sz, l_offset);
      EXIT WHEN l_chunk IS NULL;
      DBMS_LOB.WRITEAPPEND(p_out, LENGTH(l_chunk), l_chunk);
      l_offset := l_offset + LENGTH(l_chunk);
    END LOOP;
  END clob_app_clob;

  -- CLOB 값을 JSON 문자열 리터럴로 p_out에 추가한다.
  -- NULL은 JSON null, 빈 값은 ""로 기록하며 임의 길이의 값을 처리한다.
  PROCEDURE clob_app_json_str(p_out IN OUT NOCOPY CLOB, p_val IN CLOB) IS
    l_offset   PLS_INTEGER := 1;
    l_chunk_sz PLS_INTEGER := 2000;
    l_len      PLS_INTEGER;
    l_chunk    VARCHAR2(4000);
    l_escaped  VARCHAR2(8000);
  BEGIN
    IF p_val IS NULL THEN
      clob_app(p_out, 'null');
      RETURN;
    END IF;
    l_len := NVL(DBMS_LOB.GETLENGTH(p_val), 0);
    IF l_len = 0 THEN
      clob_app(p_out, '""');
      RETURN;
    END IF;
    clob_app(p_out, '"');
    WHILE l_offset <= l_len LOOP
      l_chunk   := DBMS_LOB.SUBSTR(p_val, l_chunk_sz, l_offset);
      -- 각 조각 내부의 JSON 특수문자를 이스케이프한다.
      l_escaped := REPLACE(l_chunk,   '\',  '\\');
      l_escaped := REPLACE(l_escaped, '"',  '\"');
      l_escaped := REPLACE(l_escaped, CHR(8),  '\b');
      l_escaped := REPLACE(l_escaped, CHR(9),  '\t');
      l_escaped := REPLACE(l_escaped, CHR(10), '\n');
      l_escaped := REPLACE(l_escaped, CHR(13), '\r');
      l_escaped := REPLACE(l_escaped, CHR(12), '\f');
      DBMS_LOB.WRITEAPPEND(p_out, LENGTH(l_escaped), l_escaped);
      l_offset := l_offset + l_chunk_sz;
    END LOOP;
    clob_app(p_out, '"');
  END clob_app_json_str;

  -- =========================================================================
  -- SQL 안전성 검사
  -- =========================================================================

  -- 앞부분의 공백, 블록 주석(/* ... */), 행 주석(-- ...)을 제거한다.
  -- 첫 번째 비주석 문자부터 시작하는 나머지 SQL을 반환한다.
  FUNCTION strip_leading_comments(p_sql IN VARCHAR2) RETURN VARCHAR2 IS
    l_pos PLS_INTEGER := 1;
    l_len PLS_INTEGER := NVL(LENGTH(p_sql), 0);
    -- SUBSTR length is characters while VARCHAR2 capacity is bytes here.
    -- Reserve four bytes per character so AL32UTF8 identifiers are safe.
    l_c2  VARCHAR2(8);
    l_nl  PLS_INTEGER;
    l_end PLS_INTEGER;
  BEGIN
    LOOP
      -- 공백 문자를 건너뛴다.
      WHILE l_pos <= l_len
            AND SUBSTR(p_sql, l_pos, 1) IN (' ', CHR(9), CHR(10), CHR(13))
      LOOP
        l_pos := l_pos + 1;
      END LOOP;
      EXIT WHEN l_pos > l_len;
      l_c2 := SUBSTR(p_sql, l_pos, 2);
      IF l_c2 = '/*' THEN
        -- 블록 주석 다음 위치로 이동한다.
        l_end := INSTR(p_sql, '*/', l_pos + 2);
        IF l_end = 0 THEN RETURN ''; END IF;  -- unterminated block comment
        l_pos := l_end + 2;
      ELSIF l_c2 = '--' THEN
        -- 행 주석 다음 위치로 이동한다.
        l_nl := INSTR(p_sql, CHR(10), l_pos + 2);
        l_pos := CASE WHEN l_nl = 0 THEN l_len + 1 ELSE l_nl + 1 END;
      ELSE
        EXIT;  -- first real character found
      END IF;
    END LOOP;
    RETURN SUBSTR(p_sql, l_pos);
  END strip_leading_comments;

  -- 금지 키워드와 문장 종료자를 검사하기 전에 주석과 문자열 리터럴을 제거한다.
  -- 실행 가능한 SQL 본문은 검사하면서도 SELECT 'drop' FROM dual 같은 무해한
  -- 문자열 리터럴이 잘못 거부되는 것을 방지한다.
  FUNCTION scrub_guard_text(p_sql IN VARCHAR2) RETURN VARCHAR2 IS
    l_pos PLS_INTEGER := 1;
    l_len PLS_INTEGER := NVL(LENGTH(p_sql), 0);
    l_out VARCHAR2(32767);
    -- One Unicode character may occupy four bytes in AL32UTF8.
    l_c1  VARCHAR2(4);
    l_c2  VARCHAR2(8);
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

  -- p_sql이 안전한 SELECT 또는 WITH 문이 아니면 ORA-20001을 발생시킨다.
  -- DML, DDL, CALL, BEGIN 블록 및 기타 금지 구문을 거부한다.
  PROCEDURE assert_safe_select(p_sql IN CLOB) IS
    l_head     VARCHAR2(32767);
    l_stripped VARCHAR2(32767);
    l_guard    VARCHAR2(32767);
    l_first    VARCHAR2(30);
    TYPE t_kw IS TABLE OF VARCHAR2(20);
    l_forbidden t_kw := t_kw(
      'INSERT', 'UPDATE', 'DELETE', 'MERGE',
      'DROP',   'ALTER',  'TRUNCATE', 'CREATE',
      'GRANT',  'REVOKE', 'COMMIT',   'ROLLBACK',
      'EXECUTE','BEGIN',  'DECLARE',  'CALL'
    );
  BEGIN
    IF p_sql IS NULL OR NVL(DBMS_LOB.GETLENGTH(p_sql), 0) = 0 THEN
      RAISE_APPLICATION_ERROR(-20001, 'ASTA_SQL_GUARD: SQL is empty');
    END IF;
    IF DBMS_LOB.GETLENGTH(p_sql) > C_MAX_SQL_CHARS THEN
      RAISE_APPLICATION_ERROR(-20001,
        'ASTA_SQL_GUARD: SQL exceeds maximum length (' || C_MAX_SQL_CHARS || ' chars)');
    END IF;
    -- 주석 제거를 위해 VARCHAR2로 처리한다(길이는 위에서 이미 검증했다).
    l_head     := DBMS_LOB.SUBSTR(p_sql, 32767, 1);
    l_stripped := strip_leading_comments(l_head);
    l_guard    := scrub_guard_text(l_head);
    -- 첫 번째 실제 키워드는 SELECT 또는 WITH여야 한다.
    l_first    := UPPER(REGEXP_SUBSTR(l_stripped, '^\w+'));
    IF l_first NOT IN ('SELECT', 'WITH') THEN
      RAISE_APPLICATION_ERROR(-20001,
        'ASTA_SQL_GUARD: First keyword must be SELECT or WITH; found: ' ||
        NVL('"' || l_first || '"', '(empty after stripping comments)'));
    END IF;
    IF INSTR(l_guard, ';') > 0 THEN
      RAISE_APPLICATION_ERROR(-20001,
        'ASTA_SQL_GUARD: Statement terminator is not allowed');
    END IF;
    IF REGEXP_LIKE(l_guard, '(^|' || CHR(10) || ')[[:space:]]*/[[:space:]]*($|' || CHR(10) || ')') THEN
      RAISE_APPLICATION_ERROR(-20001,
        'ASTA_SQL_GUARD: SQL*Plus slash terminator is not allowed');
    END IF;
    -- 독립된 단어로 나타나는 모든 금지 키워드를 거부한다.
    -- Oracle REGEXP에서는 (^|\W) ... (\W|$)로 \b를 근사한다.
    FOR i IN 1..l_forbidden.COUNT LOOP
      IF REGEXP_LIKE(l_guard, '(^|\W)' || l_forbidden(i) || '(\W|$)', 'i') THEN
        RAISE_APPLICATION_ERROR(-20001,
          'ASTA_SQL_GUARD: Forbidden keyword detected: ' || l_forbidden(i));
      END IF;
    END LOOP;
  END assert_safe_select;

  -- =========================================================================
  -- 실행
  -- =========================================================================

  -- 실행 표식을 SQL 주석에 삽입하기 전에 검증한다.
  FUNCTION normalize_run_id(p_run_id IN VARCHAR2) RETURN VARCHAR2 IS
    l_run_id VARCHAR2(32767) := TRIM(p_run_id);
  BEGIN
    IF l_run_id IS NULL THEN
      RAISE_APPLICATION_ERROR(-20001, 'ASTA_SOURCE: run_id is required');
    END IF;
    IF LENGTH(l_run_id) > C_MAX_RUN_ID_CHARS
       OR NOT REGEXP_LIKE(l_run_id, '^[A-Za-z0-9][A-Za-z0-9_.:-]*$') THEN
      RAISE_APPLICATION_ERROR(-20001, 'ASTA_SOURCE: invalid run_id marker');
    END IF;
    RETURN l_run_id;
  END normalize_run_id;

  FUNCTION cancel_run_vc(p_run_id IN VARCHAR2) RETURN VARCHAR2 IS
    l_run_id VARCHAR2(64) := normalize_run_id(p_run_id);
  BEGIN
    RETURN '{"status":"SKIPPED","code":"SOURCE_CANCEL_NOT_AVAILABLE","run_id":' ||
      json_str(l_run_id) ||
      ',"cancelled_sql_count":0,"failed_sql_count":0,' ||
      '"message":"ALTER SYSTEM is not permitted; ADB parent watchdog only"}';
  EXCEPTION
    WHEN OTHERS THEN
      RETURN '{"status":"FAILED","code":"SOURCE_RUN_CANCEL","run_id":' ||
        json_str(p_run_id) || ',"message":' || json_str(SUBSTR(SQLERRM, 1, 1000)) || '}';
  END cancel_run_vc;

  -- 다음 기능을 수행하는 제한 실행 래퍼를 생성한다.
  --   1. LAST_* 통계를 활성화하기 위해 /*+ gather_plan_statistics */를 삽입한다.
  --   2. V$SQL.SQL_TEXT에서 검색할 고유 /* ASTA_RUN_ID=<id> */ 표식을 삽입한다.
  --   3. 전체 쿼리 실행계획은 수행하면서 조회 행 수를 제한하도록 원본 SQL을
  --      COUNT(*) + ROWNUM <= n으로 감싼다.
  FUNCTION build_exec_sql(
    p_sql    IN CLOB,
    p_run_id IN VARCHAR2,
    p_rows   IN PLS_INTEGER
  ) RETURN CLOB IS
    l_header VARCHAR2(300) :=
      'SELECT /*+ gather_plan_statistics */ /* ASTA_RUN_ID=' || p_run_id || ' */ ' ||
      'COUNT(*) FROM (';
    l_footer VARCHAR2(60) := ') WHERE ROWNUM <= ' || TO_CHAR(p_rows);
  BEGIN
    -- 결과: SELECT /*+ gather_plan_statistics */ /* ASTA_RUN_ID=x */ COUNT(*) FROM (<sql>) WHERE ROWNUM <= n
    RETURN TO_CLOB(l_header) || p_sql || TO_CLOB(l_footer);
  END build_exec_sql;

  -- 마지막 bounded 실행의 실제 결과 행을 원래 fetch 순서대로 JSON CLOB으로
  -- 직렬화한다. NULL ON NULL과 JSON native scalar encoding으로 NULL/문자/숫자/
  -- 날짜 의미를 보존한다. 지원하지 않는 결과 datatype은 호출부에서 digest
  -- FAILED로 기록하며 row-count fallback을 동등성 증거로 사용하지 않는다.
  FUNCTION build_digest_sql(
    p_sql    IN CLOB,
    p_run_id IN VARCHAR2,
    p_rows   IN PLS_INTEGER
  ) RETURN CLOB IS
    l_header VARCHAR2(1000) :=
      'SELECT /*+ gather_plan_statistics */ /* ASTA_RUN_ID=' || p_run_id || ' */ ' ||
      'JSON_ARRAYAGG(row_doc FORMAT JSON ORDER BY row_no RETURNING CLOB), COUNT(*) FROM (' ||
      'SELECT ROWNUM row_no, JSON_OBJECT(t.* NULL ON NULL RETURNING CLOB) row_doc FROM (';
    l_footer VARCHAR2(100) := ') t WHERE ROWNUM <= ' || TO_CHAR(p_rows) || ')';
  BEGIN
    RETURN TO_CLOB(l_header) || p_sql || TO_CLOB(l_footer);
  END build_digest_sql;

  -- 전체 결과 증거는 성능 측정용 bounded wrapper와 분리하여 생성한다. 최종
  -- ORDER BY가 없는 SQL은 row hash별 multiplicity를 정렬해 multiset 의미와
  -- duplicate 수를 보존한다. ORDER BY가 있으면 실제 fetch 순서를 보존한다.
  FUNCTION top_level_sql_text(p_sql IN CLOB) RETURN VARCHAR2 IS
    l_sql VARCHAR2(32767) := DBMS_LOB.SUBSTR(p_sql, 32767, 1);
    l_out VARCHAR2(32767);
    l_pos PLS_INTEGER := 1;
    l_len PLS_INTEGER := LENGTH(l_sql);
    l_depth PLS_INTEGER := 0;
    -- VARCHAR2 length is bytes; one AL32UTF8 character may need four bytes.
    l_ch VARCHAR2(4);
  BEGIN
    WHILE l_pos <= l_len LOOP
      IF SUBSTR(l_sql, l_pos, 2) = '/*' THEN
        l_pos := NVL(NULLIF(INSTR(l_sql, '*/', l_pos + 2), 0), l_len) + 2;
      ELSIF SUBSTR(l_sql, l_pos, 2) = '--' THEN
        l_pos := NVL(NULLIF(INSTR(l_sql, CHR(10), l_pos + 2), 0), l_len) + 1;
      ELSE
        l_ch := SUBSTR(l_sql, l_pos, 1);
        IF l_ch IN ('''', '"') THEN
          DECLARE l_quote VARCHAR2(4) := l_ch; BEGIN
            l_pos := l_pos + 1;
            WHILE l_pos <= l_len LOOP
              IF SUBSTR(l_sql, l_pos, 1) = l_quote THEN
                IF SUBSTR(l_sql, l_pos + 1, 1) = l_quote THEN l_pos := l_pos + 2;
                ELSE l_pos := l_pos + 1; EXIT; END IF;
              ELSE l_pos := l_pos + 1; END IF;
            END LOOP;
          END;
          l_out := l_out || ' ';
        ELSIF l_ch = '(' THEN
          l_depth := l_depth + 1; l_out := l_out || ' '; l_pos := l_pos + 1;
        ELSIF l_ch = ')' THEN
          l_depth := GREATEST(0, l_depth - 1); l_out := l_out || ' '; l_pos := l_pos + 1;
        ELSE
          l_out := l_out || CASE WHEN l_depth = 0 THEN UPPER(l_ch) ELSE ' ' END;
          l_pos := l_pos + 1;
        END IF;
      END IF;
    END LOOP;
    RETURN l_out;
  END top_level_sql_text;

  FUNCTION detect_result_mode(p_sql IN CLOB) RETURN VARCHAR2 IS
  BEGIN
    RETURN CASE
      WHEN REGEXP_LIKE(top_level_sql_text(p_sql), '(^|\W)ORDER[[:space:]]+BY(\W|$)')
      THEN 'ORDERED_ROWS' ELSE 'UNORDERED_MULTISET' END;
  END detect_result_mode;

  FUNCTION build_full_count_sql(p_sql IN CLOB, p_run_id IN VARCHAR2) RETURN CLOB IS
  BEGIN
    RETURN TO_CLOB('SELECT /* ASTA_RUN_ID=' || p_run_id || '-FULLCOUNT */ COUNT(*) FROM (') ||
      p_sql || TO_CLOB(')');
  END build_full_count_sql;

  FUNCTION build_full_digest_sql(
    p_sql IN CLOB, p_run_id IN VARCHAR2, p_result_mode IN VARCHAR2
  ) RETURN CLOB IS
    l_hash_fn VARCHAR2(300) := DBMS_ASSERT.ENQUOTE_NAME(
      SYS_CONTEXT('USERENV', 'SESSION_USER'), FALSE
    ) || '.ASTA_SOURCE_PKG.SHA256_CLOB';
  BEGIN
    IF p_result_mode = 'ORDERED_ROWS' THEN
      RETURN TO_CLOB(
        'SELECT /* ASTA_RUN_ID=' || p_run_id || '-FULLDIGEST */ ' ||
        'JSON_ARRAYAGG(row_doc FORMAT JSON ORDER BY row_no RETURNING CLOB) FROM (' ||
        'SELECT ROWNUM row_no, JSON_OBJECT(t.* NULL ON NULL RETURNING CLOB) row_doc FROM ('
      ) || p_sql || TO_CLOB(') t)');
    END IF;
    RETURN TO_CLOB(
      'SELECT /* ASTA_RUN_ID=' || p_run_id || '-FULLDIGEST */ ' ||
      'JSON_ARRAYAGG(JSON_OBJECT(''row_hash'' VALUE row_hash,''multiplicity'' VALUE row_multiplicity RETURNING CLOB) ' ||
      'FORMAT JSON ORDER BY row_hash RETURNING CLOB) FROM (' ||
      'SELECT ' || l_hash_fn || '(JSON_OBJECT(t.* NULL ON NULL RETURNING CLOB)) row_hash, ' ||
      'COUNT(*) row_multiplicity FROM ('
    ) || p_sql || TO_CLOB(
      ') t GROUP BY ' || l_hash_fn || '(JSON_OBJECT(t.* NULL ON NULL RETURNING CLOB)))'
    );
  END build_full_digest_sql;

  FUNCTION sha256_varchar(p_value IN VARCHAR2) RETURN VARCHAR2 IS
    l_hash VARCHAR2(64);
  BEGIN
    SELECT LOWER(RAWTOHEX(STANDARD_HASH(p_value, 'SHA256')))
    INTO   l_hash
    FROM   dual;
    RETURN l_hash;
  END sha256_varchar;

  FUNCTION result_metadata_hash(p_sql IN CLOB) RETURN VARCHAR2 IS
    l_cursor INTEGER;
    l_count  INTEGER;
    l_desc   DBMS_SQL.DESC_TAB2;
    l_meta   VARCHAR2(32767) := 'ASTA_RESULT_METADATA_V1';
  BEGIN
    l_cursor := DBMS_SQL.OPEN_CURSOR;
    DBMS_SQL.PARSE(l_cursor, p_sql, DBMS_SQL.NATIVE);
    DBMS_SQL.DESCRIBE_COLUMNS2(l_cursor, l_count, l_desc);
    DBMS_SQL.CLOSE_CURSOR(l_cursor);
    FOR i IN 1..l_count LOOP
      l_meta := l_meta || '|' || TO_CHAR(i) || ':' || LENGTHB(l_desc(i).col_name) || ':' ||
        l_desc(i).col_name || ':' || l_desc(i).col_type || ':' || l_desc(i).col_max_len || ':' ||
        NVL(TO_CHAR(l_desc(i).col_precision), '-') || ':' || NVL(TO_CHAR(l_desc(i).col_scale), '-') || ':' ||
        NVL(TO_CHAR(l_desc(i).col_charsetid), '-') || ':' || NVL(TO_CHAR(l_desc(i).col_charsetform), '-');
      IF LENGTHB(l_meta) > 30000 THEN
        RAISE_APPLICATION_ERROR(-20001, 'ASTA_RESULT_DIGEST: result metadata exceeds safe hash input');
      END IF;
    END LOOP;
    RETURN sha256_varchar(l_meta);
  EXCEPTION
    WHEN OTHERS THEN
      IF DBMS_SQL.IS_OPEN(l_cursor) THEN DBMS_SQL.CLOSE_CURSOR(l_cursor); END IF;
      RAISE;
  END result_metadata_hash;

  FUNCTION ordered_result_digest(
    p_result_json IN CLOB,
    p_metadata_hash IN VARCHAR2,
    p_row_count IN NUMBER
  ) RETURN VARCHAR2 IS
    l_hash   VARCHAR2(64) := p_metadata_hash;
    l_chunk  VARCHAR2(16000);
    l_offset PLS_INTEGER := 1;
    l_length PLS_INTEGER := NVL(DBMS_LOB.GETLENGTH(p_result_json), 0);
  BEGIN
    WHILE l_offset <= l_length LOOP
      l_chunk := DBMS_LOB.SUBSTR(p_result_json, 8000, l_offset);
      l_hash := sha256_varchar(l_hash || ':' || LENGTHB(l_chunk) || ':' || l_chunk);
      l_offset := l_offset + LENGTH(l_chunk);
    END LOOP;
    RETURN sha256_varchar(
      l_hash || ':rows=' || NVL(TO_CHAR(p_row_count), 'null') || ':chars=' || TO_CHAR(l_length)
    );
  END ordered_result_digest;

  -- 동적 SQL을 만들기 전에 반복 정책을 정규화한다. 잘못된 값은
  -- run_evidence의 바깥쪽 예외 처리를 통해 구조화된 ASTA 오류로 반환한다.
  FUNCTION normalize_repeat_policy(p_repeat_policy IN VARCHAR2) RETURN VARCHAR2 IS
    l_policy VARCHAR2(30) := UPPER(TRIM(NVL(p_repeat_policy, 'AUTO')));
    l_repeat PLS_INTEGER;
  BEGIN
    IF l_policy IN ('AUTO', 'ONCE') THEN
      RETURN l_policy;
    ELSIF REGEXP_LIKE(l_policy, '^REPEAT:[0-9]+$') THEN
      l_repeat := TO_NUMBER(SUBSTR(l_policy, 8));
      RETURN 'REPEAT:' || TO_CHAR(LEAST(GREATEST(l_repeat, 1), C_MAX_REPEATS));
    END IF;

    RAISE_APPLICATION_ERROR(
      -20001,
      'ASTA_SOURCE: invalid repeat_policy. Use AUTO, ONCE, or REPEAT:<n>'
    );
  END normalize_repeat_policy;

  FUNCTION normalize_repeat_count(p_repeat_policy IN VARCHAR2) RETURN PLS_INTEGER IS
    l_policy VARCHAR2(30) := normalize_repeat_policy(p_repeat_policy);
  BEGIN
    IF l_policy = 'AUTO' THEN
      RETURN 4;
    ELSIF l_policy = 'ONCE' THEN
      RETURN 1;
    END IF;
    RETURN TO_NUMBER(SUBSTR(l_policy, 8));
  END normalize_repeat_count;

  FUNCTION sql_bind_placeholder_count(p_sql IN CLOB) RETURN PLS_INTEGER IS
    l_len       PLS_INTEGER := NVL(DBMS_LOB.GETLENGTH(p_sql), 0);
    l_pos       PLS_INTEGER := 1;
    l_count     PLS_INTEGER := 0;
    l_state     VARCHAR2(20) := 'NORMAL';
    -- These variables hold one character, not one byte. VARCHAR2(1) raises
    -- ORA-06502 as soon as a Korean/other multibyte character is encountered.
    l_char      VARCHAR2(4);
    l_next      VARCHAR2(4);
    l_q_close   VARCHAR2(4);
  BEGIN
    WHILE l_pos <= l_len LOOP
      l_char := DBMS_LOB.SUBSTR(p_sql, 1, l_pos);
      l_next := CASE WHEN l_pos < l_len THEN DBMS_LOB.SUBSTR(p_sql, 1, l_pos + 1) END;
      IF l_state = 'LINE_COMMENT' THEN
        IF l_char IN (CHR(10), CHR(13)) THEN l_state := 'NORMAL'; END IF;
      ELSIF l_state = 'BLOCK_COMMENT' THEN
        IF l_char = '*' AND l_next = '/' THEN l_state := 'NORMAL'; l_pos := l_pos + 1; END IF;
      ELSIF l_state = 'SINGLE_QUOTE' THEN
        IF l_char = '''' THEN
          IF l_next = '''' THEN l_pos := l_pos + 1; ELSE l_state := 'NORMAL'; END IF;
        END IF;
      ELSIF l_state = 'DOUBLE_QUOTE' THEN
        IF l_char = '"' THEN
          IF l_next = '"' THEN l_pos := l_pos + 1; ELSE l_state := 'NORMAL'; END IF;
        END IF;
      ELSIF l_state = 'Q_QUOTE' THEN
        IF l_char = l_q_close AND l_next = '''' THEN l_state := 'NORMAL'; l_pos := l_pos + 1; END IF;
      ELSE
        IF l_char = '-' AND l_next = '-' THEN l_state := 'LINE_COMMENT'; l_pos := l_pos + 1;
        ELSIF l_char = '/' AND l_next = '*' THEN l_state := 'BLOCK_COMMENT'; l_pos := l_pos + 1;
        ELSIF l_char = '''' THEN l_state := 'SINGLE_QUOTE';
        ELSIF l_char = '"' THEN l_state := 'DOUBLE_QUOTE';
        ELSIF UPPER(l_char) = 'Q' AND l_next = '''' AND l_pos + 2 <= l_len THEN
          l_q_close := DBMS_LOB.SUBSTR(p_sql, 1, l_pos + 2);
          l_q_close := CASE l_q_close WHEN '[' THEN ']' WHEN '(' THEN ')' WHEN '{' THEN '}' WHEN '<' THEN '>' ELSE l_q_close END;
          l_state := 'Q_QUOTE'; l_pos := l_pos + 2;
        ELSIF l_char = ':' AND l_next IS NOT NULL
              AND REGEXP_LIKE(l_next, '[A-Za-z0-9_$#]') THEN
          l_count := l_count + 1;
        END IF;
      END IF;
      l_pos := l_pos + 1;
    END LOOP;
    RETURN l_count;
  END sql_bind_placeholder_count;

  FUNCTION normalize_run_advisor(p_run_advisor IN VARCHAR2) RETURN VARCHAR2 IS
  BEGIN
    RETURN CASE
      WHEN UPPER(TRIM(NVL(p_run_advisor, 'N'))) IN ('Y', 'YES', 'TRUE', '1') THEN 'Y'
      ELSE 'N'
    END;
  END normalize_run_advisor;

  FUNCTION normalize_sqltune_time_sec(p_sqltune_time_sec IN NUMBER) RETURN PLS_INTEGER IS
  BEGIN
    RETURN LEAST(GREATEST(NVL(p_sqltune_time_sec, 1800), 60), 1800);
  END normalize_sqltune_time_sec;

  -- Browser/API callers may provide only the collected SQL_ID. The execution
  -- schema itself is resolved server-side from AWR and never trusted from the
  -- request payload.
  FUNCTION resolve_parsing_schema(p_source_sql_id IN VARCHAR2) RETURN VARCHAR2 IS
    l_sql_id VARCHAR2(13) := LOWER(TRIM(p_source_sql_id));
    l_schema VARCHAR2(128);
  BEGIN
    IF l_sql_id IS NULL THEN
      RETURN NULL;
    END IF;
    IF NOT REGEXP_LIKE(l_sql_id, '^[0-9a-z]{13}$') THEN
      RAISE_APPLICATION_ERROR(-20001, 'ASTA_SOURCE: invalid source_sql_id');
    END IF;

    SELECT parsing_schema_name
    INTO l_schema
    FROM (
      SELECT parsing_schema_name
      FROM dba_hist_sqlstat
      WHERE sql_id = l_sql_id
      AND parsing_schema_name IS NOT NULL
      ORDER BY snap_id DESC, instance_number DESC
    )
    WHERE ROWNUM = 1;

    l_schema := UPPER(TRIM(l_schema));
    IF NOT REGEXP_LIKE(l_schema, '^[A-Z][A-Z0-9_$#]{0,127}$') THEN
      RAISE_APPLICATION_ERROR(-20001, 'ASTA_SOURCE: invalid AWR parsing schema');
    END IF;
    RETURN DBMS_ASSERT.SIMPLE_SQL_NAME(l_schema);
  EXCEPTION
    WHEN NO_DATA_FOUND THEN
      RAISE_APPLICATION_ERROR(-20001, 'ASTA_SOURCE: source_sql_id not found in AWR');
  END resolve_parsing_schema;

  -- =========================================================================
  -- 커서 조회
  -- =========================================================================

  -- ASTA_RUN_ID 표식을 이용해 V$SQL에서 실행된 커서를 찾는다.
  -- 표식은 SQL_TEXT(VARCHAR2(1000))의 처음 약 100자 안에 있으므로,
  -- sql_fulltext(CLOB)에 접근하지 않고 sql_text의 INSTR만으로 충분하다.
  PROCEDURE find_cursor(
    p_run_id          IN  VARCHAR2,
    p_sql_id          OUT VARCHAR2,
    p_child_number    OUT NUMBER,
    p_plan_hash_value OUT NUMBER
  ) IS
    l_marker VARCHAR2(200) := 'ASTA_RUN_ID=' || p_run_id;
  BEGIN
    SELECT sql_id, child_number, plan_hash_value
    INTO   p_sql_id, p_child_number, p_plan_hash_value
    FROM (
      SELECT sql_id, child_number, plan_hash_value
      FROM   v$sql
      WHERE  INSTR(sql_text, l_marker) > 0
      ORDER  BY last_active_time DESC NULLS LAST, child_number DESC
    )
    WHERE  ROWNUM = 1;
  EXCEPTION
    WHEN NO_DATA_FOUND THEN
      p_sql_id          := NULL;
      p_child_number    := NULL;
      p_plan_hash_value := NULL;
  END find_cursor;

  -- Child cursor/ACS 관측은 원문 bind 값을 반환하지 않는다. 캡처 값은 Source
  -- 안에서 SHA-256 fingerprint로만 변환하며, 대표 bind를 Before/After에 실제
  -- 재적용하지 못한 현재 실행 경로는 반드시 coverage BLOCKED로 표시한다.
  FUNCTION collect_child_cursor_evidence(
    p_sql_id IN VARCHAR2,
    p_bind_placeholder_count IN PLS_INTEGER
  ) RETURN CLOB IS
    l_out CLOB;
    l_first BOOLEAN := TRUE;
    l_bind_first BOOLEAN := TRUE;
    l_bind_count PLS_INTEGER := 0;
  BEGIN
    DBMS_LOB.CREATETEMPORARY(l_out, TRUE);
    clob_app(l_out, '{"status":"COMPLETED","source":"V$SQL_AND_V$SQL_BIND_CAPTURE"');
    clob_app(l_out, ',"raw_bind_values_retained":false,"child_cursors":[');
    FOR c IN (
      SELECT child_number, plan_hash_value, executions,
             is_bind_sensitive, is_bind_aware, is_shareable
      FROM v$sql
      WHERE sql_id = LOWER(TRIM(p_sql_id))
      ORDER BY child_number
    ) LOOP
      IF NOT l_first THEN clob_app(l_out, ','); END IF;
      l_first := FALSE;
      clob_app(l_out, '{"child_number":' || json_num(c.child_number) ||
        ',"plan_hash_value":' || json_num(c.plan_hash_value) ||
        ',"executions":' || json_num(c.executions) ||
        ',"is_bind_sensitive":' || json_str(c.is_bind_sensitive) ||
        ',"is_bind_aware":' || json_str(c.is_bind_aware) ||
        ',"is_shareable":' || json_str(c.is_shareable) || '}');
    END LOOP;
    clob_app(l_out, '],"bind_metadata":[');
    FOR b IN (
      SELECT name, position, datatype_string, was_captured, last_captured,
             CASE WHEN value_string IS NULL THEN NULL
                  ELSE LOWER(RAWTOHEX(STANDARD_HASH(value_string, 'SHA256'))) END value_fingerprint
      FROM v$sql_bind_capture
      WHERE sql_id = LOWER(TRIM(p_sql_id))
      ORDER BY child_number, position
    ) LOOP
      l_bind_count := l_bind_count + 1;
      IF NOT l_bind_first THEN clob_app(l_out, ','); END IF;
      l_bind_first := FALSE;
      clob_app(l_out, '{"name":' || json_str(b.name) ||
        ',"position":' || json_num(b.position) ||
        ',"oracle_type":' || json_str(b.datatype_string) ||
        ',"was_captured":' || json_str(b.was_captured) ||
        ',"last_captured":' || json_str(TO_CHAR(b.last_captured, 'YYYY-MM-DD"T"HH24:MI:SS')) ||
        ',"value_fingerprint":' || json_str(
          CASE WHEN b.value_fingerprint IS NULL THEN NULL ELSE 'sha256:' || b.value_fingerprint END
        ) || '}');
    END LOOP;
    clob_app(l_out, '],"bind_placeholder_count":' || json_num(p_bind_placeholder_count));
    IF NVL(p_bind_placeholder_count, 0) = 0 AND l_bind_count = 0 THEN
      clob_app(l_out,
        ',"bind_coverage_status":"NOT_APPLICABLE","bind_coverage_reason":"BIND_NOT_APPLICABLE"}');
    ELSE
      clob_app(l_out,
        ',"bind_coverage_status":"BLOCKED","bind_coverage_reason":"BIND_REPLAY_NOT_PERFORMED"}');
    END IF;
    RETURN l_out;
  EXCEPTION
    WHEN OTHERS THEN
      RETURN TO_CLOB(
        '{"status":"BLOCKED","raw_bind_values_retained":false,"child_cursors":[],' ||
        '"bind_metadata":[],"bind_coverage_status":"BLOCKED",' ||
        '"bind_coverage_reason":"BIND_EVIDENCE_UNAVAILABLE"}'
      );
  END collect_child_cursor_evidence;

  -- =========================================================================
  -- 통계 수집: V$SQL_PLAN_STATISTICS_ALL의 LAST_* 값
  -- =========================================================================

  -- V$SQL_PLAN_STATISTICS_ALL에서 실행별 LAST_* 통계를 수집한다.
  -- LAST_CR_BUFFER_GETS, LAST_DISK_READS, LAST_ELAPSED_TIME은 계획 루트 행(id=0)에서 가져온다.
  -- FILTER/스칼라 서브쿼리 계획을 포함하도록 LAST_OUTPUT_ROWS는 0번과 1번 행의 최댓값을 사용한다.
  PROCEDURE collect_metrics(
    p_sql_id         IN  VARCHAR2,
    p_child_number   IN  NUMBER,
    p_output_rows    OUT NUMBER,
    p_cr_buffer_gets OUT NUMBER,
    p_disk_reads     OUT NUMBER,
    p_elapsed_us     OUT NUMBER
  ) IS
  BEGIN
    SELECT
      MAX(CASE WHEN id IN (0, 1) THEN last_output_rows   END),
      MAX(CASE WHEN id = 0      THEN last_cr_buffer_gets END),
      MAX(CASE WHEN id = 0      THEN last_disk_reads     END),
      MAX(CASE WHEN id = 0      THEN last_elapsed_time   END)
    INTO
      p_output_rows,
      p_cr_buffer_gets,
      p_disk_reads,
      p_elapsed_us
    FROM v$sql_plan_statistics_all
    WHERE sql_id       = p_sql_id
    AND   child_number = p_child_number;
  EXCEPTION
    WHEN NO_DATA_FOUND THEN
      p_output_rows    := NULL;
      p_cr_buffer_gets := NULL;
      p_disk_reads     := NULL;
      p_elapsed_us     := NULL;
  END collect_metrics;

  FUNCTION collect_optimizer_intent_evidence(
    p_sql_id       IN VARCHAR2,
    p_child_number IN NUMBER
  ) RETURN CLOB IS
    l_out CLOB;
    l_first BOOLEAN := TRUE;
    l_object_name VARCHAR2(128);
    l_object_owner VARCHAR2(128);
    l_starts NUMBER;
    l_buffers NUMBER;
    l_anti_semi_count PLS_INTEGER := 0;
  BEGIN
    DBMS_LOB.CREATETEMPORARY(l_out, TRUE);
    BEGIN
      SELECT object_owner, object_name, last_starts, last_cr_buffer_gets
      INTO l_object_owner, l_object_name, l_starts, l_buffers
      FROM (
        SELECT object_owner, object_name, last_starts, last_cr_buffer_gets
        FROM v$sql_plan_statistics_all
        WHERE sql_id = p_sql_id
          AND child_number = p_child_number
          AND object_name IS NOT NULL
          AND NVL(last_starts, 0) > 1
        ORDER BY NVL(last_cr_buffer_gets, 0) DESC, NVL(last_elapsed_time, 0) DESC, id
      )
      WHERE ROWNUM = 1;
    EXCEPTION WHEN NO_DATA_FOUND THEN
      l_object_owner := NULL; l_object_name := NULL; l_starts := NULL; l_buffers := NULL;
    END;
    SELECT COUNT(*)
    INTO l_anti_semi_count
    FROM v$sql_plan_statistics_all
    WHERE sql_id = p_sql_id
      AND child_number = p_child_number
      AND (UPPER(operation || ' ' || options) LIKE '%ANTI%'
           OR UPPER(operation || ' ' || options) LIKE '%SEMI%');

    clob_app(l_out, '{"status":"COMPLETED","source":"V$SQL_PLAN_STATISTICS_ALL_LAST"');
    clob_app(l_out, ',"dominant_repeated_owner":' || json_str(l_object_owner));
    clob_app(l_out, ',"dominant_repeated_object":' || json_str(l_object_name));
    clob_app(l_out, ',"dominant_repeated_starts":' || json_num(l_starts));
    clob_app(l_out, ',"dominant_repeated_buffers":' || json_num(l_buffers));
    clob_app(l_out, ',"anti_semi_present":' || CASE WHEN l_anti_semi_count > 0 THEN 'true' ELSE 'false' END);
    clob_app(l_out, ',"nodes":[');
    FOR n IN (
      SELECT object_owner, object_name, operation, options, last_starts, last_cr_buffer_gets
      FROM v$sql_plan_statistics_all
      WHERE sql_id = p_sql_id
        AND child_number = p_child_number
        AND object_name IS NOT NULL
        AND NVL(last_starts, 0) > 0
      ORDER BY NVL(last_cr_buffer_gets, 0) DESC, id
      FETCH FIRST 100 ROWS ONLY
    ) LOOP
      IF NOT l_first THEN clob_app(l_out, ','); END IF;
      l_first := FALSE;
      clob_app(l_out, '{"object_owner":' || json_str(n.object_owner) ||
        ',"object_name":' || json_str(n.object_name) ||
        ',"operation":' || json_str(TRIM(n.operation || ' ' || n.options)) ||
        ',"starts":' || json_num(n.last_starts) ||
        ',"buffers":' || json_num(n.last_cr_buffer_gets) || '}');
    END LOOP;
    clob_app(l_out, ']}');
    RETURN l_out;
  EXCEPTION WHEN OTHERS THEN
    RETURN TO_CLOB('{"status":"BLOCKED","reason":"OPTIMIZER_INTENT_EVIDENCE_UNAVAILABLE"}');
  END collect_optimizer_intent_evidence;

  -- =========================================================================
  -- 실행계획: DBMS_XPLAN.DISPLAY_CURSOR
  -- =========================================================================

  -- DBMS_XPLAN.DISPLAY_CURSOR 전체 출력을 하나의 CLOB으로 반환한다.
  -- 형식에는 ALLSTATS LAST(gather_plan_statistics 힌트 필요), predicate 정보,
  -- peeked bind, outline 및 note 섹션이 포함된다.
  FUNCTION collect_xplan(
    p_sql_id       IN VARCHAR2,
    p_child_number IN NUMBER
  ) RETURN CLOB IS
    l_plan  CLOB;
    l_first BOOLEAN := TRUE;
    l_line  VARCHAR2(4000);
  BEGIN
    DBMS_LOB.CREATETEMPORARY(l_plan, TRUE);
    FOR r IN (
      SELECT plan_table_output AS line_text
      FROM TABLE(
        DBMS_XPLAN.DISPLAY_CURSOR(
          sql_id          => p_sql_id,
          cursor_child_no => p_child_number,
          format          => 'ALLSTATS LAST +PREDICATE +PEEKED_BINDS +OUTLINE +NOTE'
        )
      )
    ) LOOP
      IF NOT l_first THEN
        DBMS_LOB.WRITEAPPEND(l_plan, 1, CHR(10));
      END IF;
      l_first := FALSE;
      l_line  := NVL(r.line_text, '');
      IF LENGTH(l_line) > 0 THEN
        DBMS_LOB.WRITEAPPEND(l_plan, LENGTH(l_line), l_line);
      END IF;
    END LOOP;
    RETURN l_plan;
  EXCEPTION
    WHEN OTHERS THEN
      RETURN TO_CLOB('XPLAN_ERROR: ' || SUBSTR(SQLERRM, 1, 2000));
  END collect_xplan;

  -- =========================================================================
  -- 오브젝트 메타데이터: 테이블·컬럼 통계 및 인덱스 정의
  -- =========================================================================

  FUNCTION collect_object_info(
    p_sql_id       IN VARCHAR2,
    p_child_number IN NUMBER
  ) RETURN CLOB IS
    l_out CLOB;
    l_first_table BOOLEAN := TRUE;
    l_first_col BOOLEAN;
    l_first_idx BOOLEAN;
    l_first_idx_col BOOLEAN;
  BEGIN
    DBMS_LOB.CREATETEMPORARY(l_out, TRUE);
    clob_app(l_out, '{"status":"COMPLETED","source":"PLAN_OBJECTS","table_stats":[');

    FOR t IN (
      SELECT DISTINCT
             p.object_owner AS owner,
             p.object_name  AS table_name,
             s.num_rows,
             s.blocks,
             s.empty_blocks,
             s.avg_row_len,
             s.sample_size,
             s.stale_stats,
             TO_CHAR(s.last_analyzed, 'YYYY-MM-DD"T"HH24:MI:SS') AS last_analyzed
      FROM   v$sql_plan_statistics_all p
             LEFT JOIN dba_tab_statistics s
               ON s.owner = p.object_owner
              AND s.table_name = p.object_name
      WHERE  p.sql_id = p_sql_id
      AND    p.child_number = p_child_number
      AND    p.object_owner IS NOT NULL
      AND    p.object_name IS NOT NULL
      AND    p.object_type LIKE 'TABLE%'
      ORDER BY p.object_owner, p.object_name
    ) LOOP
      IF NOT l_first_table THEN clob_app(l_out, ','); END IF;
      l_first_table := FALSE;
      clob_app(l_out, '{"owner":' || json_str(t.owner)
        || ',"table_name":' || json_str(t.table_name)
        || ',"num_rows":' || json_num(t.num_rows)
        || ',"blocks":' || json_num(t.blocks)
        || ',"empty_blocks":' || json_num(t.empty_blocks)
        || ',"avg_row_len":' || json_num(t.avg_row_len)
        || ',"sample_size":' || json_num(t.sample_size)
        || ',"last_analyzed":' || json_str(t.last_analyzed)
        || ',"stale_stats":' || json_str(t.stale_stats)
        || ',"columns":[');

      l_first_col := TRUE;
      FOR c IN (
        SELECT column_name,
               data_type,
               nullable,
               num_distinct,
               density,
               num_nulls,
               histogram,
               TO_CHAR(last_analyzed, 'YYYY-MM-DD"T"HH24:MI:SS') AS last_analyzed
        FROM   dba_tab_columns
        WHERE  owner = t.owner
        AND    table_name = t.table_name
        ORDER  BY column_id
        FETCH FIRST 60 ROWS ONLY
      ) LOOP
        IF NOT l_first_col THEN clob_app(l_out, ','); END IF;
        l_first_col := FALSE;
        clob_app(l_out, '{"column_name":' || json_str(c.column_name)
          || ',"data_type":' || json_str(c.data_type)
          || ',"nullable":' || json_str(c.nullable)
          || ',"num_distinct":' || json_num(c.num_distinct)
          || ',"density":' || json_num(c.density)
          || ',"num_nulls":' || json_num(c.num_nulls)
          || ',"histogram":' || json_str(c.histogram)
          || ',"last_analyzed":' || json_str(c.last_analyzed) || '}');
      END LOOP;

      clob_app(l_out, '],"indexes":[');
      l_first_idx := TRUE;
      FOR i IN (
        SELECT owner,
               index_name,
               index_type,
               uniqueness,
               blevel,
               leaf_blocks,
               distinct_keys,
               clustering_factor,
               num_rows,
               status,
               TO_CHAR(last_analyzed, 'YYYY-MM-DD"T"HH24:MI:SS') AS last_analyzed
        FROM   dba_indexes
        WHERE  table_owner = t.owner
        AND    table_name = t.table_name
        ORDER  BY index_name
        FETCH FIRST 30 ROWS ONLY
      ) LOOP
        IF NOT l_first_idx THEN clob_app(l_out, ','); END IF;
        l_first_idx := FALSE;
        clob_app(l_out, '{"owner":' || json_str(i.owner)
          || ',"index_name":' || json_str(i.index_name)
          || ',"index_type":' || json_str(i.index_type)
          || ',"uniqueness":' || json_str(i.uniqueness)
          || ',"blevel":' || json_num(i.blevel)
          || ',"leaf_blocks":' || json_num(i.leaf_blocks)
          || ',"distinct_keys":' || json_num(i.distinct_keys)
          || ',"clustering_factor":' || json_num(i.clustering_factor)
          || ',"num_rows":' || json_num(i.num_rows)
          || ',"status":' || json_str(i.status)
          || ',"last_analyzed":' || json_str(i.last_analyzed)
          || ',"columns":[');

        l_first_idx_col := TRUE;
        FOR ic IN (
          SELECT column_name, column_position, descend
          FROM   dba_ind_columns
          WHERE  index_owner = i.owner
          AND    index_name = i.index_name
          ORDER  BY column_position
        ) LOOP
          IF NOT l_first_idx_col THEN clob_app(l_out, ','); END IF;
          l_first_idx_col := FALSE;
          clob_app(l_out, '{"column_name":' || json_str(ic.column_name)
            || ',"position":' || json_num(ic.column_position)
            || ',"descend":' || json_str(ic.descend) || '}');
        END LOOP;
        clob_app(l_out, ']}');
      END LOOP;
      clob_app(l_out, ']}');
    END LOOP;

    clob_app(l_out, ']}');
    RETURN l_out;
  EXCEPTION
    WHEN OTHERS THEN
      RETURN TO_CLOB('{"status":"FAILED","source":"PLAN_OBJECTS","table_stats":[],"error":{"code":'
        || TO_CHAR(SQLCODE) || ',"message":' || json_str(SUBSTR(SQLERRM, 1, 2000)) || '}}');
  END collect_object_info;

  -- EXPLAIN PLAN이 PLAN_TABLE에 기록한 object만 사용해 통계와 인덱스를
  -- 수집한다. 입력 SQL은 실행하지 않으며 DBA_* dictionary만 조회한다.
  FUNCTION collect_estimated_object_info(p_statement_id IN VARCHAR2) RETURN CLOB IS
    l_out CLOB;
    l_first_table BOOLEAN := TRUE;
    l_first_col BOOLEAN;
    l_first_idx BOOLEAN;
  BEGIN
    DBMS_LOB.CREATETEMPORARY(l_out, TRUE);
    clob_app(l_out, '{"status":"COMPLETED","source":"ESTIMATED_PLAN_OBJECTS","table_stats":[');
    FOR t IN (
      SELECT DISTINCT p.object_owner owner, p.object_name table_name,
             s.num_rows, s.blocks, s.avg_row_len, s.sample_size, s.stale_stats,
             TO_CHAR(s.last_analyzed, 'YYYY-MM-DD"T"HH24:MI:SS') last_analyzed
        FROM plan_table p
        LEFT JOIN dba_tab_statistics s
          ON s.owner=p.object_owner AND s.table_name=p.object_name
       WHERE p.statement_id=p_statement_id
         AND p.object_owner IS NOT NULL AND p.object_name IS NOT NULL
         AND p.operation='TABLE ACCESS'
       ORDER BY p.object_owner, p.object_name
    ) LOOP
      IF NOT l_first_table THEN clob_app(l_out, ','); END IF;
      l_first_table := FALSE;
      clob_app(l_out, '{"owner":' || json_str(t.owner) ||
        ',"table_name":' || json_str(t.table_name) ||
        ',"num_rows":' || json_num(t.num_rows) ||
        ',"blocks":' || json_num(t.blocks) ||
        ',"avg_row_len":' || json_num(t.avg_row_len) ||
        ',"sample_size":' || json_num(t.sample_size) ||
        ',"last_analyzed":' || json_str(t.last_analyzed) ||
        ',"stale_stats":' || json_str(t.stale_stats) || ',"columns":[');
      l_first_col := TRUE;
      FOR c IN (
        SELECT column_name, data_type, nullable, column_id
          FROM dba_tab_columns
         WHERE owner=t.owner AND table_name=t.table_name
         ORDER BY column_id
         FETCH FIRST 120 ROWS ONLY
      ) LOOP
        IF NOT l_first_col THEN clob_app(l_out, ','); END IF;
        l_first_col := FALSE;
        clob_app(l_out, '{"column_name":' || json_str(c.column_name) ||
          ',"data_type":' || json_str(c.data_type) ||
          ',"nullable":' || json_str(c.nullable) ||
          ',"column_id":' || json_num(c.column_id) || '}');
      END LOOP;
      clob_app(l_out, '],"indexes":[');
      l_first_idx := TRUE;
      FOR i IN (
        SELECT x.index_name, x.uniqueness, x.status, x.visibility,
               x.blevel, x.leaf_blocks, x.distinct_keys,
               LISTAGG(c.column_name, ',') WITHIN GROUP (ORDER BY c.column_position) columns_csv
          FROM dba_indexes x
          LEFT JOIN dba_ind_columns c
            ON c.index_owner=x.owner AND c.index_name=x.index_name
         WHERE x.table_owner=t.owner AND x.table_name=t.table_name
         GROUP BY x.index_name, x.uniqueness, x.status, x.visibility,
                  x.blevel, x.leaf_blocks, x.distinct_keys
         ORDER BY x.index_name
      ) LOOP
        IF NOT l_first_idx THEN clob_app(l_out, ','); END IF;
        l_first_idx := FALSE;
        clob_app(l_out, '{"index_name":' || json_str(i.index_name) ||
          ',"uniqueness":' || json_str(i.uniqueness) ||
          ',"status":' || json_str(i.status) ||
          ',"visibility":' || json_str(i.visibility) ||
          ',"blevel":' || json_num(i.blevel) ||
          ',"leaf_blocks":' || json_num(i.leaf_blocks) ||
          ',"distinct_keys":' || json_num(i.distinct_keys) ||
          ',"columns_csv":' || json_str(i.columns_csv) || '}');
      END LOOP;
      clob_app(l_out, ']}');
    END LOOP;
    clob_app(l_out, ']}');
    RETURN l_out;
  EXCEPTION WHEN OTHERS THEN
    RETURN TO_CLOB('{"status":"FAILED","source":"ESTIMATED_PLAN_OBJECTS","table_stats":[],"message":') ||
      TO_CLOB(json_str(SUBSTR(SQLERRM, 1, 1000))) || TO_CLOB('}');
  END collect_estimated_object_info;

  FUNCTION run_estimated_evidence(
    p_sql IN CLOB, p_run_id IN VARCHAR2, p_source_sql_id IN VARCHAR2,
    p_parsing_schema IN VARCHAR2, p_plan_table_owner IN VARCHAR2
  ) RETURN CLOB IS
    l_statement_id VARCHAR2(30);
    l_plan_table_name VARCHAR2(300);
    l_explain_sql CLOB;
    l_plan_text CLOB;
    l_object_info CLOB;
    l_result CLOB;
    l_first BOOLEAN := TRUE;
    l_line VARCHAR2(4000);
  BEGIN
    l_statement_id := 'ASTA_' || TO_CHAR(ABS(DBMS_UTILITY.GET_HASH_VALUE(p_run_id, 1, 999999999)));
    -- PLAN_TABLE is commonly exposed as Oracle's public SYS.PLAN_TABLE$ synonym;
    -- qualify neither side so invoker schemas without a local table can use it.
    l_plan_table_name := 'PLAN_TABLE';
    EXECUTE IMMEDIATE 'DELETE FROM ' || l_plan_table_name || ' WHERE statement_id=:statement_id'
      USING l_statement_id;
    l_explain_sql := TO_CLOB('EXPLAIN PLAN SET STATEMENT_ID = ''') ||
      TO_CLOB(l_statement_id) || TO_CLOB(''' INTO ') ||
      TO_CLOB(l_plan_table_name) || TO_CLOB(' FOR ') || p_sql;
    EXECUTE IMMEDIATE l_explain_sql;
    -- EXPLAIN PLAN uses the requested parsing schema for name resolution, but
    -- PLAN_TABLE and package dictionary queries belong to the helper owner.
    EXECUTE IMMEDIATE 'ALTER SESSION SET CURRENT_SCHEMA = ' ||
      DBMS_ASSERT.SIMPLE_SQL_NAME(UPPER(p_plan_table_owner));

    DBMS_LOB.CREATETEMPORARY(l_plan_text, TRUE);
    FOR r IN (
      SELECT plan_table_output line_text
        FROM TABLE(DBMS_XPLAN.DISPLAY('PLAN_TABLE', l_statement_id,
          'TYPICAL +PREDICATE +ALIAS +NOTE'))
    ) LOOP
      IF NOT l_first THEN DBMS_LOB.WRITEAPPEND(l_plan_text, 1, CHR(10)); END IF;
      l_first := FALSE;
      l_line := NVL(r.line_text, '');
      IF LENGTH(l_line) > 0 THEN DBMS_LOB.WRITEAPPEND(l_plan_text, LENGTH(l_line), l_line); END IF;
    END LOOP;
    l_object_info := collect_estimated_object_info(l_statement_id);
    EXECUTE IMMEDIATE 'DELETE FROM ' || l_plan_table_name || ' WHERE statement_id=:statement_id'
      USING l_statement_id;

    DBMS_LOB.CREATETEMPORARY(l_result, TRUE);
    clob_app(l_result,
      '{"status":"COMPLETED","contract_version":"asta.v1"' ||
      ',"execution_boundary":"SOURCE_BASEDB_DBLINK_ONLY"' ||
      ',"guard_policy":' || json_str(C_GUARD_POLICY) ||
      ',"evidence_method":"EXPLAIN_PLAN_DICTIONARY_ONLY"' ||
      ',"source_sql_executed":false,"plan_kind":"ESTIMATED"' ||
      ',"metrics_source":"NONE_SQL_NOT_EXECUTED"' ||
      ',"run_id":' || json_str(p_run_id) ||
      ',"source_sql_id":' || json_str(LOWER(TRIM(p_source_sql_id))) ||
      ',"parsing_schema_name":' || json_str(p_parsing_schema) ||
      ',"sql_id":null,"child_number":null,"plan_hash_value":null' ||
      ',"fetch_rows_limit":null,"repeat_count":0,"repeat_policy":"NONE"' ||
      ',"warmup_count":0,"measurement_count":0,"completed_measurement_count":0' ||
      ',"measurement_status":"SKIPPED","measurement_reason":"SOURCE_SQL_NOT_EXECUTED"' ||
      ',"median_elapsed_time_us":null,"median_buffer_gets":null,"median_disk_reads":null,"elapsed_noise_pct":null' ||
      ',"advisor_requested":false,"sqltune_time_limit_sec":null,"row_count":null' ||
      ',"result_digest":null,"result_digest_status":"SKIPPED"' ||
      ',"result_digest_algorithm":null,"result_digest_scope":"ESTIMATED_PLAN"' ||
      ',"result_digest_mode":null,"result_metadata_digest":null,"result_total_rows":null,"result_digest_rows":null' ||
      ',"result_chunks_complete":false,"result_evidence_complete":false,"result_truncated":false' ||
      ',"result_digest_error":"SOURCE_SQL_NOT_EXECUTED"' ||
      ',"timing_scope":"EXPLAIN_PLAN_ONLY","elapsed_wall_ms":null,"elapsed_wall_ms_per_exec":null' ||
      ',"last_output_rows":null,"last_cr_buffer_gets":null,"last_disk_reads":null,"last_elapsed_time_us":null' ||
      ',"plan_text":');
    clob_app_json_str(l_result, l_plan_text);
    clob_app(l_result, ',"object_info":');
    clob_app_clob(l_result, l_object_info);
    clob_app(l_result,
      ',"child_cursor_evidence":{"status":"SKIPPED","bind_coverage_status":"NOT_EVALUATED","bind_coverage_reason":"SOURCE_SQL_NOT_EXECUTED"}' ||
      ',"optimizer_intent_evidence":{"status":"SKIPPED","reason":"ESTIMATED_PLAN_ONLY"}' ||
      ',"measurement_runs":[]' ||
      ',"advisor":{"status":"SKIPPED","report":null}' ||
      ',"error":null}');
    RETURN l_result;
  EXCEPTION
    WHEN OTHERS THEN
      BEGIN
        EXECUTE IMMEDIATE 'DELETE FROM ' || l_plan_table_name || ' WHERE statement_id=:statement_id'
          USING l_statement_id;
      EXCEPTION WHEN OTHERS THEN NULL; END;
      RETURN TO_CLOB('{"status":"FAILED","code":"ESTIMATED_PLAN_FAILED"' ||
        ',"contract_version":"asta.v1","source_sql_executed":false,"plan_kind":"ESTIMATED"' ||
        ',"error":{"code":' || TO_CHAR(SQLCODE) || ',"message":' ||
        json_str(SUBSTR(SQLERRM, 1, 2000)) || '}}');
  END run_estimated_evidence;

  -- =========================================================================
  -- SQL Tuning Advisor(선택 사항)
  -- =========================================================================

  -- run_evidence_store_vc가 직접 생성한 Scheduler job만 best-effort로 정리한다.
  -- 실행 중인 job은 Advisor 결과를 훼손하지 않도록 중지/강제 삭제하지 않는다.
  -- 정리 실패는 호출 결과를 덮어쓰지 않고 OUT 감사 상태로만 반환한다.
  PROCEDURE cleanup_advisor_scheduler_job(
    p_job_name       IN  VARCHAR2,
    p_cleanup_status OUT VARCHAR2,
    p_cleanup_detail OUT VARCHAR2
  ) IS
    l_running PLS_INTEGER := 0;
    l_exists  PLS_INTEGER := 0;
  BEGIN
    p_cleanup_status := 'NOT_CREATED';
    p_cleanup_detail := 'No Scheduler job was created.';
    IF p_job_name IS NULL THEN
      RETURN;
    END IF;

    BEGIN
      SELECT COUNT(*) INTO l_running
        FROM user_scheduler_running_jobs
       WHERE job_name = UPPER(p_job_name);
    EXCEPTION
      WHEN OTHERS THEN
        p_cleanup_status := 'CHECK_FAILED';
        p_cleanup_detail := 'Unable to inspect Scheduler running state: ' || SUBSTR(SQLERRM, 1, 1800);
        RETURN;
    END;

    IF l_running > 0 THEN
      p_cleanup_status := 'SKIPPED_RUNNING';
      p_cleanup_detail := 'Scheduler job is still RUNNING; it was left intact without STOP_JOB or force drop.';
      RETURN;
    END IF;

    BEGIN
      SELECT COUNT(*) INTO l_exists
        FROM user_scheduler_jobs
       WHERE job_name = UPPER(p_job_name);
    EXCEPTION
      WHEN OTHERS THEN
        p_cleanup_status := 'CHECK_FAILED';
        p_cleanup_detail := 'Unable to inspect Scheduler job state: ' || SUBSTR(SQLERRM, 1, 1800);
        RETURN;
    END;

    IF l_exists = 0 THEN
      p_cleanup_status := 'ALREADY_REMOVED';
      p_cleanup_detail := 'Scheduler job was already removed, including possible auto_drop cleanup.';
      RETURN;
    END IF;

    BEGIN
      DBMS_SCHEDULER.DROP_JOB(job_name => p_job_name, force => FALSE);
      p_cleanup_status := 'DROPPED';
      p_cleanup_detail := 'Inactive Scheduler job was explicitly dropped.';
    EXCEPTION
      WHEN OTHERS THEN
        p_cleanup_status := 'DROP_FAILED';
        p_cleanup_detail := 'Scheduler DROP_JOB failed without changing the Advisor result: ' || SUBSTR(SQLERRM, 1, 1700);
    END;
  EXCEPTION
    WHEN OTHERS THEN
      p_cleanup_status := 'CLEANUP_FAILED';
      p_cleanup_detail := 'Unexpected Scheduler cleanup failure: ' || SUBSTR(SQLERRM, 1, 1800);
  END cleanup_advisor_scheduler_job;

  -- 지정한 sql_id로 DBMS_SQLTUNE을 실행한다(sql_id가 없으면 sql_text 사용).
  -- 잔여 작업이 남지 않도록 성공 또는 오류와 관계없이 종료 시 tuning task를 삭제한다.
  FUNCTION run_advisor_opt(
    p_sql_id   IN VARCHAR2,
    p_sql      IN CLOB,
    p_run_id   IN VARCHAR2,
    p_time_sec IN NUMBER
  ) RETURN CLOB IS
    -- 작업명은 DBMS_SQLTUNE 명명 규칙에 맞게 prefix와 정제된 run_id로 구성한다.
    -- 버전 간 Advisor 호환성을 위해 30자 이하로 유지한다.
    l_task         VARCHAR2(30) :=
      'ASTA_' || SUBSTR(REGEXP_REPLACE(UPPER(p_run_id), '[^A-Z0-9_$#]', ''), 1, 25);
    l_created_task VARCHAR2(128);
    l_report       CLOB;
    l_time         PLS_INTEGER  := LEAST(GREATEST(NVL(p_time_sec, 300), 60), 1800);
  BEGIN
    IF p_sql_id IS NOT NULL THEN
      l_created_task := DBMS_SQLTUNE.CREATE_TUNING_TASK(
        sql_id     => p_sql_id,
        task_name  => l_task,
        time_limit => l_time
      );
    ELSE
      l_created_task := DBMS_SQLTUNE.CREATE_TUNING_TASK(
        sql_text   => p_sql,
        task_name  => l_task,
        time_limit => l_time
      );
    END IF;
    l_task := NVL(l_created_task, l_task);
    DBMS_SQLTUNE.EXECUTE_TUNING_TASK(task_name => l_task);
    l_report := DBMS_SQLTUNE.REPORT_TUNING_TASK(
      task_name => l_task,
      type      => 'TEXT',
      level     => 'TYPICAL',
      section   => 'ALL'
    );
    DBMS_SQLTUNE.DROP_TUNING_TASK(task_name => l_task);
    RETURN l_report;
  EXCEPTION
    WHEN OTHERS THEN
      -- 정리를 시도하되 DROP 오류는 무시한다.
      BEGIN
        DBMS_SQLTUNE.DROP_TUNING_TASK(task_name => l_task);
      EXCEPTION WHEN OTHERS THEN NULL;
      END;
      RETURN TO_CLOB('SQLTUNE_ERROR: ' || SUBSTR(SQLERRM, 1, 2000));
  END run_advisor_opt;

  PROCEDURE run_advisor_job(
    p_run_id   IN VARCHAR2,
    p_sql_id   IN VARCHAR2,
    p_sql_text IN VARCHAR2,
    p_time_sec IN NUMBER
  ) IS
    PRAGMA AUTONOMOUS_TRANSACTION;
    l_report CLOB;
    l_status VARCHAR2(30) := 'COMPLETED';
    l_error_message VARCHAR2(2000);
  BEGIN
    l_report := run_advisor_opt(p_sql_id, TO_CLOB(p_sql_text), p_run_id, p_time_sec);
    IF DBMS_LOB.SUBSTR(l_report, 13, 1) = 'SQLTUNE_ERROR' THEN
      l_status := 'FAILED';
    END IF;
    DELETE FROM asta_source_advisor_results WHERE run_id = p_run_id;
    INSERT INTO asta_source_advisor_results(run_id, status, report, created_at)
    VALUES(p_run_id, l_status, l_report, SYSTIMESTAMP);
    COMMIT;
  EXCEPTION
    WHEN OTHERS THEN
      ROLLBACK;
      l_error_message := SUBSTR(SQLERRM, 1, 2000);
      BEGIN
        INSERT INTO asta_source_advisor_results(run_id, status, report, created_at)
        VALUES(p_run_id, 'FAILED', TO_CLOB('SQLTUNE_ERROR: ' || l_error_message), SYSTIMESTAMP);
        COMMIT;
      EXCEPTION WHEN OTHERS THEN NULL;
      END;
  END run_advisor_job;

  -- =========================================================================
  -- 공개 진입점
  -- =========================================================================

  FUNCTION run_evidence(
    p_sql              IN CLOB,
    p_run_id           IN VARCHAR2,
    p_fetch_rows       IN NUMBER   DEFAULT 100,
    p_repeat_policy    IN VARCHAR2 DEFAULT 'AUTO',
    p_run_advisor      IN VARCHAR2 DEFAULT 'N',
    p_sqltune_time_sec IN NUMBER   DEFAULT 1800,
    p_source_sql_id    IN VARCHAR2 DEFAULT NULL,
    p_result_evidence_mode IN VARCHAR2 DEFAULT 'BOUNDED',
    p_result_max_rows  IN NUMBER DEFAULT 100000
  ) RETURN CLOB IS
    -- 실행 변수
    l_exec_sql        CLOB;
    l_digest_sql      CLOB;
    l_result_rows_json CLOB;
    l_result_digest   VARCHAR2(64);
    l_digest_status   VARCHAR2(30) := 'PENDING';
    l_digest_error    VARCHAR2(1000);
    l_row_count       NUMBER;
    l_result_total_rows NUMBER;
    l_result_mode     VARCHAR2(30);
    l_result_scope    VARCHAR2(30) := 'BOUNDED_ORDERED_FIRST_N';
    l_result_complete VARCHAR2(5) := 'false';
    l_result_max_rows PLS_INTEGER;
    l_evidence_mode   VARCHAR2(30);
    l_fetch_rows      PLS_INTEGER;
    l_repeats         PLS_INTEGER;
    l_warmup_count    PLS_INTEGER := 0;
    l_measurement_count PLS_INTEGER := 0;
    l_completed_measurements PLS_INTEGER := 0;
    l_bind_placeholder_count PLS_INTEGER := 0;
    l_measurement_runs_json VARCHAR2(32767) := '[';
    l_measurement_first BOOLEAN := TRUE;
    l_median_elapsed_us NUMBER;
    l_median_buffer_gets NUMBER;
    l_median_disk_reads NUMBER;
    l_elapsed_noise_pct NUMBER;
    l_measurement_status VARCHAR2(30) := 'BLOCKED';
    l_measurement_reason VARCHAR2(100) := 'MEASUREMENT_EVIDENCE_INCOMPLETE';
    l_start           TIMESTAMP;
    l_end             TIMESTAMP;
    l_elapsed_ms      NUMBER;
    -- 커서 식별
    l_sql_id          VARCHAR2(13);
    l_child_number    NUMBER;
    l_plan_hash_value NUMBER;
    -- 실행 통계(V$SQL_PLAN_STATISTICS_ALL의 LAST_* 값)
    l_output_rows     NUMBER;
    l_cr_buffer_gets  NUMBER;
    l_disk_reads      NUMBER;
    l_elapsed_us      NUMBER;
    -- 실행계획 원문, 오브젝트 메타데이터 및 Advisor
    l_plan_text       CLOB;
    l_object_info     CLOB;
    l_child_cursor_evidence CLOB;
    l_optimizer_intent_evidence CLOB;
    l_advisor_report  CLOB;
    l_advisor_status  VARCHAR2(30) := 'SKIPPED';
    -- 출력
    l_result          CLOB;
    l_run_id          VARCHAR2(64);
    l_repeat_policy   VARCHAR2(30);
    l_run_advisor     VARCHAR2(1);
    l_sqltune_time_sec PLS_INTEGER;
    l_original_schema  VARCHAR2(128);
    l_parsing_schema   VARCHAR2(128);
    l_schema_changed   BOOLEAN := FALSE;
  BEGIN
    -- 1. 검증: SELECT 또는 WITH만 허용한다.
    assert_safe_select(p_sql);
    l_run_id := normalize_run_id(p_run_id);

    -- 2. 조회 행 수를 안전한 범위로 제한한다.
    l_fetch_rows := LEAST(GREATEST(NVL(p_fetch_rows, 100), 1), C_MAX_FETCH_ROWS);

    -- 3. 워밍 캐시 실행을 위한 반복 횟수를 결정한다.
    l_repeat_policy := normalize_repeat_policy(p_repeat_policy);
    l_repeats := normalize_repeat_count(l_repeat_policy);
    l_warmup_count := CASE WHEN l_repeat_policy = 'AUTO' THEN 1 ELSE 0 END;
    l_measurement_count := l_repeats - l_warmup_count;
    l_bind_placeholder_count := sql_bind_placeholder_count(p_sql);
    l_run_advisor := normalize_run_advisor(p_run_advisor);
    l_sqltune_time_sec := normalize_sqltune_time_sec(p_sqltune_time_sec);
    l_evidence_mode := UPPER(TRIM(NVL(p_result_evidence_mode, 'BOUNDED')));
    IF l_evidence_mode NOT IN ('ESTIMATED_PLAN', 'PLAN_ONLY', 'BOUNDED', 'FULL_RESULT') THEN
      RAISE_APPLICATION_ERROR(-20001, 'ASTA_SOURCE: invalid result evidence mode');
    END IF;
    l_result_max_rows := LEAST(GREATEST(NVL(p_result_max_rows, 100000), 1), 1000000);
    l_result_mode := detect_result_mode(p_sql);

    -- Reproduce the namespace used when the collected SQL was originally
    -- parsed. ALTER SESSION changes name resolution only; it grants no object
    -- privileges. The ORCLAI helper still needs direct SELECT grants.
    l_original_schema := SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA');
    l_parsing_schema := resolve_parsing_schema(p_source_sql_id);
    IF l_parsing_schema IS NOT NULL AND l_parsing_schema <> UPPER(l_original_schema) THEN
      EXECUTE IMMEDIATE 'ALTER SESSION SET CURRENT_SCHEMA = ' || l_parsing_schema;
      l_schema_changed := TRUE;
    END IF;

    -- Production-safe path: parse and optimize only. No SELECT cursor is
    -- opened, no row is fetched, and no Advisor or result digest is run.
    IF l_evidence_mode = 'ESTIMATED_PLAN' THEN
      l_result := run_estimated_evidence(
        p_sql, l_run_id, p_source_sql_id, l_parsing_schema, l_original_schema
      );
      IF l_schema_changed THEN
        EXECUTE IMMEDIATE 'ALTER SESSION SET CURRENT_SCHEMA = ' ||
          DBMS_ASSERT.SIMPLE_SQL_NAME(UPPER(l_original_schema));
        l_schema_changed := FALSE;
      END IF;
      RETURN l_result;
    END IF;

    -- 4. gather_plan_statistics 힌트와 실행 표식이 포함된 제한 실행 SQL을 생성한다.
    l_exec_sql := build_exec_sql(p_sql, l_run_id, l_fetch_rows);
    l_digest_sql := build_digest_sql(p_sql, l_run_id, l_fetch_rows);

    -- 5. 실행한다(워밍 캐시 반복 루프).
    l_start := SYSTIMESTAMP;
    FOR i IN 1..l_repeats LOOP
      l_output_rows := NULL;
      l_cr_buffer_gets := NULL;
      l_disk_reads := NULL;
      l_elapsed_us := NULL;
      EXECUTE IMMEDIATE l_exec_sql INTO l_row_count;
      find_cursor(l_run_id, l_sql_id, l_child_number, l_plan_hash_value);
      IF l_sql_id IS NOT NULL THEN
        collect_metrics(
          l_sql_id, l_child_number,
          l_output_rows, l_cr_buffer_gets, l_disk_reads, l_elapsed_us
        );
      END IF;
      IF i > l_warmup_count THEN
        IF NOT l_measurement_first THEN l_measurement_runs_json := l_measurement_runs_json || ','; END IF;
        l_measurement_first := FALSE;
        l_measurement_runs_json := l_measurement_runs_json ||
          '{"phase":"MEASURE","status":"COMPLETED","sequence":' || TO_CHAR(i - l_warmup_count) ||
          ',"last_elapsed_time_us":' || json_num(l_elapsed_us) ||
          ',"last_cr_buffer_gets":' || json_num(l_cr_buffer_gets) ||
          ',"last_disk_reads":' || json_num(l_disk_reads) || '}';
        IF l_elapsed_us IS NOT NULL AND l_cr_buffer_gets IS NOT NULL THEN
          l_completed_measurements := l_completed_measurements + 1;
        END IF;
      END IF;
    END LOOP;
    l_measurement_runs_json := l_measurement_runs_json || ']';
    l_end := SYSTIMESTAMP;

    -- 경과 시간을 밀리초 단위로 계산한다(가능하면 마지막 실행, 아니면 전체 시간).
    l_elapsed_ms :=   EXTRACT(DAY    FROM (l_end - l_start)) * 86400000
                    + EXTRACT(HOUR   FROM (l_end - l_start)) * 3600000
                    + EXTRACT(MINUTE FROM (l_end - l_start)) * 60000
                    + EXTRACT(SECOND FROM (l_end - l_start)) * 1000;

    BEGIN
      SELECT MEDIAN(elapsed_us), MEDIAN(buffer_gets), MEDIAN(disk_reads),
             CASE WHEN MEDIAN(elapsed_us) > 0
                  THEN ROUND((MAX(elapsed_us) - MIN(elapsed_us)) * 100 / MEDIAN(elapsed_us), 3)
             END
      INTO l_median_elapsed_us, l_median_buffer_gets, l_median_disk_reads, l_elapsed_noise_pct
      FROM JSON_TABLE(l_measurement_runs_json, '$[*]'
        COLUMNS(
          elapsed_us NUMBER PATH '$.last_elapsed_time_us' NULL ON ERROR,
          buffer_gets NUMBER PATH '$.last_cr_buffer_gets' NULL ON ERROR,
          disk_reads NUMBER PATH '$.last_disk_reads' NULL ON ERROR
        ));
    EXCEPTION WHEN OTHERS THEN
      l_median_elapsed_us := NULL; l_median_buffer_gets := NULL;
      l_median_disk_reads := NULL; l_elapsed_noise_pct := NULL;
    END;
    IF l_warmup_count = 1 AND l_measurement_count = 3
       AND l_completed_measurements = 3
       AND l_elapsed_noise_pct IS NOT NULL AND l_elapsed_noise_pct <= 20 THEN
      l_measurement_status := 'ACCEPTED';
      l_measurement_reason := 'MEASUREMENT_ACCEPTED';
    ELSIF l_completed_measurements = 3
          AND l_elapsed_noise_pct IS NOT NULL AND l_elapsed_noise_pct > 20 THEN
      l_measurement_reason := 'MEASUREMENT_NOISE_TOO_HIGH';
    END IF;

    -- 6. sql_text의 ASTA_RUN_ID 표식으로 V$SQL에서 커서를 찾는다.
    find_cursor(l_run_id, l_sql_id, l_child_number, l_plan_hash_value);

    -- 7. V$SQL_PLAN_STATISTICS_ALL에서 실행별 LAST_* 통계를 수집한다.
    IF l_sql_id IS NOT NULL THEN
      collect_metrics(
        l_sql_id, l_child_number,
        l_output_rows, l_cr_buffer_gets, l_disk_reads, l_elapsed_us
      );
    END IF;

    -- 8. DBMS_XPLAN과 데이터 사전에서 실행계획 및 오브젝트 메타데이터를 수집한다.
    IF l_sql_id IS NOT NULL THEN
      l_plan_text := collect_xplan(l_sql_id, l_child_number);
      l_object_info := collect_object_info(l_sql_id, l_child_number);
    ELSE
      l_plan_text := TO_CLOB(
        'Cursor not found in shared pool. ASTA_RUN_ID=' || l_run_id ||
        '. Possible causes: cursor_sharing=FORCE, short shared_pool_size, ' ||
        'or query completed before V$SQL was visible.'
      );
      l_object_info := TO_CLOB('{"status":"SKIPPED","source":"PLAN_OBJECTS","table_stats":[],"message":"Cursor not found; object metadata unavailable"}');
    END IF;
    l_child_cursor_evidence := collect_child_cursor_evidence(
      COALESCE(LOWER(TRIM(p_source_sql_id)), l_sql_id),
      l_bind_placeholder_count
    );
    l_optimizer_intent_evidence := collect_optimizer_intent_evidence(l_sql_id, l_child_number);

    -- Performance/XPLAN evidence above remains the bounded execution. Full
    -- result evidence is a separate fail-closed pass and never overwrites the
    -- measured cursor metrics.
    BEGIN
      IF l_evidence_mode = 'PLAN_ONLY' THEN
        l_result_scope := 'PLAN_ONLY';
        l_digest_status := 'SKIPPED';
        l_digest_error := 'PLAN_ONLY_SCREEN';
        l_result_complete := 'false';
      ELSIF l_evidence_mode = 'FULL_RESULT' THEN
        EXECUTE IMMEDIATE build_full_count_sql(p_sql, l_run_id) INTO l_result_total_rows;
        l_result_scope := 'FULL_RESULT';
        IF l_result_total_rows > l_result_max_rows THEN
          l_digest_status := 'BLOCKED';
          l_digest_error := 'EQUIVALENCE_BUDGET_EXCEEDED';
        ELSE
          EXECUTE IMMEDIATE build_full_digest_sql(p_sql, l_run_id, l_result_mode)
            INTO l_result_rows_json;
          IF l_result_rows_json IS NULL THEN l_result_rows_json := TO_CLOB('[]'); END IF;
          l_result_digest := ordered_result_digest(
            l_result_rows_json, result_metadata_hash(p_sql), l_result_total_rows
          );
          l_digest_status := 'COMPLETED';
          l_result_complete := 'true';
        END IF;
      ELSE
        EXECUTE IMMEDIATE l_digest_sql INTO l_result_rows_json, l_result_total_rows;
        IF l_result_rows_json IS NULL THEN l_result_rows_json := TO_CLOB('[]'); END IF;
        l_result_digest := ordered_result_digest(
          l_result_rows_json, result_metadata_hash(p_sql), l_result_total_rows
        );
        l_digest_status := 'COMPLETED';
      END IF;
    EXCEPTION
      WHEN OTHERS THEN
        l_digest_status := 'FAILED';
        l_digest_error := SUBSTR(SQLERRM, 1, 1000);
        l_result_digest := NULL;
        l_result_complete := 'false';
    END;

    -- 9. 선택적으로 SQL Tuning Advisor를 실행한다.
    IF l_run_advisor = 'Y' THEN
      l_advisor_report := run_advisor_opt(l_sql_id, p_sql, l_run_id, l_sqltune_time_sec);
      l_advisor_status := CASE
        WHEN DBMS_LOB.SUBSTR(l_advisor_report, 13, 1) = 'SQLTUNE_ERROR' THEN 'FAILED'
        ELSE 'COMPLETED'
      END;
    END IF;

    -- 10. JSON CLOB 응답을 생성한다.
    DBMS_LOB.CREATETEMPORARY(l_result, TRUE);

    -- 스칼라 필드(모두 하나의 VARCHAR2 조각에 들어간다).
    clob_app(l_result,
      '{"status":"COMPLETED"'    ||
      ',"contract_version":"asta.v1"' ||
      ',"execution_boundary":"SOURCE_BASEDB_DBLINK_ONLY"' ||
      ',"guard_policy":'         || json_str(C_GUARD_POLICY)       ||
      ',"evidence_method":"BOUNDED_ORDERED_JSON_GATHER_PLAN_STATS"' ||
      ',"result_evidence_method":"FULL_RESULT_ORACLE_JSON_DIGEST_V2"' ||
      ',"metrics_source":"V$SQL_PLAN_STATISTICS_ALL_LAST"' ||
      ',"run_id":'               || json_str(l_run_id)              ||
      ',"source_sql_id":'        || json_str(LOWER(TRIM(p_source_sql_id))) ||
      ',"parsing_schema_name":'  || json_str(l_parsing_schema)       ||
      ',"sql_id":'               || json_str(l_sql_id)              ||
      ',"child_number":'         || json_num(l_child_number)        ||
      ',"plan_hash_value":'      || json_num(l_plan_hash_value)     ||
      ',"fetch_rows_limit":'     || json_num(l_fetch_rows)          ||
      ',"repeat_count":'         || json_num(l_repeats)             ||
      ',"repeat_policy":'        || json_str(l_repeat_policy)       ||
      ',"warmup_count":'         || json_num(l_warmup_count)       ||
      ',"measurement_count":'    || json_num(l_measurement_count)  ||
      ',"completed_measurement_count":' || json_num(l_completed_measurements) ||
      ',"measurement_status":'   || json_str(l_measurement_status) ||
      ',"measurement_reason":'   || json_str(l_measurement_reason) ||
      ',"median_elapsed_time_us":' || json_num(l_median_elapsed_us) ||
      ',"median_buffer_gets":'   || json_num(l_median_buffer_gets) ||
      ',"median_disk_reads":'    || json_num(l_median_disk_reads) ||
      ',"elapsed_noise_pct":'    || json_num(l_elapsed_noise_pct) ||
      ',"advisor_requested":'    || CASE WHEN l_run_advisor = 'Y' THEN 'true' ELSE 'false' END ||
      ',"sqltune_time_limit_sec":' || json_num(l_sqltune_time_sec)   ||
      ',"row_count":'            || json_num(l_row_count)           ||
      ',"result_digest":'        || json_str(l_result_digest)       ||
      ',"result_digest_status":' || json_str(l_digest_status)       ||
      ',"result_digest_algorithm":' || json_str(CASE WHEN l_result_scope = 'FULL_RESULT'
        THEN 'SHA256_ORACLE_JSON_RESULT_V2' ELSE 'SHA256_CHAINED_ORDERED_JSON_V1' END) ||
      ',"result_digest_scope":' || json_str(l_result_scope) ||
      ',"result_digest_mode":' || json_str(l_result_mode) ||
      ',"result_metadata_digest":' || json_str(CASE WHEN l_result_digest IS NOT NULL THEN result_metadata_hash(p_sql) END) ||
      ',"result_total_rows":' || json_num(l_result_total_rows) ||
      ',"result_digest_rows":'   || json_num(CASE WHEN l_digest_status = 'COMPLETED' THEN l_result_total_rows END) ||
      ',"result_chunks_complete":' || l_result_complete ||
      ',"result_evidence_complete":' || l_result_complete ||
      ',"result_truncated":false' ||
      ',"result_digest_error":'  || json_str(l_digest_error)        ||
      ',"timing_scope":"repeat_loop_total"' ||
      ',"elapsed_wall_ms":'      || json_num(ROUND(l_elapsed_ms))   ||
      ',"elapsed_wall_ms_per_exec":' || json_num(ROUND(l_elapsed_ms / l_repeats)) ||
      ',"last_output_rows":'     || json_num(l_output_rows)         ||
      ',"last_cr_buffer_gets":'  || json_num(l_cr_buffer_gets)      ||
      ',"last_disk_reads":'      || json_num(l_disk_reads)          ||
      ',"last_elapsed_time_us":' || json_num(l_elapsed_us)          ||
      ',"plan_text":'
    );
    -- plan_text를 JSON 문자열로 추가한다(대용량 CLOB일 수 있다).
    clob_app_json_str(l_result, l_plan_text);

    -- object_info를 원시 JSON으로 추가한다: LLM 근거용 테이블·컬럼 통계와 인덱스 메타데이터.
    clob_app(l_result, ',"object_info":');
    IF l_object_info IS NULL OR NVL(DBMS_LOB.GETLENGTH(l_object_info), 0) = 0 THEN
      clob_app(l_result, 'null');
    ELSE
      clob_app_clob(l_result, l_object_info);
    END IF;

    clob_app(l_result, ',"child_cursor_evidence":');
    clob_app_clob(l_result, NVL(l_child_cursor_evidence,
      TO_CLOB('{"status":"BLOCKED","bind_coverage_status":"BLOCKED","bind_coverage_reason":"BIND_EVIDENCE_UNAVAILABLE"}')));

    clob_app(l_result, ',"optimizer_intent_evidence":');
    clob_app_clob(l_result, NVL(l_optimizer_intent_evidence,
      TO_CLOB('{"status":"BLOCKED","reason":"OPTIMIZER_INTENT_EVIDENCE_UNAVAILABLE"}')));
    clob_app(l_result, ',"measurement_runs":');
    clob_app(l_result, l_measurement_runs_json);

    -- Advisor 하위 객체
    clob_app(l_result,
      ',"advisor":{"status":' || json_str(l_advisor_status) || ',"report":');
    clob_app_json_str(l_result, l_advisor_report);
    clob_app(l_result, '}');

    clob_app(l_result, ',"error":null}');
    IF l_schema_changed THEN
      EXECUTE IMMEDIATE 'ALTER SESSION SET CURRENT_SCHEMA = ' ||
        DBMS_ASSERT.SIMPLE_SQL_NAME(UPPER(l_original_schema));
      l_schema_changed := FALSE;
    END IF;
    RETURN l_result;

  EXCEPTION
    WHEN OTHERS THEN
      DECLARE
        l_error_code NUMBER := SQLCODE;
        l_error_message VARCHAR2(4000) := SUBSTR(SQLERRM, 1, 4000);
        l_error_backtrace VARCHAR2(4000) := SUBSTR(DBMS_UTILITY.FORMAT_ERROR_BACKTRACE, 1, 4000);
      BEGIN
        IF l_schema_changed THEN
          BEGIN
            EXECUTE IMMEDIATE 'ALTER SESSION SET CURRENT_SCHEMA = ' ||
              DBMS_ASSERT.SIMPLE_SQL_NAME(UPPER(l_original_schema));
          EXCEPTION WHEN OTHERS THEN NULL;
          END;
        END IF;
      -- ADB Bridge가 정확히 보고할 수 있도록 구조화된 오류 JSON을 반환한다.
      RETURN TO_CLOB(
        '{"status":"FAILED"'       ||
        ',"contract_version":"asta.v1"' ||
        ',"execution_boundary":"SOURCE_BASEDB_DBLINK_ONLY"' ||
        ',"guard_policy":' || json_str(C_GUARD_POLICY) ||
        ',"evidence_method":"BOUNDED_ORDERED_JSON_GATHER_PLAN_STATS"' ||
        ',"result_evidence_method":"FULL_RESULT_ORACLE_JSON_DIGEST_V2"' ||
        ',"metrics_source":"V$SQL_PLAN_STATISTICS_ALL_LAST"' ||
        ',"run_id":'               || json_str(p_run_id) ||
        ',"source_sql_id":'        || json_str(LOWER(TRIM(p_source_sql_id))) ||
        ',"parsing_schema_name":'  || json_str(l_parsing_schema) ||
        ',"sql_id":null,"child_number":null,"plan_hash_value":null' ||
        ',"fetch_rows_limit":null,"repeat_count":null,"repeat_policy":' ||
        json_str(SUBSTR(UPPER(TRIM(p_repeat_policy)), 1, 30)) ||
        ',"advisor_requested":null,"sqltune_time_limit_sec":null,"row_count":null' ||
        ',"result_digest":null,"result_digest_status":"FAILED"' ||
        ',"result_digest_algorithm":"SHA256_CHAINED_ORDERED_JSON_V1"' ||
        ',"result_digest_scope":' || json_str(CASE
          WHEN UPPER(TRIM(p_result_evidence_mode)) = 'FULL_RESULT' THEN 'FULL_RESULT'
          WHEN UPPER(TRIM(p_result_evidence_mode)) = 'PLAN_ONLY' THEN 'PLAN_ONLY'
          WHEN UPPER(TRIM(p_result_evidence_mode)) = 'ESTIMATED_PLAN' THEN 'ESTIMATED_PLAN'
          ELSE 'BOUNDED_ORDERED_FIRST_N' END) ||
        ',"result_digest_mode":null,"result_metadata_digest":null,"result_total_rows":null,"result_digest_rows":null' ||
        ',"result_chunks_complete":false,"result_evidence_complete":false,"result_truncated":false' ||
        ',"result_digest_error":' || json_str(l_error_message) ||
        ',"timing_scope":"repeat_loop_total","elapsed_wall_ms":null,"elapsed_wall_ms_per_exec":null' ||
        ',"last_output_rows":null,"last_cr_buffer_gets":null' ||
        ',"last_disk_reads":null,"last_elapsed_time_us":null' ||
        ',"plan_text":null' ||
        ',"object_info":{"status":"SKIPPED","source":"PLAN_OBJECTS","table_stats":[]}' ||
        ',"advisor":{"status":"SKIPPED","report":null}' ||
        ',"error":{"code":' || TO_CHAR(l_error_code) ||
        ',"message":' || json_str(l_error_message) ||
        ',"backtrace":' || json_str(l_error_backtrace) || '}}'
      );
      END;
  END run_evidence;

  FUNCTION run_evidence_store_vc(
    p_sql              IN VARCHAR2,
    p_run_id           IN VARCHAR2,
    p_fetch_rows       IN NUMBER   DEFAULT 100,
    p_repeat_policy    IN VARCHAR2 DEFAULT 'AUTO',
    p_run_advisor      IN VARCHAR2 DEFAULT 'N',
    p_sqltune_time_sec IN NUMBER   DEFAULT 1800,
    p_source_sql_id    IN VARCHAR2 DEFAULT NULL,
    p_result_evidence_mode IN VARCHAR2 DEFAULT 'BOUNDED',
    p_result_max_rows  IN NUMBER DEFAULT 100000
  ) RETURN VARCHAR2 IS
    PRAGMA AUTONOMOUS_TRANSACTION;
    l_result CLOB;
    l_len    NUMBER;
    l_sql_id VARCHAR2(13);
    l_job_name VARCHAR2(128);
    l_job_action VARCHAR2(4000);
    l_advisor_report CLOB;
    l_advisor_status VARCHAR2(30);
    l_deadline TIMESTAMP;
    l_sleep_count PLS_INTEGER := 0;
    l_advisor_fragment CLOB;
    l_source_logins VARCHAR2(30);
    l_cleanup_status VARCHAR2(30) := 'NOT_CREATED';
    l_cleanup_detail VARCHAR2(2000) := 'No Scheduler job was created.';
    l_advisor_error_message VARCHAR2(2000);
    l_outer_error_code NUMBER;
    l_outer_error_message VARCHAR2(4000);
    l_outer_error_backtrace VARCHAR2(4000);
  BEGIN
    l_result := run_evidence(
      p_sql              => TO_CLOB(p_sql),
      p_run_id           => p_run_id,
      p_fetch_rows       => p_fetch_rows,
      p_repeat_policy    => p_repeat_policy,
      p_run_advisor      => 'N',
      p_sqltune_time_sec => p_sqltune_time_sec,
      p_source_sql_id    => p_source_sql_id,
      p_result_evidence_mode => p_result_evidence_mode,
      p_result_max_rows  => p_result_max_rows
    );

    IF UPPER(NVL(p_run_advisor, 'N')) = 'Y' THEN
      BEGIN
        SELECT JSON_VALUE(l_result, '$.sql_id' RETURNING VARCHAR2(13) NULL ON ERROR)
        INTO l_sql_id
        FROM dual;
        DELETE FROM asta_source_advisor_results WHERE run_id = p_run_id;
        COMMIT;
        BEGIN
          SELECT logins INTO l_source_logins FROM v$instance;
        EXCEPTION WHEN OTHERS THEN
          l_source_logins := 'UNKNOWN';
        END;
        IF l_source_logins = 'RESTRICTED' THEN
          -- 제한 로그인 상태에서는 DB Link를 통해 실행한 DBMS_SQLTUNE/Scheduler 작업이
          -- 종료되고 ADB에 ORA-03150으로 나타날 수 있다. Source 직접접속 또는 동기
          -- SQLTUNE fallback을 시도하지 않는다. 이미 수집한 런타임 근거를 보존하고
          -- 명시적인 Advisor 실패를 반환하여 호출자가 정직한 상태로 1단계부터
          -- 계속 처리할 수 있게 한다.
          l_advisor_status := 'FAILED';
          l_advisor_report := TO_CLOB(
            'SQLTUNE_ERROR: Source DB logins are RESTRICTED, so DBMS_SQLTUNE cannot be executed safely through the ADB DB Link path. '
            || 'Action: ask DBA to open normal logins/disable restricted session for the DB Link helper path, then rerun ASTA. '
            || 'No Source DB direct fallback was attempted.'
          );
        ELSIF l_sql_id IS NULL THEN
          l_advisor_status := 'FAILED';
          l_advisor_report := TO_CLOB(
            'SQLTUNE_ERROR: Source cursor SQL_ID was not found; no Scheduler job was created.'
          );
        ELSE
          l_job_name := 'ASTA_ADV_' || SUBSTR(RAWTOHEX(SYS_GUID()), 1, 20);
          -- SQL text를 job_action에 삽입하지 않는다. 실행 직후 찾은 SQL_ID만
          -- 안전하게 인용해 전달하여 길이 제한과 PL/SQL 문자열 주입을 피한다.
          l_job_action :=
            'BEGIN ' ||
            DBMS_ASSERT.ENQUOTE_NAME(SYS_CONTEXT('USERENV', 'SESSION_USER'), FALSE) ||
            '.ASTA_SOURCE_PKG.RUN_ADVISOR_JOB(' ||
            DBMS_ASSERT.ENQUOTE_LITERAL(p_run_id) || ',' ||
            DBMS_ASSERT.ENQUOTE_LITERAL(l_sql_id) || ',NULL,' ||
            TO_CHAR(LEAST(GREATEST(NVL(p_sqltune_time_sec, 300), 60), 1800)) ||
            '); END;';
          DBMS_SCHEDULER.CREATE_JOB(
            job_name   => l_job_name,
            job_type   => 'PLSQL_BLOCK',
            job_action => l_job_action,
            enabled    => FALSE,
            auto_drop  => TRUE
          );
          DBMS_SCHEDULER.RUN_JOB(job_name => l_job_name, use_current_session => FALSE);
          COMMIT;
          l_deadline := SYSTIMESTAMP + NUMTODSINTERVAL(LEAST(GREATEST(NVL(p_sqltune_time_sec, 60), 60), 1800) + 30, 'SECOND');
          LOOP
            BEGIN
              SELECT status, report
              INTO l_advisor_status, l_advisor_report
              FROM asta_source_advisor_results
              WHERE run_id = p_run_id;
              EXIT;
            EXCEPTION
              WHEN NO_DATA_FOUND THEN
                NULL;
            END;
            EXIT WHEN SYSTIMESTAMP > l_deadline;
            DBMS_SESSION.SLEEP(1);
            l_sleep_count := l_sleep_count + 1;
          END LOOP;
          IF l_advisor_status IS NULL THEN
            l_advisor_status := 'FAILED';
            l_advisor_report := TO_CLOB('SQLTUNE_ERROR: advisor scheduler job did not finish before timeout');
          END IF;
        END IF;
        cleanup_advisor_scheduler_job(l_job_name, l_cleanup_status, l_cleanup_detail);
        DBMS_LOB.CREATETEMPORARY(l_advisor_fragment, TRUE);
        clob_app(l_advisor_fragment, ',"advisor":{"status":' || json_str(l_advisor_status) || ',"report":');
        clob_app_json_str(l_advisor_fragment, l_advisor_report);
        clob_app(l_advisor_fragment,
          ',"cleanup_status":' || json_str(l_cleanup_status) ||
          ',"cleanup_detail":' || json_str(l_cleanup_detail) || '}');
        l_result := REPLACE(
          l_result,
          ',"advisor":{"status":"SKIPPED","report":null}',
          l_advisor_fragment
        );
        l_result := REPLACE(l_result, '"advisor_requested":false', '"advisor_requested":true');
      EXCEPTION
        WHEN OTHERS THEN
          l_advisor_error_message := SUBSTR(SQLERRM, 1, 2000);
          cleanup_advisor_scheduler_job(l_job_name, l_cleanup_status, l_cleanup_detail);
          DBMS_LOB.CREATETEMPORARY(l_advisor_fragment, TRUE);
          clob_app(l_advisor_fragment, ',"advisor":{"status":"FAILED","report":');
          clob_app_json_str(l_advisor_fragment, TO_CLOB('SQLTUNE_ERROR: ' || l_advisor_error_message));
          clob_app(l_advisor_fragment,
            ',"cleanup_status":' || json_str(l_cleanup_status) ||
            ',"cleanup_detail":' || json_str(l_cleanup_detail) || '}');
          l_result := REPLACE(l_result, ',"advisor":{"status":"SKIPPED","report":null}', l_advisor_fragment);
          l_result := REPLACE(l_result, '"advisor_requested":false', '"advisor_requested":true');
      END;
    END IF;

    DELETE FROM asta_source_results WHERE run_id = p_run_id;
    INSERT INTO asta_source_results(run_id, response_json, created_at)
    VALUES (p_run_id, l_result, SYSTIMESTAMP);
    COMMIT;
    l_len := NVL(DBMS_LOB.GETLENGTH(l_result), 0);
    RETURN '{"status":"STORED","contract_version":"asta.v1","run_id":' ||
           json_str(p_run_id) || ',"length":' || json_num(l_len) || '}';
  EXCEPTION
    WHEN OTHERS THEN
      l_outer_error_code := SQLCODE;
      l_outer_error_message := SUBSTR(SQLERRM, 1, 4000);
      l_outer_error_backtrace := SUBSTR(DBMS_UTILITY.FORMAT_ERROR_BACKTRACE, 1, 4000);
      ROLLBACK;
      cleanup_advisor_scheduler_job(l_job_name, l_cleanup_status, l_cleanup_detail);
      RETURN '{"status":"FAILED","contract_version":"asta.v1","run_id":' ||
             json_str(p_run_id) ||
             ',"advisor_job_cleanup":{"status":' || json_str(l_cleanup_status) ||
             ',"detail":' || json_str(l_cleanup_detail) || '}' ||
             ',"error":{"code":' || TO_CHAR(l_outer_error_code) ||
             ',"message":' || json_str(l_outer_error_message) ||
             ',"backtrace":' || json_str(l_outer_error_backtrace) || '}}';
  END run_evidence_store_vc;

  PROCEDURE run_evidence_store_proc(
    p_sql              IN VARCHAR2,
    p_run_id           IN VARCHAR2,
    p_fetch_rows       IN NUMBER   DEFAULT 100,
    p_repeat_policy    IN VARCHAR2 DEFAULT 'AUTO',
    p_run_advisor      IN VARCHAR2 DEFAULT 'N',
    p_sqltune_time_sec IN NUMBER   DEFAULT 1800,
    p_source_sql_id    IN VARCHAR2 DEFAULT NULL,
    p_result_evidence_mode IN VARCHAR2 DEFAULT 'BOUNDED',
    p_result_max_rows  IN NUMBER DEFAULT 100000,
    p_status_json      OUT VARCHAR2
  ) IS
  BEGIN
    p_status_json := run_evidence_store_vc(
      p_sql              => p_sql,
      p_run_id           => p_run_id,
      p_fetch_rows       => p_fetch_rows,
      p_repeat_policy    => p_repeat_policy,
      p_run_advisor      => p_run_advisor,
      p_sqltune_time_sec => p_sqltune_time_sec,
      p_source_sql_id    => p_source_sql_id,
      p_result_evidence_mode => p_result_evidence_mode,
      p_result_max_rows  => p_result_max_rows
    );
  END run_evidence_store_proc;

  FUNCTION get_result_chunk(
    p_run_id IN VARCHAR2,
    p_offset IN NUMBER DEFAULT 1,
    p_amount IN NUMBER DEFAULT 8000
  ) RETURN VARCHAR2 IS
    l_result CLOB;
  BEGIN
    SELECT response_json
    INTO   l_result
    FROM   asta_source_results
    WHERE  run_id = p_run_id;

    RETURN DBMS_LOB.SUBSTR(
      l_result,
      LEAST(GREATEST(NVL(p_amount, 8000), 1), 8000),
      GREATEST(NVL(p_offset, 1), 1)
    );
  EXCEPTION
    WHEN NO_DATA_FOUND THEN
      RETURN NULL;
  END get_result_chunk;

END asta_source_pkg;
/
