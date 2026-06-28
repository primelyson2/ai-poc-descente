# AI SQL Tuning Assistant(ASTA) 프로그램 명세서

최종 업데이트: 2026-06-27  
대상 시스템: OADT2 / AI SQL Tuning Assistant(ASTA)

---

## 1. 이 문서의 목적

이 문서는 OADT2에 포함된 **AI SQL Tuning Assistant(ASTA)** 프로그램이 무엇을 하는지, 내부적으로 어떤 순서로 동작하는지, 어떤 DB/패키지/API를 호출하는지, 결과 보고서가 어떤 의미인지 쉽게 이해할 수 있도록 정리한 프로그램 명세서입니다.

한 줄로 요약하면:

> 사용자가 SQL을 입력하면, ASTA가 Source DB에서 실제 실행 증거를 수집하고, Oracle SQL Tuning Advisor, Vector 유사 사례, AI 튜닝을 조합해 SQL 튜닝 결과 보고서를 생성하는 프로그램입니다.

---

## 2. 프로그램 목적

### 2.1 ASTA가 하는 일

ASTA는 사용자가 입력한 SQL에 대해 아래 작업을 수행합니다.

1. SQL이 안전한 조회문인지 검사
2. Source DB에서 원본 SQL을 실제 실행
3. 실행 계획, 실행 통계, XPLAN 수집
4. 필요 시 Oracle SQL Tuning Advisor 수행
5. 과거 유사 튜닝 사례 검색
6. AI가 튜닝 후보 SQL 생성
7. 후보 SQL이 있으면 다시 Source DB에서 실행 검증
8. Before/After 비교
9. 최종 Markdown 튜닝 보고서 생성
10. 결과를 Vector KB에 저장

### 2.2 ASTA가 하지 않는 일

ASTA는 자동으로 운영 DB를 변경하지 않습니다.

자동으로 하지 않는 것:

```text
- 인덱스 자동 생성
- SQL Profile 자동 적용
- 통계 자동 수집
- Plan Baseline 자동 적용
- 운영 SQL 자동 교체
- DML/DDL 실행
```

즉 ASTA는 **튜닝 조언, 실행 검증, 보고서 생성 도구**입니다. 운영 변경은 DBA 또는 담당자가 별도로 승인해야 합니다.

---

## 3. 전체 구조

### 3.1 큰 그림

```text
사용자 브라우저
  ↓
OADT2 화면의 AI SQL Tuning Assistant UI
  ↓
FastAPI /api/asta/*
  ↓
ADB ORDS /ords/asta/*
  ↓
ADB PL/SQL ASTA_PKG
  ↓
ADB DB Link
  ↓
Source BaseDB ASTA_SOURCE_PKG
```

### 3.2 구조 원칙

현재 ASTA의 핵심 원칙은 다음과 같습니다.

```text
FastAPI/Python은 중계만 한다.
실제 분석은 ADB ORDS + PL/SQL에서 한다.
Source DB 실행 증거는 DB Link를 통해 Source helper package가 수집한다.
```

Python이 직접 Source DB에 접속해서 SQL을 실행하거나 XPLAN을 가져오지 않습니다.

---

## 4. 구성 요소

### 4.1 Browser UI

파일:

```text
static/js/extensions/tuning_assistant.js
```

역할:

| 역할 | 설명 |
|---|---|
| SQL 입력 | 사용자가 튜닝할 SQL 입력 |
| 옵션 선택 | LLM profile, SQL Tuning Advisor 사용 여부 등 |
| 분석 실행 | `/api/asta/analyze` 호출 |
| 진행 상태 표시 | 11단계 수행 이력 표시 |
| 결과 보고서 표시 | Markdown 결과서를 화면에 렌더링 |

---

### 4.2 FastAPI Proxy

파일:

```text
app/routers/asta_proxy.py
```

FastAPI는 ASTA의 실제 엔진이 아닙니다. 역할은 **same-origin thin proxy** 입니다.

브라우저가 직접 ADB ORDS를 호출하지 않고, OADT2 서버의 `/api/asta/*`를 호출합니다.

#### FastAPI endpoint

