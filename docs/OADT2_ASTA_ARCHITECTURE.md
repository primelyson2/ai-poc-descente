# OADT2 ASTA 아키텍처 및 프로그램 명세

최종 업데이트: 2026-07-06

이 문서는 ASTA(AI SQL Tuning Assistant)의 내부 아키텍처, 실행 순서, API, 판정 기준을 설명하는 단일 기준 문서다. 개발자용 사용법과 쉬운 오류 조치는 `AI_SQL_TUNING_ASSISTANT_MANUAL.md`, 품질 자동화는 `ASTA_QUALITY_AGENT.md`를 참고한다.

## 1. 목적과 안전 원칙

ASTA는 느린 조회 SQL을 분석하고 구조적으로 다시 작성한 후보를 실제로 비교한다. 다음 조건을 모두 확인한 경우에만 후보를 `IMPROVED`로 채택한다.

1. Oracle 실행계획에서 의도한 병목이 제거되었다.
2. 원본과 후보의 전체 결과가 동일하다.
3. 바인드와 실행계획 안정성이 확인되었거나 바인드가 없다.
4. 반복 측정이 충분하고 결과 변동이 허용 범위 안이다.
5. OLTP 또는 BATCH 기준에서 실제 성능이 개선되었다.

확인이 부족하거나 후보 실행이 실패하면 원본 SQL을 유지한다. ASTA는 운영 SQL 교체, DDL/DML, 인덱스·통계·SQL Profile·SQL Plan Baseline 적용을 자동으로 수행하지 않는다.

## 2. 유일한 운영 경로

```text
Browser
  → OADT2 FastAPI thin proxy (/api/asta/*)
  → ADB ORDS (asta.v1)
  → ADB ASTA_PKG / DBMS_SCHEDULER
  → ASTA_SOURCE_BRIDGE_PKG
  → allowlisted DB Link
  → Source DB ASTA_SOURCE_PKG
```

- 브라우저는 외부 ORDS 주소나 Source DB를 직접 호출하지 않는다.
- FastAPI는 same-origin 요청 전달, 응답 정규화, 조회 감사만 담당하는 thin proxy다.
- FastAPI/Python의 Source direct, SSH/subprocess 실행 및 Python ASTA runtime fallback은 금지한다.
- ADB PL/SQL이 SQL Guard, 비동기 실행, LLM, Vector, 비교와 결과서 생성을 담당한다.
- Source PL/SQL만 Source SQL 실행, XPLAN, 실행 통계, 전체 결과 digest와 선택적 SQL Tuning Advisor를 수집한다.
- Source 연결은 ADB `ASTA_SOURCE_CONNECTIONS` allowlist에서 결정한다. 사용자가 임의 DB Link를 요청에 넣을 수 없다.

## 3. 구성요소와 책임

| 구성요소 | 책임 | 하지 않는 일 |
|---|---|---|
| `static/js/extensions/tuning_assistant.js` | SQL 입력, 샘플 선택, 실행 유형, 비동기 poll, 개발자 친화 메시지 | DB 직접 접속, 최종 판정 생성 |
| `static/js/extensions/asta_report_tabs.js` | Markdown 결과서를 5개 탭의 안전한 DOM으로 표시 | raw HTML 실행, 판정 변경 |
| `app/routers/asta_proxy.py` | ORDS thin proxy, run/progress/report 조회, 상태 정규화와 감사 | Source SQL·LLM·Vector 로컬 실행 |
| `ASTA_SQL_GUARD_PKG` | 단일 read-only `SELECT`/`WITH` 검증 | DML/DDL 허용 |
| `ASTA_SOURCE_BRIDGE_PKG` | allowlisted DB Link를 통한 Source package 호출 | 임의 link 또는 Source direct 연결 |
| `ASTA_LLM_PKG` | 실행 근거 기반 진단, 구조 재작성, 제한된 repair | 근거 없는 객체·인덱스 생성 |
| `ASTA_VECTOR_PKG` | 검증된 사례 검색, gate 결과에 따른 사례 저장 | 과거 사례만으로 현재 후보 채택 |
| `ASTA_REPORT_PKG` | 비교 artifact와 같은 결론의 Markdown 생성 | raw Advisor/비밀정보 덤프 |
| `ASTA_PKG` | 요청 저장, Scheduler 실행, 단계 orchestration, deterministic 최종 비교 | 운영 변경 자동 적용 |
| Source `ASTA_SOURCE_PKG` | SQL 실행, XPLAN/metrics/object 정보, full-result digest, bind evidence | 후보 채택 결정 |

## 4. 비동기 API 실행 계약

### 제출

