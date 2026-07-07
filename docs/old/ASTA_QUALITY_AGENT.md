# ASTA 결과 품질 Loop Agent 설계

## 목적

이 agent의 목적은 코드를 자동으로 고치는 것이 아니라, LLM에 전달할 evidence의 양과 순서를 반복 실험해
ASTA가 더 안전하고 빠른 후보 SQL을 만드는 조건을 찾는 것이다. 매시간 실험 결과를 누적하고
`reports/asta_quality_agent/latest.md`에 승인용 제안서를, `latest.json`에 같은 판정의 기계 판독본을 만든다.
프로그램 또는 DB 변경은 하지 않는다.

첫 번째 샘플 `asta-awr-01 / SESL0640.selectList`는 고객 제공 OLTP SQL이므로 전체 평균과 분리된 필수 gate다.
기본 정책은 최근 5회 안에서 동일 variant가 최소 3회 실행되고 3회 모두 다음 조건을 만족해야 통과한다.

- 후보 SQL이 원본과 구조적으로 다르다.
- 결과 동등성이 deterministic comparison으로 확인된다.
- OLTP 1차 지표인 Buffer Gets가 최소 5% 개선되고, elapsed가 3초 이내이며 기존보다 300ms를 초과해 악화되지 않는다.
- 실패, timeout, 후보 없음, 비동등, 성능 미개선은 모두 실패로 계산한다.

이 gate가 실패하면 다른 9개 SQL의 평균이 좋아도 `DEPLOY_REVIEW_READY`가 될 수 없다.

## 권장 evidence escalation

| 단계 | LLM에 전달 | 목적 | 다음 단계 조건 |
|---|---|---|---|
| E0 | SQL + workload 목표 | 가장 싼 구조 재작성 기준선 | 후보 없음 또는 미개선 |
| E1 | SQL + focused XPLAN | 실제 병목 operation을 진단 | 후보 없음/미개선 |
| E2 | E1 + buffer/elapsed/disk/rows | 최적화 목표를 실측 수치로 제한 | 동등하지만 미개선 |
| E3 | E2 + object/column/index metadata | cardinality·선택도·사용 가능 index 이해 | 비동등 또는 잘못된 join/aggregate |
| E4 | E3 + Advisor 핵심 요약 | Oracle 진단을 구조 재작성에 보조 사용 | 여전히 미개선 |
| E5 | E4 + 검증된 IMPROVED Vector 사례 | 유사 성공 패턴 재사용 | 최후 단계 |

E1부터는 한 번에 긴 SQL JSON을 요구하지 않는다.

1. 진단 단계는 `rewrite_strategy`, `target_operations`, `semantic_risks`만 JSON으로 받는다.
2. 생성 단계는 실행 가능한 SQL CLOB만 받는다.
3. SQL guard를 통과한 후보만 Source DB에서 실행한다.
4. Before/After는 여러 번 수행하고 workload별 primary metric으로 판정한다.
5. 실패 유형에 따라 evidence를 한 단계씩 추가한다.

처음부터 모든 정보를 주는 C 방식은 prompt 비용과 잡음을 늘리고 어떤 정보가 효과가 있었는지 알 수 없으므로
최소 통과 단계를 기본값으로 사용한다. 다만 고객 SQL은 비용보다 재현 가능한 개선이 우선이다.

## 매시간 계산하는 값

각 `(SQL, evidence variant, cycle)`에 대해 다음 값을 보존한다.

- 후보 생성 여부와 오류 유형
- 결과 동등성 여부
- Before/After buffer gets, elapsed time, disk reads
- workload별 primary metric 감소율
- prompt chars와 LLM 호출 횟수
- variant 실행 순서(cache warming 편향 확인용)
- 고객 SQL 성공 여부

최근 N회 window에서 다음을 계산한다.

- 고객 SQL 성공 횟수, 성공률, primary metric 중앙 개선률
- 전체 SQL 성공률과 동등성률
- variant별 prompt 크기 중앙값
- 고객 gate를 통과한 최소 evidence 단계

