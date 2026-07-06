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


def test_terminal_failure_keeps_authoritative_failed_stage_and_throws():
    source = (ROOT / "static/js/extensions/tuning_assistant.js").read_text(encoding="utf-8")
    assert 'if (["FAILED", "ERROR", "BLOCKED", "REJECTED"].includes(overall))' in source
    assert "return byIndex;" in source
    assert "isOverallFailed ? (failed || running)" in source
    assert 'if (["FAILED", "BLOCKED", "REJECTED"].includes(status))' in source
    assert "err.progress = progress" in source
    assert "if (err?.progress)" in source


def test_before_evidence_uses_single_unambiguous_message():
    source = (ROOT / "static/js/extensions/tuning_assistant.js").read_text(encoding="utf-8")
    assert 'observationDetail = "Source SQL 실행 요청 처리 중";' in source
    assert "Source DB 세션 관측 불가" not in source
    assert "Source SQL 진척은 직접 확인되지 않음" not in source