| Method | Path | 역할 |
|---|---|---|
| `GET` | `/api/asta/profiles` | 사용 가능한 ASTA AI profile 목록 |
| `POST` | `/api/asta/analyze` | SQL 튜닝 분석 실행 |
| `GET` | `/api/asta/runs/{run_id}` | 저장된 run 전체 JSON 조회 |
| `GET` | `/api/asta/runs/{run_id}/progress` | 단계별 진행 상태 조회 |
| `GET` | `/api/asta/runs/{run_id}/report` | Markdown 보고서 조회 |

#### FastAPI가 하는 일

```text
- UI payload를 ORDS용 payload로 정리
- source_db_id 기본값 설정
- fetch_rows 기본값 설정
- sqltune timeout 제한
- llm_profile 기본값 설정
- ORDS로 전달
- ORDS 응답을 거의 그대로 UI에 반환
```

#### FastAPI가 하지 않는 일

```text
- SQL 실행 안 함
- Source DB 직접 접속 안 함
- XPLAN 수집 안 함
- SQLTUNE 실행 안 함
- LLM 호출 안 함
- Vector 검색/저장 안 함
- 최종 보고서 직접 생성 안 함
```

---

## 5. ADB ORDS 계층

파일:

```text
db/ords/asta_ords_module.sql
```

ORDS module:

```text
module_name = asta.v1
base_path   = asta/
```

### ORDS endpoint

| Method | ORDS path | 내부 PL/SQL |
|---|---|---|
| `POST` | `/analyze` | `ASTA_PKG.ANALYZE_SQL(:body_text)` |
| `GET` | `/profiles` | `ASTA_PKG.LIST_PROFILES` |
| `GET` | `/runs/:run_id` | `ASTA_PKG.GET_RUN(:run_id)` |
| `GET` | `/runs/:run_id/progress` | `ASTA_PKG.GET_PROGRESS(:run_id)` |
| `GET` | `/runs/:run_id/report` | `ASTA_PKG.GET_REPORT(:run_id)` |

ORDS는 긴 JSON/Markdown/CLOB를 chunk로 내려줍니다.

```text
response_contract = CLOB_CHUNKED_JSON
```

---

## 6. ADB PL/SQL 패키지

ADB 안에 ASTA의 핵심 엔진이 있습니다.

경로:

```text
db/adb/
```

| Package | 파일 | 역할 |
|---|---|---|
| `ASTA_PKG` | `asta_pkg.sql` | 전체 orchestration, 공개 API |
| `ASTA_SQL_GUARD_PKG` | `asta_sql_guard_pkg.sql` | SQL 안전성 검사 |
| `ASTA_SOURCE_BRIDGE_PKG` | `asta_source_bridge_pkg.sql` | DB Link로 Source helper 호출 |
| `ASTA_VECTOR_PKG` | `asta_vector_pkg.sql` | 유사 사례 검색/저장 |
| `ASTA_LLM_PKG` | `asta_llm_pkg.sql` | DBMS_CLOUD_AI 호출 |
| `ASTA_REPORT_PKG` | `asta_report_pkg.sql` | 결과 보고서/응답 JSON 생성 |

---

## 7. Source BaseDB Helper

파일:

```text
db/source/asta_source_pkg.sql
```

설치 위치:

```text
Source BaseDB
```

이 패키지는 Source DB에서 실제 SQL을 실행하고 evidence를 만듭니다.

### 주요 역할

```text
- 원본 SQL 실행
- 후보 SQL 실행
- row count 수집
- elapsed time 수집
- buffer gets 수집
- disk reads 수집
- SQL_ID / child number / plan hash 수집
- DBMS_XPLAN.DISPLAY_CURSOR 수집
- 필요 시 DBMS_SQLTUNE 실행
- 결과 JSON을 CLOB로 저장
- ADB가 DB Link로 chunk 단위 조회
```

### 수집하는 주요 evidence

| 항목 | 의미 |
|---|---|
| `sql_id` | Oracle SQL 식별자 |
| `child_number` | cursor child number |
| `plan_hash_value` | 실행계획 hash |
| `row_count` | fetch된 row 수 |
| `elapsed_wall_ms` | 실제 실행 wall-clock 시간 |
| `last_output_rows` | 실행 계획 기준 출력 row |
| `last_cr_buffer_gets` | consistent read buffer gets |
| `last_disk_reads` | physical read |
| `last_elapsed_time_us` | plan stats elapsed |
| `xplan` | 실제 실행계획 |
| `advisor.report` | SQL Tuning Advisor 결과 |

---

