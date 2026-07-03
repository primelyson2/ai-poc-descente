# ASTA 결과 품질 Loop Agent 설계

## 목적

이 agent의 목적은 코드를 자동으로 고치는 것이 아니라, LLM에 전달할 evidence의 양과 순서를 반복 실험해
ASTA가 더 안전하고 빠른 후보 SQL을 만드는 조건을 찾는 것이다. 매시간 실험 결과를 누적하고
`reports/asta_quality_agent/latest.md`에 승인용 제안서를, `latest.json`에 같은 판정의 기계 판독본을 만든다.
프로그램 또는 DB 변경은 하지 않는다.

첫 번째 샘플 `asta-awr-01 / SESL0640.selectList`는 고객 제공 SQL이므로 전체 평균과 분리된 필수 gate다.
기본 정책은 최근 5회 안에서 동일 variant가 최소 3회 실행되고 3회 모두 다음 조건을 만족해야 통과한다.

- 후보 SQL이 원본과 구조적으로 다르다.
- 결과 동등성이 deterministic comparison으로 확인된다.
- BATCH 기준 elapsed time이 최소 5% 개선된다.
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
2. `scripts/asta-quality-agent.timer`가 매시간 oneshot service를 실행한다.
3. agent는 기존 A/B/C ADB 실험기를 호출하고 `history.jsonl`에 결과를 누적한다.
4. 담당자는 `latest.md`의 고객 gate, 단계별 표, 다음 조치를 검토한다.
5. 승인된 경우에만 별도 작업으로 `asta_llm_pkg.sql`, `asta_pkg.sql`, 테스트를 수정한다.
6. 코드 리뷰 후 ADB compile/ORDS 배포를 별도로 승인한다.

현재 A/B/C는 `SQL`, `SQL+metrics`, `compact full evidence` 비교다. 위의 E1~E5를 완전히 독립 실험하려면
다음 승인 변경에서 실험 runner와 `ASTA_LLM_PKG`가 evidence mask를 받도록 확장해야 한다.
그 전까지 agent 보고서는 현재 가능한 A/B/C 중 최저 통과 단계를 계산하고, 다음 단계 구현 필요성을 제안한다.

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
통과하면 커밋하고 `reports/asta_quality_agent/pending_deployment.json`을 만든다.

이 표식이 있는 동안 추가 자동 수정은 중단된다. 담당자가 변경을 검토·배포한 뒤 표식을 제거해야 다음 실험 결과에
대한 자동 수정이 가능하다. autopilot은 ADB package compile, ORDS 설치 또는 DB 배포를 실행하지 않는다.
