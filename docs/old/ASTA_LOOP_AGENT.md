# ASTA Loop Agent

> ASTA의 LLM evidence/prompt 품질을 매시간 실험하고 사람이 승인할 제안서만 만들려면
> `tools/asta_quality_agent.py`와 `docs/ASTA_QUALITY_AGENT.md`를 사용한다.
> 아래 도구의 `improve_command` 자동 코드 수정 기능은 정기 운영에 사용하지 않는다.

`tools/asta_loop_agent.py`는 ASTA의 검증 명령을 점수화하고, 실패 증거를 개선 명령에 전달한 뒤,
변경 전후를 다시 검증하는 로컬 오케스트레이터다.

## 안전 경계

- 기본적으로 깨끗한 Git 작업 트리에서만 시작한다.
- 필수 검증 실패, 점수 미개선, 허용 경로 밖 변경은 자동 거부하고 해당 회차 변경을 복구한다.
- 운영 DB DDL, 배포, credential 변경, Git commit/push는 수행하지 않는다.
- 실제 DB 검증은 선택 항목이다. 해당 명령을 활성화했을 때만 기존 ASTA 실행기를 호출한다.
- 점수는 테스트 통과 여부만 뜻한다. SQL 의미 동등성은 ASTA의 deterministic comparison 계약이 계속 최종 기준이다.

## 시작

```bash
cp asta-loop.yaml.example asta-loop.yaml
uv run python tools/asta_loop_agent.py --config asta-loop.yaml --evaluate-only
```

자동 개선을 켜려면 `asta-loop.yaml`의 `improve_command`를 활성화한다. 명령에는 다음 치환값을 쓸 수 있다.

- `{brief}`: 현재 실패와 정책을 담은 개선 지시서
- `{iteration_dir}`: 해당 회차 로그/patch 경로
- `{root}`: 저장소 루트

```bash
uv run python tools/asta_loop_agent.py --config asta-loop.yaml --max-iterations 3
```

각 실행은 `reports/asta_loop/<UTC timestamp>/summary.json`에 baseline, 회차별 변경 경로,
채택/거부 사유, 최종 점수를 남긴다. 실서비스 배포는 이 loop 밖의 별도 승인 단계로 유지한다.

## 권장 단계적 도입

1. 처음에는 Python 계약 테스트만 `required`로 두고 `--evaluate-only`로 기준선을 만든다.
2. 테스트 DB가 안정적일 때 10-SQL live 검증을 추가한다.
3. 반복 실행의 분산을 확인한 뒤 live 검증의 통과 기준과 가중치를 고정한다.
4. 마지막으로 개선 명령을 연결하고 최대 회차를 1부터 늘린다.
