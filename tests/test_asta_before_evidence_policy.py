from pathlib import Path

from app.routers.asta_proxy import _coerce_payload


ROOT = Path(__file__).resolve().parents[1]


def test_proxy_defaults_to_minimal_and_accepts_only_supported_modes():
    assert _coerce_payload({"sql": "select 1 from dual"})["before_evidence_mode"] == "MINIMAL"
    assert _coerce_payload({"sql": "select 1 from dual", "before_evidence_mode": "thorough"})["before_evidence_mode"] == "THOROUGH"
    assert _coerce_payload({"sql": "select 1 from dual", "options": {"before_evidence_mode": "FAST_PLAN"}})["before_evidence_mode"] == "FAST_PLAN"
    assert _coerce_payload({"sql": "select 1 from dual", "before_evidence_mode": "unsafe"})["before_evidence_mode"] == "MINIMAL"


def test_adb_maps_stage4_modes_without_changing_candidate_policy():
    main = (ROOT / "db/adb/asta_pkg.sql").read_text(encoding="utf-8")
    assert "FUNCTION normalized_before_evidence_mode" in main
    assert "JSON_VALUE(p_body_json, '$.before_evidence_mode'" in main
    assert "l_before_repeat_policy := CASE WHEN l_before_evidence_mode = 'THOROUGH' THEN 'AUTO' ELSE 'ONCE' END" in main
    assert "WHEN l_execute_source_sql = 'N' THEN 'ESTIMATED_PLAN'" in main
    assert "WHEN l_before_evidence_mode = 'FAST_PLAN' THEN 'BOUNDED'" in main

    before = main[main.index("l_source_json := asta_source_bridge_pkg.run_source_evidence"):]
    before = before[:before.index(");")]
    assert "p_repeat_policy    => l_before_repeat_policy" in before
    assert "p_result_evidence_mode => l_before_result_mode" in before

    screen = main[main.index("l_after_json := asta_source_bridge_pkg.run_source_evidence"):]
    screen = screen[:screen.index(");")]
    assert "p_repeat_policy    => 'ONCE'" in screen
    assert "p_result_evidence_mode => l_candidate_result_mode" in screen
    final = main[main.index("p_run_id           => l_run_id || '-TUNED-FINAL'"):]
    final = final[:final.index(");")]
    assert "p_repeat_policy    => 'AUTO'" in final
    assert "p_result_evidence_mode => 'FULL_RESULT'" in final


def test_ui_hides_policy_selector_and_always_sends_minimal():
    ui = (ROOT / "static/js/extensions/tuning_assistant.js").read_text(encoding="utf-8")
    assert 'id="asta-before-evidence-mode"' not in ui
    assert "beforeEvidenceModeSelect" not in ui
    assert ui.count('before_evidence_mode: "MINIMAL"') == 2
    assert "기본 안전 모드는 업무 SELECT를 실행하지 않고 EXPLAIN PLAN" in ui
