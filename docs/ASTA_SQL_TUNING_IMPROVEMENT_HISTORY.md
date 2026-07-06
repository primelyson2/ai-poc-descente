# ASTA SQL 튜닝 개선 누적 이력

## 운영 원칙

- 상태는 `[대기]`, `[진행중]`, `[완료]`, `[차단]`만 사용한다.
- 아래 단계는 순서대로 진행하며 **한 번에 한 단계만 `[진행중]`으로 작업한다.** 다음 단계는 현재 단계의 완료 기준과 회귀 테스트를 통과한 뒤 시작한다.
- 실제 결과값 동등성이 확인되지 않은 후보는 성능 개선으로 판정하지 않는다.
- 비밀정보, 접속 문자열, 토큰, 비밀번호 및 원문 고객 데이터는 이 문서에 기록하지 않는다.
- 각 단계의 변경은 작고 되돌릴 수 있게 유지하며 DB compile/deploy, ORDS 및 서비스 변경은 별도 승인 범위로 관리한다.

## 활성 OLTP 판정 정책

- 2026-07-05 사용자 정책 변경으로 절대 latency hard guard를 `2,000,000us`에서 `3,000,000us`로 변경했다.
- 현재 활성 기준은 Buffer Gets 5% 이상 감소, 3회 중앙 elapsed `3초 이하`, 원본 대비 증가 `300ms 이하`, noise gate 및 result digest 동등성 통과다.
- 단계 0의 1.642초 후보는 당시 2초 기준을 통과한 역사적 사실이며 현재 3초 기준도 통과한다. 과거 기록의 2초 표기는 당시 정책을 뜻한다.
- 로컬 ADB PL/SQL 소스는 3초로 변경했지만 이번 작업에서는 DB compile/deploy를 하지 않았다. 따라서 원격 ADB 객체에는 이전 2초 기준이 남아 있을 수 있다.

## 단계 현황

| 단계 | 상태 | 주제 |
|---:|---|---|
| 0 | [완료] | 고객 SQL 1 OLTP 기준선과 의미 있는 개선 확보 |
| 1 | [완료] | XPLAN 지배 병목 자동 랭킹 |
| 2 | [완료] | SQL 구문과 Plan Node 연결 |
| 3 | [완료] | 병목 패턴별 후보 다양화 |
| 4 | [완료] | Optimizer 의도 검증 |
| 5 | [완료] | 반복 측정과 실행예산 |
| 6 | [완료] | 동등성 검증 확장 |
| 7 | [완료] | Bind와 plan 안정성 |
| 8 | [완료] | 상태머신, UI, Vector 학습 |

## 실환경 반영 — 2026-07-05 [차단]

### 목표

- 로드맵 0~8의 로컬 변경을 Source→ADB→proxy→UI 실제 흐름에 최소 범위로 연결하고, 전체 결과·Optimizer 의도·bind/plan·실행예산 gate가 성공을 추측하지 않게 한다.

### 작업 항목과 변경 파일

- Source full-result/child cursor evidence: `db/source/asta_source_pkg.sql`, `db/adb/asta_source_bridge_pkg.sql`.
- ADB fail-closed 비교/Vector 분리: `db/adb/asta_pkg.sql`, `db/adb/asta_vector_pkg.sql`.
- proxy 상태머신 연결: `app/asta_runtime_gates.py`, `app/routers/asta_proxy.py`.
- UI cache 반영: `static/index.html`, `static/js/extensions/tuning_assistant.js`.
- 최소 배포/검증: `tools/asta_deploy_source.py`, `tools/asta_deploy_adb.py`, `tools/asta_roadmap_runtime_deploy.py`.
- 계약 테스트: `tests/test_asta_runtime_deployment_contract.py`.
- 상세 배포/롤백 기록: `reports/asta_roadmap_runtime_deploy/20260705T174506KST/README.md`.

### 테스트 및 실측

- TDD RED 6건을 확인한 뒤 GREEN `6 passed`.
- 전체 회귀 `345 passed, 10 failed`; 기존 baseline 10건과 동일하며 신규 실패는 0건이다.
- Source `ASTA_SOURCE_PKG`, ADB `ASTA_SOURCE_BRIDGE_PKG`/`ASTA_VECTOR_PKG`/`ASTA_PKG`의 spec/body가 모두 VALID이고 USER_ERRORS=0이다.
- 고객 SQL full-result 262행 ordered digest가 일치했다. 실제 XPLAN은 VIF Starts `845→1`, anti consumer와 set-operation barrier 유지로 Optimizer intent VERIFIED다.
- 과거 후보 3회 중앙 elapsed `1,641,880us`, Buffer Gets `1,079,324`로 활성 3초 정책을 통과한다.
- 대표 bind replay가 없어 최종 판정은 `BLOCKED / BIND_REPLAY_NOT_PERFORMED`다.
- 정적 UI는 실제 HTTP에서 새 cache-buster와 BLOCKED 표시를 확인했다.

### 완료 기준과 현재 차단

- DB compile/bridge/full-result/XPLAN/UI static 기준은 완료했다.
- 2026-07-05 18:06:05 KST 서비스가 PID `759185`로 재시작됐다. startup/runtime 오류 없이 DB pool이 준비됐고 current-contract final API에서 `asta.workflow.v1`을 확인했다.
- 실제 final API는 incomplete smoke run을 `BLOCKED`로 유지하고 Vector를 `REJECTED_OBSERVATION`, positive eligible=false로 반환했다. UI root/JS도 실제 HTTP와 byte equality를 통과했다.
- 고객 SQL ID는 bind capture 0건, ACS statistics/selectivity 0건, fixture bind placeholder 0개로 NULL/SELECTIVE/BROAD coverage를 만들 근거가 없다. 동일 bind replay를 실행하지 않았으며 `BIND_COVERAGE_INSUFFICIENT` 때문에 실환경 상태는 계속 `[차단]`이다.

### 위험 및 롤백

- 배포 전 DBMS_METADATA DDL과 객체 상태를 `reports/asta_roadmap_runtime_deploy/20260705T174506KST/`에 보존했다.
- DB 롤백은 저장된 spec→body DDL 적용 후 VALID/USER_ERRORS=0 확인, 앱 롤백은 기존 미커밋 변경을 보존한 상태에서 승인된 파일 단위 복원 후 서비스 재시작/health 확인 순서다.
- ORDS metadata, allowlist, 운영 설정, 서비스 강제 종료, git commit/push는 수행하지 않았다.

### 작업 이력

- 2026-07-05: full-result/child cursor 계약 TDD 및 Source→ADB bridge 배포 완료.
- 2026-07-05: 고객 SQL 전체 262행 digest와 실제 barrier XPLAN 검증 완료.
- 2026-07-05: 서비스 재시작 권한과 bind replay 증거 부족으로 실환경 최종 상태를 `[차단]`으로 기록.
- 2026-07-05: 서비스 재시작(PID 759185), final API/UI/Vector rejected routing smoke 완료. 서비스 차단은 해소됐다.
- 2026-07-05: Source bind capture/ACS와 fixture를 값 비노출로 조사했으나 대표 bucket 0/0/0으로 확인되어 bind replay 및 ACCEPTED 승격을 차단했다.

## 첫 고객 SQL 최종 결과서 생성 — 2026-07-05 [완료]

- Source DB 최소 반복으로 원본/UNION DISTINCT barrier 후보를 각 1회 새로 실행했다.
- 새 Before/After는 `125,969,118us / 9,160,611 buffers`와 `1,749,081us / 1,079,302 buffers`다.
- full-result `ORDERED_ROWS` 262행의 row count, metadata, digest가 완전히 일치했다.
- 실제 XPLAN은 VIF producer Starts `845→1`, ANTI consumer, set-operation barrier 유지로 Optimizer intent VERIFIED다.
- 기존 3회 실측 artifact를 반복 성능 근거로 명시해 재사용했다. 후보 중앙 elapsed `1,641,880us`, Buffer Gets `1,079,324`, 개선율은 각각 `98.6812%`, `88.2167%`다.
- 이 고객 SQL은 SQL text/capture/ACS에 bind가 없는 literal SQL로 재확인되어 `BIND_NOT_APPLICABLE`로 판정했다. 동등성·intent·OLTP latency·Buffer·300ms guard는 각각 별도 증거로 통과했다.
- 최종 판정은 `IMPROVED`다. Markdown/안전 HTML은 `reports/asta_customer_01_final/20260705T182718KST/`에 보존했다.
- 전체 회귀 `345 passed, 10 failed`, 기존 baseline 동일, 신규 실패 0건이다. DB package/ORDS/service/git 변경은 없었다.

## 단계 0 [완료] — 고객 SQL 1 OLTP 기준선과 개선

### 목표

첫 번째 고객 SQL `SESL0640.selectList`(SQL ID `7rcw6d3us86r7`)를 OLTP로 바로잡고, 결과 의미를 보존하면서 중앙 elapsed 2초 이하의 재현 가능한 개선을 확보한다.

### 작업 항목

- BATCH로 잘못 지정된 fixture, 품질 gate, 실행 context를 OLTP로 통일했다.
- Source 실행 결과를 ordered JSON과 컬럼 metadata 기반 digest로 비교하도록 구현했다.
- ADB 판정에 결과 digest 필수 조건과 OLTP 2초 hard guard를 추가했다.
- correlated `NOT EXISTS (VIF_WHOLESALE_S)` 반복 실행을 DISTINCT 제외 키 helper로 분리했다.
- 단순 CTE merge 실패 후, 동일 projection의 항상 빈 branch를 포함한 `UNION DISTINCT` barrier로 optimizer merge를 막았다.

### 변경 파일

- `db/source/asta_source_pkg.sql`
- `db/adb/asta_pkg.sql`
- `tools/run_asta_prompt_abc_adb.py`
- `tools/asta_quality_agent.py`
- `static/js/extensions/tuning_assistant.js`
- `asta-quality-agent.yaml.example`
- `tests/test_asta_result_digest_contract.py`
- `tests/test_asta_quality_agent.py`
- `reports/asta_customer_01_oltp_diagnosis.md`
- `reports/asta_customer_01_live/candidate_union_barrier.sql`
- `reports/asta_customer_01_live/candidate_union_barrier_verify3.json`

### 테스트/실측

- 원본 3회 elapsed: `142,640,389us`, `124,498,199us`, `123,915,378us`; 중앙값 `124,498,199us`.
- 원본 중앙 Buffer Gets: `9,159,788`.
- 후보 3회 elapsed: `1,641,880us`, `1,615,886us`, `1,644,745us`; 중앙값 `1,641,880us`.
- 후보 중앙 Buffer Gets: `1,079,324`.
- Buffer Gets `88.2167%`, elapsed `98.6812%` 감소; 후보 노이즈 `1.758%`.
- 원본/후보 6회의 bounded ordered result digest가 모두 일치했다.
- Source `ASTA_SOURCE_PKG`와 ADB `ASTA_PKG`는 compile 후 VALID, `USER_ERRORS=0`을 확인했다.
- 근거: `reports/asta_customer_01_oltp_diagnosis.md`, `reports/asta_customer_01_live/candidate_union_barrier_verify3.json`.

### 완료 기준

- 결과 digest 일치.
- Buffer Gets 5% 이상 감소.
- 3회 중앙 elapsed 2초 이하, 원본 대비 악화 300ms 이하.
- 측정 노이즈 gate 통과 및 Source/ADB package VALID.

### 위험/롤백

- digest 범위는 현재 정렬된 첫 100행이므로 무제한 전체 결과의 동등성까지 증명하지 않는다.
- 자동 LLM이 barrier 없는 단순 DISTINCT CTE를 다시 생성할 수 있다.
- DB package 변경은 보존한 배포 전 DDL로 객체별 복구할 수 있으며 ORDS/운영 설정은 변경하지 않았다.

### 작업 이력

- 2026-07-05: OLTP 재분류, 지배 병목 진단, result digest와 2초 hard guard 배포 검증 완료.
- 2026-07-05: `UNION DISTINCT` barrier 후보 Before/After 각 3회 실측 후 `IMPROVED` 확정.

## 단계 1 [완료] — XPLAN 지배 병목 자동 랭킹

### 목표

DBMS_XPLAN ALLSTATS의 `Starts`, `E-Rows`, `A-Rows`, `A-Time`, `Buffers`와 부모-자식 관계를 파싱하여, 재작성 대상을 결정론적으로 랭킹하고 근거 수치와 reason code를 구조화해 반환한다.

### 작업 항목

- 기존 품질 판정 코드가 있는 `tools/asta_quality_agent.py`를 재사용한다.
- XPLAN 표의 축약 수치(K/M/G), 시간, operation indentation을 파싱한다.
- 부모 Starts가 낮고 자식 node가 반복되는 subtree 경계를 식별한다.
- buffer/time 점유율, 반복 횟수, cardinality 오차, subtree 행 증폭을 고정 가중치로 랭킹한다.
- 고객 SQL의 `VIF_WHOLESALE_S Starts=845`, 하위 `TGP_STYDE_L_PK A-Rows=940M/Buffers=7.691M` 유형을 회귀 fixture로 고정한다.

### 변경 파일

