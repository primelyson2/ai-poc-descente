from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
UI = (ROOT / "static/js/extensions/tuning_assistant.js").read_text(encoding="utf-8")
INDEX = (ROOT / "static/index.html").read_text(encoding="utf-8")


def test_sql_input_is_an_open_collapsible_section():
    assert '<details id="asta-input-section" class="tuning-card tuning-collapsible-section" open>' in UI
    assert '<summary class="tuning-card-title tuning-collapsible-summary">' in UI
    assert '<span class="section-title">SQL 분석 입력</span>' in UI
    assert '<div class="tuning-collapsible-body">' in UI


def test_analysis_result_is_rendered_as_an_open_collapsible_section():
    assert '<details class="card tuning-report-card tuning-collapsible-section" open>' in UI
    assert '<summary class="tuning-report-collapse-summary">' in UI
    assert '<span class="section-title">ASTA 분석 결과</span>' in UI
    assert '<div class="tuning-report-collapse-body">' in UI


def test_result_collapses_input_and_reset_reopens_it():
    assert 'function collapseInputSectionForResult()' in UI
    assert 'inputSection.open = false;' in UI
    render_result = UI[UI.index("function renderResult(target, data)"):UI.index("function decodeVectorEntities")]
    assert "collapseInputSectionForResult();" in render_result

    reset_workspace = UI[UI.index("function resetWorkspace()"):UI.index("function optimizationGoalForWorkload")]
    assert 'document.getElementById("asta-input-section")' in reset_workspace
    assert "inputSection.open = true;" in reset_workspace


def test_collapsible_sections_have_visible_toggle_and_new_cache_version():
    assert ".tuning-collapsible-summary::-webkit-details-marker" in UI
    assert ".tuning-collapsible-summary::after" in UI
    assert ".tuning-report-collapse-summary::after" in UI
    assert "tuning_assistant.js?v=20260714_guide_introduction1" in INDEX


def test_input_and_result_sections_share_the_same_surface_contract():
    shared = re.search(r"\.tuning-card,\s*\.tuning-report-card\s*\{([^}]+)\}", UI)
    assert shared, "input/result cards must use one shared visual surface rule"
    rule = shared.group(1)
    assert "border:1px solid var(--border)" in rule
    assert "border-radius:var(--radius-lg)" in rule
    assert "background:var(--surface)" in rule
    assert "box-shadow:none" in rule
    assert '<span class="section-title">SQL 분석 입력</span>' in UI
    assert ".tuning-collapsible-body { padding:var(--space-4); border-top:1px solid var(--border); }" in UI
    assert "border-radius:22px" not in UI


def test_mobile_cards_and_single_report_action_keep_the_shared_shape():
    assert ".tuning-card { padding:0; border-radius:var(--radius-lg); box-shadow:none; }" in UI
    assert ".tuning-report-actions { grid-template-columns:1fr;" in UI
    assert ".tuning-controls-row > .tuning-field:last-child { grid-column:1 / -1; }" not in UI
    assert ".tuning-input:focus, .tuning-sql:focus" in UI


def test_dropdown_chevron_is_inset_from_the_right_edge():
    assert "select.tuning-input {" in UI
    assert "appearance:none" in UI
    assert "background-position:right 16px center" in UI
    assert "padding-right:42px" in UI
