# Select AI 가이드

Oracle Autonomous Database 의 **Select AI**(`DBMS_CLOUD_AI`) 로 자연어→SQL(NL2SQL)·대화를 구성하는 절차를 정리한 문서입니다. AI Profile 은 "어떤 LLM 을, 어떤 자격증명으로, 어떤 테이블 대상으로 쓸지"를 담는 설정 단위입니다.

> 이 문서의 예시는 특정 회사가 아니라 **일반 인사(HR) 스키마**(`EMPLOYEES`·`DEPARTMENTS`·`JOBS`·`JOB_HISTORY`·`LOCATIONS`)를 대상으로 합니다. 실제 환경의 **스키마 소유자·테이블·DB 유저명**으로 바꿔 사용하세요.

---

## 1. OCI Generative AI LLM 활용 — AI Profile 생성

OCI **Generative AI** 를 LLM 으로 사용하는 프로필입니다. API 키 대신 **리소스 주체(Resource Principal)** 자격증명(`OCI$RESOURCE_PRINCIPAL`)으로 인증하므로, 키를 DB 에 저장할 필요가 없습니다.

### 사전 준비
- **Principal Auth 활성화** + **IAM 정책**: ADB 가 리소스 주체로 OCI GenAI 를 호출할 수 있어야 합니다. 동적 그룹 + `generative-ai-family` 사용 권한이 필요합니다 → [`Prerequisites.md`](Prerequisites.md) 의 **"필요 IAM 정책 (Policy) 모음" 1) SELECT AI ↔ OCI Generative AI 접근** 참고.
- **DB 패키지 권한**: 접속 사용자에 `DBMS_CLOUD_AI` EXECUTE ([`Prerequisites.md`](Prerequisites.md) "DB 패키지 실행 권한 부여").
- **리전 제공 여부**: `region` 에 지정한 곳(예: `us-chicago-1`)에서 해당 `model` 이 제공되어야 합니다.
- **대상 테이블**: `object_list` 의 객체가 실제 존재하고 접속 사용자가 조회 권한을 가져야 합니다.

### 생성 스크립트

```sql
BEGIN
    dbms_cloud_ai.drop_profile(
        profile_name => 'AIF_NL2SQL',
        force => true
    );

    dbms_cloud_ai.create_profile(
        profile_name => 'AIF_NL2SQL',
        attributes =>
            '{"annotations": "true",
            "comments": "true",
            "constraints": "true",
            "credential_name": "OCI$RESOURCE_PRINCIPAL",
            "embedding_model": "cohere.embed-v4.0",
            "enforce_object_list": "true",
            "max_tokens": 1500,
            "model": "openai.gpt-5.4",
            "object_list": [
                {"owner": "HR", "name": "EMPLOYEES"},
                {"owner": "HR", "name": "DEPARTMENTS"},
                {"owner": "HR", "name": "JOBS"},
                {"owner": "HR", "name": "JOB_HISTORY"},
                {"owner": "HR", "name": "LOCATIONS"}
            ],
            "object_list_mode": "all",
            "provider": "oci",
            "region": "us-chicago-1",
            "temperature": 0
            }'
        );
END;
/
```

> `drop_profile(..., force => true)` 를 먼저 호출하므로, 같은 이름의 프로필이 있으면 지우고 새로 만듭니다(없어도 `force => true` 라 오류 없음). 즉 **재실행 가능(idempotent)** 스크립트입니다.

### 속성(attributes) 설명

| 속성 | 값(예시) | 의미 |
|---|---|---|
| `provider` | `oci` | LLM 공급자 = OCI Generative AI |
| `region` | `us-chicago-1` | GenAI 호출 리전(해당 모델 제공 리전이어야 함) |
| `model` | `openai.gpt-5.4` | 사용할 생성 모델(OCI GenAI 카탈로그의 모델명) |
| `credential_name` | `OCI$RESOURCE_PRINCIPAL` | 리소스 주체 인증(별도 API 키 불필요) |
| `embedding_model` | `cohere.embed-v4.0` | 임베딩 모델 — RAG/유사도(few-shot 검색)용 |
| `object_list` | `HR.*` 목록 | NL2SQL 대상 테이블/뷰 (owner+name) |
| `object_list_mode` | `all` | 대상 목록 처리 방식 |
| `enforce_object_list` | `true` | **object_list 에 있는 객체로만** 제한 |
| `comments` | `true` | 컬럼/테이블 **Comment** 를 스키마 컨텍스트에 포함 |
| `annotations` | `true` | 23ai **Annotation** 메타데이터 포함 |
| `constraints` | `true` | 제약조건(PK/FK 등) 정보 포함 → 조인 추론 개선 |
| `max_tokens` | `1500` | 응답 최대 토큰 |
| `temperature` | `0` | 0=결정적(재현성↑), 높을수록 다양성↑ |

