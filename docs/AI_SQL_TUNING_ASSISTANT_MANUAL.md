# AI SQL Tuning Assistant 개발자용 사용자 매뉴얼

최종 업데이트: 2026-07-06

## 1. 먼저 알아둘 내용

ASTA(AI SQL Tuning Assistant)는 느린 조회 SQL을 분석하고 개선 SQL을 제안하는 도구다. 원본과 개선 SQL을 실제로 비교한 뒤 안전하다고 확인된 경우에만 개선 성공으로 표시한다.

사용자가 먼저 알아야 할 내용은 세 가지다.

1. ASTA는 입력한 운영 SQL을 자동으로 바꾸지 않는다.
2. 오류나 확인 부족이 있으면 항상 원본 SQL을 유지한다.
3. 문제가 생기면 화면의 **다음 행동**을 먼저 읽고, 해결되지 않으면 **Run ID와 문의 코드**를 담당자에게 전달한다.

ASTA는 `SELECT` 또는 `WITH`로 시작하는 조회 SQL만 실행한다. INSERT, UPDATE, DELETE, 테이블 변경, 인덱스 생성은 수행하지 않는다.

### 자주 나오는 용어

| 화면/보고서 용어 | 쉬운 의미 |
|---|---|
| 원본 SQL | 사용자가 입력한 현재 SQL |
| 개선 SQL 또는 후보 SQL | ASTA가 테스트 목적으로 만든 SQL |
| 실행 정보 | 실행시간, 읽은 데이터량, 실행계획 등 비교에 필요한 정보 |
| 실행계획(XPLAN) | Oracle이 SQL을 어떤 순서로 처리했는지 보여주는 정보 |
| Buffer Gets | DB가 메모리에서 읽은 데이터 블록 수. 일반적으로 적을수록 DB 부하가 작다. |
| 전체 결과 비교 | 원본과 개선 SQL이 같은 데이터를 반환하는지 확인하는 작업 |
| 문의 코드 | 담당자가 상세 원인을 찾기 위한 영문 코드. 사용자가 해석할 필요는 없다. |
| Run ID | 한 번의 분석을 구분하는 번호. 문의할 때 반드시 함께 전달한다. |

### 내부 실행 경로 — 운영 담당자 참고

정식 실행 경로는 다음 하나뿐이다.

```text
Browser
  → OADT2 FastAPI thin proxy (/api/asta/*)
  → ADB ORDS / ASTA_PKG
  → allowlisted DB Link
  → Source DB ASTA_SOURCE_PKG
```

- 브라우저는 외부 ORDS 주소를 직접 호출하지 않는다.
- FastAPI는 요청 전달, 비동기 분석 조회, 최종 안전 검증 상태 정리를 담당한다. Python이 Source SQL, XPLAN, LLM, Advisor를 대신 실행하지 않는다.
- Source DB는 사용자가 선택하지 않으며 ADB의 `ASTA_SOURCE_CONNECTIONS` allowlist로 결정한다.
- DDL/DML, 인덱스·통계·SQL Profile·SQL Plan Baseline 생성, 운영 SQL 교체는 자동 수행하지 않는다.
- SQL Tuning Advisor 권고도 결과서 근거일 뿐 자동 적용하지 않는다.

## 2. 화면에서 분석 실행하기

1. OADT2의 **AI SQL Tuning Assistant** 확장 화면을 연다.
2. **AI Profile**을 선택한다. 화면은 `/api/asta/profiles`에서 이름이 `ASTA`로 시작하고 선택 가능한 profile을 불러오며, 조회 실패 시 내장 기본 목록을 사용한다.
3. **실행 유형**을 선택한다.
   - `OLTP`: 화면 조회처럼 빠른 응답과 낮은 DB 부하가 중요한 SQL
   - `BATCH`: 배치처럼 전체 작업 완료시간이 중요한 SQL
4. 직접 SQL을 입력하거나 **샘플 튜닝대상 SQL**을 선택한다. 샘플을 고르면 SQL과 해당 workload가 함께 반영된다.
5. 필요한 경우 **AI 참고사항**에 반드시 유지해야 하는 조건, 중점적으로 볼 테이블, 의심되는 느린 구간을 적는다. 실제 실행 결과와 참고사항이 다르면 실제 결과를 우선한다.
6. **AI 분석 실행**을 누른다. 버튼이 `분석중`으로 바뀌고 run이 제출된다.
7. 완료 후 결과서와 Run ID를 확인한다. 새 입력으로 돌아가려면 **신규분석(초기화)**, 원문 Markdown을 보관하려면 **보고서 다운로드**를 누른다.

