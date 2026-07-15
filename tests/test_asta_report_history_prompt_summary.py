"""Result-report contracts for the safe verified-history prompt disclosure."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "db/adb/asta_report_pkg.sql"


def test_report_discloses_actual_safe_history_prompt_context_without_sql_preview():
    src = REPORT.read_text(encoding="utf-8")
    assert src.index("FUNCTION safe_vector_text(p_val IN VARCHAR2) RETURN VARCHAR2;") < src.index(
        "PROCEDURE append_verified_history_prompt_summary("
    )
    helper = src.split("PROCEDURE append_verified_history_prompt_summary(", 1)[1].split(
        "END append_verified_history_prompt_summary;", 1
    )[0]

    for required in (
        "## Vector 검색·프롬프트 반영",
        "검토 수행:",
        "프롬프트 반영 결과: 반영하지 않음",
        "판단 사유:",
        "DIAGNOSIS와 CANDIDATE_SQL 프롬프트에 함께 보냈습니다",
        "현재 근거가 항상 우선",
        "CANDIDATE_ACCEPTANCE_CHECKLIST",
        "verified_history_reference_summary.cases[*]",
        "case_id",
        "change_summary",
    ):
        assert required in helper
    assert "        ))\n    ) LOOP" in helper
    assert "sql_preview" not in helper
    assert "report_ref" not in helper
    assert "append_verified_history_prompt_summary(l_report, p_llm_json);" in src


def test_report_keeps_only_core_bottleneck_explanation():
    src = REPORT.read_text(encoding="utf-8")
    helper = src.split("PROCEDURE append_bottleneck_diagnosis(", 1)[1].split(
        "END append_bottleneck_diagnosis;", 1
    )[0]
    build = src.rsplit("FUNCTION build_report(", 1)[1].split("END build_report;", 1)[0]

    assert "핵심 병목 설명" in helper
    for removed in ("### 지배 병목 대상", "### 진단 요약과 변경 전략", "### 의미 보존 위험과 확인 사항"):
        assert removed not in helper
    assert "append_bottleneck_diagnosis(" in build
    assert "## 작업 수행 이력" not in build
    assert "append_stage_check(l_report" not in build
    assert "append_stage_timing(l_report" not in build
    assert "## 상세 분석" not in build
    assert "append_verified_history_prompt_summary(l_report" in build


def test_report_does_not_render_oracle_sql_tuning_advisor_sections():
    src = REPORT.read_text(encoding="utf-8")
    build = src.rsplit("FUNCTION build_report(", 1)[1].split("END build_report;", 1)[0]
    assert "append_advisor_summary(l_report" not in build
    assert "append_dba_review(l_report" not in build
    assert "Oracle SQL Tuning Advisor 요약" not in build
