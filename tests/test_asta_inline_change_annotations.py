"""SQL-only 구조 재작성의 선두 변경 요약 헤더 계약 회귀 테스트."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_evidence_prompt_requests_leading_header_and_server_can_supply_it():
    llm = read("db/adb/asta_llm_pkg.sql")
    assert "For a changed SQL, prepend: /* ASTA_TUNING_CHANGE_1:" in llm
    assert "ASTA will add it if omitted" in llm
    assert "prepend_generated_change_annotation" in llm
    assert "expected buffer/elapsed effect" in llm


def test_structural_candidate_gets_missing_header_and_comment_only_is_not_rewrite():
    llm = read("db/adb/asta_llm_pkg.sql")
    assert "FUNCTION leading_change_annotation_count" in llm
    assert "leading_change_annotation_count(l_candidate_sql) < 1" in llm
    assert "prepend_generated_change_annotation(l_candidate_sql)" in llm
    assert "ASTA added the required leading change annotation" in llm
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
    assert "Preserve columns, datatypes, order, NULL and COUNT(DISTINCT) semantics" in llm
    assert "No DDL, new hints, statistics changes" in llm


def test_all_prompt_modes_require_join_and_aggregation_grain_equivalence():
    llm = read("db/adb/asta_llm_pkg.sql")
    prompt = llm[llm.index("FUNCTION build_tuning_prompt("):llm.index("END build_tuning_prompt;")]
    contract = "preserve row grain, duplicate multiplicity, outer-join null extension, GROUP BY keys, analytic PARTITION BY keys, and scalar-aggregate empty-input behavior"
    assert contract in prompt
    # The contract must precede the A/B early-return branch so A, B, and C all receive it.
    assert prompt.index(contract) < prompt.index("IF l_mode IN ('A', 'B') THEN")
    assert "Pre-aggregate only at the original correlation or join-key grain." in prompt


def test_all_prompt_modes_prevent_asta_awr_01_invalid_identifier_rewrites():
    llm = read("db/adb/asta_llm_pkg.sql")
    prompt = llm[llm.index("FUNCTION build_tuning_prompt("):llm.index("END build_tuning_prompt;")]
    identifier_contract = "Identifier safety is mandatory: use only base-table column names present for that same source in the input SQL or supplied object metadata"
    assert identifier_contract in prompt
    assert prompt.index(identifier_contract) < prompt.index("IF l_mode IN ('A', 'B') THEN")
    assert "never guess abbreviated column names" in prompt
    assert "Every introduced CTE or inline view must project each column referenced downstream from a valid source expression." in prompt


def test_all_prompt_modes_prevent_asta_awr_01_invalid_set_projections():
    llm = read("db/adb/asta_llm_pkg.sql")
    prompt = llm[llm.index("FUNCTION build_tuning_prompt("):llm.index("END build_tuning_prompt;")]
    projection_contract = "never use SELECT * in a UNION, INTERSECT, or MINUS"
    assert projection_contract in prompt
    assert prompt.index(projection_contract) < prompt.index("IF l_mode IN ('A', 'B') THEN")
    assert "same number of expressions in the same semantic order with compatible datatypes in every branch" in prompt
    assert "using typed zero or NULL placeholders where a measure is absent" in prompt
    assert "After joining sources, qualify every referenced column with its source alias." in prompt