입력 SQL의 마지막 세미콜론 하나는 화면이 자동 제거한다. 여러 SQL을 세미콜론으로 연결했거나 데이터를 변경하는 문장, `FOR UPDATE`가 포함된 경우에는 안전을 위해 실행하지 않는다.

### 현재 SQL Advisor 정책

일반 화면에서는 시간이 오래 걸릴 수 있는 Oracle 튜닝 권고 기능을 기본적으로 사용하지 않는다. 입력 카드에는 `Oracle 튜닝 권고: 사용 안 함`이 표시된다.

운영 담당자가 라이선스와 실행 시간을 확인한 뒤 API에서 별도로 켤 수 있지만, 일반 개발자가 설정할 필요는 없다.

## 3. 실행 유형별 개선 성공 기준

두 유형 모두 원본과 결과가 같고, 여러 번 실행해도 안정적이며, 실제 성능이 좋아야 개선 성공으로 표시한다.

### OLTP

- 주 지표: DB가 메모리에서 읽은 데이터 블록 수(Buffer Gets)
- 개선 SQL의 대표 실행시간: 3초 이하
- 후보가 원본보다 느린 경우: Buffer Gets가 20% 이상 줄고, 후보가 1초 이하이거나 elapsed 증가가 300ms 이하여야 채택 가능
- 후보가 원본보다 빠른 경우: Buffer Gets가 5% 이상 줄어야 채택 가능

### BATCH

- 주 지표: 전체 실행시간
- 원본과 결과가 같다는 확인을 마친 뒤 개선 SQL의 대표 실행시간이 원본보다 짧아야 한다.

원본과 개선 SQL은 준비 실행 1회와 성능 측정 3회를 수행한다. 실행시간 차이가 너무 크거나 측정이 빠지면 성능 개선을 확정하지 않는다.

## 4. 제공 샘플 SQL

`직접 입력` 외에 실제 고객 SQL로 최종 검증을 통과한 샘플 1개를 제공한다. 샘플 선택은 분석을 자동 시작하지 않는다.

화면 샘플은 단순히 개선 SQL이 만들어지거나 한 번 빨라졌다는 이유로 유지하지 않는다. 전체 결과 동일성, 실행계획 개선 의도, 반복 측정, 실행 유형별 기준을 모두 통과해 최종 결과가 `IMPROVED`인 SQL만 제공한다. 이전 02~15 샘플은 2026-07-06 실환경 재검증에서 이 최종 기준을 통과하지 못해 화면에서 제외했다.

| 번호 | 화면 이름 | 대표 패턴 |
|---:|---|---|
| 01 | SESL0640.selectList | 고객 회귀 SQL |

## 5. 화면의 진행 단계

| 번호 | 코드 | 의미 |
|---:|---|---|
| 1 | `REQUEST_RECEIVED` | 요청 수신 |
| 2 | `ORDS_DISPATCH` | 분석 서버 연결 |
| 3 | `SQL_GUARD` | 입력 SQL이 안전한 조회 문장인지 확인 |
| 4 | `BEFORE_EVIDENCE` | 원본 SQL의 실행시간·읽기량·실행계획 수집 |
| 5 | `SQL_TUNING_ADVISOR` | Oracle 튜닝 권고. 일반 화면에서는 사용 안 함 |
| 6 | `LLM_REWRITE` | AI가 개선 SQL 작성 |
| 7 | `AFTER_EVIDENCE` | 개선 SQL을 테스트하고 실행 정보 수집 |
| 8 | `BEFORE_AFTER_COMPARE` | 원본과 개선 SQL의 결과·성능 비교 |
| 9 | `VECTOR_KB` | 비슷한 튜닝 사례 검색 |
| 10 | `FINAL_REPORT` | 결과서 작성 |
| 11 | `VECTOR_SAVE` | 검증 결과 저장 |