- `tools/asta_quality_agent.py`
- `tests/test_asta_xplan_bottleneck_ranker.py`
- `tests/fixtures/asta_customer_01_dominant_xplan.txt`
- `docs/ASTA_SQL_TUNING_IMPROVEMENT_HISTORY.md`

### 테스트/실측

- TDD RED: 2026-07-05, 신규 함수 import 실패로 테스트 수집 오류를 확인했다.
- TDD GREEN: 2026-07-05, 신규 랭커 테스트 `4 passed`.
- 고객 fixture에서 Id 28 `VIEW VIF_WHOLESALE_S`가 `REPEATED_SUBTREE_ROOT`, `DOMINANT_BUFFERS`, `DOMINANT_A_TIME` 근거로 1위에 선정됐다.
- 관련 테스트 명령: `uv run --offline --no-sync python -m pytest -q tests/test_asta_xplan_bottleneck_ranker.py tests/test_asta_quality_agent.py tests/test_asta_contract_hardening_codex.py tests/test_asta_result_digest_contract.py`.
- 관련 테스트 결과: `35 passed`.
- 전체 테스트 명령: `uv run --offline --no-sync python -m pytest -q`.
- 전체 테스트 결과: `258 passed, 10 failed`. 이전 기준선과 동일한 기존 실패 10건이며 단계 1 신규 실패는 0건이다.
- 실제 저장 XPLAN 93개 node 분석에서도 Id 28이 1위였다. 근거는 Starts `845`, Buffers `8,090,000`(`88.3381%`), A-Time `124,900,000us`(`87.5631%`), subtree 최대 A-Rows `940,000,000`이다.
- Python compile과 `git diff --check`를 통과했다.

### 설계 결정

- 별도 프레임워크를 만들지 않고 기존 품질 판정 경계인 `tools/asta_quality_agent.py`에 순수 함수로 추가했다.
- plan indentation을 stack으로 해석해 parent/child를 만들고, 부모 Starts가 1 이하인 반복 node를 subtree root 후보로 본다.
- 정렬 키는 고정 점수, Buffers, A-Time, Starts, node id 순서로 두어 동점도 결정론적으로 처리한다.
- 반복 경계 보너스는 buffer/time 점유율이 5% 이상일 때만 크게 적용해 저비용 반복 lookup의 과대평가를 줄였다.
- 파싱 근거가 없으면 추측하지 않고 `INSUFFICIENT_EVIDENCE / XPLAN_ALLSTATS_ROWS_NOT_FOUND`를 반환한다.

### 완료 기준

- 같은 XPLAN 입력은 byte-for-byte 동일한 구조화 랭킹을 반환한다.
- 고객 correlated subtree root가 1위이며 2차 반복 scan도 상위 후보에 유지된다.
- 근거에 node/parent/child, 원시 metric, 점유율, cardinality와 subtree 행 수가 포함된다.
- 관련 테스트 통과, 전체 회귀에서 신규 실패 0건.

### 위험/롤백

- A-Time은 병렬/중첩 실행에서 단순 합산할 수 없으므로 점유율은 우선순위 신호로만 사용한다.
- XPLAN 표시 형식이나 locale가 달라지면 파싱하지 못하고 `INSUFFICIENT_EVIDENCE`로 종료한다.
- 가중치는 경험적 초기값이며 단계 4의 plan 의도 검증 전에는 자동 SQL 적용 근거로 사용하지 않는다.
- Predicate/Outline/query block과 원본 SQL fragment는 아직 연결하지 않는다. 이는 단계 2 범위다.
- 병렬 plan의 PX 계층, adaptive plan의 미사용 branch, 여러 plan table 형식은 추가 fixture가 필요하다.
- 롤백은 신규 함수, fixture와 테스트 제거로 국한되며 기존 품질 판정 경로에는 연결하지 않는다.

### 작업 이력

- 2026-07-05: 기존 parser 부재를 확인하고 quality-agent 내부 최소 parser/ranker 계약을 테스트로 먼저 작성했다.
- 2026-07-05: 반복 경계 보너스가 저비용 lookup을 과대평가한 첫 구현을 수정해 실측 점유율과 결합했다.
- 2026-07-05: 관련 35건과 전체 268건을 실행해 신규 실패 0건을 확인하고 단계 1을 `[완료]`로 종료했다.
- 2026-07-05: Hermes 독립 재검증 시 프로젝트 `.venv`에는 `pytest`가 설치되어 있지 않아 문서의 `uv run --offline --no-sync python -m pytest ...` 명령은 그대로 재현되지 않았다. 대신 `uv run --offline --with pytest --no-project python -m pytest -q tests/test_asta_xplan_bottleneck_ranker.py`로 신규 테스트 `4 passed`를 확인했고, 별도 직접 호출로 dominant node Id 28, `VIF_WHOLESALE_S`, Starts 845를 확인했으며 `git diff --check`도 통과했다.

## 단계 2 [완료] — SQL 구문과 Plan Node 연결

### 목표

단계 1의 dominant plan node를 원본 SQL의 query block, CTE, inline view, subquery, predicate 및 alias에 결정론적으로 연결하고, 불확실하거나 모호하면 자동 rewrite를 차단한다.

### 작업 항목

- 표준 라이브러리만 사용해 SQL 문자열 literal, line/block comment를 제외하고 quoted identifier를 keyword로 취급하지 않는 위치 보존 tokenizer를 구현했다.
- 괄호 stack으로 CTE와 subquery 범위를 만들고 `NOT EXISTS`, `EXISTS`, `SCALAR_SUBQUERY`, `INLINE_VIEW` construct를 분류했다.
- `FROM`/`JOIN` object와 alias, CTE 외부 alias 참조를 추적해 correlated subquery를 식별했다.
- XPLAN Predicate Information의 node별 quoted alias를 추출해 SQL object/alias 근거와 교차 확인했다.
- 단계 1 랭킹을 내부에서 호출하는 public pure function `link_dominant_plan_node_to_sql`을 추가했다.
- 동일 object가 여러 SQL fragment에 등장하면 `AMBIGUOUS_SQL_FRAGMENT`, object가 없으면 `PLAN_OBJECT_NOT_FOUND_IN_SQL`, predicate alias가 다르면 `XPLAN_ALIAS_MISMATCH`로 rewrite를 차단했다.
- Predicate Information이 없어도 object와 SQL structure가 유일하면 confidence `0.85`로 제한 연결하고, predicate alias까지 일치하면 `0.99`로 연결한다.

### 변경 파일

- `tools/asta_quality_agent.py`
- `tests/test_asta_sql_plan_linker.py`
- `tests/fixtures/asta_customer_01_style_not_exists.sql`
- `tests/fixtures/asta_customer_01_dominant_xplan.txt`
- `docs/ASTA_SQL_TUNING_IMPROVEMENT_HISTORY.md`
- `.agent-handoff/CONTEXT.md`

### 테스트/실측

- TDD RED: 고객 성공 연결 테스트를 먼저 추가한 뒤 public 함수 import 오류로 수집 실패를 확인했다.
- 나머지 필수 행동인 중복 object ambiguity, comment/string/quoted identifier 오인 방지, 근거 부족, alias mismatch, Predicate 미제공 제한 연결, scalar/inline view, 결정론성 테스트도 구현 전에 추가하고 동일 RED를 확인했다.
- GREEN: 단계 2 테스트 8건과 단계 1 테스트를 합쳐 `12 passed`.
- REFACTOR: scope 선택과 source span 생성을 helper로 분리한 뒤 관련 테스트 `43 passed`.
- 관련 테스트 명령: `UV_NO_CACHE=1 PYTHONPATH=/home/opc/.cache/uv/archive-v0/uV3M1hTXKn5DvRqO/lib/python3.11/site-packages /home/opc/.local/bin/uv run --offline --no-sync python -m pytest -q tests/test_asta_sql_plan_linker.py tests/test_asta_xplan_bottleneck_ranker.py tests/test_asta_quality_agent.py tests/test_asta_contract_hardening_codex.py tests/test_asta_result_digest_contract.py`.
- 전체 테스트 명령: `UV_NO_CACHE=1 PYTHONPATH=/home/opc/.cache/uv/archive-v0/uV3M1hTXKn5DvRqO/lib/python3.11/site-packages /home/opc/.local/bin/uv run --offline --no-sync python -m pytest -q`.
- 전체 결과: `266 passed, 10 failed`. 단계 1 기준선과 동일한 기존 실패 10건이며 단계 2 신규 실패는 0건이다.
- `uv run --offline --with pytest --no-project`는 현재 uv cache에 pytest 배포본이 없어 의존성 해석에 실패했다. 프로젝트 `.venv`에도 pytest가 없으므로 위의 고정 archive `PYTHONPATH` + `uv run --offline --no-sync` 명령을 재현 명령으로 사용했다.
- Python compile과 `git diff --check`를 통과했다.
- 실제 UI 전체 고객 SQL과 저장된 전체 XPLAN 연결 결과: dominant Id 28 → query block/CTE `STYLE` → construct `NOT EXISTS` → object `DSNT.VIF_WHOLESALE_S`, alias `VWS`, correlated outer alias `A`, immediate consumer `CTE_FILTER`, source line 19~25, confidence `0.99`, `rewrite_allowed=true`.

### 설계 결정

- 외부 SQL parser 의존성을 추가하지 않고 분석에 필요한 최소 Oracle SELECT 구조만 보수적으로 해석한다.
- source span은 Python character offset과 1-based line/column을 함께 반환한다.
- XPLAN generated query block 이름을 추측하지 않고 SQL에서 확인된 CTE 이름 또는 `MAIN`만 반환한다.
- Predicate alias 근거가 존재하는데 SQL alias와 맞지 않으면 optimizer transformation 가능성으로 간주해 유일 object라도 차단한다.
- comment/string은 token 후보에서 제거하고 quoted identifier는 identifier로만 취급해 `"NOT"`, `"FROM"`을 keyword로 오인하지 않는다.
- 결과에는 dominant node, query block/CTE, construct, object/alias, source span, immediate consumer, correlated alias, predicate evidence, confidence, reason code 및 rewrite 허용 여부를 모두 포함한다.

### 완료 기준

- 고객 Id 28이 `STYLE` CTE의 correlated `NOT EXISTS`와 정확한 source span으로 연결된다.
- object 중복, object 부재, predicate alias 불일치는 명시적 reason code와 함께 rewrite가 차단된다.
- comment/string/quoted identifier가 후보 또는 keyword로 오인되지 않는다.
- 같은 SQL/XPLAN 입력은 동일한 구조화 결과를 반환한다.
- 관련 테스트 통과 및 전체 회귀 신규 실패 0건.

### 위험/롤백

- optimizer transformation으로 원문과 plan shape가 직접 대응하지 않을 수 있어 alias 불일치는 보수적으로 차단한다.
- 현재 최소 parser는 SELECT 계열과 일반적인 WITH/FROM/JOIN/subquery 구조만 다룬다. Oracle `MODEL`, `MATCH_RECOGNIZE`, `JSON_TABLE`, lateral/polymorphic table function 등은 지원 근거가 없다.
- comma join의 두 번째 이후 source, synonym을 통한 object 이름 변화, quoted case-sensitive object, 여러 CTE가 같은 object를 참조하는 경우는 보수적으로 차단되거나 추가 fixture가 필요하다.
- XPLAN Predicate Information이 없는 유일 object 연결은 confidence `0.85`이며 단계 4 optimizer 의도 검증 전에는 runtime 자동 rewrite에 사용하지 않는다.
- 단계 2 함수는 기존 runtime 경로에 연결하지 않았으므로 롤백은 신규 tokenizer/linker 함수, fixture와 테스트 제거로 제한된다.

### 작업 이력

- 2026-07-05: 로드맵 등록, 단계 1 완료 전 착수 금지.
- 2026-07-05: RED에서 public 함수 부재와 필수 행동 테스트의 실패를 확인했다.
- 2026-07-05: 최소 tokenizer/scope/object/predicate linker로 GREEN을 만들고 helper 분리 REFACTOR 후 관련 43건을 통과했다.
- 2026-07-05: 실제 전체 고객 SQL 연결과 전체 회귀 `266 passed, 기존 10 failed`를 확인하고 단계 2를 `[완료]`로 종료했다. 단계 3은 `[대기]` 상태로 유지한다.

## 단계 3 [완료] — 병목 패턴별 후보 다양화

### 목표

단계 2의 안전한 link 결과를 입력으로 받아 병목 패턴별 구조화 전략을 결정론적으로 계획하고, 실패한 전략의 반복을 막는다. SQL/LLM/DB 실행은 하지 않는다.

### 작업 항목

- `CORRELATED_NOT_EXISTS`, `CORRELATED_EXISTS`, `SCALAR_AGGREGATE`, `REPEATED_FACT_SCAN`, `COMPOSITE_IN` registry를 구현했다.
- correlated NOT EXISTS에 DISTINCT key producer, GROUP BY key producer, UNION DISTINCT set-operation barrier의 3개 전략을 고정 순서로 등록했다.
- 단계 2의 `rewrite_allowed`, confidence, reason code를 선행 gate로 사용해 blocked/저신뢰 link에서는 후보를 0개 반환한다.
- 전략별 target source span/query block/object, transformation summary, expected plan effect, semantic constraints, prerequisites, risk, blocked reason 및 executable 여부를 구조화했다.
- failure feedback의 strategy ID는 재계획에서 제외한다. `DISTINCT_CTE_MERGED`이면 barrier를 다음 1순위로 승격한다.
- SQL 또는 candidate SQL 문자열은 생성하지 않고 `sql_execution_allowed=false`를 명시했다.