> `comments`·`annotations`·`constraints` 를 `true` 로 두면 스키마 메타데이터가 LLM 프롬프트에 함께 전달되어 **NL2SQL 정확도가 올라갑니다**. (테이블/컬럼 Comment·Annotation 을 잘 채워둘수록 효과가 큼 — 이 도구의 **AI Profile Object Meta** 화면에서 관리)

### 생성 확인

```sql
-- 프로필 목록
SELECT profile_name, status FROM user_cloud_ai_profiles WHERE profile_name = 'AIF_NL2SQL';

-- 속성 확인
SELECT attribute_name, attribute_value
FROM   user_cloud_ai_profile_attributes
WHERE  profile_name = 'AIF_NL2SQL'
ORDER  BY attribute_name;
```

- 생성 후 이 PoC 도구의 **AI Profile Test** 화면 드롭다운에 `AIF_NL2SQL` 이 나타나면 정상입니다.
- 빠른 동작 확인:
  ```sql
  SELECT DBMS_CLOUD_AI.GENERATE(
           prompt       => '부서별 직원 수를 알려줘',
           profile_name => 'AIF_NL2SQL',
           action       => 'showsql') AS sql_text
  FROM dual;
  ```

### 다른 OCI Tenancy 의 Gen AI 사용 (크로스-테넌시)

기본 프로필은 `OCI$RESOURCE_PRINCIPAL`(리소스 주체)로 인증하는데, 이는 **ADB 자신이 속한 tenancy 의 신원**이라 자기 tenancy 의 Gen AI 만 호출됩니다. **다른 tenancy 의 Gen AI** 를 쓰려면:
1. **인증 주체(`credential_name`)** 를 그 tenancy 에 접근 권한이 있는 사용자로 바꾸고,
2. **`oci_compartment_id`** 로 그 tenancy 의 Gen AI 컴파트먼트를 지정합니다.

**1) (상대 tenancy 관리자) 사용자·정책·API 키 준비**
- Gen AI 사용 권한 정책: `Allow group <genai-users> to use generative-ai-family in compartment <genai-compartment>`
- 그 사용자의 **API 서명 키** 발급 → **fingerprint** 와 **개인키(PEM)** 확보.

**2) 내 ADB 에 그 사용자 credential 생성**
```sql
BEGIN
  DBMS_CLOUD.CREATE_CREDENTIAL(
    credential_name => 'GENAI_OTHER_TNCY',
    user_ocid       => 'ocid1.user.oc1..aaaa...(상대 tenancy 사용자)',
    tenancy_ocid    => 'ocid1.tenancy.oc1..aaaa...(상대 tenancy)',
    private_key     => 'MIIEvQIBADAN...(PEM 본문, -----BEGIN/END----- 줄 제외)',
    fingerprint     => 'aa:bb:cc:...:zz');
END;
/
```

**3) 프로필 — credential 교체 + `oci_compartment_id` + `region`**
```sql
BEGIN
    dbms_cloud_ai.drop_profile(profile_name => 'AIF_NL2SQL', force => true);

    dbms_cloud_ai.create_profile(
        profile_name => 'AIF_NL2SQL',
        attributes => '{
            "provider": "oci",
            "credential_name": "GENAI_OTHER_TNCY",              -- ← OCI$RESOURCE_PRINCIPAL 대신
            "oci_compartment_id": "ocid1.compartment.oc1..aaaa...(상대 tenancy 의 GenAI 컴파트먼트)",
            "region": "us-chicago-1",                            -- 상대 tenancy 에서 그 모델이 제공되는 리전
            "model": "openai.gpt-5.4",
            "embedding_model": "cohere.embed-v4.0",
            "annotations": "true", "comments": "true", "constraints": "true",
            "enforce_object_list": "true", "object_list_mode": "all",
            "max_tokens": 1500, "temperature": 0,
            "object_list": [
                {"owner": "DESCENTE1", "name": "DIMCOUPON"},
                {"owner": "DESCENTE1", "name": "DIMMEMBERINFO"},
                {"owner": "DESCENTE1", "name": "FACTMEMBERCOUPON"},
                {"owner": "DESCENTE1", "name": "FACTMEMBERSHIPLEVELHISTORY"},
                {"owner": "DESCENTE1", "name": "V_FACTSALESORDERFORCRM3YVR"}
            ]
        }');
END;
/
```

