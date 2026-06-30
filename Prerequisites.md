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