### 변경 파일

- `tools/asta_strategy_planner.py`
- `tests/test_asta_strategy_planner.py`
- `tools/asta_quality_agent.py` — 3초 활성 정책 상수
- `tools/run_asta_prompt_abc_adb.py` — runner 기본 3초 정책
- `db/adb/asta_pkg.sql` — 미배포 3초 PL/SQL 소스
- `asta-quality-agent.yaml`, `asta-quality-agent.yaml.example`
- `static/js/extensions/tuning_assistant.js`
- `docs/ASTA_QUALITY_AGENT.md`
- `reports/asta_customer_01_oltp_diagnosis.md`와 현재 latest 정책 보고서
- 관련 정책/registry 테스트, 이 누적 문서와 `.agent-handoff/CONTEXT.md`

### 테스트/실측

- 정책 TDD RED: 2.5초 OLTP 후보가 기존 2초 기본값으로 실패하는 것을 확인했다.
- 정책 GREEN: quality-agent와 runner 모두 2.5초는 통과하고 3.1초는 실패하며 target `3,000,000us`를 반환한다.
- 단계 3 TDD RED: `tools.asta_strategy_planner` 모듈 부재로 신규 계약 테스트 수집 실패를 확인했다.
- 단계 3 GREEN/REFACTOR: 고객 NOT EXISTS 3전략, merge feedback 전환, blocked/unsupported, 결정론성, scalar/EXISTS/repeated fact/composite IN family와 입력 불변성 테스트 `9 passed`.
- 관련 테스트 명령: `UV_NO_CACHE=1 PYTHONPATH=/home/opc/.cache/uv/archive-v0/uV3M1hTXKn5DvRqO/lib/python3.11/site-packages /home/opc/.local/bin/uv run --offline --no-sync python -m pytest -q tests/test_asta_strategy_planner.py tests/test_asta_sql_plan_linker.py tests/test_asta_xplan_bottleneck_ranker.py tests/test_asta_quality_agent.py tests/test_asta_result_digest_contract.py tests/test_asta_workload_type.py::test_oltp_comparison_enforces_three_second_latency_target_before_buffer_win`.
- 관련 결과: `41 passed`.
- 전체 테스트 명령: `UV_NO_CACHE=1 PYTHONPATH=/home/opc/.cache/uv/archive-v0/uV3M1hTXKn5DvRqO/lib/python3.11/site-packages /home/opc/.local/bin/uv run --offline --no-sync python -m pytest -q`.
- 전체 결과: `276 passed, 10 failed`. 기존 실패 10건과 동일하며 이번 정책/단계 3 신규 실패는 0건이다.
- 고객 기본 순서: `NOT_EXISTS_DISTINCT_KEY_ANTI` → `NOT_EXISTS_GROUP_BY_KEY_ANTI` → `NOT_EXISTS_UNION_DISTINCT_BARRIER`.
- DISTINCT merge feedback 후 순서: 실패 DISTINCT 제외 → `NOT_EXISTS_UNION_DISTINCT_BARRIER` → `NOT_EXISTS_GROUP_BY_KEY_ANTI`.
- Python compile과 `git diff --check`를 통과했다.

### 설계 결정

- strategy registry는 별도 순수 Python 모듈에 두고 기존 runtime에서 import하지 않는다.
- 단계 2 link confidence `0.8` 미만, `BLOCKED`, `rewrite_allowed=false`는 전략 생성 전에 차단한다.
- registry 정의는 호출마다 deep copy해 입력, feedback, 전역 registry가 변경되지 않게 했다.
- `executable=true`는 후보 SQL 생성 단계로 넘길 수 있는 전략이라는 뜻이며 실제 실행 허가는 아니다. 실제 SQL/DB 실행은 `sql_execution_allowed=false`로 금지한다.
- failure feedback은 이미 실패한 strategy ID를 재시도하지 않는 결정론적 exclusion/reorder에만 사용한다.

### 완료 기준

- 고객 NOT EXISTS link에서 서로 다른 3개 전략과 완전한 target/constraint/effect 계약이 생성된다.
- DISTINCT merge 실패 뒤 동일 전략을 반복하지 않고 barrier가 1순위가 된다.
- blocked/unsupported link는 후보 0개와 명시적 차단 reason을 반환한다.
- 네 가지 필수 pattern family와 correlated EXISTS를 결정론적으로 선택한다.
- 관련 테스트 통과 및 전체 회귀 신규 실패 0건.

### 위험/롤백

- registry는 구조화 계획일 뿐 실제 SQL의 문법·의미·optimizer 효과를 보장하지 않는다. SQL 생성/검증은 후속 단계다.
- composite IN의 nullable tuple, scalar aggregate empty-input, wildcard grain은 전략 semantic constraints로만 기록하며 아직 증명하지 않는다.
- failure reason taxonomy는 현재 `DISTINCT_CTE_MERGED`와 일반 strategy exclusion 중심이다. ORA/동등성/성능 feedback 세분화는 후속 확장 대상이다.
- 실행 횟수와 후보 예산은 단계 5 범위이므로 이번에는 실행하지 않는다.
- 롤백은 신규 planner/test 제거와 3초 활성 정책 소스를 이전 값으로 복원하는 것이며, DB는 미배포 상태라 객체 롤백이 필요 없다.

### 작업 이력

- 2026-07-05: 로드맵 등록.
- 2026-07-05: 활성 OLTP hard guard를 3초로 변경하고 2.5초 통과/3.1초 실패 경계를 검증했다. 300ms 증가 guard는 유지했다.
- 2026-07-05: 단계 3 RED 후 deterministic registry/planner를 구현하고 고객 merge 실패 feedback에서 barrier 승격을 확인했다.
- 2026-07-05: 관련 41건, 전체 `276 passed, 기존 10 failed`를 확인하고 단계 3을 `[완료]`로 종료했다. 단계 4는 `[대기]`다.

## 단계 4 [완료] — Optimizer 의도 검증

### 목표

후보 strategy의 `expected_plan_effect`가 실제 After XPLAN에 나타났는지 Before/After tree와 ALLSTATS Starts로 확인하고, 확인되지 않으면 result digest와 성능 판정 전에 fail-closed로 거절한다.

### 작업 항목

- Plan hash/node id가 아니라 target object, operation family, active execution과 부모-자식 tree로 의미상 대응 node를 찾는다.
- producer와 대응 fact descendant의 Before/After Starts를 비교해 반복 subtree 제거를 검증한다.
- strategy의 producer Starts, ANTI consumer, set-operation merge barrier 기대값을 실제 operation tree에서 확인한다.
- DISTINCT key CTE가 Starts 845로 남으면 `DISTINCT_CTE_REMERGED`로 탐지하고 `OPTIMIZER_INTENT_NOT_MET`로 거절한다.
- target active node가 없거나 복수이고 Starts/operation 증거가 모호하면 `INSUFFICIENT_PLAN_EVIDENCE`로 차단한다.
- `evaluate_candidate_after_optimizer_intent`는 VERIFIED가 아니면 evidence run을 읽어 digest/성능 비교를 호출하지 않는다.
- quality normalize/failure taxonomy에 optimizer verdict와 평가 여부를 보존해 보고 원인이 명확히 남도록 했다.

### 변경 파일

- `tools/asta_optimizer_intent.py`
- `tools/asta_quality_agent.py`
- `tests/test_asta_optimizer_intent.py`
- `tests/fixtures/asta_customer_01_distinct_merged_xplan.txt`
- `tests/fixtures/asta_customer_01_union_barrier_xplan.txt`
- `reports/asta_phase4_tdd.md`
- `docs/ASTA_SQL_TUNING_IMPROVEMENT_HISTORY.md`
- `.agent-handoff/CONTEXT.md`

### 테스트/실측

- 수직 슬라이스 1 RED: `tools.asta_optimizer_intent` 부재로 collection error. GREEN: plan hash `1663017477→101251183` 변경과 무관하게 VIF producer Id `28→31`을 의미상 대응시켜 `1 passed`.
- 수직 슬라이스 2 RED: `verify_optimizer_intent` import 실패. GREEN: 실패 DISTINCT, 성공 barrier, plan-hash-only, 누락/모호 증거 행동 `5 passed`.
- 수직 슬라이스 3 RED: `evaluate_candidate_after_optimizer_intent` import 실패. GREEN: digest/성능 선행 차단 포함 `7 passed`.
- REFACTOR RED: quality normalize에서 `optimizer_intent_verdict`가 소실되어 `KeyError`. GREEN: verdict/reason/evaluation flags 보존 후 단계 4 `7 passed`.
- 정확한 명령과 실제 실패/통과 로그: `reports/asta_phase4_tdd.md`.
- 관련 테스트 명령: `UV_NO_CACHE=1 PYTHONPATH=/home/opc/.cache/uv/archive-v0/uV3M1hTXKn5DvRqO/lib/python3.11/site-packages /home/opc/.local/bin/uv run --offline --no-sync python -m pytest -q tests/test_asta_optimizer_intent.py tests/test_asta_strategy_planner.py tests/test_asta_sql_plan_linker.py tests/test_asta_xplan_bottleneck_ranker.py tests/test_asta_quality_agent.py tests/test_asta_result_digest_contract.py tests/test_asta_workload_type.py::test_oltp_comparison_enforces_three_second_latency_target_before_buffer_win`.
- 관련 결과: `48 passed`.
- 전체 테스트 명령: `UV_NO_CACHE=1 PYTHONPATH=/home/opc/.cache/uv/archive-v0/uV3M1hTXKn5DvRqO/lib/python3.11/site-packages /home/opc/.local/bin/uv run --offline --no-sync python -m pytest -q`.
- 전체 결과: `283 passed, 10 failed`. 단계 3 baseline `276 passed, 10 failed` 대비 신규 7건 통과, 기존 실패 10건 동일, 신규 실패 0건이다.
- 실패 DISTINCT 전체 실측: VIF Id 28 Starts `845→845`, fact Id 38 Starts `845→845`, `REJECTED / OPTIMIZER_INTENT_NOT_MET`.
- 성공 barrier 전체 실측: VIF Id `28→31`, Starts `845→1`; fact Id `38→41`, Starts `845→1`; ANTI와 `SORT UNIQUE+UNION-ALL` 유지, `VERIFIED`.
- Python compile과 `git diff --check` 통과.

### 설계 결정

- plan hash는 evidence에 기록하지만 성공 조건에 포함하지 않는다.
- inactive Starts=0 branch는 후보 producer로 선택하지 않고 active target object가 Before/After 각각 정확히 하나일 때만 대응한다.
- operation은 VIEW/INDEX_ACCESS/TABLE_ACCESS family로 정규화하고, descendant는 object+operation family로 대응한다.
- expected effect는 registry의 start target과 consumer/barrier 요구를 읽어 검증하며 고정 SQL 문자열을 찾지 않는다.
- VERIFIED 결과만 기존 deterministic result digest/3초 latency/성능 비교로 전달한다.
- runtime DB/ORDS에는 연결하거나 배포하지 않고 로컬 순수 평가 계약과 quality report taxonomy까지만 구현했다.

### 완료 기준

- 성능 수치가 좋아도 optimizer intent가 REJECTED/BLOCKED면 digest와 성능 판정을 수행하지 않는다.
- 고객 실패/성공 fixture가 각각 정확한 reason과 Starts/tree evidence로 REJECTED/VERIFIED된다.
- plan hash만 바꾼 동일 실패 shape는 통과하지 않는다.
- node/Starts/operation 증거가 누락·모호하면 추측 없이 `INSUFFICIENT_PLAN_EVIDENCE`다.
- 관련 테스트 통과 및 전체 회귀 신규 실패 0건.

### 위험/롤백

- 현재 대응은 active object name이 유일하다는 전제다. synonym, 동일 object의 여러 active branch, PX/adaptive plan은 보수적으로 차단할 수 있다.
- excerpt fixture는 실측 관련 subtree를 보존했지만 전체 plan의 모든 transformation을 일반화하지 않는다. 전체 저장 plan으로 별도 동일 판정을 확인했다.
- set-operation barrier는 ancestor `SORT UNIQUE`와 `UNION-ALL`로 확인한다. 다른 Oracle transformation의 동등한 barrier 표현은 추가 fixture가 필요하다.
- scalar/composite/fact strategy의 start key는 읽지만 고객 사례 수준의 operation-specific assertion fixture는 후속 확장이 필요하다.
- 로컬 wrapper를 기존 DB/ORDS runtime에 배포하지 않았으므로 실서비스 판정에는 아직 적용되지 않는다.
- 롤백은 신규 optimizer 모듈/테스트/fixture 제거와 quality-agent의 optimizer 필드·failure taxonomy 추가분 제거다. DB 객체 롤백은 필요 없다.

### 작업 이력