화면에서는 `대기 중`, `진행 중`, `완료`, `확인 필요`로 상태를 표시한다. `확인 필요`가 나오면 원본 SQL은 변경되지 않은 상태다. 화면의 다음 행동을 읽고 Run ID를 보관한다.

영문 상태와 내부 단계 번호는 API 호환을 위해 유지한다. 내부 orchestration은 deterministic하며 `BEFORE_AFTER_COMPARE`, Vector, XPLAN 정보는 결과서 생성과 담당자 진단에 사용한다.

## 6. ASTA가 안전을 확인하는 순서

ASTA는 다음 순서로 확인한다. 앞 단계가 끝나지 않으면 성능 수치가 좋아 보여도 개선 성공으로 표시하지 않는다.

1. 느린 작업이 실제로 줄었는지 실행계획으로 확인
2. 원본과 개선 SQL이 같은 데이터와 같은 컬럼을 반환하는지 확인
3. 조건값이 달라져도 안전한지 확인
4. 여러 번 실행해도 성능이 안정적인지 확인
5. 모든 확인이 끝난 경우에만 개선 성공 결정

전체 결과 비교 방식은 다음과 같다.

- `ORDER BY`가 있으면 행 순서까지 비교한다.
- `ORDER BY`가 없으면 순서와 관계없이 비교하되 중복 행 개수는 그대로 확인한다.
- 컬럼 이름·순서·데이터 형식, NULL, 전체 행 수와 실제 값을 함께 확인한다.
- 일부 행만 확인한 경우에는 결과가 같다고 확정하지 않는다.

내부적으로는 위 절차를 deterministic fail-closed 방식으로 처리한다. 이는 “확실하지 않으면 적용하지 않는다”는 뜻이다.

## 7. 결과 메시지 읽기

| 화면 결과 | 의미 | 개발자가 할 일 |
|---|---|---|
| 개선 성공 (`IMPROVED`) | 결과가 같고 실제 성능이 좋아짐 | 개선 SQL을 코드 리뷰와 배포 절차에 따라 검토 |
| 성능 개선 없음 (`NOT_IMPROVED`) | 결과는 같지만 충분히 빨라지지 않음 | 원본 SQL 유지 |
| 개선 SQL 실행 실패 (`CANDIDATE_FAILED`) | 자동 생성 SQL에서 오류 발생 | 원본 SQL 유지, Run ID 전달 |
| 결과가 다름 (`NON_EQUIVALENT`) | 원본과 개선 SQL의 데이터 또는 컬럼이 다름 | 개선 SQL 사용 금지 |
| 개선안 없음 (`NO_REWRITE`) | 안전한 개선 SQL을 만들지 못함 | 참고사항을 보완하거나 원본 유지 |
| 확인 부족 (`INSUFFICIENT_EVIDENCE`) | 안전 또는 성능 확인이 끝나지 않음 | 원본 유지, 화면 안내에 따라 재시도 또는 문의 |

기술 결과 코드보다 화면의 **권장 행동**을 우선 읽는다. “현재 적용하지 마세요”가 표시되면 성능 수치가 좋아도 원본 SQL을 유지한다.

Advisor `FAILED`나 유사 Vector 사례 없음 자체는 후보 검증을 자동 성공·실패시키지 않는다. 최종 판단은 실행 근거와 gate 결과로 한다.

## 8. 결과서 사용법

결과 카드 헤더에는 Run ID, 현재 상태와 총 경과 시간, **맨 위**, **맨 아래**, **보고서 다운로드**, **신규분석(초기화)** 작업이 모인다.

결과서는 다음 5개 탭으로 나뉜다.

- **요약**: 결론, 병목 진단, 전후 수치 비교, Advisor 요약
- **튜닝 전**: 원본 SQL과 Before XPLAN
- **튜닝 후**: 후보 SQL과 After XPLAN. 후보가 생성됐지만 gate에서 차단된 경우에도 진단 근거로 표시될 수 있다.
- **상세 분석**: 사용자 참고사항 반영, 유사 사례, 적용 전 확인사항, 작업 이력
- **객체 정보**: SQL이 사용한 테이블과 인덱스 정보

탭은 클릭하거나 `←`/`→`, `Home`, `End` 키로 이동한다. 모바일에서는 탭 목록을 가로 스크롤할 수 있다. 지원하지 않는 Markdown 문법은 실행 가능한 HTML로 해석하지 않고 일반 텍스트로 표시한다.

