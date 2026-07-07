# ASTA 소스코드 실행 흐름

최종 업데이트: 2026-07-07

이 문서는 Real ASTA 저장소에서 사용자가 **AI 분석 실행**을 누른 뒤 브라우저, FastAPI, ADB ORDS, ADB package, DB Link, Source package가 실제로 어떤 순서로 동작하는지 추적한다. 정책과 판정의 단일 기준은 `OADT2_ASTA_ARCHITECTURE.md`이며, 이 문서는 구현 위치를 찾기 위한 companion 문서다.

## 1. 현재 운영 경로

```text
Browser
  static/js/extensions/tuning_assistant.js
    → POST /api/asta/analyze

FastAPI thin proxy
  app/routers/asta_proxy.py::analyze()
    → payload 정규화
    → POST ORDS /asta/analyze

ADB ORDS asta.v1
  db/ords/asta_ords_module.sql
    → ASTA_PKG.SUBMIT_RUN(:body_text)

ADB asynchronous runtime
  ASTA_PKG.SUBMIT_RUN
    → ASTA_RUNS에 QUEUED 저장
    → DBMS_SCHEDULER job 생성
    → 즉시 run_id 반환
  ASTA_PKG.EXECUTE_RUN(run_id)
    → ASTA_PKG.RUN_PIPELINE(...)

Source boundary
  ASTA_SOURCE_BRIDGE_PKG.RUN_SOURCE_EVIDENCE
    → ASTA_SOURCE_CONNECTIONS allowlist
    → DB Link
    → Source ASTA_SOURCE_PKG.RUN_EVIDENCE_STORE_PROC
    → ASTA_SOURCE_PKG.RUN_EVIDENCE

Browser polling
  GET /api/asta/runs/{run_id}/progress
  terminal 이후 GET /api/asta/runs/{run_id}
  결과서 GET /api/asta/runs/{run_id}/report
```

중요한 경계는 다음과 같다.

- FastAPI는 SQL, XPLAN, Advisor, LLM, Vector를 로컬에서 실행하지 않는다.
- 현재 `/api/asta/analyze`는 FastAPI `BackgroundTasks`에 장기 분석을 등록하지 않는다. ORDS 제출을 기다린 뒤 ADB의 `QUEUED` 응답을 전달한다.
- 장기 실행의 소유자는 ADB `DBMS_SCHEDULER`다. 프로세스 재시작이나 브라우저 종료와 무관하게 ADB 저장 상태를 기준으로 조회한다.
- Source SQL은 ADB가 allowlist에서 고른 DB Link를 통해서만 Source `ASTA_SOURCE_PKG`에서 실행된다.
- Python direct DB/SSH/subprocess fallback은 운영 경로가 아니다.

## 2. 화면 생성과 입력

주요 파일은 다음과 같다.

- `static/index.html`: `tuning_assistant.js`, `asta_report_tabs.js` cache-busted asset 로드
- `static/js/extensions/tuning_assistant.js`: 입력, 샘플, 제출, polling, 진행 Drawer, 결과 카드
- `static/js/extensions/asta_report_tabs.js`: Markdown section 분류, 6개 탭, SQL 좌우 비교, verdict 도움말

화면은 다음 입력을 만든다.

- AI Profile
- 실행 유형 `OLTP` 또는 `BATCH`
- 샘플 SQL 또는 직접 입력
- AI 참고사항
- SQL textarea

샘플은 OLTP 15개와 BATCH 5개다. 샘플을 선택하면 SQL과 workload만 채워지며 분석은 자동 시작하지 않는다.

`SQL 분석 입력`과 `ASTA 분석 결과`는 독립적인 `<details>`다. 결과가 정상 렌더링될 때 입력은 접고 결과를 펼친다. 초기화하면 결과를 비우고 입력을 다시 연다.

