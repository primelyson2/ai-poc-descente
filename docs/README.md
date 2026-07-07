# OADT2 문서 안내

최종 업데이트: 2026-07-07

## ASTA canonical 요약

OADT2 ASTA는 `Browser → FastAPI thin proxy → ADB ORDS/ASTA_PKG → allowlisted DB Link → Source ASTA_SOURCE_PKG` 경로만 사용한다. Source direct와 Python runtime fallback은 금지한다.

11단계 번호는 기존 API 계약을 유지한다. 실제 evidence 수집/호출 순서는 `REQUEST_RECEIVED → ORDS_DISPATCH → SQL_GUARD → BEFORE_EVIDENCE → SQL_TUNING_ADVISOR → VECTOR_KB → LLM_REWRITE → AFTER_EVIDENCE → BEFORE_AFTER_COMPARE → VECTOR_SAVE → FINAL_REPORT`다. 제출은 `ASTA_PKG.SUBMIT_RUN → DBMS_SCHEDULER → ASTA_PKG.EXECUTE_RUN`으로 비동기 실행된다. `LLM_REWRITE`는 full SQL과 compact XPLAN, 실행 통계, 객체정보, Advisor 상태, 유사사례 및 사용자 목표를 함께 받는다.

판정은 `IMPROVED`, `NOT_IMPROVED`, `CANDIDATE_FAILED`, `NON_EQUIVALENT`, `NO_REWRITE`, `INSUFFICIENT_EVIDENCE`다. 후보 없음/악화/비동등/실패는 원본 SQL을 유지한다. 후보가 있을 때만 After evidence를 표시하고 raw artifact와 visible report를 분리한다. 유사 결과서 링크는 `/api/asta/runs/{run_id}/report`다. UI 결과서는 `요약 → 튜닝 전 → SQL 변경 → 튜닝 후 → 상세 분석 → 객체 정보` 6개 탭이며 진행 상세는 11단계 Drawer로 표시한다. **매뉴얼 및 사용설명** dialog에서는 PoC 샘플 화면, `OCI Load Balancer → VM`, DEV/PRO/shared 리소스와 단계별 package/procedure를 바로 확인할 수 있다.

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
