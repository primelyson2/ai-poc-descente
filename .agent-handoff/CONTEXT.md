# Real ASTA 작업 인계

## 작업 트리 변경 Git 커밋 — 2026-07-10

- 요청/결론: 사용자가 요청한 현재 작업 트리 변경 전체를 단일 Git 커밋으로 반영했다. 기존 변경을 되돌리거나 제외하지 않았다.
- 변경 파일: ASTA ADB/Source/ORDS package, UI, 문서, 테스트 및 이 handoff를 포함한 현재 worktree 전체.
- 검증: 커밋 직전 `git diff --check` 통과. 새 기능 테스트는 이번 Git 반영 작업에서 별도 실행하지 않았으며, 이전 구현·배포 검증 결과는 아래 항목을 참조한다.
- 통합: `origin/ASTA`의 VPD/Select AI 보안 작업 기준점 `2a36f64` 위로 충돌 없이 rebase했다. 이 작업 트리는 해당 원격 변경과 ASTA 변경을 함께 포함한다.
- 관련 커밋: 이 handoff를 포함한 현재 브랜치의 최신 커밋.

## GPT5.4 fallback 우선순위 상향 — 2026-07-10 ADB 배포 완료

- 요청/결론: SQL 생성 실패 시 성능이 좋은 LLM을 먼저 쓰는 방향이 맞고, 현재 관찰상 `ASTA_GPT54_PROFILE`이 가장 좋아 보인다는 사용자 의견을 반영했다. 기본 primary profile은 그대로 두고, 실패 fallback resolver에서 GPT5.4를 첫 번째 fallback으로 우선 선택하도록 수정하고 Real ASTA ADB에 배포했다.
- 변경: `ASTA_LLM_PKG.available_fallback_profile`의 우선순위를 `GPT5.4 → Grok Reasoning → Grok GenAI → Gemini → GPT5.2 → GPT5.1 → mini/nano`로 조정했다. 호출자가 이미 GPT5.4를 primary로 쓴 경우에는 기존 로직대로 GPT5.4를 제외하고 다음 fallback을 고른다. 존재하지 않는 profile은 계속 `USER_CLOUD_AI_PROFILES` 기반으로 제외된다.
- 변경 파일: `db/adb/asta_llm_pkg.sql`, `tests/test_asta_llm_candidate_recovery.py`, 이 handoff.
- 검증: `tests/test_asta_llm_candidate_recovery.py tests/test_asta_ords_migration_contract.py` 결과 `25 passed`; `git diff --check` 통과.
- 배포: 사용자 승인 후 active Run/Scheduler/running progress 0건에서 `ASTA_LLM_PKG` spec/body를 백업 후 컴파일했다. PACKAGE/PACKAGE BODY 모두 `VALID`, `USER_ERRORS=0`, 배포 후 active Run/job/progress 0건이다.
- 배포 smoke: 원격 `USER_SOURCE`에서 `available_fallback_profile` 내 GPT5.4 우선순위가 Grok Reasoning/Grok GenAI/Gemini보다 앞선 것을 확인했다. `USER_CLOUD_AI_PROFILES`에는 `ASTA_GPT54_PROFILE`이 존재하고 legacy `ASTA_DB_GENAI_TEST`는 없다.
- artifact: `reports/asta_gpt54_fallback_deploy/20260709T151529Z/`에 배포 전 spec/body 백업, backup manifest, `deploy_summary.json`을 보존했다. SQL 원문, credential, LLM prompt/response는 저장하지 않았다.
- 미수행: 외부 LLM 호출, 신규 Run 실행, 서비스 재시작, commit/push는 수행하지 않았다.
- 관련 커밋: 없음.

## OLTP 3초 hard guard 제거 — 2026-07-09 ADB/UI 배포 완료

- 요청/결론: `OADT2-ASTA-2388a8ae9aa040ed9ef97133d855881f`는 후보가 실제로 빨라졌는데도 `NOT_IMPROVED`로 표시됐다. 저장 comparison은 `PLAN_SCREEN_OLTP_LATENCY_TARGET_NOT_MET`였고, 원본 elapsed `139,709,652us`, 후보 PLAN screen elapsed `3,863,987us`, Buffer Gets `9,323,247 → 1,086,788`였다. 즉 3초 hard guard 하나 때문에 전체 검증 전에 탈락한 것이 원인이다.
- 정책 변경: `ASTA_PKG.build_comparison_json`에서 OLTP `l_after_elapsed > 3000000` absolute latency 탈락과 `oltp_latency_target_us/oltp_latency_target_met` JSON 출력을 제거했다. 후보가 원본보다 빠르고 Buffer Gets가 5% 이상 줄면 3초를 넘어도 `IMPROVED`가 될 수 있다. 후보가 원본보다 느려진 경우의 1초/300ms tradeoff 제한은 유지했다.
- Stage 7 선별 변경: `candidate_plan_screen_reason`에서 `PLAN_SCREEN_OLTP_LATENCY_TARGET_NOT_MET` 반환을 제거했다. PLAN_ONLY screen은 Source 오류, metric 누락, optimizer intent, Buffer Gets 5% 개선 여부만 보고 다음 FULL_RESULT 검증으로 넘긴다.
- 보고서/UI: `ASTA_REPORT_PKG`의 별도 PLAN_SCREEN 3초 초과 추천문을 제거하고 일반 PLAN_SCREEN 문구로 처리한다. 화면 OLTP 설명은 “Buffer Reads 우선, 후보가 원본보다 느려지는 경우에만 1초/300ms tradeoff 제한”으로 변경했고 cache-buster는 `tuning_assistant.js?v=20260709_no_3s_latency1`이다.
- 변경 파일: `db/adb/asta_pkg.sql`, `db/adb/asta_report_pkg.sql`, `static/js/extensions/tuning_assistant.js`, `static/index.html`, `docs/AI_SQL_TUNING_ASSISTANT_MANUAL.md`, `docs/OADT2_ASTA_ARCHITECTURE.md`, 관련 테스트와 이 handoff. 기존 dirty worktree는 보존했다.
- 로컬 검증: 직접 관련 `49 passed`; 전체 `476 passed, 기존 기준선 8 failed in 1.49s`, 신규 실패 0건. `node --check` 2개 JS와 `git diff --check` 통과.
- 배포: 사용자 승인에 따라 active Run/Scheduler/running progress 0건에서 `ASTA_REPORT_PKG`, `ASTA_PKG` spec/body를 백업 후 컴파일했다. 두 package의 PACKAGE/PACKAGE BODY 모두 `VALID`, `USER_ERRORS=0`, 배포 후 active Run/job/progress 0건이다.
- 배포 smoke: 원격 `USER_SOURCE`에서 comparison/screen 모두 3초 elapsed guard와 `OLTP_LATENCY_TARGET_NOT_MET` 신규 생성 marker가 없고 Buffer Gets gate는 유지됨을 확인했다. 실행 서비스 `/`는 새 cache URL을 참조하며 제공 `tuning_assistant.js`는 workspace와 236,703 bytes로 byte-identical이다.
- artifact: `reports/asta_no_3s_latency_guard_deploy/20260709T143905Z/`에 백업 manifest와 `deploy_summary.json`을 보존했다. 기존 2388 저장 row/report는 갱신하지 않았다. SQL 원문, credential, LLM prompt/response는 저장하지 않았다.
- 관련 커밋: 없음.

## Run e81056 후보 복구 경로 보강 — 2026-07-09 ADB 배포 완료

- 요청/결론: e81056에서 유일한 생성 후보가 ORA-25156 precheck로 탈락하고, 두 모델은 NO_REWRITE, 마지막 하드코딩 profile은 미존재해 후보가 0건이 된 문제를 줄이도록 후보 생성 복구 경로 3개를 구현하고 Real ASTA ADB에 배포했다. 외부 LLM 호출과 신규 분석 Run 실행은 수행하지 않았다.
- 동적 fallback: `ASTA_DB_GENAI_TEST` 하드코딩을 제거했다. `ASTA_LLM_PKG.available_fallback_profile`이 `USER_CLOUD_AI_PROFILES`에 실제 존재하는 ASTA profile만 우선순위(Grok Reasoning/GenAI, Gemini, GPT-5.4/5.2/5.1/mini/nano)로 선택하며 없는 ordinal은 호출하지 않는다. diagnosis/candidate/repair 모두 이 resolver를 사용한다.
- guard repair: Stage 2 후보가 `assert_candidate_compatible`에서 ORA-25156 등 구조 안전 검사에 실패하면 후보와 정확한 오류, Source column dictionary를 `REPAIR_SQL`에 전달해 내부 repair round를 한 번 수행한다. 성공 후보는 `candidate_source=GUARD_REPAIR`, artifact에 `guard_repair_attempted=true`를 남긴다. repair 내부 provider fallback도 실제 존재 profile만 사용한다.
- 검증 이력 재사용: `ASTA_PKG.verified_history_candidate`가 동일 Source DB/workload, 원본 CLOB 길이+내용 완전 일치, 과거 `IMPROVED`, optimizer intent `VERIFIED`, result scope `FULL_RESULT`, equivalence `VERIFIED`, measurement `ACCEPTED`를 모두 만족하는 최신 후보만 가져온다. 후보 Guard를 다시 통과해야 하며 현재 Run과 원본 동일 SQL은 제외한다. validation candidate 다음, 새 LLM 호출 전에 `VERIFIED_HISTORY_REUSE`로 사용하고 progress에 원본 Run ID를 남긴다.
- 안전 계약: history 재사용 후보도 기존 Stage 7 예상 Plan/PLAN_ONLY/전체 검증 흐름을 그대로 거친다. API top-level `candidate_sql`은 여전히 최종 `IMPROVED` 채택 SQL만 노출하고 ANALYSIS_ONLY에서는 성능·동등성 미검증 상태를 유지한다.
- 변경 파일: `db/adb/asta_llm_pkg.sql`, `db/adb/asta_pkg.sql`, 신규 `tests/test_asta_llm_candidate_recovery.py`, `tests/test_asta_ords_migration_contract.py`, 이 handoff. 기존 dirty worktree는 보존했다.
- 로컬 검증: 2026-07-09 재확인 결과 candidate recovery/ORDS migration/annotation/linear scanner/column dictionary 관련 `61 passed`; 전체 `476 passed, 기존 기준선 8 failed in 1.49s`, 신규 실패 0건. `node --check` 2개 JS와 `git diff --check` 통과.
- 배포: 사용자 승인 후 precheck에서 활성 `ASTA_RUNS`/Scheduler/running progress 0건을 확인했다. `ASTA_LLM_PKG`, `ASTA_PKG` spec/body를 백업하고 두 package를 순서대로 컴파일했다. 최종 두 package의 PACKAGE/PACKAGE BODY 모두 `VALID`, `USER_ERRORS=0`, 배포 후 활성 Run/job/progress 0건이다.
- 배포 smoke: 원격 `USER_SOURCE` marker 9건(`available_fallback_profile`, `user_cloud_ai_profiles`, legacy `ASTA_DB_GENAI_TEST` 부재, guard repair, `GUARD_REPAIR`, source evidence 전달, `verified_history_candidate`, `VERIFIED_HISTORY_REUSE`, `candidate_source`)을 확인했다. `USER_CLOUD_AI_PROFILES`에는 ASTA profile 8개가 있고 `ASTA_DB_GENAI_TEST`는 0건이며 `ASTA_PKG.LIST_PROFILES` 응답에도 legacy profile이 없다.
- artifact: `reports/asta_candidate_recovery_deploy/20260709T141703Z/`에 백업 manifest와 `deploy_summary.json`을 보존했다. credential, SQL 원문, LLM prompt/response는 저장하지 않았다.
- 관련 커밋: 없음.

## Run e81056 개선 SQL 미생성 진단 — 2026-07-09

- 대상 `OADT2-ASTA-e81056213d5d4caaab11bb00eaffba65`; ADB Run/Progress/LLM audit/결과서를 읽기 전용으로 대조했다. 코드·DB·배포 상태는 변경하지 않았다.
- 실행 모드: `ANALYSIS_ONLY / ESTIMATED_PLAN_ONLY / SOURCE_SQL_NOT_EXECUTED`, `source_sql_executed=false`. 원본 SQL을 실행하지 않아 A-Time, Buffer Gets, Starts, elapsed, result equivalence 실측이 없었다. 진단 LLM도 `반복 작업 식별 불가`, `dominant repeated-work operation 확정 불가`, target_operations 빈 배열을 반환했다.
- 후보 시도: 1차 `ASTA_GROK_REASONING_PROFILE`은 `NO_REWRITE`; 2차 `ASTA_GROK_GENAI_PROFILE`은 18,291자 SQL을 생성했지만 ANSI JOIN과 구식 `(+)`를 혼용해 `ASTA_SQL_GUARD` ORA-25156 precheck에서 차단; 3차 `ASTA_GEMINI_PROFILE`은 `NO_REWRITE`; 4차 `ASTA_DB_GENAI_TEST`는 존재하지 않는 profile이라 `ORA-20046`으로 즉시 실패했다.
- 최종: 유효 후보가 0건이라 `NO_REWRITE / No structural rewrite candidate`, AFTER_EVIDENCE와 비교는 SKIPPED, tuned_sql null이다. 직접 원인은 유일한 생성 후보의 구조 안전성 실패이며, 실측 없는 estimated plan에서 두 모델이 fail-closed한 점과 존재하지 않는 하드코딩 fallback이 성공 가능성을 더 낮췄다.
- 권장 조치: fallback을 실제 ENABLED profile에서 동적으로 구성하고 `ASTA_DB_GENAI_TEST`를 제거/교체한다. candidate guard 실패도 analysis-only에서 오류를 포함한 REPAIR_SQL로 1회 보정한다. 동일 SQL의 과거 검증 후보가 있으면 새 생성 전에 fingerprint 기반 재사용 후보로 제시하되 ANALYSIS_ONLY에서는 성능·동등성 미검증 표시는 유지한다.
- 관련 커밋: 없음.

## Source 미실행 ANALYSIS_ONLY 운영 배포 완료 — 2026-07-09

- 요청/결론: 사용자가 이전 precheck의 stale `RUNNING` 3건 종료 처리를 명시 승인했고, 이후 `ANALYSIS_ONLY` 변경을 Real ASTA ADB에 배포했다. ORDS/Source package/service restart/commit/push는 수행하지 않았다.
- stale cleanup: `ASTA_PKG` public subprogram metadata에는 `SUBMIT_RUN`, `EXECUTE_RUN`, `ENFORCE_CANDIDATE_TIMEOUT`, `ANALYZE_SQL`, `LIST_PROFILES`, `GET_RUN`, `GET_PROGRESS`, `GET_LLM_CALL`, `GET_REPORT`만 있었고 일반 cancel/cleanup API는 없었다. `ENFORCE_CANDIDATE_TIMEOUT`은 reason이 `CANDIDATE_TIMEOUT`인 timeout API라 stale cleanup에 사용하지 않았다. 이전 precheck의 정확한 3건만 `FAILED / STALE_ORPHAN_CLEANUP`으로 최소 갱신했다. 영향은 `ASTA_RUNS` 3행, `ASTA_RUN_PROGRESS` 0행, Scheduler job drop 0건이다. SQL 원문/request/response/report는 갱신하거나 artifact에 저장하지 않았다.
- stale 대상: `OADT2-ASTA-fad861d08a98493b95afdd0c2e570e46`, `OADT2-ASTA-5edea6e6cd3f4a53949fefda0459e105`, `OADT2-ASTA-7eef2527f0b249c2a9cb4f48d1fa9fcc`. 관련 Scheduler job은 존재하지 않았고 running job도 0건이었다. cleanup 후 활성 Run/job/progress는 모두 0건이다.
- 배포 전/백업: predeploy 활성 Run/job/progress 0건을 확인했다. `ASTA_VECTOR_PKG`, `ASTA_REPORT_PKG`, `ASTA_PKG`의 spec/body를 `reports/asta_analysis_only_deploy/20260709T094134Z/backup/`에 분리 백업했다. DBMS_METADATA의 PACKAGE DDL이 spec 뒤에 body까지 붙는 현상을 감지해 `PACKAGE BODY` 헤더 기준으로 강제 분리했고, 6개 백업 모두 kind 검증과 SHA-256 기록을 통과했다.
- 배포: 의존 순서 `ASTA_VECTOR_PKG -> ASTA_REPORT_PKG -> ASTA_PKG`로 workspace SQL을 컴파일했다. 최종 6개 객체 PACKAGE/PACKAGE BODY 모두 VALID, `USER_ERRORS=0`, rollback 수행 없음. USER_SOURCE marker는 `ANALYSIS_ONLY`, `ESTIMATED_PLAN_ONLY`, `SOURCE_SQL_NOT_EXECUTED`, `source_runtime_metrics_status`, `runtime_verification_status`, `튜닝 후보 제안/분석 완료`, `확보된 근거`, `미확보 근거`, `미측정`, `ANALYSIS_OBSERVATION`, `ANALYSIS_SCOPE`, `observation_reason` 모두 존재한다.
- smoke: 외부 LLM 호출과 Source 업무 SQL 실행 없이 합성 JSON으로 `ASTA_REPORT_PKG.BUILD_REPORT`/`BUILD_RESPONSE_JSON`를 호출했다. 결과는 `analysis_mode=ESTIMATED_PLAN_ONLY`, `execution_mode=SOURCE_SQL_NOT_EXECUTED`, `source_sql_executed=false`, `runtime_verification_status=NOT_EXECUTED`, comparison `verdict=ANALYSIS_ONLY`, `source_runtime_metrics_status=NOT_MEASURED`, `equivalence_status=NOT_EVALUATED`, 측정 metric null이다. 보고서는 결론/확보된 근거/미확보 근거/미측정 문구를 모두 포함했다.
- Vector smoke: savepoint 이후 `ASTA_VECTOR_PKG.SAVE_CASE`를 호출해 `learning_class=ANALYSIS_OBSERVATION`, `observation_reason=ESTIMATED_PLAN_ONLY_RUNTIME_NOT_EXECUTED`, `rejection_reason=null`을 확인했다. insert row는 savepoint rollback으로 제거되어 `rows_after_rollback=0`이다.
- HTTP/UI: same-origin login/profile API 200, `/` cache marker 2개 확인, `tuning_assistant.js`와 `asta_report_tabs.js` 모두 HTTP 제공 파일이 workspace 파일과 byte-identical이다. JS에는 `ANALYSIS_ONLY`와 미실행 분석 mode badge/guide marker가 존재한다.
- 사후 상태: 활성 Run/job/progress 0건, 3개 package 6개 객체 VALID, USER_ERRORS 0. `select-ai-test.service`는 active이고 uvicorn은 0.0.0.0:8000 listen 중이다. 서비스 재시작 없음.
- artifact: 전체 비민감 배포 기록은 `reports/asta_analysis_only_deploy/20260709T094134Z/`에 있다. 주요 파일은 `stale_cleanup_summary.json`, `backup_manifest.json`, `deploy_summary.json`, `smoke_summary.json`, `http_verification.json`, `post_status.json`, `service_status.json`이다. credential, 업무 SQL 원문, LLM prompt/response는 저장하지 않았다.

## Source 미실행 ANALYSIS_ONLY 운영 배포 보류 — 2026-07-09

- 요청/결론: 사용자가 `ANALYSIS_ONLY` 변경의 Real ASTA 운영 배포를 승인했으나, 배포 전 안전 precheck에서 `ASTA_RUNS.status='RUNNING'` 3건이 확인되어 사용자 지정 절차에 따라 배포를 보류했다. Scheduler running job은 0건, running progress는 0건이지만 “활성 Run·job 0건” 조건을 충족하지 못했다.
- 활성 Run: `OADT2-ASTA-fad861d08a98493b95afdd0c2e570e46`(2026-07-03 13:25:50), `OADT2-ASTA-5edea6e6cd3f4a53949fefda0459e105`(2026-07-04 09:33:39), `OADT2-ASTA-7eef2527f0b249c2a9cb4f48d1fa9fcc`(2026-07-04 13:10:47)이 `RUNNING` 상태다. 관련 Scheduler job은 현재 실행 중이 아니다.
- 현재 DB 상태: ADB 접속 user는 `ASTA`. `ASTA_PKG`, `ASTA_REPORT_PKG`, `ASTA_VECTOR_PKG`의 PACKAGE/PACKAGE BODY는 모두 VALID이고 `USER_ERRORS=0`이다.
- 수행/미수행: precheck만 수행했다. package spec/body 백업, workspace SQL 컴파일, rollback, smoke, ORDS/Source/service 변경은 전혀 수행하지 않았다. 기존 Run row/report도 수정하지 않았다. 외부 LLM 호출, Source 업무 SQL 실행, commit/push 없음.
- artifact: `reports/asta_analysis_only_deploy/20260709T094134Z/precheck.json`에 비민감 precheck 결과만 저장했다. SQL 원문·credential·LLM prompt/response는 저장하지 않았다.
- 서비스 상태: `select-ai-test.service`는 active이고 `uvicorn` PID 1355243이 0.0.0.0:8000에서 listen 중이다. 재시작은 수행하지 않았다.
- 다음 단계: 위 3개 `RUNNING` row를 stale orphan으로 볼지, 별도 정리/상태 변경 승인을 받을지 결정해야 배포를 재개할 수 있다. 현재 사용자 절차 기준으로는 활성 Run 0건이 아니므로 배포를 진행하면 안 된다.

## Source 미실행 ANALYSIS_ONLY 계약/API/UI/보고서 정합성 — 2026-07-09 로컬 완료, 배포 안 함

- 요청/결론: 직전 timeout 이후 작업을 이어서 `execute_source_sql=false` 후보 생성 경로를 실패/개선실패가 아닌 정상 분석 전용 모드로 완성했다. 후보와 예상 Plan이 생성되지만 Source DB에서 원본·후보 SQL을 실행하지 않은 경우 verdict는 `ANALYSIS_ONLY`, analysis_mode는 `ESTIMATED_PLAN_ONLY`, execution_mode는 `SOURCE_SQL_NOT_EXECUTED`가 된다. 성능 개선 여부와 결과 동등성은 미검증으로 표시한다.
- ADB 계약: `ASTA_PKG`의 미실행 후보 비교 JSON이 `NOT_IMPROVED` 대신 `ANALYSIS_ONLY`를 반환한다. Source runtime metrics, Before/After 실제 XPLAN, result equivalence, 반복 성능 상태는 각각 `NOT_MEASURED`/`NOT_AVAILABLE`/`NOT_EVALUATED` 등으로 분리했고 수치 metric은 null로 둔다. 실측 ON의 기존 PLAN_ONLY/비교 판정 흐름은 그대로 유지한다.
- API/보고서: `ASTA_REPORT_PKG.BUILD_RESPONSE_JSON`는 top-level `analysis_mode`, `execution_mode`, `source_sql_executed`, `runtime_verification_status`를 반환한다. Markdown 결론은 “튜닝 후보 제안/분석 완료, 성능 개선 여부 미검증”으로 표시하고, 확보된 근거와 미확보 근거를 분리한다. 미측정 metric은 0/추정치가 아니라 `미측정`/N/A 의미로 출력한다.
- UI/다운로드: `tuning_assistant.js`는 `isEstimatedPlanAnalysisOnly`로 미실행 분석 모드를 감지하고 성공 흐름으로 처리하되, mode badge와 한국어 안내문으로 성능·동등성 미검증을 표시한다. 미실행 분석 toast는 별도 문구를 사용하고, 기존 실측 성공 toast 계약도 유지했다. `asta_report_tabs.js`의 verdict guide/download 파싱에도 `ANALYSIS_ONLY`를 추가했다.
- Vector/문서: `ASTA_VECTOR_PKG`는 `ANALYSIS_ONLY`를 검증 성공 사례가 아닌 `ANALYSIS_OBSERVATION`으로 저장한다. 사용자/개발자 문서와 source execution flow, architecture 문서에 두 모드의 근거 차이와 `ANALYSIS_ONLY` 의미를 반영했다.
- 변경 파일: 이번 보완의 핵심은 `db/adb/asta_pkg.sql`, `db/adb/asta_report_pkg.sql`, `db/adb/asta_vector_pkg.sql`, `static/js/extensions/tuning_assistant.js`, `static/js/extensions/asta_report_tabs.js`, `docs/AI_SQL_TUNING_ASSISTANT_MANUAL.md`, `docs/README.md`, `docs/asta_source_execution_flow.md`, `docs/OADT2_ASTA_ARCHITECTURE.md`, `tests/test_asta_estimated_plan_safe_mode.py`, `tests/js/asta_report_tabs_dom_test.cjs`, `tests/test_asta_developer_manual_contract.py`, `tests/test_asta_adb_ords_static_contracts.py`, 이 handoff다. 기존 dirty worktree와 사용자가 만든 누적 변경은 되돌리지 않았다.
- TDD/검증: 신규 계약 RED를 먼저 확인했다. 이후 선별 `tests/test_asta_phase8_ui_vector_contract.py tests/test_asta_estimated_plan_safe_mode.py`는 `15 passed`; 관련 묶음은 `90 passed`; Node는 `node --check static/js/extensions/tuning_assistant.js`, `node --check static/js/extensions/asta_report_tabs.js`, `node tests/js/asta_report_tabs_dom_test.cjs`, `node tests/js/asta_llm_trace_render_test.cjs` 모두 통과했다. `git diff --check` 통과.
- 전체 회귀: `PYTHONPATH=/home/opc/.cache/uv/archive-v0/uV3M1hTXKn5DvRqO/lib/python3.11/site-packages .venv/bin/python -m pytest -q` 결과 `472 passed, 기존 기준선 8 failed in 1.47s`. 실패는 기존 handoff와 같은 정적 계약 4, proxy 2, workload 2이며 이번 `ANALYSIS_ONLY`/UI 신규 실패는 없다.
- HTTP 정적 제공: 서비스 재시작 없이 `http://127.0.0.1:8000/static/js/extensions/tuning_assistant.js`와 `asta_report_tabs.js`를 받아 workspace 파일과 `cmp -s` byte equality를 확인했다. 크기는 각각 236,605 bytes, 24,342 bytes로 로컬/HTTP가 동일하다.
- 배포/커밋: 사용자 지시에 따라 DB package, ORDS, 서비스 재시작, commit/push는 수행하지 않았다. 운영 반영에는 ADB package/ORDS 및 정적 자산 배포 승인이 별도로 필요하다.

## Source 미실행 + 튜닝 후보 생성 결과서 문구 정합성 — 2026-07-09 ADB 배포 완료

- 요청/결론: `OADT2-ASTA-b70c843cbda04836ad0d5e6ebb912285`는 LLM 튜닝 후보와 원본/후보 예상 Plan이 생성됐지만 Source DB에서 두 SQL 모두 실행하지 않았다. 기존 결과서의 “성능이 충분히 좋아지지 않음”, “Buffer Gets 증가”, “Before/After 실제 실행 결과” 표현은 evidence 범위와 맞지 않아 예상 Plan 안전 모드 전용 문구로 수정했다.
- 결과서 변경: 후보가 있으면 “튜닝 후보 SQL 생성 / 실제 성능·결과 동등성·채택 여부 미판정”으로 결론을 표시한다. 실행시간·Buffer Gets·Disk Reads는 `미측정`으로 표시하고, 병목은 `EXPLAIN PLAN 기반 예상 병목`으로 한정한다. 후보 SQL 제목/주의문, 과거 유사 사례, DBA 검토, 작업 수행 이력도 원본·후보 SQL 미실행과 예상 Plan 수집 사실에 맞췄다.
- 단계 표: 안전 모드에서는 4단계를 `원본 SQL/예상 Plan`, 7단계를 `후보 SQL/예상 Plan`, 8단계를 `예상 Plan 범위 비교`로 표시한다. `DONE`은 EXPLAIN PLAN/evidence 단계 완료일 뿐 업무 SQL 실행 완료가 아님을 명시한다. 실제 PLAN_ONLY/전체 실행 결과서 분기는 유지했다.
- 변경 파일: `db/adb/asta_report_pkg.sql`, `tests/test_asta_estimated_plan_safe_mode.py`, `tests/test_claude_review_regressions.py`, 이 handoff. 기존 dirty worktree와 동시 작업 변경은 보존했다.
- 검증: 결과서/안전 모드 관련 선별 `30 passed`; 전체 `470 passed, 기존 8 failed in 1.48s`, 신규 실패 0. 기존 실패는 정적 계약 4, proxy 2, workload 계약 2이며 이번 변경과 무관하다. `git diff --check` 통과.
- 배포: 사용자 승인 후 활성 ASTA Scheduler 0건에서 기존 `ASTA_REPORT_PKG` spec/body를 분리 백업하고 수정본을 컴파일했다. PACKAGE/PACKAGE BODY 모두 VALID, `USER_ERRORS=0`, 배포 marker 2건이며 배포 후 활성 job도 0건이다.
- b70 smoke: 저장된 source/LLM/after/comparison artifact로 결과서를 메모리에서 재생성했다. `source_sql_executed=false`, `plan_kind=ESTIMATED`, `screen_mode=ESTIMATED_PLAN`, `equivalence=NOT_EVALUATED`를 확인했다. 새 후보 생성 결론, 실행시간/Buffer Gets 미측정, 예상 병목, 후보 SQL/예상 Plan, 유사 사례 범위, 단계 표, 잘못된 “성능 미개선” 문구 부재 등 15개 검증이 모두 통과했다.
- 배포 artifact: `reports/asta_estimated_candidate_report_deploy/20260709T074830Z/`에 배포 전 spec/body와 비민감 요약을 보존했다. 기존 b70의 저장 결과서(`ASTA_RUNS.DETAILED_REPORT_MD`)는 배포 전후 길이/hash가 동일하며 갱신하지 않았다. 신규 Run부터 새 문구가 적용된다. 기존 b70 저장 결과서를 바꾸려면 별도 데이터 변경 승인이 필요하다. 서비스/ORDS/외부 LLM/commit/push 변경 없음.

## LLM 실제 컬럼 dictionary 전달 — 2026-07-09 Source/ADB 배포 완료