`POST /api/asta/analyze`는 FastAPI background worker에서 긴 분석을 유지하지 않는다. 요청은 ORDS의 `ASTA_PKG.SUBMIT_RUN`으로 전달되고, ADB는 `ASTA_RUNS`에 요청을 저장한 뒤 `DBMS_SCHEDULER` job을 생성해 다음 형태로 즉시 응답한다.

```json
{
  "run_id": "OADT2-ASTA-...",
  "status": "QUEUED",
  "execution_mode": "ADB_SCHEDULER"
}
```

Scheduler는 `ASTA_PKG.EXECUTE_RUN(run_id)`을 호출한다. `EXECUTE_RUN`은 저장된 `REQUEST_JSON`을 읽어 분석을 수행한다. 같은 `idempotency_key`와 같은 요청은 기존 run을 반환하며, 다른 요청에 같은 key를 쓰면 `IDEMPOTENCY_CONFLICT`로 거절한다.

### 조회

| OADT2 API | ADB ORDS/PLSQL | 용도 |
|---|---|---|
| `GET /api/asta/profiles` | `ASTA_PKG.LIST_PROFILES` | 선택 가능한 `ASTA*` AI profile |
| `GET /api/asta/runs/{run_id}/progress` | `ASTA_PKG.GET_PROGRESS` | 작고 빠른 진행 상태 poll |
| `GET /api/asta/runs/{run_id}` | `ASTA_PKG.GET_RUN` | 완료 artifact 조회 |
| `GET /api/asta/runs/{run_id}/report` | `ASTA_PKG.GET_REPORT` | Markdown 결과서 조회 |
| `GET /api/asta/runs/{run_id}/report/view` | OADT2 안전 HTML renderer | 브라우저 결과서 보기 |
| `GET /api/asta/runs/{run_id}/report/download` | OADT2 Markdown response | 원문 결과서 내려받기 |

UI는 `progress`를 poll하고 terminal 상태가 된 뒤 전체 run 또는 report를 한 번 조회한다. 수십 MB가 될 수 있는 전체 artifact를 진행 확인 용도로 반복 조회하지 않는다.

## 5. 11단계와 실제 수행 순서

저장/API 호환을 위해 단계 번호와 code는 고정한다.

| 번호 | code | 쉬운 의미 |
|---:|---|---|
| 1 | `REQUEST_RECEIVED` | 요청 접수 |
| 2 | `ORDS_DISPATCH` | ADB 분석 요청 전달 |
| 3 | `SQL_GUARD` | 조회 SQL 안전 확인 |
| 4 | `BEFORE_EVIDENCE` | 원본 SQL 실행 정보 수집 |
| 5 | `SQL_TUNING_ADVISOR` | Oracle 튜닝 권고 수집 또는 생략 |
| 6 | `LLM_REWRITE` | 근거 기반 후보 SQL 생성 |
| 7 | `AFTER_EVIDENCE` | 후보 SQL 실행 정보 수집 |
| 8 | `BEFORE_AFTER_COMPARE` | 원본/후보 deterministic 비교 |
| 9 | `VECTOR_KB` | 검증 사례 검색 |
| 10 | `FINAL_REPORT` | 최종 결과서 생성 |
| 11 | `VECTOR_SAVE` | 검증 결과 사례 저장 |

실제 의존 순서는 다음과 같다.

```text
SQL_GUARD
  → BEFORE_EVIDENCE
  → SQL_TUNING_ADVISOR
  → VECTOR_KB
  → LLM_REWRITE
  → AFTER_EVIDENCE
  → BEFORE_AFTER_COMPARE
  → VECTOR_SAVE
  → FINAL_REPORT
```

`VECTOR_KB`는 LLM 입력에 선행하지만 호환을 위해 단계 번호 9를 유지한다. 후보가 없으면 7·8단계는 `SKIPPED` 또는 `NO_REWRITE` artifact를 남긴다. 호환용 final review는 새로운 AI 판정을 만들지 않고 `SKIPPED / DETERMINISTIC_COMPARISON`으로 남는다.

## 6. 입력과 LLM 재작성 계약

SQL Guard는 하나의 `SELECT` 또는 `WITH` 문장만 허용한다. DML, DDL, PL/SQL, 여러 문장, `FOR UPDATE`와 허용되지 않은 객체는 실행하지 않는다.

LLM은 원본 SQL만 받지 않는다. 다음 근거를 함께 받아 구조적 후보를 만든다.

- compact XPLAN과 실제 Starts/A-Rows/A-Time/Buffers
- 실행시간, Buffer Gets, Disk Reads, 결과 행 수
- 객체·인덱스·통계 정보
- Advisor 상태와 요약된 권고 유형
- Vector KB의 검증된 유사 사례
- OLTP/BATCH 실행 유형과 사용자 참고사항