## 8. Repository Table

경로:

```text
db/asta/
```

| 파일 | 내용 |
|---|---|
| `001_asta_repository.sql` | `asta_runs`, `asta_run_progress` |
| `002_asta_source_connections.sql` | Source DB allowlist |
| `003_asta_runs_source_db_id.sql` | migration |
| `004_asta_vector_tables.sql` | Vector KB tables |

### 8.1 `ASTA_RUNS`

ASTA 실행 1건의 최종 결과 저장.

주요 컬럼:

```text
run_id
status
input_sql
tuned_sql
llm_profile
source_db_id
source_schema
source_db_link
detailed_report_md
response_json
error_code
error_message
```

### 8.2 `ASTA_RUN_PROGRESS`

단계별 진행 상태 저장.

```text
run_id
seq
code
label
status
detail
started_at
completed_at
elapsed_ms
```

### 8.3 `ASTA_SOURCE_CONNECTIONS`

Source DB 연결 allowlist.

```text
source_db_id
db_link_name
source_schema
enabled
```

중요한 이유:

> 사용자가 임의로 DB Link나 schema를 넣어 실행하지 못하게 막기 위해 source는 allowlist에서만 고릅니다.

### 8.4 `ASTA_TUNING_CASES`, `ASTA_TUNING_CASE_CHUNKS`

Vector KB용 저장소.

```text
과거 SQL
튜닝 SQL
보고서
유사 사례 chunk
fingerprint
```

---

## 9. ASTA 11단계 수행 흐름

ASTA 화면에서 보는 핵심 실행 단계입니다.

| 순서 | 코드 | 이름 | 설명 |
|---:|---|---|---|
| 1 | `REQUEST_RECEIVED` | 요청 수신 | 사용자가 분석 요청 |
| 2 | `ORDS_DISPATCH` | ADB ORDS 분석 호출 | FastAPI가 ORDS로 전달 |
| 3 | `SQL_GUARD` | SQL 안전성 검사 | SELECT/WITH 단일문인지 확인 |
| 4 | `BEFORE_EVIDENCE` | 원본 SQL 분석 | Source DB에서 원본 SQL 실행/XPLAN 수집 |
| 5 | `SQL_TUNING_ADVISOR` | Oracle SQL Tuning Advisor | 요청 시 Oracle Advisor 수행 |
| 6 | `VECTOR_KB` | Vector KB 유사 사례 조회 | 과거 유사 튜닝 사례 검색 |
| 7 | `LLM_REWRITE` | AI 1차 튜닝 | AI가 후보 SQL 생성 |
| 8 | `AFTER_EVIDENCE` | 튜닝 SQL 분석 | 후보 SQL을 다시 Source DB에서 검증 |
| 9 | `LLM_FINAL_REVIEW` | AI Before/After 정리 | 전후 비교를 AI가 정리 |
| 10 | `FINAL_REPORT` | 최종 보고서 생성 | Markdown 결과서 생성 |
| 11 | `VECTOR_SAVE` | Vector KB 저장 | 성공/실패 사례 저장 |

---

## 10. 실제 실행 흐름

### 10.1 사용자가 SQL 입력

예:

```sql
SELECT ...
FROM ...
WHERE ...
```

UI가 이 SQL과 옵션을 FastAPI로 보냅니다.

---

### 10.2 FastAPI가 요청 정리

FastAPI는 다음 기본값을 붙입니다.

```json
{
  "source_db_id": "DB0903_TESTDB",
  "fetch_rows": 100,
  "benchmark_repeat": 1,
  "sqltune_time_limit": 1800,
  "vector_top_k": 3,
  "use_llm": true,
  "run_advisor": false,
  "llm_profile": "ASTA_GROK_REASONING_PROFILE"
}
```

그리고 ORDS로 넘깁니다.

---

### 10.3 ADB `ASTA_PKG.ANALYZE_SQL` 시작

ADB에서 run_id를 만들고 진행 상태를 기록합니다.

예:

```text
OADT2-ASTA-5530d2fa8f8d8436e063911a000a722e
```

---

### 10.4 SQL Guard

`ASTA_SQL_GUARD_PKG`가 SQL을 검사합니다.

허용:

```sql
SELECT ...
WITH ...
```

차단:

```sql
INSERT
UPDATE
DELETE
MERGE
CREATE
ALTER
DROP
TRUNCATE
BEGIN
CALL
EXEC
```

