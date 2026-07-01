# AI SQL Tuning Assistant 사용자·운영 매뉴얼

최종 업데이트: 2026-06-30

## 사용법

SQL과 ASTA profile/Advisor 옵션을 선택해 분석한다. UI는 FastAPI **thin proxy**를 통해 ADB ORDS로 요청한다. Source DB evidence는 ADB에서 allowlisted **DB Link**로만 수집하며 Source direct/Python fallback은 없다.

## 화면의 11단계

1. `REQUEST_RECEIVED`
2. `ORDS_DISPATCH`
3. `SQL_GUARD`
4. `BEFORE_EVIDENCE`
5. `SQL_TUNING_ADVISOR`
6. `LLM_REWRITE` — **SQL-only** 구조 재작성
7. `AFTER_EVIDENCE` — 후보 SQL이 있을 때만
8. `BEFORE_AFTER_COMPARE` — **deterministic** 비교
9. `VECTOR_KB` — 검증 뒤 참고 사례 조회
10. `FINAL_REPORT`
11. `VECTOR_SAVE`

`LLM_REWRITE` 후 `VECTOR_KB` 순서다. 과거 `LLM_FINAL_REVIEW` 표시는 deprecated run 조회 호환용일 뿐 신규 판정을 만들지 않는다.

## 결과 읽기

- `IMPROVED` / 개선 성공: 동등하고 실측 개선
- `NOT_IMPROVED` / 개선실패: elapsed 악화 또는 개선 없음, 원본 유지
- `CANDIDATE_FAILED` / 후보 실행 실패: 원본 유지
- `NON_EQUIVALENT` / 결과 불일치: 원본 유지
- `NO_REWRITE` / 개선 SQL 없음: After 단계는 SKIPPED
- `INSUFFICIENT_EVIDENCE` / 측정 불충분

OLTP에서는 Buffer Gets를 중심으로 읽되 elapsed 악화는 성공이 아니다. Disk Reads는 물리 I/O 영향 판단에 사용한다. Advisor가 `FAILED`여도 후속 단계는 계속된다. 유사 사례가 없을 수 있으며, 있으면 `/api/asta/runs/{run_id}/report` 형태 `report_ref`를 참고 링크로 제공한다.

Raw artifact와 visible report는 분리된다. 원본/Before XPLAN/Advisor 상태는 보존되고 후보가 있을 때만 후보 SQL과 After XPLAN이 보인다. 보고서 문구는 comparison verdict와 일치해야 한다.

## 조회/장애 확인

- 분석: `POST /api/asta/analyze`
- run: `GET /api/asta/runs/{run_id}`
- progress: `GET /api/asta/runs/{run_id}/progress`
- 결과서: `GET /api/asta/runs/{run_id}/report`

실패 시 `ASTA_SOURCE_CONNECTIONS`, DB Link, Source `ASTA_SOURCE_PKG`, ADB package 상태를 확인한다. Password, wallet, credential은 로그/보고서에 출력하지 않는다. DDL, 인덱스, 통계, SQL Profile/Baseline, 운영 SQL 교체는 자동 수행하지 않는다.
