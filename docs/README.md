# OADT2 문서 안내

최종 업데이트: 2026-07-10

## ASTA canonical 요약

OADT2 ASTA는 `Browser → FastAPI thin proxy → ADB ORDS/ASTA_PKG → allowlisted DB Link → Source ASTA_SOURCE_PKG` 경로만 사용한다. Source direct와 Python runtime fallback은 금지한다.

내부 API는 `REQUEST_RECEIVED → ORDS_DISPATCH → SQL_GUARD → BEFORE_EVIDENCE → LLM_REWRITE → AFTER_EVIDENCE → BEFORE_AFTER_COMPARE → FINAL_REPORT → VECTOR_SAVE`의 9개 progress code를 유지한다. 사용자 진행 Drawer와 화면 매뉴얼은 앞의 접수·연결·Guard를 1번 `요청 및 분석 준비`로 묶고 나머지를 연속 재번호화해 `1~7`로 표시한다. 사용자 3단계에서 후보 SQL이 생성되면 이후 검증이 끝나기 전에도 전체 SQL을 보여 주며, 이는 검증 중 후보이지 적용 권고가 아니다. 제출은 `ASTA_PKG.SUBMIT_RUN → DBMS_SCHEDULER → ASTA_PKG.EXECUTE_RUN`으로 비동기 실행된다. raw Vector 검색 결과는 prompt에 넣지 않고 artifact에 `vector_evidence_included=false`로 기록한다. Source SQL을 실제 실행한 경우에만 같은 workload의 `POSITIVE_VERIFIED` 사례를 SQL 원문 없이 change summary·전후 지표·fingerprint 상태로 축약해 two-stage prompt의 참고 패턴으로 제공하고 `verified_history_references_included` 및 `verified_history_reference_summary`를 남긴다. 결과서는 실제로 추가한 안전 지시와 사례 요약을 표시한다. 현재 SQL/XPLAN이 독립적으로 구조·key·consumer를 증명해야 하며 과거 SQL의 identifier/literal/predicate 복사나 과거 사례만의 채택은 금지한다. 후보 생성은 SQL·XPLAN·실제 컬럼 dictionary·workload·사용자 목표를 사용하고, 검증된 동일 SQL history가 있으면 `VERIFIED_HISTORY_REUSE`로 먼저 재검증할 수 있다.

comparison verdict는 `IMPROVED`, `ANALYSIS_ONLY`, `NOT_IMPROVED`, `CANDIDATE_FAILED`, `NON_EQUIVALENT`, `NO_REWRITE`, `INSUFFICIENT_EVIDENCE`다. `ANALYSIS_ONLY / ESTIMATED_PLAN_ONLY / SOURCE_SQL_NOT_EXECUTED`는 `execute_source_sql=false`의 정상 미실행 분석 완료이며 `source_runtime_metrics_status=NOT_MEASURED`, `runtime_verification_status=NOT_EXECUTED`, `equivalence_status=NOT_EVALUATED`, `repeat_performance_status=NOT_MEASURED`다. `PLAN_SCREEN_*`는 사용자 4단계 후보 선별 reason이고 `CANDIDATE_RUNTIME_LIMIT`은 Run `error_code`다. 후보 없음/악화/비동등/실패는 원본 SQL을 유지한다. Vector는 `IMPROVED → POSITIVE_VERIFIED`, `ANALYSIS_ONLY → ANALYSIS_OBSERVATION`, 나머지 → `REJECTED_OBSERVATION`으로 분리한다. UI 결과서는 6개 탭이며 진행 상세는 연속 7단계 Drawer로 표시한다. **매뉴얼 및 사용설명**에는 ASTA 콘셉트와 역할을 요약한 소개, 아키텍처, 분석 Workflow, 개발자 실행 추적 네 탭이 있다.

결과서의 병목 진단은 원본 evidence와 지배 operation의 위치·key·consumer·실측값, 변경 전략과 semantic risk를 상세히 표시한다. 유사 개선 사례 섹션은 프롬프트 반영 여부와 관계없이 항상 검토 결과를 작성한다. 단계 상태와 timing은 진행 Drawer에서 제공하므로 결과서에는 작업 수행 이력과 단계별 수행 체크를 중복 표시하지 않는다.

## 문서

- `OADT2_ASTA_ARCHITECTURE.md`: package/API/DB Link 경계, 실행 순서, evidence-aware LLM과 deterministic 판정을 합친 단일 기준 명세
- `AI_SQL_TUNING_ASSISTANT_MANUAL.md`: 사용자/운영 가이드
- `asta_source_execution_flow.md`: 현재 Scheduler/DB Link/Source 함수 단위 실행 추적

## 코드

- FastAPI thin proxy: `app/routers/asta_proxy.py`
- UI: `static/js/extensions/tuning_assistant.js`
- ADB: `db/adb/`
- Source helper: `db/source/asta_source_pkg.sql`
- ORDS: `db/ords/asta_ords_module.sql`
- 로컬 smoke: `tools/asta_smoke_adb.py`

정적 검증은 현재 저장소의 offline pytest 환경과 `node --check static/js/extensions/tuning_assistant.js`, `node --check static/js/extensions/asta_report_tabs.js`를 사용한다. 2026-07-06 실환경 반영 이력 이후에도 실제 deploy/smoke는 별도 승인을 받은 환경에서만 수행한다.

## 개발자 실행 추적

### 플랫폼별 역할과 실제 코드

UI 팝업의 **04 개발자 실행 추적**에서 브라우저, FastAPI, ORDS, Target ADB, Source DB, AI/LLM별 실제 파일과 함수/package를 확인한다. 상세 기준은 `asta_source_execution_flow.md` 16절이다.

### 버튼 클릭부터 보고서 다운로드까지

`POST /api/asta/analyze → ASTA_PKG.SUBMIT_RUN/EXECUTE_RUN/RUN_PIPELINE → Source 원본 evidence → Vector artifact → verified history 또는 LLM 후보 → Source 후보 evidence → BUILD_COMPARISON_JSON → ASTA_VECTOR_PKG.SAVE_CASE → ASTA_REPORT_PKG.BUILD_REPORT → UI poll/render/download` 순서다. 기본은 `ESTIMATED_PLAN_ONLY` 미실행 evidence이고, **소스 DB에서 SQL을 실제 실행하여 검증** 체크박스 opt-in에서만 Source runtime 실측으로 진행한다.

### 실패·차단·원본 유지 분기

`ANALYSIS_ONLY`는 미실행 분석 완료라 실패가 아니며, 후보 적용 전 Source 실측·동등성 검증이 필요하다. `IMPROVED`를 제외한 guard 거절, 후보 없음/실패, 비동등, 근거 부족, 성능 미달은 원본을 유지한다. 어떤 분기도 운영 SQL을 자동 변경하지 않는다.

### Run ID로 추적하는 방법

먼저 `/api/asta/runs/{run_id}/progress`의 단계와 `llm_calls` 요약을 확인한다. 필요한 한 호출만 `/api/asta/runs/{run_id}/llm-calls/{call_id}`로 보고, terminal이면 `/api/asta/runs/{run_id}/report`를 조회한다. 이후 sanitized API audit, `ASTA_RUNS`/`ASTA_RUN_PROGRESS`/`ASTA_LLM_CALL_LOG`, 해당 Scheduler job과 Source marker 순서로 확인한다. **보고서 다운로드** 버튼은 브라우저 `downloadText`이며 서버에는 `/report/view`, `/report/download`도 있다. credential과 SQL/bind 원문은 진단 기록에 넣지 않는다.