- 요청/결론: Run 98e의 `TGP_STYDE_L.BRAND_CD` 같은 base-table identifier hallucination을 줄이기 위해 deterministic lineage validator는 추가하지 않고 실제 Source column dictionary를 Stage 2 후보 생성과 ORA repair prompt에 전달하도록 구현했다.
- Source: `collect_estimated_object_info`가 예상 Plan의 TABLE ACCESS 객체마다 `DBA_TAB_COLUMNS`에서 최대 120개 컬럼을 `column_name/data_type/nullable/column_id`로 수집해 `object_info.table_stats[*].columns`에 포함한다. SQL은 실행하지 않으며 기존 통계·인덱스 수집은 유지한다.
- ADB LLM: 신규 `compact_column_dictionary`가 Source object_info를 `owner/table_name/columns`만 남긴 JSON으로 축약한다. 통계·인덱스는 제외하고 최대 30개 테이블/총 600개 컬럼으로 제한한다. Stage 2에는 listed table에서 dictionary에 있는 column만 사용하고 유사 테이블의 correlation key를 복사하지 말라는 계약과 함께 전달한다.
- Repair: `repair_sql_candidate`에 optional `p_source_evidence_json`을 추가하고 두 repair 호출 모두 `l_source_json`을 전달한다. repair prompt에도 동일 dictionary를 넣어 ORA-00904 식별자를 원본 SQL과 실제 컬럼 목록으로만 수정하도록 했다.
- 변경 파일: `db/source/asta_source_pkg.sql`, `db/adb/asta_llm_pkg.sql`, `db/adb/asta_pkg.sql`, 신규 `tests/test_asta_llm_column_dictionary_prompt.py`, 이 handoff. 기존 dirty worktree와 동시 작업 변경은 보존했다.
- 검증: 신규 dictionary 계약 4건 포함 관련 `81 passed`, 전체 `469 passed, 기존 8 failed in 1.48s`, 신규 실패 0. 기존 실패는 정적 계약 4, proxy 2, workload 2이며 이번 변경과 무관하다. `git diff --check` 통과.
- Source 배포: 사용자 승인 후 ORCLAI 저장 연결에서 기존 `ASTA_SOURCE_PKG` spec/body를 분리 백업하고 수정본을 컴파일했다. PACKAGE/PACKAGE BODY 모두 VALID, USER_ERRORS=0, estimated column limit marker 1건이다. 첫 smoke는 index-only plan이라 TABLE ACCESS object_info가 비어 실패했지만 package는 VALID였다. 이어 ADB→DB Link `FULL` hint 예상 Plan smoke가 `COMPLETED / ESTIMATED / source_sql_executed=false`로 성공했다.
- Source dictionary smoke: `DSNT.TGP_STYDE_L`를 대상 테이블로 확인했고 27개 컬럼을 반환했다. `COMP_CD`, `STYLE_CD`, `FIRS_IN_DE`, `USE_YN`이 존재하고 `BRAND_CD`는 존재하지 않았다. 업무 SELECT는 실행하지 않았고 EXPLAIN PLAN만 수행했다.
- ADB 배포: 기존 `ASTA_LLM_PKG`와 `ASTA_PKG` spec/body를 분리 백업한 뒤 두 package를 연속 컴파일했다. 4개 PACKAGE/PACKAGE BODY가 모두 VALID, USER_ERRORS=0이다. dictionary helper 1, Stage 2/repair prompt 2, nested columns 1, source evidence parameter 4, pipeline source evidence 전달 8 marker를 확인했고 기존 LLM trace API marker 2도 보존했다. 배포 전후 활성 ASTA Scheduler job은 0건이다.
- 배포 artifact: `reports/asta_column_dictionary_deploy/20260709T070313Z/`에 Source/ADB 백업, 로그, 배포 요약, bridge smoke, 최종 검증 JSON을 보존했다. 외부 LLM 재호출, 서비스/ORDS/업무 데이터 변경, commit/push는 수행하지 않았다.

## 분석 진행상태 LLM prompt/응답 추적 UI — 2026-07-09 배포 완료

- 요청/결론: 분석 진행상태 6단계에서 LLM에게 어떤 prompt를 보냈고 어떤 응답을 받았는지 확인할 수 있도록 구현했다. 호출 목록은 실시간 요약만 polling하고, 원문은 사용자가 버튼을 누른 한 호출만 lazy-load하며 prompt/응답 블록은 기본 접힘이다.
- ADB `ASTA_PKG`: `GET_PROGRESS`에 `llm_calls` 요약 배열을 추가했다. `ASTA_LLM_CALL_LOG`의 call_id/stage/attempt/profile/SENT·RECEIVED·FAILED/prompt·response 문자 수/error code/timing만 반환하며 CLOB 원문은 넣지 않는다. 새 `GET_LLM_CALL(run_id, call_id)`은 두 식별자를 함께 조건으로 정확한 prompt/response 한 건만 반환하고 운영 SQL·XPLAN 민감도 marker를 포함한다.
- ORDS/FastAPI: `GET runs/:run_id/llm-calls/:call_id` handler와 same-origin `/api/asta/runs/{run_id}/llm-calls/{call_id}` proxy를 추가했다. FastAPI 전역 auth 보호를 거치며 legacy in-memory snapshot이 원문 조회를 가로채지 않고 authoritative ADB row만 조회한다. ORDS 응답은 기존 no-store/nosniff/runtime-boundary header와 CLOB chunking을 유지한다.
- UI: 6단계 상세에 DIAGNOSIS/CANDIDATE_SQL/REPAIR_SQL별 attempt, profile, 상태, 문자 수, 실시간 elapsed를 표시한다. **Prompt·응답 원문 보기**를 눌러야 API를 호출하며, 원문 경고·기본 접힘·개별 복사를 제공한다. polling 중 elapsed만 바뀔 때 loaded 원문 DOM을 보존하고, SENT→RECEIVED처럼 응답 metadata가 바뀌면 stale cache를 폐기한다. cache version은 `20260709_llm_trace1`이다.
- 문서/테스트: 사용자 매뉴얼, architecture/source flow, ADB README 및 ORDS/header/cache 계약 테스트를 갱신했다. 신규 Node 렌더 테스트 `tests/js/asta_llm_trace_render_test.cjs`는 summary에 원문이 섞이지 않음, lazy control, HTML escape와 기본 접힘을 검증한다.
- 검증: 관련 선별 `25 passed`, progress 전체 `17 passed`, Node PASS, `node --check`, Python `py_compile`, `git diff --check` 통과. 전체 `465 passed, 기존 계열 8 failed in 1.47s`; 실패는 기존 ADB smoke/report/error 계약 4, proxy error-return 기대 2, workload 계약 2이며 이번 LLM trace 신규 실패는 없다.
- ADB/ORDS 배포: 활성 ASTA Scheduler 0건에서 기존 `ASTA_PKG`와 ORDS metadata를 백업하고 새 `ASTA_PKG` 및 `asta.v1` module을 배포했다. 최종 package spec/body 모두 VALID, `USER_ERRORS=0`, 배포 marker 존재, ORDS module 1개/template 6개/handler 6개, 활성 job 0건이다. 성공 artifact는 `reports/asta_llm_trace_deploy/20260709T064656Z/`이며 package 백업, ORDS metadata, raw SQL/prompt/응답을 제외한 deploy/HTTP 요약을 보존한다.
- DB/API smoke: 기존 Run의 `GET_PROGRESS`에서 LLM 호출 요약 5건을 반환하면서 raw prompt/response key가 없음을 확인했다. 선택한 `REPAIR_SQL / RECEIVED` 호출은 prompt 38,581자와 응답 18,330자의 저장 길이가 일치했고 sensitivity marker가 존재했다. 같은 call ID를 다른 Run ID로 조회하면 `LLM_CALL_NOT_FOUND`였다. 원문은 artifact/로그/응답 요약에 기록하지 않았다.
- 웹 배포: systemd restart는 interactive authentication으로 실패했다. HUP 종료가 정상 종료로 분류돼 unit이 inactive가 된 뒤 `sudo -n systemctl start select-ai-test.service`로 즉시 복구했고, 새 PID `1355243`, startup complete, HTTP GET 200을 확인했다. 인증된 same-origin smoke에서 새 cache version/JS marker, progress 5건, lazy 원문 길이, no-store, cross-run 차단을 모두 통과했다. HTTP 요약은 성공 artifact의 `http_verification.json`이다.
- 배포 중 복구 기록: 첫 artifact `reports/asta_llm_trace_deploy/20260709T064501Z/`에서는 새 package가 VALID였으나 smoke의 집계형 최신-call 선택 SQL이 `ORA-00935`로 실패했다. 자동 rollback이 DBMS_METADATA spec/body 구분을 잘못 처리해 package가 잠시 INVALID가 됐지만, 즉시 현재 검증본을 재컴파일해 spec/body VALID·오류 0건으로 복구했다. 이 첫 시도에서는 ORDS를 변경하지 않았다. smoke SQL을 단순 call_id 정렬로, 백업을 spec/body 분리 검증 방식으로 고친 뒤 두 번째 배포가 성공했다.
- 변경 파일: `db/adb/asta_pkg.sql`, `db/ords/asta_ords_module.sql`, `app/routers/asta_proxy.py`, `static/js/extensions/tuning_assistant.js`, `static/index.html`, ADB README/문서 3개, 관련 테스트와 신규 Node 테스트, 이 handoff. 기존 다른 작업의 미커밋 변경을 보존했다.
- 남은 문제/다음 단계: 기능 배포와 API/UI 자산 smoke는 완료됐다. 실제 사용자는 새 분석 또는 기존 Run의 진행 상세 6단계를 열고 호출별 원문 버튼을 사용할 수 있다. 커밋/push는 수행하지 않았다.

## Run 98e 후보 ORA-00904 원인 — LLM의 이종 테이블 키 대칭화 오류 — 2026-07-09

- 대상 `OADT2-ASTA-98e18cc469234d618297c65b522d50fb`을 ADB에서 읽기 전용 진단했다. Run은 COMPLETED지만 7단계 AFTER_EVIDENCE가 83,534ms 후 `ORA-00904: "BRAND_CD": invalid identifier`, 비교는 `CANDIDATE_FAILED`, 원본 유지다. 실제 Source SQL은 실행하지 않았고 예상 Plan parse에서 차단됐다.
- 새 annotation 정규화 배포는 정상 적용됐다. Grok 2차가 18,241자 후보를 생성했고 SQL Guard를 통과했으며 Source parse 단계까지 도달했다. 이전 ORA-06502/annotation 손상은 재발하지 않았다.
- 정확한 모델 오류: 후보가 `FIRS_IN` helper의 `DSNT.TGP_STYDE_L` SELECT/GROUP BY에 `BRAND_CD`를 추가했다. Source `DBA_TAB_COLUMNS` 대조 결과 TGP_STYDE_L에는 `COMP_CD`, `STYLE_CD`, `FIRS_IN_DE`, `USE_YN`은 있지만 `BRAND_CD`가 없다. 반면 함께 재작성한 `FIRS_OUT` 원천 `DSNT.TSE_DIV_L`에는 BRAND_CD가 있다. 모델이 유사한 두 correlated MIN을 GROUPING SETS helper로 대칭화하면서 TSE_DIV_L의 correlation key를 TGP_STYDE_L에도 복사한 것이다.
- 왜 prompt만으로 막히지 않았나: SQL-only Stage 1/2는 source evidence에서 `plan_text`만 추출해 SQL/XPLAN을 모델에 제공하며 `object_info`의 실제 column dictionary는 전달하지 않는다. 프롬프트에 “identifier를 만들지 말라”는 규칙은 있지만 Oracle parser/schema resolver가 아니라 생성 모델의 자기검사에 의존하므로 18K 장문 SQL과 유사 패턴에서 이 규칙을 위반했다.
- 자동 repair도 2회 호출됐지만 두 응답 모두 TGP_STYDE_L 주변 BRAND_CD를 유지했고, 추가로 ASTA annotation을 leading header에 두지 않아 Guard에서 거절됐다. 따라서 ORA-00904의 실질적 수정 후보가 만들어지지 않았다.
- 일반화된 개선 방향: (1) Stage 2와 repair prompt에 해당 object의 실제 column dictionary를 bounded JSON으로 포함, (2) 후보의 새 alias.column과 CTE projection을 deterministic lineage validator로 검사, (3) ORA-00904 repair에 오류 식별자의 실제 소유 object/available columns를 전달해야 한다. 이번 요청은 원인 질문으로 처리해 코드/package/Run/Source DB/서비스는 변경하지 않았다. 외부 LLM 재호출 없음.

## LLM prompt/응답 조회 및 진행상태 노출 현황 — 2026-07-09

- 현재 ADB는 Run별 모든 LLM 호출을 `ASTA_LLM_CALL_LOG`에 autonomous transaction으로 저장한다. 저장 항목은 `DIAGNOSIS`, `CANDIDATE_SQL`, `REPAIR_SQL`별 attempt/profile/status, 정확한 `prompt_clob`/`response_clob`, 문자 수, 오류, 시작/완료 시각이다.
- 호출은 `DBMS_CLOUD_AI.GENERATE(... action=>'chat')`이며, 1단계 DIAGNOSIS에는 원본 SQL·전체 XPLAN·사용자 참고사항을, 2단계 CANDIDATE_SQL에는 diagnosis·원본 SQL·전체 XPLAN·구조/의미 보존 규칙을 전달한다. 후보 Oracle 오류 시 REPAIR_SQL은 원본·실패 후보·ORA 오류를 전달한다.
- 현재 `/runs/{run_id}/progress`는 `ASTA_RUN_PROGRESS`의 6단계 `LLM_REWRITE` RUNNING/DONE과 timing/detail만 반환하고 `ASTA_LLM_CALL_LOG`는 반환하지 않는다. UI 상세 Drawer도 이 단계 수준 로그만 표시한다. 최종 report API의 `artifacts.llm`에는 diagnosis/최종 raw response/candidate/profile error가 일부 보존되지만 prompt 원문과 attempt 전체 이력은 없다.
- 진행상태에 표시하는 것은 가능하다. `GET_PROGRESS`에 해당 Run의 call-log 요약 배열을 추가하면 현재 1초 polling으로 DIAGNOSIS/CANDIDATE/REPAIR별 attempt/profile/SENT·RECEIVED·FAILED/문자 수/소요시간을 실시간 표시할 수 있다. prompt/response 원문은 운영 SQL·XPLAN을 포함하므로 기본 접힘, 권한 제한, lazy chunk 조회 및 민감정보 보호가 필요하다.
- 이번 요청은 현황 진단만 수행했다. 코드/DB/package/service 변경 없음.

## Run 51ea 개선 SQL 미표시 — 정규화 주석 수정·ADB 배포 완료 — 2026-07-09

- 대상 `OADT2-ASTA-51ea54dd30ff4a949a891178c6392a7d`를 ADB에서 읽기 전용 진단했다. Run은 COMPLETED지만 `tuned_sql`이 없고 비교는 `NO_REWRITE / No structural rewrite candidate`다. 4단계 예상 Plan은 정상 완료했고 실제 Source SQL은 실행하지 않았다.
- 이전 `structural_sql_key` 다중바이트 ORA-06502는 재발하지 않았다. 6단계는 76,250ms에 DONE했고 `ASTA_LLM_PKG` 결과도 COMPLETED다. Grok reasoning/Gemini는 `NO_REWRITE`, DB fallback profile은 미존재로 실패했지만 `ASTA_GROK_GENAI_PROFILE`은 17,904자의 완전한 `WITH` 후보를 생성했다.
- 후보는 FIRS_OUT/FIRS_IN과 GROUPING SETS 구조를 포함하고 원본 저장 응답 그대로는 SQL Guard `OK`다. 최종 탈락 오류는 `ASTA_SQL_GUARD: malformed ASTA tuning change annotation`이다.
- 정확한 원인: `ASTA_LLM_PKG.normalize_sql_response`에서 `l_comment_end := INSTR(l_text, '*/', 3)`는 닫는 `*/`의 `*` 위치를 반환하는데, `l_header := RTRIM(SUBSTR(l_text, 1, l_comment_end))`가 그 위치까지만 복사한다. 정상 `/* ... */`가 `/* ... *`로 잘려 Guard가 거절한다. 동일 함수 재현 결과 raw candidate 17,904자/정상 leading annotation/Guard OK, normalized 17,905자/닫는 slash 누락/Guard malformed가 일치했다.
- 수정: `db/adb/asta_llm_pkg.sql`의 header 복사를 `SUBSTR(l_text, 1, l_comment_end + 1)`로 변경해 `*/` 두 글자를 모두 보존했다. `tests/test_asta_inline_change_annotations.py`에 fenced SQL의 leading annotation 종료 문자가 보존되는 정적 회귀 계약을 추가했다.
- 배포: 사용자 승인 후 활성 ASTA Scheduler 0건을 확인하고 기존 `ASTA_LLM_PKG` spec/body를 백업한 뒤 package body를 컴파일했다. PACKAGE/PACKAGE BODY 모두 VALID, USER_ERRORS=0이며 배포된 BODY에서 `annotation_closer` marker 1건을 확인했다. 배포 전후 활성 job은 0건이다.
- 배포 후 저장 후보 재검증: 새 정규화 결과는 정상 `/* ... */` leading comment를 그대로 보존하고 annotation count 1, SQL Guard `OK`다. 구조 비교도 `DIFFERENT`로 정상 완료했다. 다음 Source 예상 Plan 단계까지 도달했으며 실제 SQL은 실행하지 않았다.
- 후보 자체의 다음 오류: 저장된 17,904자 Grok 후보는 Source `EXPLAIN PLAN`에서 `ORA-00904: "BRAND_CD": invalid identifier`로 실패했다. 이는 annotation/Guard 버그와 별개인 모델 후보의 컬럼 참조 오류다. 정상 전체 Run에서는 Stage 7 repair 경로가 이 오류를 처리할 수 있지만, 이번 검증은 외부 LLM을 재호출하지 않아 repair는 수행하지 않았다. 신규 pipeline Run 0건, 활성 job 0건이다.
- 검증: 관련 `35 passed`; 전체 `458 passed, 기존 9 failed in 1.44s`, 신규 실패 0. `git diff --check` 통과. artifact는 `reports/asta_llm_annotation_fix_deploy/20260709T061028Z/`에 배포 전 spec/body, 배포 요약, SQL 원문 없는 저장 후보 검증 요약을 보존했다. 서비스/Source package/ORDS/업무 데이터/commit/push 변경 없음. 외부 LLM 재호출 없음.

## Run 509a 개선 SQL 누락 원인·다중바이트 structural key 수정 — 2026-07-09 ADB 배포 완료

- 요청/결론: `OADT2-ASTA-509a7954080946a887537c10df2e537b`가 개선 SQL을 만들지 못한 원인을 ADB에서 읽기 전용으로 진단했다. Run은 전체적으로 COMPLETED였지만 6단계 `LLM_REWRITE`가 `ORA-06502: character string buffer too small`로 FAILED했고, 이후 후보 Plan/비교는 `No structural rewrite candidate`로 생략됐다.
- 실제 LLM 결과: GPT-5.4 1차 후보는 `NO_REWRITE`였지만 Grok 2차는 22,531자의 완전한 `WITH` 후보를 반환했다. 후보는 ASTA change annotation을 포함했고 `ASTA_SQL_GUARD_PKG.INSPECT_SQL`을 통과했다. 후보는 FIRS_OUT/FIRS_IN 상관 MIN을 `GROUPING SETS` 기반 사전 집계로 바꾸는 내용이었다. 즉 모델이 후보를 만들지 못한 것이 아니라 후보 수신 직후 ASTA 내부 구조 비교가 실패했다.
- 정확한 원인: `ASTA_LLM_PKG.structural_sql_key`의 단일 순회 scanner가 `l_char`, `l_next`를 `VARCHAR2(1)` byte로 선언했다. 원본 SQL 18,497자에는 한글 등 비ASCII 121자가 있어 한 문자를 대입하는 순간 ORA-06502가 발생했다. 실제 Run 원문을 사용한 비영속 PL/SQL 재현에서 `VARCHAR2(1) -> ORA-06502`, `VARCHAR2(4) -> OK`를 확인했다.
- 수정: `db/adb/asta_llm_pkg.sql`의 scanner 문자 버퍼를 AL32UTF8 안전한 `VARCHAR2(4)`로 변경했다. chunk도 `VARCHAR2(4096)`로 넓히고 1,000 characters마다 flush해 chunk의 byte overflow 가능성을 제거했다. `tests/test_asta_structural_sql_key_linear_scanner.py`에 문자/next/chunk 크기 회귀 계약을 추가했다.
- 사용자 제시 권고와 비교: ASTA diagnosis도 독립적으로 FIRS_OUT/FIRS_IN 상관 MIN 제거를 1순위로 선정했다. 반면 제시된 YY의 SALE_DE 제거는 원본의 결과 grain/행 수를 바꿀 수 있어 “기간합계가 업무 의도”라는 명시가 없으면 ASTA의 의미 보존 규칙상 자동 적용하면 안 된다. ITEM 단위 FIRS_OUT/FIRS_IN 예시도 원본 COLOR_CD/SIZE_CD `'-'` wildcard 의미를 잃을 수 있어 ASTA 후보는 GROUPING SETS로 이를 보존했다. 인덱스/DDL과 bind interface 변경은 SQL-only 후보 정책상 의도적으로 제외된다.
- 검증: 관련 scanner/annotation/LLM audit `34 passed`; 전체 `457 passed, 기존 9 failed in 1.45s`, 신규 실패 0. 기존 9건은 정적 계약 5, 로컬/ORDS proxy 2, workload 계약 2로 이번 변경과 무관하다. `git diff --check` 통과.
- 배포: 사용자 승인 후 활성 ASTA Scheduler 0건을 확인하고 기존 `ASTA_LLM_PKG` spec/body를 백업한 뒤 수정본만 ADB에 컴파일했다. PACKAGE/PACKAGE BODY 모두 VALID, USER_ERRORS=0이며 배포된 `USER_SOURCE`에서 `l_chunk VARCHAR2(4096)`, `l_char/l_next VARCHAR2(4)`, 1,000-character flush marker를 각각 1건 확인했다. 배포 전후 활성 job은 0건이다.
- 실환경 검증: 전체 Run 재제출은 저장 SQL을 외부 LLM으로 다시 보낼 수 있어 안전 정책이 실행 전에 차단했다. 대신 외부 LLM 호출 없이 기존 Grok 응답 22,542자를 재사용했다. 정규화된 후보 22,531자는 SQL Guard `OK`, 수정된 구조 비교는 `DIFFERENT`이며 원본/후보 key를 끝까지 계산했다. 후보 Source 예상 Plan은 `COMPLETED / EXPLAIN_PLAN_DICTIONARY_ONLY / plan_kind=ESTIMATED / source_sql_executed=false`, plan 38,591자, result digest SKIPPED다. 신규 pipeline Run 0건, 검증 후 활성 job 0건이다.
- artifact: `reports/asta_llm_multibyte_fix_deploy/20260709T055726Z/`에 배포 전 spec/body, `deploy_summary.json`, 비밀정보·SQL 원문이 없는 `stored_candidate_verification.json`을 보존했다. 기존 Run row/report는 소급 변경하지 않았다. 서비스/Source package/ORDS/업무 데이터/commit/push 변경 없음.

## ESTIMATED_PLAN 튜닝 전 UI 표시·보고서 Run ID — 2026-07-09 배포 완료

- 요청/결론: Source SQL 미실행 모드에서 결과서에 생성되는 `## 튜닝 전 예상 Plan`이 UI의 `튜닝 전` 탭에 보이지 않던 문제를 수정했다. UI 섹션 분류기가 기존 `튜닝 전 XPLAN`만 인식하던 것이 원인이었다.
- UI: `static/js/extensions/asta_report_tabs.js`에 `튜닝전 예상 plan -> before`, `튜닝후 예상 plan -> after` 규칙을 추가했다. DOM 회귀에서 예상 Plan heading과 fenced plan text가 각각 튜닝 전/후 패널에 렌더링됨을 확인했다. cache version은 `20260709_estimated_plan_tabs1`이다.
- 보고서: `ASTA_REPORT_PKG.BUILD_REPORT`의 `## 결론` 첫 항목에 `- Run ID: \`<run_id>\``를 추가했다. 이후 생성되는 보고서와 UI 요약 탭에서 Run ID를 확인할 수 있다. 기존 저장 보고서는 소급 수정하지 않았다.
- 검증: 관련 `53 passed`, 전체 `456 passed, 기존 9 failed in 1.64s`, 신규 실패 0. 전체 JS DOM 2개 통과, `node --check`, `git diff --check` 통과.
- 배포: 활성 Scheduler 0건에서 기존 `ASTA_REPORT_PKG` spec/body를 백업하고 package body를 컴파일했다. PACKAGE/PACKAGE BODY 모두 VALID, USER_ERRORS=0이다. 합성 ESTIMATED_PLAN report smoke에서 Run ID, `## 튜닝 전 예상 Plan`, Plan 본문, SQL 미실행 범위 문구를 모두 확인했다. artifact는 `reports/asta_estimated_plan_ui_report_deploy/20260709T052915Z/`다.
- 웹: 서비스는 PID 1318404, active/running, 0.0.0.0:8000 listener다. 실제 HTTP `/`에서 새 cache version을, 제공 JS에서 before/after 예상 Plan 규칙을 확인했고 workspace 파일과 byte-identical이다. 정적 파일 직접 제공이라 서비스 재시작은 하지 않았다.
- 변경 파일: `db/adb/asta_report_pkg.sql`, `static/js/extensions/asta_report_tabs.js`, `static/index.html`, `tests/js/asta_report_tabs_dom_test.cjs`, `tests/test_asta_estimated_plan_safe_mode.py`, cache 계약 테스트 2개, 이 handoff. 커밋 없음.

## Run 1f50 ORA-01039 권한 해결 검증 — 2026-07-09 완료

- DBA가 `ORCLAI`에 `DSNT.TGP_ORDER_D`, `DSNT.TGP_WHOLESALE_EXCEPT`, `DSNT.TGP_STYGRP_D`, `DSNT.TGP_STYGRP_M`의 직접 SELECT를 부여한 뒤 실제 `DBA_TAB_PRIVS`에서 4개 grant를 모두 확인했다.
- `DSNT.VIF_WHOLESALE_S`와 `DSNT.V_STYGRP_D`를 각각 단독 `ESTIMATED_PLAN`으로 재검증했고 모두 `COMPLETED / EXPLAIN_PLAN_DICTIONARY_ONLY / plan_kind=ESTIMATED`, plan text 존재, `source_sql_executed=false`, `result_digest_status=SKIPPED`, Oracle 오류 없음이다.
- 원본 Run `OADT2-ASTA-1f50ae344edc4bd59c6a4d8ed13c5ae9`의 18K SQL도 동일한 Bridge 경로에서 `OADT2-ASTA-GRANT-ORIGINAL` smoke로 예상 Plan 생성에 성공했다. 실제 업무 SQL·LLM·후보 SQL은 실행하지 않았다.
- 검증 후 활성 ASTA Scheduler job은 0건이다. 코드, package, DB Link, 서비스 변경 없음. 권한 부여는 DBA가 외부에서 수행했고 이번 세션은 읽기/예상 Plan 검증만 수행했다.

## Run 1f50 ORA-01039 정확한 뷰/직접 권한 확정 — 2026-07-09

- 추가 대조: `DSNT.VIF_WHOLESALE_S`, `DSNT.V_STYGRP_D`는 각각 `SELECT 1 ... WHERE 1=0` 일반 파싱이 성공하지만 EXPLAIN PLAN만 ORA-01039로 실패한다. 두 view는 `BEQUEATH DEFINER`다. 따라서 업무 조회 권한은 정상이고 ASTA의 예상 Plan 전용 권한 조건만 충족하지 못한 상태다.
- ORCLAI 역할은 CONNECT/RESOURCE/SELECT_CATALOG_ROLE뿐이다. 누락된 4개 underlying table은 ORCLAI direct, 부여된 role, PUBLIC 어느 경로에도 SELECT/READ grant가 없고 ORCLAI에 SELECT ANY TABLE/READ ANY TABLE도 없다. “뷰 조회 권한이 있다”와 “다른 owner view를 EXPLAIN할 underlying object 권한이 있다”는 별개다.
- 대상 `OADT2-ASTA-1f50ae344edc4bd59c6a4d8ed13c5ae9`의 SQL 원문은 출력하지 않고 참조 객체를 분리해 각 view를 `ESTIMATED_PLAN`으로 재현했다. `DSNT.VIF_WHOLESALE_S`와 `DSNT.V_STYGRP_D` 두 view 모두 단독 EXPLAIN PLAN에서 `ORA-01039`가 재현됐다.
- `ORCLAI`에는 두 view 자체와 `DSNT.TGP_STYDE_L`, `DSNT.TGP_STYLE_M`의 직접 SELECT가 있다. 다음 underlying table의 직접 SELECT는 없다: `DSNT.TGP_ORDER_D`, `DSNT.TGP_WHOLESALE_EXCEPT`, `DSNT.TGP_STYGRP_D`, `DSNT.TGP_STYGRP_M`. `SELECT ANY TABLE`/`READ ANY TABLE`도 없다.
- 정확한 최소 DBA 조치는 DSNT owner 또는 DBA가 위 4개 table에 대해 `GRANT SELECT ... TO ORCLAI`를 직접 부여하는 것이다. 역할 권한이 아니라 direct object grant가 필요하다. 권한 부여 후 두 view 단독 예상 Plan과 원본 Run SQL 예상 Plan을 재검증해야 한다.
- `SELECT USER FROM dual@DBLINK`를 원격 로그인 사용자 증거로 해석했던 이전 진단은 부정확했다. Source DB에는 `ASTA` user/role이 없어 `GRANT ... TO ASTA`가 ORA-01917로 실패했다. DB Link/credential 변경이 이 ORA-01039의 해결책이라는 결론은 철회한다.
- 대안으로 `ORCLAI.ASTA_SOURCE_DEFINER_PKG` wrapper를 로컬 구현하고 Source에 컴파일했으나 정확한 문제 SQL에서 동일 ORA-01039가 재현되어 효과가 없음을 확인했다. ADB Bridge는 배포하지 않았고 wrapper는 Source에서 삭제했으며 관련 로컬 변경도 모두 원상 복구했다. 기존 `ASTA_SOURCE_PKG`, ADB Bridge, 서비스, DB Link 매핑은 변경되지 않았다.
- 진단용 Source evidence row만 생성됐으며 업무 SQL은 실행되지 않았다. `git diff --check`, JS syntax 통과. 관련 로컬 테스트는 구현 중 `76 passed`; wrapper 변경은 최종적으로 제거했다.

## ORCLAI credential 갱신 후 DB Link 재검증 — 2026-07-09

- credential 소유자가 `ASTA_ORCLAI_LINK_CRED`의 ORCLAI 인증정보 갱신을 완료했다고 알려 재검증했다.
- 기존 링크를 건드리지 않고 `ASTA_ORCLAI_LINK_MIG` 임시 링크를 `credential_name`, private non-TLS 옵션, `shared=>TRUE`, `auth_credential_name`으로 생성했다. 연결은 성공했으나 실제 원격 `USER`가 다시 `ASTA`였고 고정 사용자 검증에 실패했다.
- 따라서 비밀번호 갱신 여부와 별개로 현재 ADB `DBMS_CLOUD_ADMIN.CREATE_DATABASE_LINK` 경로가 이 credential을 ORCLAI fixed-user 링크로 적용하지 않는 상태다. 최종 `ASTA_ORCLAI_LINK`와 allowlist 매핑은 변경하지 않았다.
- 실패한 임시 링크를 삭제했다. 최종 상태: 임시 링크 0건, 기존 링크 원격 `USER=ASTA`, `DB0903_TESTDB`/`DSNT_PDB` 모두 기존 링크 매핑. 운영 영향 없음.
- 권장 링크 정렬은 현재 방식으로 진행 불가하다. 후속은 ADB ADMIN/Oracle 지원을 통한 fixed-user DB Link 생성 확인 또는 Source `ASTA_SOURCE_PKG`의 definer-rights/ORCLAI wrapper 방식 검토다.

## ASTA_ORCLAI_LINK ORCLAI 고정 사용자 전환 시도 — 2026-07-09 안전 중단

- 사용자 승인으로 `ASTA_ORCLAI_LINK`를 Source parsing schema `ORCLAI` 고정 사용자 링크로 전환하려 했다. 활성 ASTA Scheduler job은 0건이었고, ADB에 활성 credential `ASTA_ORCLAI_LINK_CRED`가 있으며 메타데이터 username은 `ORCLAI`임을 확인했다. 비밀값은 조회·출력하지 않았다.
- 기존 링크를 바로 삭제하지 않고 `ASTA_ORCLAI_LINK_MIG` 임시 링크를 먼저 생성해 원격 `USER`를 검증했다. 첫 시도는 private non-TLS 필수값인 `directory_name=>NULL` 누락으로 `ORA-28759`가 발생했다. Oracle 공식 형식대로 `ssl_server_cert_dn=>NULL`, `directory_name=>NULL`, `private_target=>TRUE`를 명시한 뒤 연결은 성공했다.
- 그러나 일반 `credential_name` 방식과 설치된 ADB의 `shared=>TRUE + auth_credential_name` 방식 모두 임시 링크의 실제 원격 `USER`가 `ASTA`였고 `USER_DB_LINKS.USERNAME`도 NULL이었다. 따라서 ORCLAI 고정 사용자 검증을 통과하지 못해 allowlist 매핑과 최종 링크는 변경하지 않았다.
- 각 실패 뒤 임시 링크를 삭제했다. 최종 상태는 `ASTA_ORCLAI_LINK_MIG` 0건, `DB0903_TESTDB`/`DSNT_PDB` 모두 원래 `ASTA_ORCLAI_LINK` 매핑, 최종 링크 원격 `USER=ASTA`다. 운영 영향 없음.
- 다음 단계는 credential 소유자가 ORCLAI 실제 비밀번호로 `ASTA_ORCLAI_LINK_CRED`를 안전하게 재생성/갱신한 뒤 같은 임시 링크 검증을 반복하는 것이다. 인증정보 변경이 불가능하면 대안으로 Source `ASTA_SOURCE_PKG`의 `AUTHID CURRENT_USER` 경계를 definer-rights 또는 별도 ORCLAI wrapper로 재설계해야 한다.
- 코드/package/service 변경 및 커밋 없음. 인계 문서만 갱신했다.

