# 사전 준비사항 (Prerequisites)

SELECT AI / AI Agent Team 기능을 사용하려면 애플리케이션이 접속할 **DB 사용자**에게 아래 권한을 미리 부여해야 합니다. ADMIN(또는 DBA 권한 보유자)으로 접속해 1회 실행합니다.

> 아래 예시의 사용자명 `askoracle` 은 실제 접속 DB 사용자명으로 바꿔서 실행하세요.

## DB 패키지 실행 권한 부여

```sql
-- Grant Database User Access to DBMS Packages
GRANT EXECUTE on DBMS_CLOUD_AI_AGENT to askoracle;
GRANT EXECUTE on DBMS_CLOUD_AI to askoracle;
GRANT EXECUTE on DBMS_NETWORK_ACL_ADMIN to askoracle;
GRANT EXECUTE on DBMS_CLOUD to askoracle;
GRANT CREATE ANY CONTEXT TO askoracle;
GRANT DROP ANY CONTEXT TO askoracle;
GRANT EXECUTE ON DBMS_RLS TO askoracle;
GRANT SELECT ON v$mapped_sql TO askoracle;
```

## 클라우드 인증(Principal Auth) 활성화

```sql
-- ENABLE_PRINCIPAL_AUTH → "이 사용자, 이 클라우드 인증 방식 써도 됨 (기능 활성화)"
BEGIN
    DBMS_CLOUD_ADMIN.ENABLE_PRINCIPAL_AUTH(
        provider => 'OCI',
        username => 'askoracle'
    );
END;
/
```

## SELECT AI 데이터 접근 제어 (Data Access)

SELECT AI 가 **실제 테이블 데이터에 접근**하는 것을 DB 전체 수준에서 켜고/끌 수 있습니다.
ADMIN(관리자) 권한으로만 실행 가능하며, **세션 단위가 아니라 해당 DB 전체 사용자**에게 적용됩니다.

```sql
-- 데이터 접근 허용 (기본값) — narrate / runsql / RAG / 합성데이터 생성 모두 사용 가능
BEGIN
    DBMS_CLOUD_AI.ENABLE_DATA_ACCESS();
END;
/

-- 데이터 접근 차단 — 메타데이터를 넘어서는 실데이터 접근을 막음
BEGIN
    DBMS_CLOUD_AI.DISABLE_DATA_ACCESS();
END;
/
```

- **기본 상태는 ENABLE**(데이터 접근 허용). 아무 설정도 안 했으면 켜져 있습니다.
- `DISABLE_DATA_ACCESS()` 는 **SELECT AI 가 실제 데이터를 다루는 작업을 전면 차단**합니다.
  차단되면 해당 action 호출 시 `ORA-20000: Data access is disabled for SELECT AI.` 가 발생합니다.

  | action | 데이터 접근 차단 시 |
  |---|---|
  | `showsql` / `explainsql` (SQL 텍스트만, 데이터 미접근) | ✅ 동작 |
  | `runsql` (SQL 실행 → 결과 행 반환) | ❌ 차단 (`ORA-20000`) |
  | `narrate` (결과를 LLM 이 자연어 설명) | ❌ 차단 |
  | RAG / 합성데이터 생성 | ❌ 차단 |