평균 대신 중앙값을 사용하는 이유는 DB cache, 동시 부하, LLM 편차로 생기는 한 번의 극단값을 줄이기 위해서다.
또한 매시간 A/B/C 시작 순서를 회전해 특정 variant가 항상 warm cache에서 실행되는 편향을 줄인다.
향후 Before/After 반복 횟수가 충분해지면 p50뿐 아니라 p95 및 bootstrap confidence interval도 추가한다.

## 파일과 승인 흐름

1. `asta-quality-agent.yaml.example`을 `asta-quality-agent.yaml`로 복사하고 profile과 SQL 목록을 확인한다.
2. `scripts/asta-quality-agent.timer`가 이전 회차 종료 한 시간 뒤 oneshot service를 실행한다.
3. agent는 기존 A/B/C ADB 실험기를 호출하고 `history.jsonl`에 결과를 누적한다.
4. 담당자는 `latest.md`의 고객 gate, 단계별 표, 다음 조치를 검토한다.
5. 자동 개선기는 `asta_llm_pkg.sql`, `asta_pkg.sql`, 테스트 중 작은 변경 한 건만 수행한다.
6. 회귀 테스트를 통과한 패키지 변경은 Source DB(해당 시)와 ADB에 자동 배포하고 ADB package smoke를 실행한다.

현재 A/B/C는 `SQL`, `SQL+metrics`, `compact full evidence` 비교다. 위의 E1~E5를 완전히 독립 실험하려면
다음 승인 변경에서 실험 runner와 `ASTA_LLM_PKG`가 evidence mask를 받도록 확장해야 한다.
그 전까지 agent 보고서는 현재 가능한 A/B/C 중 최저 통과 단계를 계산하고, 다음 단계 구현 필요성을 제안한다.

현재 Source evidence의 `row_count`와 `last_output_rows` 일치만으로는 실제 결과값 동등성을 증명하지 못한다.
실험기는 이를 `SHAPE_ONLY`로 기록하고, Source가 `result_digest`/`result_hash`/`result_checksum` 중 하나를
제공해 반복 실행의 digest가 일치할 때만 `semantic_equivalent=true`로 판정한다. 따라서 Source package에
결과 digest를 추가하기 전에는 품질 gate가 안전하게 닫힌 상태가 정상이다.

고객 SQL 정밀 실험은 기본 자동 회차와 분리해 다음 옵션으로 실행한다. 이 명령은 ADB LLM 호출과 Source DB
실행을 발생시키므로 실환경 승인 후에만 사용한다.

```bash
.venv/bin/python tools/run_asta_prompt_abc_adb.py \
  --samples asta-awr-01 \
  --modes A,B,C \
  --strategies AUTO,DOMINANT_NOT_EXISTS,CORRELATED_MIN,REPEATED_FACT_SCAN \
  --benchmark-runs 3 \
  --ora-retries 2
```

`--benchmark-runs`는 Before/After 독립 실행의 중앙값과 변동폭을 계산한다. `--ora-retries`는 후보의 Oracle
검증/실행 오류 원문과 실패 SQL을 모델에 다시 제공한다. 전략별 후보를 분리해 생성하므로 한 가지 프롬프트
패턴에 수렴하는 문제도 줄인다.

이 고객 SQL의 122초 측정은 정상 기준선이 아니라 실행계획 회귀다. `STYLE` CTE의 correlated `NOT EXISTS`
아래 `VIF_WHOLESALE_S`가 845회 재시작되고, 그 안의 `TGP_STYDE_L_PK` fast full scan이 누적 약 9.4억 행과
809만 buffer gets를 처리하면서 약 121초를 소비했다. 반면 나머지 본문은 약 1.29초이므로 첫 구조 후보는
도매 제외 키를 한 번만 계산하는 DISTINCT helper/anti-join이어야 한다. 과거 103초 후보는 Buffer Gets가
줄었더라도 현재 3초 latency guard를 충족하지 못하므로 실패다.

## 반복 측정과 실행예산 계약

