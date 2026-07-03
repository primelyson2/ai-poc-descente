"""ASTA 결과 품질 agent의 고객 SQL gate와 evidence 선택 테스트."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.asta_quality_agent import calculate_stats, choose_variant, normalize_result, report_markdown
from tools.run_asta_prompt_abc_adb import rotate_modes


def config():
    return {
        "quality": {
            "customer_sample_id": "asta-awr-01",
            "customer_min_runs": 3,
            "customer_min_success_rate": 1.0,
            "history_cycles": 5,
            "min_batch_elapsed_reduction_pct": 5,
            "min_oltp_buffer_reduction_pct": 5,
        },
        "variants": [
            {"id": "A", "evidence": "SQL"},
            {"id": "B", "evidence": "SQL + XPLAN"},
            {"id": "C", "evidence": "FULL"},
        ],
    }


def result(mode: str, elapsed_after: int = 80, equivalent: bool = True):
    return {
        "sample_id": "asta-awr-01",
        "mode": mode,
        "candidate_generated": True,
        "prompt_chars": 1000,
        "comparison": {
            "runtime_shape_equivalent": equivalent,
            "before_elapsed_time_us": 100,
            "after_elapsed_time_us": elapsed_after,
            "before_buffer_gets": 1000,
            "after_buffer_gets": 900,
        },
    }


def normalized(mode: str, cycle: int, elapsed_after: int = 80, equivalent: bool = True):
    return normalize_result(result(mode, elapsed_after, equivalent), {"asta-awr-01": "BATCH"}, f"cycle-{cycle}")


def test_customer_sql_requires_every_configured_repeat_to_improve():
    rows = [normalized("B", 1), normalized("B", 2), normalized("B", 3, elapsed_after=101)]
    stats = calculate_stats(rows, config())
    b = next(item for item in stats if item.variant_id == "B")
    assert b.customer_successes == 2
    assert not b.customer_gate_passed
    assert choose_variant(stats) is None


def test_choose_lowest_evidence_variant_that_passes_customer_gate():
    rows = [normalized(mode, cycle) for mode in ("B", "C") for cycle in range(1, 4)]
    stats = calculate_stats(rows, config())
    assert choose_variant(stats).variant_id == "B"


def test_non_equivalent_candidate_never_counts_as_improvement():
    rows = [normalized("A", cycle, equivalent=False) for cycle in range(1, 4)]
    a = calculate_stats(rows, config())[0]
    assert a.customer_successes == 0
    assert not a.customer_gate_passed


def test_report_is_review_only_and_blocks_deploy_without_customer_gate():
    rows = [normalized("A", 1)]
    stats = calculate_stats(rows, config())
    report = report_markdown(stats, rows, config(), "cycle-1")
    assert "EXPERIMENT_MORE" in report
    assert "배포하면 안 됩니다" in report
    assert "자동 적용: **없음**" in report


def test_variant_order_rotates_to_reduce_cache_warming_bias():
    modes = ["A", "B", "C"]
    assert rotate_modes(modes, sample_index=0, cycle_rotation=0) == ["A", "B", "C"]
    assert rotate_modes(modes, sample_index=0, cycle_rotation=1) == ["B", "C", "A"]
    assert rotate_modes(modes, sample_index=1, cycle_rotation=2) == ["A", "B", "C"]
