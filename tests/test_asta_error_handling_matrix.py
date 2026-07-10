from pathlib import Path
import asyncio
import sys

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.routers import asta_proxy


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_plsql_classifies_common_operational_error_families():
    source = read("db/adb/asta_pkg.sql")
    expected = {
        "ORA-00942": "SOURCE_OBJECT_NOT_FOUND",
        "ORA-01031": "SOURCE_PRIVILEGE_DENIED",
        "ORA-00904": "SQL_INVALID_IDENTIFIER",
        "ORA-00918": "SQL_AMBIGUOUS_COLUMN",
        "ORA-00911": "SQL_SYNTAX_ERROR",
        "ORA-01789": "SQL_SET_SHAPE_MISMATCH",
        "ORA-01476": "SQL_DIVIDE_BY_ZERO",
        "ORA-01722": "SQL_INVALID_NUMBER",
        "ORA-01861": "SQL_INVALID_DATE",
        "ORA-32039": "SQL_RECURSIVE_WITH_INVALID",
        "ORA-03150": "SOURCE_DBLINK_UNAVAILABLE",
        "ORA-01013": "EXECUTION_CANCELLED",
        "ORA-00054": "RESOURCE_BUSY",
        "ORA-01555": "SNAPSHOT_TOO_OLD",
        "ORA-01652": "SPACE_EXHAUSTED",
        "ORA-22828": "PAYLOAD_LIMIT",
        "ORA-04068": "PACKAGE_INVALIDATED",
        "ORA-02290": "REPOSITORY_CONSTRAINT",
        "ORA-274": "SCHEDULER_SUBMIT_FAILED",
    }
    for oracle_code, application_code in expected.items():
        assert oracle_code in source
        assert application_code in source


def test_failed_run_lookup_contracts_include_code_message_and_error_object():
    source = read("db/adb/asta_pkg.sql")
    for function_name in ("get_run", "get_progress", "get_report"):
        start = source.index(f"FUNCTION {function_name}(")
        end = source.index(f"END {function_name};", start)
        section = source[start:end]
        assert "error_code" in section
        assert "error_message" in section
        assert "error_json(l_error_code, l_error_message)" in section


def test_source_failure_prefers_exact_nested_oracle_message():
    source = read("db/adb/asta_pkg.sql")
    start = source.index("FUNCTION source_response_error_message(")
    end = source.index("END source_response_error_message;", start)
    section = source[start:end]
    assert "RETURN NVL(l_error_message, l_message);" in section


def test_canonical_response_exposes_top_level_error_fields():
    source = read("db/adb/asta_report_pkg.sql")
    section = source[source.index("FUNCTION build_response_json(", source.index("PACKAGE BODY")):]
    assert '\"error_code\"' in section
    assert "json_vc(p_error_json, '$.code', NULL)" in section
    assert '\"error_message\"' in section
    assert "json_vc(p_error_json, '$.message', NULL)" in section


def test_submit_failure_is_a_terminal_structured_response():
    source = read("db/adb/asta_pkg.sql")
    section = source[source.index("FUNCTION submit_run("):source.index("END submit_run;")]
    assert '\"status\":\"FAILED\"' in section
    assert "classify_error_code(l_submit_error" in section
    assert '\"error_message\"' in section


def test_proxy_extracts_exact_error_message():
    assert asta_proxy._response_error_message({
        "error_message": "ORA-00942: table or view does not exist",
        "error": {"message": "less specific"},
    }) == "ORA-00942: table or view does not exist"


def test_analyze_converts_terminal_ords_failure_to_http_error(monkeypatch):
    async def fake_post(*_args, **_kwargs):
        return {
            "status": "FAILED",
            "error_code": "SQL_GUARD_REJECTED",
            "error_message": "ORA-20001: unsafe SQL",
        }

    monkeypatch.setattr(asta_proxy, "_post_json_to_ords", fake_post)
    monkeypatch.setattr(asta_proxy, "_resolve_ords_url", lambda *_args: "https://example.invalid")
    monkeypatch.setattr(asta_proxy, "_ords_timeout", lambda *_args: 30)
    monkeypatch.setattr(asta_proxy.asta_audit, "write_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(asta_proxy.asta_audit, "write_run_index", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(asta_proxy.asta_audit, "base_context", lambda *_args, **_kwargs: {})

    class Request:
        async def json(self):
            return {"sql": "delete from t"}

    try:
        asyncio.run(asta_proxy.analyze(Request(), None, "devdoADB"))
        assert False, "expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 422
        assert exc.detail["error"] == "SQL_GUARD_REJECTED"
        assert "ORA-20001" in exc.detail["message"]


def test_ui_prefers_persisted_error_message_over_generic_step_detail():
    source = read("static/js/extensions/tuning_assistant.js")
    assert "progress?.error_message || progress?.error?.message || failedStep?.detail" in source
    assert '["FAILED", "ERROR"].includes(String(data?.status || "").toUpperCase())' in source
    assert "data?.error_message || data?.error?.message" in source
    assert "immediateError.progress = data" in source


def test_ui_highlights_oracle_error_and_explains_ora_00942_privilege_case():
    source = read("static/js/extensions/tuning_assistant.js")
    assert "function extractAstaOracleError(value)" in source
    assert "ORA-\\d{5}" in source
    assert "Oracle 오류" in source
    assert "조회 권한이 없을 때도 ORA-00942" in source
    assert "직접 SELECT 권한" in source
