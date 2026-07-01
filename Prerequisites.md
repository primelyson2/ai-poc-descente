# 사전 준비사항 (Prerequisites)

이 문서는 두 종류의 사전 준비를 다룹니다.

1. **[프로젝트 배포(설치) 사전 준비 — HTTP / HTTPS](#프로젝트-배포설치-사전-준비--http--https)** — OCI Resource Manager 로 앱을 인스턴스에 올리기 전에 갖춰야 할 것들.
2. **DB 사전 준비** — 앱이 접속할 DB 사용자에게 부여할 권한·프로시저·함수(그 아래 모든 절).

---

## 프로젝트 배포(설치) 사전 준비 — HTTP / HTTPS

OCI Resource Manager 원클릭 스택으로 앱을 배포하기 전에 준비할 항목입니다. **HTTP**(`deploy/http/` — Load Balancer·인증서 없이 인스턴스 공인 IP 의 앱 포트로 직접 접속)와 **HTTPS**(`deploy/https/` — 공용 Load Balancer 가 TLS 종단) 두 변형이 있으며, 각각 필요한 준비물이 다릅니다.

> 배포 아키텍처·절차·트러블슈팅 전체는 [`DEPLOY_OCI.md`](DEPLOY_OCI.md) 와 [`README.md`](README.md) §4 를 1차 출처로 보세요. 여기서는 **배포 전에 미리 손봐야 하는 것**만 정리합니다.

### 공통 사전 준비 (HTTP · HTTPS 모두)

- **OCI 테넌시 + 구획(Compartment)** 과 인스턴스/네트워크 리소스를 만들 **IAM 권한**.
- 배포 리전의 **컴퓨트 서비스 한도** — 선택한 shape(기본 `VM.Standard.E5.Flex`, Always Free 는 `VM.Standard.A1.Flex`) 기준 여유. oracledb 는 Thin 모드라 ARM(A1)에서도 동작합니다.
- **기존 VCN + 서브넷** — 스택은 네트워크를 **생성하지 않고 선택**합니다. 미리 준비된 VCN/서브넷이 있어야 합니다.
- **소스가 올라간 공개(public) GitHub 리포** — RM 이 zip 아카이브를 받고 인스턴스가 `git clone` 합니다. private 리포는 실패합니다(별도 토큰/PAR 필요). 기본값: `https://github.com/primelyson2/select-ai-test.git` (브랜치 `main`).
- **SSH 공개키** *(선택)* — 인스턴스에 SSH 접속하려면 준비. 없으면 생성:
  ```bash
  ssh-keygen -t rsa -b 4096 -f ~/.ssh/id_rsa
  cat ~/.ssh/id_rsa.pub
  ```

### HTTP 배포 (`deploy/http/`) — 추가 준비

가장 준비가 적은 경로입니다. 위 공통 준비에 더해:

- **선택한 서브넷의 보안 목록(Security List/NSG) 인바운드 개방**:
  - `8000/TCP` (앱 포트) ← 클라이언트 → 인스턴스
  - `22/TCP` (SSH, 선택)
- **공인 IP** 로 접속하려면 서브넷이 public 이고 **공인 IP 할당** 옵션을 켜야 합니다(기본 켬). private 서브넷이면 해제.

> 접속 URL: `app_url = http://<공인IP>:8000`

### HTTPS 배포 (`deploy/https/`) — 추가 준비 (Terraform 밖에서 필수)

Load Balancer·리스너·백엔드는 Terraform 이 만들지만, 다음은 **반드시 별도로 미리** 준비해야 합니다(누락 시 LB 가 인증서를 못 읽어 리스너가 동작하지 않음).

1. **OCI Certificates 서비스 인증서** — 배포와 **동일 리전**에 발급된 인증서의 **OCID**. 스택 변수 `certificate_ocid` 에 입력합니다(LB 443 리스너가 참조).
2. **IAM 정책** — LB 가 Certificates 서비스 인증서를 읽도록 관리자가 1회 생성:
   ```
   Allow any-user to read leaf-certificate-bundles in compartment <구획> where all { request.principal.type = 'loadbalancer' }
   ```
   (정확한 표현은 OCI 문서 "Load Balancer + Certificates Service" 로 확인)
3. **선택한 서브넷의 보안 목록(Security List/NSG) 인바운드 개방**:
   - `443/TCP` ← 클라이언트 → LB (80→443 리다이렉트를 켜면 `80/TCP` 도)
   - `8000/TCP` ← LB → 인스턴스
   - `22/TCP` ← SSH (선택)
4. *(선택)* **LB 전용 서브넷** — 비우면 인스턴스 서브넷을 재사용. Private LB 로 쓰려면 별도 옵션.

> 접속 URL: `https_url = https://<LB IP>` (TLS 종단 = LB, LB→인스턴스 구간은 평문 HTTP:8000).
> **Private CA 발급 인증서**는 브라우저가 기본 신뢰하지 않아 경고가 뜹니다 — 클라이언트가 해당 Private CA 루트를 신뢰 저장소에 추가해야 경고 없이 접속됩니다(내부망용 정상).

### 배포 후

두 변형 모두 앱은 `config.yaml` 없이도 기동됩니다. 접속 URL 로 들어가 좌측 **[Database 관리]** 화면에서 Wallet zip 업로드로 첫 ADB 를 등록합니다(접속정보·Wallet 은 리포/Terraform 에 넣지 않음). 등록한 DB 사용자에는 아래 **DB 사전 준비** 권한이 부여되어 있어야 합니다.

---

## DB 사전 준비

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

메뉴 **Select AI Test - Predefined Query** 가 사용하는 객체입니다. 사전정의 case 를
`T_PREDEFINED_QUERY` 에 등록해 두고, `f_predefined_query(p_id, p_question, p_profile_name)` 가
① ID로 기준SQL(`SQL_TEXT`)·추출항목(`ENTITY_SPEC`)·예외규칙(`EXCEPTION_RULES`)을 조회 →
② 고정 프롬프트([역할]/[처리 절차]/[중요]/[출력 형식])와 조립 → ③ `DBMS_CLOUD_AI.GENERATE(chat)` 로
LLM 에 전달 → ④ **WHERE 가 완성된 SQL 을 `{"sql":"..."}` JSON 객체로 반환**합니다. **SQL 실행은
호출 측(앱)에서** `sql` 값을 꺼내 수행하고 결과를 Table list 로 렌더합니다(함수는 실행하지 않음).
ID 가 없으면 상태 JSON(`not_found`), 예외 시 `error` JSON 을 반환합니다.
> ⚠️ LLM 이 `sql` 값 안의 줄바꿈을 `\n` 으로 이스케이프하지 않고 실제 개행으로 넣는 경우가 있어,
> 호출 측 JSON 파서는 제어문자 허용 모드로 파싱해야 합니다(Python: `json.loads(s, strict=False)`).

- **접속 사용자 스키마에 생성**합니다(앱은 스키마 접두사 없이 호출 — 객체는 접속 사용자가 소유해야 함).
- **선행 권한**: 위 [DB 패키지 실행 권한 부여](#db-패키지-실행-권한-부여)의 `DBMS_CLOUD_AI` EXECUTE 권한과,
  호출 시 넘기는 **AI Profile(`p_profile_name`)이 생성·ENABLED** 되어 있어야 합니다.
- 자세한 설계·해설은 `CJ ENM 산출물/과제1.자연어 to SQL 생성-4.predefined query function.md` 참고.

### 1) 테이블 생성

```sql
-- 이미 존재하면 ORA-00955 — 무시 가능
CREATE TABLE T_PREDEFINED_QUERY(
    ID              NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, -- 자동 증가 PK
    DESCRIPTION     VARCHAR2(4000) NOT NULL,    -- 설명 (드롭다운 표시)
    SQL_TEXT        CLOB           NOT NULL,    -- 기준SQL (:바인드 포함)
    ENTITY_SPEC     VARCHAR2(4000) NOT NULL,    -- 질의에서 추출할 항목
    EXCEPTION_RULES VARCHAR2(4000) NOT NULL,    -- 예외규칙
    NL_QUESTION     VARCHAR2(4000) NOT NULL,    -- 자연어 질의 예시
    INS_DTM         TIMESTAMP DEFAULT SYSTIMESTAMP, -- 입력 일시
    MOD_DTM         TIMESTAMP DEFAULT SYSTIMESTAMP  -- 수정 일시
);
```

### 2) 함수 생성 — `f_predefined_query`

> **PL/SQL 주의**: ① 상태 JSON 은 `RETURN JSON_OBJECT(...)` 로 직접 반환하면 PLS-00684 → `SELECT JSON_OBJECT(...) INTO v FROM DUAL` 로 받습니다. ② 함수에 내장한 고정 프롬프트 안의 작은따옴표(`'G'`, `DATE '...'` 예시)는 PL/SQL 문자열 리터럴이라 `''` 로 이스케이프되어 있습니다. ③ 엔티티 추출·`:바인드` 치환은 **LLM 이 프롬프트 지시대로** 수행하고, 함수는 그 답변(`{"sql":"..."}` JSON)을 그대로 반환합니다.

```sql
CREATE OR REPLACE FUNCTION f_predefined_query(
    p_id           IN NUMBER,        -- 실행할 T_PREDEFINED_QUERY.ID
    p_question     IN VARCHAR2,      -- 사용자 자연어 질의
    p_profile_name IN VARCHAR2       -- 호출할 AI Profile
) RETURN CLOB
IS
    -- 고정 프롬프트([역할][처리 절차][중요][출력 형식])는 함수에 내장하고,
    -- [기준 SQL]=SQL_TEXT, [추출 항목]=ENTITY_SPEC, [예외 규칙]=EXCEPTION_RULES 는 테이블에서,
    -- [질의]=p_question 을 조립해 DBMS_CLOUD_AI.GENERATE 를 호출한다.
    -- LLM 은 WHERE 를 완성한 SQL 을 {"sql":"..."} JSON 객체로 반환한다(실행은 호출 측(앱)에서).
    v_sql_text    CLOB;
    v_entity_spec VARCHAR2(4000);
    v_exception   VARCHAR2(4000);
    v_prompt      CLOB;
    v_answer      CLOB;
    v_result      CLOB;
    v_err         VARCHAR2(4000);
BEGIN
    -- [1] ID 로 기준SQL·추출항목·예외규칙 조회 (없으면 not_found)
    BEGIN
        SELECT SQL_TEXT, ENTITY_SPEC, EXCEPTION_RULES
          INTO v_sql_text, v_entity_spec, v_exception
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

    -- [2] 프롬프트 조립 — 고정 섹션은 내장, 가변 섹션(기준SQL/추출항목/예외규칙/질의)만 끼워 넣음.
    v_prompt :=
'[역할]

너는 Oracle SQL Generator이다.

사용자의 자연어 질의를 분석하여 아래 기준 SQL의 WHERE 절을 질의에 맞게 수정한다.
바인드 변수(:변수명)는 모두 실제 리터럴 값으로 치환한다.
예외 규칙에 따라 필요한 조건은 제거한다.
최종적으로 완성된 SQL을 JSON 형식으로만 반환한다.

[처리 절차]

1. 질의에서 아래 [추출 항목]의 값을 추출한다.
2. 추출한 값으로 기준 SQL의 바인드 변수(:변수명)를 컬럼 타입에 맞는 리터럴로 치환한다.
   - VARCHAR2 : 작은따옴표('')로 감싼다.
     예) s."BRANDCODE" = ''G''
   - NUMBER : 따옴표 없이 숫자로 입력한다.
     예) s."CUSTOMERTYPE" = 1
   - DATE : DATE ''yyyy-mm-dd'' 형식으로 입력한다.
     예) s."SALESDATE" >= DATE ''2025-01-01''
3. 질의에 없는 항목은 각 항목의 기본값을 사용한다.
4. 예외 규칙에 해당하는 조건은 SQL에서 해당 조건절 전체를 삭제한다.
5. 모든 바인드 변수를 실제 값으로 치환한 완성 SQL을 JSON 객체로 반환한다.

[중요]

- 모든 :변수명은 반드시 실제 값으로 치환해야 한다.
- 최종 SQL에는 '':''로 시작하는 바인드 변수가 하나도 남아있으면 안 된다.
- SELECT 절, FROM 절, JOIN 절, ORDER BY 절은 변경하지 않는다.
- WHERE 절만 수정한다.
- 지정된 예외 규칙 외에는 SQL 구조를 변경하지 않는다.
- 설명, 해설, 근거, 마크다운, 코드블록, 주석은 출력하지 않는다.

[기준 SQL]

' || v_sql_text || '

[추출 항목]

' || v_entity_spec || '

[예외 규칙]

' || v_exception || '

[출력 형식]

반드시 아래 형식의 JSON 객체 하나만 출력한다.

{
  "sql": "완성된 SQL"
}

JSON 객체 외에는 어떠한 텍스트도 출력하지 않는다.

[질의]

' || p_question;

    -- [3] LLM 호출 → {"sql":"..."} JSON 을 그대로 반환
    v_answer := DBMS_CLOUD_AI.GENERATE(
        prompt       => v_prompt,
        profile_name => p_profile_name,
        action       => 'chat');
    RETURN v_answer;

EXCEPTION
    -- 모든 예외 → 오류 내용을 JSON 으로 반환 (호출 측이 인식 가능)
    WHEN OTHERS THEN
        v_err := SQLERRM;   -- SQLERRM 은 SQL 안에서 직접 못 쓰므로 변수에 담아 전달
        SELECT JSON_OBJECT('status' VALUE 'error',
                 'result' VALUE JSON_OBJECT('error' VALUE v_err, 'question' VALUE p_question)
                 RETURNING CLOB)
          INTO v_result FROM DUAL;
        RETURN v_result;
END;
/
```