응답은 JSON-only 후보 계약을 따른다. SQL 문법 오류 등 제한된 경우에만 repair를 시도하며, 안전한 후보를 얻지 못하면 원본을 유지한다. 모델의 설명이나 과거 Vector 사례는 최종 채택 근거가 아니며 7·8단계의 실제 검증을 반드시 거친다.

## 7. 전체 결과 동일성 검증

행 수나 첫 N행만 같다고 결과 동일로 판정하지 않는다. Source `ASTA_SOURCE_PKG`는 다음 정보를 포함한 typed full-result digest를 만든다.

- 컬럼 순서, 이름, datatype, precision/scale, 길이와 문자 집합 metadata
- NULL을 구분한 행별 hash
- 중복 행의 multiplicity
- 최종 `ORDER BY`가 있으면 `ORDERED_ROWS`, 없으면 `UNORDERED_MULTISET`
- 전체 행 수, digest 처리 행 수, 완료 여부와 알고리즘

소스에서 보이는 `JSON_ARRAYAGG(JSON_OBJECT(... row_hash ... multiplicity ...))` 형태의 SQL은 업무 SQL을 바꾸는 쿼리가 아니다. 원본과 후보의 전체 결과가 같은지를 비교하기 위한 내부 FULLDIGEST wrapper다.

다음은 fail-closed로 `NON_EQUIVALENT` 또는 `INSUFFICIENT_EVIDENCE`가 된다.

- 결과 또는 metadata digest 불일치
- 일부 행만 처리했거나 digest가 완료되지 않음
- ordered/unordered mode 불일치
- 미지원 datatype 또는 비교에 필요한 정보 누락

## 8. 최종 안전 검증 순서

후보는 아래 순서로 검증한다. 앞 단계가 실패하면 뒤 성능 수치가 좋아도 채택하지 않는다.

1. **Optimizer intent**: 지배 병목의 Starts 감소, 반복 subtree 제거, anti/semi join 또는 barrier 유지 등 계획 의도가 실제 XPLAN에서 확인되어야 한다.
2. **Full-result equivalence**: 전체 결과와 metadata가 같아야 한다.
3. **Bind/plan stability**: 대표 bind bucket별 결과·계획이 안정적이어야 한다. bind가 없는 SQL은 `BIND_NOT_APPLICABLE`로 처리한다.
4. **Repeated measurement**: warm-up과 반복 측정 횟수, 중앙값, noise 기준을 충족해야 한다.
5. **Workload performance**: OLTP/BATCH 기준에서 실제 개선이어야 한다.

### OLTP

Buffer Gets를 우선하되 사용자 지연을 함께 제한한다. 현재 코드 기준의 주요 채택 조건은 다음과 같다.

- 후보 실행시간 3초 이하
- Buffer Gets 5% 이상 감소하면서 실행시간이 악화되지 않음, 또는
- Buffer Gets 20% 이상 감소하고 후보가 1초 이하이거나 실행시간 증가가 300ms 이하

### BATCH

전체 elapsed time 중앙값이 원본보다 감소해야 한다. 결과 동일성·반복 측정·noise 검증은 OLTP와 동일하게 선행한다.

## 9. 상태와 verdict

run의 `QUEUED`, `RUNNING`, `COMPLETED`, `FAILED`는 처리 상태다. `COMPLETED`는 분석 절차가 끝났다는 뜻이지 성능 개선 성공을 뜻하지 않는다. 채택 여부는 comparison verdict를 확인한다.

| verdict | 의미 | 최종 사용 SQL |
|---|---|---|
| `IMPROVED` | 모든 필수 검증을 통과하고 실제 개선 | 검증된 후보 |
| `NOT_IMPROVED` | 결과는 비교 가능하지만 성능 개선 없음 | 원본 |
| `NON_EQUIVALENT` | 원본과 후보 결과가 다름 | 원본 |
| `INSUFFICIENT_EVIDENCE` | 계획·결과·bind·반복 측정 근거 부족 | 원본 |
| `CANDIDATE_FAILED` | 후보 SQL 실행 실패 | 원본 |
| `NO_REWRITE` | 안전한 구조 재작성 후보 없음 | 원본 |

내부 `error_code`, `verdict_reason`, `measurement_reason`은 API와 운영 추적을 위해 유지한다. UI에서는 개발자가 이해할 수 있는 제목·설명·다음 행동을 먼저 보여주고 내부 코드는 **문의 코드**로 분리한다.

## 10. 제한 시간과 취소 경계

후보 실행에는 원본 실행시간을 기준으로 한 adaptive runtime limit를 적용한다. `CANDIDATE_RUNTIME_LIMIT`가 발생하면 후보를 중단하고 원본을 유지한다.

FULLDIGEST는 업무 SQL의 bounded fetch보다 오래 걸릴 수 있다. 특히 많은 결과를 정렬·hash하는 경우 후보 SQL 실행은 빨라도 동일성 검증이 한도를 넘을 수 있다. 현재 운영상 주의점은 다음과 같다.