목적:

> ASTA가 분석 도구로만 동작하고 DB를 변경하지 못하게 하기 위함입니다.

---

### 10.5 Source DB 원본 SQL 실행

ADB가 직접 Source DB에 접속하는 게 아니라 아래 경로로 호출합니다.

```text
ADB ASTA_SOURCE_BRIDGE_PKG
  → DB Link
  → Source ASTA_SOURCE_PKG
```

Source helper가 원본 SQL을 실행하고 실행 증거를 모읍니다.

수집 예:

```text
SQL_ID
실행 시간
buffer gets
disk reads
row count
실제 XPLAN
Oracle Advisor report
```

---

### 10.6 SQL Tuning Advisor

옵션이 켜져 있으면 Source DB에서 아래 Oracle package를 수행합니다.

```sql
DBMS_SQLTUNE.CREATE_TUNING_TASK
DBMS_SQLTUNE.EXECUTE_TUNING_TASK
DBMS_SQLTUNE.REPORT_TUNING_TASK
```

Advisor 결과는 이런 식으로 해석됩니다.

| 유형 | 의미 |
|---|---|
| SQL Profile | Optimizer 보정 권고 |
| Index Finding | 인덱스 생성 권고 |
| Statistics | 통계/히스토그램 권고 |
| SQL Rewrite | SQL 재작성 권고 |
| No finding | Oracle Advisor 권고 없음 |

주의:

> Advisor 결과도 자동 적용하지 않습니다. 보고서에 DBA 검토 대상으로 표시합니다.

---

### 10.7 Vector KB 검색

`ASTA_VECTOR_PKG`가 과거 사례를 찾습니다.

찾는 내용:

```text
이 SQL과 비슷한 과거 튜닝 사례가 있는가?
비슷한 실행계획/문제 패턴이 있었는가?
과거에 어떤 rewrite가 효과 있었는가?
```

현재 전략:

```text
FINGERPRINT_FIRST_CHUNK_SCAN
```

Vector KB가 없어도 분석은 멈추지 않습니다.

```text
VECTOR_KB = SKIPPED 또는 NOT_CONFIGURED
```

---

### 10.8 AI 1차 튜닝

`ASTA_LLM_PKG`가 DBMS_CLOUD_AI를 호출합니다.

현재 기본 profile:

```text
ASTA_GROK_REASONING_PROFILE
```

기본 모델:

```text
xai.grok-4-fast-reasoning
```

AI에게 주는 정보:

```text
- 원본 SQL
- Source 실행 evidence compact JSON
- XPLAN 요약
- SQL Tuning Advisor 요약
- Vector 유사 사례 요약
- 사용자 메모/튜닝 context
```

중요한 점:

> raw evidence는 CLOB로 보존하고, LLM prompt에는 compact evidence만 넣습니다.

이유:

```text
긴 JSON/XPLAN을 무식하게 잘라 넣으면
중요 정보가 잘리거나 ORA-06502/CLOB 문제가 날 수 있음
```

---

### 10.9 AI 후보 SQL 검증

AI가 `candidate_sql`을 만들면 ASTA는 바로 믿지 않습니다.

검사 항목:

```text
- SELECT/WITH인지?
- 금지 키워드 없는지?
- 실제 Source DB에서 실행 가능한지?
- row count / 결과 비교 가능한지?
- before보다 after metric이 좋아졌는지?
```

후보 SQL이 실패하면:

```text
candidate_error 저장
원본 SQL 유지
보고서에는 개선 SQL 없음으로 표시
```

즉 아래 메시지는 전체 ASTA 실패가 아닙니다.

```text
LLM candidate failed executable validation
```

의미:

> AI가 만든 후보 SQL이 실행 검증에 실패해서 채택하지 않았다는 뜻입니다.

현재 보고서 정책:

```text
후보 SQL 실패 또는 원본 SQL 유지
→ 튜닝 SQL 코드블록 표시 안 함
→ 개선 SQL 없음 표시
```

---

### 10.10 Before/After 비교

후보 SQL이 성공하면 원본과 후보를 비교합니다.

| 항목 | 의미 |
|---|---|
| elapsed time | 실행 시간 |
| buffer gets | 논리 I/O |
| disk reads | 물리 I/O |
| row count | 결과 row 수 |
| plan hash | 실행계획 변화 |
| xplan | 접근 경로/조인 방식 |
| output match | 결과 동등성 신호 |