> 기본(자기 tenancy) 프로필과 **다른 점은 `credential_name`(리소스주체→상대 사용자 API키) + `oci_compartment_id`(상대 tenancy 컴파트먼트) 두 가지**뿐입니다. 나머지 속성은 동일합니다.

**주의**
- **리전**: 상대 tenancy 에서 그 `model`·`embedding_model` 이 실제 제공되는 리전이어야 합니다.
- **컴파트먼트**: `oci_compartment_id` 는 상대 tenancy 안에서 그 사용자가 `generative-ai-family` 를 쓸 수 있는 컴파트먼트여야 합니다.
- **전용 클러스터(dedicated) 모델**이면 `oci_endpoint_id`(엔드포인트 OCID)도 추가 지정합니다.
- **네트워크**: 사설 서브넷 ADB 라면 아웃바운드(서비스 게이트웨이/NAT) 조건이 동일하게 적용됩니다.
- 키를 DB 에 저장하기 싫으면, 리소스 주체 유지 + **크로스-테넌시 IAM(소스 `Endorse` / 타깃 `Admit`)** 정책으로도 가능하지만 양쪽 tenancy 관리자 권한이 필요합니다(위 API 키 방식이 더 간단).

---

## 2. 외부 LLM(OpenRouter 등 OpenAI 호환 엔드포인트) 활용 — AI Profile 생성

OpenAI 호환 REST 엔드포인트(예: **OpenRouter**)를 `provider_endpoint` 로 지정해 사용하는 프로필입니다. OCI 내부 호출(1번)과 달리 **공용 인터넷으로 나가므로** 두 가지가 추가로 필요합니다:
- **네트워크 ACL** — DB 가 외부 호스트로 나갈 수 있도록 허용
- **API 키 자격증명** — `DBMS_CLOUD.CREATE_CREDENTIAL` 에 키 저장

### 사전 준비
- **네트워크 ACL**: DB → `openrouter.ai` (443) 허용 (아래 ①)
- **API 키**: OpenRouter API Key(`sk-or-v1-...`)
- **DB 권한**: `DBMS_CLOUD_AI`·`DBMS_CLOUD`·`DBMS_NETWORK_ACL_ADMIN` EXECUTE
- **대상 테이블**: `object_list` 의 객체 존재 + 조회 권한

### 생성 스크립트 (3단계 — 순서대로 실행)

**① 네트워크 ACL — 외부 호스트 허용**
```sql
BEGIN
  DBMS_NETWORK_ACL_ADMIN.APPEND_HOST_ACE(
    host => 'openrouter.ai',
    ace  => xs$ace_type(
              privilege_list => xs$name_list('http'),
              principal_name => 'HR', -- 실제 Select AI를 사용할 DB 유저명으로 변경
              principal_type => xs_acl.ptype_db)
  );
END;
/
```

**② 자격증명 — OpenRouter API 키 저장**
```sql
BEGIN
  DBMS_CLOUD.CREATE_CREDENTIAL(
    credential_name => 'OPENROUTER_CRED',
    username        => 'OPENROUTER',
    password        => '<sk-or-v1-... 등 OpenRouter API Key>'
  );
END;
/
```

**③ 프로필 생성**
```sql
BEGIN
    dbms_cloud_ai.drop_profile(
        profile_name => 'AI_PRF_OSS',
        force => true
    );

    dbms_cloud_ai.create_profile(
        profile_name => 'AI_PRF_OSS',
        attributes =>
            '{"provider_endpoint": "https://openrouter.ai/api",
            "model": "google/gemma-4-26b-a4b-it",
            "embedding_model": "google/gemini-embedding-001",
            "credential_name": "OPENROUTER_CRED",
            "comments":"true",
            "annotations": "true",
            "constraints": "false",
            "enforce_object_list": "true",
            "temperature": 0,
            "max_tokens": 2000,
            "object_list_mode": "all",
            "object_list": [
                {"owner": "HR", "name": "EMPLOYEES"},
                {"owner": "HR", "name": "DEPARTMENTS"},
                {"owner": "HR", "name": "JOBS"},
                {"owner": "HR", "name": "LOCATIONS"}
            ]
            }'
        );
END;
/
```