- 2026-07-05: 로드맵 등록.
- 2026-07-05: 실제 실패 DISTINCT와 성공 UNION barrier XPLAN을 fixture로 고정하고 세 수직 슬라이스 RED→GREEN→REFACTOR를 완료했다.
- 2026-07-05: 전체 저장 XPLAN에서도 DISTINCT 재-merge 거절과 barrier Starts=1/구조 유지 VERIFIED를 확인했다.
- 2026-07-05: 관련 48건, 전체 `283 passed, 기존 10 failed`를 확인하고 단계 4를 `[완료]`로 종료했다. 단계 5는 `[대기]`다.

## 단계 5 [완료] — 반복 측정과 실행예산

### 목표

Before/After 반복, cache/order 편향, timeout과 runaway session을 제한하면서 재현 가능한 중앙값을 얻는다.

### 작업 항목

- workload별 warm-up/측정 횟수, 후보 수, 전체·후보별 실행 횟수와 wall-clock 예산을 정의했다.
- Before 우선 및 측정 round별 후보 순서 rotation을 결정론적 schedule로 만들고 warm-up은 중앙값과 noise에서 제외했다.
- 완료된 측정만으로 elapsed/Buffer Gets 중앙값과 변동폭을 계산하며 누락, 실패, timeout, runaway 및 과도한 noise는 fail-closed 처리했다.
- 단계 4 `VERIFIED`를 첫 gate로 두고, 그 뒤에 실행 안전성·예산, 측정 완전성·noise, result digest, 성능 및 OLTP 3초/원본 대비 300ms guard 순으로 판정했다.
- timeout/runaway에는 취소 요청과 잔류 session 확인 필요 상태를 남기고, 실패한 후보는 terminal 처리해 추가 실행을 막았다.
- 기존 runner의 반복 비교 함수를 재사용해 digest와 Buffer Gets 5% 감소 계약을 유지했다.

### 변경 파일

- `tools/asta_execution_budget.py`
- `tools/asta_quality_agent.py`
- `asta-quality-agent.yaml.example`
- `tests/test_asta_execution_budget.py`
- `tests/test_asta_quality_agent.py`
- `tests/fixtures/asta_customer_01_measurement_campaign.json`
- `reports/asta_phase5_tdd.md`
- `docs/ASTA_QUALITY_AGENT.md`
- `docs/ASTA_SQL_TUNING_IMPROVEMENT_HISTORY.md`
- `.agent-handoff/CONTEXT.md`

### 테스트/실측

- 수직 슬라이스 1 RED: 실행예산 모듈 부재로 collection error. GREEN: schedule/median/noise 행동 `2 passed`.
- 수직 슬라이스 2 RED: `check_execution_budget` import 실패. GREEN: 전체·후보별 횟수/시간 예산 행동 `5 passed`.
- 수직 슬라이스 3 RED: campaign evaluator import 실패. 최초 GREEN에서 status merge 결함으로 `2 failed, 9 passed`, 수정 후 `11 passed`.
- REFACTOR RED: schedule preflight와 quality normalize reason 보존 행동 `2 failed`; 수정 후 `13 passed`. workload override resolver RED import 실패 후 최종 단계 5 `14 passed`.
- 정확한 명령과 실제 RED/GREEN 결과는 `reports/asta_phase5_tdd.md`에 기록했다.
- 관련 테스트: `62 passed in 0.38s`.
- 전체 테스트: `297 passed, 10 failed in 0.85s`. 단계 4 baseline `283 passed, 10 failed` 대비 신규 14건 통과, 기존 실패 10건 동일, 신규 실패 0건이다.
- 고객 실측 fixture의 warm-up 제외 결과: Before elapsed 중앙값 `124,498,199us`, After `1,641,880us`; noise `15.04%`/`1.758%`; Buffer Gets 감소 `88.2167%`; digest 일치 및 단계 4 intent VERIFIED로 최종 `ACCEPTED`다.
- fixture 예산 사용량은 전체 8회/`527,659ms`, 후보 4회/`6,603ms`이며 설정 상한 안이다.

### 완료 기준

- budget preflight 및 누적 ledger가 전체·후보별 실행 횟수/시간 초과를 명시적 reason code로 차단한다.
- 중앙값, noise, warm-up 제외, 처리 실행 수와 중단 사유가 구조화된다.
- intent 미검증, 증거 부족, 측정 불완전, noise 초과, timeout/runaway는 성공으로 추측하지 않는다.
- timeout/runaway는 취소 및 잔류 session 확인 요구를 반환하고 해당 후보의 후속 실행을 차단한다.
- OLTP 후보는 중앙 elapsed 3초 이하와 원본 대비 증가 300ms 이하를 모두 통과해야 한다.
- 관련 테스트 통과 및 전체 회귀 신규 실패 0건.

### 설계 결정

- 신규 모듈은 DB를 호출하지 않는 순수 planning/evaluation 계층이다. 실제 실행기는 반환된 schedule, budget decision, cancel/session-check 계약을 소비해야 한다.
- 실행 ledger는 입력을 변경하지 않고 새 상태를 반환해 재시도 및 병렬 orchestration에서 결정론성을 유지한다.
- schedule 생성 시 후보 수·예상 실행 횟수를 먼저 검사해 명백한 예산 초과는 DB 호출 전에 차단한다.
- cache 편향을 완전히 제거했다고 가정하지 않고 순서 rotation과 측정 noise를 evidence로 보존한다.
- 결과 digest와 기존 성능 비교는 단계 4 intent, 실행 안전성, 예산 및 측정 품질 gate를 통과한 뒤에만 평가한다.

### 위험/롤백

- 반복 실행 자체가 Source 부하가 될 수 있어 기본값은 warm-up 1회, 측정 3회, 후보 최대 4개, 전체 20회/10분으로 제한했다. workload override로 더 보수적인 값을 적용할 수 있다.
- Python timeout 결과의 실제 Oracle cancel과 잔류 session 조회는 실행 adapter 책임이다. 이번 단계는 이를 요구하는 구조화 상태까지만 구현했고 외부 DB에서 새 실행하지 않았다.
- fixture의 warm-up 값은 실측 3회와 분리된 제어 표본이다. 중앙값/성능 근거는 기존 고객 실측 3회만 사용한다.
- median range 기반 noise는 작은 표본의 간단한 gate다. p95나 신뢰구간은 표본·예산 정책 확장 후 추가해야 한다.
- 신규 모듈은 아직 실서비스 runtime/DB/ORDS에 배포되지 않았다.
- 롤백은 신규 execution-budget 모듈/테스트/fixture 제거, quality-agent의 단계 5 taxonomy/필드 제거, config의 `execution_budget` 블록 제거다. DB 객체 롤백은 필요 없다.

### 작업 이력

- 2026-07-05: 로드맵 등록.
- 2026-07-05: schedule·측정 요약, 실행예산 ledger, campaign gate를 세 수직 슬라이스 RED→GREEN→REFACTOR로 구현했다.
- 2026-07-05: 고객 OLTP 실측 fixture가 intent→budget/safety→measurement→digest/performance 순서로 ACCEPTED됨을 확인했다.
- 2026-07-05: 관련 `62 passed`, 전체 `297 passed, 기존 10 failed`를 확인하고 단계 5를 `[완료]`로 종료했다. 단계 6은 `[대기]`다.

## 단계 6 [완료] — 동등성 검증 확장

### 목표

현재 first-N ordered digest를 NULL, datatype, 순서, 중복과 전체 결과 규모에 맞게 확장한다.

### 작업 항목

- SQL의 최종 top-level `ORDER BY`를 comment, string, quoted identifier 및 analytic 내부 정렬과 구분해 `ORDERED_ROWS`/`UNORDERED_MULTISET` 정책을 결정한다.
- ordered 결과는 행 순서를 보존하고 unordered 결과는 typed row hash를 정렬하되 중복 hash를 모두 유지해 multiset multiplicity를 보존한다.
- 컬럼 위치·이름·Oracle datatype·precision·scale·길이·charset metadata를 별도 digest하고 NULL과 빈 문자열, 숫자, 문자열, RAW, 날짜/시간을 type tag와 length prefix로 canonicalize한다.
- DATE/TIMESTAMP는 typed value만 받아 NLS 의존 문자열을 차단하고 미지원 datatype은 구조화된 불완전 evidence로 반환한다.
- 전체 행 수, digest 처리 행 수, chunk 완료, truncation, scope, mode, algorithm, metadata 및 반복 실행 안정성을 모두 확인한다.
- row/byte budget 초과, bounded/truncated evidence, mode/metadata 불일치와 반복 불안정은 명시적 reason code로 fail-closed 처리한다.
- 단계 4 intent `VERIFIED` → 단계 6 result equivalence `VERIFIED` → 단계 5 budget/반복 측정/성능 순서를 campaign에 적용했다.
- 품질 실험 runner가 SQL을 전달해 기존 `BOUNDED_ORDERED_FIRST_N` digest를 semantic success로 인정하는 우회 경로를 차단했다.

### 변경 파일

- `tools/asta_result_equivalence.py`
- `tools/asta_execution_budget.py`
- `tools/run_asta_prompt_abc_adb.py`
- `tools/asta_quality_agent.py`
- `tests/test_asta_result_equivalence.py`
- `tests/test_asta_execution_budget.py`
- `tests/test_asta_quality_agent.py`
- `tests/test_asta_result_digest_contract.py`
- `asta-quality-agent.yaml.example`
- `reports/asta_phase6_tdd.md`
- `docs/ASTA_QUALITY_AGENT.md`
- `docs/ASTA_SQL_TUNING_IMPROVEMENT_HISTORY.md`
- `.agent-handoff/CONTEXT.md`

### 테스트/실측

- 수직 슬라이스 1 RED: `tools.asta_result_equivalence` 부재로 collection error. GREEN: 순서 정책과 typed ordered/multiset digest `3 passed`.
- 수직 슬라이스 2 RED: `verify_result_equivalence` import 실패. GREEN: full evidence와 bounded/truncated/budget/mode/metadata/row/digest 판정 `7 passed`.
- 수직 슬라이스 3 RED: campaign의 `equivalence_evidence` 인자 부재로 `2 failed`. GREEN: intent→equivalence→measurement 순서 및 과거 bounded 차단 `2 passed`.
- REFACTOR RED: chunk 크기별 digest 불일치와 unsupported datatype 예외 유출 `2 failed`; 수정 후 단계 6+5 `25 passed`.
- row/byte budget 및 typed temporal RED: `max_bytes` 인자 부재 `1 failed`; GREEN 후 NLS 문자열 날짜와 byte 초과가 구조화 차단됐다.
- quality RED: phase 6 필드 소실 `KeyError`; GREEN 후 equivalence status/verdict/evidence와 실패 taxonomy를 보존했다.
- config RED: `equivalence_budget` 부재 `KeyError`; GREEN 후 full-result 필수, 100만 행/256MiB 상한을 명시했다.
- runner RED: `sql_text` 인자 부재 `TypeError`; GREEN 후 SQL-aware full-result gate가 활성화됐다.
- 정확한 명령과 실제 RED/GREEN 결과는 `reports/asta_phase6_tdd.md`에 기록했다.
- 관련 테스트: `76 passed in 0.39s`.
- 전체 테스트: `311 passed, 10 failed in 0.86s`. 단계 5 baseline `297 passed, 10 failed` 대비 신규 14건 통과, 기존 실패 10건 동일, 신규 실패 0건이다.
- 고객의 기존 3회 digest는 `BOUNDED_ORDERED_FIRST_N`이므로 단계 6에서 `BLOCKED / FULL_RESULT_EVIDENCE_REQUIRED`, 처리 측정 0회 및 budget 소비 0으로 판정된다.
- 결정적 full-result fixture는 unordered 행 순서 변경을 VERIFIED하고, ordered 순서 변경·중복 제거·NULL 변경·metadata precision 변경을 각각 non-equivalent로 판정했다.

### 완료 기준

- `FULL_RESULT` scope, 전체 행 수/metadata/mode/algorithm/chunk 완전성 및 안정 digest가 모두 일치할 때만 `RESULT_EQUIVALENCE_VERIFIED`다.
- ORDER BY 결과는 순서까지, ORDER BY 없는 결과는 중복을 유지한 multiset으로 비교한다.
- row count/shape 및 first-N fallback은 semantic proof가 아니며 성능 판정으로 넘기지 않는다.
- 전체 결과 검증 예산 초과, 잘린 evidence, mode/metadata 불일치, 증거 불완전은 추측 없이 차단한다.
- 동등성 실패 시 단계 5 실행예산을 소비하거나 성능 판정을 수행하지 않는다.
- 관련 테스트 통과 및 전체 회귀 신규 실패 0건.

### 설계 결정

- root digest는 chunk 경계와 무관한 typed row stream으로 계산하고 chunk digest/count는 수집 완전성 증거로만 둔다.
- unordered multiset은 row hash 정렬 후 모든 항목을 root stream에 포함하므로 같은 행의 중복 횟수를 제거하지 않는다.
- 빈 결과 0행과 scalar aggregate의 NULL 1행을 서로 다른 행 수와 digest로 보존한다.
- metadata digest가 다르면 값 digest가 우연히 같아도 `RESULT_METADATA_MISMATCH`다.
- 기존 Source package의 bounded evidence를 거짓으로 full evidence로 승격하지 않았다. 로컬 source/ADB package는 이번 단계에서 변경·compile하지 않았다.