## Run 1f50 ORA-01039 권한 오류 재현·확정 — 2026-07-09

- 대상 `OADT2-ASTA-1f50ae344edc4bd59c6a4d8ed13c5ae9`를 읽기 전용으로 확인했다. `FAILED / ASTA_PKG`, `execute_source_sql=false`, `before_evidence_mode=MINIMAL`이며 SQL Guard는 1,475ms에 완료되고 4단계 BEFORE_EVIDENCE가 4,475ms에 `ORA-01039: insufficient privileges on underlying objects of the view`로 실패했다. 업무 SQL, LLM, 후보 SQL은 실행되지 않았다.
- `DB0903_TESTDB` 연결 설정은 `source_schema=ORCLAI`, `source_db_link=ASTA_ORCLAI_LINK`지만 실제 DB Link 원격 `USER`는 `ASTA`다. `ORCLAI.ASTA_SOURCE_PKG` spec/body는 VALID이고 DB Link에서 조회 가능하다. 따라서 `AUTHID CURRENT_USER`의 EXPLAIN PLAN parse가 ORCLAI가 아닌 ASTA 직접 권한으로 수행되며, 대상 view의 underlying object 직접 SELECT 권한 부족 또는 실행 사용자 불일치가 원인으로 확정됐다.
- 재시도로 해결될 성격이 아니다. DBA 조치는 대상 view와 underlying object의 필요한 직접 SELECT 권한을 Source의 ASTA 사용자에게 부여하거나, DB Link 인증 사용자를 실제 parsing/owner 계정인 ORCLAI로 정렬하는 것이다. 역할을 통한 권한만으로는 stored PL/SQL/parse 경계에서 충분하지 않을 수 있다.
- UI/ADB 오류 분류는 ORA-00942와 ORA-01031만 권한 계열로 매핑하고 ORA-01039는 누락되어, 화면이 문의 코드 `ASTA_PKG` 및 “잠시 후 다시 시도” 일반 안내로 표시된다. 후속 구현 시 `ORA-01039 -> SOURCE_PRIVILEGE_DENIED` 분류와 “재시도 대신 DBA 직접 권한 확인” 안내를 추가해야 한다.
- 코드, DB 권한, DB Link, 서비스는 변경하지 않았다. 관련 커밋 없음.

## 운영 Source DB ORCLAI EXPLAIN PLAN 권한 확인 — 2026-07-09

- 운영 Source DB 저장 연결 `DSNT`에 읽기/진단 목적으로 접속했고 세션 사용자와 current schema가 모두 `ORCLAI`임을 확인했다.
- Oracle에는 별도의 `EXPLAIN PLAN` 시스템 권한이 없으며, 실제 동작은 PLAN_TABLE 기록 권한과 대상 객체 접근 권한으로 결정된다. `USER_SYS_PRIVS`의 `%PLAN%` 항목은 0건이었지만 PUBLIC `PLAN_TABLE` synonym이 존재했다.
- 같은 ORCLAI 세션에서 `DUAL` 대상 EXPLAIN PLAN은 2행, 실제 업무 객체 `DSNT.TGP_STYLE_M` 대상 EXPLAIN PLAN은 3행을 정상 생성했다. 따라서 ORCLAI는 해당 객체 기준 EXPLAIN PLAN을 수행할 수 있다.
- 테스트는 savepoint 이후 수행하고 rollback했으며 두 statement_id의 잔존 PLAN_TABLE 행은 0건이다. 코드·패키지·서비스·업무 데이터 변경 없음.

## Run 0f4ce ORA-01039 권한 오류 진단 — 2026-07-09

- 대상 `OADT2-ASTA-0f4ce374307e4e3ea0b5c793e55a5c8a`는 `execute_source_sql=false`, `before_evidence_mode=MINIMAL`이었다. 실제 업무 SQL 실행이 아니라 4단계 Source `EXPLAIN PLAN`에서 `ORA-01039: insufficient privileges on underlying objects of the view`가 발생했다.
- 진행 상태: SQL Guard DONE(1,471ms) → BEFORE_EVIDENCE FAILED(4,436ms) → 이후 LLM/후보 단계 미진입. 원본 SQL과 후보 SQL은 실행되지 않았다.
- 현재 ADB `ASTA_ORCLAI_LINK`의 remote `USER`는 `ASTA`이고 package owner/source schema는 `ORCLAI`다. `AUTHID CURRENT_USER` Source package는 DB Link invoker 권한으로 SQL을 parse하므로, 대상 view 또는 그 underlying object에 대한 직접 SELECT 권한/DB Link 사용자 불일치가 ORA-01039 원인으로 유력하다. 역할을 통한 권한만 있거나 view owner와 실행 사용자 권한이 분리돼도 같은 오류가 날 수 있다.
- 조치 방향: DBA가 해당 view의 underlying object 직접 SELECT 권한을 DB Link 실행 사용자에게 부여하거나, DB Link를 실제 ORCLAI 사용자로 교체해 owner/invoker 경계를 일치시켜야 한다. 비밀정보를 조회·기록하지 않았다. 애플리케이션/DB 변경 없음.

## 초기 SQL 입력 기본값 제거 — 2026-07-09

- 화면 초기 SQL textarea의 `select * from dual` 기본값을 제거하고 빈 입력 + `SELECT ...` placeholder로 변경했다. 샘플 선택과 직접 입력 동작은 유지한다.
- `node --check`, 관련 static/textarea/sticky controls 테스트 `30 passed`, `git diff --check` 통과. 정적 JS는 현재 uvicorn이 제공하는 workspace 파일에 반영된다.

## Source SQL 미실행 예상 Plan 안전 모드 — 2026-07-09 로컬 구현 완료/배포 대기

- 요청/결론: UI에 **소스 DB에서 SQL을 실제 실행하여 검증** 체크박스를 추가했다. 기본은 해제이며 `execute_source_sql=false`로 원본과 후보 업무 SELECT를 실행하지 않고 Source EXPLAIN PLAN 예상계획, PLAN_TABLE object 통계·인덱스만 LLM에 전달한다.
- Source: `p_result_evidence_mode=ESTIMATED_PLAN`을 추가했다. parsing schema에서 `EXPLAIN PLAN`하되 helper owner의 qualified PLAN_TABLE을 사용하고, DBMS_XPLAN DISPLAY와 DBA_TAB_STATISTICS/DBA_INDEXES/DBA_IND_COLUMNS 정보를 반환한다. count/digest, cursor metrics, Advisor, 결과 fetch는 수행하지 않으며 `source_sql_executed=false`, `plan_kind=ESTIMATED`를 기록한다.
- ADB: Proxy/ASTA_PKG 기본값은 false다. 미실행 모드에서는 4단계 원본과 7단계 후보 모두 ESTIMATED_PLAN을 사용하고 full-result/성능 gate로 승격하지 않는다. comparison은 `ESTIMATED_PLAN_ONLY_RUNTIME_NOT_EXECUTED`, 원본 유지, 동등성 미평가로 저장한다. 명시적 true에서만 기존 MINIMAL 원본 실행과 PLAN_ONLY/AUTO 후보 검증이 동작한다.
- LLM/결과서/UI: LLM은 예상 Plan을 A-Time/Buffer/Starts 실측으로 주장하지 않고 Cost/Cardinality 기반 추정으로만 설명한다. 결과서는 예상 Plan, 실제 성능·동등성 미검증, 적용 금지를 명시한다. UI 진행 상세도 미실행/실행 opt-in 경로를 구분하며 cache version은 `20260709_estimated_plan1`이다.
- 변경 파일: Source package/README, ADB bridge/main/LLM/report, FastAPI proxy, UI/index, 문서 3개, 신규 `tests/test_asta_estimated_plan_safe_mode.py` 및 관련 계약 테스트, 이 handoff.
- 검증: 관련 50 passed. 전체 `455 passed, 기존 9 failed in 1.54s`, 신규 실패 0. `node --check`, `git diff --check` 통과.
- 남은 단계: 실제 Source/ADB package backup→compile→VALID/errors=0→ESTIMATED_PLAN smoke, Proxy 서비스 재시작과 HTTP 자산/payload 검증이 필요하다. 사용자의 명시적 배포 승인 전에는 DB package와 서비스를 변경하지 않았다. 정적 파일 직접 제공 구조라 새 UI가 먼저 보일 수 있으므로 backend 배포 전 실제 실행 버튼 사용을 피해야 한다.
- 배포 결과(2026-07-09): ORCLAI DBTools 저장 연결(`DSNT`)로 Source package를 백업·컴파일했다. PACKAGE/PACKAGE BODY 모두 VALID, USER_ERRORS=0이다. SQLcl에서 `RUN_EVIDENCE` 함수를 SELECT 안에서 직접 호출하면 PLAN_TABLE DML의 ORA-14551이 발생하므로 실제 저장 프로시저/DB Link 경로를 사용했다. ADB의 `ASTA_SOURCE_BRIDGE_PKG`, `ASTA_LLM_PKG`, `ASTA_REPORT_PKG`, `ASTA_PKG`를 백업 후 배포했고 8개 object 모두 VALID/errors=0이다. Bridge smoke는 `EXPLAIN_PLAN_DICTIONARY_ONLY`, `source_sql_executed=false`, `plan_kind=ESTIMATED`, `result_digest_status=SKIPPED`로 성공했다. 전체 `ASTA_PKG` pipeline smoke `OADT2-ASTA-ESTPLAN-PIPELINE-SMOKE`도 COMPLETED, `NOT_IMPROVED / ESTIMATED_PLAN_ONLY_RUNTIME_NOT_EXECUTED`, before/after 모두 ESTIMATED로 성공했다. 배포 artifact는 `reports/asta_estimated_plan_deploy/20260709T040046Z/`와 Source `20260709T035536Z/`다.
- 웹: systemd restart는 interactive authentication으로 실패했으나 stale listener를 정리하고 새 uvicorn PID 1315157로 수동 기동했다. 애플리케이션 startup complete 및 HTTP GET 200 로그를 확인했다. static cache version은 `20260709_estimated_plan1`이다.

## 6단계 structural key 선형 scanner 교체 — 2026-07-09 ADB 배포 완료

- 요청/결론: 6단계에서 장기 정지한 `b177` 실행을 중단하고, `structural_sql_key`의 전체 SQL block/line comment 제거를 backtracking 정규식에서 단일 순회 scanner로 교체한 뒤 실제 ADB `ASTA_LLM_PKG`에 배포했다.
- 실행 정리: `OADT2-ASTA-b177a55b135d4f7fb7ad43813a1d2a2d`와 사용자 추가 승인한 동일 병목 Run `OADT2-ASTA-58add3b1d73543cf85f9368011a7c431`의 정확한 Scheduler job만 `STOP_JOB(force=>true)`로 중단했다. 두 row와 진행 중 단계는 `FAILED / USER_CANCELLED`로 정리했고 다른 Run은 변경하지 않았다.
- 구현: `db/adb/asta_llm_pkg.sql`의 private `structural_sql_key`가 최대 32,767자를 한 번 순회한다. NORMAL/STRING/QUOTED_IDENTIFIER/LINE_COMMENT/BLOCK_COMMENT 상태를 구분해 실제 주석과 hint만 공백으로 바꾸고, 문자열·quoted identifier 내부의 `/*`, `--`, doubled quote는 보존한다. 최종 whitespace 정규화만 단순 regex로 유지했다.
- 테스트: 신규 `tests/test_asta_structural_sql_key_linear_scanner.py` 포함 관련 계약 `60 passed`. 전체 `450 passed, 기존 9 failed in 1.44s`로 신규 실패 0건이다. `git diff --check`도 통과했다.
- 배포: 활성 ASTA Scheduler job 0건을 확인하고 현재 ADB `ASTA_LLM_PKG` spec/body DDL을 백업한 후 로컬 package를 compile했다. PACKAGE/PACKAGE BODY 모두 `VALID`, `USER_ERRORS=0`, 배포 후 활성 job 0건이다. artifact는 `reports/asta_llm_linear_scanner_deploy/20260709T021032Z/`에 있다.
- 관찰사항: compile은 ADB의 `Allocate PGA memory from OS` 자원 대기로 약 수 분 지연됐지만 정상 완료됐다. 별도 post-deploy `USER_SOURCE` 교차 조회도 같은 PGA 지연로 종료했으나, 배포 스크립트 자체의 compile/object/error/job 검증은 모두 성공했다. 외부 LLM 재호출이나 새 전체 ASTA Run은 수행하지 않았다.
- 변경 파일: `db/adb/asta_llm_pkg.sql`, 신규 scanner 계약 테스트, 이 handoff. 커밋/push 없음.

## Run b177 6단계 장기 실행 진단 — 2026-07-09

- 대상 `OADT2-ASTA-b177a55b135d4f7fb7ad43813a1d2a2d`를 ADB에서 읽기 전용으로 확인했다. 코드/DB/실행 상태는 변경하지 않았다.
- Run은 01:40:13 시작, 4단계는 345,248ms 후 완료했고 6단계는 01:46:01부터 RUNNING이다. LLM 자체는 DIAGNOSIS 2회(9.85초, 19.264초), CANDIDATE_SQL 2회(2.264초, 20.156초)를 이미 응답했다.
- 1차 diagnosis는 유효 JSON이 아니어서 Grok fallback까지 갔고, 1차 candidate는 `NO_REWRITE`, Grok 2차 candidate는 13,693자였다. 2차 후보 수신(01:46:55) 뒤 다음 fallback의 SENT audit row가 생기지 않아 외부 LLM 호출 전 로컬 후보 검증 구간에서 멈춰 있다.
- 코드상 직후 첫 연산은 `structural_sql_key(p_sql) = structural_sql_key(l_candidate_sql)`이다. `structural_sql_key`의 전체 SQL 주석 제거 정규식 `'/\*(.|[[:space:]])*?\*/'`는 겹치는 대안 `.`/space를 반복해 긴 SQL에서 catastrophic backtracking 가능성이 높다. 후보 shape는 13,693자, 207줄, 블록 주석 1쌍이다.
- 해당 Scheduler session은 active이고 `resmgr:cpu quantum` 대기/재개를 반복했다. 진단 시점에 이 Run job elapsed 약 12분 33초, CPU used 약 5.57초였다. 같은 SQL ID의 다른 ASTA job도 장기 실행 중이어서 공통 정규식 병목 정황이 강하다.
- 권장 후속: 실행 중단 여부는 사용자 승인 후 결정한다. 수정 시 regex 기반 block-comment 제거를 선형 스캐너/비중첩 패턴으로 교체하고 13K~32K SQL 회귀 테스트 및 ADB 실측 후 배포한다.

## PLAN_ONLY 탈락 결과서 일관성 보강 — 2026-07-09 ADB 배포 완료

- 요청/결론: Run f4343처럼 후보 실측 수치/변경 설명은 표시하면서 SQL·XPLAN은 없다고 출력하는 모순이 재발하지 않도록 `ASTA_REPORT_PKG` 결과서 조립 로직을 수정하고 실제 ADB에 배포했다. 기존 Run 저장 이력은 수정하지 않았다.
- 상태 분리: 결과서에서는 후보 `생성됨`, Source `실행됨`, 최종 `채택됨`을 별도로 판단한다. PLAN_ONLY 정책 탈락이 `candidate_error`에 기록돼도 generation candidate와 COMPLETED After plan이 있으면 숨기지 않는다. API top-level `candidate_sql`은 기존대로 `IMPROVED` 채택 SQL만 노출한다.
- 표시 변경: 선별 탈락 후보는 `PLAN_ONLY 선별 탈락 후보 SQL — 적용하지 마세요`로 SQL과 실제 XPLAN을 표시하고, XPLAN이 전체 결과 검증 완료를 뜻하지 않음을 명시한다. 후보가 생성됐지만 실행 plan이 없을 때와 후보 자체가 없을 때의 문구도 분리했다.
- 결론/수치: `PLAN_SCREEN_*`별 쉬운 설명을 추가했다. OLTP latency 탈락은 Buffer Gets 감소율, 실제 PLAN_ONLY 시간, 3초 기준 초과, full-result/동등성 미검증, 원본 유지 사유를 한 문장에 연결한다. comparison에 감소율/delta가 빠진 선별 응답은 Before/After 원시 수치로 결과서에서 계산한다.
- 배포/검증: 활성 Scheduler 0건에서 배포 전 spec/body를 백업하고 `ASTA_REPORT_PKG`를 compile했다. PACKAGE/PACKAGE BODY 모두 `VALID`, `USER_ERRORS=0`. f4343 artifact 기반 비영속 build_report smoke는 탈락 후보 heading, 원본 유지 사유, PLAN_ONLY XPLAN 경고, `88.35%`, `4.624433초`, 잘못된 “개선 SQL 없음” 부재를 모두 통과했다. 배포 후 Scheduler 0건, 웹 서비스 active다.
- 로컬 검증: 관련 계약 `38 passed`; 전체 `447 passed, 기존 9 failed in 1.42s`, 신규 실패 0건. `git diff --check` 통과. 배포 artifact와 백업은 `reports/asta_report_consistency_deploy/20260708T155144Z/`에 있다.
- 변경 파일: `db/adb/asta_report_pkg.sql`, `tests/test_asta_blocked_candidate_report_contract.py`, `tests/test_asta_inline_change_annotations.py`, 이 handoff. 커밋 없음.

## Run f4343 결과서 앞뒤 불일치 진단 — 2026-07-09

- 대상 `OADT2-ASTA-f4343f9895e647e8a670d33349ac63a7`; ADB Run/Progress/GET_RUN/GET_REPORT를 읽기 전용으로 대조했다. 코드·DB·결과 이력은 변경하지 않았다.
- 실제 판정은 `COMPLETED / NOT_IMPROVED / PLAN_SCREEN_OLTP_LATENCY_TARGET_NOT_MET`, `screen_mode=PLAN_ONLY`, `full_result_executed=false`, `retain_original_sql=true`다. 후보 선별 실측은 elapsed `138,734,533us → 4,624,433us`(약 96.67% 감소), Buffer Gets `9,322,778 → 1,085,874`(약 88.35% 감소)지만 OLTP 절대 기준 3초를 넘어서 탈락했다. PLAN_ONLY라 full-result digest/동등성은 평가하지 않았다.
- 결과서 모순: 결론/수치 비교/병목 진단은 후보의 comparison과 변경 설명을 출력하지만, `튜닝 후 SQL`은 “개선 SQL 없음”, `튜닝 후 XPLAN`은 “evidence 없음”이라고 출력한다. 실제 generation candidate 17,383자와 After plan 35,253자는 모두 존재한다.
- 코드 원인: `ASTA_REPORT_PKG.build_report`의 SQL/XPLAN 출력은 `llm_has_improved_sql()`을 통과한 `l_candidate_sql_vc`에 의존한다. Stage 7이 정상적인 선별 탈락도 `llm.candidate_error="Candidate rejected by PLAN_ONLY screen: ..."`로 기록하고, `llm_has_improved_sql()`은 candidate_error가 하나라도 있으면 FALSE를 반환한다. 반면 수치 섹션은 `p_comparison_json`의 PLAN_ONLY after metrics를 무조건 출력하므로 서로 다른 artifact 선택 조건이 충돌한다.
- 권장 수정: 생성/실행/채택 상태를 분리한다. 선별 탈락 후보는 `후보 SQL·XPLAN(적용 금지)`로 표시하고, 결론은 “Buffer Gets는 88.35% 감소했지만 4.624초로 3초 기준 미달, 동등성 미검증, 원본 유지”라고 명시한다. `candidate_error`는 실행 오류와 정책 탈락을 구분하거나 report에서 `PLAN_SCREEN_*`를 후보 부재로 취급하지 않아야 한다.
- 관련 커밋: 없음.

## 4단계 원본 SQL 수집 UI 최소 실행 고정 — 2026-07-09 완료

- 요청/결론: UI의 `4단계 원본 SQL 수집` 선택 상자를 제거하고 일반 UI 요청을 항상 `before_evidence_mode=MINIMAL`로 고정했다. 4단계는 제한 실행 1회와 전체 count/digest 각 1회로 원본 SQL을 최대 3회 호출한다.
- UI/표시: 진행 상세와 Workflow 설명도 MINIMAL 고정 기준만 표시한다. 남은 profile/workload/sample 3개 선택 항목은 데스크톱 3열, 태블릿 2열, 모바일 1열로 정리했다. cache version은 `20260709_stage4_minimal1`이다.
- 호환성: ADB package와 FastAPI의 기존 `before_evidence_mode` API 해석은 외부 호출 호환성을 위해 유지했다. 이번 변경은 정적 UI/문서/테스트만이며 DB package 재배포와 서비스 재시작은 하지 않았다.
- 검증: 관련 계약 `57 passed`; 전체 `445 passed, 기존 9 failed in 1.45s`로 신규 실패 0건. `node --check`, `git diff --check` 통과. 실제 localhost HTTP에서 새 cache version, 선택기/DOM 변수 부재, payload 두 위치의 MINIMAL 고정을 확인했다.
- 변경 파일: `static/js/extensions/tuning_assistant.js`, `static/index.html`, 관련 UI/정책 테스트 9개, 문서 3개, 이 handoff. 커밋/push 없음.

## Stage 7 선별/watchdog 배포 — 2026-07-08 완료 (ALTER SYSTEM 제외)

- 요청/결론: 사용자 지시에 따라 `ALTER SYSTEM`을 전혀 사용하지 않는 형태로 Source/ADB/UI/Proxy 변경을 모두 실환경에 배포했다. Source cancel API는 호환성 유지용이며 항상 `SKIPPED / SOURCE_CANCEL_NOT_AVAILABLE`을 반환하고, timeout 시 ADB parent Scheduler job만 중지한다.
- Source 배포: `ASTA_SOURCE_PKG`를 재컴파일했으며 PACKAGE/PACKAGE BODY `VALID`, `USER_ERRORS=0`이다. `PLAN_ONLY + ONCE` smoke와 cancel-unavailable smoke가 성공했다. 배포 전 백업과 로그는 `reports/asta_stage7_screen_deploy/20260708T084938Z/`에 있다.
- ADB 배포: `ASTA_SQL_GUARD_PKG`, `ASTA_LLM_PKG`, `ASTA_SOURCE_BRIDGE_PKG`, `ASTA_PKG`를 dependency 순서로 배포했다. 8개 spec/body 모두 `VALID`, 오류 0건이며 같은 artifact 디렉터리에 배포 전 DDL 8개와 `adb_deploy_summary.json`을 보존했다.
- 실환경 smoke: 혼합 ANSI JOIN/구식 `(+)` 후보가 ORA-25156 사전 검사에서 차단됐고, Bridge PLAN_ONLY는 `COMPLETED / ONCE / repeat_count=1 / digest SKIPPED`였다. Run `OADT2-ASTA-STAGE7-SCREEN-SMOKE`는 `COMPLETED`, `PLAN_SCREEN_OPTIMIZER_INTENT_NOT_VERIFIED`, `screen_mode=PLAN_ONLY`, `full_result_executed=false`; Source에는 `-TUNED-SCREEN`만 있고 `-TUNED-FINAL`은 없어 탈락 후보가 반복/전체 검증으로 진입하지 않음을 확인했다.
- 웹 배포: 정적 자산 cache version은 `20260708_stage7_screen1`이며 HTTP 제공을 확인했다. Python proxy 반영을 위해 서비스를 새 PID `1233071`로 기동했고 `active/running`, 2026-07-08 18:07:25 KST 시작, HTTP 200을 확인했다.
- 배포 후 상태: ASTA Scheduler 실행 job 0건. `node --check`와 `git diff --check` 통과. 배포 전 전체 회귀는 `445 passed, 기존 9 failed`로 신규 실패가 없었다. 최종 두 pytest 파일 재실행은 현재 venv에 pytest 모듈이 없어 수행 불가했으나, Oracle compile/실호출 smoke는 모두 성공했다.
- 변경 파일: `db/source/asta_source_pkg.sql`, Source README, ADB guard/LLM/bridge/main 4개 package, `app/routers/asta_proxy.py`, UI/문서/계약 테스트, 이 handoff. 커밋/push 없음.

## Run 441213 재실패 및 동일 SQL LLM 변동 분석 — 2026-07-08

- 대상 `OADT2-ASTA-441213c91b7d42cf9505dd552d3038a1`; 읽기 전용으로 ADB/Source evidence, LLM call log, 동일 input_sql 이력을 비교했다. DB/코드 변경 없음.
- 직전 로컬 구현한 ORA-25156 guard/PLAN_ONLY/watchdog/Source cancel은 원격 marker가 ADB screen=0, guard=0, Source PLAN_ONLY=0으로 모두 미배포 상태였다. 실제 Run ID도 기존 `-TUNED/-REPAIRED` 경로이므로 이번 실패는 새 로직 재실패가 아니라 기존 배포본 재실행이다.
- 이번 terminal은 `CANDIDATE_RUNTIME_LIMIT`. 최초 후보는 `ORA-00920: invalid relational operator`; GPT-5.4 repair 후보는 실행됐지만 AUTO 4회 중앙 `128,500,838us`, Buffer Gets `9,321,247`, repeat wall `516,391ms`로 원본 `130,430,651us / 9,324,867`과 사실상 같았다. 기존 watchdog 422초가 먼저 parent job을 종료했다.
- LLM chain: GPT-5.4 DIAGNOSIS 성공 → GPT-5.4 CANDIDATE_SQL 10자(NO_REWRITE) → Grok GenAI 18,627자 응답은 채택되지 않음 → Gemini 11,409자 응답에서 정규화된 11,291자 후보가 선택된 것으로 확인되며 ORA-00920 → GPT-5.4 REPAIR 16,211자 → 느린 후보.
- 동일 input SQL SHA-256은 최근/과거 모두 `e009...e643`. 과거 IMPROVED `aa7ba3...`는 Grok Reasoning→NO_REWRITE→Grok GenAI→repair 2회 후 `1,437,259us / 1,076,461 buffers`; `654959...`는 Grok Reasoning 1차 후보로 `1,457,303us / 1,079,348 buffers`. 두 성공 tuned SQL hash도 서로 달라 고정 재현이 아니었다.
- 변동 원인: 선택 profile/모델 체인이 달랐고, 첫 모델의 NO_REWRITE/검증 실패에 따라 fallback provider가 달라진다. 또한 같은 입력 SQL이어도 Source XPLAN·metrics와 배포된 prompt 코드가 달라 전체 prompt는 동일하지 않다. temperature 0이어도 외부 provider/model serving의 bitwise 결정성은 보장되지 않는다.
- 결론: LLM을 단일 정답 생성기로 사용한 것이 근본 원인이다. 과거 성공 후보를 verified template/fingerprint로 재사용하지 않고 매번 새로 생성하며, 기존 배포본은 문법/PLAN 선별 전 후보를 AUTO 4회 실행한다. 로컬 구현분을 배포하고, 추가로 동일 SQL의 과거 POSITIVE_VERIFIED 후보를 우선 재검증하는 deterministic reuse가 필요하다.

## AIF_GENAI credential 공유 및 ASTA GPT-5 profile 5종 생성 — 2026-07-08 완료

- 요청/결론: ADMIN 권한으로 같은 ADB의 `ASKORACLE.GENAI_CRED`를 ASTA가 비밀키 복제 없이 사용하도록 공유하고, 로컬 GPT-5 후보 10종을 실제 chat smoke했다. 호출 성공한 5종만 ENABLED 상태로 유지했다.
- credential: `GRANT EXECUTE ON ASKORACLE.GENAI_CRED TO ASTA`와 `ASTA.GENAI_CRED -> ASKORACLE.GENAI_CRED` private synonym을 생성했다. credential 비밀값은 조회·출력·파일 기록하지 않았다.
- 생성/유지 profile: `ASTA_GPT51_PROFILE=openai.gpt-5.1`, `ASTA_GPT52_PROFILE=openai.gpt-5.2`, `ASTA_GPT54_PROFILE=openai.gpt-5.4`, `ASTA_GPT54_MINI_PROFILE=openai.gpt-5.4-mini`, `ASTA_GPT54_NANO_PROFILE=openai.gpt-5.4-nano`.
- 공통 설정: provider OCI, Chicago, 원본 `AIF_GENAI` compartment, shared `GENAI_CRED`, max_tokens 8192, temperature 0, annotations/comments/constraints false. 기존 ASTA 기본 profile은 변경하지 않았다.
- 제외: `openai.gpt-5`, `gpt-5-mini`, `gpt-5-nano`, `gpt-5.2-pro`, `gpt-5.5`는 최소 chat에서 HTTP 400 또는 Object not found였고 생성 직후 profile을 삭제했다.
- 검증: 유지 5종 모두 exact-marker chat 성공(약 1.4~2.3초), ENABLED/model exact match, `ASTA_PKG.LIST_PROFILES` 5종 노출, 실패 5종 잔여 없음, credential synonym 및 EXECUTE grant 확인 완료.
- 변경 범위: DB credential object grant/synonym과 AI profile만 변경했다. package/ORDS/service/source code/default profile/git commit/push는 변경하지 않았다.
- 롤백: 5개 profile을 `DBMS_CLOUD_AI.DROP_PROFILE(..., force=>true)`로 제거한 뒤 ASTA synonym 삭제 및 `REVOKE EXECUTE ON ASKORACLE.GENAI_CRED FROM ASTA` 순서로 수행한다.
- 관련 커밋: 없음.

## 7단계 PLAN_ONLY 선별·watchdog·원격 취소 보강 — 2026-07-08 로컬 구현 완료