**보고서 다운로드**는 화면에 표시된 내용을 Markdown 파일로 저장한다. SQL이 포함될 수 있으므로 회사가 승인한 위치에만 보관한다. 비밀번호, 토큰, 접속 문자열을 AI 참고사항이나 SQL 주석에 넣지 않는다.

## 9. 자주 보는 메시지와 해결 방법

화면은 쉬운 설명을 먼저 보여주고, 담당자 진단용 영문 코드는 **문의 코드**로 따로 표시한다. 문의 코드를 외울 필요는 없다.

| 화면 메시지 | 문의 코드 예 | 개발자가 할 일 |
|---|---|---|
| 후보 SQL 검증 시간이 초과되었습니다 | `CANDIDATE_RUNTIME_LIMIT` | 같은 테스트를 바로 반복하지 말고 Run ID를 담당자에게 전달한다. 원본 SQL은 변경되지 않았다. |
| 실행할 수 없는 SQL입니다 | `SQL_GUARD_REJECTED` | SELECT/WITH 한 문장인지 확인하고 데이터 변경 문장과 `FOR UPDATE`를 제거한다. |
| SQL 문법을 확인해 주세요 | `SQL_SYNTAX_ERROR` | 괄호, 쉼표, 별칭, JOIN 조건을 확인한다. |
| 컬럼이나 객체 이름을 찾을 수 없습니다 | `SQL_INVALID_IDENTIFIER` | 테이블 별칭과 컬럼명을 확인한다. |
| 테이블 또는 뷰를 찾을 수 없습니다 | `SOURCE_OBJECT_NOT_FOUND` | 객체명과 스키마명을 확인하고 계속되면 Run ID를 전달한다. |
| 조회 권한이 부족합니다 | `SOURCE_PRIVILEGE_DENIED` | Run ID와 객체명을 DB 담당자에게 전달한다. |
| 분석 대상 DB에 연결할 수 없습니다 | `SOURCE_DBLINK_UNAVAILABLE` | 잠시 후 다시 시도하고 계속되면 운영 담당자에게 문의한다. |
| 원본과 개선 SQL의 결과가 다릅니다 | `RESULT_DIGEST_MISMATCH` | 개선 SQL을 사용하지 않는다. |
| 결과 컬럼 구성이 다릅니다 | `RESULT_METADATA_MISMATCH` | 개선 SQL의 SELECT 컬럼명·순서·형식을 확인한다. |
| 전체 결과 비교가 필요합니다 | `FULL_RESULT_EVIDENCE_REQUIRED` | 원본 SQL을 유지하고 Run ID를 전달한다. |
| 입력값별 안전성을 충분히 확인하지 못했습니다 | `BIND_COVERAGE_INSUFFICIENT` | 자주 쓰는 조건값을 참고사항에 적어 다시 검증한다. |
| 성능 측정 횟수가 부족합니다 | `MEASUREMENT_EVIDENCE_INCOMPLETE` | 잠시 후 다시 실행한다. |
| 실행시간 변동이 너무 큽니다 | `MEASUREMENT_NOISE_TOO_HIGH` | DB 부하가 낮을 때 다시 실행한다. |

### Source DB에 `ASTA_RUN_ID ... FULLDIGEST` SQL이 보일 때

이 SQL은 원본과 개선 SQL이 같은 결과를 반환하는지 확인하는 ASTA 내부 작업이다. 결과 행을 비교 가능한 형태로 바꾸고 중복 행까지 확인한다. 데이터를 변경하지는 않지만 결과가 크거나 계산이 복잡하면 오래 걸릴 수 있다.

`후보 SQL 검증 시간이 초과되었습니다`가 함께 나타나면 같은 분석을 반복하지 않는다. 화면은 이미 실패로 보이더라도 Source DB의 결과 비교 작업이 잠시 계속될 수 있으므로 Run ID를 담당자에게 전달한다.

## 10. API 조회 — 연동 개발자 참고

same-origin 기본 경로는 다음과 같다.