주의:

> OLTP/짧은 SQL은 elapsed time보다 buffer gets 감소를 더 중요하게 봅니다.

이유:

```text
짧은 SQL은 실행 시간이 캐시/순간 부하에 흔들릴 수 있음.
많이 반복되는 SQL은 buffer gets/CPU 감소가 더 중요함.
```

---

### 10.11 최종 보고서 생성

`ASTA_REPORT_PKG`가 Markdown 보고서를 만듭니다.

현재 보고서 구조:

```text
# AI SQL Tuning Assistant Report

## 튜닝 결과
### Before/After 핵심 비교

## 실행 메타데이터

## 단계별 수행 체크

## 원본 SQL

## Source 실행 Evidence 요약

## Oracle SQL Tuning Advisor 요약

## 튜닝 SQL

## 튜닝 후 Source 실행 Evidence 요약

## Vector 유사 사례 요약

## DBA 검토사항
```

후보 SQL이 없으면 `## 튜닝 SQL`에는 이렇게 표시됩니다.

```text
개선 SQL 없음 — AI 1차 튜닝에서 실행 가능한 변경 SQL이 없어 원본 SQL을 유지했습니다.
```

---

## 11. API 명세

### 11.1 `POST /api/asta/analyze`

SQL 분석 실행.

#### Request 예시

```json
{
  "sql": "select ... from ... where ...",
  "source_db_id": "DB0903_TESTDB",
  "llm_profile": "ASTA_GROK_REASONING_PROFILE",
  "use_llm": true,
  "run_advisor": true,
  "fetch_rows": 100,
  "benchmark_repeat": 1,
  "sqltune_time_limit": 1800,
  "vector_top_k": 3,
  "tuning_context": {
    "user_notes": "업무상 응답시간이 중요함"
  }
}
```

#### Response 주요 필드

```json
{
  "run_id": "...",
  "status": "COMPLETED",
  "progress": {
    "REQUEST_RECEIVED": "DONE",
    "ORDS_DISPATCH": "DONE",
    "SQL_GUARD": "DONE",
    "BEFORE_EVIDENCE": "DONE",
    "SQL_TUNING_ADVISOR": "FAILED",
    "VECTOR_KB": "DONE",
    "LLM_REWRITE": "DONE",
    "AFTER_EVIDENCE": "DONE",
    "LLM_FINAL_REVIEW": "DONE",
    "FINAL_REPORT": "DONE",
    "VECTOR_SAVE": "DONE"
  },
  "report_markdown": "...",
  "proxy": {
    "source": "ADB_ORDS",
    "external_call": false
  }
}
```

---

### 11.2 `GET /api/asta/profiles`

사용 가능한 ASTA AI profile 목록 조회.

현재 ADMIN 기준 profile:

| Profile | Provider | Model |
|---|---|---|
| `ASTA_DB_GENAI_TEST` | oci | `xai.grok-4-fast-reasoning` |
| `ASTA_GROK_GENAI_PROFILE` | oci | `xai.grok-4-fast-reasoning` |
| `ASTA_GROK_REASONING_PROFILE` | oci | `xai.grok-4-fast-reasoning` |

참고:

```text
ASKORACLE schema에는 GPT 5.4/5.5 profile이 있으나,
ADMIN runtime에서 바로 사용하려면 ADMIN.OPENAI_CRED가 필요합니다.
```

---

### 11.3 `GET /api/asta/runs/{run_id}/progress`

실행 진행 상태 조회.

반환 예:

```json
{
  "run_id": "...",
  "status": "RUNNING",
  "progress": [
    {
      "seq": 1,
      "code": "REQUEST_RECEIVED",
      "label": "OADT2 request received",
      "status": "DONE",
      "elapsed_ms": 0
    }
  ]
}
```

---

### 11.4 `GET /api/asta/runs/{run_id}/report`

저장된 Markdown 보고서 조회.

---

## 12. 주요 옵션 명세

