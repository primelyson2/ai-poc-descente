from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ui_translates_internal_codes_into_problem_and_next_action():
    ui = (ROOT / "static/js/extensions/tuning_assistant.js").read_text(encoding="utf-8")

    for code in (
        "CANDIDATE_RUNTIME_LIMIT",
        "SQL_GUARD_REJECTED",
        "SQL_SYNTAX_ERROR",
        "SOURCE_DBLINK_UNAVAILABLE",
        "RESULT_DIGEST_MISMATCH",
        "FULL_RESULT_EVIDENCE_REQUIRED",
        "BIND_COVERAGE_INSUFFICIENT",
        "MEASUREMENT_NOISE_TOO_HIGH",
    ):
        assert code in ui
    for text in (
        "후보 SQL 검증 시간이 초과되었습니다",
        "원본 SQL은 변경되지 않았습니다",
        "다음 행동:",
        "문의 코드:",
        "기술 정보 (문의 시 전달)",
        "문의 정보 복사",
    ):
        assert text in ui
    assert "function friendlyAstaIssue(" in ui
    assert 'runButton.textContent = "확인 필요"' in ui
    assert 'runButton.textContent = "다시 분석"' in ui


def test_timeout_keeps_stable_code_but_uses_developer_friendly_message():
    package = (ROOT / "db/adb/asta_pkg.sql").read_text(encoding="utf-8")

    assert "error_code='CANDIDATE_RUNTIME_LIMIT'" in package
    assert "후보 SQL 검증 시간이 초과되었습니다. 원본 SQL은 변경되지 않았습니다." in package
    assert "Candidate execution exceeded the adaptive runtime limit; original SQL retained" not in package


def test_report_separates_easy_explanation_from_support_code():
    report = (ROOT / "db/adb/asta_report_pkg.sql").read_text(encoding="utf-8")

    assert "FUNCTION friendly_reason_text(" in report
    assert "- 권장 행동: " in report
    assert "- 쉬운 설명: " in report
    assert "- 문의 코드: `" in report
    assert "메모리 읽기 블록 수(Buffer Gets)" in report
    assert "검증 중인 개선 SQL — 현재 적용하지 마세요" in report


def test_manual_starts_with_developer_actions_and_common_messages():
    manual = (ROOT / "docs/AI_SQL_TUNING_ASSISTANT_MANUAL.md").read_text(encoding="utf-8")

    assert "개발자용 사용자 매뉴얼" in manual
    assert "먼저 알아둘 내용" in manual
    assert "Run ID와 문의 코드" in manual
    assert "자주 나오는 용어" in manual
    assert "자주 보는 메시지와 해결 방법" in manual
    assert "Source DB에 `ASTA_RUN_ID ... FULLDIGEST` SQL이 보일 때" in manual
    assert "같은 분석을 반복하지 않는다" in manual


def test_cache_buster_serves_developer_message_ui():
    index = (ROOT / "static/index.html").read_text(encoding="utf-8")
    assert "asta_report_tabs.js?v=20260707_verdict_popover1" in index
    assert "tuning_assistant.js?v=20260707_manual_tabs1" in index