- 후보 실행 budget과 전체 결과 digest budget을 구분해서 해석한다.
- ADB Scheduler job 중단이 DB Link 너머 Source session을 즉시 취소한다고 가정하지 않는다.
- timeout 이후 늦게 도착한 Source 결과를 기존 실패 verdict의 성공으로 덮어쓰지 않는다.
- 장시간 분석은 `progress`와 Source session을 함께 확인하고 업무 세션은 중단하지 않는다.

## 11. Advisor와 Vector 정책

일반 UI 요청은 현재 `run_advisor=false`, `use_sqltune=false`가 기본이다. Oracle SQL Tuning Advisor는 운영자가 라이선스와 시간을 검토해 명시적으로 요청할 때만 실행한다. Advisor가 생략되거나 실패해도 구조 재작성과 deterministic 비교는 가능한 범위에서 계속한다. Advisor 권고는 자동 적용하지 않는다.

Vector 저장은 검증 수준을 구분한다.

- 모든 필수 gate를 통과한 사례만 positive verified 사례로 검색에 사용한다.
- 실패·비동등·근거 부족·timeout은 rejected observation으로 분리한다.
- raw SQL, literal, bind 값, 인증정보를 Vector metadata에 저장하지 않는다.
- 내부 결과서 참조는 `/api/asta/runs/{run_id}/report` 형식을 사용한다.

## 12. 결과서와 UI

Markdown 원문은 comparison artifact와 같은 verdict를 사용한다. 후보가 최종 채택되지 않았더라도 실제 후보와 After evidence가 존재하면 진단 근거로 표시할 수 있지만, 반드시 **현재 적용하지 마세요**와 원본 유지 결론을 함께 표시한다.

UI는 결과서를 다음 5개 탭으로 나눈다.

1. 요약
2. 튜닝 전
3. 튜닝 후
4. 상세 분석
5. 객체 정보

탭 표시는 raw Markdown을 변경하지 않는다. renderer는 허용된 heading, 문단, 목록, 표, code block만 안전한 DOM으로 만들며 raw HTML/script 링크를 실행하지 않는다.

## 13. 저장 구조와 감사

주요 저장 객체는 다음과 같다.

- `ASTA_RUNS`: 요청, 상태, 원본/후보, 최종 response와 report
- `ASTA_RUN_PROGRESS`: 단계별 상태와 시간
- `ASTA_SOURCE_CONNECTIONS`: 허용된 Source DB와 DB Link mapping
- `ASTA_LLM_CALL_LOG`: LLM 단계·크기·상태 감사 정보
- `ASTA_TUNING_CASES`: Vector 사례와 검증 metadata

로그와 인계 문서에는 비밀번호, wallet password, token, cookie, raw bind 값을 기록하지 않는다. SQL 원문이 불필요한 운영 artifact에는 run ID, fingerprint, verdict와 허용된 측정값만 남긴다.

## 14. 설치·컴파일과 변경 경계

ADB package 컴파일 순서는 다음과 같다.

```text
ASTA_SQL_GUARD_PKG
  → ASTA_SOURCE_BRIDGE_PKG
  → ASTA_VECTOR_PKG
  → ASTA_LLM_PKG
  → ASTA_REPORT_PKG
  → ASTA_PKG
```

비동기 column migration이 적용되지 않은 기존 설치는 package 컴파일 전에 `db/asta/005_asta_async_run_columns.sql`을 적용해야 한다. ASTA schema에는 Scheduler job 생성·실행 권한이 필요하다.

저장소 코드 변경과 실환경 배포는 별개다. Source/ADB package, ORDS metadata, 서비스 재시작은 명시적 승인과 백업·rollback·VALID/USER_ERRORS 검증 없이 수행하지 않는다. workspace와 배포본의 계약이 다를 수 있으므로 실환경 검증 전 package marker와 object 상태를 확인한다.

## 15. 코드 기준 위치

- 사용자 매뉴얼: `docs/AI_SQL_TUNING_ASSISTANT_MANUAL.md`
- FastAPI proxy: `app/routers/asta_proxy.py`
- UI: `static/js/extensions/tuning_assistant.js`
- 결과서 탭: `static/js/extensions/asta_report_tabs.js`
- ADB packages: `db/adb/`
- ORDS module: `db/ords/asta_ords_module.sql`
- Source package: `db/source/asta_source_pkg.sql`
- 품질 gate: `app/asta_runtime_gates.py`, `tools/asta_execution_budget.py`, `tools/asta_result_equivalence.py`, `tools/asta_bind_plan_stability.py`
- 실행 도구: `tools/run_asta_10_sqls.py`, `tools/asta_smoke_adb.py`
- 공통 작업 인계: `.agent-handoff/CONTEXT.md`