- 요청/결론: ORA-25156 사전 차단 → PLAN_ONLY 1회 선별 → 통과 후보만 전체/반복 검증 → 실제 pass 수 기반 watchdog → Source 원격 cancel 순서로 로컬 구현했다. DB package 배포/compile은 수행하지 않았다.
- ORA-25156: ADB SQL Guard에 `assert_candidate_compatible`를 추가해 주석/문자열 제거 후 ANSI JOIN과 구식 `(+)`가 함께 있는 후보를 Source 실행 전에 차단한다. 후보 생성과 repair 양쪽 prompt/검증에 적용했다.
- Source/Bridge: `p_result_evidence_mode=PLAN_ONLY`를 추가했다. ONCE와 함께 사용하면 gather-plan 실행 1회만 수행하고 result count/digest는 `SKIPPED / PLAN_ONLY`로 생략한다.
- 7단계: 후보/repair를 `*-SCREEN` Run ID로 `ONCE + PLAN_ONLY` 실행한다. optimizer intent가 VERIFIED이고 OLTP는 Buffer Gets 5% 이상 감소·3초 latency, BATCH는 elapsed 5% 이상 감소를 만족해야 정밀 검증으로 승격한다. 미달 후보는 `NOT_IMPROVED / PLAN_SCREEN_*`, `full_result_executed=false`로 원본을 유지한다.
- 정밀 검증: 선별 통과 시에만 원본 `-BASELINE-FINAL`과 후보 `-TUNED-FINAL`을 각각 `AUTO + FULL_RESULT`로 실행해 양쪽 반복 measurement와 full-result evidence를 갖춘 뒤 기존 deterministic comparison을 수행한다.
- watchdog: `candidate_timeout_seconds`가 예상 pass 수×candidate/baseline 1회 시간×1.2+overhead를 사용하고 최대 1800초로 제한한다. PLAN_ONLY는 1회+30초, baseline/candidate full은 각각 6회+90초 예산이다.
- 원격 취소: Source `cancel_run_vc`와 Bridge `cancel_source_run`을 추가했다. timeout watchdog은 SCREEN/BASELINE/FINAL suffix의 Source `ASTA_RUN_ID` 세션에 `ALTER SYSTEM CANCEL SQL`을 먼저 요청하고 취소 수를 progress detail에 남긴 후 parent job을 종료한다. Source owner에 `GV_$SESSION`, `GV_$SQL`, `ALTER SYSTEM` 직접 권한이 필요하며 README에 DBA 승인 조건을 기록했다.
- 변경 파일: `db/adb/asta_sql_guard_pkg.sql`, `db/adb/asta_llm_pkg.sql`, `db/adb/asta_source_bridge_pkg.sql`, `db/adb/asta_pkg.sql`, `db/source/asta_source_pkg.sql`, Source README, UI workflow/문서, 관련 테스트와 신규 `tests/test_asta_stage7_screening_and_cancel.py`, 이 handoff다.
- 검증: 관련 계약 114 passed(기존 baseline 5 failed 제외), 전체 `445 passed, 기존 9 failed in 1.42s`, 신규 실패 0. JS syntax와 `git diff --check` 통과. 실제 Oracle compile/Source 권한/원격 cancel smoke는 미배포 상태라 후속 배포 승인 시 backup→Source grants/package→ADB guard/LLM/bridge/main 순서로 검증해야 한다.
- 관련 커밋: 없음.

## AIF_GENAI 기반 ASTA GPT-5.4 profile 생성 시도 — 2026-07-08 인증 차단/정리 완료

- 요청: 같은 ADB의 `ASKORACLE.AIF_GENAI` 정보를 이용해 ASTA용 GPT profile을 생성한다.
- 확인: 원본 profile은 `provider=oci`, `region=us-chicago-1`, `model=openai.gpt-5.4`, 일반 사용자 credential `ASKORACLE.GENAI_CRED`를 사용한다. 최소 chat smoke는 성공했다. ASTA와 ASKORACLE은 동일 ADB의 서로 다른 스키마다.
- 시도: `ASTA_GPT54_PROFILE`을 ASTA 기존 정책(`OCI$RESOURCE_PRINCIPAL`, 8192 tokens, temperature 0, annotations/comments/constraints false)으로 생성하고 ASTA 컴파트먼트 및 원본 AIF 컴파트먼트에서 각각 chat smoke했다. 두 경우 모두 OCI inference endpoint가 `ORA-20404 Object not found`를 반환했다.
- 원인: `AIF_GENAI`의 GPT-5.4 접근은 schema-local 일반 credential에 의존한다. ASTA에서 같은 이름을 참조하면 `ORA-20004: Credential "ASTA"."GENAI_CRED" does not exist`이며, ASKORACLE credential은 ASTA에 공유되지 않는다. 비밀값을 조회하거나 복제하지 않았다.
- 정리: 미작동 `ASTA_GPT54_PROFILE`은 `DBMS_CLOUD_AI.DROP_PROFILE(..., force=>true)`로 제거했고 잔여 row가 0임을 확인했다. 기존 ASTA profile/package/서비스/코드는 변경하지 않았다.
- 다음 단계: credential 소유자가 OCI signing-key 값을 ASTA 스키마에 별도 credential로 안전하게 생성하거나, ASTA ADB Resource Principal에 GPT-5.4 모델 접근 IAM/entitlement를 부여해야 한다. 이후 같은 profile을 재생성하고 chat smoke 및 `ASTA_PKG.LIST_PROFILES` 노출을 검증한다.
- 관련 커밋: 없음.

## Run ba3857 7단계 실패 진단 — 2026-07-08

- 대상: `OADT2-ASTA-ba38574585354252be4f2f3b0e3099d4`. 읽기 전용으로 ADB run/progress/LLM audit와 Source 저장 evidence를 조회했다. 코드/DB 상태는 변경하지 않았다.
- terminal 원인은 `CANDIDATE_RUNTIME_LIMIT`. 7단계는 2026-07-08 16:40:12 KST 시작, 16:48:26 KST watchdog 종료로 약 493.5초 진행됐다. Scheduler history는 parent job이 force stop된 것을 확인한다.
- 1차 LLM 후보는 Source 실행 직후 `ORA-25156: old style outer join (+) cannot be used with ANSI joins`로 실패했다. REPAIR_SQL 1회가 정상 응답했고 repair 후보를 다시 실행했다.
- 원본 evidence: `ONCE`, last elapsed `142,057,037us`, Buffer Gets `9,324,294`, full-result 262행 완료. `candidate_timeout_seconds` 공식은 `ceil(original_last_sec*3+30)`이므로 이 Run의 실제 watchdog 예산은 457초다.
- repair 후보 evidence: `AUTO` 4회, 중앙 elapsed `130,176,887us`, last `129,395,372us`, Buffer Gets `9,336,067`, repeat loop wall `527,816ms`, full-result 262행 완료. 반복 루프만 527.8초라 457초 watchdog보다 약 70.8초 길고, full count/digest 시간은 이 밖에 추가된다.
- 결론: 직접 원인은 repair 후보가 원본과 비슷하게 느린 상태에서 4회 반복된 것이고, 구조적 원인은 7단계 timeout이 원본 1회×3+30초인데 후보 정책은 AUTO 4회+full count+digest라 비개선 후보는 정상 완료 전에 watchdog에 걸리는 예산 불일치다. repair 후보의 Buffer Gets도 원본보다 11,773(약 0.13%) 증가해 OLTP 개선 후보가 아니다.
- Source에 `-REPAIRED` COMPLETED evidence가 사후 저장된 점으로 보아 parent ADB Scheduler가 중지된 뒤 원격 DB Link 작업이 계속되어 저장까지 마친 것으로 추정된다. watchdog의 원격 Source 취소 보장도 후속 개선 대상이다.
- 권장 후속: 7단계도 우선 `ONCE + FULL_RESULT`로 검증하고 intent/성능 gate 통과 후보만 반복 측정하거나, watchdog을 실제 실행 횟수와 full-result pass를 포함한 총 budget으로 산정한다. ORA-25156 방지를 위해 LLM prompt/validator에서 ANSI JOIN과 `(+)` 혼용 후보를 사전 차단한다.

## 4단계 원본 SQL 수집 호출 최소화·선택 정책 — 2026-07-08 완료/ADB 배포

- 2026-07-08 16:32 KST 사용자 승인 후 장기 실행 중이던 두 Scheduler job만 `DBMS_SCHEDULER.STOP_JOB(..., force=>TRUE)`로 중지했다. 각 Run과 RUNNING progress 1건을 `FAILED / LLM_RUNTIME_LIMIT`로 terminal 처리했고 잔여 ASTA Scheduler job은 0건이다.
- 배포: 원격 `ASTA_PKG` spec/body를 `reports/asta_before_evidence_policy_deploy/20260708T073213Z/`에 백업한 뒤 로컬 `db/adb/asta_pkg.sql`만 compile했다. Source package, ORDS, 다른 ADB package, 서비스는 변경/재시작하지 않았다.
- 배포 검증: `ASTA_PKG` PACKAGE/PACKAGE BODY 모두 `VALID`, `USER_ERRORS=0`, 신규 normalizer/request/mapping marker 4개가 원격 USER_SOURCE에 존재한다.
- 실제 smoke Run `OADT2-ASTA-MINPOL-20260708073214`는 `COMPLETED`; 4단계 evidence가 `repeat_policy=ONCE`, `repeat_count=1`, `result_digest_scope=FULL_RESULT`, `result_digest_status=COMPLETED`, `advisor_requested=false`를 반환했다. 종료 후 Scheduler 0건, `select-ai-test.service` active다.
- 최종 배포 artifact: `reports/asta_before_evidence_policy_deploy/20260708T073213Z/deploy_summary.json`과 같은 디렉터리의 배포 전 spec/body 백업. 커밋/push 없음.

- 2026-07-08 16:29~16:30 KST 배포 시도: `ASTA_PKG` 단독 백업/compile 전에 안전 점검을 수행했으나 활성 Scheduler job 2건이 있어 compile 전에 중단했다. DB package/객체는 변경되지 않았다.
- 활성 job은 `ASTA_RUN_56140337F069CDAEE063251900`(Run `OADT2-ASTA-fac2...`, 약 1시간 45분)과 `ASTA_RUN_56140337F06ACDAEE063251900`(Run `OADT2-ASTA-3b64...`, 약 1시간 37분)이며 둘 다 6단계 `LLM_REWRITE` RUNNING, ACTIVE/`resmgr:cpu quantum`, 동일 SQL ID `f1tzn5290tbaa`다. 이외 RUNNING row 3건은 실제 Scheduler job 없이 과거 FINAL_REPORT FAILED 상태가 남은 stale row다.
- 안전상 실행 중 job을 임의 종료하거나 활성 package를 교체하지 않았다. 진단 artifact: `reports/asta_before_evidence_policy_deploy/20260708T072934Z/deploy_summary.json`, `reports/asta_before_evidence_policy_deploy/20260708T073002Z/deploy_summary.json`. 다음 단계는 사용자 승인 후 두 활성 Scheduler job을 정리하고 Run을 terminal 처리한 뒤 ASTA_PKG backup→compile→VALID/USER_ERRORS=0→MINIMAL smoke다.

- 요청/결론: 4단계 `BEFORE_EVIDENCE`의 원본 SQL 실행을 기존 고정 `AUTO + FULL_RESULT` 최대 6회에서 기본 `MINIMAL = ONCE + FULL_RESULT` 최대 3회로 줄였다. 최종 전체 결과 동등성 검증은 유지한다.
- 선택 정책: `before_evidence_mode=MINIMAL|FAST_PLAN|THOROUGH`. `MINIMAL`은 최대 3회, `FAST_PLAN`은 `ONCE + BOUNDED` 최대 2회지만 전체 결과 동등성 확정이 제한되며, `THOROUGH`는 기존 `AUTO + FULL_RESULT` 최대 6회다. 잘못된 값은 `MINIMAL`로 정규화한다.
- 범위: 정책은 4단계 원본 수집에만 적용한다. 7단계 후보 SQL 검증의 기존 `AUTO + FULL_RESULT` 반복은 변경하지 않았다. UI에 `4단계 원본 SQL 수집` 선택 상자를 추가하고 top-level/options payload, FastAPI proxy, ADB `RUN_PIPELINE`까지 연결했다.
- 변경 파일: `app/routers/asta_proxy.py`, `db/adb/asta_pkg.sql`, `static/js/extensions/tuning_assistant.js`, `static/index.html`, 관련 문서 3개, 관련 테스트 및 신규 `tests/test_asta_before_evidence_policy.py`, 이 handoff다.
- 검증: 관련 계약 `90 passed`, 최종 핵심 UI/정책 `38 passed`, 전체 `441 passed, 기존 9 failed in 1.42s`로 신규 실패 0건. `node --check`와 `git diff --check` 통과. 서비스는 active/running이나 현재 실행 namespace의 localhost curl은 connection refused라 HTTP 자산 직접 비교는 못 했다.
- 남은 문제/다음 단계: 실제 ADB 실행 정책까지 적용 완료했다. 과거 FINAL_REPORT 실패 후 `ASTA_RUNS.status=RUNNING`으로 남은 stale row 3건은 실행 job이 없고 이번 승인 대상이 아니어서 변경하지 않았다. 필요하면 별도 승인으로 이력 정합성을 정리한다.
- 관련 커밋: 없음.

## 11단계 Workflow 상세 설명 전면 교체 — 2026-07-08 완료

- 요청/결론: 매뉴얼 팝업의 `11단계 Workflow`에서 기존 짧은 `수행 내용` 한 문단을 제거하고, 11개 단계 모두 실제 코드 흐름을 설명하는 번호형 `상세 진행` 4개 항목으로 교체했다. 기존 `생성 근거`, `실패·차단`, package/procedure는 유지했다.
- 단계별로 요청 정규화/감사/QUEUED, Scheduler claim/progress poll, SQL Guard 이중 검사, 4단계 원본 최대 6회 실행, Advisor가 4단계 Source 호출 안에서 수행되는 점, 6단계 two-stage LLM(보통 2회·fallback 최대 6회), 7단계 후보 최대 6회 및 2회 repair/최대 3후보 실측, deterministic gate 순서, 결과서 재구성, Vector positive/rejected 분리를 구체적으로 표시한다.
- 실제 호출 순서 9→6과 현재 `p_vector_json`이 LLM prompt에 포함되지 않아 Vector 결과가 artifact로만 보존되는 구현 상태도 숨기지 않고 반영했다. 7단계 ORA repair가 6단계가 아니라 7단계 RUNNING 안에서 수행되는 점도 명시했다.
- 상세 진행은 넓은 2열 번호형 목록이며 모바일에서는 1열로 전환한다. 기존 `work` 필드는 11단계 전체에서 제거했고 `tasks` 배열을 렌더링한다.
- 변경 파일: `static/js/extensions/tuning_assistant.js`, `static/index.html`, `tests/test_asta_manual_dialog.py`, cache 계약 테스트 5개, 이 handoff다.
- 검증: 관련 `46 passed`, 전체 `438 passed, 기존 9 failed in 1.42s`, 신규 실패 0건. JS syntax와 `git diff --check` 통과. localhost `/`와 JS는 workspace와 byte-identical하고 cache version `20260708_workflow_details1`과 새 상세 문구를 실제 제공한다.
- DB/ORDS/package 배포, 서비스 재시작, commit/push는 수행하지 않았다. 정적 파일 직접 제공 방식이라 UI 변경은 실행 서비스에 반영됐다.

## 6단계 개선 SQL 만들기 상세 진단 — 2026-07-08

- 6단계 `LLM_REWRITE`는 SQL을 실행하지 않고 2-stage LLM 생성만 수행한다. 1차 DIAGNOSIS는 원본 SQL+전체 XPLAN+workload/user context로 dominant repeated-work operation, rewrite strategy, target operation, change summary, semantic risk JSON을 요청한다. 기본 profile 실패/잘못된 JSON이면 fallback profile까지 최대 2회 호출한다.
- 2차 CANDIDATE_SQL은 diagnosis+원본 SQL+전체 XPLAN으로 실행 가능한 Oracle SELECT/WITH 한 문장만 요청한다. output column/order/datatype, predicate/join, row grain/duplicate, NULL/aggregate semantics와 Oracle name-resolution/syntax를 보존하도록 강제하며 최대 4개 profile을 순차 시도한다.
- 후보 응답은 32,767자 한도, NO_REWRITE, 원본과 구조적으로 동일/comment-only/hint-only 여부, SQL Guard를 검사한다. 통과하면 변경 주석을 보장하고 candidate JSON을 만든다. 모든 LLM 시도는 `ASTA_LLM_CALL_LOG`에 stage/attempt/profile/status로 감사 기록된다.
- 정상 경로의 외부 LLM 호출은 보통 diagnosis 1회 + candidate 1회 = 2회이며, fallback이 모두 동작하면 최대 6회다. validation candidate가 request에 있으면 LLM 생성을 생략하고 그 후보를 사용한다.
- 후보 실제 실행과 성능/동등성 검증은 7단계다. 7단계 Source 실행이 ORA로 실패하면 repair LLM을 최대 2라운드 호출하고 각 후보를 다시 실행하지만, 현재 progress상 별도 6단계 하위 이벤트가 아니라 7단계 RUNNING 안에서 수행된다.
- 9단계 Vector search는 실행 순서상 6단계보다 먼저 수행되지만, 현재 `generate_sql_only_tuning`은 `p_vector_json`을 prompt에 넣지 않고 응답에도 `vector_evidence_included:false`를 기록한다. UI/문서의 “Vector 유사사례를 6단계 입력으로 전달” 설명과 실제 코드가 불일치한다.
- 코드/DB/서비스 변경은 하지 않았다. 6단계 상세 UI를 구현할 때는 DIAGNOSIS/CANDIDATE/fallback/guard 상태를 서버 progress로 분리하고, repair는 7단계 하위 작업으로 별도 표시하는 것이 정확하다.

## 4단계 진행상태 세부 작업 표시 — 2026-07-08 완료

- 요청/결론: 분석 진행상태의 4단계 `원본 SQL 실행 정보 수집`이 막연한 “처리 중”으로만 보이던 문제를 수정했다. compact 현재 단계에는 `원본 SQL 최대 6회 실행 및 실행계획·전체 결과 검증 중`을 표시한다.
- 상세 Drawer의 4단계 진행 중 영역에 `제한 실행 4회(워밍업 1 + 측정 3)`, `Elapsed/Buffer Gets/Disk Reads/XPLAN/bind/child cursor/객체 통계·인덱스`, `전체 결과 건수 1회`, `전체 결과 digest 1회`를 별도 카드로 표시한다.
- Source 호출은 현재 단일 동기 호출이라 하위 단계별 완료 이벤트가 없다. 따라서 가짜 퍼센트나 시간 기반 추정은 표시하지 않고, 어느 항목이 끝났는지는 Source 응답 후 확정된다는 안내를 명시했다. 4단계를 벗어나면 전용 상세 영역은 자동으로 숨긴다.
- 변경 파일: `static/js/extensions/tuning_assistant.js`, `static/index.html`, `tests/test_asta_progress_details.py`, `tests/test_asta_ui_run_id.py`, cache 계약 테스트 5개, 이 handoff다.
- 검증: 관련 `50 passed`, 전체 `437 passed, 기존 9 failed in 1.41s`, 신규 실패 0건. JS syntax와 `git diff --check` 통과. localhost `/`와 JS는 workspace와 byte-identical하고 cache version `20260708_before_evidence_detail1` 및 새 상세 문구를 실제 제공한다.
- DB/ORDS/package 배포, 서비스 재시작, commit/push는 수행하지 않았다. 정적 파일 직접 제공 방식이라 UI 변경은 실행 서비스에 반영됐다.

## 4단계 원본 SQL 반복 실행 진단 — 2026-07-08

- 4단계 `BEFORE_EVIDENCE`는 원본 SQL을 한 번만 실행하지 않는다. ADB가 Source Bridge를 `p_repeat_policy='AUTO'` 및 bridge 기본 `FULL_RESULT`로 호출한다.
- Source `AUTO`는 bounded/gather_plan_statistics SQL을 warm-up 1회 + 측정 3회, 합계 4회 실행한다. 이어 full-result count 1회와 full-result digest 1회를 별도 수행하므로 원본 SQL 실행계획이 실질적으로 최대 6회 작동한다.
- 반복 뒤 XPLAN, V$SQL metrics, child cursor/bind, optimizer intent, DBA_* 객체 통계/인덱스를 조회한다. 이들은 대부분 원본 SQL 재실행은 아니지만 추가 dictionary/plan 작업이다. Advisor가 켜져 있으면 같은 Source 호출 안에서 별도 SQL Tuning Advisor도 실행한다. 현재 UI 기본값은 Advisor OFF다.
- `fetch_rows` 제한은 외부 COUNT/ROWNUM wrapper라서 조인·정렬·집계·correlated subquery가 먼저 큰 작업을 하면 비용을 충분히 줄이지 못한다. 샘플 1 원본은 실측 중앙 약 124.5초이므로 반복 4회만 단순 계산해도 약 8.3분이고 full count/digest까지 더해져 4단계가 훨씬 길어질 수 있다.
- 코드/DB/서비스 변경은 하지 않았다. 고객용 개선 시 초기 진단을 `ONCE + BOUNDED`로 줄이고, 후보가 생긴 뒤 최종 검증에서만 반복 측정과 FULL_RESULT를 수행하는 단계 분리가 필요하다.

## 권한 없는 테이블 ORA 오류 명확화 — 2026-07-08 완료

- 요청/결론: 고객이 권한 없는 테이블을 조회할 때의 동작을 점검했다. Oracle은 객체가 실제로 존재해도 현재 실행 계정에 직접 조회 권한이 없으면 정보 노출 방지를 위해 흔히 `ORA-00942: table or view does not exist`를 반환한다. 기존 UI는 이를 단순 “객체 없음”으로만 안내해 권한 문제 가능성이 불명확했다.
- 실환경 근거: 2026-07-07 Source smoke에서 direct SELECT grant가 없는 `DSNT.TGP_ORDER_D` 조회가 ORA-00942였다는 기존 검증 기록을 재확인했다. 이번에 같은 실경로를 신규 Run과 Source Bridge로 재검증하려 했으나 두 호출 모두 120초 이상 terminal 응답 없이 대기해 클라이언트만 종료했다. 신규 `OADT2-ASTA-PRIV-*` row와 Scheduler job은 생성되지 않았고, package-lock 점검의 scheduler 목록도 0건이었다. 소유권을 확정할 수 없는 Python DB session은 중단하지 않았다.
- UI 변경: `SOURCE_OBJECT_NOT_FOUND` 제목을 “테이블 또는 뷰를 찾을 수 없거나 권한이 없습니다”로 바꾸고, ORA-00942가 객체 없음과 권한 없음 양쪽에서 발생할 수 있음을 설명한다. 오류 카드에 감싸진 ORA-200xx보다 실제 실행 ORA를 우선 추출한 `Oracle 오류` 전용 강조 박스를 추가하고 복사 정보에도 동일 문구를 포함했다.
- ADB 로컬 변경: `source_response_error_message`가 FAILED 응답의 일반 `message`보다 구조화된 `error.message`의 SQLERRM을 우선하도록 변경했다. 이 package 변경은 compile/deploy하지 않았다. 현재 Source 실패 JSON은 이미 `error.message`에 ORA를 넣으므로 UI 변경은 정적 자산으로 즉시 제공된다.
- 변경 파일: `db/adb/asta_pkg.sql`, `static/js/extensions/tuning_assistant.js`, `static/index.html`, `tests/test_asta_error_handling_matrix.py`, cache 계약 테스트 6개, 신규 재현 도구 `tools/verify_asta_permission_error.py`, 이 handoff다.
- 검증: 오류 관련/연관 계약 `58 passed`, JS syntax와 `git diff --check` 통과. 전체 `436 passed, 기존 9 failed in 1.34s`, 신규 실패 0건이다. localhost `/`는 HTTP 200이며 `tuning_assistant.js?v=20260708_ora_error1`을 제공하고, 제공된 JS는 workspace와 byte-identical하며 ORA 추출/강조 코드를 포함한다.
- 남은 문제/다음 단계: 고객 테스트 전에 ASTA_PKG 제출 및 Source DB Link가 정상 응답하는지 운영 상태를 별도로 확인해야 한다. ADB package hardening 배포가 필요하면 별도 승인 후 backup/compile/VALID/USER_ERRORS=0/smoke 순서로 수행한다. DB/ORDS/package 배포, 서비스 재시작, commit/push는 수행하지 않았다.

## 요청과 결론

- 고객 첫 SQL `asta-awr-01 / SESL0640.selectList`(SQL ID `7rcw6d3us86r7`)를 OLTP로 실환경 검증했다.
- 결과값 digest가 완전히 일치한 최종 후보는 중앙 elapsed `1,641,880us`, Buffer Gets `1,079,324`로 목표 2초를 통과했다.
- 원본 중앙값 `124,498,199us`, `9,159,788 buffers` 대비 elapsed `98.6812%`, buffers `88.2167%` 감소로 최종 판정은 `IMPROVED`다.
- ORDS, 운영 설정, git push는 변경하지 않았고 로컬 변경을 커밋하지 않았다.

## 현재 OLTP 정책 — 2026-07-05 변경

- 활성 absolute latency hard guard는 `3,000,000us`다. Buffer Gets 5% 감소, 원본 대비 증가 300ms 이하, noise와 digest gate는 유지한다.
- 2.5초 후보는 새 기준을 통과하고 3.1초 후보는 실패하는 quality-agent/runner 경계 테스트를 추가했다.
- 기존 1.642초 후보가 당시 2초 gate를 통과했다는 기록은 역사적 사실이며 현재 3초 기준도 통과한다.
- 로컬 `db/adb/asta_pkg.sql`은 3초로 변경했지만 DB compile/deploy를 하지 않았다. 원격 ADB `ASTA_PKG`에는 이전 2초 기준이 남아 있을 수 있다.

## 원인과 최종 후보

- `STYLE`의 correlated `NOT EXISTS (VIF_WHOLESALE_S)`가 845회 재실행되어 `TGP_STYDE_L_PK`를 누적 약 9.4억 행 처리한 것이 122초 회귀의 지배 원인이었다.
- 단순 DISTINCT helper는 optimizer가 merge하여 원본과 같은 plan이 되었고 성능이 개선되지 않았다.
- 최종 후보는 동일 projection의 항상 빈 branch를 포함한 `UNION DISTINCT` set-operation barrier로 제외 키를 한 번 계산하게 했다. 새 hint/DDL은 사용하지 않았다.
- 최종 후보 SQL: `reports/asta_customer_01_live/candidate_union_barrier.sql`
- 상세 진단: `reports/asta_customer_01_oltp_diagnosis.md`

## 변경 및 실환경 배포

- `db/source/asta_source_pkg.sql`: ordered JSON + 컬럼 metadata를 연쇄 SHA-256으로 계산하는 result digest를 additive 응답 필드로 구현했다. Source `ASTA_SOURCE_PKG` spec/body compile 후 모두 VALID, USER_ERRORS=0이다.
- `db/adb/asta_pkg.sql`: digest 누락/실패/불일치 시 성능 판정을 금지하고 OLTP 2초 hard guard를 추가했다. ADB `ASTA_PKG` spec/body compile 후 모두 VALID, USER_ERRORS=0이다.
- `tools/run_asta_prompt_abc_adb.py`: DOMINANT_NOT_EXISTS 후보 다양화, ORA 재시도, 3회 중앙값/노이즈, digest 및 latency gate를 적용했다.
- `tools/asta_quality_agent.py`, fixture/config/docs/UI/tests: 첫 고객 SQL을 OLTP로 통일하고 2초/300ms guard와 digest-only 의미 동등성 검증을 적용했다.
- 배포 전 DDL/상태는 `reports/asta_deploy_backup/` 아래에 보존했다. Source 최종 compile/smoke 로그는 `reports/asta_deploy_source/20260705T032143Z/compile.log`, `reports/asta_deploy_source/20260705T032149Z/digest_smoke.log`다.

## 실제 측정과 검증

- 원본 3회: `142,640,389us / 9,158,361`, `124,498,199us / 9,159,788`, `123,915,378us / 9,159,788`.
- 후보 3회: `1,641,880us / 1,079,325`, `1,615,886us / 1,079,324`, `1,644,745us / 1,079,323`.
- 후보 elapsed 노이즈는 `1.758%`이며 원본/후보 6회의 digest가 모두 동일했다.
- Source digest smoke: 동일 행/순서는 동일 digest, 역순은 다른 digest, status COMPLETED.
- 최종 실험 artifact: `reports/asta_customer_01_live/candidate_union_barrier_verify3.json`.
- 전체 pytest: `254 passed, 10 failed`. 신규 실패는 0이며 10건은 기존 정적 계약/Proxy 기대값 및 누락 report 관련 실패다.

## 잔여 위험/다음 단계

- 현재 digest 범위는 ASTA bounded 실행과 동일한 `BOUNDED_ORDERED_FIRST_N` 100행이다. 단순 row count/shape fallback은 허용하지 않지만 무제한 전체 결과 동등성까지 증명하지는 않는다.
- 자동 LLM이 단순 DISTINCT CTE를 다시 만들 수 있어 runner prompt에는 barrier 패턴을 보강했지만 ADB `ASTA_LLM_PKG`는 이번 승인 범위에서 compile하지 않았다.
- 1차 목표가 이미 2초 안에 들어와 `TSE_ISSU_D` 복합 IN 추가 재작성은 수행하지 않았다. 향후 전체 결과/더 높은 fetch 범위에서 필요할 때만 2차 병목으로 다룬다.

## 개선 로드맵 단계 1 — 2026-07-05 완료

- 누적 이력 문서 `docs/ASTA_SQL_TUNING_IMPROVEMENT_HISTORY.md`를 만들고 단계 0의 실환경 근거와 단계 1~8 순차 로드맵을 기록했다. 한 번에 한 단계만 진행한다.
- `tools/asta_quality_agent.py`에 DBMS_XPLAN ALLSTATS 표의 Starts/E-Rows/A-Rows/A-Time/Buffers 및 indentation 기반 parent/child parser와 결정론적 병목 ranker를 순수 함수로 추가했다.
- 고객 회귀 fixture에서 Id 28 `VIEW VIF_WHOLESALE_S`가 Starts 845, Buffers 8.09M, A-Time 124.9초, 하위 940M rows 근거로 1위다. 실제 저장 XPLAN 93개 node에서도 동일했다.
- TDD RED(import 오류) 후 GREEN 4건, 관련 테스트 35건 통과. 전체는 `258 passed, 10 failed`로 기존 실패 10건과 같고 신규 실패는 없다.
- 변경 파일: `tools/asta_quality_agent.py`, `tests/test_asta_xplan_bottleneck_ranker.py`, `tests/fixtures/asta_customer_01_dominant_xplan.txt`, `docs/ASTA_SQL_TUNING_IMPROVEMENT_HISTORY.md`, 이 handoff.
- DB compile/deploy, ORDS, 서비스, git commit/push는 수행하지 않았다. 다음 단계는 단계 2 SQL 구문/Plan Node 연결이다.

## 개선 로드맵 단계 2 — 2026-07-05 완료

- `tools/asta_quality_agent.py`에 표준 라이브러리 기반 위치 보존 SQL tokenizer와 CTE/subquery/object/alias scope 분석을 추가했다. comment/string은 제외하고 quoted identifier는 keyword로 취급하지 않는다.
- public pure function `link_dominant_plan_node_to_sql(sql_text, plan_text)`가 단계 1 랭킹을 호출해 dominant node를 SQL fragment에 연결한다. 기존 runtime 경로에는 연결하지 않았다.
- 결과 계약은 query block/CTE, construct, object/alias, character offset 및 line/column span, immediate consumer, correlated outer aliases, XPLAN predicate evidence, confidence, reason codes, `rewrite_allowed`를 포함한다.
- 실제 고객 전체 SQL/XPLAN에서 Id 28 `VIF_WHOLESALE_S`는 `STYLE` CTE의 line 19~25 correlated `NOT EXISTS`, alias `VWS`, outer alias `A`, immediate consumer `CTE_FILTER`로 confidence `0.99` 연결됐다.
- 동일 object 중복은 `AMBIGUOUS_SQL_FRAGMENT`, object 부재는 `PLAN_OBJECT_NOT_FOUND_IN_SQL`, predicate alias 불일치는 `XPLAN_ALIAS_MISMATCH`로 자동 rewrite를 차단한다. Predicate가 없고 structure가 유일할 때만 confidence `0.85`로 제한 연결한다.
- TDD RED(import 오류) → GREEN(단계 1+2 `12 passed`) → REFACTOR 후 관련 `43 passed`. 전체는 `266 passed, 10 failed`로 기존 실패 10건과 같고 신규 실패는 없다.
- 재현 명령은 고정 pytest archive `PYTHONPATH`와 `uv run --offline --no-sync`를 사용한다. `uv --with pytest --no-project --offline`은 현재 cache에 배포본이 없어 실패한다.
- 변경 파일: `tools/asta_quality_agent.py`, `tests/test_asta_sql_plan_linker.py`, `tests/fixtures/asta_customer_01_style_not_exists.sql`, `tests/fixtures/asta_customer_01_dominant_xplan.txt`, 누적 이력 문서와 이 handoff.
- DB compile/deploy, ORDS, 서비스, git commit/push는 수행하지 않았다. 다음 단계 3 병목 패턴별 후보 다양화는 `[대기]`다.

