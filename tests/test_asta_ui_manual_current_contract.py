"""Real ASTA UI 매뉴얼이 현재 실행 계약과 같은 이름과 경계를 쓰는지 검증한다."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "static/js/extensions/tuning_assistant.js"
INDEX = ROOT / "static/index.html"
PROXY = ROOT / "app/routers/asta_proxy.py"
ORDS = ROOT / "db/ords/asta_ords_module.sql"
ADB = ROOT / "db/adb/asta_pkg.sql"
LLM = ROOT / "db/adb/asta_llm_pkg.sql"
VECTOR = ROOT / "db/adb/asta_vector_pkg.sql"
REPORT = ROOT / "db/adb/asta_report_pkg.sql"
SOURCE = ROOT / "db/source/asta_source_pkg.sql"
DOCS = (
    ROOT / "docs/AI_SQL_TUNING_ASSISTANT_MANUAL.md",
    ROOT / "docs/OADT2_ASTA_ARCHITECTURE.md",
    ROOT / "docs/asta_source_execution_flow.md",
    ROOT / "docs/README.md",
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def ui_section(start: str, end: str) -> str:
    text = read(UI)
    return text[text.index(start):text.index(end)]


def test_architecture_distinguishes_default_estimated_plan_from_runtime_opt_in():
    architecture = ui_section("const ASTA_ARCHITECTURE_ZONES", "const ASTA_WORKFLOW_GUIDE")
    source = read(SOURCE)
    for marker in (
        "execute_source_sql=false",
        "ESTIMATED_PLAN",
        "source_sql_executed=false",
        "execute_source_sql=true",
        "PLAN_ONLY",
        "FULL_RESULT",
    ):
        assert marker in architecture
    assert "l_evidence_mode = 'ESTIMATED_PLAN'" in source
    assert "l_evidence_mode = 'PLAN_ONLY'" in source
    assert "l_evidence_mode = 'FULL_RESULT'" in source


def test_workflow_covers_current_candidate_recovery_and_vector_classes():
    workflow = ui_section("const ASTA_WORKFLOW_GUIDE", "const ASTA_DEVELOPER_PLATFORMS")
    adb = read(ADB)
    llm = read(LLM)
    vector = read(VECTOR)
    implementation_markers = {
        "VERIFIED_HISTORY_REUSE": adb,
        "available_fallback_profile": llm,
        "compact_column_dictionary": llm,
        "guard_repair_attempted": llm,
        "candidate_source": llm,
        "ANALYSIS_OBSERVATION": vector,
        "observation_reason": vector,
    }
    for marker, implementation in implementation_markers.items():
        assert marker in implementation
        assert marker in workflow


def test_manual_names_analysis_only_fields_without_claiming_measurement():
    ui = read(UI)
    manual = read(DOCS[0])
    adb = read(ADB)
    report = read(REPORT)
    for marker in (
        "ANALYSIS_ONLY",
        "ESTIMATED_PLAN_ONLY",
        "SOURCE_SQL_NOT_EXECUTED",
        "source_sql_executed=false",
        "source_runtime_metrics_status=NOT_MEASURED",
        "runtime_verification_status=NOT_EXECUTED",
        "equivalence_status=NOT_EVALUATED",
        "repeat_performance_status=NOT_MEASURED",
    ):
        assert marker in ui
        assert marker in manual
    for marker in (
        '"verdict":"ANALYSIS_ONLY"',
        '"analysis_mode":"ESTIMATED_PLAN_ONLY"',
        '"execution_mode":"SOURCE_SQL_NOT_EXECUTED"',
        '"source_sql_executed":false',
        '"source_runtime_metrics_status":"NOT_MEASURED"',
        '"equivalence_status":"NOT_EVALUATED"',
        '"repeat_performance_status":"NOT_MEASURED"',
    ):
        assert marker in adb
    assert "l_runtime_status := 'NOT_EXECUTED'" in report
    assert "runtime_verification_status" in report
    for forbidden in (
        "ANALYSIS_ONLY는 개선 성공",
        "ANALYSIS_ONLY는 개선 실패",
    ):
        assert forbidden not in ui
        assert forbidden not in manual


def test_developer_trace_includes_llm_summary_lazy_detail_and_report_download_paths():
    developer = ui_section("const ASTA_DEVELOPER_PLATFORMS", "const PROGRESS_LOG_STATE")
    proxy = read(PROXY)
    ords = read(ORDS)
    adb = read(ADB)
    for marker, implementation in (
        ("get_run_llm_call", proxy),
        ("ASTA_PKG.GET_LLM_CALL", ords),
        ("build_llm_calls_json", adb),
        ("llm_calls", adb),
    ):
        assert marker in implementation
        assert marker in developer
    for endpoint in (
        "/api/asta/runs/{run_id}/progress",
        "/api/asta/runs/{run_id}/llm-calls/{call_id}",
        "/api/asta/runs/{run_id}/report",
        "/api/asta/runs/{run_id}/report/view",
        "/api/asta/runs/{run_id}/report/download",
    ):
        assert endpoint in developer
        assert endpoint in read(DOCS[0])
    assert "보고서 다운로드 버튼은 브라우저의 downloadText" in developer


def test_manual_separates_comparison_verdicts_from_stage_reasons_and_run_errors():
    developer = ui_section("const ASTA_DEVELOPER_BRANCHES", "const ASTA_DEVELOPER_TRACE")
    adb = read(ADB)
    for verdict in (
        "IMPROVED",
        "ANALYSIS_ONLY",
        "NOT_IMPROVED",
        "NON_EQUIVALENT",
        "INSUFFICIENT_EVIDENCE",
        "CANDIDATE_FAILED",
        "NO_REWRITE",
    ):
        assert f"l_verdict := '{verdict}'" in adb or f'\"verdict\":\"{verdict}\"' in adb
        assert verdict in developer
    assert "PLAN_SCREEN_*는 verdict가 아니라 사용자 4~5단계의 선별 reason" in developer
    assert "CANDIDATE_RUNTIME_LIMIT은 comparison verdict가 아니라 Run error_code" in developer


def test_current_two_stage_llm_uses_only_safe_verified_history_reference_metadata():
    llm = read(LLM)
    assert 'vector_evidence_included":false' in llm
    required = ("vector_evidence_included=false",)
    for path in (UI, *DOCS):
        text = read(path)
        for marker in required:
            assert marker in text, f"{path.name} omits {marker}"
    for marker in ("VERIFIED_HISTORY_PATTERN_REFERENCE", "verified_history_references_included"):
        assert marker in llm
        assert marker in read(UI)
    assert "VERIFIED_HISTORY_PATTERN_REFERENCE" in read(DOCS[1])


def test_screen_names_defaults_api_and_cache_buster_match_current_ui():
    ui = read(UI)
    manual = read(DOCS[0])
    assert "AI 모델 설정" in ui
    assert "실행 유형" in ui
    assert "샘플 튜닝대상 SQL" in ui
    assert "소스 DB에서 SQL을 실제 실행하여 검증" in ui
    assert 'id="asta-execute-source-sql" type="checkbox"' in ui
    assert "executeSourceSqlInput.checked = false" in ui
    for button in (
        "매뉴얼 및 사용설명",
        "AI 분석 실행",
        "신규분석(초기화)",
        "보고서 다운로드",
        "Prompt·응답 원문 보기",
    ):
        assert button in ui
        assert button in manual
    for path in DOCS:
        assert "최종 업데이트: 2026-07-10" in read(path)
    assert "tuning_assistant.js?v=20260714_guide_introduction1" in read(INDEX)
