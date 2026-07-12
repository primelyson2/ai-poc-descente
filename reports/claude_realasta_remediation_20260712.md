# Real ASTA remediation 완료 보고서 — 2026-07-12

## 결론

Claude Opus 세션 중단 후 남은 누적 변경을 reset/checkout/clean/stash/revert 없이 보존해 독립 검토했다. ORDS History/Input SQL, 사용자 7단계 진행 Drawer, 보고서/LLM 정책, 테스트 실행 경로를 정합화했고 전체 회귀와 Real ASTA 반영을 완료했다.

## 코드·계약 검토

- 최초 재검증: 루트에서 `uv run --with pytest pytest -q`가 `508 passed`였다. skip/xfail/테스트 삭제로 실패를 숨긴 흔적은 없었다.
- ORDS 신규 `history`, `runs/:run_id/input-sql` handler를 각각 분리해 GET, package 호출, JSON MIME, `no-store`, `no-cache`, `nosniff`, CLOB 2,000자 chunk loop를 개별 검증하도록 계약을 강화했다.
- `progressDrawerSteps()`의 내부 준비 3단계 묶음과 사용자 `1~7` 순서가 실제 Node 실행 테스트에서 일치한다.
- `pyproject.toml`의 pytest `pythonpath=["."]`로 README 명령을 환경변수 없이 그대로 실행할 수 있다.
- 독립 보안 리뷰에서 History 검색어가 FastAPI→ORDS HTTP header로 넘어가기 전 제어문자를 제거하지 않던 경계를 발견했다. 실패 테스트를 먼저 확인한 뒤 C0/DEL 문자를 공백으로 접어 header injection/invalid header를 방지했다.

## 최종 테스트

- Python 전체: `510 passed in 1.36s`.
- JS 실행: `asta_llm_trace_render_test`, `asta_progress_sequence_test`, `asta_progress_time_test`, `asta_report_tabs_dom_test` 모두 PASS.
- 문법/정적: 관련 JS `node --check`, Python `compileall`, `git diff --check` 통과.
- skip/xfail 추가 없음. assertion 완화나 실패 테스트 삭제 없음.

## Real ASTA 배포

- 배포 전/후 active Scheduler job, QUEUED/RUNNING run, RUNNING progress 모두 0.
- workspace와 운영 executable source 비교 후 `ASTA_LLM_PKG → ASTA_REPORT_PKG → ASTA_PKG`만 백업·반영했다.
- 세 package spec/body 6개 모두 workspace source와 일치, `VALID`, `USER_ERRORS=0`.
- ORDS는 이미 8개 route가 배포돼 있었고 History/Input SQL handler, `no-store`, CLOB 계약이 workspace와 일치해 불필요한 재배포를 하지 않았다.
- package backup과 배포 요약: `reports/claude_realasta_remediation/20260712T141611Z/deploy_summary.json`.
- DB 변경, 신규 tuning run, Source package, schema migration은 수행하지 않았다.

## 인증 API/UI smoke

- 기존 terminal run 하나만 사용했다. 신규 분석은 제출하지 않았다.
- 인증 login, History 검색, Input SQL lazy-load가 HTTP 200이고 History는 SQL preview만, Input SQL endpoint는 저장 원문과 일치했다.
- 브라우저 경계의 `no-store`와 `nosniff`, 실제 제공 `Tuning History` 메뉴/검색/Input SQL JS 자산을 확인했다.
- SQL 원문, credential, cookie, access key는 artifact에 저장하지 않았다.
- 최종 증거: `reports/claude_realasta_remediation/20260712T142135Z/authenticated_history_input_sql_smoke.json`.
- 서버에 Chromium 계열 브라우저가 없어 실제 브라우저 클릭 자동화는 불가능했다. 대신 실제 제공 정적 자산과 인증 API를 검증하고 Node DOM/행동 테스트를 통과시켰다.

## 런타임

- FastAPI 검색 header 보안 수정 반영을 위해 `select-ai-test.service`를 한 번 재시작했다.
- 최종 service는 active, Uvicorn은 `0.0.0.0:8000` listening, application startup 및 두 DB pool ready를 확인했다.

## Git 상태

- Real ASTA remediation을 단일 로컬 커밋으로 기록했다.
- `origin/ASTA` push는 remote가 HTTPS username/password를 요구하지만 이 VM에 credential helper, GitHub CLI, outbound SSH key, GitHub token 환경변수가 없어 인증 전에 차단됐다. 코드·배포 문제가 아니며 GitHub 인증 제공 후 `git push origin ASTA`만 남는다.
