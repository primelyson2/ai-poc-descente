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
--   AUTHID DEFINER를 사용하므로 권한을 부여받는 사용자는 이 패키지의 EXECUTE 권한만 있으면 된다.
--
-- 설치 및 권한 부여 방법은 db/source/README.md를 참고한다.

CREATE OR REPLACE PACKAGE asta_source_pkg AUTHID CURRENT_USER AS

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
   *   p_repeat_policy    'AUTO'(워밍 실행 2회) | 'ONCE' | 'REPEAT:<n>'(n=1~5).
   *   p_run_advisor      DBMS_SQLTUNE 실행은 'Y', 생략은 'N'. 기본값: 'N'.
   *   p_sqltune_time_sec DBMS_SQLTUNE 제한시간(초, 60~1800). 기본값: 1800.
   */
  FUNCTION run_evidence(
    p_sql              IN CLOB,
    p_run_id           IN VARCHAR2,
    p_fetch_rows       IN NUMBER   DEFAULT 100,
    p_repeat_policy    IN VARCHAR2 DEFAULT 'AUTO',
    p_run_advisor      IN VARCHAR2 DEFAULT 'N',
    p_sqltune_time_sec IN NUMBER   DEFAULT 1800
  ) RETURN CLOB;

  FUNCTION run_evidence_store_vc(
    p_sql              IN VARCHAR2,
    p_run_id           IN VARCHAR2,
    p_fetch_rows       IN NUMBER   DEFAULT 100,
    p_repeat_policy    IN VARCHAR2 DEFAULT 'AUTO',
    p_run_advisor      IN VARCHAR2 DEFAULT 'N',
    p_sqltune_time_sec IN NUMBER   DEFAULT 1800
  ) RETURN VARCHAR2;

  PROCEDURE run_evidence_store_proc(
    p_sql              IN VARCHAR2,
    p_run_id           IN VARCHAR2,
    p_fetch_rows       IN NUMBER   DEFAULT 100,
    p_repeat_policy    IN VARCHAR2 DEFAULT 'AUTO',
    p_run_advisor      IN VARCHAR2 DEFAULT 'N',
    p_sqltune_time_sec IN NUMBER   DEFAULT 1800,
    p_status_json      OUT VARCHAR2
  );

  FUNCTION get_result_chunk(
    p_run_id IN VARCHAR2,
    p_offset IN NUMBER DEFAULT 1,
    p_amount IN NUMBER DEFAULT 8000
  ) RETURN VARCHAR2;

END asta_source_pkg;
/

