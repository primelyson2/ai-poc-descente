# AI SQL Tuning Assistant(ASTA) 프로그램 명세서

최종 업데이트: 2026-07-03

## 목적과 경계

ASTA는 Source DB 실측 evidence를 바탕으로 안전한 SQL 구조 재작성 후보를 검증하고 deterministic 결과서를 만든다. Browser는 FastAPI **thin proxy**를 통해 ADB ORDS를 호출한다. ADB `ASTA_PKG`가 canonical orchestration을 담당하고 Source 실행/XPLAN/Advisor는 allowlisted **DB Link**의 `ASTA_SOURCE_PKG`만 사용한다. Source direct 및 Python runtime fallback은 없다.

## 수행 계약

1. `REQUEST_RECEIVED`
2. `ORDS_DISPATCH`
3. `SQL_GUARD`
4. `BEFORE_EVIDENCE`
5. `SQL_TUNING_ADVISOR`
6. `LLM_REWRITE` (원본 SQL + compact Source/Vector evidence + 사용자 목표)
7. `AFTER_EVIDENCE` (후보가 있을 때만)
8. `BEFORE_AFTER_COMPARE` (ADB PL/SQL **deterministic**)
9. `VECTOR_KB` (LLM 호출 전 유사 사례 검색)
10. `FINAL_REPORT`
11. `VECTOR_SAVE`

단계 번호는 API 호환을 위해 유지하되 실제 orchestration은 `BEFORE_EVIDENCE → SQL_TUNING_ADVISOR → VECTOR_KB → LLM_REWRITE → AFTER_EVIDENCE → BEFORE_AFTER_COMPARE` 순서다. LLM에는 full SQL과 compact XPLAN, runtime metrics, object/index metadata, Advisor 상태, Vector 유사 사례 및 사용자 목표를 전달한다. 빈 모델 응답은 `NO_REWRITE`가 아니라 명시적 `FAILED / EMPTY_RESPONSE`로 기록한다.

## 판정 계약

| Verdict | 사용자 표시 | 채택 |
|---|---|---|
| `IMPROVED` | 개선 성공 | 후보 |
| `NOT_IMPROVED` | 개선실패 | 원본 |
| `CANDIDATE_FAILED` | 후보 실행 실패 | 원본 |
| `NON_EQUIVALENT` | 결과 불일치 | 원본 |
| `NO_REWRITE` | 개선 SQL 없음 | 원본 |
| `INSUFFICIENT_EVIDENCE` | 측정 불충분 | 원본 |

동등성 신호가 성능보다 먼저다. elapsed 악화는 Buffer/Disk 일부 개선과 관계없이 `NOT_IMPROVED`다. 짧은 OLTP SQL은 Buffer Gets가 중심 지표이며 Disk Reads도 별도 보존한다. Advisor `FAILED`나 Vector 결과 없음은 이후 보고서/저장을 막지 않는다.

Raw artifact에는 원본 SQL, Before XPLAN, Advisor, comparison을 보존한다. visible report는 raw dump와 분리하고 후보가 있을 때만 candidate/After를 표시한다. 보고서 결론과 comparison verdict는 일치해야 한다. Vector `report_ref`는 `/api/asta/runs/{run_id}/report`이며 사례는 참고 자료일 뿐 현재 판정 근거가 아니다.

## 공개 API/구현

- `POST /api/asta/analyze` → `ASTA_PKG.ANALYZE_SQL`
- `GET /api/asta/runs/{run_id}` → `ASTA_PKG.GET_RUN`
- `GET /api/asta/runs/{run_id}/progress` → `ASTA_PKG.GET_PROGRESS`
- `GET /api/asta/runs/{run_id}/report` → `ASTA_PKG.GET_REPORT`

패키지: `ASTA_SQL_GUARD_PKG`, `ASTA_SOURCE_BRIDGE_PKG`, `ASTA_VECTOR_PKG`, `ASTA_LLM_PKG`, `ASTA_REPORT_PKG`, `ASTA_PKG`. FastAPI는 SQL/LLM/Vector/비교/보고서 로직을 구현하지 않는다.
