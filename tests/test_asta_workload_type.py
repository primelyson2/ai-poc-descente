"""OLTP/BATCH workload 선택의 UI→proxy→ADB 계약 회귀 테스트."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.routers.asta_proxy import _coerce_payload
from tools.asta_sample_sql_verifier import load_samples


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_proxy_canonicalizes_workload_and_ignores_client_goal():
    batch = _coerce_payload({"sql": "select 1 from dual", "tuning_context": {"workload_type": " batch ", "optimization_goal": "EVIL"}})
    assert batch["tuning_context"]["workload_type"] == "BATCH"
    assert batch["tuning_context"]["optimization_goal"] == "MINIMIZE_ELAPSED_TIME"
    invalid = _coerce_payload({"sql": "select 1 from dual", "tuning_context": {"workload_type": "DW", "optimization_goal": "MINIMIZE_ELAPSED_TIME"}})
    assert invalid["tuning_context"] == {"workload_type": "OLTP", "optimization_goal": "MINIMIZE_BUFFER_READS"}


def test_ui_exposes_and_propagates_workload_context_and_resets_oltp():
    ui = read("static/js/extensions/tuning_assistant.js")
    for token in ['id="asta-workload-type"', 'value="OLTP"', 'value="BATCH"',
                  "OLTP — Buffer Reads 최소화", "배치 — Elapsed Time 최소화",
                  'workloadSelect.value = "OLTP"', "optimizationGoalForWorkload"]:
        assert token in ui
    assert "채택 latency는 3초 이하, 기존 대비 증가는 300ms 이하" in ui
    assert ui.count("workload_type:") >= 2  # normal and hidden SQL-only payloads
    assert ui.count("optimization_goal:") >= 2
    samples = load_samples()
    contract = json.loads(read("tests/fixtures/asta_sample_01_contract.json"))
    artifact = json.loads(read("reports/asta_sample_sqls_under_60s/verification.json"))
    assert len(samples) == 20
    assert all(sample["workload"] == "BATCH" for sample in samples[15:])
    assert hashlib.sha256(samples[0]["sql"].encode("utf-8")).hexdigest() == contract["sql_sha256"]
    records = {item["sample_id"]: item for item in artifact["samples"]}
    assert set(records) == {
        f"asta-awr-{index:02d}" for index in range(2, 16)
    }
    for sample in samples[1:15]:
        assert hashlib.sha256(sample["sql"].encode("utf-8")).hexdigest() == records[sample["id"]]["sql_sha256"]


def test_sql_only_prompt_is_workload_specific_and_artifact_preserves_goal():
    llm = read("db/adb/asta_llm_pkg.sql")
    assert "p_workload_type IN VARCHAR2 DEFAULT 'OLTP'" in llm
    for token in ["logical buffer reads", "last_cr_buffer_gets per execution", "random table lookups",
                  "elapsed time / wall-clock duration", "temp-heavy work", "buffer gets is a supporting metric",
                  "Do not add hints or index DDL", '\"workload_type\"', '\"optimization_goal\"']:
        assert token in llm


def test_orchestration_normalizes_and_passes_workload_to_llm_and_comparison():
    main = read("db/adb/asta_pkg.sql")
    assert "FUNCTION normalize_workload_type" in main
    assert "'$.tuning_context.workload_type'" in main
    assert "p_workload_type => l_workload_type" in main
    assert "build_comparison_json(l_source_json, l_after_json, l_workload_type)" in main
    no_rewrite = main[main.index("No structural rewrite candidate"):]
    assert "json_str(l_workload_type)" in no_rewrite
    assert "'ELAPSED_TIME' ELSE 'BUFFER_READS'" in no_rewrite
    assert "'MINIMIZE_ELAPSED_TIME' ELSE 'MINIMIZE_BUFFER_READS'" in no_rewrite


def test_comparison_and_vector_metadata_are_workload_aware():
    main = read("db/adb/asta_pkg.sql")
    assert "p_workload_type IN VARCHAR2 DEFAULT 'OLTP'" in main
    assert "MINIMIZE_BUFFER_READS" in main and "MINIMIZE_ELAPSED_TIME" in main
    assert '"primary_metric":' in main and '"workload_type":' in main
    assert "INSUFFICIENT_EVIDENCE" in main
    assert "OLTP_BUFFER_READS_MEANINGFUL_IMPROVEMENT" in main
    assert "BATCH_ELAPSED_TIME_NOT_IMPROVED" in main


def test_report_displays_workload_and_primary_metric():
    report = read("db/adb/asta_report_pkg.sql")
    assert "실행 유형" in report
    assert "Primary metric" in report
    assert "$.workload_type" in report
    assert "$.primary_metric" in report


def test_oltp_large_buffer_reduction_accepts_imperceptible_elapsed_tradeoff():
    """실측 사례(0.635448s→0.917737s, gets 37237→4979)를 계약으로 고정한다."""
    main = read("db/adb/asta_pkg.sql")
    # 86.63% 감소이며 282,289us 증가했지만 after가 1초 이하라 의미 있는 개선이다.
    before_elapsed, after_elapsed = 635448, 917737
    before_gets, after_gets = 37237, 4979
    assert round((before_gets - after_gets) / before_gets * 100, 2) == 86.63
    assert after_elapsed - before_elapsed == 282289
    assert after_elapsed <= 1_000_000
    assert "OLTP_BUFFER_READS_MEANINGFUL_IMPROVEMENT" in main
    assert "l_retain_original := CASE WHEN l_verdict = 'IMPROVED' THEN 'false'" in main
    assert "l_gets_pct >= 20" in main
    assert "l_after_elapsed <= 1000000" in main
    assert "(l_after_elapsed - l_before_elapsed) <= 300000" in main
    for field in ['\"elapsed_delta_us\"', '\"after_elapsed_under_1s\"',
                  '\"user_perceptible_latency_risk\"']:
        assert field in main


def test_oltp_tradeoff_boundaries_and_report_wording():
    main = read("db/adb/asta_pkg.sql")
    report = read("db/adb/asta_report_pkg.sql")
    assert "OLTP_BUFFER_READS_IMPROVED_LATENCY_TRADEOFF_TOO_LARGE" in main
    assert "의미 있는 개선 - Buffer Gets 대폭 감소, 튜닝 SQL 적용 검토" in report
    assert "1초 미만으로 사용자 체감 영향 제한적" in report
    assert "동시 실행 시 DB 부하 개선" in report
    assert "OLTP 개선 성공" in report
    assert "고빈도·동시 실행에서 의미" in report


def test_oltp_comparison_enforces_three_second_latency_target_before_buffer_win():
    main = read("db/adb/asta_pkg.sql")
    target = "l_after_elapsed > 3000000"
    improvement = "l_after_elapsed <= l_before_elapsed AND l_gets_pct >= 5"
    assert target in main
    assert "OLTP_LATENCY_TARGET_NOT_MET" in main
    assert "WHEN l_after_elapsed > 3000000 THEN 'HIGH'" in main
    assert '\"oltp_latency_target_us\":3000000' in main
    assert main.index(target) < main.index(improvement)