CREATE OR REPLACE PACKAGE BODY asta_source_pkg AS

  C_MAX_FETCH_ROWS CONSTANT PLS_INTEGER := 10000;
  C_MAX_SQL_CHARS  CONSTANT PLS_INTEGER := 32767;
  C_MAX_REPEATS    CONSTANT PLS_INTEGER := 5;
  C_MAX_RUN_ID_CHARS CONSTANT PLS_INTEGER := 64;
  C_GUARD_POLICY   CONSTANT VARCHAR2(40) := 'SELECT_WITH_SINGLE_STATEMENT';

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
    l_c2  VARCHAR2(2);
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
      RETURN 2;
    ELSIF l_policy = 'ONCE' THEN
      RETURN 1;
    END IF;
    RETURN TO_NUMBER(SUBSTR(l_policy, 8));
  END normalize_repeat_count;

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
             LEFT JOIN all_tab_statistics s
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
        FROM   all_tab_columns
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
        FROM   all_indexes
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
          FROM   all_ind_columns
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

  -- =========================================================================
  -- SQL Tuning Advisor(선택 사항)
  -- =========================================================================

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
    p_sqltune_time_sec IN NUMBER   DEFAULT 1800
  ) RETURN CLOB IS
    -- 실행 변수
    l_exec_sql        CLOB;
    l_row_count       NUMBER;
    l_fetch_rows      PLS_INTEGER;
    l_repeats         PLS_INTEGER;
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
    l_advisor_report  CLOB;
    l_advisor_status  VARCHAR2(30) := 'SKIPPED';
    -- 출력
    l_result          CLOB;
    l_run_id          VARCHAR2(64);
    l_repeat_policy   VARCHAR2(30);
    l_run_advisor     VARCHAR2(1);
    l_sqltune_time_sec PLS_INTEGER;
  BEGIN
    -- 1. 검증: SELECT 또는 WITH만 허용한다.
    assert_safe_select(p_sql);
    l_run_id := normalize_run_id(p_run_id);

    -- 2. 조회 행 수를 안전한 범위로 제한한다.
    l_fetch_rows := LEAST(GREATEST(NVL(p_fetch_rows, 100), 1), C_MAX_FETCH_ROWS);

    -- 3. 워밍 캐시 실행을 위한 반복 횟수를 결정한다.
    l_repeat_policy := normalize_repeat_policy(p_repeat_policy);
    l_repeats := normalize_repeat_count(l_repeat_policy);
    l_run_advisor := normalize_run_advisor(p_run_advisor);
    l_sqltune_time_sec := normalize_sqltune_time_sec(p_sqltune_time_sec);

    -- 4. gather_plan_statistics 힌트와 실행 표식이 포함된 제한 실행 SQL을 생성한다.
    l_exec_sql := build_exec_sql(p_sql, l_run_id, l_fetch_rows);

    -- 5. 실행한다(워밍 캐시 반복 루프).
    l_start := SYSTIMESTAMP;
    FOR i IN 1..l_repeats LOOP
      EXECUTE IMMEDIATE l_exec_sql INTO l_row_count;
    END LOOP;
    l_end := SYSTIMESTAMP;

    -- 경과 시간을 밀리초 단위로 계산한다(가능하면 마지막 실행, 아니면 전체 시간).
    l_elapsed_ms :=   EXTRACT(DAY    FROM (l_end - l_start)) * 86400000
                    + EXTRACT(HOUR   FROM (l_end - l_start)) * 3600000
                    + EXTRACT(MINUTE FROM (l_end - l_start)) * 60000
                    + EXTRACT(SECOND FROM (l_end - l_start)) * 1000;

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
      ',"evidence_method":"BOUNDED_COUNT_GATHER_PLAN_STATS"' ||
      ',"metrics_source":"V$SQL_PLAN_STATISTICS_ALL_LAST"' ||
      ',"run_id":'               || json_str(l_run_id)              ||
      ',"sql_id":'               || json_str(l_sql_id)              ||
      ',"child_number":'         || json_num(l_child_number)        ||
      ',"plan_hash_value":'      || json_num(l_plan_hash_value)     ||
      ',"fetch_rows_limit":'     || json_num(l_fetch_rows)          ||
      ',"repeat_count":'         || json_num(l_repeats)             ||
      ',"repeat_policy":'        || json_str(l_repeat_policy)       ||
      ',"advisor_requested":'    || CASE WHEN l_run_advisor = 'Y' THEN 'true' ELSE 'false' END ||
      ',"sqltune_time_limit_sec":' || json_num(l_sqltune_time_sec)   ||
      ',"row_count":'            || json_num(l_row_count)           ||
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
      clob_app(l_result, l_object_info);
    END IF;

    -- Advisor 하위 객체
    clob_app(l_result,
      ',"advisor":{"status":' || json_str(l_advisor_status) || ',"report":');
    clob_app_json_str(l_result, l_advisor_report);
    clob_app(l_result, '}');

    clob_app(l_result, ',"error":null}');
    RETURN l_result;

  EXCEPTION
    WHEN OTHERS THEN
      -- ADB Bridge가 정확히 보고할 수 있도록 구조화된 오류 JSON을 반환한다.
      RETURN TO_CLOB(
        '{"status":"FAILED"'       ||
        ',"contract_version":"asta.v1"' ||
        ',"execution_boundary":"SOURCE_BASEDB_DBLINK_ONLY"' ||
        ',"guard_policy":' || json_str(C_GUARD_POLICY) ||
        ',"evidence_method":"BOUNDED_COUNT_GATHER_PLAN_STATS"' ||
        ',"metrics_source":"V$SQL_PLAN_STATISTICS_ALL_LAST"' ||
        ',"run_id":'               || json_str(p_run_id) ||
        ',"sql_id":null,"child_number":null,"plan_hash_value":null' ||
        ',"fetch_rows_limit":null,"repeat_count":null,"repeat_policy":' ||
        json_str(SUBSTR(UPPER(TRIM(p_repeat_policy)), 1, 30)) ||
        ',"advisor_requested":null,"sqltune_time_limit_sec":null,"row_count":null,"timing_scope":"repeat_loop_total","elapsed_wall_ms":null,"elapsed_wall_ms_per_exec":null' ||
        ',"last_output_rows":null,"last_cr_buffer_gets":null' ||
        ',"last_disk_reads":null,"last_elapsed_time_us":null' ||
        ',"plan_text":null' ||
        ',"object_info":{"status":"SKIPPED","source":"PLAN_OBJECTS","table_stats":[]}' ||
        ',"advisor":{"status":"SKIPPED","report":null}' ||
        ',"error":{"code":' || TO_CHAR(SQLCODE) ||
        ',"message":' || json_str(SUBSTR(SQLERRM, 1, 4000)) || '}}'
      );
  END run_evidence;

  FUNCTION run_evidence_store_vc(
    p_sql              IN VARCHAR2,
    p_run_id           IN VARCHAR2,
    p_fetch_rows       IN NUMBER   DEFAULT 100,
    p_repeat_policy    IN VARCHAR2 DEFAULT 'AUTO',
    p_run_advisor      IN VARCHAR2 DEFAULT 'N',
    p_sqltune_time_sec IN NUMBER   DEFAULT 1800
  ) RETURN VARCHAR2 IS
    PRAGMA AUTONOMOUS_TRANSACTION;
    l_result CLOB;
    l_len    NUMBER;
    l_sql_id VARCHAR2(13);
    l_job_name VARCHAR2(128);
    l_advisor_report CLOB;
    l_advisor_status VARCHAR2(30);
    l_deadline TIMESTAMP;
    l_sleep_count PLS_INTEGER := 0;
    l_advisor_fragment CLOB;
    l_source_logins VARCHAR2(30);
  BEGIN
    l_result := run_evidence(
      p_sql              => TO_CLOB(p_sql),
      p_run_id           => p_run_id,
      p_fetch_rows       => p_fetch_rows,
      p_repeat_policy    => p_repeat_policy,
      p_run_advisor      => 'N',
      p_sqltune_time_sec => p_sqltune_time_sec
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
        ELSE
          l_job_name := 'ASTA_ADV_' || SUBSTR(RAWTOHEX(SYS_GUID()), 1, 20);
          DBMS_SCHEDULER.CREATE_JOB(
            job_name   => l_job_name,
            job_type   => 'PLSQL_BLOCK',
            job_action => 'BEGIN asta_source_pkg.run_advisor_job(' ||
                          json_str(p_run_id) || ',' || json_str(l_sql_id) || ',' ||
                          json_str(SUBSTR(p_sql, 1, 32767)) || ',' ||
                          TO_CHAR(LEAST(GREATEST(NVL(p_sqltune_time_sec, 300), 60), 1800)) ||
                          '); END;',
            enabled    => TRUE,
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
        DBMS_LOB.CREATETEMPORARY(l_advisor_fragment, TRUE);
        clob_app(l_advisor_fragment, ',"advisor":{"status":' || json_str(l_advisor_status) || ',"report":');
        clob_app_json_str(l_advisor_fragment, l_advisor_report);
        clob_app(l_advisor_fragment, '}');
        l_result := REPLACE(
          l_result,
          ',"advisor":{"status":"SKIPPED","report":null}',
          l_advisor_fragment
        );
        l_result := REPLACE(l_result, '"advisor_requested":false', '"advisor_requested":true');
      EXCEPTION
        WHEN OTHERS THEN
          DBMS_LOB.CREATETEMPORARY(l_advisor_fragment, TRUE);
          clob_app(l_advisor_fragment, ',"advisor":{"status":"FAILED","report":');
          clob_app_json_str(l_advisor_fragment, TO_CLOB('SQLTUNE_ERROR: ' || SUBSTR(SQLERRM, 1, 2000)));
          clob_app(l_advisor_fragment, '}');
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
      ROLLBACK;
      RETURN '{"status":"FAILED","contract_version":"asta.v1","run_id":' ||
             json_str(p_run_id) || ',"error":{"code":' || TO_CHAR(SQLCODE) ||
             ',"message":' || json_str(SUBSTR(SQLERRM, 1, 4000)) || '}}';
  END run_evidence_store_vc;

  PROCEDURE run_evidence_store_proc(
    p_sql              IN VARCHAR2,
    p_run_id           IN VARCHAR2,
    p_fetch_rows       IN NUMBER   DEFAULT 100,
    p_repeat_policy    IN VARCHAR2 DEFAULT 'AUTO',
    p_run_advisor      IN VARCHAR2 DEFAULT 'N',
    p_sqltune_time_sec IN NUMBER   DEFAULT 1800,
    p_status_json      OUT VARCHAR2
  ) IS
  BEGIN
    p_status_json := run_evidence_store_vc(
      p_sql              => p_sql,
      p_run_id           => p_run_id,
      p_fetch_rows       => p_fetch_rows,
      p_repeat_policy    => p_repeat_policy,
      p_run_advisor      => p_run_advisor,
      p_sqltune_time_sec => p_sqltune_time_sec
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