상단 **매뉴얼 및 사용설명**은 `aria-modal` dialog를 연다. User/개발자 카드는 OCI 리소스 없이 PoC 샘플 화면 역할만 표시한다. UI(VM) 카드는 `OCI Load Balancer → DK-AI-DEV-VM-01` 진입 경로를 포함하고, AI Lakehouse/BaseDB 카드는 DEV/PRO/shared OCI 리소스를 기능·경계와 함께 표시한다. 11단계 Workflow 탭은 이 문서의 단계별 실행 영역과 실제 package/procedure를 화면 안에서 조회할 수 있게 한다. backdrop, 닫기 버튼, `Escape`로 닫을 수 있고 포커스는 열기 전 control로 돌아간다.

## 3. 브라우저 제출

`tuning_assistant.js`의 실행 handler는 SQL formatting과 클라이언트 검사를 거쳐 same-origin endpoint를 호출한다.

```http
POST /api/asta/analyze
Content-Type: application/json
```

주요 payload는 다음 의미를 가진다.

```json
{
  "sql": "SELECT ...",
  "sql_text": "SELECT ...",
  "source_db_id": "allowlisted logical id",
  "ai_profile": "ASTA_...",
  "llm_profile": "ASTA_...",
  "run_advisor": false,
  "use_sqltune": false,
  "tuning_context": {
    "workload_type": "OLTP",
    "user_notes": "..."
  },
  "options": {
    "fetch_rows": 100,
    "timeout_seconds": 900,
    "run_mode": "ASYNC"
  }
}
```

일반 UI는 `run_advisor=false`, `use_sqltune=false`다. Advisor를 명시적으로 켜는 API 계약은 남아 있지만 화면 기본 실행에서는 사용하지 않는다. 사용자가 DB Link 이름이나 Source schema를 직접 지정할 수 없다.

제출 직후 브라우저는 임시 진행 정보를 표시한다. ADB가 run ID를 반환하면 `/progress` polling으로 전환한다. `QUEUED`와 `RUNNING`은 처리 상태이며 개선 성공 판정이 아니다.

## 4. FastAPI thin proxy

파일: `app/routers/asta_proxy.py`

### 4.1 `analyze()`

현재 동작은 다음과 같다.

1. request JSON이 object인지 확인한다.
2. `_coerce_payload()`로 `sql/sql_text`, `ai_profile/llm_profile`, boolean과 제한값을 정규화한다.
3. `source_schema`, `source_db_link` 같은 임의 연결 입력을 제거하고 logical `source_db_id`만 유지한다.
4. `run_id`가 없으면 `OADT2-ASTA-<uuid>`를 만들고 `run_id/client_run_id`에 넣는다.
5. 설정의 ORDS `analyze_path`로 `_post_json_to_ords()`를 호출한다.
6. ORDS의 `QUEUED/RUNNING` 제출 응답을 감사 정보와 함께 반환한다.

FastAPI source에는 과거 호환을 위한 in-memory async helper와 `BackgroundTasks` 인자가 남아 있다. 그러나 현재 `analyze()`는 `background_tasks.add_task()`를 호출하지 않는다. 이를 현재 실행 owner로 문서화하거나 새 코드에서 사용하면 안 된다.

### 4.2 조회 endpoint

| OADT2 endpoint | proxy 함수 | ORDS suffix |
|---|---|---|
| `GET /api/asta/profiles` | `profiles()` | `/profiles` |
| `GET /api/asta/runs/{run_id}` | `get_run()` | `/runs/{run_id}` |
| `GET /api/asta/runs/{run_id}/progress` | `get_run_progress()` | `/runs/{run_id}/progress` |
| `GET /api/asta/runs/{run_id}/report` | `get_run_report()` | `/runs/{run_id}/report` |
| `GET /api/asta/runs/{run_id}/report/view` | 안전 HTML renderer | report JSON |
| `GET /api/asta/runs/{run_id}/report/download` | Markdown attachment | report JSON |

`_audited_run_lookup()`은 ORDS 응답에 proxy/audit 정보를 붙이고, final comparison이 있으면 Python의 mirror runtime gate를 적용해 계약 불일치를 fail-closed로 만든다. 로컬 snapshot 조회는 과거 실행의 진단/조회 보조 수단일 뿐 Source 분석 fallback이 아니다.

