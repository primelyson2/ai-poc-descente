# OADT2 ASTA 내부 아키텍처 및 수행 순서

최종 업데이트: 2026-06-30

## Canonical 경계

`Browser → FastAPI thin proxy → ADB ORDS → ASTA_PKG → ASTA_SOURCE_BRIDGE_PKG → allowlisted DB Link → Source ASTA_SOURCE_PKG`가 유일한 production 경로다. FastAPI/Python의 Source direct, SSH/subprocess 및 Python runtime fallback은 금지한다. SQL 실행, XPLAN, Advisor, LLM, Vector, 비교와 보고서는 ADB/Source PL/SQL 책임이다.

## 11단계

1. `REQUEST_RECEIVED`
2. `ORDS_DISPATCH`
3. `SQL_GUARD`
4. `BEFORE_EVIDENCE`
5. `SQL_TUNING_ADVISOR`
6. `LLM_REWRITE` — 원본 SQL과 고정 구조 재작성 지시만 넣는 **SQL-only** 호출
7. `AFTER_EVIDENCE` — 후보가 있을 때만 실행
8. `BEFORE_AFTER_COMPARE` — PL/SQL **deterministic** 판정
9. `VECTOR_KB` — 비교가 끝난 결과의 참고 사례 조회
10. `FINAL_REPORT`
11. `VECTOR_SAVE`

`LLM_REWRITE` 뒤에 `VECTOR_KB`가 위치한다. 과거 Vector-before-LLM 및 `LLM_FINAL_REVIEW` canonical 흐름은 deprecated이며 신규 run에 쓰지 않는다. 호환용 artifact의 final review는 `SKIPPED / DETERMINISTIC_COMPARISON`이다.

## 판정과 보고서

`ASTA_PKG.BUILD_COMPARISON_JSON`은 실행 성공, 결과 동등성, 동일 조건, `last_cr_buffer_gets`, `last_elapsed_time_us`, `last_disk_reads`, plan/output 신호 순으로 판정한다. OLTP는 Buffer Gets를 중심으로 보지만 elapsed 악화는 성공으로 승격하지 않는다.

- `IMPROVED`: 개선 성공
- `NOT_IMPROVED`: 개선실패(특히 elapsed 악화), 원본 유지
- `CANDIDATE_FAILED`: 후보 실행 실패, 원본 유지
- `NON_EQUIVALENT`: 결과 불일치, 원본 유지
- `NO_REWRITE`: 개선 SQL 없음
- `INSUFFICIENT_EVIDENCE`: 측정 불충분

원본 SQL, Before XPLAN, Advisor 상태는 raw artifact에 보존한다. 후보 SQL/After XPLAN은 후보가 있을 때만 표시한다. visible Markdown은 raw dump와 분리하며 comparison verdict와 같은 결론을 쓴다. Vector 사례는 근거가 아닌 참고이며 `report_ref`는 `/api/asta/runs/{run_id}/report` 내부 링크다.

현재 Vector KB 조회는 SQL fingerprint 기반 lookup이다. embedding 의미 유사도 검색 고도화는 별도 후속 범위이며, 현재 결과를 embedding 유사도 결과로 표시하지 않는다.

## 실제 API와 패키지

FastAPI thin proxy endpoint: `POST /api/asta/analyze`, `GET /api/asta/runs/{run_id}`, `GET /api/asta/runs/{run_id}/progress`, `GET /api/asta/runs/{run_id}/report`.

`POST /api/asta/analyze`는 더 이상 FastAPI background worker에서 장시간 ORDS 요청을 유지하지 않는다. ORDS의 `ASTA_PKG.SUBMIT_RUN`을 한 번 호출해 `QUEUED`와 `run_id`를 즉시 받고, ADB `DBMS_SCHEDULER`가 `ASTA_PKG.EXECUTE_RUN(run_id)`을 실행한다. `EXECUTE_RUN`은 `ASTA_RUNS.REQUEST_JSON`을 읽어 전체 11단계를 수행하며, MCP Server도 동일한 `SUBMIT_RUN → GET_PROGRESS → GET_REPORT` 계약을 사용한다. 동일 `idempotency_key`와 동일 요청은 기존 run을 반환하고, 다른 요청에 같은 key를 재사용하면 `IDEMPOTENCY_CONFLICT`로 거절한다.

ADB compile 순서: `ASTA_SQL_GUARD_PKG → ASTA_SOURCE_BRIDGE_PKG → ASTA_VECTOR_PKG → ASTA_LLM_PKG → ASTA_REPORT_PKG → ASTA_PKG`. 기존 설치에는 패키지 컴파일 전에 `db/asta/005_asta_async_run_columns.sql`을 적용해야 하며, ASTA schema에는 Scheduler Job 생성·실행 권한이 필요하다.
