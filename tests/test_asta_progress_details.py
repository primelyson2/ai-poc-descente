"""ASTA 현재 단계 요약과 11단계 상세 진행 로그 UI 계약."""

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "static/js/extensions/tuning_assistant.js"


def source() -> str:
    return SOURCE.read_text(encoding="utf-8")


def test_default_progress_is_current_stage_only_and_drawer_contains_all_steps():
    text = source()
    assert 'id="asta-current-progress" class="tuning-progress-anchor" aria-live="polite" hidden' in text
    assert 'class="tuning-current-progress' in text
    assert 'class="tuning-progress-open"' in text
    assert '>상세</button>' in text
    assert 'class="tuning-progress-drawer" hidden' in text
    assert 'role="dialog" aria-modal="true"' in text
    assert "steps.map((step) => renderProgressDetailStep(step, isComplete, llmCalls, runId)).join(\"\")" in text
    assert 'aria-label="ASTA 11단계 전체 진행상태와 로그"' in text


def test_ready_state_hides_progress_until_analysis_really_starts():
    text = source()
    assert "if (ready) {" in text
    assert "target.hidden = true;" in text
    assert 'target.innerHTML = "";' in text
    assert "PROGRESS_LOG_STATE.delete(target);" in text
    assert "target.hidden = false;" in text


def test_polling_never_replaces_the_drawer_dom_during_the_same_run():
    text = source()
    assert "const PROGRESS_RENDER_STATE = new WeakMap();" in text
    assert "function refreshProgressView" in text
    assert "previousRender?.runId === runId" in text
    assert "refreshProgressView(target, steps, {" in text
    assert "PROGRESS_RENDER_STATE.set(target, { runId });" in text
    assert 'class="tuning-progress-step-elapsed"' in text
    assert 'data-progress-step-card="${escapeHtml(step.seq)}"' in text
    assert 'data-progress-log-signature' in text


def test_each_detail_step_renders_status_timing_and_logs():
    text = source()
    assert 'function renderProgressDetailStep(step, isComplete, llmCalls = [], runId = "")' in text
    assert "progressStatusLabel(status)" in text
    assert "formatProgressTimestamp(step.started_at || step.at)" in text
    assert "formatProgressTimestamp(step.completed_at)" in text
    assert "stepElapsedMs(step, isComplete)" in text
    assert "buildStepLogs(step, isComplete)" in text
    assert 'class="tuning-progress-step-logs"' in text
    assert "단계 로그" in text


def test_drawer_step_cards_are_collapsed_summary_rows_by_default():
    text = source()
    assert '<details class="tuning-progress-detail-step' in text
    assert '<summary class="tuning-progress-step-head">' in text
    assert 'class="tuning-progress-step-body"' in text
    assert "const autoOpen =" in text
    assert "previousStatus !== status" in text
    assert "card.open =" in text
    assert ".tuning-progress-step-list { display:grid; gap:4px; }" in text
    assert ".tuning-progress-step-head { min-height:32px;" in text


def test_step_elapsed_distinguishes_milliseconds_unmeasured_and_skipped():
    text = source()
    assert "function formatStepElapsed(step, isComplete)" in text
    assert 'if (status === "SKIPPED") return "생략";' in text
    assert 'return "미측정";' in text
    assert 'return elapsed < 1 ? "<1ms" : `${Math.round(elapsed)}ms`;' in text
    assert "formatStepElapsed(current, isComplete)" in text
    assert "formatStepElapsed(step, isComplete)" in text


def test_polling_preserves_open_drawer_and_logs_only_stage_changes():
    text = source()
    assert 'const drawerWasOpen = !target.querySelector(".tuning-progress-drawer")?.hidden;' in text
    assert "if (drawerWasOpen)" in text
    assert "openProgressDrawer(target, false);" in text
    assert "function openProgressDrawer(target, focusClose = true)" in text
    assert "function closeProgressDrawer(target)" in text
    assert 'event.key === "Escape"' in text
    assert "const PROGRESS_LOG_STATE = new WeakMap();" in text
    assert 'console.info("asta-stage-progress"' in text
    assert "logChangedProgressSteps(target, runId, steps);" in text


def test_progress_drawer_styles_keep_default_summary_compact():
    text = source()
    for selector in (
        ".tuning-progress-open",
        ".tuning-progress-drawer",
        ".tuning-progress-drawer-panel",
        ".tuning-progress-drawer-close",
        ".tuning-progress-step-list",
        ".tuning-progress-step-log",
    ):
        assert selector in text
    assert "@media (max-width: 700px)" in text


