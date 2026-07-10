# OADT2 문서 안내

최종 업데이트: 2026-07-08

## ASTA canonical 요약

OADT2 ASTA는 `Browser → FastAPI thin proxy → ADB ORDS/ASTA_PKG → allowlisted DB Link → Source ASTA_SOURCE_PKG` 경로만 사용한다. Source direct와 Python runtime fallback은 금지한다.

11단계 번호는 기존 API 계약을 유지한다. 실제 evidence 수집/호출 순서는 `REQUEST_RECEIVED → ORDS_DISPATCH → SQL_GUARD → BEFORE_EVIDENCE → SQL_TUNING_ADVISOR → VECTOR_KB → LLM_REWRITE → AFTER_EVIDENCE → BEFORE_AFTER_COMPARE → VECTOR_SAVE → FINAL_REPORT`다. 제출은 `ASTA_PKG.SUBMIT_RUN → DBMS_SCHEDULER → ASTA_PKG.EXECUTE_RUN`으로 비동기 실행된다. `LLM_REWRITE`는 full SQL과 compact XPLAN, 실행 통계, 객체정보, Advisor 상태, 유사사례 및 사용자 목표를 함께 받는다.

판정은 `IMPROVED`, `ANALYSIS_ONLY`, `NOT_IMPROVED`, `CANDIDATE_FAILED`, `NON_EQUIVALENT`, `NO_REWRITE`, `INSUFFICIENT_EVIDENCE`다. `ANALYSIS_ONLY`는 `execute_source_sql=false`의 정상 미실행 분석 완료이며 성능 개선 성공/실패가 아니다. 후보 없음/악화/비동등/실패는 원본 SQL을 유지한다. 후보가 있을 때만 After evidence를 표시하고 raw artifact와 visible report를 분리한다. 유사 결과서 링크는 `/api/asta/runs/{run_id}/report`다. UI 결과서는 `요약 → 튜닝 전 → SQL 변경 → 튜닝 후 → 상세 분석 → 객체 정보` 6개 탭이며 진행 상세는 11단계 Drawer로 표시한다. **매뉴얼 및 사용설명** dialog에서는 PoC 샘플 화면, `OCI Load Balancer → VM`, DEV/PRO/shared 리소스와 단계별 package/procedure를 바로 확인할 수 있다.

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

UI 팝업의 **03 개발자 실행 추적**에서 브라우저, FastAPI, ORDS, Target ADB, Source DB, AI/LLM별 실제 파일과 함수/package를 확인한다. 상세 기준은 `asta_source_execution_flow.md` 16절이다.

### 버튼 클릭부터 보고서 다운로드까지

`POST /api/asta/analyze → ASTA_PKG.SUBMIT_RUN/EXECUTE_RUN/RUN_PIPELINE → Source 원본·후보 evidence → LLM 후보 → BUILD_COMPARISON_JSON → ASTA_REPORT_PKG.BUILD_REPORT → UI poll/render/download` 순서다. 기본은 `ESTIMATED_PLAN_ONLY` 미실행 evidence이고, 체크박스 opt-in에서만 Source runtime 실측으로 진행한다.

### 실패·차단·원본 유지 분기

`ANALYSIS_ONLY`는 미실행 분석 완료라 실패가 아니며, 후보 적용 전 Source 실측·동등성 검증이 필요하다. `IMPROVED`를 제외한 guard 거절, 후보 없음/실패, 비동등, 근거 부족, 성능 미달은 원본을 유지한다. 어떤 분기도 운영 SQL을 자동 변경하지 않는다.

### Run ID로 추적하는 방법

먼저 `/progress`와 report를 조회하고 sanitized API audit, `ASTA_RUNS`/`ASTA_RUN_PROGRESS`/`ASTA_LLM_CALL_LOG`, 해당 Scheduler job과 Source marker 순서로 확인한다. credential과 SQL/bind 원문은 진단 기록에 넣지 않는다.