## 개선 로드맵 단계 3 — 2026-07-05 완료

- 신규 `tools/asta_strategy_planner.py`는 단계 2 link 결과를 입력으로 받아 SQL이 아닌 결정론적 전략 계획만 반환한다. 기존 runtime에서 import하지 않는다.
- registry family는 correlated NOT EXISTS/EXISTS, scalar aggregate, repeated fact scan, composite IN이다. 각 전략은 ID, target span/query block/object, summary, expected plan effect, semantic constraints, prerequisites, risk, blocked reason, executable을 포함한다.
- 고객 NOT EXISTS 기본 순서는 DISTINCT key anti → GROUP BY key anti → UNION DISTINCT barrier다. `DISTINCT_CTE_MERGED` feedback 후 실패 DISTINCT를 제외하고 barrier → GROUP BY 순서가 된다.
- blocked/저신뢰 link는 후보 0개다. planner의 `executable=true`는 후보 생성 가능 의미이며 `sql_execution_allowed=false`로 실제 실행은 금지한다.
- 정책 RED는 2.5초가 기존 기준으로 실패함을 확인했고 3초 변경 후 2.5초 통과/3.1초 실패가 됐다. planner RED는 모듈 부재였으며 GREEN/REFACTOR 후 신규 planner 테스트 9건이 통과했다.
- 관련 테스트 `41 passed`, 전체 `276 passed, 10 failed`; 기존 실패 10건과 같고 신규 실패는 없다.
- 변경 파일: `tools/asta_strategy_planner.py`, `tests/test_asta_strategy_planner.py`, 3초 정책 관련 ADB/Python/config/UI/docs/tests, 누적 이력 문서와 이 handoff.
- DB/ORDS/서비스/git commit/push 및 SQL 실행은 수행하지 않았다. 다음 단계 4 Optimizer 의도 검증은 `[대기]`다.

## 개선 로드맵 단계 4 — 2026-07-05 완료

- 신규 `tools/asta_optimizer_intent.py`는 Before/After XPLAN의 target object, operation family, active execution과 tree를 이용해 의미상 대응 node를 찾고 strategy `expected_plan_effect`를 검증한다. plan hash는 참고 evidence일 뿐 성공 조건이 아니다.
- producer/fact descendant Starts, 반복 subtree 제거, ANTI consumer와 set-operation barrier(`SORT UNIQUE`, `UNION-ALL`)를 구조적으로 확인한다.
- 실패 DISTINCT 실측은 VIF Id 28 Starts `845→845`, fact Id 38 `845→845`로 `REJECTED / OPTIMIZER_INTENT_NOT_MET`, `DISTINCT_CTE_REMERGED`다.
- 성공 barrier 실측은 VIF Id `28→31` Starts `845→1`, fact Id `38→41` Starts `845→1`, ANTI/barrier 유지로 `VERIFIED`다.
- active target node가 없거나 복수이고 Starts/operation 증거가 불충분하면 `BLOCKED / INSUFFICIENT_PLAN_EVIDENCE`이며 추측하지 않는다.
- `evaluate_candidate_after_optimizer_intent`는 VERIFIED가 아니면 digest/성능 비교를 호출하지 않고 `digest_evaluated=false`, `performance_evaluated=false`로 fail-closed 반환한다. quality normalize/report taxonomy가 verdict와 한국어 원인을 보존한다.
- 수직 슬라이스 RED→GREEN 로그는 `reports/asta_phase4_tdd.md`에 있다. 단계 4 `7 passed`, 관련 `48 passed`, 전체 `283 passed, 10 failed`; 기존 실패 10건 동일, 신규 실패 0건이다.
- 변경 파일: optimizer 모듈, quality-agent, 단계 4 테스트, 실패/성공 XPLAN fixture, 누적 이력, TDD 로그와 이 handoff.
- DB compile/deploy, ORDS, 서비스 재시작, git commit/push는 수행하지 않았다. 로컬 평가 wrapper는 아직 실서비스 runtime에 배포되지 않았다. 다음 단계 5 반복 측정/실행예산은 `[대기]`다.

## 개선 로드맵 단계 5 — 2026-07-05 완료

- 신규 `tools/asta_execution_budget.py`에 workload별 schedule, warm-up/측정 분리, 후보 순서 rotation, 중앙값/noise 요약, 전체·후보별 실행 횟수/wall-clock ledger를 순수 함수로 구현했다.
- campaign 판정은 단계 4 intent `VERIFIED`를 먼저 요구한다. timeout/runaway·예산, 측정 완전성/noise, result digest, Buffer Gets 및 OLTP 중앙 3초/원본 대비 300ms 순으로 fail-closed 평가한다.
- timeout/runaway는 cancel과 잔류 session 확인 요구를 반환하고 후보를 terminal 처리한다. 실패 후보 재호출은 실행 수를 추가 소비하지 않고 차단된다.
- 고객 실측 fixture는 Before/After 중앙 `124,498,199us / 1,641,880us`, noise `15.04% / 1.758%`, Buffer Gets 감소 `88.2167%`, digest 일치, intent VERIFIED로 `ACCEPTED`다. budget은 전체 8회/527,659ms, 후보 4회/6,603ms다.
- 수직 슬라이스별 RED→GREEN 기록은 `reports/asta_phase5_tdd.md`에 있다. 단계 5 테스트 `14 passed`, 관련 `62 passed`, 전체 `297 passed, 10 failed`; 단계 4와 같은 기존 실패 10건이며 신규 실패 0건이다.
- 변경 파일: execution-budget 모듈/테스트/fixture, quality-agent taxonomy/normalize, example config, 품질 문서, 누적 이력, TDD 기록과 이 handoff.
- DB compile/deploy, Source/ADB 신규 실행, ORDS, 서비스 재시작, git commit/push는 수행하지 않았다. 신규 계층은 아직 실서비스 runtime에 연결되지 않았다. 다음 단계 6 동등성 검증 확장은 `[대기]`다.

## 개선 로드맵 단계 6 — 2026-07-05 완료

- 신규 `tools/asta_result_equivalence.py`는 최종 top-level ORDER BY 유무를 `ORDERED_ROWS`/`UNORDERED_MULTISET`으로 구분하고 typed full-result stream digest를 생성·검증한다. unordered도 duplicate row hash를 모두 유지한다.
- metadata 위치/이름/datatype/precision/scale/길이/charset, NULL, 전체 행 수, chunk 완전성, scope/mode/algorithm과 반복 안정성을 검사한다. 빈 0행과 scalar NULL 1행은 다르다.
- bounded/truncated evidence, row/byte budget 초과, mode/metadata 불일치, 미지원 datatype과 NLS 문자열 temporal 값은 명시적 reason으로 fail-closed다.
- campaign 판정은 단계 4 intent VERIFIED → 단계 6 equivalence VERIFIED → 단계 5 measurement budget/성능 순서다. 품질 runner도 SQL-aware verifier를 호출한다.
- 기존 고객 실측은 first-100 digest뿐이므로 `BLOCKED / FULL_RESULT_EVIDENCE_REQUIRED`, measurement 처리·budget 소비 0이다. 과거 1.642초 성능 사실은 유지되지만 full-result 의미 동등성은 재검증이 필요하다.
- synthetic full fixture에서 unordered 순서 변경은 VERIFIED, ordered 순서 변경·중복 제거·NULL 변경·precision 변경은 각각 non-equivalent다.
- TDD 기록은 `reports/asta_phase6_tdd.md`. 관련 `76 passed`, 전체 `311 passed, 10 failed`; 기존 실패 10건 동일, 신규 실패 0건이다.
- 변경 파일: result-equivalence 모듈/테스트, execution campaign, 품질 runner/agent/config/tests, 누적 이력, 품질 문서, TDD 기록과 이 handoff.
- DB compile/deploy, 외부 DB 실행, ORDS, 서비스 재시작, git commit/push는 수행하지 않았다. 실제 Source package는 아직 bounded evidence만 생성하므로 full-result producer 구현·배포가 후속 실환경 과제다. 다음 단계 7 bind/plan 안정성은 `[대기]`다.

## 개선 로드맵 단계 7 — 2026-07-05 완료

- 신규 `tools/asta_bind_plan_stability.py`는 raw value 없이 bind 이름/위치/datatype/NULL/bucket/`sha256:` fingerprint와 Before/After 동일 집합을 검증한다. 기본 대표 bucket은 NULL/SELECTIVE/BROAD이고 실패 허용은 0개다.
- 각 bind의 Before/After 반복 XPLAN을 plan family, 정규화 shape, target subtree Starts로 비교한다. 같은 plan hash의 shape 변화는 실패하고 다른 hash의 동일 shape는 허용한다.
- bucket별 expected family인 `SET_OPERATION_BARRIER`와 `ANTI_SINGLE_PRODUCER` variation은 허용하지만 동일 bind plan flip, shape/Starts 불안정, Before 불안정과 증거 부족은 차단한다.
- multi-bind campaign은 모든 bind의 intent와 실제 full-result evidence를 먼저 검증한 뒤 plan stability → 전체 실행예산 preflight → bind별 반복 성능 순서로 평가한다.
- 정상 3-bind fixture는 3/3 성공, 24회, 최악 중앙 elapsed `1,641,880us`, noise `1.758%`로 ACCEPTED다. 한 bind의 digest/3.1초/Buffer/noise 실패는 후보 전체를 거절한다.
- TDD 기록은 `reports/asta_phase7_tdd.md`. 관련 `90 passed in 0.43s`, 전체 `325 passed, 10 failed`; 기존 실패 10건 동일, 신규 실패 0건이다.
- 변경 파일: bind-plan 모듈/테스트/fixture, quality taxonomy/normalize/config/tests, 누적 이력, 품질 문서, TDD 기록과 이 handoff.
- DB compile/deploy, 외부 DB 실행, ORDS, 서비스 재시작, git commit/push는 수행하지 않았다. 실제 Source child cursor/ACS/bind-aware 및 full-result evidence producer는 아직 없다. 다음 단계 8 상태머신/UI/Vector 학습은 `[대기]`다.

## 개선 로드맵 단계 8 — 2026-07-05 완료

- 신규 `tools/asta_workflow_state.py`는 Intent→Full Result→Bind/Plan→Measurement→Final 순서를 강제하고 out-of-order/missing evidence를 차단한다. 첫 terminal은 later success가 덮지 못하며 동일 attempt 재조회와 authorized restart가 결정적이다.
- 신규 `tools/asta_vector_learning.py`는 gate-complete FULL_RESULT success만 `POSITIVE_VERIFIED`, 후보 없음/ORA/비동등/bounded/intent 미달/bind flip/timeout은 `REJECTED_OBSERVATION`으로 분리한다.
- 상태/Vector record는 allowlist evidence만 보존한다. ORA code/reason은 유지하지만 포함된 SQL/literal/bind 값과 raw field는 제거한다.
- UI는 현재 단계, 차단 reason, 증거 수준, intent, full-result, bind/plan, budget/measurement를 안전한 DOM/textContent 한국어 카드로 표시한다. BLOCKED/REJECTED/FAILED는 success toast가 아니며 report/error/download SQL도 redacted copy만 사용한다.
- 로컬 ADB Vector source는 positive-only 검색, gate 재검증, rejected 분리, raw source/tuned SQL NULL 저장, 내부 report path와 allowlist metadata/chunk 계약으로 변경했다. 기존 legacy row는 삭제하지 않았다.
- TDD 기록은 `reports/asta_phase8_tdd.md`. 관련 `135 passed in 0.27s`, 전체 `339 passed, 10 failed in 0.92s`, JS syntax 통과; 기존 실패 10건 동일, 신규 실패 0건이다.
- 변경 파일: workflow/vector-learning 모듈·fixture·테스트, UI, ADB main/vector source, Vector DDL 설명, 기존 보안/UI 계약 테스트, 누적 이력, 품질 문서, TDD 기록과 이 handoff.
- DB compile/deploy, 외부 DB/브라우저 실행, ORDS, 서비스 재시작, git commit/push는 수행하지 않았다. 원격 환경에는 새 상태머신/Vector gate가 적용되지 않았다. 로드맵 0~8 로컬 구현은 완료됐고 다음은 full-result/child-cursor evidence producer와 ADB/UI 실환경 통합 검증·배포다.

## 관련 커밋

- 없음. 기존 원격 대비 46개 로컬 커밋과 미추적 파일을 보존했다.

## 첫 고객 SQL 최종 튜닝결과서 — 2026-07-05

- SQL ID `7rcw6d3us86r7`의 원본과 검증된 UNION DISTINCT barrier 후보를 Source DB에서 새로 각 1회 실행했다. timeout 600초, full-result 최대 100,000행으로 제한했다.
- 새 실측: Before `125,969,118us / 9,160,611 buffers`, After `1,749,081us / 1,079,302 buffers`; plan hash `2939336253 → 3133970339`.
- full-result는 `ORDERED_ROWS` 262행이며 metadata/result digest가 완전히 일치했다. VIF producer Starts `845→1`, ANTI consumer와 set-operation barrier 유지로 intent VERIFIED다.
- 기존 2026-07-05 3회 artifact를 성능 반복 근거로 명시적으로 재사용했다. 중앙값은 Before `124,498,199us / 9,159,788`, After `1,641,880us / 1,079,324`; elapsed 98.6812%, buffers 88.2167% 감소다.
- SQL text, V$SQL_BIND_CAPTURE, ACS 모두 bind 0건으로 재확인되어 bind gate는 `BIND_NOT_APPLICABLE`이다. 다른 동등성/intent/성능 gate는 실제 증거로 각각 통과했다.
- 최종 판정 `IMPROVED`. Markdown: `reports/asta_customer_01_final/20260705T182718KST/ASTA_SQL_TUNING_RESULT_7rcw6d3us86r7.md`; HTML: 같은 디렉터리의 `.html` 파일. HTML parser allowlist 검증 통과.
- 전체 회귀 `345 passed, 10 failed`; 기존 baseline 10건 동일, 신규 실패 0건. DB package/ORDS/service/git 변경 없음.

## 로드맵 0~8 실환경 반영 — 2026-07-05 부분 완료/차단

- Source `ASTA_SOURCE_PKG`에 full-result ordered/multiset digest와 child cursor/ACS, fingerprint-only bind metadata를 구현·배포했다. spec/body VALID, USER_ERRORS=0이며 smoke는 FULL_RESULT/complete를 통과했다.
- ADB `ASTA_SOURCE_BRIDGE_PKG`, `ASTA_VECTOR_PKG`, `ASTA_PKG`를 최소 범위로 배포했다. 6개 spec/body 객체 모두 VALID, USER_ERRORS=0이고 Source bridge full-result smoke가 통과했다.
- proxy 최종 조회 상태머신 adapter와 UI cache-buster를 연결했다. 실제 HTTP 정적 UI/JS는 새 파일을 제공하고 안전 DOM/BLOCKED toast 계약을 충족한다.
- 고객 SQL ID `7rcw6d3us86r7`의 원본/후보 full-result는 262행 ORDERED_ROWS digest와 metadata가 일치했다. 실제 XPLAN은 VIF Starts 845→1, 반복 subtree 제거, anti/barrier 유지로 intent VERIFIED다.
- 기존 성능 3회 후보 중앙 1,641,880us, Buffer 1,079,324로 3초 정책을 통과하지만 대표 bind replay가 없어 최종 `BLOCKED / BIND_REPLAY_NOT_PERFORMED`다.
- 전체 회귀는 `345 passed, 10 failed`; 기존 baseline 10건 동일, 신규 실패 0건이다.
- 서비스 후속 검증: 2026-07-05 18:06:05 KST부터 PID `759185` active/running, startup complete와 DB pool ready이며 traceback/runtime 오류는 없다. current-contract final API가 HTTP 200, `asta.workflow.v1`, `BLOCKED`, Vector `REJECTED_OBSERVATION`/positive=false를 반환해 신규 adapter 로드를 확인했다. UI root/JS도 실제 HTTP 200 및 byte equality를 통과했다.
- Bind 후속 진단: 고객 SQL ID의 bind capture 0건, ACS statistics/selectivity 0건, 저장 fixture bind placeholder 0개다. NULL/SELECTIVE/BROAD coverage는 0/0/0이며 원문 값은 조회·기록하지 않았다. 동일 bind replay는 실행하지 않고 최종 `BLOCKED / BIND_COVERAGE_INSUFFICIENT`를 유지한다.
- Vector 후속 진단: current-contract smoke rejected row 1건이 저장됐고 positive 검색 결과 0건, rejected smoke 미포함을 확인했다.
- ORDS metadata/allowlist/운영 설정/git commit/push는 변경하지 않았다. 롤백 DDL과 상세 기록은 `reports/asta_roadmap_runtime_deploy/20260705T174506KST/`에 있다.

## ASTA 결과서 5개 탭 UI 개선 — 2026-07-05 완료

- 요청/결론: 보고서 생성 내용과 raw Markdown artifact는 유지하고 UI 표시만 `Overview`, `튜닝전`, `튜닝후`, `상세내용`, `Object 통계 및 정보` 순서의 accessible tab으로 분리했다. Gate 카드는 Overview 상단에만 유지한다.
- 구현: 정확한 heading level/key parser, 제한 normalization(CRLF/공백/dash/튜닝 전후), duplicate/missing fail-closed, 안전 DOM Markdown renderer(table/list/heading/paragraph/pre-code), keyboard Arrow/Home/End와 roving focus, 모바일 horizontal scroll을 추가했다. SQL literal은 화면에 보존하고 credential/token/connection string만 마스킹한다.
- 원문 계약: `window.__astaLastReport.rawReport`를 download에 사용하므로 기존 Markdown 원문은 변하지 않는다. raw HTML/script/javascript link는 활성화하지 않는다.
- 변경 파일: `static/js/extensions/asta_report_tabs.js`, `static/js/extensions/tuning_assistant.js`, `static/index.html`, `tests/js/asta_report_tabs_dom_test.cjs`, `tests/test_asta_report_tabs.py`, phase 8/cache 계약 테스트, 누적 이력과 이 handoff.
- TDD: RED `3 failed`(모듈/원문 분리/load 부재) 확인 후 DOM 행동 test PASS. 관련 `32 passed`, JS syntax 2건 통과, 전체 `348 passed, 10 failed in 0.95s`; 기존 실패 10건 동일, 신규 실패 0건이다.
- 서비스/검증: `select-ai-test.service`는 기존 PID 759185로 active/running이며 재시작하지 않았다. localhost HTTP static smoke는 권한 경계에서 거부되어 브라우저/HTTP 제공 여부는 미확인이다.
- 남은 문제: 제한 renderer 밖 Markdown 문법은 plain text다. 새 heading은 명시적 rule/test가 필요하다. DB compile/deploy, ORDS, 서비스 재시작, git commit/push는 수행하지 않았다.

## ASTA 입력 textarea rows 조정 — 2026-07-05 완료

- 메인 `#asta-sql`은 `rows=10`, `#asta-tuning-notes`는 `rows=3`으로 변경하고 각각 explicit label `for`를 연결했다.
- 두 ID에만 `height:auto; min-height:0; overflow-y:auto`를 적용해 desktop/mobile의 기존 class 고정 높이보다 rows가 우선한다. 긴 값, resize, 붙여넣기, 전체 value와 payload/validation은 그대로다.
- hidden SQL-only/debug 경로와 결과서 SQL/XPLAN code 영역은 변경하지 않았다. assistant cache version만 `20260705_textarea_rows1`로 갱신했다.
- TDD RED는 기존 `18/4`와 scoped CSS 부재로 `2 failed`; GREEN 관련 `31 passed`, JS syntax와 diff check 통과. 전체 `350 passed, 10 failed in 0.95s`, 기존 실패 10건 동일, 신규 실패 0건이다.
- localhost HTTP static 확인은 권한 경계에서 거부되어 실행 서비스의 200/rows 제공 여부는 미확인이다. 서비스 재시작, DB/ORDS, git commit/push는 수행하지 않았다.

## ASTA sticky 결과 탭 + select controls row — 2026-07-05 완료

- `.tuning-report-tablist`는 실제 `#asta-report-scroll` 안에서 `position:sticky; top:0; z-index:20`과 opaque background/border/shadow를 사용한다. scroll container는 `overflow:auto`, transform/contain 없음이며 모바일 horizontal scroll도 유지한다.
- AI Profile/Workload/샘플 SQL은 `.tuning-controls-row`의 direct label children이다. desktop 3열 minmax, <=1100px 2열, <=720px 1열이며 notes/SQL textarea는 wrapper 밖 full-width다.
- select ID/options/default/listener/payload, 5-tab keyboard/ARIA/Gate, textarea rows 10/3은 변경하지 않았다. cache version은 `20260705_sticky_controls1`이다.
- strict TDD RED `3 failed`(sticky/wrapper/grid 부재) → GREEN 신규 `3 passed`; 관련 `43 passed`, Node DOM PASS, JS syntax와 diff check 통과. 전체 `353 passed, 10 failed in 0.94s`, 기존 실패 10건 동일, 신규 실패 0건이다.
- Hermes 독립 검증에서 관련 37건, Node DOM, JS syntax, diff check를 통과했고 실행 서비스의 index/assistant asset HTTP 200 및 sticky/3열/rows 10·3 자산 내용을 확인했다. 서비스 재시작, DB/ORDS, git commit/push는 수행하지 않았다.

## ASTA 신규 샘플 14개 — 2026-07-05 완료/실측 반영

- 1번은 `asta-awr-01 / SESL0640.selectList`, 26,321 bytes, SHA-256 `843c516404ddfdc3560010155ed2a5f4c1df435c97b6ff9e9ac3a51b0fafbe16`으로 불변이며 UI는 ID 01~15 총 15개다.
- allowlist는 `DSNT.TGP_STYDE_L`, `DSNT.TGP_STYLE_M`, `DSNT.TSE_DIV_L`, `DSNT.TSE_INOUT_S`, `DSNT.TSE_ISSU_D`, `DSNT.TSE_ORDER_S`, `DSNT.TSE_SALE_DAY_S`, `DSNT.TSE_SALE_MON_S`, `DSNT.TSE_SHOP_M`, `DSNT.VIF_WHOLESALE_S`, `DSNT.V_STYGRP_D` 11개다.
- Hermes가 승인된 ADB→DB Link→Source 경로로 사용자 요청 read-only SELECT를 실행해 `reports/asta_sample_sqls_under_60s/verification.json`을 만들었다. 02 `상관 EXISTS 반복 / CORRELATED_EXISTS_COUNT` 2.144583s/82행, 03 `상관 NOT EXISTS 반복 / CORRELATED_NOT_EXISTS` 1.446327s/80행, 04 `스칼라 MIN 중복 조회 / SCALAR_MIN_REPEATED` 1.563683s/80행, 05 `중복 CTE 이중 스캔 / DUPLICATE_CTE_SCAN` 3.234152s/200행, 06 `함수 적용 조건 / FUNCTION_PREDICATE` 1.128622s/200행, 07 `DISTINCT와 GROUP BY 중복 / REDUNDANT_DISTINCT_GROUP` 1.166045s/200행, 08 `UNION 중복 제거 / UNION_DUPLICATE_ELIMINATION` 1.335038s/200행, 09 `복합 IN 재조회 / COMPOSITE_IN_RESCAN` 17.532135s/80행, 10 `일판매 중복 스캔 / REPEATED_FACT_SCALAR` 1.115838s/40행, 11 `상세행 스칼라 SUM / CORRELATED_SCALAR_SUM` 1.086405s/60행, 12 `인라인 집계 중복 / DUPLICATE_INLINE_AGGREGATE` 1.334617s/200행, 13 `EXISTS와 NOT EXISTS 연쇄 / EXISTS_NOT_EXISTS_CHAIN` 1.894681s/45행, 14 `월판매 GROUP BY 반복 / REPEATED_GROUP_BY_CTE` 1.734214s/200행, 15 `함수 조인과 후행 필터 / FUNCTION_JOIN_ORDER` 12.928623s/38행이다.
- 14개 모두 `COMPLETED`, under 60s, timeout=false, session usable=true, outside allowlist=[]이며 최대는 17.532135초다. artifact와 UI의 ID/label/pattern/SQL fingerprint는 14/14 일치한다.
- TDD RED `4 failed, 1 passed`에서 artifact-dependent skip을 제거하고 stale fingerprint 차단을 추가해 GREEN `5 passed`가 됐다. 관련 `25 passed`, Node DOM PASS, JS syntax 통과, 전체 `359 passed, 9 failed`; 기존 baseline 10 failures 대비 신규 실패 0이고 기존 실패 1건 감소다. `git diff --check`도 통과했다.
- cache는 `20260705_samples15_under60_1`. 기존 PID 759185 서비스를 재시작하지 않았고, 서비스 로그에서 `/`와 정확한 cache-busted JS HTTP 200을 확인했다. 제공 대상 JS는 15개/ID 01~15/1번 hash 불변 계약을 통과한다.
- SQL formatting/event/payload, sticky/3열, rows 10/3, 1번은 변경하지 않았다. Source에서는 SELECT 검증만 수행했고 DB/ORDS package는 변경하지 않았다.
- 롤백은 UI 02~15/cache/test 계약의 파일 단위 복원이며 DB/ORDS/서비스 롤백은 없다. commit/push는 수행하지 않았다.
## Advisor Scheduler job cleanup — 2026-07-05 완료

- Source `ASTA_SOURCE_PKG`에 현재 호출이 생성한 `ASTA_ADV_%` job만 best-effort 정리하는 helper를 추가했다. 실행 중 job은 중지/force drop하지 않고, 비활성 job만 `DROP_JOB(force=>FALSE)`로 삭제하며 cleanup 결과는 additive JSON으로 남긴다.
- 백업: `reports/asta_advisor_job_cleanup/20260705T133920Z/source_asta_source_pkg_before.sql`. Source package만 제한 배포했고 spec/body VALID, USER_ERRORS=0이다.
- 실제 ADB→DB Link→Source Advisor smoke 2회 모두 `COMPLETED / cleanup_status=DROPPED`; 신규 Scheduler job과 DBMS_SQLTUNE task 잔여 0건이다. 기존 DISABLED 성공 job 3개는 보존했다.
- 테스트: 집중 `4 passed`; 전체 `363 passed, 기존 9 failed`, 신규 실패 0; diff check 통과. UI Advisor flag는 아직 false이며 활성화는 별도 단계다.

## ASTA UI Advisor 기본 활성화 — 2026-07-05 완료

- 선행 조건은 라이선스 확인, Source cleanup 배포, 실제 Advisor smoke 2회 `COMPLETED / DROPPED / 신규 job·task 0`이다.
- 실제 analyze payload의 top-level과 options 양쪽 `run_advisor/use_sqltune` 네 값만 `true`로 변경했다. 다른 option, 샘플 SQL, formatting/event/polling/UI 동작은 불변이다.
- strict RED `1 failed` → focused GREEN `40 passed`; JS syntax 통과. 전체 `364 passed, 9 failed in 1.14s`로 baseline 9건 동일, 신규 실패 0이다. diff check 통과.
- cache-buster는 `20260705_advisor_ui1`. 서비스 재시작, DB/ORDS 변경, 기존 Scheduler job 삭제, commit/push 없음.
- HTTP 검증은 `/`와 `/static/js/extensions/tuning_assistant.js?v=20260705_advisor_ui1`을 curl로 200 확인한 뒤 제공 JS에서 `run_advisor: true`와 `use_sqltune: true`가 각각 2개인지 확인한다.
- 롤백은 네 flag를 false로, cache를 `20260705_samples15_under60_1`로 복원한다.

## ASTA 결과서 카드 헤더 통합 — 2026-07-05 완료

- 결과 제목/Run ID, 기존 완료 상태·elapsed 노드, 기존 다운로드/초기화/위·아래 버튼, 탭을 `.tuning-report-header`에 통합했다. 새 상태나 액션을 중복 생성하지 않으며 초기화 시 기존 노드를 hero의 원래 순서로 복원한다.
- 탭은 `요약`, `튜닝 전`, `튜닝 후`, `상세 분석`, `객체 정보`. 내부 id/classification/ARIA/keyboard/click/scroll reset/Gate/raw report는 불변이다.
- Redwood surface/border/primary/text/radius 토큰 기반 compact segmented control로 변경하고 hardcoded active blue와 강한 tab shadow를 제거했다. 700px 모바일은 nowrap horizontal scroll과 정렬된 padding을 유지한다.
- strict RED `5 failed, 4 passed` → 중간 `8 passed, 1 failed` → 관련 GREEN `41 passed`; Node DOM PASS, 두 JS syntax PASS. 전체 `367 passed, 9 failed in 1.13s`, baseline 364/기존 9 failures 대비 신규 실패 0, diff check 통과.
- cache는 두 자산 모두 `20260705_report_header1`. HTTP 검증 URL은 `/`, `asta_report_tabs.js?v=20260705_report_header1`, `tuning_assistant.js?v=20260705_report_header1`이다.
- 롤백은 새 header DOM 이동/복원·CSS와 label을 직전 상태로 복원하고 tabs cache `20260705_report_tabs1`, assistant cache `20260705_advisor_ui1`로 되돌린다. DB/ORDS/서비스 재시작/commit/push 없음.

## Advisor 요약·Gate UI 제거·근거 기반 DBA 검토 — 2026-07-05 코드 준비 완료

- 요청/결론: H2/H3 `Oracle SQL Tuning Advisor 요약`을 기본 `요약` 탭으로 이동했고, 표시 전용 Gate host/card/function/CSS/문구를 제거했다. backend workflow gate와 comparison/equivalence artifact는 유지한다.
- `db/adb/asta_report_pkg.sql`: 고정 DBA 4줄을 `append_dba_review`로 교체했다. Advisor 상태/8K 권고 유형, verdict/equivalence, 실제 before/after metric, object stats/index evidence로 승인·영향·테스트·rollback을 생성하며 자동 적용은 금지한다.
- `db/adb/asta_llm_pkg.sql`: DBA 검토를 generic boilerplate로 만들지 말고 evidence별 승인/영향/rollback을 쓰며 raw Advisor report를 dump하지 않도록 prompt를 보강했다. 배포 범위 제한으로 이 package는 source-only다.
- UI/테스트/cache 변경: `static/js/extensions/asta_report_tabs.js`, `static/js/extensions/tuning_assistant.js`, `static/index.html`, `tests/js/asta_report_tabs_dom_test.cjs`, `tests/test_asta_report_tabs.py`, `tests/test_asta_phase8_ui_vector_contract.py`, `tests/test_asta_runtime_deployment_contract.py`, 신규 `tests/test_asta_dba_review_contract.py`. cache는 `20260705_advisor_summary_dba1`이다.
- Oracle 19c 검토: private BOOLEAN/`INSTR(...) > 0`, CLOB `JSON_VALUE`, 실제 comparison/object_info path와 routine ordering은 안전 계약으로 고정했다. NESTED PATH의 null child를 `COUNT(*)`가 오인할 위험은 RED 1건 후 `COUNT(index_name)`으로 수정했다.
- TDD: Advisor RED 1→GREEN, Gate RED 3→12 GREEN, DBA RED 2→2 GREEN, Oracle 19c count RED 1→3 GREEN, cache RED 1→GREEN. 최종 focused `21 passed`, Node DOM PASS, 두 JS syntax PASS. 전체 `370 passed, 기존 9 failed in 1.16s`, 신규 실패 0.
- 서비스/DB: DB/ORDS deploy, 서비스 재시작, commit/push 없음. PID 759185/8000 listen은 확인했으나 Codex sandbox localhost 연결 거부로 HTTP 실측은 못 했다.
- 다음 단계: Hermes가 기존 `tools.asta_deploy_adb.connect/run_script`를 이용해 현재 ADB `ASTA_REPORT_PKG` DDL을 백업하고 `db/adb/asta_report_pkg.sql` 하나만 배포한다. PACKAGE/PACKAGE BODY VALID, USER_ERRORS=0 및 synthetic live report에서 Advisor 요약/근거형 DBA 문구를 확인한다. 다른 ADB package는 배포하지 않는다.
- 롤백: 백업한 ASTA_REPORT_PKG spec/body를 적용해 VALID/USER_ERRORS=0 확인. UI는 SECTION_RULES/Gate/cache를 직전 `20260705_report_header1`로 복원한다.

