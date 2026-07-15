from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_report_tabs_dom_behavior():
    completed = subprocess.run(
        ["node", "tests/js/asta_report_tabs_dom_test.cjs"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_result_renderer_keeps_raw_download_without_gate_ui():
    ui = (ROOT / "static/js/extensions/tuning_assistant.js").read_text(encoding="utf-8")
    start = ui.index("function renderResult")
    end = ui.index("API 오류 객체", start)
    renderer = ui[start:end]

    assert "rawReport: String(report)" in renderer
    assert "displayReport: safeReport" in renderer
    assert "window.__astaLastReport.rawReport" in ui[ui.index('getElementById("asta-download-report")'):]
    assert 'querySelector(".tuning-gate-host")' not in renderer
    assert "renderAstaGateSummary" not in ui
    assert "buildAstaGateViewModel" not in ui
    assert ".tuning-gate-" not in ui
    assert "검증 Gate 상태" not in ui


def test_result_renderer_integrates_existing_status_actions_and_tabs_in_one_header():
    ui = (ROOT / "static/js/extensions/tuning_assistant.js").read_text(encoding="utf-8")
    start = ui.index("function renderResult")
    end = ui.index("API 오류 객체", start)
    renderer = ui[start:end]
    reset_start = ui.index("function resetWorkspace")
    reset_end = ui.index("function optimizationGoalForWorkload", reset_start)
    reset = ui[reset_start:reset_end]

    assert 'class="tuning-report-header"' in renderer
    assert 'class="tuning-report-status-slot"' in renderer
    assert 'id="asta-report-tabs-host"' in renderer
    assert 'querySelector(".tuning-report-tablist")' in renderer
    assert "if (tabsHost && tabList) tabsHost.appendChild(tabList)" in renderer
    assert "if (statusSlot && progressTarget) statusSlot.appendChild(progressTarget)" in renderer
    assert "if (reportActions && downloadButton) reportActions.append(downloadButton)" in renderer
    assert "reportActions.append(downloadButton, resetButton)" not in renderer
    assert "asta-report-top" not in renderer
    assert "asta-report-bottom" not in renderer
    assert 'id="asta-download-report"' not in renderer
    assert 'id="asta-reset"' not in renderer
    assert "topActions.insertBefore(resetButton, secretButton)" in reset
    assert "topActions.insertBefore(downloadButton, secretButton)" in reset
    assert "topActions.append(progressTarget)" in reset


def test_report_card_uses_redwood_tokens_and_compact_segmented_tabs():
    ui = (ROOT / "static/js/extensions/tuning_assistant.js").read_text(encoding="utf-8")
    redwood = (ROOT / "static/css/redwood.css").read_text(encoding="utf-8")
    for token in ("--surface", "--surface-alt", "--border", "--primary", "--primary-light", "--text", "--text-muted"):
        assert token in redwood
        assert f"var({token})" in ui

    assert ".tuning-report-card {" in ui
    assert "background:var(--surface)" in ui
    assert "border:1px solid var(--border)" in ui
    assert ".tuning-report-header {" in ui
    assert ".tuning-verdict-summary {" in ui
    assert ".tuning-verdict-help-toggle {" in ui
    assert ".tuning-verdict-help {" in ui
    assert "position:absolute" in ui[ui.index(".tuning-verdict-help {"):ui.index(".tuning-verdict-help h3")]
    assert ".tuning-verdict-help-anchor::after" in ui
    assert ".tuning-verdict-help-open::after" in ui
    assert ".tuning-report-tabs-host {" in ui
    tablist = ui[ui.index(".tuning-report-tablist {"):ui.index(".tuning-report-tab {", ui.index(".tuning-report-tablist {"))]
    assert "background:var(--surface-alt)" in tablist
    assert "border:1px solid var(--border)" in tablist
    assert "border-radius:var(--radius-lg)" in tablist
    assert "box-shadow" not in tablist
    active_start = ui.index('.tuning-report-tab[aria-selected="true"]')
    active_end = ui.index("}", active_start)
    active = ui[active_start:active_end]
    assert "var(--primary)" in active
    assert "var(--primary-light)" in active or "var(--surface)" in active
    for hardcoded in ("#1d4ed8", "#2563eb", "#eff6ff", "#bfdbfe"):
        assert hardcoded not in active


def test_report_mobile_header_keeps_segmented_tabs_scrollable_without_wrapping():
    ui = (ROOT / "static/js/extensions/tuning_assistant.js").read_text(encoding="utf-8")
    mobile_start = ui.index("@media (max-width: 700px)")
    mobile = ui[mobile_start:ui.index("@media", mobile_start + 1)]
    assert ".tuning-report-header" in mobile
    assert ".tuning-report-tablist" in mobile
    assert "overflow-x:auto" in mobile
    assert "flex-wrap:nowrap" in mobile
    assert "padding-inline:" in mobile


def test_index_loads_report_tabs_before_tuning_assistant():
    index = (ROOT / "static/index.html").read_text(encoding="utf-8")
    tabs = index.index("/static/js/extensions/asta_report_tabs.js")
    assistant = index.index("/static/js/extensions/tuning_assistant.js")
    assert tabs < assistant


def test_report_tabs_expose_safe_line_diff_for_before_and_tuned_sql():
    tabs = (ROOT / "static/js/extensions/asta_report_tabs.js").read_text(encoding="utf-8")
    ui = (ROOT / "static/js/extensions/tuning_assistant.js").read_text(encoding="utf-8")
    assert '{ id: "changes", label: "SQL 변경" }' in tabs
    assert tabs.index('{ id: "before", label: "튜닝 전" }') < tabs.index('{ id: "changes", label: "SQL 변경" }') < tabs.index('{ id: "after", label: "튜닝 후" }')
    assert "function buildSqlLineDiff(beforeSql, afterSql)" in tabs
    assert "function formatSqlForDiff(sql)" in tabs
    assert "공백·줄바꿈·키워드 대소문자를 통일한 SQL 포맷 기준" in tabs
    assert "function alignSqlDiffRows(rows)" in tabs
    assert "function renderSqlDiff(parent, beforeSql, afterSql, changeSummary, changeLocation)" in tabs
    assert "무엇을 어디서 바꿨나" in tabs
    assert "tuning-sql-side-by-side" in tabs
    assert "tuning-sql-diff-pane-${side}" in tabs
    assert ".tuning-sql-diff-pane {" in ui
    assert ".tuning-sql-diff-remove" in ui
    assert ".tuning-sql-diff-add" in ui
    assert ".tuning-sql-diff-line" in ui