`/report/view`는 제한된 Markdown subset을 HTML로 변환하고 CSP를 적용한다. `/report/download`는 원문 Markdown을 attachment로 반환한다.

### 4.3 숨김 SQL-only 경로

`POST /api/asta/llm-sql-only`는 명시적인 숨김 진단 경로다. Evidence, SQL Guard 결과서, Vector, Advisor, deterministic 비교를 거치는 정식 ASTA 분석이 아니며 일반 결과와 혼용하지 않는다.

## 5. ORDS adapter

파일: `db/ords/asta_ords_module.sql`

ORDS module은 `asta.v1`, base path는 `asta/`다.

| ORDS handler | 호출 package 함수 |
|---|---|
| `POST asta/analyze` | `ASTA_PKG.SUBMIT_RUN(:body_text)` |
| `GET asta/profiles` | `ASTA_PKG.LIST_PROFILES` |
| `GET asta/runs/:run_id` | `ASTA_PKG.GET_RUN(:run_id)` |
| `GET asta/runs/:run_id/progress` | `ASTA_PKG.GET_PROGRESS(:run_id)` |
| `GET asta/runs/:run_id/report` | `ASTA_PKG.GET_REPORT(:run_id)` |

각 handler는 JSON CLOB을 2,000자 단위로 출력하며 `no-store`, execution boundary, contract version header를 설정한다. ORDS 자체는 분석 로직이나 판정을 수행하지 않는다.

## 6. ADB 제출과 Scheduler

파일: `db/adb/asta_pkg.sql`

### 6.1 `ASTA_PKG.SUBMIT_RUN`

`SUBMIT_RUN`은 다음 순서로 동작한다.

1. run ID와 선택적 `idempotency_key`를 정규화한다.
2. SQL이 존재하는지 확인하고 `ASTA_SQL_GUARD_PKG.ASSERT_SAFE_SELECT`를 실행한다.
3. 동일 idempotency key와 동일 request면 기존 run을 반환한다.
4. 같은 key에 다른 request면 `IDEMPOTENCY_CONFLICT`, 같은 run ID 충돌이면 `RUN_ID_CONFLICT`로 거절한다.
5. `ASTA_RUNS`에 request JSON과 `QUEUED` 상태를 commit한다.
6. `ASTA_RUN_<id>` Scheduler job을 만들고 `ASTA_PKG.EXECUTE_RUN(run_id)` 인자를 설정한다.
7. job을 enable하고 `execution_mode=ADB_SCHEDULER` 응답을 반환한다.

대표 응답:

```json
{
  "run_id": "OADT2-ASTA-...",
  "status": "QUEUED",
  "execution_mode": "ADB_SCHEDULER",
  "job_name": "ASTA_RUN_..."
}
```

### 6.2 `ASTA_PKG.EXECUTE_RUN`

Scheduler는 `QUEUED` 또는 승인된 `RETRY` row를 잠그고 상태를 `RUNNING`으로 바꾼 뒤 저장된 `REQUEST_JSON`으로 `RUN_PIPELINE`을 호출한다. 예외 시 run을 `FAILED/EXECUTE_RUN`으로 종결한다.

`ASTA_PKG.ANALYZE_SQL`은 현재 호환 wrapper이며 내부에서 `SUBMIT_RUN`을 호출한다. ORDS handler는 `ANALYZE_SQL`이 아니라 `SUBMIT_RUN`을 직접 호출한다.

## 7. ADB pipeline과 11단계

저장/API 단계 번호는 고정되어 있다.