## Run aa7 결과서 불일치 진단 — 2026-07-06

- 대상 `OADT2-ASTA-aa7ba3f1891344d697803b64f363faf9`을 ADB에서 read-only 조회했다. SQL/LLM 원문은 인계에 기록하지 않았다.
- 실제 저장 row는 COMPLETED이며 tuned_sql 17,533자, report 129,803자, response 약 29.8M자다. LLM candidate와 after evidence가 실제 존재하고 after plan_text는 33,990자다.
- comparison은 `INSUFFICIENT_EVIDENCE / OPTIMIZER_INTENT_RUNTIME_EVIDENCE_REQUIRED`, intent BLOCKED, bind BLOCKED/BIND_REPLAY_NOT_PERFORMED, measurement BLOCKED다. report builder가 verdict가 IMPROVED가 아니면 candidate 변수를 NULL로 만들고 같은 변수로 after XPLAN 표시까지 막아 `개선 SQL 없음`/`SKIPPED`를 잘못 출력한다.

## ASTA Chicago GPT 사용 가능성 진단 — 2026-07-06

- 실행 서비스의 기존 ADB 풀을 통해 `/api/profiles`와 `/api/asta/profiles`를 read-only 조회했다. 두 DB 상태는 모두 `ok`였고 ASTA API는 HTTP 200이었다.
- 실제 ADB AI profile은 `ASTA_GEMINI_PROFILE`, `ASTA_GROK_GENAI_PROFILE`, `ASTA_GROK_REASONING_PROFILE` 3개뿐이며 모두 ENABLED다. GPT/OpenAI profile은 없다.
- 두 Grok profile은 `provider=oci`, `region=us-chicago-1`, `credential=OCI$RESOURCE_PRINCIPAL`이고 모델은 각각 xAI Grok 4.20 non-reasoning과 Grok 4.3이다. 기본 profile은 `ASTA_GROK_REASONING_PROFILE`이다.
- 로컬 `models.txt`에는 Chicago용 `openai.gpt-*` 후보가 있으나 UI 후보 목록이므로 테넌시 entitlement나 실제 호출 성공의 증거로 보지 않았다.
- VM Instance Principal로 Chicago `ListModels(vendor=openai, capability=CHAT)`를 호출했으나 `404 NotAuthorizedOrNotFound`였다. IAM policy/dynamic-group 조회도 같은 권한 부족으로 차단됐다. 이는 VM 주체의 조회 권한 부족이며 ADB Resource Principal의 GPT 승인 거절을 뜻하지 않는다.
- Oracle 공개 문서상 Chicago는 OCI Generative AI 지원 리전이고 공개 OpenAI 모델은 현재 `openai.gpt-oss-20b/120b`로 확인된다. 로컬 후보에 있는 GPT-4o/4.1/5.x 제한 공개 entitlement는 공개 문서와 VM 주체로 확정하지 못했다.
- DB profile 생성/변경, DBMS_CLOUD_AI GPT 호출, 배포, 서비스 재시작, commit/push는 수행하지 않았다. 최종 확정에는 승인된 모델 ID로 임시 ASTA GPT profile을 생성해 최소 chat smoke 후 유지/삭제 여부를 결정하거나, OCI Console의 해당 테넌시 Chicago playground/model catalog를 권한 있는 사용자로 확인해야 한다.

## 데상트 테넌시 Chicago GPT 실제 사용 확인 — 2026-07-06

- 고객 테넌시 API 키 인증으로 테넌시 이름 `descentekorea`, 리전 `us-chicago-1`을 확인했다.
- OCI Generative AI 모델 카탈로그에서 `openai.gpt-oss-120b`, `openai.gpt-oss-20b` 두 모델이 모두 `ACTIVE`, capability `CHAT`, type `BASE`로 조회됐다.
- `openai.gpt-oss-20b` On-Demand 최소 chat smoke를 실행해 HTTP 200, 호출 성공, 기대 응답 문자열 일치를 확인했다. 따라서 데상트 테넌시 Chicago 리전에서 해당 GPT 모델의 실제 사용이 가능하다.
- 모델/profile/IAM/DB/서비스 설정 변경, 배포, commit/push는 수행하지 않았다. `openai.gpt-oss-120b`는 카탈로그 활성 상태까지만 확인했고 별도 inference smoke는 수행하지 않았다.
- 실제 full-result는 262행 ordered digest/metadata/complete가 일치한다. 로컬 deterministic XPLAN 재현은 correlated NOT EXISTS target을 0.99 confidence로 연결했고 producer Starts 845→1, repeated subtree 제거, ANTI consumer 유지로 두 전략에서 intent VERIFIED였다.
- 원본/후보 bind placeholder와 bind metadata가 모두 0개라 bind replay는 `BIND_NOT_APPLICABLE`이어야 하지만 Source는 모든 SQL을 무조건 BLOCKED로 반환한다.
- Before/After repeat_count는 각각 2다. 현 strict execution policy의 warm-up 1 + measurement 3을 충족하지 않아 최종 terminal은 현재로서는 BLOCKED가 맞다. 성능/동등성은 강한 provisional improvement지만 추가 반복 측정 전 IMPROVED 확정은 불가하다.
- 코드 원인: ADB comparison의 optimizer intent와 measurement status가 상수 BLOCKED로 초기화된 뒤 갱신되지 않음, Source bindless N/A 미지원, report builder의 candidate 존재/채택 상태 혼동. proxy merge는 저장 comparison을 충실히 fail-closed 반영했을 뿐 1차 원인이 아니다.
- 신규 RED `tests/test_asta_blocked_candidate_report_contract.py`: blocked candidate/after evidence 표시, intent runtime derivation, bindless N/A, measurement derivation 4건 모두 예상대로 실패한다. 구현은 하지 않았다.
- localhost report API는 인증 없이 HTTP 401이어서 proxy 원문 HTTP 응답은 확인하지 못했다. ADB `ASTA_PKG.GET_RUN/GET_REPORT/GET_PROGRESS`와 저장 row는 직접 대조했다.
- DB compile/deploy, ORDS, 서비스 재시작, commit/push 없음. 다음 승인을 받으면 Source bind N/A → ADB intent/measurement integration → report candidate 표시 분리 순서로 수정한다.
## Run aa7 결과서 수정·실측 — 2026-07-06 부분 배포 완료

- 요청/결론: `OADT2-ASTA-aa7ba3f1891344d697803b64f363faf9`의 숨겨진 후보/After XPLAN 문제를 수정했다. 실제 Before/After 각 warm-up 1 + measure 3에서 full-result 262행 ordered digest/metadata 동일, intent VERIFIED(Starts 845→1/ANTI 유지), bind `BIND_NOT_APPLICABLE`, 중앙 elapsed 121.197587초→1.437259초, buffers 9,159,767→1,076,461, noise 0.990%/3.193%로 최종 `IMPROVED`다.
- 변경 파일: `db/adb/asta_report_pkg.sql`, `db/adb/asta_pkg.sql`, `db/source/asta_source_pkg.sql`, `app/asta_runtime_gates.py`, `tools/asta_workflow_state.py`, `tools/asta_deploy_adb.py`, 관련 계약 테스트, 이력/배포 보고서/이 handoff. 기존 미커밋 변경은 보존했다.
- TDD: 신규 report 계약 4 RED→GREEN. 추가 metric reset/Before+After bind evidence 2 RED→GREEN. 최종 focused `51 passed`; 전체 `377 passed, 기존 9 failed`, 신규 실패 0. Node syntax 2개, Python compile, git diff check 통과.
- ADB 배포: `reports/asta_aa7_result_fix/20260706T001500KST/`에 `ASTA_REPORT_PKG`, `ASTA_PKG` spec/body 백업 후 두 package만 배포. PACKAGE/BODY VALID 4개, USER_ERRORS=0. 기존 run report/response도 롤백 보존했다.
- 결과서/API: `aa7_report_improved.md`, `.html`; report API `http://127.0.0.1:8000/api/asta/runs/OADT2-ASTA-aa7ba3f1891344d697803b64f363faf9/report` HTTP 200, 후보 SQL/RAW After XPLAN 포함, DB build 결과와 동일.
- 남은 문제: Source `.secrets/source_db.json`이 sandbox에 없고 사전 승인 명령의 escalation도 거절되어 `ASTA_SOURCE_PKG` 신규 코드는 미배포다. remote package는 VALID/USER_ERRORS=0이나 `RETURN 4`, `BIND_NOT_APPLICABLE`, measurement runs, optimizer evidence marker가 없다. Python service도 `sudo -n` 재시작이 거절되어 PID 759185/2026-07-05 시작 상태다. 다음 권한 가능한 세션에서 Source package backup/deploy/VALID/errors=0 후 service restart와 새 end-to-end run을 수행해야 한다.
- 롤백: ADB package는 `tools/asta_deploy_adb.py --aa7-rollback <dir>`. 기존 run은 `aa7_report_before.md`, `aa7_response_before.json` 복원. Source는 미배포라 rollback 없음. ORDS metadata/allowlist/운영 설정/commit/push 변경 없음.
## SQL Advisor 기본 OFF — 2026-07-06 코드 준비 완료

- 요청/결론: 장시간 Advisor를 당분간 피하도록 UI 일반 실행 top-level/options의 `run_advisor/use_sqltune`을 모두 false로 변경했다. proxy/ADB 누락 기본값도 false이며 명시적 true opt-in은 유지한다. Advisor PL/SQL/schema/artifact와 결과서 Advisor summary/DBA review는 삭제하지 않았다.
- UI: 입력 카드에 토글 없는 `SQL Advisor: OFF` 상태를 표시하고 client progress는 기본 OFF 생략으로 표시한다. OFF evidence/report 계약은 requested=false/status=SKIPPED다. cache `20260706_advisor_default_off1`.

- 변경 파일: `static/js/extensions/tuning_assistant.js`, `static/index.html`, `tests/test_tuning_assistant_static.py`, 신규 `tests/test_asta_advisor_default_off.py`, `tests/test_asta_runtime_deployment_contract.py`, `tools/asta_deploy_adb.py`의 읽기 전용 live static 검증 모드, 이력/이 handoff.
- TDD/검증: RED 3(UI payload/상태/cache) → GREEN focused 37 passed. Node DOM PASS, 두 JS syntax PASS. 전체 `381 passed, 기존 9 failed`, 신규 실패 0. Python compile/diff check 통과.
- HTTP: `/`와 `/static/js/extensions/tuning_assistant.js?v=20260706_advisor_default_off1`을 조회하는 검증 모드를 추가했으나 현재 Codex network namespace가 localhost socket을 `EPERM`으로 차단해 실측하지 못했다. 권한 가능한 환경에서 `.venv/bin/python tools/asta_deploy_adb.py --advisor-off-live-static reports/asta_advisor_default_off/20260706`으로 확인한다.
- DB/ORDS deploy, 서비스 재시작, commit/push 없음. 롤백은 UI 네 flag/표시/진행 문구/cache만 직전 상태로 복원한다.

## ASTA 사용자·운영 매뉴얼 현행화 — 2026-07-06 완료

- 요청/결론: `docs/AI_SQL_TUNING_ASSISTANT_MANUAL.md`를 현재 UI와 fail-closed runtime 계약 기준으로 전면 현행화했다. 실제 코드의 SQL Advisor 기본 OFF 정책을 반영했다.
- 반영 내용: Browser→FastAPI thin proxy→ADB ORDS→allowlisted DB Link→Source 경계, 화면 실행 절차, OLTP/BATCH 채택 기준, 샘플 15개, 11단계, 품질 gate/전체 결과·bind·반복 측정, verdict, 5개 결과 탭, API, 장애 점검과 운영 안전 수칙.
- 변경 파일: `docs/AI_SQL_TUNING_ASSISTANT_MANUAL.md`, 문서별 업데이트 날짜를 검증하도록 조정한 `tests/test_asta_workflow_tools_and_docs.py`, 이 handoff.
- 검증: 문서 계약 단일 테스트 `1 passed`; 변경 파일 `git diff --check` 통과. 테스트 파일 전체 실행은 임시 pytest 환경에 `oracledb`가 없어 무관한 deploy/smoke import 3건이 실패했고, 문서 표기 1건은 수정 후 통과했다.
- DB/ORDS/서비스/외부 전송/commit/push는 수행하지 않았다. 관련 커밋 없음.

## SQL_ID 03rs5gnjsy7va 조회 — 2026-07-06 미발견

- 사용자 요청에 따라 SQL_ID `03rs5gnjsy7va`를 튜닝 SQL 생성 목적으로 읽기 전용 조회했다.
- 활성 Source ID `DB0903_TESTDB`, `DSNT_PDB`의 DB Link는 동일 Source DB를 가리킨다. Source current cursor(`GV$SQL`)와 AWR(`DBA_HIST_SQLTEXT`), ADB local current/AWR를 모두 확인했으나 0건이며 조회 오류는 없었다.
- SQL 원문·plan·통계를 확보하지 못해 후보 SQL을 추측 생성하지 않았다. 다른 DB의 SQL_ID인지 확인하거나 원본 SQL/AWR SQL Text가 필요하다.
- 임시 조회 스크립트만 `/tmp/inspect_asta_sql_id.py`에 만들었고 저장소 구현 파일은 변경하지 않았다. SQL 실행, ASTA run 생성, DB/ORDS 변경, 배포, commit/push 없음.

## Run 9da Candidate adaptive timeout 진단 — 2026-07-06

- 대상 `OADT2-ASTA-9da8edc2ab6d4b8d835e6fa57e506d90`을 ADB/Source에서 읽기 전용 조회했다. 최종 ADB 상태는 `FAILED / CANDIDATE_RUNTIME_LIMIT`, 실패 단계는 `AFTER_EVIDENCE`다.
- timeout 계산은 원본 `last_elapsed_time_us=584us`에 `3배+30초`, 최소 60초 규칙을 적용해 60초였다. 이 값은 bounded COUNT wrapper 기준이며 full-result digest 비용을 반영하지 않는다.
- 최초 TUNED 후보는 `ORA-00905`로 실패했다. REPAIRED 후보의 bounded evidence는 `47,165us`, FULLCOUNT는 `43,165us`였지만 FULLDIGEST가 `163,180,990us`와 약 261만 buffer gets를 사용했다. 원본 FULLDIGEST도 `174,183,327us`였다.
- watchdog은 ADB 부모 Scheduler job을 60초에 중단·실패 처리했지만 DB Link 너머 Source FULLDIGEST는 계속 실행되어 REPAIRED 결과를 `COMPLETED / FULL_RESULT / 80 rows`로 저장했다. 후보 자체보다 digest가 timeout 원인이며, 원격 실행 취소 경계도 불완전하다.
- 설계 개선 후보: 후보 bounded 실행 timeout과 equivalence timeout 분리, 원본 FULLDIGEST 실측을 기준으로 digest budget 산정, Source session 취소/timeout 적용, timeout 뒤 늦게 저장된 Source 결과 처리 정책 명시. 이번에는 진단만 했고 코드/DB/서비스/배포/commit/push 변경 없음.

## 개발자 친화 메시지·매뉴얼 개선 — 2026-07-06 코드 완료

- 요청/결론: DBA가 아닌 개발자가 오류 원인과 다음 행동을 바로 이해하도록 UI, 결과서, timeout 메시지, 사용자 매뉴얼을 쉬운 한국어 중심으로 변경했다. 내부 reason/error code는 운영 추적과 API 호환을 위해 그대로 유지하고 화면에서는 `문의 코드`로 분리한다.
- UI: 공통 `FRIENDLY_ASTA_ISSUES` 사전과 `friendlyAstaIssue` 변환기를 추가했다. timeout, SQL 입력/문법/권한/연결, 결과 불일치, 전체 결과 부족, bind coverage, 측정 부족/noise 등 주요 코드를 `제목·설명·다음 행동`으로 변환한다. 오류 카드는 `기술 정보 (문의 시 전달)`과 `문의 정보 복사`를 제공하며 실패 버튼은 `확인 필요`/`다시 분석`으로 표시한다.
- 진행 단계/입력 용어: `Evidence`, `Workload`, `Profile`, `gate` 중심 문구를 `실행 정보`, `실행 유형`, `AI 모델 설정`, `안전 검증` 중심으로 교체했다. Advisor 표시는 `Oracle 튜닝 권고: 사용 안 함`이다.
- ADB/결과서: `CANDIDATE_RUNTIME_LIMIT` 코드는 유지하면서 error_message를 `후보 SQL 검증 시간이 초과되었습니다. 원본 SQL은 변경되지 않았습니다...`로 변경했다. 결과서에 쉬운 설명·권장 행동·문의 코드를 분리하고 Buffer Gets/Disk Reads/elapsed를 한국어로 설명하며 미검증 후보는 `현재 적용하지 마세요`로 표시한다.
- 매뉴얼: `docs/AI_SQL_TUNING_ASSISTANT_MANUAL.md`를 개발자용 빠른 안내, 용어표, 쉬운 진행 단계, 자주 보는 메시지/조치, FULLDIGEST 설명, 개발자 우선 문제 해결 순서로 재구성했다.
- cache는 `20260706_developer_messages1`. 신규 계약 테스트 `tests/test_asta_developer_friendly_messages.py`를 추가하고 관련 기존 테스트 문구를 갱신했다.
- 검증: 관련 `65 passed, 2 deselected`; Node DOM PASS, JS syntax PASS, `git diff --check` 통과. 전체 `386 passed, 기존 9 failed in 1.25s`, 신규 실패 0이다.
- DB/ORDS 배포, 서비스 재시작, 외부 전송, commit/push는 수행하지 않았다. ADB package의 새 한국어 timeout/결과서 문구는 배포 전 소스 상태이며 현재 실행 DB에는 아직 반영되지 않았다.

## ASTA 화면 샘플 최종 Gate 정리 — 2026-07-06 완료

- 요청/결론: Real ASTA의 현재 E2E 경로로 03~15를 모두 실행하고, 기존 02 결과도 포함해 최종 `IMPROVED`가 아닌 샘플을 화면에서 제거했다. 과거 고객 full-gate 검증을 통과한 `asta-awr-01`은 요청대로 보호해 유일한 화면 샘플로 유지했다.
- 실환경 결과: 02~15는 모두 실행 상태는 `COMPLETED`였지만 verdict가 `INSUFFICIENT_EVIDENCE`, optimizer intent가 `BLOCKED / OPTIMIZER_INTENT_EVIDENCE_INCOMPLETE`, 반복 측정이 `BLOCKED / MEASUREMENT_EVIDENCE_INCOMPLETE`였다. 05·08·12·14는 full-result digest 불일치도 관측됐다. 일회성 elapsed/Buffer Gets 개선 여부와 무관하게 전부 제거했다.
- artifact: `reports/asta_sample_gate_validation_20260706/summary.json`, `summary.md`에 01~15의 run_id, verdict, before/after 핵심 지표, 동등성/차단 사유, 유지/제거 결정을 기록했다. SQL 원문과 비밀정보는 넣지 않았다.
- 변경 파일: `static/js/extensions/tuning_assistant.js`, `static/index.html`, `docs/AI_SQL_TUNING_ASSISTANT_MANUAL.md`, 샘플/cache 관련 테스트, 신규 `tests/test_asta_final_sample_gate.py`, 실행 도구 `tools/run_asta_10_sqls.py`, 위 artifact와 이 handoff. 기존 미커밋 변경은 보존했다.
- strict TDD: 01 단독 유지 계약을 먼저 실행해 예상 RED `1 failed`(화면 15개 노출)를 확인한 뒤 삭제 후 GREEN `1 passed`. 관련 회귀 `66 passed`. JS 문법 2개와 Node DOM 테스트 PASS. 전체 회귀 `388 passed, 기존 9 failed`; 직전 baseline의 동일한 9건이며 신규 실패는 없다. `git diff --check` 통과.
- 서비스: `select-ai-test.service`는 기존 PID 822785로 active이며 재시작하지 않았다. `/`, cache-busted assistant JS, report-tabs JS가 모두 HTTP 200이고 제공 파일이 로컬 파일과 byte-identical이다. 제공 assistant JS의 화면 샘플 ID는 1개다.
- 잔류 점검: 이번 03~15 run은 모두 terminal 완료했고 현재 ADB Scheduler 실행 job은 0건이다. ADB 저장소에는 2026-07-03~04의 기존 RUNNING 상태 row 3건이 있으나 실제 running job은 없어 과거 stale metadata로 판단했다. 승인 범위 밖이므로 수정하지 않았다. 확인 시 Source의 일반 업무 세션은 ASTA 작업이 아니어서 건드리지 않았다.
- DB package/ORDS 설정, 서비스 재시작, commit/push는 수행하지 않았다.

## ASTA 신규 IMPROVED 샘플 캠페인 — 2026-07-06 preflight 차단

- 요청/결론: 최종 `IMPROVED`를 통과한 신규 화면 샘플 최대 3개를 만들도록 승인받았으나 성공 0개, UI 추가 0개로 종료했다. 기존 `asta-awr-01`은 그대로 보존했다.
- 실환경 preflight: Source `ASTA_SOURCE_PKG` spec/body는 VALID, USER_ERRORS=0이지만 현재 배포본의 `AUTO=4`, `BIND_NOT_APPLICABLE`, `measurement_runs`, `optimizer_intent_evidence` marker가 모두 false다. `current_contract_deployed=false`다.
- 차단 판단: ADB final gate는 optimizer intent `VERIFIED`, 3회 measurement `ACCEPTED`를 필수로 요구한다. 현재 Source는 그 evidence를 생성할 수 없고 사용자가 DB package/ORDS 변경과 gate 완화를 금지했으므로, 새 SQL은 내용과 성능에 관계없이 최종 `IMPROVED`가 구조적으로 불가능하다. 성공 가능성이 없는 Source/ASTA 실행으로 고객 DB 부하를 만들지 않았다.
- 검토 패턴: 상관 NOT EXISTS 반복→단일 anti producer, 중복 스칼라 집계→한 번의 사전 집계, 함수 조건→sargable 조건의 세 방향을 설계 대상으로 기록했으나 모두 `NOT_EXECUTED`다. 미검증 SQL은 UI에 추가하지 않았다.
- artifact: `reports/asta_new_samples_20260706/runtime_status/source_remote_status.json`, `campaign_summary.json`, `campaign_summary.md`. 신규 계약 테스트는 `tests/test_asta_new_sample_campaign_contract.py`다.
- strict TDD: campaign artifact 부재 상태에서 RED `2 failed`를 확인한 뒤, 차단 artifact와 UI 무변경 계약으로 GREEN `9 passed`. 전체 회귀 `390 passed, 기존 9 failed`, 신규 실패 0. JS syntax 2건, Node DOM, `git diff --check` 통과.
- 서비스: 기존 PID `822785` active, 재시작 없음. `/`, assistant JS, report-tabs JS 모두 HTTP 200이고 세 파일 모두 workspace와 byte-identical이다. 제공 UI 샘플은 01 한 개다.
- 잔류: ADB running Scheduler job 0건. 2026-07-03~04의 기존 stale RUNNING row 3건은 실제 job이 없어 보존했다. Source에서 보인 활성 JDBC SQL은 일반 업무 세션이며 ASTA child가 아니어서 건드리지 않았다.
- DB package/ORDS/DDL/index/statistics, 매뉴얼/cache-buster, 서비스 재시작, commit/push 변경 없음.

## ASTA 내부 명세 단일화 — 2026-07-06 완료

- 요청/결론: 중복된 `AI_SQL_TUNING_ASSISTANT_PROGRAM_SPEC.md`와 `OADT2_ASTA_ARCHITECTURE.md` 중 후자를 단일 기준 문서로 선택해 전면 현행화하고 전자는 삭제했다. 기존 README·배포 가이드가 아키텍처 문서를 대표 내부 문서로 연결하고 있어 이 경로를 유지했다.
- 통합 내용: 운영 경계, 구성요소 책임, `SUBMIT_RUN → Scheduler → EXECUTE_RUN` 비동기 계약, 11단계와 실제 의존 순서, SQL Guard/LLM, FULLDIGEST, optimizer intent→전체 결과→bind/plan→반복 측정→workload gate, verdict, adaptive timeout, Advisor 기본 OFF, Vector/결과서/저장·배포 경계를 한 문서에 정리했다.
- 참조 정리: 사용자 매뉴얼과 `docs/README.md`에서 삭제 문서 링크를 제거했다. 활성 `README.md`, `Guide_Deploy_OCI.md`, `db/adb/README.md`의 동기식 `ANALYZE_SQL` 설명을 현재 async 계약으로 수정했다. 초기 동기 구현을 담은 `docs/asta_source_execution_flow.md`에는 현재 기준 문서와 deprecated 경고를 추가했다. 역사적 계획 문서는 변경하지 않았다.
- 변경 파일: `docs/OADT2_ASTA_ARCHITECTURE.md`, 삭제한 `docs/AI_SQL_TUNING_ASSISTANT_PROGRAM_SPEC.md`, `docs/AI_SQL_TUNING_ASSISTANT_MANUAL.md`, `docs/README.md`, `README.md`, `Guide_Deploy_OCI.md`, `db/adb/README.md`, `docs/asta_source_execution_flow.md`, `tests/test_asta_workflow_tools_and_docs.py`, 이 handoff.
- 검증: 단일 문서/필수 계약 테스트 `2 passed`; 삭제 문서의 활성 참조 없음; `git diff --check` 통과. DB/ORDS/서비스/외부 전송/commit/push 변경 없음.

## 신규 IMPROVED 샘플 14개 요청 재점검 — 2026-07-06 차단

- 요청 범위는 Real ASTA(`/opt/select-ai-test`)에서 bounded 원본 SQL 14개를 Source 60초 미만으로 검증하고 실제 전체 파이프라인의 최종 `IMPROVED`만 UI에 반영하는 것이다. package/DB schema deploy, 서비스 재시작, commit/push는 금지됐다.
- 승인된 ADB→DB Link→Source 읽기 경로로 원격 `ASTA_SOURCE_PKG`를 다시 조회했다. PACKAGE/BODY는 VALID, USER_ERRORS=0이지만 `AUTO=4`, `BIND_NOT_APPLICABLE`, `measurement_runs`, `optimizer_intent_evidence` 필수 marker가 모두 없고 `current_contract_deployed=false`다.
- 기존 동일 Real ASTA 경로의 02~15 총 14개 실측은 모두 `COMPLETED`였으나 최종 verdict `INSUFFICIENT_EVIDENCE`, optimizer intent `BLOCKED / OPTIMIZER_INTENT_EVIDENCE_INCOMPLETE`, measurement `BLOCKED`였다. SQL 교체로 해결할 수 없는 runtime evidence producer 차단이다.
- 현재 계약에서 최종 `IMPROVED` 14개를 만들려면 Source package에 반복 측정/optimizer intent/bindless evidence producer를 먼저 배포해야 한다. 이는 명시적으로 금지된 DB package deploy이므로 신규 Source/ASTA 실행, UI 변경, RED 테스트 작성을 시작하지 않았다. 불필요한 고객 DB 부하와 허위 verdict/UI 반영을 피했다.
- 이번 재점검의 변경은 이 handoff뿐이다. DB/ORDS/서비스/UI/git commit/push 변경 없음. 다음 진행에는 최소한 현재 로컬 `ASTA_SOURCE_PKG`의 제한 배포 승인이 필요하다.

## Real ASTA 신규 IMPROVED 샘플 14개 — 2026-07-06 완료

- 사용자가 Source/ADB/schema/ORDS/runtime 배포를 모두 승인해 이전 preflight 차단을 해제했다. Real ASTA `/opt/select-ai-test`와 승인된 ADB→DB Link→Source 경로만 사용했다.
- Source `ASTA_SOURCE_PKG`를 배포 전 백업한 뒤 배포했다. PACKAGE/BODY VALID, USER_ERRORS=0, `AUTO=4`/`BIND_NOT_APPLICABLE`/`measurement_runs`/`optimizer_intent_evidence` marker가 모두 true다. Source full-result smoke는 COMPLETED, FULL_RESULT, complete=true, bind NOT_APPLICABLE다. 백업/로그는 `reports/asta_deploy_source/20260706T130257Z/`다.
- ADB는 `ASTA_SQL_GUARD_PKG`, `ASTA_SOURCE_BRIDGE_PKG`, `ASTA_VECTOR_PKG`, `ASTA_LLM_PKG`, `ASTA_REPORT_PKG`, `ASTA_PKG` 순으로 백업·배포했다. spec/body 12개 모두 VALID, USER_ERRORS=0다. async/LLM log migrations와 ORDS `asta.v1`을 적용했고 기존 repository/vector/source mapping은 보존했다. 백업/상태는 `reports/asta_sample14_runtime_deploy/20260706T220303KST/`다.
- LLM이 선두 변경 주석 뒤 prose를 SQL로 오인한 ORA-06502 회귀를 strict RED→GREEN으로 수정했다. 정규화기는 실제 줄 시작 WITH/SELECT 앞 prose만 제거하고 검증된 선두 주석은 보존한다.
- campaign 전용 `validation_candidate_sql`은 동일 SQL Guard를 통과한 SELECT/WITH 후보만 허용한다. 모든 후보는 Source ONCE/FULL_RESULT/55초 preflight 후 정식 ASTA Before/After AUTO=4, full-result digest, optimizer intent, bind, measurement, workload gate를 그대로 통과해야 하며 verdict override는 없다.
- optimizer intent는 반복 producer Starts 감소뿐 아니라 공통 target access buffers 20% 이상 감소, target operation 제거, plan shape 변화+전체 buffers 20% 이상 감소를 실제 plan-node evidence로 검증하도록 확장했다. equivalence와 measurement gate 순서는 유지했다.
- 원본 14개는 모두 SELECT/WITH-only, allowlist 내 객체, bounded predicate/ROWNUM, side effect 없음이다. 최신 Source wall time은 1.878~4.924초로 모두 60초 미만이며 timeout=false, session usable=true다.
- 최종 02~15 모두 새로운 terminal run에서 `COMPLETED / IMPROVED`, candidate VALID, equivalence VERIFIED, optimizer intent VERIFIED, measurement ACCEPTED(각 side warm-up 1 + measure 3), bind NOT_APPLICABLE를 통과했다. 전체 시도는 51회이며 실패/noise/구버전 run은 채택하지 않았다.
- 최종 상세 artifact는 `reports/asta_new_samples_20260706/campaign_summary.json`, Source 실행 artifact는 `reports/asta_sample_sqls_under_60s/verification.json`, 개별 결과는 `reports/asta_sample14_campaign_20260706/asta-awr-*.json`이다. SQL 원문이나 bind 값은 결과 artifact에 넣지 않았다.
- UI는 보호 샘플 01 hash를 유지하고 02~15를 현재 hash/run 결과로 추가했다. cache version은 `20260706_samples14_improved1`. 실행 서비스 root와 두 cache-busted JS는 HTTP 200이며 served bytes가 workspace와 동일하고 화면 샘플은 15개다.
- strict TDD: campaign 완료 계약 RED `1 failed, 2 passed`; LLM normalizer RED 1건; 기존 one-sample UI 계약 RED 4건을 확인했다. targeted GREEN `61 passed`. 전체 회귀 `393 passed, 기존 9 failed`, 신규 실패 0. JS syntax 2개, Node DOM, Python compile, `git diff --check` 통과.
- 서비스 재시작은 `systemctl restart`와 `sudo -n systemctl restart` 모두 OS 인증 경계에서 거절되어 실행하지 못했다. 기존 PID 822785는 active/running이며, Python app 코드는 변경하지 않았고 정적 asset은 실행 서비스에서 최신 bytes로 제공된다. ADB/ORDS package는 DB에서 직접 반영되어 14개 최종 run에 사용됐다.
- 종료 시 sample campaign prefix의 QUEUED/RUNNING row는 0건이다. 별도 run `OADT2-ASTA-4d8bdb850e714ca59a0f5cf0824d3e06`의 Scheduler job 1개가 RUNNING이지만 이번 campaign 소유가 아니며 동시 작업으로 판단해 중단·변경하지 않았다.
- 주요 변경 파일: `db/adb/asta_llm_pkg.sql`, `db/adb/asta_pkg.sql`, `tools/asta_deploy_adb.py`, `tools/asta_sample_sql_verifier.py`, 신규 campaign/candidate 도구, UI/index, sample/campaign/runtime 계약 테스트, artifact와 이 handoff. git commit/push 없음.

