"""ASTA 화면 매뉴얼/아키텍처/11단계 Workflow 팝업 계약."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "static/js/extensions/tuning_assistant.js"
INDEX = ROOT / "static/index.html"


def source() -> str:
    return SOURCE.read_text(encoding="utf-8")


def test_manual_dialog_has_accessible_trigger_tabs_and_close_paths():
    text = source()
    assert 'id="asta-manual-open"' in text
    assert '>매뉴얼 및 사용설명</button>' in text
    assert 'id="asta-manual-dialog"' in text
    assert 'role="dialog" aria-modal="true"' in text
    assert 'aria-labelledby="asta-manual-title"' in text
    assert 'role="tablist" aria-label="ASTA 도움말 목차"' in text
    assert 'data-manual-tab="architecture"' in text
    assert 'data-manual-tab="workflow"' in text
    assert "function openAstaManualDialog" in text
    assert "function closeAstaManualDialog" in text
    assert 'event.key === "Escape"' in text
    assert 'event.target === manualDialog' in text
    assert "manualReturnFocus?.focus?.()" in text


def test_manual_tabs_have_clear_clickable_and_selected_affordance():
    text = source()
    assert 'class="tuning-manual-tab-index">01</span>' in text
    assert 'class="tuning-manual-tab-index">02</span>' in text
    assert 'class="tuning-manual-tab-label">아키텍처</span>' in text
    assert 'class="tuning-manual-tab-label">11단계 Workflow</span>' in text
    assert ".tuning-manual-tab::after { content:'열기';" in text
    assert ".tuning-manual-tab[aria-selected=\"true\"]::after { content:'선택됨 ✓';" in text
    assert "transform:translateY(-1px)" in text
    assert "cursor:pointer" in text
    assert "box-shadow:inset 0 -3px var(--primary)" in text


def test_architecture_explains_all_four_requested_responsibility_zones():
    text = source()
    for title in (
        "User / 개발자",
        "UI (VM)",
        "OCI AI Lakehouse",
        "OCI ERP Database (BaseDB)",
    ):
        assert title in text
    for boundary in (
        "운영 SQL 자동 변경 없음",
        "FastAPI thin proxy",
        "ORDS · ADB PL/SQL · DBMS_SCHEDULER",
        "DB Link · ASTA_SOURCE_PKG",
    ):
        assert boundary in text
    assert "ASTA_ARCHITECTURE_ZONES" in text
    assert "renderArchitectureManual" in text


def test_architecture_maps_oci_resources_into_dev_pro_and_shared_groups():
    text = source()
    assert "ASTA_OCI_RESOURCE_GROUPS" not in text
    for compartment in (
        "DEV compartment",
        "PRO compartment",
        "Shared / Regional OCI Services",
    ):
        assert compartment in text
    for resource in (
        "OCI Load Balancer",
        "DK-AI-DEV-VM-01",
        "Autonomous Database 26ai",
        "ORDS asta.v1",
        "ASTA Vector KB",
        "OCI ERP Database (BaseDB)",
        "ASTA_SOURCE_PKG",
        "VCN / Subnet / NSG",
        "OCI IAM",
        "OCI Generative AI",
    ):
        assert resource in text
    assert "OCID 비표시" not in text
    assert "tuning-manual-resources" not in text
    assert "tuning-manual-resource-groups" not in text
    assert "tuning-manual-zone-resources" in text
    assert "tuning-manual-compartment" in text
    assert "zone.resources.map" in text
    assert "zone.resources.length ?" in text
    user_zone = text[text.index('key: "user"'):text.index('key: "ui"')]
    assert 'compartment: "PoC 샘플 화면"' in user_zone
    assert "resources: []" in user_zone
    assert "OCI Load Balancer → DK-AI-DEV-VM-01" in text


def test_workflow_manual_covers_exactly_eleven_canonical_steps_and_procedures():
    text = source()
    assert "ASTA_WORKFLOW_GUIDE" in text
    for seq in range(1, 12):
        assert f"seq: {seq}," in text
    for code in (
        "REQUEST_RECEIVED",
        "ORDS_DISPATCH",
        "SQL_GUARD",
        "BEFORE_EVIDENCE",
        "SQL_TUNING_ADVISOR",
        "LLM_REWRITE",
        "AFTER_EVIDENCE",
        "BEFORE_AFTER_COMPARE",
        "VECTOR_KB",
        "FINAL_REPORT",
        "VECTOR_SAVE",
    ):
        assert f'code: "{code}"' in text
    for procedure in (
        "ASTA_PKG.SUBMIT_RUN",
        "ASTA_PKG.EXECUTE_RUN / RUN_PIPELINE",
        "ASTA_SQL_GUARD_PKG.ASSERT_SAFE_SELECT",
        "ASTA_SOURCE_BRIDGE_PKG.RUN_SOURCE_EVIDENCE",
        "ASTA_SOURCE_PKG.RUN_EVIDENCE",
        "ASTA_SOURCE_PKG.RUN_ADVISOR_OPT",
        "ASTA_LLM_PKG.GENERATE_SQL_ONLY_TUNING",
        "ASTA_PKG.BUILD_COMPARISON_JSON",
        "ASTA_VECTOR_PKG.SEARCH_SIMILAR_CASES",
        "ASTA_REPORT_PKG.BUILD_REPORT",
        "ASTA_VECTOR_PKG.SAVE_CASE",
    ):
        assert procedure in text
    assert "호환 단계 번호" in text
    assert "실제 호출은 9 → 6" in text


def test_workflow_manual_replaces_short_work_text_with_detailed_task_lists():
    text = source()
    workflow = text[text.index("const ASTA_WORKFLOW_GUIDE"):text.index("const ASTA_DEVELOPER_PLATFORMS")]
    assert "work:" not in workflow
    assert workflow.count("tasks: [") == 11
    assert 'class="tuning-manual-step-task-list"' in text
    assert "step.tasks.map" in text
    for detail in (
        "request_json과 QUEUED 상태",
        "1초 간격 progress 조회",
        "SUBMIT_RUN 접수 시 한 번",
        "업무 SELECT를 실행하지 않고 EXPLAIN PLAN",
        "4단계 Source response의 advisor.status",
        "정상 LLM 호출은 보통 2회, fallback 포함 최대 6회",
        "실제 실행 체크 시에만 PLAN_ONLY·ONCE",
        "result digest",
        "generate_sql_only_tuning prompt에는 p_vector_json을 넣지 않아",
        "11단계 Vector 저장 결과",
        "REJECTED_OBSERVATION",
    ):
        assert detail in workflow


def test_manual_dialog_is_responsive_and_asset_cache_is_bumped():
    text = source()
    for selector in (
        ".tuning-manual-dialog",
        ".tuning-manual-panel",
        ".tuning-manual-architecture-grid",
        ".tuning-manual-workflow-list",
        ".tuning-manual-workflow-card",
    ):
        assert selector in text
    assert "@media (max-width: 700px)" in text
    assert "tuning_assistant.js?v=20260709_no_3s_latency1" in INDEX.read_text(encoding="utf-8")
