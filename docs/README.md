# OADT2 문서 안내

최종 업데이트: 2026-07-03

## ASTA canonical 요약

OADT2 ASTA는 `Browser → FastAPI thin proxy → ADB ORDS/ASTA_PKG → allowlisted DB Link → Source ASTA_SOURCE_PKG` 경로만 사용한다. Source direct와 Python runtime fallback은 금지한다.

11단계 번호는 기존 API 계약을 유지한다. 실제 evidence 수집/호출 순서는 `REQUEST_RECEIVED → ORDS_DISPATCH → SQL_GUARD → BEFORE_EVIDENCE → SQL_TUNING_ADVISOR → VECTOR_KB → LLM_REWRITE → AFTER_EVIDENCE → BEFORE_AFTER_COMPARE → VECTOR_SAVE → FINAL_REPORT`다. `LLM_REWRITE`는 full SQL과 compact XPLAN, 실행 통계, 객체정보, Advisor 상태, 유사사례 및 사용자 목표를 함께 받는다.

판정은 `IMPROVED`, `NOT_IMPROVED`, `CANDIDATE_FAILED`, `NON_EQUIVALENT`, `NO_REWRITE`, `INSUFFICIENT_EVIDENCE`다. 후보 없음/악화/비동등/실패는 원본 SQL을 유지한다. 후보가 있을 때만 After evidence를 표시하고 raw artifact와 visible report를 분리한다. 유사 결과서 링크는 `/api/asta/runs/{run_id}/report`다.

## 문서

- `OADT2_ASTA_ARCHITECTURE.md`: package/API/DB Link 경계와 새 수행 순서
- `AI_SQL_TUNING_ASSISTANT_PROGRAM_SPEC.md`: evidence-aware LLM 및 deterministic 판정 명세
- `AI_SQL_TUNING_ASSISTANT_MANUAL.md`: 사용자/운영 가이드

## 코드

- FastAPI thin proxy: `app/routers/asta_proxy.py`
- UI: `static/js/extensions/tuning_assistant.js`
- ADB: `db/adb/`
- Source helper: `db/source/asta_source_pkg.sql`
- ORDS: `db/ords/asta_ords_module.sql`
- 로컬 smoke: `tools/asta_smoke_adb.py`

정적 검증은 `uv run --with pytest pytest -q`와 `node --check static/js/extensions/tuning_assistant.js`를 사용한다. 실제 deploy/smoke는 별도 승인을 받은 환경에서만 수행한다.