### 위험/롤백

- 전체 결과 직렬화 비용이 원 쿼리보다 커질 수 있어 기본 상한을 100만 행/256MiB로 두며 초과 시 `EQUIVALENCE_BUDGET_EXCEEDED`로 차단한다.
- 현재 Python canonicalizer는 주요 scalar type을 지원하며 BLOB/object/XML/vector 등 미지원 type은 fail-closed다.
- SQL order detector는 최종 top-level ORDER BY 기준이다. Oracle MODEL, MATCH_RECOGNIZE 등 특수 순서 의미에는 추가 fixture가 필요하다.
- 실제 Source `ASTA_SOURCE_PKG`는 여전히 bounded first-N만 생성하므로 현재 고객 후보는 실환경 full-result producer 구현·compile·재실행 전에는 단계 6을 통과할 수 없다.
- 신규 gate와 runner 연결은 로컬 코드뿐이며 DB/ORDS/서비스에는 배포하지 않았다.
- 롤백은 result-equivalence 모듈/테스트 제거, campaign·runner·quality의 equivalence 필드/호출 제거, config의 `equivalence_budget` 제거다. DB 객체 롤백은 필요 없다.

### 작업 이력

- 2026-07-05: 로드맵 등록.
- 2026-07-05: ordered/multiset typed full-result digest와 fail-closed evidence verifier를 수직 슬라이스 TDD로 구현했다.
- 2026-07-05: campaign과 품질 runner에 단계 4→6→5 순서를 적용하고 기존 first-100 고객 증거가 차단됨을 확인했다.
- 2026-07-05: 관련 `76 passed`, 전체 `311 passed, 기존 10 failed`를 확인하고 단계 6을 `[완료]`로 종료했다. 단계 7은 `[대기]`다.

## 단계 7 [완료] — Bind와 plan 안정성

### 목표

대표 bind 집합과 child cursor 환경에서 후보의 성능 및 의미 안정성을 검증한다.

### 작업 항목

- 대표 bind는 이름, 위치, Oracle datatype, NULL 여부, 선택도 bucket 및 `sha256:` fingerprint만 보존하고 원문 값 key와 비-hash fingerprint를 차단한다.
- Before/After bind fingerprint 일치, bind signature 일관성, 최소 case 수와 `NULL`/`SELECTIVE`/`BROAD` bucket coverage를 검증한다.
- 각 bind의 Before/After plan 반복 표본에서 target object의 active node, plan family, 정규화 shape와 target subtree Starts signature를 계산한다.
- 같은 plan hash여도 shape/Starts가 바뀌면 차단하고, plan hash가 달라도 shape/Starts가 안정적이면 허용한다.
- 동일 bind 내 plan family flip, shape 변화, Starts 불안정, Before baseline 불안정 및 plan 증거 부족을 fail-closed 처리한다.
- bucket별 expected plan family에 맞는 parameter-sensitive variation은 허용하되 예상 밖 family는 차단한다.
- 모든 bind에 대해 Optimizer Intent → Full-result Equivalence → Bind/Plan Stability를 먼저 완료한 뒤 전체 실행예산을 preflight하고 반복 측정/성능을 수행한다.
- 한 bind라도 digest, intent, 3초 latency/300ms 증가, Buffer Gets, noise 또는 예산 gate를 실패하면 후보 전체를 거절한다.

### 변경 파일

- `tools/asta_bind_plan_stability.py`
- `tools/asta_quality_agent.py`
- `tests/test_asta_bind_plan_stability.py`
- `tests/fixtures/asta_customer_01_bind_cases.json`
- `tests/test_asta_quality_agent.py`
- `asta-quality-agent.yaml.example`
- `reports/asta_phase7_tdd.md`
- `docs/ASTA_QUALITY_AGENT.md`
- `docs/ASTA_SQL_TUNING_IMPROVEMENT_HISTORY.md`
- `.agent-handoff/CONTEXT.md`

### 테스트/실측

- 수직 슬라이스 1 RED: `tools.asta_bind_plan_stability` 부재로 collection error. GREEN: 대표 bind privacy/metadata/NULL/bucket coverage `3 passed`.
- 수직 슬라이스 2 RED: plan stability public 함수 import 실패. GREEN: actual customer XPLAN 기반 family/shape/Starts 안정성 `7 passed`.
- 수직 슬라이스 3 RED: bind campaign 함수 import 실패. GREEN: 세 bind 전체 gate, latency 회귀, 선행 gate 및 전체 budget `11 passed`.
- REFACTOR RED: Before plan evidence 미검증과 bind별 실패 reason 미분류 `2 failed`; 수정 후 Before/After 독립 안정성과 digest/Buffer/noise 원인을 보존했다.
- quality RED: phase 7 필드 소실 `KeyError`; GREEN 후 bind 결과와 failure taxonomy를 보존했다.
- config RED: `bind_stability` 부재 `KeyError`; 추가 직후 YAML `NULL`이 null로 해석되는 실패를 확인하고 문자열 bucket으로 수정했다.
- privacy RED: 평문 fingerprint가 VERIFIED되는 `1 failed`; `sha256:` 형식만 허용하도록 수정했다.
- 판정 순서 RED: 두 번째 bind digest mismatch 전에 첫 bind 8회가 처리됨; 실제 full-result evidence를 모든 bind에서 먼저 검증해 `processed_run_count=0`으로 수정했다.
- 정확한 명령과 결과는 `reports/asta_phase7_tdd.md`에 기록했다.
- 관련 테스트: `90 passed in 0.43s`.
- 전체 테스트: `325 passed, 10 failed in 0.89s`. 단계 6 baseline `311 passed, 10 failed` 대비 신규 14건 통과, 기존 실패 10건 동일, 신규 실패 0건이다.
- 3개 익명 bind fixture의 정상 campaign은 24회, 최악 After 중앙 elapsed `1,641,880us`, 최악 noise `1.758%`로 `ACCEPTED / BIND_PLAN_STABILITY_VERIFIED`다.
- actual 성공 barrier XPLAN은 `SET_OPERATION_BARRIER`, deterministic broad 파생 plan은 `ANTI_SINGLE_PRODUCER`로 bucket 정책에 따라 함께 허용됐다.
- actual 실패 DISTINCT XPLAN을 한 bind의 반복 표본에 섞으면 `PLAN_FLIP_DETECTED`; 동일 hash shape 변경은 `PLAN_SHAPE_UNSTABLE`; descendant Starts 변경은 `STARTS_SUBTREE_UNSTABLE`다.

### 완료 기준

- 원문 값 없이 대표 bind signature, NULL 및 선택도 coverage와 Before/After 동일 bind 적용을 증명한다.
- 각 bind의 Before와 After plan 반복 표본이 독립적으로 안정적이며 expected family/intent를 충족한다.
- 합리적 bind-sensitive family variation은 허용하되 동일 bind의 plan flip, shape/Starts 불안정은 차단한다.
- 대표 bind 성공률은 100%이며 어느 bind에서도 equivalence, intent, OLTP latency, Buffer/noise gate 실패를 허용하지 않는다.
- 전체 bind 실행예산을 DB 실행 전에 확인하고 초과 시 처리 실행 0회로 차단한다.
- 관련 테스트 통과 및 전체 회귀 신규 실패 0건.

### 설계 결정

- plan hash는 관측 evidence일 뿐 안정성의 충분조건이 아니다. 정규화 operation/object/parent shape와 target subtree Starts를 별도로 비교한다.
- 다른 bind bucket 사이의 plan family 차이는 정책에 명시된 expected family이고 각 bind 내부가 안정적일 때만 허용한다.
- Before와 After shape가 서로 달라지는 것은 구조적 rewrite의 정상 결과일 수 있으므로 각 side의 반복 안정성을 검증하며 동일 shape를 강제하지 않는다.
- 모든 bind의 실제 full-result evidence를 plan 안정성 전에 재검증해 선언 상태와 evidence 불일치가 측정으로 넘어가지 않게 했다.
- 성공률 하한은 현재 `max_failed_bind_cases=0`, 즉 대표 bind 100% 통과로 고정했다.

### 위험/롤백

- bind fingerprint는 원문을 저장하지 않지만 낮은 cardinality 값은 사전 대입 위험이 있어 실제 운영에서는 keyed/HMAC fingerprint와 접근 통제가 더 안전하다.
- plan family 분류는 현재 target object, ANTI, `SORT UNIQUE+UNION-ALL`, Starts 중심이다. PX/adaptive inactive branch, SQL Plan Directive 등에는 추가 fixture가 필요하다.
- fixture는 익명 synthetic bind metadata와 기존 고객 XPLAN/측정의 결정적 조합이다. 실제 child cursor/ACS 및 bind-aware flag를 Source에서 새로 수집하지 않았다.
- 단계 6과 마찬가지로 현재 Source package가 full-result evidence를 생성하지 않으므로 실환경 고객 후보는 아직 단계 7까지 도달할 수 없다.
- 신규 모듈과 quality/config 계약은 로컬에만 있으며 DB/ORDS/서비스에 배포하지 않았다.
- 롤백은 bind-plan 모듈/테스트/fixture 제거, quality taxonomy/필드 제거, config의 `bind_stability` 블록 제거다. DB 객체 롤백은 필요 없다.

### 작업 이력

- 2026-07-05: 로드맵 등록.
- 2026-07-05: 대표 bind coverage, plan shape/Starts 안정성, multi-bind campaign을 세 수직 슬라이스 TDD로 구현했다.
- 2026-07-05: 단계 4→6→7→5 순서를 강제하고 bind별 latency/Buffer/noise/digest 및 전체 실행예산 실패를 검증했다.
- 2026-07-05: 관련 `90 passed`, 전체 `325 passed, 기존 10 failed`를 확인하고 단계 7을 `[완료]`로 종료했다. 단계 8은 `[대기]`다.

## 단계 8 [완료] — 상태머신, UI, Vector 학습

### 목표

진단·후보·검증 상태를 UI에서 정확히 설명하고, 검증된 성공 사례만 Vector 학습에 사용한다.

### 작업 항목

- `OPTIMIZER_INTENT → FULL_RESULT_EQUIVALENCE → BIND_PLAN_STABILITY → EXECUTION_MEASUREMENT → FINAL_DECISION` 순서를 명시적 순수 상태머신으로 정의했다.
- out-of-order, 증거 누락 및 미승인 restart는 fail-closed 처리하고 terminal failure/rejection/block은 이후 success 이벤트가 덮어쓰지 못하게 했다.
- 동일 attempt 재조회는 기존 terminal snapshot을 그대로 반환하고 새 attempt는 명시적 restart 승인만 허용한다.
- UI에 현재 단계, 차단 reason, 증거 수준, Optimizer intent, full-result equivalence, bind/plan 안정성, 실행예산/반복측정을 한국어 gate 카드로 표시한다.
- UI gate는 `createElement`/`textContent`와 label allowlist만 사용하며 raw HTML·외부 URL을 만들지 않는다.
- `BLOCKED/REJECTED/FAILED`를 완료 progress나 success toast로 승격하지 않고 authoritative terminal 상태와 원본 reason을 유지한다.
- UI 표시·오류 상세·다운로드 report에서 SQL block/literal/bind 값을 redaction하고 raw response JSON fallback을 제거했다.
- Vector positive는 모든 gate와 `FULL_RESULT`가 확인된 `POSITIVE_VERIFIED`만 허용한다.
- 실패·증거 부족·bounded digest·intent 미달·bind 불안정·timeout은 `REJECTED_OBSERVATION`으로 분리하고 reason/evidence만 보존한다.
- 로컬 ADB Vector 소스는 positive만 검색하며 SQL CLOB/chunk를 저장하지 않고 allowlist metadata, 내부 report reference, 검증/거절 chunk만 저장하도록 변경했다.

### 변경 파일

- `tools/asta_workflow_state.py`
- `tools/asta_vector_learning.py`
- `static/js/extensions/tuning_assistant.js`
- `db/adb/asta_pkg.sql`
- `db/adb/asta_vector_pkg.sql`
- `db/asta/004_asta_vector_tables.sql`
- `tests/test_asta_workflow_state.py`
- `tests/test_asta_phase8_ui_vector_contract.py`
- `tests/fixtures/asta_phase8_workflow_scenarios.json`
- `tests/test_asta_contract_hardening_codex.py`
- `tests/test_asta_adb_ords_static_contracts.py`
- `tests/test_asta_ui_run_id.py`
- `reports/asta_phase8_tdd.md`
- `docs/ASTA_QUALITY_AGENT.md`
- `docs/ASTA_SQL_TUNING_IMPROVEMENT_HISTORY.md`
- `.agent-handoff/CONTEXT.md`

### 테스트/실측