| 번호 | code | 실제 역할 |
|---:|---|---|
| 1 | `REQUEST_RECEIVED` | 요청 접수 marker |
| 2 | `ORDS_DISPATCH` | ORDS 전달 marker |
| 3 | `SQL_GUARD` | read-only 단일 SQL 재검증 |
| 4 | `BEFORE_EVIDENCE` | 원본 Source evidence |
| 5 | `SQL_TUNING_ADVISOR` | Source evidence 안의 Advisor 상태 반영 |
| 6 | `LLM_REWRITE` | evidence 기반 구조 재작성 |
| 7 | `AFTER_EVIDENCE` | 후보 Source evidence와 runtime watchdog |
| 8 | `BEFORE_AFTER_COMPARE` | deterministic gate와 workload 판정 |
| 9 | `VECTOR_KB` | LLM 전에 검증 사례 검색 |
| 10 | `FINAL_REPORT` | Markdown 결과서 작성 |
| 11 | `VECTOR_SAVE` | gate 결과에 맞는 Vector 관측 저장 |

단계 번호 순서와 실제 호출 의존 순서는 다르다.

```text
1 REQUEST_RECEIVED
2 ORDS_DISPATCH
3 SQL_GUARD
4 BEFORE_EVIDENCE
5 SQL_TUNING_ADVISOR
9 VECTOR_KB search
6 LLM_REWRITE
7 AFTER_EVIDENCE
8 BEFORE_AFTER_COMPARE
11 VECTOR_SAVE
10 FINAL_REPORT
```

Vector 검색 결과가 LLM prompt에 들어가므로 9단계가 6단계보다 먼저 실행된다. 번호는 API 호환 때문에 바꾸지 않는다.

### 7.1 Before evidence

`RUN_PIPELINE`은 `ASTA_SOURCE_CONNECTIONS`의 logical source를 확인하고 bridge에 다음 핵심 값을 전달한다.

- 원본 SQL과 run marker
- `repeat_policy=AUTO`
- `result_evidence_mode=FULL_RESULT`
- fetch/result 행 예산
- Advisor opt-in 여부
- 선택적 원본 `source_sql_id`

실패하면 4단계를 FAILED로 기록하고 fail-closed error를 반환한다.

### 7.2 Vector 검색과 LLM

`ASTA_VECTOR_PKG`는 positive verified 사례만 검색 근거로 사용한다. `ASTA_LLM_PKG`는 원본 SQL 외에 XPLAN, 실제 metrics, object 정보, Advisor 상태, 유사 사례, workload와 사용자 참고사항을 받아 JSON-only 구조 후보를 만든다.

후보 SQL은 SQL Guard를 다시 통과해야 한다. 제한된 repair 후에도 안전한 후보가 없으면 7·8단계를 `SKIPPED`, verdict를 `NO_REWRITE`로 처리한다.

### 7.3 After evidence와 watchdog

후보가 있으면 7단계에서 동일 Source 경로로 실행한다. adaptive candidate runtime limit를 계산하고 watchdog job을 arm한다. timeout은 후보를 `CANDIDATE_RUNTIME_LIMIT`로 실패시키고 원본을 유지한다.

ADB job stop이 DB Link 너머 이미 시작한 Source statement를 즉시 취소한다고 가정하지 않는다. 운영 진단 시 ADB run/job과 Source session의 run marker를 함께 확인한다.

### 7.4 deterministic 비교

8단계 비교 순서는 다음과 같다.

1. optimizer intent evidence
2. full-result 및 metadata equivalence
3. bind/child cursor evidence 또는 `BIND_NOT_APPLICABLE`
4. warm-up/반복 측정 완전성 및 noise
5. OLTP/BATCH 성능 기준

모든 필수 gate를 통과해야 `IMPROVED`다. LLM 설명, Advisor 권고, Vector 유사도는 verdict를 덮어쓰지 못한다.

### 7.5 Vector 저장과 결과서

검증이 끝나면 `ASTA_VECTOR_PKG`가 gate-complete success와 rejected observation을 분리해 저장한다. raw SQL, literal, bind 값은 Vector metadata에 저장하지 않는다.

`ASTA_REPORT_PKG.BUILD_REPORT`는 comparison과 같은 verdict의 Markdown을 만든다. `ASTA_RUN_PROGRESS` timing을 넣기 위해 단계 10/11 저장 후 report를 다시 구성하고, 최종 response/report/status를 `ASTA_RUNS`에 commit한다. rich response 저장이 실패해도 완료 run을 RUNNING으로 남기지 않고 `FAILED/ASTA_PERSIST`로 종결한다.

