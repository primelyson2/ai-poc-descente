from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def section(text: str, start: str, end: str) -> str:
    begin = text.index(start)
    return text[begin:text.index(end, begin)]


def test_ui_omits_gate_card_while_backend_gate_artifacts_remain():
    ui = (ROOT / "static/js/extensions/tuning_assistant.js").read_text(encoding="utf-8")
    tabs = (ROOT / "static/js/extensions/asta_report_tabs.js").read_text(encoding="utf-8")
    runtime = (ROOT / "app/asta_runtime_gates.py").read_text(encoding="utf-8")
    report = (ROOT / "db/adb/asta_report_pkg.sql").read_text(encoding="utf-8")
    main = (ROOT / "db/adb/asta_pkg.sql").read_text(encoding="utf-8")
    assert "renderAstaGateSummary" not in ui
    assert "buildAstaGateViewModel" not in ui
    assert "tuning-gate" not in ui
    assert "tuning-gate-host" not in tabs
    assert "검증 Gate 상태" not in ui
    for evidence in ("equivalence_status", "comparison", "verdict"):
        assert evidence in runtime
        assert evidence in main
    assert "p_comparison_json" in report
    assert "결과 동일성" in report


def test_ui_terminal_outcome_never_turns_blocked_or_rejected_into_success_toast():
    ui = (ROOT / "static/js/extensions/tuning_assistant.js").read_text(encoding="utf-8")
    assert "function astaWorkflowOutcome" in ui
    outcome = section(ui, "function astaWorkflowOutcome", "function redactAstaReportForUi")
    for status in ("BLOCKED", "REJECTED", "FAILED", "ERROR"):
        assert f'"{status}"' in outcome
    submit = ui[ui.index('document.getElementById("asta-run").addEventListener'):]
    assert "const terminalOutcome = astaWorkflowOutcome(data);" in submit
    assert 'terminalOutcome === "ACCEPTED"' in submit
    assert 'window.Toast?.show?.("ASTA 분석이 완료되었습니다.", "success")' in submit
    assert "const issue = friendlyAstaIssue(data, terminalOutcome)" in submit
    assert 'window.Toast?.show?.(`${issue.title}: ${issue.message}`' in submit
    success_branch = submit[submit.index('terminalOutcome === "ACCEPTED"'):submit.index("} catch (err)")]
    assert success_branch.index('"ASTA 분석이 완료되었습니다.", "success"') < success_branch.index("else")


def test_ui_masks_sql_literals_bind_values_and_preserves_ora_reason_text():
    ui = (ROOT / "static/js/extensions/tuning_assistant.js").read_text(encoding="utf-8")
    redactor = section(ui, "function redactAstaSensitiveText", "function astaWorkflowOutcome")
    assert "ORA-" in redactor
    assert "SQL_TEXT_REDACTED" in redactor
    assert "BIND_VALUE_REDACTED" in redactor
    assert "slice(0, 2000)" in redactor
    assert "eval(" not in redactor


def test_ui_report_preserves_sql_but_masks_credentials_and_download_keeps_raw_artifact():
    ui = (ROOT / "static/js/extensions/tuning_assistant.js").read_text(encoding="utf-8")
    assert "function redactAstaReportForUi" in ui
    renderer = section(ui, "function renderResult", "function decodeVectorEntities")
    assert "const safeReport = redactAstaReportForUi(report);" in renderer
    assert "report: safeReport" in renderer
    assert "renderTrustedVectorBlocks(reportScroller, window.__astaLastReport.report)" in renderer
    assert "rawReport: String(report)" in renderer
    assert "displayReport: safeReport" in renderer
    assert "JSON.stringify(data" not in renderer
    redactor = section(ui, "function redactAstaReportForUi", "function renderResult")
    assert "CREDENTIAL_REDACTED" in redactor
    assert "CONNECTION_STRING_REDACTED" in redactor
    assert "SQL_TEXT_REDACTED" not in redactor
    assert "SQL_LITERAL_REDACTED" not in redactor
    download = ui[ui.index('document.getElementById("asta-download-report").addEventListener'):]
    assert "window.__astaLastReport.rawReport" in download
    error_detail = section(ui, "function errorDetailText", "function renderError")
    assert "JSON.stringify(payload" not in error_detail


def test_vector_positive_search_is_gate_complete_only_and_rejections_are_separate():
    vector = (ROOT / "db/adb/asta_vector_pkg.sql").read_text(encoding="utf-8")
    main = (ROOT / "db/adb/asta_pkg.sql").read_text(encoding="utf-8")
    search = section(vector, "FUNCTION search_similar_cases(", "END search_similar_cases;")
    save_start = vector.index("FUNCTION save_case(\n", vector.index("PACKAGE BODY"))
    save = vector[save_start:vector.index("END save_case;", save_start)]
    metadata = section(main, "FUNCTION build_vector_metadata(", "END build_vector_metadata;")

    assert "POSITIVE_VERIFIED" in search
    assert "$.learning_class" in search
    assert "REJECTED_OBSERVATION" in save
    assert "POSITIVE_VERIFIED" in save
    assert "VECTOR_POSITIVE_GATE_INCOMPLETE" in save
    for path in (
        "$.optimizer_intent_status", "$.result_digest_scope", "$.equivalence_status",
        "$.bind_stability_status", "$.all_representative_binds_passed", "$.measurement_status",
    ):
        assert path in save
        assert path in metadata
    assert "VERIFIED_OUTCOME" in save
    assert "REJECTED_OBSERVATION" in save
    assert "REJECTION_REASON" in save
    assert '"learning_class":' in save


def test_vector_storage_does_not_persist_raw_sql_or_bind_literals_in_chunks():
    vector = (ROOT / "db/adb/asta_vector_pkg.sql").read_text(encoding="utf-8")
    save_start = vector.index("FUNCTION save_case(\n", vector.index("PACKAGE BODY"))
    save = vector[save_start:vector.index("END save_case;", save_start)]
    assert "USING l_case_id, l_redacted_sql, l_redacted_sql" in save
    assert "save_case_chunk(l_case_id, 'SOURCE_SQL', p_sql)" not in save
    assert "save_case_chunk(l_case_id, 'TUNED_SQL', p_tuned_sql)" not in save
    assert "|| p_tuned_sql" not in save
    assert "bind_value" not in save.lower()
    assert "rejected_candidate_sql" not in save.lower()
    assert "l_report_ref" in save
    assert "REGEXP_LIKE(p_report_markdown, '^/api/asta/runs/" in save
    assert "REJECTION_REASON_REDACTED" in save
    assert "'change_summary' VALUE" not in save
    assert "'advisor_summary' VALUE" not in save