- 상태머신 RED: `tools.asta_workflow_state` 부재 collection error. GREEN: 순서, terminal precedence, 재조회/restart `4 passed`.
- Vector RED: `tools.asta_vector_learning` 부재 collection error. GREEN: positive/rejected 분리와 민감정보 제외 포함 상태 테스트 `7 passed`.
- UI RED: gate renderer/outcome/redactor 부재로 `3 failed`. GREEN: 안전 DOM, 한국어 gate, 실패 toast 계약 `3 passed`.
- Vector PL/SQL RED: positive filter/rejected 분리/raw SQL 차단 계약 `2 failed`. GREEN 후 stage 8 UI/Vector 계약 `5 passed`.
- REFACTOR RED: ORA에 포함된 SQL 본문이 snapshot에 남아 `1 failed`; ORA 코드는 유지하고 SQL/literal/bind를 redaction해 상태 테스트 `8 passed`.
- 기존 Vector/UI 회귀는 raw SQL chunk와 2-state failure 목록 기대 때문에 `3 failed`; 새 보안·terminal 계약으로 갱신 후 `43 passed`.
- UI report/download raw fallback RED `1 failed`; SQL fenced/detail/section redaction과 raw JSON fallback 제거 후 JS/UI `34 passed`.
- Vector report reference·자유형 rejection reason RED `1 failed`; 내부 경로 allowlist와 reason code redaction, change/advisor 원문 제외 후 단계 8 계약 `6 passed`.
- fixture는 성공, 후보 없음, ORA, 비동등, bounded digest, timeout, intent 미달, bind plan flip을 포함한다.
- 관련 테스트: `135 passed in 0.27s`; `node --check static/js/extensions/tuning_assistant.js` 통과.
- 전체 테스트: `339 passed, 10 failed in 0.92s`. 단계 7 baseline `325 passed, 10 failed` 대비 신규 14건 통과, 기존 실패 10건 동일, 신규 실패 0건이다.
- accepted fixture만 `POSITIVE_VERIFIED`; 나머지 7개 실패/부족 fixture는 모두 `REJECTED_OBSERVATION`이며 positive record는 없다.

### 완료 기준

- 단계 4~7 gate 순서와 terminal precedence가 하나의 deterministic snapshot으로 표현된다.
- 재조회/재시작에서 terminal 결과가 임의로 성공으로 바뀌지 않는다.
- UI가 gate 상태와 reason/evidence를 표시하고 실패를 성공 progress/toast로 바꾸지 않는다.
- UI/Vector/log용 구조화 record에 SQL·bind 원문과 literal이 포함되지 않는다.
- 모든 gate가 VERIFIED/ACCEPTED이고 full-result evidence인 경우만 positive Vector 대상이다.
- rejected 관측은 positive 검색에서 제외되지만 reason과 안전한 evidence를 별도 보존한다.
- 관련 테스트, JS syntax 및 전체 회귀 신규 실패 0건.

### 설계 결정

- terminal precedence는 첫 authoritative terminal을 보존한다. later success나 중복 poll 응답은 이를 덮어쓰지 못한다.
- 상태 snapshot은 stage별 allowlist evidence만 남기며 원문 SQL field는 입력돼도 폐기한다.
- positive eligibility는 최종 status 문자열 하나가 아니라 다섯 gate의 개별 상태와 `FULL_RESULT` scope를 다시 확인한다.
- rejected observation도 같은 Vector table을 사용할 수 있지만 `learning_class`로 분리하고 positive search는 명시적으로 `POSITIVE_VERIFIED`만 조회한다.
- 기존 Vector row의 raw SQL 컬럼은 schema 호환성을 위해 남지만 신규 save는 NULL을 넣는다. 기존 데이터 삭제는 이번 범위에서 수행하지 않았다.
- UI report 원문은 서버 artifact에 남을 수 있으나 브라우저 표시·다운로드에는 redacted copy만 사용한다.

### 위험/롤백

- 로컬 ADB PL/SQL 변경은 compile하지 않았으므로 Oracle 문법/실행 검증이 필요하다. 원격 DB에는 기존 Vector 동작이 남아 있다.
- 현재 API가 `workflow_state`를 제공하지 않으면 UI는 기존 comparison field로 제한된 fallback 표시를 한다.
- 기존 Vector rows에는 raw SQL/구버전 metadata가 남을 수 있다. 이번 단계는 파괴적 cleanup을 하지 않고 새 검색에서 positive class 없는 legacy row를 제외한다.
- report redaction은 보수적이어서 SQL 제목 아래의 설명 일부까지 숨길 수 있다.
- rejected corpus의 실제 별도 table/index/retention 정책은 배포 전에 운영 설계가 필요하다.
- 롤백은 workflow/vector-learning 모듈과 테스트 제거, UI gate/redaction/outcome 변경 제거, ADB vector positive filter/save 분기와 metadata 필드 제거다. DB 객체는 배포하지 않아 실환경 롤백은 없다.

### 작업 이력

- 2026-07-05: 로드맵 등록.
- 2026-07-05: 상태머신, Vector learning classifier, 안전 UI를 세 수직 슬라이스 RED→GREEN으로 구현했다.
- 2026-07-05: 로컬 ADB Vector 소스에 positive/rejected 분리, positive-only 검색과 raw SQL 비저장 계약을 적용했다.
- 2026-07-05: 관련 `135 passed`, 전체 `339 passed, 기존 10 failed`, JS syntax 통과를 확인하고 단계 8을 `[완료]`로 종료했다.

## 별도 UI 개선 [완료] — 결과서 5개 탭 가독성 개선

### 목표

로드맵 단계 0~8의 판정 의미와 보고서 생성 artifact를 변경하지 않고, 실제 ASTA 결과서의 브라우저 표시만 Overview/튜닝전/튜닝후/상세내용/Object 통계 및 정보의 5개 탭으로 분리한다.

### 작업 항목 및 구현 방식

- ATX Markdown heading을 fenced code 밖에서만 파싱하고 heading level과 정확한 정규화 key를 함께 사용한다. CRLF, 연속 공백, em dash/hyphen, `튜닝전`/`튜닝 전`, `튜닝후`/`튜닝 후`만 제한적으로 정규화하며 fuzzy matching은 하지 않는다.
- 동일 target heading이 여러 번 나오면 해당 section 전체를 `AMBIGUOUS_REPORT_SECTION`으로 제외한다. 누락된 section과 중복 section은 인접 탭으로 흘리지 않고 해당 탭에 `표시할 내용이 없습니다.`를 표시한다.
- 중첩된 H2/H3 범위는 같은 탭 안에서 source offset 순서로 병합하여 heading level과 본문 경계를 보존하고 중복 렌더링을 막는다.
- Overview 상단에 기존 검증 Gate 카드 host를 하나만 두고 workflow/comparison fallback을 그대로 사용한다.
- tablist/tab/tabpanel 역할, `aria-selected`, `aria-controls`, roving tabindex, click과 ArrowLeft/ArrowRight/Home/End 전환 및 focus 이동을 구현했다. 기본 탭은 Overview다.
- fenced SQL/XPLAN은 `pre > code`를 만들고 `textContent`로 넣는다. SQL literal은 UI에서 보존하고 credential/token/connection string만 마스킹한다. raw HTML, script, Markdown/javascript link는 DOM element로 활성화하지 않는다.
- 제한 Markdown renderer는 heading, paragraph, ordered/unordered list, fenced code, pipe table만 allowlist DOM으로 만든다. 수치 비교 pipe table은 실제 HTML table로 표시한다.
- 모바일 tablist는 nowrap horizontal scroll을 사용하며 패널/표/코드도 독립 overflow를 갖는다. 기존 맨 위/맨 아래 컨트롤은 탭 container에 계속 적용되고 탭 전환 시 상단으로 이동한다.
- `window.__astaLastReport.rawReport`에 서버 원문을 별도로 보존하여 Markdown 다운로드는 변경 없이 원문을 사용한다. UI 전용 credential-redacted 사본은 `displayReport/report`로 분리했다.

### 변경 파일

- `static/js/extensions/asta_report_tabs.js`
- `static/js/extensions/tuning_assistant.js`
- `static/index.html`
- `tests/js/asta_report_tabs_dom_test.cjs`
- `tests/test_asta_report_tabs.py`
- `tests/test_asta_phase8_ui_vector_contract.py`
- `tests/test_asta_runtime_deployment_contract.py`
- `docs/ASTA_SQL_TUNING_IMPROVEMENT_HISTORY.md`
- `.agent-handoff/CONTEXT.md`

### RED/GREEN 및 테스트

- RED 명령: 고정 pytest archive `PYTHONPATH`와 `uv run --offline --no-sync python -m pytest -q tests/test_asta_report_tabs.py`. 결과는 `3 failed`; 탭 모듈 부재, 원문 download 분리 부재, index load 부재라는 예상 원인으로 실패했다. 기본 `uv` cache는 read-only였으므로 `UV_CACHE_DIR=/tmp/uv-cache`를 사용했다.
- GREEN DOM 행동: `node tests/js/asta_report_tabs_dom_test.cjs` → `PASS`. 실제 fake DOM에서 정확한 탭 5개/순서/ARIA, click, Arrow/Home/End, focus, panel visibility, Gate 단일 위치, CRLF/heading 변형, code literal, HTML table, raw script/link 비활성, empty state, duplicate fail-closed를 검증했다.
- 관련 테스트: `32 passed in 0.08s` (`tests/test_asta_report_tabs.py`, 기존 tuning static, phase 8 UI/Vector 계약).
- JS syntax: `node --check static/js/extensions/asta_report_tabs.js`, `node --check static/js/extensions/tuning_assistant.js` 모두 통과.
- 전체 회귀: `348 passed, 10 failed in 0.95s`. 직전 baseline의 기존 실패 10건이 그대로이며 이번 변경의 신규 실패는 0건이다.
- 실행 중 서비스는 `select-ai-test.service` PID 759185, active/running 상태를 확인했다. 서비스 재시작은 하지 않았다. localhost HTTP static smoke는 실행 권한 경계에서 거부되어 실제 응답/브라우저 확인은 수행하지 못했다.

### 완료 기준

- 요구된 5개 탭과 heading-to-tab mapping이 결정론적으로 동작하고 모호/누락 section은 fail-closed다.
- Gate는 Overview에만 존재하며 기존 상태 fallback을 유지한다.
- SQL/XPLAN literal과 원문 Markdown download가 보존되고 executable HTML/script/javascript link가 생성되지 않는다.
- 키보드/ARIA/모바일 overflow와 Markdown table/code 가독성 계약을 행동 테스트로 검증한다.
- 관련 테스트 및 JS syntax가 통과하고 전체 회귀 신규 실패가 없다.

### 위험/한계 및 롤백

- renderer는 의도적으로 제한된 Markdown subset만 지원한다. blockquote, nested list, inline emphasis/link는 plain text로 보이며 실행 가능한 HTML로 변환하지 않는다.
- 정확히 등록되지 않은 heading 또는 잘못된 heading level은 다른 탭으로 추측 배치하지 않는다. 보고서 heading 계약이 추가되면 명시적 rule/test가 필요하다.
- static 파일은 디스크에 반영됐지만 서비스 재시작/별도 배포는 하지 않았다. 현재 FastAPI static mount가 즉시 읽는 구조로 예상되나, 이번 작업에서는 HTTP 권한 거부로 실제 제공 여부를 확인하지 못했다.
- 롤백은 index의 `asta_report_tabs.js` include 제거, `tuning_assistant.js`의 tab delegation/CSS/rawReport 분리 제거, 신규 module/test 제거다. DB/ORDS/서비스 롤백은 필요 없다.

### 작업 이력

- 2026-07-05: 기존 이력/handoff/dirty tree를 확인하고 변경을 보존했다.
- 2026-07-05: DOM 행동 계약을 먼저 RED로 추가한 뒤 parser/classifier/safe renderer/tab controller를 GREEN으로 구현했다.
- 2026-07-05: 관련 32건 및 전체 `348 passed, 기존 10 failed`, JS syntax를 확인하여 별도 UI 개선을 `[완료]`로 기록했다.

## 별도 UI 조정 [완료] — 입력 textarea 표시 행 수

### 목표

입력값·payload·검증·모바일 동작을 변경하지 않고 메인 SQL 입력은 10줄, `LLM 참고사항`은 3줄이 보이도록 초기 표시 높이만 조정한다.

### 변경 파일 및 구현

- `static/js/extensions/tuning_assistant.js`: `asta-sql`을 `rows="10"`, `asta-tuning-notes`를 `rows="3"`으로 변경하고 두 label에 정확한 `for` 연결을 추가했다.
- 같은 파일에서 `#asta-sql, #asta-tuning-notes`에만 `height:auto`, `min-height:0`, `overflow-y:auto`를 적용했다. ID specificity가 desktop/mobile의 기존 `.tuning-sql` 고정 height/min-height보다 우선하여 rows 기반 초기 높이를 사용한다.
- 붙여넣기, textarea value, maxlength, validation, formatting, `tuning_context.user_notes` 및 SQL payload 조립은 변경하지 않았다. resize와 textarea 자체 세로 스크롤은 유지했다.
- hidden SQL-only button/debug 경로와 결과서 `pre/code` 영역에는 selector를 적용하지 않았다.
- `static/index.html`: 변경 자산에 한해 `tuning_assistant.js?v=20260705_textarea_rows1`로 cache version을 갱신했다.
- 테스트: `tests/test_asta_textarea_rows.py`, `tests/test_asta_runtime_deployment_contract.py`.