## 8. ADB → Source DB bridge

파일: `db/adb/asta_source_bridge_pkg.sql`

`ASTA_SOURCE_BRIDGE_PKG.RUN_SOURCE_EVIDENCE`는 다음 안전 경계를 적용한다.

1. `source_db_id`로 enabled `ASTA_SOURCE_CONNECTIONS` row를 조회한다.
2. DB Link, schema, run ID, source SQL ID 형식을 검증한다.
3. ADB `ASTA_SQL_GUARD_PKG`로 SQL을 다시 검사한다.
4. fetch rows, repeat policy, Advisor limit, result mode/max rows를 범위 안으로 정규화한다.
5. SQL CLOB을 AL32UTF8 byte 수 기준 최대 32,767-byte DB Link VARCHAR2 payload로 변환한다.
6. 동적 호출 대상은 allowlisted schema와 link의 `ASTA_SOURCE_PKG.RUN_EVIDENCE_STORE_PROC`로 제한한다.
7. Source가 저장한 결과를 chunk로 회수해 ADB CLOB으로 조립한다.

멀티바이트 SQL은 4,000-character chunk로 읽어 누적 `LENGTHB`를 검사한다. 32,767 bytes를 넘으면 잘라 보내지 않고 명시적으로 거절한다.

## 9. Source evidence

파일: `db/source/asta_source_pkg.sql`

공개 진입점은 `RUN_EVIDENCE`, DB Link 저장 wrapper인 `RUN_EVIDENCE_STORE_PROC`와 `RUN_EVIDENCE_STORE_VC`다.

### 9.1 SQL Guard와 parsing schema

Source에서도 하나의 `SELECT` 또는 `WITH`만 허용한다. `source_sql_id`가 있으면 원 SQL의 parsing schema를 찾아 `CURRENT_SCHEMA`를 일시 변경해 이름 해석을 재현한다. 이는 이름 해석만 바꾸며 객체 권한을 추가하지 않는다. 종료와 예외 경로에서 원 schema로 복원한다.

### 9.2 반복 실행과 metrics

`AUTO`는 warm-up 1회와 측정 3회다. 각 bounded 실행에는 `gather_plan_statistics`와 `ASTA_RUN_ID` marker가 들어간다.

각 실행 후 marker로 `V$SQL` cursor를 찾고 `V$SQL_PLAN_STATISTICS_ALL`의 LAST metrics를 수집한다.

- elapsed time
- Buffer Gets
- Disk Reads
- output rows
- SQL ID, child number, plan hash

측정 3회가 모두 존재하고 elapsed noise가 20% 이하여야 Source measurement status가 `ACCEPTED`다. median elapsed, Buffer Gets, Disk Reads와 개별 `measurement_runs`를 반환한다.

### 9.3 XPLAN, optimizer intent, bind

`DBMS_XPLAN.DISPLAY_CURSOR` 기반 plan text와 node statistics를 수집한다. `optimizer_intent_evidence`는 target access/operation, Starts, buffers, plan shape 등 ADB 비교가 사용할 실제 node evidence를 제공한다.

child cursor/ACS와 `V$SQL_BIND_CAPTURE`는 raw bind 값을 반환하지 않는다. bind metadata는 datatype/position/bucket/fingerprint 중심이며 원문 값은 유지하지 않는다. placeholder와 capture가 모두 없으면 `BIND_NOT_APPLICABLE`, bind가 있으나 replay가 없으면 fail-closed blocked evidence다.

### 9.4 객체 통계와 인덱스

XPLAN의 owner/object를 기준으로 다음 dictionary를 조회한다.

- `DBA_TAB_STATISTICS`
- `DBA_TAB_COLUMNS`
- `DBA_INDEXES`
- `DBA_IND_COLUMNS`