### 1번(OCI)과 다른 점

| 구분 | 1) OCI GenAI | 2) 외부 LLM(OpenRouter) |
|---|---|---|
| 인증 | 리소스 주체 `OCI$RESOURCE_PRINCIPAL`(키 불필요) | **API 키** 자격증명(`CREATE_CREDENTIAL`) |
| 네트워크 ACL | 불필요(OCI 내부) | **필요**(외부 호스트 `openrouter.ai`) |
| 엔드포인트 지정 | `provider`=`oci` + `region` | **`provider_endpoint`**(OpenAI 호환 base URL) |
| IAM 정책 | `generative-ai-family` 동적그룹 필요 | 불필요(대신 API 키·ACL) |

### 속성 설명(추가분)

| 속성 | 값(예시) | 의미 |
|---|---|---|
| `provider_endpoint` | `https://openrouter.ai/api` | OpenAI 호환 REST 엔드포인트 base URL |
| `model` | `google/gemma-4-26b-a4b-it` | 엔드포인트가 제공하는 모델 ID(OpenRouter 표기법) |
| `credential_name` | `OPENROUTER_CRED` | ②에서 만든 API 키 자격증명 |
| `constraints` | `false` | 제약조건 메타데이터 미포함(여기선 끔) |

> `comments`·`annotations`·`enforce_object_list`·`temperature`·`max_tokens`·`object_list(_mode)` 는 1번과 같은 개념입니다.

### 주의
- **ACL 의 `principal_name` 은 실제 접속 DB 유저명과 일치**해야 합니다(예시는 `HR`). 불일치 시 호출에서 `ORA-24247`(network access denied) 발생.
- **API 키는 비밀**입니다 — `password` 에만 넣고 문서·리포지토리에 커밋 금지. 유출 시 OpenRouter 에서 키 회전(재발급) 후 `CREATE_CREDENTIAL` 재실행.
- 외부 LLM 경로는 **스키마 메타데이터·프롬프트가 외부(OpenRouter)로 전송**됩니다 — 데이터 거버넌스/보안 정책을 먼저 확인하세요. (실제 행 데이터는 `narrate`/RAG action 에서만 전송)
- ACL 은 `host => 'openrouter.ai'` 로 그 호스트만 허용합니다. 다른 도메인/서브도메인으로 바꾸면 해당 호스트로 ACE 를 다시 추가해야 합니다.

### 생성 확인
```sql
SELECT profile_name, status FROM user_cloud_ai_profiles WHERE profile_name = 'AI_PRF_OSS';

SELECT DBMS_CLOUD_AI.GENERATE(
         prompt       => '직무별 평균 급여를 알려줘',
         profile_name => 'AI_PRF_OSS',
         action       => 'showsql') AS sql_text
FROM dual;
```

## 3. Feedback 과 `v$mapped_sql` / `v$sql`

SELECT AI 의 **Feedback**(사용자가 "이 질문엔 이 SQL이 맞다/틀리다"를 학습시키는 기능)은 두 동적성능뷰와 함께 이해하면 쉽습니다.

### 두 뷰 개요

| 뷰 | 무엇인가 | 주요 컬럼 |
|---|---|---|
| **`v$mapped_sql`** | **SQL Translation Framework** 의 변환 내역. SELECT AI 가 자연어(`select ai …` / `DBMS_CLOUD_AI.GENERATE`)를 실제 SQL 로 **번역한 기록**이 남는다. | `SQL_ID`(원본), `MAPPED_SQL_ID`(변환된 SQL의 ID), `SQL_TEXT`/`SQL_FULLTEXT`(원본), `MAPPED_SQL_TEXT`(변환문), `USE_COUNT`(사용횟수), `TRANSLATION_TIMESTAMP` |
| **`v$sql`** | **공유 SQL 영역(커서 캐시)**. 실제로 **파싱·실행된 SQL** 이 SQL_ID 단위로 올라온다. | `SQL_ID`, `SQL_FULLTEXT`(전체문, CLOB), `SQL_TEXT`(앞 1000자), `EXECUTIONS`, `ELAPSED_TIME` 등 통계 |