### RED/GREEN 및 테스트

- RED: `uv run --offline --no-sync python -m pytest -q tests/test_asta_textarea_rows.py` 실행 결과 `2 failed`. 실제 원인은 기존 SQL `rows=18`, notes `rows=4`와 두 ID 전용 rows-height override 부재였다.
- GREEN/관련: rows/label/CSS와 기존 UI/cache 계약 `31 passed in 0.05s`; 최종 관련 묶음도 통과했다.
- `node --check static/js/extensions/tuning_assistant.js` 통과.
- `git diff --check` 통과.
- 전체 회귀: `350 passed, 10 failed in 0.95s`. 이전 baseline의 기존 실패 10건이 동일하며 신규 실패는 0건이다.
- 실행 서비스 HTTP 확인은 localhost read 요청의 권한 승인이 거부되어 수행하지 못했다. 서비스 재시작은 요청대로 하지 않았으며 디스크의 index/cache version/rows 값은 정적 테스트로 확인했다.

### 완료 기준

- 정확한 textarea ID/label 연결과 `10/3` rows가 정적 DOM 계약으로 검증된다.
- 두 visible 입력만 rows 기반 초기 높이를 사용하고 긴 입력은 자체 vertical scroll로 접근된다.
- payload, validation, max length, hidden/debug 및 결과 영역에 변경이 없다.
- 관련/전체 회귀 신규 실패가 없고 JS syntax 및 diff check가 통과한다.

### 위험/롤백 및 작업 이력

- 실제 실행 서비스의 HTTP 200과 제공된 자산 byte는 권한 경계 때문에 이번 작업에서 확인하지 못했다. static mount가 요청마다 파일을 읽는 기존 구조라 재시작은 하지 않았다.
- 롤백은 두 textarea의 rows를 기존 `18/4`로 되돌리고 ID-scoped CSS와 cache version 변경을 제거하는 것이다. DB/ORDS/서비스 롤백은 없다.
- 2026-07-05: 기존 dirty tree를 보존하고 RED 2건을 확인한 뒤 최소 마크업/CSS 변경으로 GREEN, 전체 `350 passed, 기존 10 failed`를 확인했다.

## 별도 UI 조정 [완료] — 결과 탭 sticky 및 선택 controls row

### 목표

결과서의 5개 탭을 실제 결과 scroll container 상단에 고정하고, AI Profile/Workload/샘플 SQL select를 데스크톱 한 줄 3열로 배치하되 기존 DOM ID·option·listener·payload와 반응형 안전성을 유지한다.

### 변경 파일 및 구현 방식

- `static/js/extensions/tuning_assistant.js`
  - `.tuning-report-tablist`에 `position:sticky`, `top:0`, `z-index:20`, 불투명 흰 배경, 하단 border와 shadow를 적용했다.
  - sticky element는 `#asta-report-scroll.tuning-report-scroll`의 direct child다. 실제 containing block인 `.tuning-report-scroll`은 `overflow:auto`이며 transform/contain이 없어 sticky를 깨지 않는다.
  - 모바일의 기존 `.tuning-report-tablist { overflow-x:auto; flex-wrap:nowrap; }`를 유지하고 position을 override하지 않아 sticky와 horizontal scroll이 함께 유지된다.
  - 세 select label을 하나의 `.tuning-controls-row` direct child로 묶었다. desktop은 `minmax(220px, .9fr) minmax(260px, 1fr) minmax(320px, 1.35fr)`, 1100px 이하는 2열, 720px 이하는 1열이다.
  - 세 select의 ID, option/default, 변수 조회, event listener와 payload 코드는 변경하지 않았다. notes/SQL textarea는 wrapper 밖 full-width이며 기존 rows `3/10`을 유지한다.
- `static/index.html`: assistant cache version을 `20260705_sticky_controls1`로 갱신했다.
- `tests/test_asta_sticky_tabs_controls_row.py`: sticky containing block/CSS, mobile 유지, 세 select direct semantic child, notes/SQL 외부 배치, desktop/tablet/mobile grid를 검증한다.
- `tests/test_asta_runtime_deployment_contract.py`: 새 cache version 계약을 갱신했다.

### RED/GREEN 및 검증

- RED: 신규 테스트 `3 failed`. 실패 원인은 sticky 속성 부재, `.tuning-controls-row` DOM 부재, 3열/반응형 CSS 부재로 모두 예상과 일치했다.
- GREEN: 신규 behavior `3 passed`.
- 관련 회귀: 신규 계약, 5-tab DOM click/keyboard/ARIA/Gate, textarea rows 10/3, 기존 UI/static/cache를 합쳐 `43 passed in 0.09s`; Node DOM test도 `PASS`다.
- JS syntax: `asta_report_tabs.js`, `tuning_assistant.js` 모두 `node --check` 통과.
- 전체 회귀: `353 passed, 10 failed in 0.94s`. 직전 `350 passed, 10 failed`에 신규 3건이 추가됐고 기존 실패 10건 동일, 신규 실패 0건이다.
- `git diff --check` 통과.
- 실행 중 서비스에서 `GET /`와 cache-busted `tuning_assistant.js?v=20260705_sticky_controls1`이 모두 HTTP 200을 반환했고, 제공된 자산에서 sticky 속성, 3열 controls row, textarea rows 10/3을 확인했다. 서비스 재시작은 수행하지 않았다.

### 완료 기준

- 결과 scroll 중 tablist가 불투명 sticky header로 유지되고 모바일 horizontal scroll 및 접근성 동작을 보존한다.
- 세 select가 동일 wrapper의 semantic direct child이며 desktop 3열, tablet 2열, mobile 1열로 page horizontal overflow 없이 전환된다.
- notes/SQL textarea, select ID/options/default/listener/payload 및 기존 Gate/키보드 동작을 변경하지 않는다.
- 관련/전체 회귀 신규 실패 0, JS syntax와 diff check를 통과한다.

### 위험/롤백 및 작업 이력

- 코드/DOM/CSS 검증과 실행 서비스의 HTTP 제공 검증을 완료했다. `GET /` 및 cache-busted assistant asset은 HTTP 200이었고, 제공된 자산에서 sticky/controls row/rows 10·3 계약을 확인했다.
- 롤백은 `.tuning-report-tablist` sticky 시각 속성, `.tuning-controls-row` wrapper/grid와 responsive rules를 제거하고 cache version을 직전 값으로 되돌리는 것이다. DB/ORDS/서비스 롤백은 없다.
- 2026-07-05: RED 3건 확인 → sticky/3-column 최소 구현 → 관련 43건, 전체 `353 passed, 기존 10 failed` 및 diff check를 완료했다. DB/ORDS/서비스/Git 변경은 수행하지 않았다.

## 샘플 SQL 14개 재설계 [완료] — Source 실측 및 UI 15개

- 1번 `asta-awr-01 / SESL0640.selectList`는 26,321 bytes, SHA-256 `843c516404ddfdc3560010155ed2a5f4c1df435c97b6ff9e9ac3a51b0fafbe16`으로 id/label/SQL byte가 불변이다. UI는 정확히 `asta-awr-01`~`asta-awr-15` 총 15개다.
- allowlist 11개는 `DSNT.TGP_STYDE_L`, `DSNT.TGP_STYLE_M`, `DSNT.TSE_DIV_L`, `DSNT.TSE_INOUT_S`, `DSNT.TSE_ISSU_D`, `DSNT.TSE_ORDER_S`, `DSNT.TSE_SALE_DAY_S`, `DSNT.TSE_SALE_MON_S`, `DSNT.TSE_SHOP_M`, `DSNT.VIF_WHOLESALE_S`, `DSNT.V_STYGRP_D`다.
- Hermes가 사용자 요청에 따른 read-only SELECT 검증을 승인된 ADB→DB Link→Source 경로로 순차 실행해 `reports/asta_sample_sqls_under_60s/verification.json`을 생성했다. DB/ORDS package, schema, allowlist 및 운영 설정은 변경하지 않았다.

| ID | label | pattern | wall elapsed(초) | fetched rows |
|---|---|---|---:|---:|
| 02 | 상관 EXISTS 반복 | `CORRELATED_EXISTS_COUNT` | 2.144583 | 82 |
| 03 | 상관 NOT EXISTS 반복 | `CORRELATED_NOT_EXISTS` | 1.446327 | 80 |
| 04 | 스칼라 MIN 중복 조회 | `SCALAR_MIN_REPEATED` | 1.563683 | 80 |
| 05 | 중복 CTE 이중 스캔 | `DUPLICATE_CTE_SCAN` | 3.234152 | 200 |
| 06 | 함수 적용 조건 | `FUNCTION_PREDICATE` | 1.128622 | 200 |
| 07 | DISTINCT와 GROUP BY 중복 | `REDUNDANT_DISTINCT_GROUP` | 1.166045 | 200 |
| 08 | UNION 중복 제거 | `UNION_DUPLICATE_ELIMINATION` | 1.335038 | 200 |
| 09 | 복합 IN 재조회 | `COMPOSITE_IN_RESCAN` | 17.532135 | 80 |
| 10 | 일판매 중복 스캔 | `REPEATED_FACT_SCALAR` | 1.115838 | 40 |
| 11 | 상세행 스칼라 SUM | `CORRELATED_SCALAR_SUM` | 1.086405 | 60 |
| 12 | 인라인 집계 중복 | `DUPLICATE_INLINE_AGGREGATE` | 1.334617 | 200 |
| 13 | EXISTS와 NOT EXISTS 연쇄 | `EXISTS_NOT_EXISTS_CHAIN` | 1.894681 | 45 |
| 14 | 월판매 GROUP BY 반복 | `REPEATED_GROUP_BY_CTE` | 1.734214 | 200 |
| 15 | 함수 조인과 후행 필터 | `FUNCTION_JOIN_ORDER` | 12.928623 | 38 |

- artifact 14개와 현재 UI 02~15를 ID, label, pattern, SQL SHA-256으로 독립 대조해 `14/14` 일치를 확인했다. 모두 `COMPLETED`, `timeout=false`, `session_usable_after=true`, `outside_allowlist=[]`, 60초 미만이며 최대 wall elapsed는 09번의 `17.532135초`다.
- TDD RED는 artifact 전 `4 failed, 1 passed`; GREEN은 skip을 모두 제거한 뒤 `5 passed`다. artifact test는 이제 현재 UI fingerprint까지 대조하므로 stale artifact를 허용하지 않는다.
- 관련 UI/샘플 회귀는 `25 passed`, Node DOM `PASS`, 두 JS `node --check` 통과다. 전체 회귀는 `359 passed, 9 failed`; 기존 baseline 10 failures 대비 신규 실패 0건이며 기존 실패가 1건 감소했다. `git diff --check`도 통과했다.
- cache version은 정확히 `20260705_samples15_under60_1`이다. 재시작 없이 실행 중 PID 759185 서비스 로그에서 `GET /`와 해당 cache-busted JS가 각각 HTTP 200임을 확인했고, 제공 대상 JS에서 총 15개, ID 01~15, 1번 SHA-256 불변 계약을 확인했다.
- SQL formatting, selection event, payload, sticky/3열 controls, textarea rows 10/3 및 1번 SQL은 변경하지 않았다.
- 롤백은 index cache version과 UI 02~15 배열/관련 계약을 직전 상태로 파일 단위 복원하고 artifact를 보존 또는 제거하는 것이다. Source 실행은 SELECT 검증뿐이므로 DB/ORDS package 롤백이나 서비스 재시작은 필요 없다. git commit/push는 수행하지 않았다.
## Oracle SQL Tuning Advisor Scheduler job 누적 방지 [완료] — 2026-07-05

- 라이선스 보유 확인 후 Source `ASTA_SOURCE_PKG`의 Advisor Scheduler job 정리를 strict TDD로 보강했다. RED는 명시적 `DROP_JOB` 및 성공·실패·timeout·예외 cleanup 계약 부재였고, GREEN 집중 테스트는 `4 passed`다.
- `cleanup_advisor_scheduler_job`은 이번 호출이 만든 정확한 job 이름만 처리한다. RUNNING이면 `STOP_JOB`/force drop 없이 `SKIPPED_RUNNING`, 비활성이면 `DBMS_SCHEDULER.DROP_JOB(..., force=>FALSE)`, 이미 없으면 `ALREADY_REMOVED`를 반환한다. 검사·삭제 오류는 기존 Advisor/ASTA 결과를 덮지 않고 additive `cleanup_status/detail`로 남긴다.
- 변경 전 Source package를 `/opt/select-ai-test/reports/asta_advisor_job_cleanup/20260705T133920Z/source_asta_source_pkg_before.sql`에 백업하고 `ASTA_SOURCE_PKG` 하나만 SQLcl 저장 연결 `DSNT`로 제한 배포했다. spec/body 모두 `VALID`, `USER_ERRORS=0`이다.
- ADB→DB Link→Source 실제 Advisor cleanup smoke를 연속 2회 수행했다. 두 번 모두 전체/Advisor `COMPLETED`, cleanup `DROPPED`, 실행 전후 `ASTA_ADV_%` 목록 동일, SQLTUNE task 목록 동일(0건)이었다.
- 기존 비활성 성공 job 3개는 요청 범위대로 삭제하지 않았다. 신규 smoke job은 남지 않았고 기존 3개는 모두 `DISABLED`, run_count=1, failure_count=0이다.
- 전체 회귀는 `363 passed, 기존 9 failed`로 신규 실패 0건이며 `git diff --check`를 통과했다. ADB/ORDS/UI/서비스/Git commit·push는 변경하지 않았다.
- 롤백은 위 backup SQL로 Source `ASTA_SOURCE_PKG` spec/body를 복원한 뒤 VALID/zero USER_ERRORS와 Advisor smoke를 재확인하는 것이다.

