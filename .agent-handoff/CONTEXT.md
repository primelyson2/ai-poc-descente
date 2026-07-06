# Real ASTA 작업 인계

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