## ASTA 결과서 11단계 소요시간 — 2026-07-06 완료

- 요청/결론: 최종 Markdown 결과서에 `ASTA_RUN_PROGRESS`의 11단계 `started_at`, `completed_at`, `elapsed_ms`를 근거로 단계별 소요시간을 추가했다. 저장 timing이 없는 단계는 `측정 불가/미기록`, 저장값이 실제 0인 단계만 `0.000 s`로 표시한다. 단계 합계와 run 시작→timing snapshot E2E를 별도로 표시하고 단계 중첩 가능성을 명시했다.
- 시간 단위: 결과서에 남아 있던 wall ms/elapsed us 표시도 모두 소수점 초(`s`)로 변환했다. JSON evidence의 기존 키/단위 계약은 변경하지 않았다.
- 변경 파일: `db/adb/asta_report_pkg.sql`, `db/adb/asta_pkg.sql`, 신규 `tests/test_asta_stage_timing_report.py`, 갱신 `tests/test_asta_ords_migration_contract.py`, 검증 모드를 추가한 `tools/asta_deploy_adb.py`, 이 handoff. 기존 미커밋 변경은 보존했다.
- strict TDD: 최초 신규 계약 `4 failed` RED, 최소 구현 후 `4 passed`; 레거시 ms/us 렌더링 계약 `1 failed` RED 후 GREEN. 관련 보고서/탭 회귀 `22 passed`, migration 포함 targeted `26 passed`. 전체 `398 passed, 기존 9 failed`, 신규 실패 0. Python compile와 `git diff --check` 통과했다. `.venv/bin/pytest` 실행 파일은 없어 최초 명령 1회가 exit 127이었고 표준 `.venv/bin/python -m pytest`로 전체 회귀를 완료했다.
- ADB 배포: `reports/asta_stage_timing_deploy/20260706/`에 기존 `ASTA_REPORT_PKG`, `ASTA_PKG` spec/body를 백업하고 두 패키지만 배포했다. PACKAGE/BODY 4개 모두 VALID, USER_ERRORS=0이다. schema/ORDS/static asset/Python runtime 변경은 없어 추가 migration, ORDS 재배포, 서비스 재시작은 하지 않았다.
- 배포 중 기존 run `OADT2-ASTA-4d8bdb850e714ca59a0f5cf0824d3e06`이 자체 60초 제한을 넘어 AFTER_EVIDENCE에서 31분 이상 Scheduler/library pin을 보유했다. bounded 계약에 따라 해당 job만 stop하고 run을 `FAILED / CANDIDATE_RUNTIME_LIMIT`로 종결했으며 다른 run은 변경하지 않았다.
- 신규 실환경 run: `OADT2-ASTA-TIMING-b3ed5a13790d46ac8aef`, `COMPLETED / NO_REWRITE`. bounded SELECT-only DUAL SQL이며 Source 실제 SQL elapsed `0.000007 s`, BEFORE_EVIDENCE stage `3.709 s`로 60초 미만이다. 단계 timing은 1/2 미기록, 3 `0.001 s`, 4 `3.709 s`, 5 미기록, 6 `0.000 s`(저장된 실제 0), 7/8 미기록, 9 `0.002 s`, 10 `0.017 s`, 11 `0.006 s`; 단계 합계 `3.735 s`, E2E snapshot `3.750 s`다.
- 실제 결과서: `reports/asta_stage_timing_deploy/20260706/OADT2-ASTA-TIMING-b3ed5a13790d46ac8aef.md`. 인증된 localhost API/view/download 모두 HTTP 200, API와 download Markdown SHA-256 동일(`f06dd4ef...f369e`), HTML view에 단계 표 노출, CSP와 attachment header 확인. 검증 파일은 같은 디렉터리의 `api_report.md`, `report_view.html`, `report_download.md`, `http_verification.json`, `stage_timing_smoke.json`이다.
- static served asset은 변경하지 않아 cache-bust/SHA 재배포 대상이 없다. HTTP API/view/download 성공으로 실행 서비스 가용성을 확인했다. git commit/push 없음.

## ASTA 소스 push 준비 — 2026-07-06

- 요청/결론: 현재 Real ASTA 변경을 점검해 원격 `ASTA` 브랜치에 push하는 작업을 시작했다. 시작 시 로컬은 `origin/ASTA` 대비 46커밋 ahead, 8커밋 behind였고 미커밋 ASTA 구현·테스트·문서가 함께 있었다.
- 원격 fetch 후 전체 회귀를 재실행했다. `PYTHONPATH=. UV_CACHE_DIR=/tmp/uv-cache uv run --no-project --offline --with pytest pytest -q` 결과는 `398 passed, 9 failed in 1.19s`로 직전 기준선과 동일하며 신규 실패는 0건이다.
- 9건은 기존 정적 계약/프록시 기대값/누락 `reports/asta_source_contract_latest.md` 관련 기준선 실패다. 최초 `.venv/bin/python -m pytest -q`는 `.venv`에 pytest가 없어 실행되지 않았고, 로컬 uv cache를 사용해 재현했다.
- `git diff --check`는 통과했다. 추적 예정 신규 파일의 credential 관련 문자열 검색 결과는 테스트/도구의 일반 보안 키워드뿐이며 `.secrets/`와 `reports/`는 계속 gitignore 대상이다.
- 다음 단계: 현재 변경을 로컬 커밋으로 보존하고 `origin/ASTA`를 merge한다. 원격이 일부 ASTA 파일을 삭제한 반면 로컬은 해당 기능을 확장했으므로 ASTA 구현은 보존하고 원격의 main/persona 변경을 함께 통합한 뒤 회귀 재실행 및 push한다.

## ASTA 소스 원격 통합 — 2026-07-06 완료

- 로컬 ASTA 변경은 커밋 `fb5b5c3`(`Implement ASTA production quality gates and reporting`)으로 보존했다.
- `origin/ASTA`의 8개 커밋을 merge commit `67f772f`로 통합했다. 충돌은 없었고 로컬 ASTA 구현은 유지하면서 원격의 persona analysis 라우터/UI와 관련 main 변경을 반영했다.
- 병합 후 전체 회귀는 `398 passed, 9 failed in 1.19s`로 병합 전과 동일하며 신규 실패 0건이다. Python `compileall`, `tuning_assistant.js`, `asta_report_tabs.js`, `persona_analysis.js`의 Node syntax, `git diff --check`가 모두 통과했다.
- push 직전 브랜치는 `origin/ASTA` 대비 48커밋 ahead, 작업 트리 clean이었다. 이 인계 갱신을 별도 커밋한 뒤 `ASTA` 브랜치를 push한다.

## Run b10 6단계 장기 실행 진단 — 2026-07-06

- 대상 `OADT2-ASTA-b10dd6e13ad24483ba52ba3c9980eb35`을 ADB에서 읽기 전용 조회했다. SQL/프롬프트/응답 원문은 출력하거나 인계에 기록하지 않았다.
- 제출 `2026-07-06 14:22:19 UTC`, Source Before evidence는 5.561초에 완료, Advisor는 SKIPPED, Vector는 0.002초에 완료됐다. 6단계 `LLM_REWRITE`는 `14:22:24 UTC`부터 RUNNING이고 7단계 `AFTER_EVIDENCE`에는 진입하지 않았다.
- LLM audit상 DIAGNOSIS는 16.5초에 RECEIVED, 첫 CANDIDATE_SQL은 6.4초에 `NO_REWRITE`로 RECEIVED, 두 번째 CANDIDATE_SQL은 3.9초에 1,449자 응답으로 RECEIVED됐다. 마지막 모델 응답은 `14:22:51.601 UTC`에 이미 끝났다.
- 약 11분 시점에도 Scheduler 세션은 active이며 blocking session은 없었다. 현재 PL/SQL stack은 `ASTA_PKG.EXECUTE_RUN → ASTA_LLM_PKG`이고 대기 이벤트는 `resmgr:cpu quantum`; 현재 PL/SQL SQL 통계는 CPU 중심이고 disk read는 극소수다.
- 결론: 화면상 “개선 SQL 만들기” 단계인 것은 맞지만 모델 응답 대기가 아니다. 두 번째 응답 후 `ASTA_LLM_PKG`의 SQL 정규화/구조 비교/guard 전후 후처리에서 CPU pathological path에 빠진 정황이다. 후보 SQL은 아직 `ASTA_RUNS.TUNED_SQL`에 저장되지 않았고 Source 후보 실행도 시작되지 않았다.
- 후보 응답은 주석 1쌍과 균형 잡힌 괄호 10쌍, WITH/SELECT 시작을 가진 형태다. 정확한 private routine line은 PL/Scope metadata가 없어 확정하지 못했지만 로컬 코드상 `normalize_sql_response`, `structural_sql_key`의 Oracle regex, `assert_safe_select` 호출 구간이 우선 조사 대상이다.
- candidate watchdog은 LLM 함수가 반환하고 7단계에 진입한 뒤에만 arm되므로 현재 6단계 CPU hang에는 timeout이 없다. 이번 요청은 진단만 수행했고 job stop, run 상태 변경, package 배포, 서비스 재시작은 하지 않았다.

## ASTA 11단계 진행 상세보기·단계 로그 UI — 2026-07-06 완료

- 요청/결론: 기본 진행 UI는 현재 단계 한 줄만 유지하고, `상세보기`를 열었을 때 11단계 전체 상태와 단계별 로그를 확인하도록 구현했다. `<details>`는 기본 닫힘이며 polling 재렌더링 중 사용자가 열어 둔 상태는 유지한다.
- 각 단계는 번호/한글명/내부 code/status, 시작·완료 시각, 저장 또는 실시간 계산 소요시간을 표시한다. 로그는 시작, 현재/종료 상태, redacted detail, 소요시간으로 구성하며 아직 시작하지 않은 단계도 PENDING으로 보인다.
- 단계 status/timestamp/detail signature가 바뀔 때만 브라우저 console에 `asta-stage-progress` 구조화 로그를 남긴다. SQL literal/bind/SQL text는 기존 redaction을 적용한다.
- `normalizeSteps`가 서버의 `started_at`, `completed_at`, `elapsed_ms`를 보존하도록 변경했다. 서버/DB schema/package는 변경하지 않았으며 기존 `ASTA_RUN_PROGRESS` 11단계 데이터만 사용한다.
- cache-buster는 `tuning_assistant.js?v=20260706_progress_details1`이다. 변경 파일: `static/js/extensions/tuning_assistant.js`, `static/index.html`, 신규 `tests/test_asta_progress_details.py`, 관련 정적/cache 계약 테스트, 이 handoff.
- TDD RED `4 failed` 확인 후 focused `49 passed`; Node syntax와 `git diff --check` 통과. 전체 회귀 `403 passed, 기존 9 failed in 1.19s`, 신규 실패 0건이다.
- `select-ai-test.service`는 PID 822785로 active이고 8000 포트 LISTEN 상태다. 최초 `/` 포함 HTTP 검증은 응답 지연으로 종료했지만 정적 자산만 10초 제한으로 재검증해 HTTP 200, 133,329 bytes, workspace 파일과 byte-identical을 확인했다. 서비스 재시작, 현재 Run 중지, DB/ORDS 변경, commit/push는 수행하지 않았다.

## ASTA 진행 상세 UI Drawer 전환 — 2026-07-06 완료

- 사용자 피드백에 따라 진행 카드 내부의 11단계 `<details>`를 제거했다. 기본 화면은 compact 현재 단계/전체 시간/Run ID와 `진행 상세` 버튼만 표시한다.
- `진행 상세`는 우측 고정 Drawer dialog를 연다. 11단계 상태·timing·로그는 Drawer에서만 보이며 닫기 버튼, backdrop 클릭, Escape로 닫는다. polling 재렌더링 중 열린 상태와 scrollTop을 유지한다.
- 모바일 <=700px에서는 하단에서 열리는 92dvh sheet로 전환하고 compact 상태에서 긴 detail/Run ID를 숨긴다. 단계 code를 숨기고 timing을 1열로 바꾼다.
- 단계별 redacted console log와 서버 progress timing 보존 계약은 유지했다. cache-buster는 `tuning_assistant.js?v=20260706_progress_drawer1`이다.
- TDD Drawer RED `4 failed` 확인 후 focused `55 passed`; Node syntax와 diff check 통과. 전체 `403 passed, 기존 9 failed in 1.20s`, 신규 실패 0건이다.
- 실행 서비스 static asset은 HTTP 200, 137,726 bytes이며 workspace 파일과 byte-identical이다. 서비스 재시작, DB/ORDS 변경, 현재 Run 중지, commit/push는 수행하지 않았다.

## ASTA 진행 UI 초기 노출·polling 깜빡임 수정 — 2026-07-06 완료

- 초기 `READY/IDLE/PENDING`이며 실제 진행 row가 없는 경우 progress anchor를 hidden 처리하고 DOM을 비운다. 분석 제출 후 RUNNING/QUEUED 상태부터 compact 진행 UI가 표시되며 초기화 시 다시 숨는다.
- polling tick마다 `innerHTML`을 교체하던 원인을 제거했다. 단계 status/detail/started/completed/elapsed의 render signature가 동일하면 기존 DOM과 Drawer를 보존하고 현재 단계·전체·각 단계 경과시간 textContent만 갱신한다.
- 실제 단계 전환, 오류, 로그 변화가 있을 때만 Drawer DOM을 다시 만들며 기존 open 상태와 scrollTop 보존도 유지한다. cache-buster는 `20260706_progress_drawer3`이다.
- 신규 계약 RED `2 failed`와 anti-flicker RED `1 failed` 확인 후 focused `51 passed`. Node syntax/diff check 통과, 전체 `405 passed, 기존 9 failed in 1.20s`, 신규 실패 0건이다.
- 실행 서비스 asset은 HTTP 200, 140,973 bytes이고 workspace와 byte-identical이다. 서비스 재시작, DB/ORDS 변경, 현재 Run 중지, commit/push 없음.

## ASTA 단계 전환 깜빡임 제거 — 2026-07-06 완료

- 잔여 원인은 단계 status가 바뀔 때 render signature가 달라져 같은 Run의 compact bar와 Drawer 전체 `innerHTML`을 교체하던 것이었다.
- 같은 Run ID 동안에는 DOM 골격을 한 번만 만들고 이후 단계 전환도 `refreshProgressView`가 현재 label/dot/class, 해당 단계 status/timing/log만 부분 갱신한다. 전체 DOM 생성은 새 Run 시작 시 한 번만 수행한다.
- Drawer 카드에 안정적인 `data-progress-step-card` key를 부여했다. 실행 중 elapsed는 timing text만 갱신하고 로그 HTML에는 매 tick 추가하지 않으며, 로그 내용이 실제로 바뀐 카드만 부분 교체한다.
- cache-buster는 `20260706_progress_drawer4`. focused `51 passed`, Node syntax/diff check 통과, 전체 `405 passed, 기존 9 failed in 1.21s`, 신규 실패 0건이다.
- 실행 서비스 asset HTTP 재검증은 localhost 응답 지연으로 종료했다. 직전 drawer3 served-byte 검증은 통과했으며 정적 파일은 workspace에서 직접 제공된다. 서비스 재시작, DB/ORDS 변경, Run 중지, commit/push 없음.

## ASTA 4단계 ORA-06502 수정·배포 — 2026-07-07 완료

- 사용자 보고는 4단계 Source evidence의 `ORA-06502: character string buffer too small`다. request audit에서 같은 SQL fingerprint의 실제 run 3건이 QUEUED/RUNNING 후 약 10~12초 안에 반복 FAILED하고 proxy가 모두 `PAYLOAD_LIMIT`로 분류한 것을 확인했다. 일시적 장애가 아니다. SQL 원문은 조회·기록하지 않았다.
- 실패 SQL은 18,411자/UTF-8 18,653 bytes로 DB Link 32,767-byte 한도 이내였다. 최초 Bridge/Source 진단 배포 후 동일 SQL 재현에서 backtrace `ORCLAI.ASTA_SOURCE_PKG body line 500 → 1206`을 확보했다. 이는 `sql_bind_placeholder_count` 호출과 내부 `DBMS_LOB.SUBSTR(...,1,...)` 대입 지점이다. SQL 문자 스캐너가 한 문자를 담는 변수를 `VARCHAR2(1)` byte로 선언해 한글 등 AL32UTF8 멀티바이트 문자를 만날 때 ORA-06502를 발생시킨 것이 정확한 원인이다.
- `db/adb/asta_source_bridge_pkg.sql`에 4000-character chunk 기반 `clob_to_dblink_varchar2`를 추가했다. 누적 `LENGTHB`를 검사해 32767 bytes 이하는 원문 그대로 전달하고, 초과하면 모호한 ORA-06502 대신 명시적인 DB Link payload-limit 오류를 반환한다.
- Source의 `sql_bind_placeholder_count` 문자 변수 3개와 `top_level_sql_text` 문자/quote 변수 2개를 `VARCHAR2(4)`로 변경했다. Source Bridge와 Source package 예외 JSON에는 `DBMS_UTILITY.FORMAT_ERROR_BACKTRACE`를 추가했다. SQL/bind 원문은 포함하지 않는다.
- Source `ASTA_SOURCE_PKG`와 ADB `ASTA_SOURCE_BRIDGE_PKG`만 백업 후 배포했다. 양쪽 PACKAGE/BODY는 모두 VALID, USER_ERRORS=0이다. Source FULL_RESULT 기본 smoke와 실제 ADB→DB Link→Source 한글 주석 smoke는 `COMPLETED`, digest `COMPLETED`다. 배포/검증 artifact는 `reports/asta_deploy_source/20260706T151449Z/`, `reports/asta_deploy_source/20260706T152106Z/`, `reports/asta_ora06502_deploy/20260707/`에 있다.
- Bridge BODY 첫 배포는 기존 Scheduler 2개가 package library lock을 잡아 120초 timeout됐으며 기존 BODY는 VALID 상태로 유지됐다. `b10...` 6단계 LLM CPU loop와 `2254...` 7단계 후보 실행은 자체 60초 제한을 수시간 초과한 stale job이어서 두 job만 stop하고 각 run/progress를 `LLM_RUNTIME_LIMIT`/`CANDIDATE_RUNTIME_LIMIT` FAILED로 정합화했다. 이후 Bridge 배포는 즉시 완료됐다.
- 동일 고객 SQL은 수정 후 기존 ORA-06502 지점을 통과했으나 FULL_RESULT와 BOUNDED 모두 120초를 초과했다. 이는 별도의 Source SQL 실행 성능 문제이며 검증 호출을 취소했다. `same_sql_retest.json`에 SQL 원문 없이 기록했다. 멀티바이트 회귀는 짧은 한글 주석 SELECT로 동일 실경로에서 2.3초 내 완료했다.
- 신규 `tests/test_asta_source_bridge_multibyte_payload.py`는 3건이다. 관련 focused 회귀 `78 passed`; 전체 회귀 `408 passed, 기존 9 failed in 1.20s`, 신규 실패 0건이다. 최종 `ALL_SCHEDULER_RUNNING_JOBS`의 ASTA job은 0건이며 package lock blocker도 없다. `git diff --check` 통과. 서비스 재시작, ORDS/schema 변경, commit/push는 수행하지 않았다.

## ASTA 분석 진행상태 compact 재구성 — 2026-07-07 완료

- 기본 진행 UI를 높이 32px의 단일 행으로 축소했다. 표시 정보는 상태점, `현재/전체 단계`(예: `4/11`), 현재 단계명, 단계 경과시간, 전체 경과시간, `상세` 버튼만 남겼다.
- 정상 실행 중 긴 detail은 기본 행에서 숨기고 title과 Drawer에서 확인하게 했다. 실패 시에만 축약 오류 detail을 기본 행에 표시한다. Run ID와 복사 버튼은 기본 행에서 제거하고 Drawer 헤더로 이동했다.
- 같은 Run의 DOM을 유지하는 기존 `refreshProgressView` 부분 갱신 구조에 단계 번호와 단계 경과시간 갱신을 추가했다. polling/단계 전환 시 전체 DOM 재생성과 깜빡임 방지 계약은 유지한다.
- 모바일에서도 동일 단일 행을 사용하고 긴 실패 detail만 숨긴다. Drawer의 11단계 timing/log와 열림/scroll 보존 동작은 변경하지 않았다.
- cache-buster는 `20260707_progress_compact1`. 변경 파일은 `static/js/extensions/tuning_assistant.js`, `static/index.html`, 진행/UI/cache 계약 테스트와 이 handoff다.
- 신규 계약 RED `2 failed` 확인 후 UI focused `52 passed`. Node syntax, `git diff --check` 통과. 전체 회귀 `409 passed, 기존 9 failed in 1.19s`, 신규 실패 0건이다.
- 실행 서비스는 active/PID 822785/8000 LISTEN이며, localhost 정적 asset HTTP 검증 결과 142,967 bytes와 SHA-256 `a61f89ad...c1a6b7e`가 workspace 파일과 동일했다. 서비스 재시작, DB/ORDS 변경, commit/push는 수행하지 않았다.

## ASTA 진행시간 +540분 보정·SQL 변경 diff — 2026-07-07 완료

- 진행 중 소요시간에 정확히 540분이 더해진 원인은 ADB가 반환한 timezone 없는 Oracle timestamp(`YYYY-MM-DD HH24:MI:SS.FF`)를 브라우저가 Asia/Seoul 로컬 시각으로 해석한 것이었다. ASTA timestamp에 timezone이 없으면 UTC로 정규화하고 microseconds를 JS milliseconds로 안전하게 줄인 뒤 epoch를 계산하도록 수정했다. 이미 `Z`/offset이 있는 ISO timestamp는 그대로 유지한다.
- Asia/Seoul Node runtime에서 `2026-07-06 15:05:11.432403`이 `2026-07-06T15:05:11.432Z`와 같은 epoch가 되는 실행 테스트를 추가했다. compact 단계/전체 소요시간과 Drawer 시작·완료 시각 모두 같은 parser를 사용한다.
- 결과서 탭에 `SQL 변경`을 `요약` 다음에 추가했다. 기존 결과서의 `SQL 변경 내용`과 `변경 위치`를 추출해 “무엇을 어디서 바꿨나” 박스로 먼저 보여주고, 이어서 튜닝 전/후 SQL fenced block을 줄 단위 diff로 표시한다.
- diff는 원본/튜닝 양쪽 줄 번호, `-` 제거, `+` 추가, 추가·삭제 줄 수를 제공한다. DOM textContent만 사용해 SQL/설명에서 HTML/스크립트를 실행하지 않는다. 긴 SQL은 40줄 bounded lookahead 알고리즘으로 비교해 브라우저의 quadratic memory 사용을 피한다.
- cache-buster는 `asta_report_tabs.js?v=20260707_sql_diff1`, `tuning_assistant.js?v=20260707_progress_time_diff1`이다. 변경 파일은 두 JS, `static/index.html`, DOM/time/cache 계약 테스트와 이 handoff다.
- RED `3 failed` 후 time/diff focused `60 passed`, 추가 Asia/Seoul/diff focused `17 passed`. 전체 회귀 `412 passed, 기존 9 failed in 1.29s`, 신규 실패 0건. 두 JS syntax와 `git diff --check` 통과.
- 실행 서비스 static asset은 HTTP로 각각 145,440/16,725 bytes를 반환했고 workspace와 SHA-256이 동일했다. 서비스 재시작, DB/ORDS 변경, commit/push는 수행하지 않았다.

## 진행 UI 미반영 확인 — 2026-07-07 브라우저 기존 세션

- 사용자 피드백 후 실행 서비스 `/`를 다시 받아 workspace `static/index.html`과 SHA-256/bytes가 동일함을 확인했다. live HTML은 `20260707_sql_diff1`, `20260707_progress_time_diff1`을 참조하며 JS 응답은 `Cache-Control: no-store, no-cache`다. 중복 ASTA UI asset도 없다.
- 당시 최신 run `OADT2-ASTA-50349ee60647410e9c5ab69c01c97789`의 DB 저장값을 읽기 전용 확인했다. DB now `2026-07-06 15:42:19.742 +00:00`, 6단계 시작 `15:41:45.679 UTC`, elapsed_ms는 RUNNING이라 null로 정상이며 실제 경과는 약 34초다. 서버 progress 데이터에 +540분은 없다.
- 결론: 해당 Run은 변경 JS가 배포되기 전에 이미 열려 있던 브라우저 탭에서 시작되어, 탭 메모리의 이전 `parseTimeMs`/UI 코드를 계속 사용하고 있다. 현재 Run은 중단·변경하지 않았다. 진행 중 새로고침하면 UI가 Run을 자동 복구하지 않으므로 완료 후 새로고침 또는 새 탭에서 다음 Run부터 최신 UI를 확인하는 것이 안전하다.

## ASTA Drawer 단계 카드 compact 전환 — 2026-07-07 완료

- 사용자 의도가 기본 진행 pill이 아니라 상세 Drawer 안 11개 단계 카드 크기임을 확인해 각 카드를 `<details>` 기반 32px 요약 행으로 변경했다.
- 닫힌 행은 단계 번호, 단계명, 소요시간, 상태, 펼침 화살표만 표시한다. 클릭 시에만 내부 code, 시작/완료 시각, 단계 로그가 보인다. RUNNING/FAILED/ERROR/BLOCKED/REJECTED 단계는 상태 전환 순간 자동으로 열고 완료 전환 시 다시 접는다. 사용자가 수동으로 닫은 RUNNING 단계는 동일 상태 polling에서 다시 열지 않는다.
- 카드 gap 8→4px, 번호 24→18px, radius/padding/font를 축소했다. Drawer 폭 540→480px, header/body/current banner padding도 함께 줄였다. 11단계 전체를 훨씬 적은 세로 공간에서 확인할 수 있다.
- cache-buster는 `tuning_assistant.js?v=20260707_progress_time_diff2`. focused `62 passed`; 전체 회귀 `413 passed, 기존 9 failed in 1.25s`, 신규 실패 0건. JS syntax와 diff check 통과.
- 실행 서비스 asset 146,706 bytes와 workspace SHA-256 `811d979e...92b50b`가 동일하다. 현재 열려 있는 기존 브라우저 탭은 메모리의 이전 JS를 유지하므로 새로고침/새 탭 이후 적용된다. DB/ORDS/서비스 재시작/commit/push 없음.

## Run 71572 단계별 0초 진단 — 2026-07-07

- 대상 `OADT2-ASTA-71572f297bb1404ca124a58a387b1246`을 ADB에서 읽기 전용 조회했다. run은 COMPLETED, created→completed 37.739초, 실제 execute started→completed 36.444초다.
- 4 BEFORE_EVIDENCE 5,023ms, 6 LLM_REWRITE 16,169ms, 7 AFTER_EVIDENCE 15,187ms로 세 단계 합계 36.379초이며 execute 시간의 약 99.8%다.
- 6단계 LLM audit는 DIAGNOSIS 7,721.971ms, CANDIDATE_SQL 1차 4,645.356ms(NO_REWRITE), 2차 3,777.122ms로 합계 약 16.144초다. 7단계 안에서는 REPAIR_SQL 10,087.62ms 후 나머지 약 5.1초가 후보 Source evidence 처리다.
- 나머지 실측은 3 SQL_GUARD 4ms, 8 비교 5ms, 9 Vector KB 2ms, 10 결과서 생성 27ms, 11 Vector 저장 8ms다. 현재 UI `formatDuration`이 1초 미만도 초 단위 소수 1자리로 표시해 모두 `0.0초`로 반올림된다.
- 1 REQUEST_RECEIVED와 2 ORDS_DISPATCH는 작업 구간이 아니라 접수/전달 상태 마커라 started_at=completed_at이고 elapsed_ms는 null이다. 5 SQL_TUNING_ADVISOR는 SKIPPED이며 동일 시각 marker다. 따라서 이 세 단계의 0초는 “실행이 매우 빠름”이 아니라 “독립 소요시간 미측정/생략” 의미다. 이번 요청은 진단만 수행했고 소스/DB/Run 상태는 변경하지 않았다.

## 단계 소요시간 millisecond/상태 표시 — 2026-07-07 완료

- 사용자 승인에 따라 단계 카드 전용 `formatStepElapsed`를 추가했다. 1초 미만 실측은 0.0초로 반올림하지 않고 정수 ms로 표시하며, 1ms 미만 실측은 `<1ms`로 표시한다.
- SKIPPED는 `생략`, elapsed_ms가 없고 동일 timestamp로 찍힌 접수/전달 marker는 `미측정`, 미시작 PENDING은 `-`로 구분한다. 단계 카드 요약, 펼친 로그, compact 현재 단계에 동일 규칙을 적용했다. 전체 경과시간은 기존 초/분 형식을 유지한다.
- Run 71572 기준 예상 표시는 1/2 `미측정`, 3 `4ms`, 4 `5.0초`, 5 `생략`, 6 `16.2초`, 7 `15.2초`, 8 `5ms`, 9 `2ms`, 10 `27ms`, 11 `8ms`다.
- cache-buster는 `tuning_assistant.js?v=20260707_progress_time_diff3`. focused `58 passed`; 전체 회귀 `414 passed, 기존 9 failed in 1.24s`, 신규 실패 0건. JS syntax/diff check 통과.
- 실행 서비스 asset 147,359 bytes와 workspace SHA-256 `d16e643a...29c759`가 동일하다. DB/ORDS/서비스 재시작/commit/push 없음.

## SQL 변경 탭 위치·좌우 비교 전환 — 2026-07-07 완료

- 결과서 탭 순서를 `요약 → 튜닝 전 → SQL 변경 → 튜닝 후 → 상세 분석 → 객체 정보`로 변경했다.
- 기존 단일 unified diff를 좌우 2-pane 비교로 교체했다. 왼쪽은 튜닝 전 원본 SQL, 오른쪽은 튜닝 후 SQL이며 각 창에 독립 줄 번호와 code를 표시한다. 삭제 줄은 왼쪽 red, 추가 줄은 오른쪽 green, 상대편이 없는 줄은 빈 hatch row로 표시한다.
- bounded lookahead diff 결과의 연속 remove/add block을 `alignSqlDiffRows`로 pair해 두 창의 대응 변경이 같은 세로 위치에 오도록 했다. 공통 줄도 양쪽 같은 행에 유지한다. 긴 SQL은 각 pane에서 가로 스크롤하고 작은 화면에서도 좌우 구조를 유지한다.
- 상단의 “무엇을 어디서 바꿨나”, 변경 위치/내용, 추가·삭제 줄 수 요약은 그대로 유지한다. SQL 렌더링은 계속 textContent만 사용한다.
- cache-buster는 `asta_report_tabs.js?v=20260707_sql_diff2`, `tuning_assistant.js?v=20260707_progress_time_diff4`. focused `33 passed`; 전체 `414 passed, 기존 9 failed in 1.24s`, 신규 실패 0건. 두 JS syntax/diff check 통과.
- 실행 서비스의 두 asset은 workspace와 각각 SHA-256 `059d5c4f...d25a3a7`, `2e667676...117b01b`로 동일하다. DB/ORDS/서비스 재시작/commit/push 없음.