ALL_* 가시성에 없지만 실행계획에는 나타나는 객체도 Source 계정의 실제 dictionary 권한 범위에서 수집하기 위한 현재 계약이다. table rows/blocks, column metadata, index와 index column을 JSON `object_info`로 반환한다.

### 9.5 full-result equivalence evidence

성능/XPLAN은 bounded wrapper로 측정하고, 결과 동일성은 별도 pass로 처리한다.

`FULL_RESULT`이면 먼저 전체 행 수를 계산한다. 최대 행 예산을 넘으면 `EQUIVALENCE_BUDGET_EXCEEDED`로 차단한다. 예산 안이면 다음을 digest에 반영한다.

- 컬럼 순서·이름·datatype·precision/scale·길이·charset metadata
- NULL을 구분한 typed row hash
- 중복 행 개수
- 최종 `ORDER BY`가 있으면 `ORDERED_ROWS`
- 없으면 `UNORDERED_MULTISET`
- 전체 행 수와 complete marker

일부 결과, digest 오류, metadata/mode 불일치는 동일하다고 추정하지 않는다.

### 9.6 SQL Tuning Advisor

`p_run_advisor='Y'`일 때만 SQL Tuning Advisor를 실행한다. 현재 일반 UI는 OFF다. Source가 만든 현재 호출 소유의 `ASTA_ADV_%` Scheduler job만 best-effort cleanup하며 실행 중인 다른 job이나 기존 job을 임의로 force drop하지 않는다. Advisor report는 참고 evidence이며 자동 적용 대상이 아니다.

## 10. Progress 조회와 화면 표시

`ASTA_PKG.RECORD_PROGRESS`는 `(run_id, seq)` 기준으로 상태, detail, `started_at`, `completed_at`, `elapsed_ms`를 `ASTA_RUN_PROGRESS`에 저장한다. `GET_PROGRESS`는 작고 빠른 polling JSON을 만든다.

브라우저는 같은 run 동안 progress DOM 골격을 한 번 만들고 값이 달라진 부분만 갱신한다. 단계 전환마다 전체 `innerHTML`을 교체하지 않아 compact bar와 Drawer 깜빡임을 방지한다.

기본 화면은 현재 단계, 전체 경과시간, Run ID, **진행 상세** 버튼만 표시한다. Drawer는 11단계 카드와 redacted detail을 보여준다. 표시 규칙은 다음과 같다.

- 실제 저장 elapsed: ms 또는 초/분으로 표시
- timestamp 차이로 계산 가능: 계산 소요시간 표시
- timestamp만 있고 구간 측정 불가: `미측정`
- 명시적 `SKIPPED`: `생략`
- 시작 전 `PENDING`: `-`

Drawer는 닫기, backdrop, Escape를 지원하고 모바일에서는 bottom sheet가 된다.

## 11. 결과 조회와 6개 탭

terminal progress를 받은 뒤 UI는 전체 run/report를 조회한다. 결과 Markdown은 다음 탭으로 분류한다.

1. 요약
2. 튜닝 전
3. SQL 변경
4. 튜닝 후
5. 상세 분석
6. 객체 정보

`SQL 변경`은 원본/후보 SQL을 좌우 pane에 줄 번호와 함께 배치하고 remove/add block을 정렬한다. raw report는 바꾸지 않는다. 객체 정보 heading은 package가 동일 제목을 여러 번 만들 수 있어 해당 section만 원문 순서대로 병합한다. 다른 중복 heading은 잘못된 배치를 피하려고 fail-closed 처리한다.

요약의 canonical verdict를 allowlist로 추출해 badge를 표시한다. `?` popover는 여섯 verdict의 의미와 권장 조치를 설명할 뿐 comparison을 변경하지 않는다. Markdown renderer는 `textContent` 중심의 안전 DOM을 사용하며 raw HTML과 script link를 실행하지 않는다.

## 12. 저장 객체