def test_compact_summary_is_a_single_dense_status_line():
    text = source()
    assert 'class="tuning-current-step"' in text
    assert 'class="tuning-current-elapsed"' in text
    assert '>상세</button>' in text
    assert 'class="tuning-current-run-label"' not in text
    assert 'class="tuning-current-run-id"' not in text
    assert 'class="tuning-progress-drawer-run"' in text
    assert "const compactLabel" in text
    assert "min-height:32px" in text


def test_naive_oracle_timestamps_are_parsed_as_utc_not_browser_local_time():
    text = source()
    assert "function normalizeAstaTimestamp(value)" in text
    assert "Timezone-less Oracle timestamps are UTC" in text
    assert "new Date(normalizeAstaTimestamp(value)).getTime()" in text


def test_timestamp_normalization_in_asia_seoul_runtime():
    completed = subprocess.run(
        ["node", "tests/js/asta_progress_time_test.cjs"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_progress_details_asset_has_a_fresh_cache_buster():
    index = (ROOT / "static/index.html").read_text(encoding="utf-8")
    assert "tuning_assistant.js?v=20260709_no_3s_latency1" in index


def test_before_evidence_shows_concrete_internal_work_without_fake_substage_progress():
    text = source()
    assert "function renderBeforeEvidenceActivity()" in text
    assert "제한 실행 1회" in text
    assert "워밍업·반복 측정 없음" in text
    assert "전체 결과 건수 확인 1회" in text
    assert "'전체 결과' : '제한 결과'" in text
    assert 'total: "최대 3회"' in text
    assert "하위 작업별 완료 신호를 보내지 않아" in text
    assert 'class="tuning-before-evidence-activity"' in text
    assert "activity.hidden = !beforeEvidenceRunning" in text


def test_llm_calls_are_rendered_inside_stage_six_with_live_summary():
    text = source()
    assert "function normalizeLlmCalls(progress)" in text
    assert "function renderLlmCallActivity(calls, runId)" in text
    assert "function refreshLlmCallActivity(target, calls, runId)" in text
    assert 'String(step.code || "").toUpperCase() === "LLM_REWRITE"' in text
    assert 'class="tuning-llm-call-host"' in text
    for stage in ("DIAGNOSIS", "CANDIDATE_SQL", "REPAIR_SQL"):
        assert stage in text
    for field in ("profile_name", "call_status", "prompt_chars", "response_chars", "elapsed_ms"):
        assert field in text
    assert 'data-llm-call-elapsed=' in text
    assert 'elapsed.textContent = call.elapsed_ms == null ? "미측정" : formatDuration(call.elapsed_ms)' in text


def test_llm_prompt_and_response_are_lazy_loaded_and_collapsed_by_default():
    text = source()
    assert "const LLM_CALL_DETAIL_CACHE = new Map();" in text
    assert 'data-load-llm-call=' in text
    assert "Prompt·응답 원문 보기" in text
    assert "원문은 버튼을 누를 때만 별도 API로 불러옵니다" in text
    assert "fetchJson(`${baseUrl}/runs/${encodeURIComponent(runId)}/llm-calls/${callId}`)" in text
    assert '<details class="tuning-llm-raw-block">' in text
    assert "운영 SQL과 XPLAN이 포함될 수 있습니다" in text
    assert "renderLlmRawBlock(\"LLM Prompt\"" in text
    assert "renderLlmRawBlock(\"Provider 응답\"" in text


def test_llm_progress_summary_never_embeds_raw_prompt_or_response():
    adb = (ROOT / "db/adb/asta_pkg.sql").read_text(encoding="utf-8")
    summary = adb.split("FUNCTION build_llm_calls_json", 1)[1].split("END build_llm_calls_json;", 1)[0]
    assert "prompt_chars" in summary
    assert "response_chars" in summary
    assert "prompt_clob" not in summary
    assert "response_clob" not in summary
    detail = adb.split("FUNCTION get_llm_call", 2)[2].split("END get_llm_call;", 1)[0]
    assert "prompt_clob" in detail
    assert "response_clob" in detail
    assert "run_id = l_run_id" in detail
    assert "call_id = p_call_id" in detail


def test_llm_trace_rendering_and_default_raw_collapse_in_node():
    completed = subprocess.run(
        ["node", "tests/js/asta_llm_trace_render_test.cjs"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
