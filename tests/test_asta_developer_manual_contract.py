"""UI 개발자 실행 절차가 실제 Real ASTA 심볼과 일치하는지 고정한다."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "static/js/extensions/tuning_assistant.js"
INDEX = ROOT / "static/index.html"
PROXY = ROOT / "app/routers/asta_proxy.py"
ORDS = ROOT / "db/ords/asta_ords_module.sql"
ADB = ROOT / "db/adb/asta_pkg.sql"
BRIDGE = ROOT / "db/adb/asta_source_bridge_pkg.sql"
SOURCE = ROOT / "db/source/asta_source_pkg.sql"
LLM = ROOT / "db/adb/asta_llm_pkg.sql"
VECTOR = ROOT / "db/adb/asta_vector_pkg.sql"
REPORT = ROOT / "db/adb/asta_report_pkg.sql"
REPORT_UI = ROOT / "static/js/extensions/asta_report_tabs.js"
DOCS = (
    ROOT / "docs/AI_SQL_TUNING_ASSISTANT_MANUAL.md",
    ROOT / "docs/asta_source_execution_flow.md",
    ROOT / "docs/OADT2_ASTA_ARCHITECTURE.md",
    ROOT / "docs/README.md",
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_developer_tab_is_separate_accessible_and_rendered():
    ui = read(UI)
    assert 'data-manual-tab="developer"' in ui
    assert 'class="tuning-manual-tab-index">03</span>' in ui
    assert 'class="tuning-manual-tab-label">개발자 실행 추적</span>' in ui
    assert 'id="asta-manual-developer"' in ui
    assert "function renderDeveloperManual" in ui
    assert '["architecture", "workflow", "developer"]' in ui
    assert "ASTA_DEVELOPER_PLATFORMS" in ui
    assert "ASTA_DEVELOPER_CALL_FLOW" in ui
    assert "ASTA_DEVELOPER_BRANCHES" in ui
    assert "ASTA_DEVELOPER_TRACE" in ui


def test_platform_roles_expose_only_real_files_and_symbols():
    ui = read(UI)
    expected = {
        UI: ("tuningAssistant", "formatSql", "stripTrailingSqlTerminator", "fetchJson", "pollRunProgress", "fetchReport", "renderResult", "downloadText"),
        REPORT_UI: ("classifyReportSections", "renderSafeMarkdown", "renderReportTabs"),
        PROXY: ("analyze", "_coerce_payload", "_post_json_to_ords", "_audited_run_lookup", "get_run_progress", "get_run_report", "download_run_report"),
        ADB: ("submit_run", "execute_run", "run_pipeline", "build_comparison_json", "record_progress"),
        BRIDGE: ("run_source_evidence", "get_connection_json"),
        SOURCE: ("run_evidence_store_proc", "run_evidence", "collect_metrics", "collect_xplan", "collect_object_info", "build_full_count_sql", "build_full_digest_sql"),
        LLM: ("generate_sql_only_tuning", "repair_sql_candidate"),
        VECTOR: ("search_similar_cases", "save_case"),
        REPORT: ("build_report", "build_response_json"),
    }
    for path, symbols in expected.items():
        implementation = read(path).lower()
        assert str(path.relative_to(ROOT)) in ui
        for symbol in symbols:
            assert symbol.lower() in implementation, f"missing real symbol {symbol} in {path}"
            assert symbol in ui, f"manual omits {symbol}"

    assert "DBMS_SCHEDULER.CREATE_JOB" in ui
    assert "DBMS_XPLAN.DISPLAY_CURSOR" in ui
    assert "DBMS_SQLTUNE" in ui
    assert "DBMS_CLOUD_AI.GENERATE" in ui


def test_call_flow_covers_submit_to_render_and_download_in_real_order():
    ui = read(UI)
    flow_source = ui[ui.index("const ASTA_DEVELOPER_CALL_FLOW"):ui.index("const ASTA_DEVELOPER_BRANCHES")]
    flow = (
        "stripTrailingSqlTerminator / formatSql",
        "POST /api/asta/analyze",
        "asta_proxy.analyze",
        "ASTA_PKG.SUBMIT_RUN",
        "ASTA_PKG.EXECUTE_RUN",
        "ASTA_PKG.RUN_PIPELINE",
        "ASTA_SQL_GUARD_PKG.ASSERT_SAFE_SELECT",
        "ASTA_SOURCE_BRIDGE_PKG.RUN_SOURCE_EVIDENCE",
        "ASTA_SOURCE_PKG.RUN_EVIDENCE_STORE_PROC",
        "ASTA_VECTOR_PKG.SEARCH_SIMILAR_CASES",
        "ASTA_LLM_PKG.GENERATE_SQL_ONLY_TUNING",
        "ASTA_PKG.BUILD_COMPARISON_JSON",
        "ASTA_VECTOR_PKG.SAVE_CASE",
        "ASTA_REPORT_PKG.BUILD_REPORT",
        "ASTA_REPORT_PKG.BUILD_RESPONSE_JSON",
        "pollRunProgress / fetchReport",
        "renderResult / renderReportTabs",
        "downloadText",
    )
    positions = [flow_source.index(item) for item in flow]
    assert positions == sorted(positions)
    for endpoint in (
        "/api/asta/runs/{run_id}/progress",
        "/api/asta/runs/{run_id}/report",
        "/api/asta/runs/{run_id}/report/download",
    ):
        assert endpoint in ui


def test_failure_original_retention_and_trace_guidance_are_visible():
    ui = read(UI)
    for marker in (
        "SQL_GUARD_REJECTED",
        "ANALYSIS_ONLY",
        "NO_REWRITE",
        "CANDIDATE_FAILED",
        "CANDIDATE_RUNTIME_LIMIT",
        "NON_EQUIVALENT",
        "INSUFFICIENT_EVIDENCE",
        "retain_original_sql=true",
        "원본 SQL 유지",
        "ASTA_RUNS",
        "ASTA_RUN_PROGRESS",
        "ASTA_LLM_CALL_LOG",
        "logs/asta/asta_request_audit.jsonl",
        "pytest -q tests/test_asta_manual_dialog.py tests/test_asta_developer_manual_contract.py",
        "node --check static/js/extensions/tuning_assistant.js",
        "git diff --check",
    ):
        assert marker in ui


def test_related_docs_share_developer_execution_contract_and_cache_version():
    required = (
        "개발자 실행 추적",
        "플랫폼별 역할과 실제 코드",
        "버튼 클릭부터 보고서 다운로드까지",
        "실패·차단·원본 유지 분기",
        "Run ID로 추적하는 방법",
        "ANALYSIS_ONLY",
        "ESTIMATED_PLAN_ONLY",
    )
    for path in DOCS:
        text = read(path)
        for heading in required:
            assert heading in text, f"{path.name} omits {heading}"
    assert "tuning_assistant.js?v=20260709_no_3s_latency1" in read(INDEX)