- `v$mapped_sql` = "무엇을 무엇으로 **번역**했나"(NL→SQL 매핑 이력)
- `v$sql` = "그 SQL 이 실제로 **실행**된 흔적과 통계"

### 두 뷰의 관계

`v$mapped_sql.MAPPED_SQL_ID` 는 **변환되어 실제 실행된 SQL 의 `SQL_ID`** 이고, 이 값은 `v$sql.SQL_ID` 로 조회할 수 있습니다. 즉 두 뷰는 `MAPPED_SQL_ID = SQL_ID` 로 연결됩니다.

```sql
SELECT m.sql_id            AS original_sql_id,   -- 원본(select ai …) SQL_ID
       m.mapped_sql_id,                          -- 변환·실행된 SQL 의 SQL_ID
       s.sql_fulltext      AS mapped_full_sql,   -- v$sql 에서 가져온 실제 실행문 전체
       s.executions, s.elapsed_time
FROM   v$mapped_sql m
LEFT JOIN v$sql s ON s.sql_id = m.mapped_sql_id
WHERE  m.mapped_sql_id IS NOT NULL;
```

> `MAPPED_SQL_ID` 가 `NULL` 이거나 커서가 캐시에서 aging-out 되면 `v$sql` 에 없을 수 있습니다. 이때는 AWR(`DBA_HIST_SQLTEXT`, 캡처되어 있어야 함)에서 조회합니다.

### Feedback 추가 시 어떻게 쓰이나

이 도구의 **AI Profile Test → 4.Feedback 관리** 에서 두 경로로 피드백을 등록합니다:

1. **실행된 내역에서(Positive)** — `v$mapped_sql` 을 조회해 **최근 NL2SQL 실행 목록(sql_id)** 을 보여주고, 특정 행의 `sql_id` 로 아래를 실행합니다.
   ```sql
   BEGIN
     DBMS_CLOUD_AI.FEEDBACK(
       profile_name  => 'AIF_NL2SQL',
       sql_id        => '<v$mapped_sql 의 SQL_ID>',
       feedback_type => 'positive',
       operation     => 'add');
   END;
   /
   ```
   → SELECT AI 는 그 `sql_id` 로 **원본 질문 + 생성된 SQL** 을 식별해, 프로파일의 **피드백 벡터 테이블(`<PROFILE>_FEEDBACK_VECINDEX$VECTAB`)** 에 저장합니다. 이후 유사 질문에서 **few-shot 예시**로 재사용되어 정확도가 올라갑니다.

2. **실행내역 없이 직접(Negative)** — 실행 이력(`v$mapped_sql`)이 없어도 `sql_text`(질문) + `response`(정답/오답 SQL) + `feedback_content` 를 직접 넣어 등록합니다.

> 정리: **`v$mapped_sql` 은 "어떤 질문이 어떤 SQL 로 실행됐는지"의 출처**로서 Positive 피드백의 `sql_id` 를 제공하고, **`v$sql` 은 그 `MAPPED_SQL_ID` 로 실제 실행문·통계를 확인**하는 용도입니다. 같은 `sql_id` 에 대한 피드백은 1건만 유지됩니다(`operation => 'add'` 가 곧 update).

> 권한: `v$mapped_sql`·`v$sql` 조회에는 각각 `GRANT READ ON SYS.V_$MAPPED_SQL`, `GRANT SELECT ON V_$SQL`(또는 ADMIN 권한)이 필요할 수 있습니다.

## 4. VPD(행 수준 보안) × 3-tier 커넥션 풀 — Application Context 주의

SELECT AI 결과에 **행 수준 보안(VPD, `DBMS_RLS`)** 을 걸 때, 정책 함수는 보통 **Application Context**(`DBMS_SESSION.SET_CONTEXT` 로 세팅하고 `SYS_CONTEXT` 로 읽는 값)를 기준으로 WHERE 술어를 만듭니다. 그런데 **3-tier 앱이 커넥션 풀로 하나의 DB 계정을 여러 최종사용자가 공유**하면, 로컬(세션) 컨텍스트가 **다음 사용자에게 새어나가** VPD 가 오작동/정보누수할 수 있습니다.

### 4.1 왜 위험한가 — 세션 스코프 × 풀 재사용