## SQL 입력·ASTA 결과 접기 UI — 2026-07-07 완료

- `SQL 분석 입력`과 `ASTA 분석 결과`를 각각 독립적인 `<details>` 섹션으로 변경했다. 제목 행 전체를 클릭하거나 키보드로 접고 펼칠 수 있으며 방향 아이콘과 focus 표시를 제공한다.
- 분석 결과가 정상 렌더링되는 시점에만 입력 섹션을 자동으로 접고 새 결과 섹션은 펼친 상태로 표시한다. 진행 polling은 접힘 상태를 건드리지 않으며, 결과 헤더의 맨 위/맨 아래/다운로드/초기화 버튼은 summary 밖에 유지해 접기 동작과 충돌하지 않는다.
- `신규분석(초기화)`은 결과를 비우고 입력 섹션을 다시 펼친다. 접힌 결과 카드는 기존 최소 높이를 제거해 제목 한 줄만 남는다.
- cache-buster는 `tuning_assistant.js?v=20260707_collapsible_sections1`. 신규 접기 계약 RED `4 failed` 후 focused `62 passed`; 전체 회귀 `418 passed, 기존 9 failed in 1.24s`, 신규 실패 0건이다. JS syntax와 `git diff --check`도 통과했다.
- 실행 서비스 asset은 150,289 bytes, SHA-256 `44268c6f...d127c6`로 workspace와 byte-identical이며 `/`도 새 cache version을 참조한다. DB/ORDS 변경, 서비스 재시작, commit/push는 수행하지 않았다.

## Oracle 튜닝 권고 비활성 표시 제거 — 2026-07-07 완료

- `SQL 분석 입력` 제목의 `Oracle 튜닝 권고: 사용 안 함` badge와 전용 CSS를 제거했다. 요청 payload의 `run_advisor:false`, `use_sqltune:false` 계약과 백엔드 동작은 변경하지 않았다.
- cache-buster는 `tuning_assistant.js?v=20260707_advisor_badge_removed1`. 관련 `55 passed`, 전체 `418 passed, 기존 9 failed in 1.25s`, 신규 실패 0건이며 JS syntax/diff check를 통과했다.
- 실행 서비스 asset은 149,836 bytes, SHA-256 `c8dc609b...938d25`로 workspace와 byte-identical이고 제거 문구/id가 없음을 확인했다. DB/ORDS 변경, 서비스 재시작, commit/push는 수행하지 않았다.

## 객체 정보 중복 섹션·결과 버튼 배치 수정 — 2026-07-07 완료

- 결과서에 `## 테이블 통계 및 인덱스 정보`가 중복되면 기존 분류기가 해당 heading을 모호한 구역으로 제외해 `객체 정보`가 비거나 일부만 보이는 원인을 수정했다. 객체 metadata 구역에 한해서는 중복 section을 원문 순서대로 모두 표시하며, SQL 전/후 등 다른 중복 heading의 fail-closed 동작은 유지한다.
- DOM 회귀 fixture에 정상 객체 통계 뒤 동일 heading의 object_info 오류 구역을 추가해 두 내용이 모두 `객체 정보` 탭에 표시됨을 검증했다.
- 결과 영역의 `맨 위`, `맨 아래` 버튼과 scroll handler를 제거했다. `보고서 다운로드`는 결과 헤더에 유지하고, `신규분석(초기화)`은 결과로 이동시키지 않아 상단의 완료 버튼 바로 옆에 표시되도록 했다.
- cache-buster는 `asta_report_tabs.js?v=20260707_object_sections1`, `tuning_assistant.js?v=20260707_result_actions1`. focused `62 passed`와 Node DOM PASS, 전체 `418 passed, 기존 9 failed in 1.24s`, 신규 실패 0건이다. 두 JS syntax와 diff check도 통과했다.
- 실행 서비스 자산은 각각 18,801/149,276 bytes이며 workspace와 SHA-256 `dd338efd...38132e`, `39e38e95...affef`로 동일하다. DB/ORDS 변경, 서비스 재시작, commit/push는 수행하지 않았다.

## 객체 통계/인덱스 미수집 원인 진단 — 2026-07-07

- 최신 5개 COMPLETED Run을 ADB에서 읽기 전용 점검했다. 모든 Run의 `artifacts.source_evidence.object_info`와 결과서 `## 테이블 통계 및 인덱스 정보` 제목은 존재하므로 UI 탭/결과서 생성 누락은 아니다.
- 최신 `OADT2-ASTA-72aaadb0d8104db089b346883b5cf10d`는 plan object `DSNT.TGP_ORDER_D` 1개를 수집했지만 num_rows/blocks가 null이고 indexes가 0개였다. Source의 현재 `collect_object_info`가 `ALL_TAB_STATISTICS`, `ALL_TAB_COLUMNS`, `ALL_INDEXES`를 사용한다.
- Source dictionary를 DB Link로 확인한 결과 `TGP_ORDER_D`는 ALL_*에서 table/stat/column/index가 모두 0건이지만 DBA_*에서는 table 1, num_rows 2,698,893, blocks 69,980, columns 43, indexes 5다. `TGP_STYGRP_M`도 ALL_* 0건, DBA_*에서는 table 1/rows 10,833/blocks 193/columns 12/index 1이다. 반면 정상 표시된 `TSE_SALE_MON_S`, `TSE_INOUT_S`는 ALL_*와 DBA_* 결과가 일치한다.
- 결론: 실행계획 하위 객체는 보이지만 ALL_* dictionary 가시성 밖인 객체가 있어 현재 package가 빈 metadata를 만든다. Source 계정은 DBA_*를 조회할 수 있으므로 `collect_object_info`의 4개 dictionary를 DBA_*로 전환하면 해결 가능하다. 이번 요청은 진단으로 처리해 source 수정/compile/deploy는 수행하지 않았다.

## Source 객체 통계/인덱스 수집 수정 배포 — 2026-07-07 완료

- 사용자 승인으로 `db/source/asta_source_pkg.sql`의 `collect_object_info` dictionary를 `ALL_TAB_STATISTICS/COLUMNS/INDEXES/IND_COLUMNS`에서 `DBA_TAB_STATISTICS/COLUMNS/INDEXES/IND_COLUMNS`로 변경했다. 회귀 계약은 DBA_* 4개 존재와 ALL_* 0개를 고정한다.
- 배포 전 실제 Scheduler job 2건이 각각 7단계 AFTER_EVIDENCE 약 47분, 6단계 LLM_REWRITE 약 46분으로 장기 정지해 있었다. 추가 사용자 승인 후 두 job만 force stop하고 진행 row와 Run을 각각 `CANDIDATE_RUNTIME_LIMIT`, `LLM_RUNTIME_LIMIT` FAILED로 정합화했다. 둘 다 running job 0을 확인했다. 실제 job이 없고 단계 11 DONE인 과거 RUNNING 잔여 row 3건은 변경하지 않았다.
- SQLcl 저장 Source 연결 `DSNT`로 기존 `ASTA_SOURCE_PKG` DDL을 백업한 뒤 현재 source를 compile했다. PACKAGE/PACKAGE BODY 모두 VALID, USER_ERRORS=0, 배포 body는 DBA dictionary ref 4개/ALL ref 0개다. ADB/ORDS와 다른 package는 변경하지 않았다.
- 직접 `DSNT.TGP_ORDER_D` smoke는 Source 계정에 direct SELECT 권한이 없어 ORA-00942였고, 이는 원 진단과 일치한다. Source 계정에 공개되고 해당 base table을 참조하는 `DSNT.VIF_WHOLESALE_S`를 이용한 1행 smoke로 최종 검증했다.
- 최종 smoke `OBJDICT20260706163541`: run COMPLETED, object_info COMPLETED, `DSNT.TGP_ORDER_D` num_rows 2,698,893, blocks 69,980, columns 43, indexes 5를 반환했다. 최종 artifact/backup/log는 `reports/asta_object_dictionary_deploy/20260706T163541Z/`다. 앞선 두 smoke 실패 artifact도 같은 상위 디렉터리에 보존했다.
- focused metadata `2 passed`, multibyte bridge `3 passed`, 전체 `418 passed, 기존 9 failed in 1.28s`, 신규 실패 0건. `git diff --check` 통과. 서비스 재시작/commit/push 없음.

## ASTA 입력·결과 UI surface 통일 점검 — 2026-07-07 완료

- `SQL 분석 입력`은 22px radius/강한 shadow/custom white였고 `ASTA 분석 결과`는 Redwood 10px radius/no-shadow surface여서 서로 다른 카드처럼 보였다. 두 영역에 공통 `.tuning-card, .tuning-report-card` 계약을 적용해 `var(--radius-lg)`, `var(--border)`, `var(--surface)`, `box-shadow:none`으로 통일했다.
- 두 접힘 제목 행은 동일한 52px 최소 높이, spacing, section-title typography, chevron/focus를 사용한다. 입력 본문과 결과 본문 모두 동일 border 분리선을 사용한다. 720/390px portrait와 low-height landscape에서 입력만 16/14/12px로 바뀌던 override도 모두 Redwood radius로 고정했다.
- 전체 점검에서 섞여 있던 blue custom input theme를 Redwood 토큰으로 정리했다. 화면 배경 accent, 입력/SQL border와 surface, primary/secondary 버튼을 `--primary/--surface/--border` 기반으로 바꾸고 form/button focus-visible 및 disabled 상태를 추가했다. 진행 성공/실패 의미색은 유지했다.
- 모바일 결과 action은 다운로드 하나인데 2열 grid라 절반 폭이던 문제를 1열 full-width로 변경했다. 1100px 이하의 3번째 설정 필드는 2열의 반쪽이 아니라 전체 행을 차지하도록 했다. 모바일 shell 배경도 surface token을 사용한다.
- cache-buster는 `tuning_assistant.js?v=20260707_ui_surface_unified1`. focused UI `64 passed`, Node DOM PASS, 전체 `420 passed, 기존 9 failed in 1.25s`, 신규 실패 0건. JS syntax/diff check 통과.
- 실행 서비스 asset은 149,999 bytes, SHA-256 `cbf24a52...62582f9`로 workspace와 byte-identical이고 `/`도 새 cache version을 참조한다. DB/ORDS/서비스 재시작/commit/push 없음.

## ASTA 드롭다운 화살표 inset 조정 — 2026-07-07 완료

- 브라우저 기본 select 화살표가 오른쪽 테두리에 붙어 보이던 문제를 해결했다. ASTA의 세 select에 동일한 14px Redwood muted chevron을 적용하고 `background-position:right 16px center`, `padding-right:42px`로 위치와 텍스트 여백을 고정했다.
- `appearance:none`과 data SVG를 사용해 브라우저별 native arrow 위치 차이를 제거했고 모바일의 shorthand padding보다 높은 selector specificity로 동일 inset을 유지한다.
- cache-buster는 `tuning_assistant.js?v=20260707_dropdown_chevron1`. focused `58 passed`, 전체 `421 passed, 기존 9 failed in 1.24s`, 신규 실패 0건. JS syntax/diff check 통과.
- 실행 서비스 asset은 150,474 bytes, SHA-256 `b968168e...db5d0d`로 workspace와 byte-identical이다. DB/ORDS/서비스 재시작/commit/push 없음.

## 결론 판정 강조·판정 기준 도움말 — 2026-07-07 완료

- 결과서 전체에서 canonical `비교 판정: verdict=...`를 우선 추출하고 legacy `최종 판정:`도 지원하는 allowlist parser를 추가했다. 허용 판정은 IMPROVED, NOT_IMPROVED, CANDIDATE_FAILED, NON_EQUIVALENT, NO_REWRITE, INSUFFICIENT_EVIDENCE 6개뿐이며 임의 문구는 판정으로 사용하지 않는다.
- `요약` 탭의 `결론` 제목 옆에 접근 가능한 `?` 버튼을 추가했다. 현재 판정은 바로 아래 badge로 강조하고 의미와 권장 조치를 함께 표시한다. success/warning/danger 의미색을 사용한다.
- `?`를 누르면 6개 판정의 `판정/의미/권장 조치` 표가 열리고 다시 누르면 닫힌다. 현재 판정 행은 강조하며 `aria-expanded`, `aria-controls`, `aria-current`를 제공한다. 모바일은 요약을 1열로 바꾸고 표는 640px 최소 폭의 가로 스크롤로 읽을 수 있게 했다.
- 실제 저장 결과서 fixture 3개에서 IMPROVED, INSUFFICIENT_EVIDENCE, NO_REWRITE 추출을 확인했다. DOM 계약은 6개 행, 현재 badge/설명, toggle open/close와 6개 문구 정확성을 검증한다.
- cache-buster는 두 자산 모두 `20260707_verdict_guide1`. focused `65 passed`, Node DOM PASS, 전체 `421 passed, 기존 9 failed in 1.26s`, 신규 실패 0건. 두 JS syntax/diff check 통과.
- 실행 서비스 자산은 tabs 23,583 bytes/SHA-256 `3e13ebab...3f341`, assistant 153,309 bytes/SHA-256 `358005b1...476ba`로 workspace와 각각 byte-identical이다. DB/ORDS/서비스 재시작/commit/push 없음.

## 결론 판정 도움말 말풍선 전환 — 2026-07-07 완료

- `?` 클릭 시 결론 아래 문서 흐름을 밀어내던 inline 도움말을 버튼에 고정된 speech-bubble popover로 변경했다. 결론 heading row 안에 button anchor를 두고 표는 absolute overlay로 표시한다.
- 말풍선은 border/shadow/꼬리, 최대 720px 폭, 최대 62vh 높이와 내부 스크롤을 사용한다. 꼬리는 scroll container에 잘리지 않도록 도움말 내부가 아니라 button anchor의 open state pseudo-element로 렌더링한다.
- 모바일은 viewport 기준 폭과 위치를 보정하고 기존 640px 기준표 가로 스크롤을 유지한다. toggle의 aria-expanded/controls, 6개 판정, 현재 행 강조 동작은 그대로다.
- cache-buster는 두 자산 모두 `20260707_verdict_popover1`. focused `65 passed`, Node DOM PASS, 전체 `421 passed, 기존 9 failed in 1.26s`, 신규 실패 0건. 두 JS syntax/diff check 통과.
- 실행 서비스 자산은 tabs 24,053 bytes/SHA-256 `52cfed21...6755f`, assistant 154,237 bytes/SHA-256 `59c87bae...8f3bf`로 workspace와 각각 byte-identical이다. DB/ORDS/서비스 재시작/commit/push 없음.

## 사이트 노출 상태 점검 — 2026-07-07

- 사용자 제보에 따라 서버 측을 읽기 전용 점검했다. `select-ai-test.service`는 PID 822785로 active/running이고 `0.0.0.0:8000`에서 LISTEN 중이다.
- `/`는 HTTP 200, 3,962 bytes이며 실행 응답과 workspace `static/index.html`의 SHA-256이 일치한다. 핵심 Redwood/layout CSS와 local JS 9개도 모두 HTTP 200이고 응답시간은 약 1~2ms다.
- `tuning_assistant.js`, `asta_report_tabs.js`는 Node 문법 검사를 통과했고 report-tabs DOM 회귀도 PASS다. 외부 jsDelivr Chart.js/XLSX도 HTTP 200, 약 0.03~0.04초였다.
- 당일 서비스 로그에 traceback/500은 없고 화면과 무관한 source map/favicon 404만 있다. 외부 10.100.4.162의 `/` health 요청도 계속 200이다.
- 인증은 활성 상태다. 비로그인 `/api/auth/status`는 HTTP 200과 `authenticated=false`, 보호 API의 401은 정상 계약이며 브라우저에는 접근 키 입력 overlay가 표시되어야 한다.
- 결론: 현재 서버/정적 자산/API 진입 경로에는 사이트 미노출을 재현할 장애가 없다. 남은 가능성은 기존 브라우저 탭 메모리/캐시, 인증 overlay 표시 상태, 사용자 브라우저 측 오류다. 서비스 재시작이나 코드/DB/ORDS 변경은 수행하지 않았다.
- 변경 파일은 이 handoff뿐이며 commit/push는 없다.

## BATCH 샘플 SQL 5개 추가 — 2026-07-07 완료

- 요청/결론: 화면 샘플에 약 1분 실행되는 배치형 SQL 5개를 추가했다. 기존 OLTP `asta-awr-01~15` 뒤에 `asta-batch-01~05`가 표시되며 샘플 선택 시 workload가 자동으로 `BATCH`가 된다.
- 패턴: 5개 보고서 섹션의 2025년 일판매 KPI 40개를 `UNION ALL`로 각각 재집계하는 원본이다. 차원은 브랜드, 상품분류, 성별, 라인, 판매기준이다. 결정론적 후보는 동일 지표를 월판매 요약에서 한 번 집계한 뒤 `UNPIVOT`한다.
- 실환경 Source full-result 검증: B01 `54.968593s→1.032141s`(98.1223%, 280행), B02 `53.489044s→1.016196s`(98.1002%, 120행), B03 `52.045566s→1.067563s`(97.9488%, 560행), B04 `35.797556s→1.042021s`(97.0891%, 840행), B05 `53.537102s→1.061858s`(98.0166%, 80행)다. 5개 모두 원본/후보 row count, metadata digest, full-result digest가 일치했다.
- 검증 artifact: `reports/asta_batch_samples_20260707/verification.json`. SQL 원문은 artifact에 넣지 않고 fingerprint와 수치만 기록했다. 실패한 보정 후보(아이템 8.86초, 시즌 222.06초)는 화면에 넣지 않았다.
- 변경 파일: `static/js/extensions/tuning_assistant.js`, `static/index.html`, `tools/asta_batch_samples.py`, `tools/verify_asta_batch_samples.py`, `tests/test_asta_batch_samples.py`, 기존 샘플/cache/workload 계약 테스트, 사용자 매뉴얼, 이 handoff.
- 테스트: 신규 TDD RED `2 failed` 후 관련 `82 passed, 기존 2 failed`. 전체 `423 passed, 기존 9 failed in 1.33s`, 신규 실패 0. Node JS syntax, report-tabs DOM, `git diff --check` 통과.
- cache-buster는 `tuning_assistant.js?v=20260707_batch_samples1`. 마지막 localhost HTTP byte 검증은 권한 승인 거절로 수행하지 못했다. 서비스 재시작, DB package/ORDS/schema/business data 변경, commit/push 없음. Source evidence 함수가 정상 계약에 따라 검증 결과 row는 저장했다.

## ASTA 문서 4종 현행화 — 2026-07-07 완료

- 요청/결론: `docs/AI_SQL_TUNING_ASSISTANT_MANUAL.md`, `docs/asta_source_execution_flow.md`, `docs/OADT2_ASTA_ARCHITECTURE.md`, `docs/README.md`를 현재 Real ASTA 코드와 2026-07-06~07 실환경 변경 기준으로 현행화했다.
- 과거 FastAPI `BackgroundTasks`/동기 `ANALYZE_SQL` 중심이던 1,322줄 실행 흐름 문서를 현재 `SUBMIT_RUN → DBMS_SCHEDULER → EXECUTE_RUN`, allowlisted DB Link, Source `AUTO/FULL_RESULT` evidence, deterministic gate, progress/report 조회 흐름으로 전면 재작성했다.
- 사용자/아키텍처 문서에는 OLTP 15+BATCH 5 샘플, Advisor UI 기본 OFF와 badge 제거, 진행 상세 Drawer/timing, 접기 입력·결과, 6개 결과 탭과 좌우 SQL 변경, verdict popover, Source DBA_* 객체정보 수집을 반영했다. `docs/old/`로 이동한 품질 문서를 현재 운영 기준으로 참조하던 링크도 제거했다.
- 변경 파일은 위 4개 문서와 이 handoff다. 코드, DB/ORDS, 서비스, static asset, commit/push 변경은 없다.
- 검증: 문서/UI 관련 `39 passed`; 전체 회귀 `423 passed, 기존 9 failed in 1.31s`, 신규 실패 0; 대상 문서와 전체 `git diff --check` 통과.

## ASTA 매뉴얼·아키텍처·11단계 Workflow 팝업 — 2026-07-07 완료

- ASTA 상단에 `매뉴얼 및 사용설명` 버튼과 접근 가능한 `aria-modal` dialog를 추가했다. 팝업은 `아키텍처`, `11단계 Workflow` 두 탭이며 닫기/backdrop/Escape, 탭 Arrow/Home/End, focus trap·복원을 지원한다.
- 아키텍처는 `User / 개발자`, `UI (VM)`, `OCI AI Lakehouse`, `OCI ERP Database (BaseDB)` 4개 영역별 제공 기능과 `운영 SQL 자동 변경 없음`, FastAPI thin proxy, ADB ORDS/Scheduler, allowlisted DB Link/Source package 경계를 카드형 흐름으로 표시한다.
- Workflow는 11개 canonical step마다 실행 영역, 실제 package/procedure, 수행 내용, 생성 근거, 실패·차단 동작을 표시한다. 호환 번호와 실제 호출 의존 순서가 달라 `VECTOR_KB(9) → LLM_REWRITE(6)`, `VECTOR_SAVE(11) → FINAL_REPORT(10) 완성`임을 명시했다.
- 모바일은 하단 sheet형 full-width 팝업, 아키텍처 1열, Workflow 상세 1열로 반응한다. cache-buster는 `tuning_assistant.js?v=20260707_manual_workflow1`이다.
- 변경 파일: `static/js/extensions/tuning_assistant.js`, `static/index.html`, 신규 `tests/test_asta_manual_dialog.py`, cache 계약 테스트 4개, 문서 4종, 이 handoff. DB/ORDS/package/schema/service restart/commit/push는 변경하지 않았다.
- TDD: 신규 계약 RED `4 failed` 확인 후 focused `62 passed`, UI runtime 경계 포함 `83 passed`. 전체 회귀 `427 passed, 기존 9 failed in 1.35s`, 신규 실패 0. JS syntax와 `git diff --check` 통과.
- 실행 서비스 `/`는 새 cache URL을 참조하고 제공 JS는 workspace와 182,698 bytes로 byte-identical하다. 서비스 재시작 없이 정적 자산이 반영됐다.

## ASTA 아키텍처 OCI 리소스 맵 — 2026-07-07 완료

- 아키텍처 팝업에 `DEV compartment`, `PRO compartment`, `Shared / Regional OCI Services` 3개 그룹의 논리 리소스 맵을 추가했다. OCID는 표시하지 않는다.
- DEV에는 `DK-AI-DEV-VM-01`, Autonomous Database 23ai, ORDS `asta.v1`, ASTA Vector KB와 각 역할을 표시한다. PRO에는 OCI ERP BaseDB, allowlisted DB Link, `ASTA_SOURCE_PKG`, ERP 업무 schema를 표시한다. Shared에는 VCN/Subnet/NSG, OCI IAM, OCI Generative AI를 표시한다.
- OCI IAM의 live compartment 상세 조회는 현재 VM Instance Principal 권한으로 `NotAuthorizedOrNotFound`여서 실제 display name/OCID inventory를 추정하지 않았다. UI는 저장소와 실행 계약으로 확인된 논리 배치임을 명시하며 OCI Console inventory 대체가 아님을 문서에 기록했다.
- cache-buster는 `tuning_assistant.js?v=20260707_manual_resources1`. 변경 파일은 assistant JS/index, 팝업/cache 계약 테스트, 문서 4종과 이 handoff다. DB/ORDS/package/schema/service restart/commit/push는 변경하지 않았다.
- 신규 리소스 계약 RED `2 failed` 후 focused `73 passed`; 전체 회귀 `428 passed, 기존 9 failed in 1.33s`, 신규 실패 0. JS syntax와 `git diff --check` 통과.
- 실행 서비스 `/`는 새 cache URL을 참조하고 제공 JS는 workspace와 188,020 bytes로 byte-identical하다.

## ASTA OCI 리소스·상단 아키텍처 통합 — 2026-07-07 완료

- 사용자 요청에 따라 별도 `OCI 리소스 배치` 하단 섹션과 `ASTA_OCI_RESOURCE_GROUPS`를 제거하고 상단 4개 책임 카드 데이터에 compartment/resources를 직접 통합했다.
- 각 카드는 `영역 → compartment → 실행 경계 → OCI Resources(OCID 비표시) → 제공 기능` 순서로 읽힌다. UI(VM)는 DEV Compute, AI Lakehouse는 DEV ADB/ORDS/Vector와 Shared GenAI/IAM/Network, BaseDB는 PRO ERP DB/DB Link/Source package/schema를 표시한다.
- cache-buster는 `tuning_assistant.js?v=20260707_manual_integrated1`. 관련 문서 4종도 별도 맵이 아니라 카드 통합형임을 반영했다.
- 통합 계약 RED `2 failed` 후 focused `73 passed`; 전체 회귀 `428 passed, 기존 9 failed in 1.35s`, 신규 실패 0. JS syntax와 `git diff --check` 통과.
- 실행 서비스 `/`는 새 cache URL을 참조하고 제공 JS는 workspace와 186,507 bytes로 byte-identical하다. DB/ORDS/package/schema/service restart/commit/push 없음.

## ASTA ADB 리소스 명칭 26ai 변경 — 2026-07-07 완료

- 사용자 요청에 따라 아키텍처 카드와 canonical 아키텍처 문서의 `Autonomous Database 23ai` 표시를 `Autonomous Database 26ai`로 변경했다. 실행 로직, DB 설정, package는 변경하지 않았다.
- cache-buster는 `tuning_assistant.js?v=20260707_manual_adb26ai1`. 관련 cache/팝업 계약 테스트를 함께 갱신했다.
- focused `38 passed`; 전체 회귀 `428 passed, 기존 9 failed in 1.35s`, 신규 실패 0. JS syntax와 `git diff --check` 통과.
- 실행 서비스 `/`는 새 cache URL을 참조하고 제공 JS는 workspace와 186,507 bytes로 byte-identical하다. 서비스 재시작/commit/push 없음.

## ASTA PoC 사용자·LB 아키텍처 정정 — 2026-07-07 완료

- `User / 개발자`는 OCI Resource를 사용하지 않는 `PoC 샘플 화면`으로 정정했다. 해당 카드의 `resources`는 빈 배열이며 OCI Resources 블록을 조건부로 렌더링하지 않는다.
- UI(VM)의 DEV compartment 리소스 앞단에 `OCI Load Balancer`를 추가하고 `HTTPS listener·backend health check → DK-AI-DEV-VM-01` 역할을 표시했다. 상단 흐름도 `PoC 샘플 화면 → OCI Load Balancer → DK-AI-DEV-VM-01 → ADB orchestration → Source evidence`로 변경했다.
- 화면의 `· OCID 비표시` 문구와 활성 문서의 관련 표현을 제거했다. cache-buster는 `tuning_assistant.js?v=20260707_manual_lb1`이다.
- 요구 계약 RED `2 failed` 후 focused `73 passed`; 전체 회귀 `428 passed, 기존 9 failed in 1.33s`, 신규 실패 0. JS syntax와 `git diff --check` 통과.
- 실행 서비스 `/`는 새 cache URL을 참조하고 제공 JS는 workspace와 186,411 bytes로 byte-identical하다. DB/ORDS/package/schema/service restart/commit/push 없음.

## ASTA 매뉴얼 탭 클릭 가능성 강조 — 2026-07-07 완료

- 사용자 피드백에 따라 팝업의 `아키텍처`, `11단계 Workflow` 탭을 일반 텍스트형 pill에서 번호가 있는 카드형 선택 내비게이션으로 변경했다.
- 각 탭은 `01/02` index, 굵은 label, 기본 `열기`, 선택 `선택됨 ✓`, primary border/하단 3px 강조선, hover 배경·shadow·translate 효과를 사용한다. 기존 role=tab, aria-selected, Arrow/Home/End와 focus 동작은 유지한다.
- 모바일은 2열 동일 폭을 유지하고 좁은 공간에서는 상태 pseudo label만 숨겨 번호·테두리·선택 강조로 구분한다.
- cache-buster는 `tuning_assistant.js?v=20260707_manual_tabs1`. 시각 계약 RED `2 failed` 후 focused `74 passed`; 전체 회귀 `429 passed, 기존 9 failed in 1.36s`, 신규 실패 0. JS syntax/diff check 통과.
- 실행 서비스 `/`는 새 cache URL을 참조하고 제공 JS는 workspace와 187,827 bytes로 byte-identical하다. DB/ORDS/package/schema/service restart/commit/push 없음.

## ASTA 원격 pull·프로그램 재기동 — 2026-07-07 완료

- 사용자 요청으로 `origin/ASTA`를 `f06e4bc → 9c4b217` fast-forward pull했다. 변경은 `Guide_Select-AI.md`, NL2SQL/Profile Test Python·JS 5개 파일이며 충돌은 없었다.
- 일반 `systemctl restart`는 interactive authentication 요구로 거절됐고, 승인된 `sudo -n systemctl restart select-ai-test.service`로 정상 재기동했다.
- 서비스 PID는 `822785 → 1125061`, active/running, 시작 시각 `2026-07-07 17:04:17 KST`, `0.0.0.0:8000` LISTEN이다. startup complete와 `descente-selectai`, `descente-tuning` DB pool ready를 확인했다.
- localhost `/`와 `/api/auth/status`는 HTTP 200이며 served index는 workspace와 byte-identical하고 `tuning_assistant.js?v=20260707_manual_tabs1`을 참조한다.
- DB package/ORDS/schema 변경, 추가 commit/push는 수행하지 않았다.

## ASTA UI 개발자 실행 절차 매뉴얼 — 2026-07-08 완료

- 요청/결론: Real ASTA 코드만 검색해 기존 매뉴얼 팝업에 별도 `03 개발자 실행 추적` 탭을 추가했다. 브라우저, FastAPI, ORDS, Target ADB, Source DB, AI/LLM의 역할과 실제 파일·함수/package, 버튼 클릭부터 report render/download까지 19개 호출 지점, 실패·차단·원본 유지 분기, Run ID 추적 방법을 표시한다.
- 실제 흐름: `formatSql/stripTrailingSqlTerminator → POST /api/asta/analyze → asta_proxy.analyze → ASTA_PKG.SUBMIT_RUN → DBMS_SCHEDULER → EXECUTE_RUN/RUN_PIPELINE → SQL Guard → 원본 Source evidence → Vector search → LLM 후보 → 후보 Source evidence → BUILD_COMPARISON_JSON → SAVE_CASE → BUILD_REPORT/BUILD_RESPONSE_JSON → poll/fetchReport → renderReportTabs/downloadText`다. canonical 결과서 생성은 Python이 아니라 ADB `ASTA_REPORT_PKG`다.
- 변경 파일: `static/js/extensions/tuning_assistant.js`, `static/index.html`, 문서 4종, 신규 `tests/test_asta_developer_manual_contract.py`, cache 기대값/로컬 runtime 금지 범위를 갱신한 관련 테스트 7개, 이 handoff.
- strict TDD: 신규 계약 테스트 RED `5 failed` 확인 후 구현했다. 최초 `.venv/bin/pytest`는 실행 파일 부재로 시작되지 않아 기존 offline uv cache 명령으로 RED/GREEN을 재현했다.
- 검증: 신규+기존 manual `11 passed`; 관련 UI/API 계약 `76 passed`; Node 결과서 DOM PASS; `node --check` 두 JS PASS; `git diff --check` PASS. 전체 `434 passed, 9 failed in 1.34s`; 직전 baseline 9건과 동일하고 신규 실패 0건이다.
- 기존 9 failures: 오래된 ADB smoke/response/run-id/failure marker 기대 4건, 누락 `reports/asta_source_contract_latest.md` 1건, 과거 proxy failure-return 기대 2건, workload signature 기대 2건이다. 이번 UI/docs 변경과 무관하다.
- 서비스 재시작, DB/ORDS/package 배포, 외부 실행, commit/push는 수행하지 않았다.
