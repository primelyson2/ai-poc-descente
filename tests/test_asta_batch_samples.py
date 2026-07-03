"""ASTA AWR 샘플 SQL의 정적 계약 테스트."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEW_PATH = ROOT / "static/js/extensions/tuning_assistant.js"


def view_text() -> str:
    return VIEW_PATH.read_text(encoding="utf-8")


def awr_blocks(view: str):
    return re.findall(
        r'\{\s*id: "asta-awr-(\d{2})",(?P<body>.*?)\n\s*\},',
        view,
        flags=re.DOTALL,
    )


def test_sesl0640_and_derived_samples_have_id_label_and_workload_metadata():
    blocks = awr_blocks(view_text())
    assert [number for number, _ in blocks] == [f"{number:02d}" for number in range(1, 11)]
    for number, body in blocks:
        if number == "01":
            assert 'sqlId: "7rcw6d3us86r7"' in body
            assert 'label: "SESL0640.selectList"' in body
        else:
            assert "ASTA intentionally inefficient sample" in body
            assert 'label: "SESL0640 ' in body
        assert 'workload: "' in body
        assert "sql: `" in body


def test_awr_samples_replace_all_legacy_samples():
    view = view_text()
    assert 'id: "asta-ui-' not in view
    assert 'id: "asta-batch-' not in view
    assert "ASTA_UI_MALICIOUS_" not in view
    assert "ASTA_BATCH_" not in view


def test_awr_samples_are_single_read_only_sql_without_sqlplus_binds():
    view = view_text()
    blocks = awr_blocks(view)
    assert len(blocks) == 10
    for _, body in blocks:
        assert re.search(r"sql: `(?:SELECT|WITH|/\*)", body, re.IGNORECASE)
        assert ":v_" not in body
        assert "FOR UPDATE" not in body.upper()
        assert not re.search(r"^\s*(variable|exec)\s", body, re.MULTILINE | re.IGNORECASE)


def test_sample_selection_sets_workload_and_refreshes_description():
    view = view_text()
    apply_sample = view[view.index("function applySampleSql"):view.index("function updateLineNumbers")]
    assert 'const workloadType = sample.workload || "OLTP"' in apply_sample
    assert "workloadSelect.value = workloadType" in apply_sample
    assert "updateWorkloadDescription(workloadType)" in apply_sample
    assert 'id="asta-workload-description"' in view
    assert 'workloadSelect.addEventListener("change"' in view


def test_reset_defaults_to_oltp():
    view = view_text()
    reset = view[view.index("function resetWorkspace"):view.index("function optimizationGoalForWorkload")]
    assert 'workloadSelect.value = "OLTP"' in reset
    assert 'updateWorkloadDescription("OLTP")' in reset