- `SET_CONTEXT` 로 만든 **로컬(세션) 컨텍스트는 "그 DB 세션이 살아있는 동안"만 유효**하고, `SYS_CONTEXT` 는 그 세션에 세팅된 값을 봅니다.
- 3-tier 는 보통 **하나의 DB 계정(APP_USER 등)으로 만든 커넥션 풀**을 여러 최종사용자가 **물리 세션을 돌려쓰기** 때문에 아래 누수가 생깁니다.

```text
[요청1] 사용자 A → 풀에서 세션 #7 대여 → SET_CONTEXT(EMPLID='2') → 조회 → 반납(컨텍스트 안 지움)
[요청2] 사용자 B → 하필 세션 #7 대여 → (컨텍스트 세팅 안 함) → 조회
        → SYS_CONTEXT 는 여전히 '2'(A의 값) → B가 A의 데이터를 봄  ❌
```

> **로그온 트리거로 컨텍스트를 세팅하는 방식은 풀에서 깨집니다** — 트리거는 물리 세션이 "생성"될 때만 돌지, 최종사용자 "요청"마다 돌지 않습니다.

### 4.2 해결책 (권장순)

> **먼저: 해결책이 막아야 하는 건 "동시 공유"가 아니라 "순차 재사용 누수"다.**
>
> 로컬 Application Context 는 **세션 사설(private) 메모리**에 저장되고, 커넥션 풀은 한 세션을 **한 순간에 한 요청에만** 빌려준다(직렬 점유). 그래서 두 종류를 구분해야 한다.
>
> | 구분 | 일반 3-tier 풀에서 | 이유 |
> |---|---|---|
> | **동시 공유** (두 사용자가 같은 순간 같은 세션에 set) | **발생 안 함** | 풀이 커넥션을 직렬 점유시킴 — 한 커넥션=한 요청. `SET_CONTEXT(A)` 도중 다른 요청이 그 세션에 끼어들 수 없다. |
> | **순차 재사용 누수** (앞 사용자 값이 남아 다음 사용자가 봄) | **발생할 수 있음** | 컨텍스트는 물리 세션이 살아있는 동안 유지되고, 논리 커넥션을 반납해도 물리 세션·컨텍스트는 안 지워진다. 풀이 자동으로 청소하지 않는다. |
>
> ```text
> [동시 공유는 안 남] A가 세션#7 독점 중이면 B는 #7을 못 받음 → B는 세션#9 → 서로 격리
> [순차 누수는 남]    A: #7 SET_CONTEXT(A) → 조회 → 반납(‼️ #7에 A값 잔존)
>                    B: #7 대여 → (set 생략 시) 조회 → SYS_CONTEXT 가 여전히 A값 → B가 A 데이터 열람 ❌
> ```
>
> 즉 **"풀만 쓰면 자동으로 안전"은 아니다.** 동시 충돌은 풀이 막아주지만, 사용자 간 잔존값 누수는 **앱이 (A) 요청마다 재설정 / 반납 시 클리어로 직접 막아야** 한다. 아래 해결책은 바로 이 순차 누수를 막기 위한 것이다.
>
> (레이스가 실제로 나려면 **한 세션을 여러 동시 요청이 공유**하거나 **set 한 커넥션과 조회 한 커넥션이 다른** 경우인데, 둘 다 풀 사용 규칙 위반이다.)

#### (A) 최소 — "요청마다 세팅 + 반납 시 클리어" (현재 PoC 구조 유지)
로컬 컨텍스트를 계속 쓰되:
1. **모든 요청 시작 시** 인증된 최종사용자 기준으로 세터 프로시저(예: `PRC_OAC_SETINFO_*`) 호출.
2. **커넥션 반납 직전 반드시 클리어**:
   ```sql
   DBMS_SESSION.CLEAR_CONTEXT('OAC_MANAGER');       -- 특정 네임스페이스
   -- 또는 DBMS_SESSION.CLEAR_ALL_CONTEXT('OAC_MANAGER');
   ```
   - 드라이버 세션 풀의 **반납/획득 콜백**(python-oracledb `sessionCallback`, UCP connection labeling 등)에서 자동 정리하도록 걸어두면 사람 실수를 막을 수 있습니다.
- 장점: 함수/구조 그대로. 단점: **규율 의존** — 한 경로라도 세팅/정리를 빠뜨리면 누수.