| 옵션 | 기본값 | 설명 |
|---|---:|---|
| `source_db_id` | `DB0903_TESTDB` | Source DB allowlist key |
| `fetch_rows` | `100` | 실행 시 fetch row 제한 |
| `benchmark_repeat` | `1` | 반복 측정 횟수 |
| `sqltune_time_limit` | `1800` | SQLTUNE 최대 초 |
| `vector_top_k` | `3` | 유사 사례 조회 개수 |
| `use_llm` | `true` | AI 튜닝 수행 여부 |
| `run_advisor` | `false` | SQL Tuning Advisor 수행 여부 |
| `llm_profile` | `ASTA_GROK_REASONING_PROFILE` | DBMS_CLOUD_AI profile |

---

## 13. 보안/안전 정책

### 13.1 SQL Guard

허용:

```text
SELECT
WITH
```

차단:

```text
INSERT / UPDATE / DELETE / MERGE
CREATE / ALTER / DROP / TRUNCATE
BEGIN / DECLARE / CALL / EXEC
복수 statement
```

---

### 13.2 Source DB 접근 정책

현재 OADT2/ASTA runtime에서 금지:

```text
FastAPI/Python Source DB 직접 접속
SSH tunnel로 Source 직접 접근
Python subprocess로 XPLAN/SQLTUNE 수집
source direct fallback
```

허용:

```text
ADB ORDS
ADB PL/SQL
ADB DB Link
Source helper package
```

---

### 13.3 자동 적용 금지

보고서에 권고는 할 수 있지만 자동 적용은 하지 않습니다.

```text
인덱스 생성: DBA 검토 필요
SQL Profile: DBA 승인 필요
통계 수집: DBA 승인 필요
Plan Baseline: DBA 승인 필요
```

---

## 14. 결과 상태 의미

### 14.1 전체 status

| Status | 의미 |
|---|---|
| `COMPLETED` | 전체 분석 완료 |
| `COMPLETED_WITH_SKIPS` | 일부 단계 skip, 보고서는 생성 |
| `FAILED` | 분석 실패 |
| `RUNNING` | 실행 중 |

### 14.2 단계 status

| Status | 의미 |
|---|---|
| `DONE` | 정상 완료 |
| `SKIPPED` | 조건상 수행 안 함 |
| `FAILED` | 해당 단계 실패 |
| `WARN` | 경고 있으나 계속 진행 |
| `PENDING` | 아직 대기 |
| `RUNNING` | 수행 중 |

---

## 15. 자주 보는 케이스 해석

### 15.1 `SQL_TUNING_ADVISOR = FAILED`

전체 실패가 아닐 수 있습니다.

예:

```text
Source PDB가 RESTRICTED SESSION 상태
DBMS_SQLTUNE scheduler job 실패
권한 부족
```

이 경우:

```text
Advisor는 FAILED
나머지 Vector/LLM/보고서는 계속 진행 가능
```

---

### 15.2 `LLM candidate failed executable validation`

뜻:

```text
AI가 후보 SQL을 만들었지만 실제 DB 실행 검증에서 실패
```

보고서 처리:

```text
개선 SQL 없음
원본 SQL 유지
candidate_error는 raw artifact에 저장
```

---

### 15.3 `Vector KB NOT_CONFIGURED`

뜻:

```text
Vector table이 없거나 설정 안 됨
```

분석 자체는 계속 진행할 수 있습니다.

---

### 15.4 `개선 SQL 없음`

뜻:

```text
AI 1차 튜닝에서 실행 가능한 변경 SQL이 없었음
또는 후보 SQL이 실패했음
또는 원본 SQL 유지 판정
```

이 경우 튜닝 SQL 코드블록을 보여주면 안 됩니다.

---

## 16. 현재 Known Limitation

| 항목 | 설명 |
|---|---|
| Vector 검색 | 현재 완전한 semantic vector distance보다 fingerprint/chunk scan 중심 |
| Source helper 필요 | Source DB에 `ASTA_SOURCE_PKG` 설치 필요 |
| SQLTUNE 의존성 | Source DB 권한/상태에 따라 실패 가능 |
| DB Link CLOB 제약 | Source 결과는 store + chunk 방식으로 가져옴 |
| ORDS 동기 호출 | 긴 SQLTUNE 실행 시 timeout 정렬 필요 |
| LLM 후보 품질 | AI 후보 SQL은 실패할 수 있으므로 반드시 실행 검증 필요 |

---

## 17. 테스트/검증 기준

권장 테스트:

