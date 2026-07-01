"""ASTA UI 배치 워크로드 샘플의 정적 계약 테스트."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEW_PATH = ROOT / "static/js/extensions/tuning_assistant.js"


def view_text() -> str:
    return VIEW_PATH.read_text(encoding="utf-8")


def batch_blocks(view: str):
    return re.findall(
        r'\{\s*id: "asta-batch-(\d{2})",(?P<body>.*?)\n\s*\},',
        view,
        flags=re.DOTALL,
    )


def test_exactly_five_batch_samples_have_ids_labels_markers_and_metadata():
    view = view_text()
    blocks = batch_blocks(view)
    assert [number for number, _ in blocks] == ["01", "02", "03", "04", "05"]
    assert view.count('id: "asta-batch-') == 5
    for number, body in blocks:
        assert f'label: "배치 {number}' in body
        assert 'workload: "BATCH"' in body
        assert f"ASTA_BATCH_{number}_" in body


def test_batch_samples_cover_five_distinct_structural_inefficiencies():
    view = view_text()
    required_markers = [
        "ASTA_BATCH_01_REPEATED_YEAR_UNION_SCANS",
        "ASTA_BATCH_02_CORRELATED_AGGREGATES",
        "ASTA_BATCH_03_DUPLICATE_CTE_SCANS",
        "ASTA_BATCH_04_FUNCTION_JOIN_WINDOW_SORT",
        "ASTA_BATCH_05_FACT_AGGREGATE_REJOINS",
    ]
    for marker in required_markers:
        assert marker in view


def test_batch_sql_is_read_only_devdo_and_avoids_cartesian_explosions():
    view = view_text()
    blocks = batch_blocks(view)
    assert len(blocks) == 5
    for _, body in blocks:
        sql = body.lower()
        assert "sql: `select" in sql or "sql: `with" in sql
        assert "devdo." in sql
        assert not re.search(r"\b(insert|update|delete|merge|create|alter|drop|truncate)\b", sql)
        assert "cross join" not in sql
        assert not re.search(r"from\s+devdo\.sales\s+\w+\s*,\s*devdo\.sales", sql)
    assert "join DEVDO.SALES s2" not in "\n".join(body for _, body in blocks)


def test_sample_selection_sets_workload_and_refreshes_description():
    view = view_text()
    apply_sample = view[view.index("function applySampleSql"):view.index("function updateLineNumbers")]
    assert 'const workloadType = sample.workload || "OLTP"' in apply_sample
    assert "workloadSelect.value = workloadType" in apply_sample
    assert "updateWorkloadDescription(workloadType)" in apply_sample
    assert 'id="asta-workload-description"' in view
    assert 'workloadSelect.addEventListener("change"' in view


def test_reset_and_legacy_samples_default_to_oltp():
    view = view_text()
    reset = view[view.index("function resetWorkspace"):view.index("function optimizationGoalForWorkload")]
    assert 'workloadSelect.value = "OLTP"' in reset
    assert 'updateWorkloadDescription("OLTP")' in reset
    assert 'sample.workload || "OLTP"' in view