#### (B) 권장 — CLIENT_IDENTIFIER + **Global Application Context**
풀에 훨씬 안전한 Oracle 표준 패턴입니다.
```sql
-- 미들티어가 요청마다 최종사용자 식별자를 세션에 심음
BEGIN DBMS_SESSION.SET_IDENTIFIER('empid:2'); END;   -- SYS_CONTEXT('USERENV','CLIENT_IDENTIFIER')

-- 컨텍스트를 전역(SGA)으로 선언하고 client_id 로 키잉
CREATE OR REPLACE CONTEXT OAC_MANAGER USING PKG_OAC_MANAGER ACCESSED GLOBALLY;
-- 세팅 시 client_id 로 귀속 (SET_CONTEXT 의 username/client_id 인자)
-- DBMS_SESSION.SET_CONTEXT('OAC_MANAGER','EMPLID','2', username=>..., client_id=>'empid:2');
```
- 이후 **어떤 풀 세션이든 자기 `CLIENT_IDENTIFIER` 에 맞는 값**을 SGA 에서 자동으로 봄 → 세션이 바뀌어도 값이 사용자와 함께 따라다님. 반납 시 `DBMS_SESSION.CLEAR_IDENTIFIER` 만 하면 됨.
- 정책 함수는 그대로 `SYS_CONTEXT` 를 읽으면 됩니다.

#### (C) 정석(12c+) — **Real Application Security(RAS)**
"여러 앱 사용자 + 공유 풀 + 행/열 보안"을 위해 Oracle 이 만든 기능. **애플리케이션 세션**(app user·role·namespace)을 물리 DB 세션에 **attach/detach** 하며 ACL 기반 데이터 보안을 커넥션 풀과 네이티브로 연동합니다. 설계 변경 비용은 크지만 3-tier 다중 사용자에 근본적으로 적합.

#### (D) 가능하면 — **`USERENV` 내장 컨텍스트**를 기준값으로
사용자 정체성을 커스텀 `SET_CONTEXT` 없이 얻을 수 있으면 누수 위험이 원천적으로 낮습니다.
```sql
SYS_CONTEXT('USERENV','SESSION_USER')          -- 접속 계정
SYS_CONTEXT('USERENV','CLIENT_IDENTIFIER')     -- 미들티어가 심은 최종사용자
```
정책 함수가 이 값만 기준으로 술어를 만들면, "요청마다 세팅"이 세터 프로시저 대신 **`SET_IDENTIFIER` 한 줄**로 줄어 실수 여지가 작아집니다.

### 4.3 SELECT AI 특유의 주의점
SELECT AI(`DBMS_CLOUD_AI.GENERATE … runsql`)는 **생성된 SQL 을 그 DB 세션에서 실행**합니다. 그 실행 세션에 최종사용자 컨텍스트가 심겨 있어야 VPD 가 맞게 필터합니다.
- `showsql` 은 SQL **텍스트만** 만들므로 컨텍스트와 무관하지만, **실제 행 필터는 "실행 세션의 컨텍스트"** 에서 결정됩니다.
- SELECT AI 실행 경로가 별도 워커/공유 프로파일로 돈다면, **그 실행 세션에도 동일하게 컨텍스트(또는 CLIENT_IDENTIFIER)를 전파**해야 합니다.

### 4.4 정리

| 상황 | 권장 |
|---|---|
| 지금 PoC 구조 유지 | **(A)** 요청마다 세팅 + **반납 콜백에서 `CLEAR_CONTEXT`** (필수) |
| 실서비스로 승격 | **(B)** `CLIENT_IDENTIFIER` + **Global Application Context** |
| 사용자·역할·행/열 보안을 제대로 | **(C)** Real Application Security |
| 정체성이 `CLIENT_IDENTIFIER` 로 충분 | **(D)** `USERENV` 기준 정책 함수 |

> **한 줄 요약:** VPD 자체는 3-tier 에서도 잘 동작하지만, **"컨텍스트를 요청마다 세팅하고 커넥션 반납 시 반드시 정리"** 하지 않으면 풀 재사용으로 **다른 사용자 데이터가 새어나갑니다.** 로컬 컨텍스트를 유지하려면 (A)의 정리 콜백을 필수로 넣고, 안전하게 가려면 **(B) `CLIENT_IDENTIFIER` + Global Application Context** 로 전환하세요.