> **참고(데이터 보안):** SQL 생성(`runsql`/`showsql`) 단계에서 LLM 으로 보내는 것은 **스키마 메타데이터
> (테이블·컬럼명, Comment/Annotation)뿐**이며, **테이블/뷰의 실제 행·값은 LLM 에 전송되지 않습니다.**
> 결과 행을 LLM 으로 보내는 action 은 `narrate`(및 RAG·합성데이터)입니다.
> 따라서 `runsql` 이 `DISABLE_DATA_ACCESS` 에 막히는 이유는 "LLM 전송" 때문이 아니라
> **SELECT AI 가 실데이터에 접근(쿼리 실행·결과 반환)하는 것 자체**를 차단하기 때문입니다.
> 출처: [About Select AI — Usage Guidelines > Prompt Augmentation Data](https://docs.oracle.com/en-us/iaas/autonomous-database-serverless/doc/select-ai-about.html)

## 뷰 재정의 시 Comment / Annotation 보존 프로시저

`CREATE OR REPLACE VIEW` 로 뷰를 재정의하면 뷰·컬럼에 달아둔 **Comment** 와 **Annotation(23ai)** 이
유실될 수 있습니다. 이 프로시저는 재정의 **직전에 기존 메타데이터를 메모리로 수집**하고,
뷰를 재정의한 뒤 **다시 적용**해 메타데이터를 보존합니다.

- **입력**
  - `p_view_name` — 뷰 이름 (스키마 없이 뷰명만. 현재 접속 스키마 기준)
  - `p_sql` — 새 뷰 정의. `AS` 뒤의 `SELECT …` 쿼리만 넘기거나,
    `CREATE OR REPLACE VIEW … AS …` 전체 DDL 을 넘겨도 됩니다(자동 판별).
- **동작 순서**: ① 코멘트 수집 → ② annotation 수집(23ai) → ③ 뷰 재정의 →
  ④ 코멘트 재적용 → ⑤ annotation 재적용. 재정의 후 **사라진(이름변경·삭제) 컬럼**의
  메타데이터는 건너뜁니다(객체 레벨은 항상 적용).
- **권한**: `AUTHID CURRENT_USER` — 접속 사용자(뷰 소유자) 스키마에서 동작하며
  `USER_*` 딕셔너리를 사용합니다. 23ai 미만이면 annotation 단계는 자동 생략됩니다.

> 참고: 컬럼 레벨 annotation 의 뷰 적용(`ALTER VIEW … MODIFY (col ANNOTATIONS …)`)은
> DB 버전/구성에 따라 지원되지 않을 수 있습니다. 그 경우 해당 구문에서 ORA 오류가 나며,
> 뷰 레벨 annotation 과 모든 코멘트는 정상 보존됩니다.

### 프로시저 생성 스크립트

```sql
CREATE OR REPLACE PROCEDURE replace_view_keep_meta (
    p_view_name IN VARCHAR2,
    p_sql       IN CLOB
)
    AUTHID CURRENT_USER
IS
    c_view CONSTANT VARCHAR2(128) := UPPER(TRIM(p_view_name));

    -- 메타데이터 보관용 컬렉션 (재정의 전에 수집해 둔다)
    TYPE t_comment_rec IS RECORD (
        col_name VARCHAR2(128),   -- NULL = 뷰(객체) 레벨
        text     VARCHAR2(4000)
    );
    TYPE t_comment_tab IS TABLE OF t_comment_rec INDEX BY PLS_INTEGER;

    TYPE t_annot_rec IS RECORD (
        col_name VARCHAR2(128),   -- NULL = 뷰(객체) 레벨
        name     VARCHAR2(128),
        val      VARCHAR2(4000),
        has_val  BOOLEAN
    );
    TYPE t_annot_tab IS TABLE OF t_annot_rec INDEX BY PLS_INTEGER;

    l_comments t_comment_tab;
    l_annots   t_annot_tab;

    l_ddl      CLOB;
    l_stmt     VARCHAR2(32767);
    l_cnt_c    PLS_INTEGER := 0;   -- 복원한 코멘트 수
    l_cnt_a    PLS_INTEGER := 0;   -- 복원한 annotation 수
    l_skipped  PLS_INTEGER := 0;   -- 사라진 컬럼으로 건너뛴 수

    -- 작은 따옴표 이스케이프 (값 → SQL 리터럴)
    FUNCTION esc(p IN VARCHAR2) RETURN VARCHAR2 IS
    BEGIN
        RETURN REPLACE(p, '''', '''''');
    END esc;

    -- 재정의 후 해당 컬럼이 아직 존재하는지
    FUNCTION col_exists(p_col IN VARCHAR2) RETURN BOOLEAN IS
        n PLS_INTEGER;
    BEGIN
        SELECT COUNT(*) INTO n
          FROM user_tab_columns
         WHERE table_name = c_view
           AND column_name = p_col;
        RETURN n > 0;
    END col_exists;
BEGIN
    -- 0) 뷰 이름 검증 (식별자 화이트리스트)
    IF NOT REGEXP_LIKE(c_view, '^[A-Z][A-Z0-9_$#]*$') THEN
        RAISE_APPLICATION_ERROR(-20001, 'invalid view name: ' || p_view_name);
    END IF;

    -- 1) 기존 코멘트 수집 (뷰 레벨 + 컬럼 레벨)
    FOR r IN (
        SELECT NULL AS column_name, comments
          FROM user_tab_comments
         WHERE table_name = c_view AND comments IS NOT NULL
        UNION ALL
        SELECT column_name, comments
          FROM user_col_comments
         WHERE table_name = c_view AND comments IS NOT NULL
    ) LOOP
        l_comments(l_comments.COUNT + 1).col_name := r.column_name;
        l_comments(l_comments.COUNT).text         := r.comments;
    END LOOP;

    -- 2) 기존 annotation 수집 (USER_ANNOTATIONS_USAGE 존재 = 23ai). 동적 SQL 로
    --    조회해 23ai 미만에서도 프로시저가 컴파일되도록 한다.
    DECLARE
        n      PLS_INTEGER;
        cur    SYS_REFCURSOR;
        v_col  VARCHAR2(128);
        v_name VARCHAR2(128);
        v_val  VARCHAR2(4000);
    BEGIN
        SELECT COUNT(*) INTO n
          FROM all_views
         WHERE view_name = 'USER_ANNOTATIONS_USAGE';
        IF n > 0 THEN
            OPEN cur FOR
                'SELECT column_name, annotation_name, annotation_value '
                || '  FROM user_annotations_usage WHERE object_name = :v'
                USING c_view;
            LOOP
                FETCH cur INTO v_col, v_name, v_val;
                EXIT WHEN cur%NOTFOUND;
                l_annots(l_annots.COUNT + 1).col_name := v_col;
                l_annots(l_annots.COUNT).name         := v_name;
                l_annots(l_annots.COUNT).val          := v_val;
                l_annots(l_annots.COUNT).has_val      := (v_val IS NOT NULL);
            END LOOP;
            CLOSE cur;
        END IF;
    END;

    -- 3) 뷰 재정의. p_sql 이 CREATE 로 시작하면 전체 DDL, 아니면 SELECT 본문으로 간주.
    IF UPPER(LTRIM(DBMS_LOB.SUBSTR(p_sql, 20, 1))) LIKE 'CREATE%' THEN
        l_ddl := p_sql;
    ELSE
        l_ddl := 'CREATE OR REPLACE VIEW "' || c_view || '" AS ' || p_sql;
    END IF;
    EXECUTE IMMEDIATE l_ddl;

    -- 4) 코멘트 재적용 (COMMENT ON TABLE 은 뷰에도 동작)
    FOR i IN 1 .. l_comments.COUNT LOOP
        IF l_comments(i).col_name IS NULL THEN
            EXECUTE IMMEDIATE
                'COMMENT ON TABLE "' || c_view || '" IS '''
                || esc(l_comments(i).text) || '''';
            l_cnt_c := l_cnt_c + 1;
        ELSIF col_exists(l_comments(i).col_name) THEN
            EXECUTE IMMEDIATE
                'COMMENT ON COLUMN "' || c_view || '"."' || l_comments(i).col_name
                || '" IS ''' || esc(l_comments(i).text) || '''';
            l_cnt_c := l_cnt_c + 1;
        ELSE
            l_skipped := l_skipped + 1;
        END IF;
    END LOOP;

    -- 5) annotation 재적용 (ADD OR REPLACE = 멱등). 값이 없으면 이름만.
    FOR i IN 1 .. l_annots.COUNT LOOP
        IF l_annots(i).col_name IS NULL THEN
            l_stmt := 'ALTER VIEW "' || c_view || '" ANNOTATIONS (ADD OR REPLACE "'
                      || l_annots(i).name || '"';
            IF l_annots(i).has_val THEN
                l_stmt := l_stmt || ' ''' || esc(l_annots(i).val) || '''';
            END IF;
            l_stmt := l_stmt || ')';
            EXECUTE IMMEDIATE l_stmt;
            l_cnt_a := l_cnt_a + 1;
        ELSIF col_exists(l_annots(i).col_name) THEN
            l_stmt := 'ALTER VIEW "' || c_view || '" MODIFY ("' || l_annots(i).col_name
                      || '" ANNOTATIONS (ADD OR REPLACE "' || l_annots(i).name || '"';
            IF l_annots(i).has_val THEN
                l_stmt := l_stmt || ' ''' || esc(l_annots(i).val) || '''';
            END IF;
            l_stmt := l_stmt || '))';
            EXECUTE IMMEDIATE l_stmt;
            l_cnt_a := l_cnt_a + 1;
        ELSE
            l_skipped := l_skipped + 1;
        END IF;
    END LOOP;

    DBMS_OUTPUT.PUT_LINE(
        '뷰 재정의 완료: ' || c_view
        || ' | 코멘트 복원 ' || l_cnt_c
        || ' | annotation 복원 ' || l_cnt_a
        || ' | 건너뜀(사라진 컬럼) ' || l_skipped);
END replace_view_keep_meta;
/
```

### 사용 예시

#### 1) SELECT 본문만 넘기는 경우 (권장)

```sql
SET SERVEROUTPUT ON;

BEGIN
    replace_view_keep_meta(
        p_view_name => 'V_FACTSALESORDERFORCRM3YVR',
        p_sql       => q'[
            SELECT a.salesdate,
                   a.brandname,
                   a.channelname,
                   a.salesamount,
                   b.usertypename
              FROM factsalesorderforcrm3yvr a,
                   dimmemberinfo b
             WHERE a.userid_code = b.userid_code
               AND a.channelname IN ('offline', '자사몰')
               AND a.salescarryovername = '정상'
        ]'
    );
END;
/
```

> 작은따옴표가 많은 SQL 은 위처럼 **`q'[ … ]'` 인용 리터럴**로 감싸면 이스케이프가 편합니다.

#### 2) CREATE OR REPLACE 전체 DDL 을 넘기는 경우

```sql
BEGIN
    replace_view_keep_meta(
        p_view_name => 'V_FACTSALESORDERFORCRM3YVR',
        p_sql       => 'CREATE OR REPLACE VIEW v_factsalesorderforcrm3yvr AS
                        SELECT a.salesdate, a.brandname, a.salesamount
                          FROM factsalesorderforcrm3yvr a'
    );
END;
/
```

### 동작 검증

```sql
-- 코멘트 확인
SELECT 'TABLE' AS lvl, NULL AS column_name, comments
  FROM user_tab_comments WHERE table_name = 'V_FACTSALESORDERFORCRM3YVR'
UNION ALL
SELECT 'COLUMN', column_name, comments
  FROM user_col_comments WHERE table_name = 'V_FACTSALESORDERFORCRM3YVR';

-- annotation 확인 (23ai)
SELECT object_name, column_name, annotation_name, annotation_value
  FROM user_annotations_usage
 WHERE object_name = 'V_FACTSALESORDERFORCRM3YVR';
```

## Agent Team thinking 단계 제목(step title) 출력 함수

AI Agent Team 의 **thinking 과정**을 화면에 보여줄 때, 각 단계(raw prompt)를
사람이 읽기 좋은 **단계 제목**으로 변환하기 위한 함수입니다.
`USER_AI_AGENT_*_HISTORY` 등에서 가져온 raw prompt 텍스트를 입력하면,
그 안에 들어 있는 키워드(`Current Task:`, `Thought:`, `Action: …` 등)를 보고
"Analyzing the prompt", "Executing the SQL query" 같은 **짧은 제목 문자열**을 돌려줍니다.

- **입력**: `p_raw_prompt`(CLOB) — Agent step 의 원본 프롬프트 텍스트
- **반환**: `VARCHAR2` — 단계 제목 (해당 없으면 `'Processing the step'`)
- **DETERMINISTIC**: 같은 입력 → 항상 같은 결과 (부수효과 없음)
- **판별 규칙(우선순위 순)**
  - `Current Task:` 포함 → `Analyzing the prompt`
  - `Thought:` + `Final Answer:` → `Preparing the final result`
  - `Thought:` + `Action: DISTINCT_VALUES_CHECK[_SH]` → `Checking distinct values from the database`
  - `Thought:` + `Action: SQL_SH` / `RUN_SQL` / `SQL_` / `RUN_SQL_` → `Executing the SQL query`
  - `Thought:` + `Action: GET_SAMPLE_ROWS_SH` → `Discovering schema metadata using sample rows`
  - `Thought:` + `Action: WEBSEARCH` → `Searching the web`
  - `Thought:` + `Action: SUMMARIZE_CONTENT[_JS]` → `Summarizing the content`
  - `Thought:` + `Action: SELECT_AI_RAG[_JS]` → `Querying vector index`
  - 그 외 `Thought:` + `Action:` → 액션명을 정규식으로 추출해 `ACTION : <NAME>`
  - 위 어디에도 안 맞으면 → `Processing the step`

> 함수는 `genai` 스키마에 생성됩니다. 실제 접속 스키마에 맞춰 스키마 접두사(`genai.`)를
> 바꾸거나 제거해서 실행하세요. 단순 텍스트 매칭(`DBMS_LOB.INSTR`)만 사용하므로
> 별도 권한·DB 버전 의존성은 없습니다.

### 함수 생성 스크립트

```sql
-- 함수
create or replace FUNCTION genai.f_agent_step_title (
  p_raw_prompt IN CLOB
) RETURN VARCHAR2
DETERMINISTIC
AS
  v_action_name VARCHAR2(200);
  -- helper: CLOB contains?
  FUNCTION has(p_txt CLOB, p_sub VARCHAR2) RETURN BOOLEAN IS
  BEGIN
    RETURN p_txt IS NOT NULL AND DBMS_LOB.INSTR(p_txt, p_sub) > 0;
  END;
BEGIN
  IF p_raw_prompt IS NULL THEN
    RETURN 'Processing the step';
  END IF;

  -- 1) Current Task
  IF has(p_raw_prompt, 'Current Task:') THEN
    RETURN 'Analyzing the prompt';

  -- 2) Thought + Final Answer
  ELSIF has(p_raw_prompt, 'Thought:') AND has(p_raw_prompt, 'Final Answer:') THEN
    RETURN 'Preparing the final result';

  -- 3) DISTINCT VALUES CHECK (2가지 케이스가 존재)
  ELSIF has(p_raw_prompt, 'Thought:')
        AND ( has(p_raw_prompt, 'Action: DISTINCT_VALUES_CHECK_SH')
           OR has(p_raw_prompt, 'Action: DISTINCT_VALUES_CHECK') ) THEN
    RETURN 'Checking distinct values from the database';

  -- 4) SQL 실행 (SQL_SH / RUN_SQL / SQL_% / RUN_SQL_%)
  ELSIF has(p_raw_prompt, 'Thought:')
        AND ( has(p_raw_prompt, 'Action: SQL_SH')
           OR has(p_raw_prompt, 'Action: RUN_SQL')
           OR has(p_raw_prompt, 'Action: SQL_')
           OR has(p_raw_prompt, 'Action: RUN_SQL_') ) THEN
    RETURN 'Executing the SQL query';

  -- 5) 샘플 로우 기반 스키마 메타 탐색
  ELSIF has(p_raw_prompt, 'Thought:')
        AND has(p_raw_prompt, 'Action: GET_SAMPLE_ROWS_SH') THEN
    RETURN 'Discovering schema metadata using sample rows';

  -- 6) Web search
  ELSIF has(p_raw_prompt, 'Thought:')
        AND has(p_raw_prompt, 'Action: WEBSEARCH') THEN
    RETURN 'Searching the web';

  -- 7) Summarize (일반/JS)
  ELSIF has(p_raw_prompt, 'Thought:')
        AND ( has(p_raw_prompt, 'Action: SUMMARIZE_CONTENT')
           OR has(p_raw_prompt, 'Action: SUMMARIZE_CONTENT_JS') ) THEN
    RETURN 'Summarizing the content';

  -- 8) Vector / RAG (일반/JS)
  ELSIF has(p_raw_prompt, 'Thought:')
        AND ( has(p_raw_prompt, 'Action: SELECT_AI_RAG')
           OR has(p_raw_prompt, 'Action: SELECT_AI_RAG_JS') ) THEN
    RETURN 'Querying vector index';

  -- 9) 나머지 모든 Action: 은 액션명 뽑아서 표시 (APEX 소스 동일 컨셉)
  ELSIF has(p_raw_prompt, 'Thought:')
        AND has(p_raw_prompt, 'Action:') THEN

    v_action_name :=
      REGEXP_SUBSTR(
        DBMS_LOB.SUBSTR(p_raw_prompt, 32000, 1),
        'Action:\s*([A-Z0-9_]+)',
        1, 1, NULL, 1
      );

    IF v_action_name IS NOT NULL THEN
      RETURN 'ACTION : ' || v_action_name;
    ELSE
      RETURN 'Processing the step';
    END IF;

  ELSE
    RETURN 'Processing the step';
  END IF;
END;
/
```

## Select AI Test - Predefined Query 용 테이블 / 함수

메뉴 **Select AI Test - Predefined Query** 가 사용하는 객체입니다. 사전정의 SQL(case)을
`T_PREDEFINED_QUERY` 에 등록해 두고, `f_predefined_query(p_id, p_question, p_profile_name)` 가
① ID로 SQL·추출프롬프트·답변예시를 조회 → ② 질의에서 엔티티 추출(chat) → ③ 이름 기반 바인딩으로
SQL 완성·실행 → ④ FEW_SHOT 을 예시로 결과를 자연어 답변으로 생성해 반환합니다.

- **접속 사용자 스키마에 생성**합니다(앱은 스키마 접두사 없이 호출 — 객체는 접속 사용자가 소유해야 함).
- **선행 권한**: 위 [DB 패키지 실행 권한 부여](#db-패키지-실행-권한-부여)의 `DBMS_CLOUD_AI` EXECUTE 권한과,
  호출 시 넘기는 **AI Profile(`p_profile_name`)이 생성·ENABLED** 되어 있어야 합니다.
- 자세한 설계·해설은 `CJ ENM 산출물/과제1.자연어 to SQL 생성-4.predefined query function.md` 참고.

### 1) 테이블 생성

```sql
-- 이미 존재하면 ORA-00955 — 무시 가능
CREATE TABLE T_PREDEFINED_QUERY(
    ID            NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, -- 자동 증가 PK
    DESCRIPTION   VARCHAR2(4000) NOT NULL,    -- 설명 (드롭다운 표시)
    NL_QUESTION   VARCHAR2(4000) NOT NULL,    -- 자연어 질의 예시
    SQL_TEXT      CLOB           NOT NULL,    -- 정답 SQL (named 바인드 :변수 포함)
    ENTITY_PROMPT VARCHAR2(4000) NOT NULL,    -- 질의에서 엔티티를 추출하는 프롬프트
    FEW_SHOT      VARCHAR2(4000) NOT NULL,    -- 답변 형식·톤 예시 (Few-shot)
    INS_DTM       TIMESTAMP DEFAULT SYSTIMESTAMP, -- 입력 일시
    MOD_DTM       TIMESTAMP DEFAULT SYSTIMESTAMP  -- 수정 일시
);
```

### 2) 함수 생성 — `f_predefined_query`

> **PL/SQL 주의**: ① JSON 은 `RETURN JSON_OBJECT(...)` 로 직접 반환하면 PLS-00684 → `SELECT JSON_OBJECT(...) INTO v FROM DUAL` 로 받습니다. ② 바인드 중복 검사는 연관 배열 `EXISTS` 사용(VARRAY 의 `MEMBER OF` 는 불가).

```sql
CREATE OR REPLACE FUNCTION f_predefined_query(
    p_id           IN NUMBER,        -- 실행할 T_PREDEFINED_QUERY.ID (사전정의 SQL 지정)
    p_question     IN VARCHAR2,      -- 엔티티 추출·답변 생성에 쓰는 사용자 질의
    p_profile_name IN VARCHAR2       -- chat 에 사용할 AI Profile
) RETURN CLOB
IS
    v_sql_text    CLOB;              -- 사전정의 SQL (이름 바인드 :변수 포함)
    v_entity_prom VARCHAR2(4000);    -- 엔티티 추출 프롬프트
    v_few_shot    VARCHAR2(4000);    -- 답변 형식·톤 예시
    v_entity_json CLOB;              -- 추출된 엔티티 JSON
    v_result      CLOB;              -- 조회결과 JSON / 상태 JSON 반환 버퍼
    v_answer      CLOB;              -- 최종 LLM 답변 (정상 반환값)
    v_missing     VARCHAR2(4000);    -- 추출 실패한 엔티티 이름들 (CSV)
    v_err         VARCHAR2(4000);    -- SQLERRM 보관용

    -- 동적 실행 / 이름 기반 바인딩
    v_cur  INTEGER;
    v_rows INTEGER;
    v_bind VARCHAR2(200);
    v_val  VARCHAR2(4000);
    v_occ  PLS_INTEGER := 1;
    TYPE t_seen IS TABLE OF BOOLEAN INDEX BY VARCHAR2(200);
    v_seen t_seen;                   -- 같은 바인드 중복 처리 방지
BEGIN
    -- [1] ID 로 사전정의 SQL·추출프롬프트·답변예시 조회 (없으면 not_found)
    BEGIN
        SELECT SQL_TEXT, ENTITY_PROMPT, FEW_SHOT
          INTO v_sql_text, v_entity_prom, v_few_shot
          FROM T_PREDEFINED_QUERY
         WHERE ID = p_id;
    EXCEPTION
        WHEN NO_DATA_FOUND THEN
            SELECT JSON_OBJECT('status' VALUE 'not_found',
                     'result' VALUE JSON_OBJECT('id' VALUE p_id, 'question' VALUE p_question)
                     RETURNING CLOB)
              INTO v_result FROM DUAL;
            RETURN v_result;
    END;

    -- [2] ENTITY_PROMPT + 질의로 엔티티 추출(chat). 마크다운 펜스 제거.
    v_entity_json := DBMS_CLOUD_AI.GENERATE(
        prompt       => v_entity_prom || CHR(10) || '질문: "' || p_question || '"',
        profile_name => p_profile_name,
        action       => 'chat');
    v_entity_json := REGEXP_REPLACE(v_entity_json, '```[a-z]*|```', '');

    -- [3] 결과를 JSON 배열로 직렬화하도록 사전정의 SQL 을 래핑해 파싱
    --     (CHR(10) 로 감싸 SQL_TEXT 끝의 -- 줄주석이 닫는 괄호를 삼키지 않게 함)
    v_cur := DBMS_SQL.OPEN_CURSOR;
    DBMS_SQL.PARSE(v_cur,
        'SELECT JSON_ARRAYAGG(JSON_OBJECT(*) RETURNING CLOB) AS result FROM ('
        || CHR(10) || v_sql_text || CHR(10) || ')',
        DBMS_SQL.NATIVE);

    -- SQL 의 :바인드를 순회하며 엔티티 값으로 이름 바인딩. 값 없으면 v_missing 에 모은다.
    LOOP
        v_bind := REGEXP_SUBSTR(v_sql_text, ':([A-Za-z0-9_$#가-힣]+)', 1, v_occ, NULL, 1);
        EXIT WHEN v_bind IS NULL;
        v_occ := v_occ + 1;
        CONTINUE WHEN v_seen.EXISTS(v_bind);   -- 같은 이름은 한 번만 처리
        v_seen(v_bind) := TRUE;

        v_val := JSON_VALUE(v_entity_json, '$."' || v_bind || '"');
        IF v_val IS NULL OR TRIM(v_val) IS NULL THEN
            v_missing := v_missing || CASE WHEN v_missing IS NOT NULL THEN ', ' END || v_bind;
        ELSE
            DBMS_SQL.BIND_VARIABLE(v_cur, ':' || v_bind, v_val);
        END IF;
    END LOOP;

    -- [3-1] 추출 안 된 엔티티가 있으면 어떤 값이 빠졌는지 알리고 중단 (실행 시 ORA-01008 예방)
    IF v_missing IS NOT NULL THEN
        DBMS_SQL.CLOSE_CURSOR(v_cur);
        SELECT JSON_OBJECT('status' VALUE 'entity_missing',
                 'result' VALUE JSON_OBJECT(
                     'id' VALUE p_id, 'question' VALUE p_question,
                     'missing_entities' VALUE v_missing,
                     'entity_json' VALUE NVL(SUBSTR(v_entity_json, 1, 1000), 'null'))
                 RETURNING CLOB)
          INTO v_result FROM DUAL;
        RETURN v_result;
    END IF;

    -- [4] 실행 → 결과 JSON (없으면 빈 배열). 래핑 덕에 결과 컬럼은 단일 CLOB.
    DBMS_SQL.DEFINE_COLUMN(v_cur, 1, v_result);
    v_rows := DBMS_SQL.EXECUTE(v_cur);
    IF DBMS_SQL.FETCH_ROWS(v_cur) > 0 THEN
        DBMS_SQL.COLUMN_VALUE(v_cur, 1, v_result);
    END IF;
    DBMS_SQL.CLOSE_CURSOR(v_cur);
    v_result := NVL(v_result, '[]');

    -- [5] FEW_SHOT + 질문 + 조회결과로 chat 호출 → 자연어 답변 반환
    v_answer := DBMS_CLOUD_AI.GENERATE(
        prompt => '아래 [조회결과]를 근거로 [질문]에 한국어로 답변하세요.' || CHR(10)
               || '[Few shot]' || CHR(10) || v_few_shot || CHR(10)
               || '[질문]' || CHR(10) || p_question || CHR(10)
               || '[조회결과(JSON)]' || CHR(10) || v_result || CHR(10)
               || '규칙: 조회결과의 값만 사용하고 추측 금지. 빈 배열([])이면 데이터 없음으로 답하세요.',
        profile_name => p_profile_name,
        action       => 'chat');
    RETURN v_answer;

EXCEPTION
    -- 엔티티 추출·SQL 실행 등 모든 예외 → 오류 내용을 JSON 으로 반환 (호출 측이 인식 가능)
    WHEN OTHERS THEN
        v_err := SQLERRM;   -- SQLERRM 은 SQL 안에서 직접 못 쓰므로 변수에 담아 전달
        IF DBMS_SQL.IS_OPEN(v_cur) THEN DBMS_SQL.CLOSE_CURSOR(v_cur); END IF;
        SELECT JSON_OBJECT('status' VALUE 'error',
                 'result' VALUE JSON_OBJECT(
                     'error' VALUE v_err, 'question' VALUE p_question,
                     'entity_json' VALUE NVL(SUBSTR(v_entity_json, 1, 1000), 'null'))
                 RETURNING CLOB)
          INTO v_result FROM DUAL;
        RETURN v_result;
END;
/
```

### 3) 검증용 샘플 데이터 (자기완결형 — DUAL 사용, 특정 테이블 불필요)

```sql
INSERT INTO T_PREDEFINED_QUERY (DESCRIPTION, NL_QUESTION, SQL_TEXT, ENTITY_PROMPT, FEW_SHOT) VALUES (
    '기간/상품코드 에코 (검증용)',
    '전일자 상품 P001 조회',
    'SELECT :상품코드 AS "상품코드", :시작일 AS "시작일", :종료일 AS "종료일" FROM DUAL',
    '기준일은 오늘이다. 아래 질문에서 조회 기간과 상품코드를 추출하라.' || CHR(10) ||
    '반드시 아래 JSON 형식으로만 응답하라(설명 없이 JSON만):' || CHR(10) ||
    '{"시작일":"YYYYMMDD","종료일":"YYYYMMDD","상품코드":"상품코드값"}' || CHR(10) ||
    '- 전일자: 시작일=기준일-1일, 종료일=기준일',
    '예) 질문: "전일자 상품 P002 조회" → 답변: "상품 P002, 조회기간 …~… 기준입니다."'
);
COMMIT;
```

### 4) 동작 검증

```sql
SET SERVEROUTPUT ON
-- 등록된 ID 확인
SELECT ID, DESCRIPTION FROM T_PREDEFINED_QUERY ORDER BY ID;

-- 함수 호출 (p_id, p_question, p_profile_name). 프로파일명은 실제 ENABLED 프로파일로.
SELECT f_predefined_query(1, '전일자 상품 P001 조회', 'AIF_NL2SQL') AS result FROM DUAL;
```

- 정상: 조회결과를 근거로 한 **자연어 답변(CLOB)** 반환
- 엔티티 미추출: `{"status":"entity_missing","result":{"missing_entities":"…"}}`
- 함수/테이블 미존재·권한 오류 등: `{"status":"error","result":{"error":"ORA-…"}}`
