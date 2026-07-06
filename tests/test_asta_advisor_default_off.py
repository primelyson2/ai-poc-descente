from pathlib import Path

from app.routers.asta_proxy import _coerce_payload


ROOT = Path(__file__).resolve().parents[1]


def test_proxy_defaults_advisor_off_when_new_or_legacy_fields_are_missing():
    for incoming in (
        {"sql": "select 1 from dual"},
        {"sql": "select 1 from dual", "options": {}},
        {"sql": "select 1 from dual", "run_advisor": False, "use_sqltune": True},
    ):
        payload = _coerce_payload(incoming)
        assert payload["run_advisor"] is False
        assert payload["use_sqltune"] is False


def test_proxy_preserves_explicit_future_advisor_opt_in():
    for incoming in (
        {"sql": "select 1 from dual", "run_advisor": True},
        {"sql": "select 1 from dual", "use_sqltune": True},
        {"sql": "select 1 from dual", "options": {"run_advisor": True}},
    ):
        payload = _coerce_payload(incoming)
        assert payload["run_advisor"] is True
        assert payload["use_sqltune"] is True


def test_adb_default_is_off_but_advisor_implementation_and_artifacts_remain():
    main = (ROOT / "db/adb/asta_pkg.sql").read_text(encoding="utf-8")
    source = (ROOT / "db/source/asta_source_pkg.sql").read_text(encoding="utf-8")
    report = (ROOT / "db/adb/asta_report_pkg.sql").read_text(encoding="utf-8")

    assert "JSON_VALUE(p_body_json, '$.run_advisor'" in main
    assert "JSON_VALUE(p_body_json, '$.use_sqltune'" in main
    assert "'false'" in main[main.index("JSON_VALUE(p_body_json, '$.run_advisor'"):main.index("FROM   dual;", main.index("JSON_VALUE(p_body_json, '$.run_advisor'"))]
    assert "FUNCTION run_advisor_opt(" in source
    assert "p_run_advisor      => l_run_advisor" in main
    assert "PROCEDURE append_advisor_summary" in report
    assert "$.advisor_requested" in report
    assert "$.advisor.status" in report
    assert "l_advisor_status  VARCHAR2(30) := 'SKIPPED'" in source
    assert "CASE WHEN l_run_advisor = 'Y' THEN 'true' ELSE 'false' END" in source
    assert "json_vc(p_source_evidence_json, '$.advisor_requested', 'false')" in report
    assert "json_vc(p_source_evidence_json, '$.advisor.status', 'SKIPPED')" in report