## ASTA UI Oracle SQL Tuning Advisor 기본 활성화 [완료] — 2026-07-05

- 라이선스 확인, Source Scheduler cleanup 배포, 실환경 Advisor smoke 2회 `COMPLETED / cleanup_status=DROPPED / 신규 job·task 잔여 0`을 선행 조건으로 UI analyze payload의 Advisor를 기본 활성화했다.
- `static/js/extensions/tuning_assistant.js`의 실제 POST payload에서 top-level `run_advisor/use_sqltune`과 `options.run_advisor/options.use_sqltune` 네 값만 `true`로 변경했다. timeout, fetch rows, SQLTune 제한시간, 샘플 SQL, formatting, event, polling 및 다른 UI 동작은 변경하지 않았다.
- strict TDD RED는 top-level true 계약에서 `1 failed`; 구현 후 샘플·runtime cache 계약을 포함한 focused GREEN은 `40 passed`, `node --check static/js/extensions/tuning_assistant.js` 통과다.
- 전체 회귀는 `364 passed, 9 failed in 1.14s`; 직전 baseline 9건과 동일하여 신규 실패 0건이다. `git diff --check`도 통과했다.
- 브라우저의 기존 false 자산 재사용을 막기 위해 cache version만 `20260705_advisor_ui1`로 갱신했다. 서비스 재시작, DB/ORDS 변경, 기존 Scheduler job 삭제, commit/push는 수행하지 않았다.
- 실행 서비스 검증 명령은 `curl -fsS -o /tmp/asta-advisor-index.html -w '%{http_code}\n' http://127.0.0.1:8000/` 및 `curl -fsS -o /tmp/asta-advisor-ui.js -w '%{http_code}\n' 'http://127.0.0.1:8000/static/js/extensions/tuning_assistant.js?v=20260705_advisor_ui1'`이다. 이어 `rg -n 'run_advisor: true|use_sqltune: true' /tmp/asta-advisor-ui.js`로 네 제공 값을 확인한다.
- 롤백은 네 payload 값을 `false`로 복원하고 index/runtime cache 계약을 직전 `20260705_samples15_under60_1`로 되돌리는 것이다. DB/ORDS/서비스 롤백은 없다.

## ASTA 결과서 카드 헤더 통합 [완료] — 2026-07-05

- 기존 결과 제목/Run ID, 완료 상태·elapsed, 다운로드/초기화, 위·아래 이동 버튼과 탭을 중복 생성하지 않고 하나의 `.tuning-report-header` 안에서 시각적으로 그룹화했다. 기존 ID와 listener를 가진 상태·버튼 노드를 결과 렌더링 시 이동하고 초기화 시 상단 hero의 원래 순서로 복원한다.
- 탭 label은 정확히 `요약`, `튜닝 전`, `튜닝 후`, `상세 분석`, `객체 정보`다. 내부 tab id, heading classification, ARIA, click, Arrow/Home/End, panel scroll 초기화와 Gate 위치는 보존했다.
- browser-tab 형태와 hardcoded active blue/강한 shadow를 제거하고 실제 Redwood 토큰 `--surface`, `--surface-alt`, `--border`, `--primary`, `--primary-light`, `--text`, `--text-muted`, `--radius-lg` 기반 compact segmented control로 변경했다. 결과 카드/header/body padding과 border/radius를 맞췄고 nested SQL/XPLAN dark code block은 유지했다.
- 700px 이하에서 header/action을 자연스럽게 줄바꿈하고 segmented tab은 `nowrap + overflow-x:auto`를 유지한다. raw Markdown, 원문 다운로드, Overview 구조, 표, SQL/XPLAN, Gate 및 metric parsing은 변경하지 않았다.
- strict RED `5 failed, 4 passed`; 첫 GREEN에서 모바일 header 명시 계약 한 건이 남아 `8 passed, 1 failed`, 보완 후 관련 `41 passed`, Node DOM `PASS`, 두 JS `node --check` 통과다.
- 전체 회귀 `367 passed, 9 failed in 1.13s`; 직전 baseline `364 passed, 기존 9 failed` 대비 신규 실패 0이며 새 계약 3건이 통과했다. `git diff --check`도 통과했다.
- cache-buster는 report tabs와 assistant 모두 `20260705_report_header1`이다. 실제 검증 URL은 `/`, `/static/js/extensions/asta_report_tabs.js?v=20260705_report_header1`, `/static/js/extensions/tuning_assistant.js?v=20260705_report_header1`이다.
- 롤백은 header host/기존 노드 이동·복원과 새 report CSS를 제거하고 기존 탭 label/CSS 및 cache version `asta_report_tabs.js?v=20260705_report_tabs1`, `tuning_assistant.js?v=20260705_advisor_ui1`을 복원한다. DB/ORDS/서비스 재시작/commit/push는 수행하지 않았다.

## Advisor 요약·Gate UI 제거·근거 기반 DBA 검토 [코드 준비 완료] — 2026-07-05

- Advisor heading `## Oracle SQL Tuning Advisor 요약`과 `### Oracle SQL Tuning Advisor 요약`을 모두 기본 `요약` 탭으로 분류했다. 같은 level의 동일 heading 중복은 기존 `AMBIGUOUS_REPORT_SECTION` fail-closed를 유지하며, raw Markdown/다운로드/안전 renderer는 변경하지 않았다.
- 표시 전용 Gate UI를 제거했다. `asta_report_tabs.js`의 `.tuning-gate-host`, assistant의 `buildAstaGateViewModel`/`renderAstaGateSummary`/호출/`.tuning-gate-*` CSS와 `검증 Gate 상태` 문구는 없다. 백엔드 workflow gate, comparison/equivalence/verdict artifact와 결과서 Markdown 근거는 유지한다.
- `ASTA_REPORT_PKG.append_dba_review`는 현재 실행의 Advisor requested/status/report 8,000자 안전 발췌, SQL PROFILE/INDEX/STATISTICS/PLAN BASELINE 권고 유형, comparison verdict/equivalence 및 실제 elapsed/buffer/disk/row 수치, object_info의 table/index/stale/last_analyzed 개수를 근거로 승인·영향 범위·테스트·rollback 항목을 생성한다. FAILED/TIMEOUT/SKIPPED 재시도 조건과 권고 없음도 사실대로 표시한다. raw Advisor report dump와 값 발명은 하지 않으며 모든 물리 변경은 자동 적용하지 않는다.
- `ASTA_LLM_PKG` source prompt도 generic boilerplate 금지와 evidence별 승인/영향/rollback 지시를 보강했다. 이번 배포 허용 범위는 `ASTA_REPORT_PKG` 하나뿐이므로 `ASTA_LLM_PKG`는 source-only이며 별도 승인 전 배포하지 않는다.
- Oracle 19c 재검토에서 `JSON_TABLE ... NESTED PATH`의 null child 행을 `COUNT(*)`가 인덱스로 오인할 수 있는 위험을 RED 1건으로 재현하고 `COUNT(index_name)`으로 보완했다. BOOLEAN은 private PL/SQL 상태로만 사용하고 `INSTR(...) > 0`을 직접 대입한다. `JSON_VALUE ... RETURNING CLOB`, 실제 producer path와 private routine ordering도 정적 계약으로 고정했다.
- 수직 TDD: Advisor 탭 RED 1건 → DOM GREEN, Gate 제거 RED 3건 → 12 GREEN, DBA helper/prompt RED 2건 → 2 GREEN, Oracle 19c nested count RED 1건 → 3 GREEN, cache RED 1건 → GREEN. 최종 focused `21 passed`, Node DOM `PASS`, 두 JS `node --check` 통과다.
- 전체 회귀는 `370 passed, 9 failed in 1.16s`; 직전 `367 passed, 기존 9 failed` 대비 신규 테스트 3건이 추가됐고 실패 목록은 동일해 신규 실패 0건이다. cache는 `20260705_advisor_summary_dba1`이다.
- 서비스 PID 759185/port 8000은 재시작하지 않았다. Codex sandbox에서 localhost 연결이 거부되어 HTTP 200은 미실측이며 Hermes가 `/`, 두 cache-busted asset을 확인해야 한다.
- DB/ORDS 배포, 서비스 재시작, commit/push는 수행하지 않았다. 롤백은 Advisor SECTION_RULES, Gate 표시 제거, `append_dba_review` 호출, LLM prompt 한 줄과 cache를 직전 `20260705_report_header1` 상태로 파일 단위 복원하는 것이다.
## 2026-07-06 — aa7 결과서 모순 수정 및 고객 SQL 1+3 재검증

- `OADT2-ASTA-aa7ba3f1891344d697803b64f363faf9`의 후보와 After XPLAN이 저장돼 있는데도 BLOCKED report builder가 이를 숨기던 원인을 수정했다. 후보 존재와 최종 채택을 분리하며, BLOCKED이면 `검증 실행된 후보 SQL — 채택 보류`로 실제 evidence를 표시한다.
- Source/ADB runtime 코드는 hardcoded intent/measurement 차단을 제거하고 warm-up 1회 + 측정 3회, Before/After bind 비적용, XPLAN Starts/ANTI evidence를 사용한다. Python gate는 `BIND_NOT_APPLICABLE`을 검증된 비적용으로 처리한다.
- strict TDD는 최초 신규 4 RED를 재현한 뒤 GREEN으로 전환했고, 추가 fail-closed 2 RED(반복별 metric reset, Before/After bind evidence)도 GREEN으로 전환했다. 최종 focused 51 passed, 전체 377 passed/기존 9 failed로 신규 실패는 0이다.
- 실제 Source bridge 재검증은 Before/After 각 warm-up 1 + measure 3으로 수행했다. 8회 모두 262행 ordered digest/metadata 동일, producer Starts 845→1, bind placeholder/metadata 0, 중앙 elapsed 121.197587초→1.437259초, buffers 9,159,767→1,076,461, noise 0.990%/3.193%로 최종 IMPROVED다.
- ADB `ASTA_REPORT_PKG`, `ASTA_PKG`만 백업·배포해 PACKAGE/BODY VALID 및 USER_ERRORS=0을 확인했다. 새 Markdown/HTML과 localhost report API의 동일 내용/HTTP 200을 확인했다.
- Source package 배포와 Python 서비스 재시작은 현재 Codex 권한 경계에서 차단됐다. Source는 기존 VALID 상태지만 신규 marker가 미배포라 다음 실행 자동 판정에는 아직 반영되지 않는다. DB/ORDS metadata, allowlist, 운영 설정, commit/push는 변경하지 않았다.
- 상세 artifact와 rollback은 `reports/asta_aa7_result_fix/20260706T001500KST/`에 있다.
## 2026-07-06 — SQL Advisor 일반 실행 기본 OFF

- 장시간 실행을 피하기 위한 사용자 결정에 따라 ASTA UI 일반 실행 payload의 top-level/options `run_advisor`, `use_sqltune` 네 값을 모두 `false`로 변경했다. `sqltune_time_limit`과 Advisor PL/SQL/artifact/schema는 향후 명시적 opt-in을 위해 유지했다.
- FastAPI `_coerce_payload`와 ADB `ASTA_PKG`의 누락 필드 기본값은 이미 OFF임을 행동/정적 테스트로 고정했다. top-level, legacy `use_sqltune`, options 중 하나라도 명시적으로 true이면 future opt-in이 유지된다.
- 입력 카드에 비대화 없는 읽기 전용 상태 `SQL Advisor: OFF`를 추가하고 client progress도 `SQL Advisor 생략 (기본 OFF)`로 표시한다. 토글은 추가하지 않았다.
- 결과서 Advisor summary/DBA review는 유지한다. OFF Source evidence는 `advisor_requested=false`, `advisor.status=SKIPPED`로 생성되고 결과서가 해당 값을 그대로 표시하는 계약을 추가했다.
- strict TDD RED는 UI payload/상태/cache 3건이었다. GREEN focused `37 passed`, Node DOM PASS, JS syntax 2건 통과. 전체 `381 passed, 기존 9 failed`, 신규 실패 0, `git diff --check` 통과다.
- cache version은 `20260706_advisor_default_off1`. DB/ORDS deploy, 서비스 재시작, commit/push는 수행하지 않았다. localhost HTTP는 현재 Codex network namespace에서 `EPERM`으로 차단됐으며, cache-busted 검증 URL과 `tools/asta_deploy_adb.py --advisor-off-live-static <outdir>` 읽기 전용 검증 모드를 제공한다.
- 롤백은 UI 네 flag를 true, client 문구를 기존 Advisor 수행 문구로, cache를 `20260705_advisor_summary_dba1`로 복원하는 것이다. backend/PLSQL 삭제나 롤백은 없다.