```bash
cd /home/ubuntu/descente_poc_ui/ai-poc-descente-main

node --check static/js/extensions/tuning_assistant.js

uv run python -m py_compile app/routers/asta_proxy.py

uv run --with pytest pytest \
  tests/test_asta_proxy.py \
  tests/test_asta_adb_ords_static_contracts.py \
  tests/test_asta_ords_migration_contract.py \
  tests/test_tuning_assistant_static.py \
  -q
```

10개 SQL live regression에서 확인하는 것:

```text
- HTTP 200 여부
- status COMPLETED 여부
- 11단계 progress 여부
- Source direct 노출 없음
- ORA-03150 노출 없음
- LLM_REWRITE 완료 여부
- AFTER_EVIDENCE 완료 여부
- FINAL_REPORT 생성 여부
- Vector save 여부
```

---

## 18. 사용자가 이해해야 할 핵심 요약

### 18.1 ASTA는 “AI가 SQL을 바꿔주는 프로그램”만은 아님

정확히는 아래를 묶은 프로그램입니다.

```text
Oracle 실행 증거
+ Oracle SQL Tuning Advisor
+ 과거 튜닝 사례
+ AI 후보 SQL
+ 실제 전후 실행 검증
+ 보고서 생성
```

### 18.2 AI보다 실행 검증이 우선

AI가 아무리 그럴듯한 SQL을 만들어도 아래 조건이면 채택하지 않습니다.

```text
실제 Source DB에서 실행 안 됨
결과가 다름
성능 개선 근거 없음
```

### 18.3 개선 SQL이 없을 수도 있음

그 경우 보고서는 아래 중심으로 나옵니다.

```text
개선 SQL 없음
원본 SQL 유지
DBA 검토사항
Advisor 권고
Vector 참고 사례
```

### 18.4 운영 DB 변경은 사람 승인 필요

ASTA는 자동으로 인덱스를 만들거나 SQL Profile을 적용하지 않습니다.

---

## 19. 한 장짜리 요약

```text
AI SQL Tuning Assistant(ASTA)

입력:
  - 사용자가 입력한 SELECT/WITH SQL
  - 선택한 AI profile
  - SQLTUNE 사용 여부
  - 사용자 튜닝 메모

처리:
  1. FastAPI가 ORDS로 중계
  2. ADB ASTA_PKG가 전체 분석 orchestration
  3. SQL Guard로 안전성 검사
  4. DB Link로 Source helper 호출
  5. Source DB에서 원본 SQL 실행/XPLAN/metrics 수집
  6. 필요 시 Oracle SQL Tuning Advisor 수행
  7. Vector KB 유사 사례 검색
  8. DBMS_CLOUD_AI로 AI 후보 SQL 생성
  9. 후보 SQL을 다시 Source DB에서 실행 검증
  10. Before/After 비교
  11. Markdown 보고서 생성
  12. 결과를 Vector KB에 저장

출력:
  - run_id
  - 11단계 수행 이력
  - Source evidence 요약
  - SQL Tuning Advisor 요약
  - 튜닝 SQL 또는 개선 SQL 없음
  - Before/After 비교
  - DBA 검토사항
  - raw JSON artifacts

안전장치:
  - SELECT/WITH만 허용
  - Source DB 직접 접속 금지
  - DB Link allowlist만 사용
  - AI 후보 SQL은 실행 검증 후 채택
  - DDL/Profile/Stats 자동 적용 금지
```

---

## 20. 관련 파일 위치

| 구분 | 경로 |
|---|---|
| UI JS | `static/js/extensions/tuning_assistant.js` |
| FastAPI proxy | `app/routers/asta_proxy.py` |
| ORDS module | `db/ords/asta_ords_module.sql` |
| ADB main package | `db/adb/asta_pkg.sql` |
| SQL Guard | `db/adb/asta_sql_guard_pkg.sql` |
| Source bridge | `db/adb/asta_source_bridge_pkg.sql` |
| Vector package | `db/adb/asta_vector_pkg.sql` |
| LLM package | `db/adb/asta_llm_pkg.sql` |
| Report package | `db/adb/asta_report_pkg.sql` |
| Source helper | `db/source/asta_source_pkg.sql` |
| Repository DDL | `db/asta/*.sql` |
| Architecture doc | `docs/OADT2_ASTA_ARCHITECTURE.md` |
| User manual | `docs/AI_SQL_TUNING_ASSISTANT_MANUAL.md` |