| 객체 | 역할 |
|---|---|
| `ASTA_RUNS` | request, 상태, 원본/후보, response JSON, Markdown, Scheduler metadata |
| `ASTA_RUN_PROGRESS` | 11단계 상태와 timing |
| `ASTA_SOURCE_CONNECTIONS` | logical source와 enabled DB Link/schema allowlist |
| `ASTA_LLM_CALL_LOG` | LLM stage/attempt/크기/상태 감사 |
| `ASTA_TUNING_CASES` 및 chunk | positive/rejected Vector 사례 |

운영 artifact와 인계 파일에는 token, password, cookie, wallet 정보, raw bind 값을 기록하지 않는다.

## 13. 상태와 장애 해석

- `QUEUED/RUNNING/COMPLETED/FAILED`는 pipeline 처리 상태다.
- `COMPLETED`가 곧 `IMPROVED`는 아니다. 최종 comparison verdict를 확인한다.
- `NO_REWRITE`, `NOT_IMPROVED`, `NON_EQUIVALENT`, `CANDIDATE_FAILED`, `INSUFFICIENT_EVIDENCE`는 모두 원본 SQL 유지다.
- 6단계 장기 실행은 모델 HTTP 대기인지 LLM 응답 후 PL/SQL 후처리 CPU인지 LLM audit와 session stack을 함께 확인한다.
- 7단계 timeout은 ADB watchdog 완료와 Source session 종료를 구분해 확인한다.
- 4단계 ORA-06502는 SQL character 길이뿐 아니라 UTF-8 byte 길이, bridge CLOB 변환, Source 내부 VARCHAR2 경계를 확인한다.
- 객체 정보가 비면 XPLAN object 존재 여부와 DBA_* dictionary 가시성을 대조한다.

진단만 요청받았을 때 job stop, run 상태 변경, package 배포를 수행하지 않는다. 중단이 필요하면 해당 run이 소유한 Scheduler job과 Source session인지 확인하고 별도 승인을 받는다.

## 14. 배포와 검증 경계

ADB package compile 순서:

```text
ASTA_SQL_GUARD_PKG
  → ASTA_SOURCE_BRIDGE_PKG
  → ASTA_VECTOR_PKG
  → ASTA_LLM_PKG
  → ASTA_REPORT_PKG
  → ASTA_PKG
```

Source `ASTA_SOURCE_PKG`, ADB package, schema migration, ORDS module, Python service, static asset은 서로 별도 배포 대상이다. 저장소 파일을 수정했다고 실환경에 반영된 것으로 보지 않는다.

배포 시에는 승인된 범위에서 다음을 확인한다.

1. 배포 전 DDL/설정 백업
2. package spec/body `VALID`, `USER_ERRORS=0`
3. ORDS handler와 contract version
4. Source bridge marker, repeat/full-result/object metadata smoke
5. 제출 `QUEUED`, progress, terminal run, report 조회
6. static cache version과 served byte 일치
7. rollback 절차

현재 문서가 반영하는 2026-07-06~07 실환경 변경에는 Scheduler 기반 pipeline, full-result/optimizer intent/bind/반복 측정 evidence, 14개 OLTP 샘플 최종 검증, 단계 timing, 멀티바이트 bridge 수정, Source DBA_* 객체정보 수집, 5개 BATCH 샘플과 최신 UI가 포함된다.

## 15. 코드 읽기 순서

1. `docs/OADT2_ASTA_ARCHITECTURE.md`
2. `static/js/extensions/tuning_assistant.js`
3. `app/routers/asta_proxy.py`
4. `db/ords/asta_ords_module.sql`
5. `db/adb/asta_pkg.sql`
6. `db/adb/asta_source_bridge_pkg.sql`
7. `db/source/asta_source_pkg.sql`
8. `db/adb/asta_llm_pkg.sql`
9. `db/adb/asta_vector_pkg.sql`
10. `db/adb/asta_report_pkg.sql`
11. `static/js/extensions/asta_report_tabs.js`

이 순서로 읽으면 제출 owner, Source 실행 경계, evidence, 판정, 저장, 화면 표시를 혼동하지 않고 따라갈 수 있다.
