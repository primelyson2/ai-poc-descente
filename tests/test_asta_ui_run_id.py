from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_active_run_id_is_visible_in_progress_header():
    source = (ROOT / "static/js/extensions/tuning_assistant.js").read_text(encoding="utf-8")
    assert 'const runId = String(progress?.run_id || progress?.runId || "").trim();' in source
    assert 'class="tuning-current-run-id"' in source
    assert ">${escapeHtml(runId)}</code>" in source
    assert "user-select:all" in source


def test_run_id_copy_button_copies_only_raw_id_value():
    source = (ROOT / "static/js/extensions/tuning_assistant.js").read_text(encoding="utf-8")
    assert 'class="tuning-copy-run-id"' in source
    assert 'await copyPlainText(runId);' in source
    assert 'navigator.clipboard.writeText(value)' in source
    assert 'textarea.value = value' in source
    assert 'Run ID만 복사했습니다.' in source


def test_submit_response_renders_run_id_before_polling():
    source = (ROOT / "static/js/extensions/tuning_assistant.js").read_text(encoding="utf-8")
    branch = source[source.index('if (data?.run_id && ["RUNNING", "QUEUED"]'):]
    render_pos = branch.index("renderProgressStack(progressTarget, { ...data")
    poll_pos = branch.index("await pollRunProgress(baseUrl, data.run_id")
    assert render_pos < poll_pos