| 용도 | Method | 경로 |
|---|---|---|
| 선택 가능한 ASTA profile | `GET` | `/api/asta/profiles` |
| 분석 제출 | `POST` | `/api/asta/analyze` |
| run 전체 조회 | `GET` | `/api/asta/runs/{run_id}` |
| 진행 상태 | `GET` | `/api/asta/runs/{run_id}/progress` |
| 결과서 JSON/Markdown | `GET` | `/api/asta/runs/{run_id}/report` |
| 안전한 HTML 결과서 | `GET` | `/api/asta/runs/{run_id}/report/view` |
| Markdown 다운로드 | `GET` | `/api/asta/runs/{run_id}/report/download` |

`POST /api/asta/analyze`는 분석을 한 번 제출하고 Run ID를 반환한다. 영문 상태와 문의 코드는 API 호환을 위해 유지한다. 사용자 화면에서는 이를 쉬운 한국어 메시지로 변환한다.

API에서 Advisor를 켜는 최소 예시는 다음과 같다. 일반 사용자 UI의 기본 정책은 계속 OFF다.

```json
{
  "sql": "SELECT ...",
  "tuning_context": {"workload_type": "OLTP"},
  "run_advisor": true
}
```

## 11. 문제가 생겼을 때

### 개발자가 먼저 확인할 것

1. 화면의 **무슨 일이 있었나요?**와 **다음 행동**을 읽는다.
2. 원본 SQL이 `SELECT` 또는 `WITH` 한 문장인지 확인한다.
3. 다시 실행하라는 안내가 있을 때만 한 번 다시 시도한다.
4. 해결되지 않으면 **문의 정보 복사**를 눌러 Run ID와 문의 코드를 담당자에게 전달한다.
5. 결과서에 `현재 적용하지 마세요`가 있으면 개선 SQL을 코드에 반영하지 않는다.

### 분석 서버 연결에서 오래 머물 때

Run ID를 복사하고 잠시 기다린다. 브라우저를 반복해서 새로 고치거나 같은 SQL을 여러 번 제출하지 않는다. 계속되면 운영 담당자에게 Run ID를 전달한다.

### 운영 담당자가 추가로 확인할 것

1. `/api/asta/runs/{run_id}/progress`에서 최초 실패 단계를 확인한다.
2. ADB `ASTA_SOURCE_CONNECTIONS`, DB Link, Source `ASTA_SOURCE_PKG` 상태를 확인한다.
3. 전체 결과 비교, 조건값별 검증, 반복 성능 측정 정보가 생성됐는지 확인한다.
4. 후보 timeout이면 ADB 작업뿐 아니라 Source의 `FULLCOUNT`/`FULLDIGEST` 실행이 남아 있는지도 확인한다.

### 화면에 확인 필요가 표시될 때

이는 프로그램 오류라는 뜻만은 아니다. 결과가 다르거나, 측정이 부족하거나, 안전 확인이 끝나지 않은 경우에도 원본을 보호하기 위해 표시된다. 성능 수치만 보고 개선 성공으로 바꾸지 않는다.

### 결과서 탭이 비어 있을 때

원문 Markdown의 heading이 결과서 계약과 일치하는지 확인한다. 중복되거나 알 수 없는 heading은 잘못된 탭 배치를 피하기 위해 자동 추측하지 않는다. `/report` 원문과 `/report/view`도 함께 대조한다.

## 12. 안전 수칙

- 인증정보, 토큰, DB 비밀번호, wallet, cookie를 SQL·참고사항·로그·결과서·인계 문서에 기록하지 않는다.
- 운영 반영 전 개선 SQL의 코드 리뷰, 영향 범위, 원복 방법을 승인받는다.
- Advisor, DB package 배포, ORDS 변경, 서비스 재시작, Source DB 변경은 사용자 또는 운영 승인 없이 수행하지 않는다.
- 배포 후에는 package `VALID`, `USER_ERRORS=0`, static asset cache version, `/profiles`, 제출, progress, report 조회를 순서대로 smoke test한다.
- 저장소 소스와 실행 서비스가 다를 수 있으므로 장애 진단 시 Run ID, 제공 중인 JS cache version, package 배포 시각을 함께 기록한다.

내부 코드와 상세 운영 계약이 필요한 담당자는 단일 기준 문서 `OADT2_ASTA_ARCHITECTURE.md`와 품질 자동화 문서 `ASTA_QUALITY_AGENT.md`를 참고한다.
