"""SQL-only 구조 재작성의 선두 변경 요약 헤더 계약 회귀 테스트."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_sql_only_prompt_requires_detailed_numbered_leading_header_for_both_workloads():
    llm = read("db/adb/asta_llm_pkg.sql")
    contract = "/* ASTA_TUNING_CHANGE_1: [기존 문제] -> [변경 방식] -> [기대 효과] */"
    assert contract in llm
    assert "첫 SQL token 이전" in llm
    assert "본문 중간에는 ASTA_TUNING_CHANGE 주석을 넣지" in llm
    assert "반복 횟수/스캔/서브쿼리/조인/집계 패턴" in llm
    assert "elapsed/buffer/temp" in llm
    assert "실제 측정값" in llm and "날조" in llm
    assert "1부터 빈 번호 없이 순차" in llm
    assert llm.index(contract) < llm.index("IF l_workload_type = 'BATCH' THEN")


def test_structural_candidate_requires_valid_header_and_comment_only_is_not_rewrite():
    llm = read("db/adb/asta_llm_pkg.sql")
    assert "FUNCTION leading_change_annotation_count" in llm
    assert "leading_change_annotation_count(l_candidate_sql) < 1" in llm
    assert "NO_REWRITE: structural candidate missing required leading ASTA_TUNING_CHANGE_1 header" in llm
    marker_check = llm.index("leading_change_annotation_count(l_candidate_sql) < 1")
    assert marker_check < llm.index("l_profile := l_try_profile", marker_check)
    assert "structural_sql_key(p_sql) = structural_sql_key(l_candidate_sql)" in llm
    assert "identical, comment-only, or hint-only candidate" in llm


def test_artifact_exposes_header_metadata_and_preserves_candidate_clob():
    llm = read("db/adb/asta_llm_pkg.sql")
    assert ',\"leading_change_annotations_present\":' in llm
    assert ',\"leading_change_annotation_count\":' in llm
    assert "clob_app_json_str(l_result, l_candidate_sql)" in llm


def test_guard_rejects_body_markers_and_validates_sequential_leading_header():
    guard = read("db/adb/asta_sql_guard_pkg.sql")
    assert "PROCEDURE assert_safe_leading_annotations" in guard
    assert "ASTA_SQL_GUARD: ASTA tuning change annotation must be in leading header" in guard
    assert "ASTA_SQL_GUARD: ASTA tuning change annotations must be sequential from 1" in guard
    assert "[[:space:]]+->[[:space:]]+.+[[:space:]]+->[[:space:]]+." in guard
    assert "assert_safe_leading_annotations(l_head)" in guard
    # 일반 원본 주석은 계속 허용한다.
    assert "strip_leading_comments(l_head)" in guard


def test_report_explains_top_header_and_header_location_when_candidate_exists():
    report = read("db/adb/asta_report_pkg.sql")
    notice = "SQL 맨 앞의 `ASTA_TUNING_CHANGE_n` 주석에 전체 변경 사항을 설명합니다."
    assert notice in report
    assert "튜닝 SQL 상단 변경 요약" in report
    section = report[report.rindex("clob_app(l_report, '## 튜닝 후 SQL") :]
    candidate_if = section.index("IF l_candidate_sql_vc IS NOT NULL THEN")
    candidate_else = section.index("ELSE", candidate_if)
    assert candidate_if < section.index(notice) < candidate_else


def test_empty_llm_summary_falls_back_to_header_annotations_in_report_and_vector_metadata():
    report = read("db/adb/asta_report_pkg.sql")
    main = read("db/adb/asta_pkg.sql")
    assert "FUNCTION inline_change_summary" in report  # compatibility helper name
    assert "FUNCTION useful_change_text" in report
    assert "inline_change_summary(l_candidate_sql_vc)" in report
    assert "inline_change_locations(l_candidate_sql_vc)" in report
    assert "FUNCTION inline_change_summary" in main
    assert "NULLIF(JSON_SERIALIZE" in main
    assert "l_inline_summary := inline_change_summary(p_llm_json);" in main
    metadata = main[main.index("FUNCTION build_vector_metadata"):main.index("END build_vector_metadata;")]
    sql_object = metadata[metadata.index("SELECT JSON_OBJECT("):metadata.index("INTO l_out FROM dual")]
    assert "inline_change_summary(p_llm_json)" not in sql_object
    assert "l_inline_summary, '-'" in sql_object


def test_formatter_keeps_each_header_comment_on_one_line_before_formatted_sql():
    report = read("db/adb/asta_report_pkg.sql")
    formatter = report[report.index("FUNCTION format_sql_basic"):report.index("END format_sql_basic;")]
    assert "l_header" in formatter and "l_body" in formatter
    assert "REGEXP_REPLACE(l_comment, '[[:space:]]+', ' ')" in formatter
    assert "l_header || CHR(10) || l_body" in formatter


def test_vector_never_exposes_empty_array_literal_as_change_summary():
    vector = read("db/adb/asta_vector_pkg.sql")
    assert "CASE WHEN TRIM(change_summary) IN ('[]', 'null', '') THEN '-'" in vector
    llm = read("db/adb/asta_llm_pkg.sql")
    assert "출력 컬럼의 datatype과 문자열 format" in llm
    assert "NLS 의존 변환" in llm
