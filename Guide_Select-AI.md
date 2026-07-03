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