`tools/asta_execution_budget.py`는 DB를 직접 실행하지 않는 결정론적 schedule·예산·판정 계층이다. 판정 순서는
Optimizer intent `VERIFIED` → timeout/runaway 및 예산 → 측정 완전성/noise → result digest → 성능 및 OLTP
latency guard다. 앞 단계가 실패하면 뒤 단계의 성공을 추측하지 않는다.

- warm-up은 cache 영향을 관찰하기 위한 실행으로만 기록하고 중앙값과 noise 계산에서 제외한다.
- 측정 round마다 후보 순서를 회전하며 Before는 각 round의 기준점으로 둔다.
- 기본값은 warm-up 1회, 측정 3회, 후보 최대 4개, 전체 20회/10분, 후보별 4회/15초다.
- OLTP per-run timeout은 180초이며 중앙 elapsed 3초 이하, 원본 대비 증가 300ms 이하를 별도 적용한다.
- 실행 횟수·시간 초과, 측정 누락, noise 초과, timeout, runaway는 각각 구조화 reason code로 차단한다.
- timeout/runaway 결과는 실제 실행 adapter에 cancel과 잔류 DB session 확인을 요구하며 해당 후보를 terminal 처리한다.

설정은 `asta-quality-agent.yaml.example`의 `execution_budget.defaults`와 workload override에서 조정한다. 신규 계층은
아직 실서비스 runtime이나 DB/ORDS에 배포되지 않았으므로 현재는 fixture 기반 품질 계약이다.

## 전체 결과 동등성 계약

단계 6부터 result digest는 `FULL_RESULT` scope만 semantic proof로 인정한다. 기존
`BOUNDED_ORDERED_FIRST_N`과 row count/shape 일치는 참고 evidence이며 후보를 성능 측정으로 넘기지 않는다.

- 최종 top-level `ORDER BY`가 있으면 `ORDERED_ROWS`로 행 순서까지 비교한다.
- 최종 ORDER BY가 없으면 `UNORDERED_MULTISET`으로 비교하며 같은 행의 중복 횟수를 보존한다.
- 컬럼 순서·이름·datatype·precision·scale·길이·charset metadata와 NULL/type-tagged 값을 digest에 포함한다.
- 전체 행 수, digest 처리 행 수, chunk 완료, truncation, mode와 algorithm이 모두 완전해야 한다.
- 기본 equivalence budget은 100만 행/256MiB다. 초과 시 first-N으로 낮추지 않고 차단한다.
- 판정 순서는 Optimizer intent VERIFIED → full-result equivalence VERIFIED → 반복 측정/실행예산 → 성능이다.

현재 배포된 Source evidence는 bounded first-100 형식이므로 기존 고객 후보도 full-result 재수집 전에는
`FULL_RESULT_EVIDENCE_REQUIRED`다. Python gate와 품질 runner는 로컬에 구현했지만 Source/ADB package 및 ORDS에는
이번 단계에서 배포하지 않았다.

## Bind와 plan 안정성 계약

대표 bind는 원문 값 없이 이름, 위치, Oracle datatype, NULL 여부, 선택도 bucket과 hash fingerprint만 기록한다.
기본 coverage는 `NULL`, `SELECTIVE`, `BROAD` 세 case이며 Before/After에 동일 fingerprint가 적용돼야 한다.

- 각 bind의 Before/After plan은 최소 2개 표본으로 shape와 target subtree Starts 안정성을 확인한다.
- plan hash가 같아도 shape 또는 Starts가 바뀌면 실패다.
- plan hash가 달라도 정규화 shape와 Starts가 같으면 hash 변화만으로 실패시키지 않는다.
- bucket별 expected plan family에 맞는 bind-sensitive/parameter-sensitive variation은 허용한다.
- 동일 bind에서 plan family가 뒤집히거나 예상 밖 family가 나오면 차단한다.
- 모든 bind의 intent와 full-result equivalence를 먼저 확인한 후 plan stability, 전체 bind 실행예산, 반복 성능 순서로 진행한다.
- 대표 bind 하나라도 3초/300ms latency, Buffer Gets, noise, digest 또는 intent를 실패하면 후보 전체를 거절한다.

현재 설정은 대표 bind 3개, 각 plan 표본 2개, 실패 허용 0개이며 raw bind 저장을 금지한다. 실제 Source의
child cursor/ACS/bind-aware evidence 수집은 아직 구현·배포하지 않았으므로 로컬 deterministic 품질 계약이다.

## 통합 상태머신과 Vector 학습 경계

통합 상태 순서는 `OPTIMIZER_INTENT → FULL_RESULT_EQUIVALENCE → BIND_PLAN_STABILITY →
EXECUTION_MEASUREMENT → FINAL_DECISION`이다. 앞 gate가 terminal이면 이후 성공 응답이나 stale poll이 상태를
바꾸지 못한다. 동일 attempt 재조회는 같은 snapshot을 반환하고 새 attempt는 명시적 restart 승인이 필요하다.

UI는 상태머신이 있으면 현재 단계, 차단 reason, evidence level 및 각 gate 결과를 한국어 카드로 표시한다.
`BLOCKED`, `REJECTED`, `FAILED`는 success toast를 만들지 않는다. SQL block, literal과 bind 값은 UI 표시·오류
상세·다운로드 copy에서 redaction하며 raw payload JSON을 fallback으로 출력하지 않는다.

Vector 학습 분류:

- `POSITIVE_VERIFIED`: 다섯 gate가 모두 VERIFIED/ACCEPTED이고 result scope가 `FULL_RESULT`인 경우만 해당한다.
- `REJECTED_OBSERVATION`: 후보 없음, ORA, bounded/불완전 evidence, 비동등, intent 미달, bind/plan 불안정, timeout과 성능 실패다.
- Positive 검색은 `learning_class=POSITIVE_VERIFIED`만 조회한다.
- 신규 저장은 raw source/tuned SQL을 NULL 처리하고 내부 report reference와 allowlist metrics/gate metadata만 저장한다.
- rejected record는 reason code와 안전한 관측 evidence만 별도 chunk로 보존한다.

로컬 Python/UI/ADB 소스 계약만 구현했으며 ADB package compile, ORDS와 서비스 배포는 수행하지 않았다.

## 수동 실행

실제 DB 실험까지 실행:

```bash
cp asta-quality-agent.yaml.example asta-quality-agent.yaml
.venv/bin/python tools/asta_quality_agent.py --config asta-quality-agent.yaml
```

이미 생성된 summary만 다시 계산:

```bash
.venv/bin/python tools/asta_quality_agent.py \
  --config asta-quality-agent.yaml \
  --summary reports/asta_prompt_abc_adb_latest/summary.json
```

systemd 파일은 템플릿만 제공한다. 복사, daemon-reload, timer enable은 운영 승인을 받은 뒤 수행한다.

## 자동 소스 개선 모드

`tools/asta_quality_autopilot.py`는 `latest.md`가 gate 미통과일 때 Codex에 보고서를 전달해 작은 소스 변경
한 건을 수행한다. 전체 pytest의 기존 실패 목록과 비교해 신규 실패가 생기면 해당 변경을 복구한다.
통과하면 변경된 Source/ADB 패키지를 자동 배포하고 Source DB 상태와 독립적인 ADB package smoke를 수행한 뒤 커밋한다.

Codex는 `--ask-for-approval never`와 `--sandbox workspace-write`로 실행한다. 따라서 실행 중 승인 입력을
기다리지 않으며, sandbox 밖 권한이 필요한 작업은 사용자에게 묻는 대신 실패로 처리한다.

배포 결과는 `reports/asta_quality_agent/last_deployment.json`과 회차별 `deploy_*.log`에 기록한다.
package smoke는 SQL guard, AI profile 목록, Source allowlist 호출을 확인한다. 실제 DB link를 포함한 end-to-end
workflow는 다음 품질 실험 회차가 검증한다. 배포 또는 smoke가 실패하면 소스 변경을 복구하고 기존 패키지를 다시 배포한다. 복구 배포 결과도
`restore_*.log`와 회차 결과에 남기며, 실패한 변경은 커밋하지 않는다.
