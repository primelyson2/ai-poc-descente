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


def test_sql_and_metrics_modes_receive_batch_workload_objective_before_return():
    llm = read("db/adb/asta_llm_pkg.sql")
    prompt = llm[llm.index("FUNCTION build_tuning_prompt("):llm.index("END build_tuning_prompt;")]
    branch_start = prompt.index("IF l_mode IN ('A', 'B') THEN")
    early_modes = prompt[branch_start:prompt.index("RETURN l_prompt;", branch_start)]
    assert "IF p_tuning_context_json IS NOT NULL THEN" in early_modes
    assert "workload_type, optimization_goal, and user_notes are mandatory rewrite objectives" in early_modes
    assert "clob_app_clob(l_prompt, p_tuning_context_json)" in early_modes


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


def test_all_prompt_modes_require_complete_and_resolvable_asta_awr_01_sql():
    llm = read("db/adb/asta_llm_pkg.sql")
    prompt = llm[llm.index("FUNCTION build_tuning_prompt("):llm.index("END build_tuning_prompt;")]
    contract = "Executable completeness preflight is mandatory"
    assert contract in prompt
    assert prompt.index(contract) < prompt.index("IF l_mode IN ('A', 'B') THEN")
    assert "never emit ellipses (... or …), TODO text, \"unchanged\" shorthand, or placeholder comments" in prompt
    assert "trace every alias.column reference in SELECT, JOIN, WHERE, GROUP BY, HAVING, and ORDER BY" in prompt
    assert "to a column projected by that exact CTE or inline-view alias" in prompt


def test_all_prompt_modes_keep_asta_awr_01_correlated_aggregates_on_original_consumers():
    llm = read("db/adb/asta_llm_pkg.sql")
    prompt = llm[llm.index("FUNCTION build_tuning_prompt("):llm.index("END build_tuning_prompt;")]
    contract = "Correlated-aggregate lift safety is mandatory"
    assert contract in prompt
    assert prompt.index(contract) < prompt.index("IF l_mode IN ('A', 'B') THEN")
    assert "build each helper CTE only from the original inner tables" in prompt
    assert "Preserve every non-wildcard correlation key" in prompt
    assert "LEFT JOIN it from the original immediate outer consumer" in prompt
    assert "Never join a helper producer to a pre-existing CTE as a substitute for the immediate outer consumer" in prompt
    assert "return no candidate when this localized lift is not possible" in prompt


def test_all_prompt_modes_preserve_asta_awr_01_cte_output_aliases():
    """A rewritten XX producer must still expose SALE_QTY to unchanged consumers."""
    llm = read("db/adb/asta_llm_pkg.sql")
    prompt = llm[llm.index("FUNCTION build_tuning_prompt("):llm.index("END build_tuning_prompt;")]
    contract = "CTE interface preservation is mandatory"
    assert contract in prompt
    assert prompt.index(contract) < prompt.index("IF l_mode IN ('A', 'B') THEN")
    assert "keep each original output column under its original alias" in prompt
    assert "Add derived values under new aliases instead of renaming or replacing an original output column" in prompt
    assert "every unchanged downstream alias.column reference remains valid" in prompt
    assert "for example XX.SALE_QTY" in prompt
    assert "reject the candidate if any unchanged downstream reference" in prompt


def test_all_prompt_modes_preserve_asta_awr_01_decode_wildcards_without_legacy_outer_joins():
    """The customer SQL's '-' wildcard aggregates must yield one joined row and compile."""
    llm = read("db/adb/asta_llm_pkg.sql")
    prompt = llm[llm.index("FUNCTION build_tuning_prompt("):llm.index("END build_tuning_prompt;")]
    contract = "When an outer DECODE makes ''-'' match all inner COLOR_CD or SIZE_CD values"
    assert contract in prompt
    assert prompt.index(contract) < prompt.index("IF l_mode IN ('A', 'B') THEN")
    assert "pre-aggregating every required exact and wildcard grain with GROUPING SETS plus GROUPING flags" in prompt
    assert "ANSI LEFT JOIN exactly one matching aggregate row" in prompt
    assert "Never join detail-grain helper rows through wildcard predicates because that multiplies consumer rows" in prompt
    assert "Never attach helper aliases with legacy (+) predicates" in prompt
    assert "isolating pre-existing (+) joins in an unchanged inline view first when necessary" in prompt
    assert "so multiple helpers cannot raise ORA-01416" in prompt


def test_all_prompt_modes_isolate_asta_awr_01_helpers_from_parent_legacy_outer_join():
    """Helper ANSI joins must not share the query block containing YY's (+) predicates."""
    llm = read("db/adb/asta_llm_pkg.sql")
    prompt = llm[llm.index("FUNCTION build_tuning_prompt("):llm.index("END build_tuning_prompt;")]
    contract = "Legacy outer-join compatibility preflight is mandatory"
    assert contract in prompt
    assert prompt.index(contract) < prompt.index("IF l_mode IN ('A', 'B') THEN")
    assert "if the query block where a helper would be joined contains any (+) predicate, add no ANSI JOIN to that block" in prompt
    assert "put the original immediate consumer (for example XX) and its helper ANSI LEFT JOINs in a new nested inline view" in prompt
    assert "leave the parent comma-separated sources and every (+) predicate verbatim" in prompt
    assert "Return no candidate if this syntax isolation cannot be completed." in prompt


def test_all_prompt_modes_reject_asta_awr_01_noop_rewrites():
    llm = read("db/adb/asta_llm_pkg.sql")
    prompt = llm[llm.index("FUNCTION build_tuning_prompt("):llm.index("END build_tuning_prompt;")]
    contract = "Structural effectiveness preflight is mandatory"
    assert contract in prompt
    assert prompt.index(contract) < prompt.index("IF l_mode IN ('A', 'B') THEN")
    assert "must actually implement its stated rewrite" in prompt
    assert "eliminate at least one repeated base-table access, correlated subquery execution, UNION branch scan" in prompt
    assert "only a redundant predicate, optimizer hint, or comment is not a structural rewrite" in prompt
    assert "return no candidate when no safe effective rewrite can be completed" in prompt


def test_xplan_focus_targets_one_dominant_asta_awr_01_operation():
    llm = read("db/adb/asta_llm_pkg.sql")
    prompt = llm[llm.index("FUNCTION build_tuning_prompt("):llm.index("END build_tuning_prompt;")]
    contract = "Evidence focus is mandatory when XPLAN is supplied"
    assert contract in prompt
    assert prompt.index(contract) < prompt.index("IF l_mode IN ('A', 'B') THEN")
    assert "rank operations by measured Buffers and A-Time, using Starts to identify repeated work" in prompt
    assert "rewrite exactly one pattern containing the dominant measured operation" in prompt
    assert "Do not select a low-buffer scalar subquery or another cheap operation" in prompt
    assert "return no candidate if that dominant pattern cannot be rewritten safely" in prompt


def test_full_evidence_rewrites_dominant_correlated_exists_view_once():
    llm = read("db/adb/asta_llm_pkg.sql")
    prompt = llm[llm.index("FUNCTION build_tuning_prompt("):llm.index("END build_tuning_prompt;")]
    contract = "CORRELATED_EXISTS_VIEW_RESTART"
    assert contract in prompt
    assert prompt.index(contract) > prompt.index("IF l_mode IN ('A', 'B') THEN")
    assert "Starts greater than 1 and dominates measured Buffers or A-Time" in prompt
    assert "evaluate that producer once in a DISTINCT CTE containing only the original correlation keys and inner predicates" in prompt
    assert "then semi-join or anti-join it only from the immediate consumer" in prompt
    assert "Preserve EXISTS versus NOT EXISTS and NULL semantics" in prompt
    assert "leave every unrelated query block unchanged" in prompt


def test_long_asta_awr_01_prompt_allows_one_cross_block_repeated_access_rewrite():
    llm = read("db/adb/asta_llm_pkg.sql")
    prompt = llm[llm.index("FUNCTION build_tuning_prompt("):llm.index("END build_tuning_prompt;")]
    boundary = "Long-SQL rewrite boundary: target exactly one repeated-access pattern"
    assert "DBMS_LOB.GETLENGTH(p_sql), 0) >= 12000" in prompt
    assert boundary in prompt
    assert prompt.index(boundary) < prompt.index("IF l_mode IN ('A', 'B') THEN")
    assert "This is a semantic scope, not a one-CTE or one-query-block edit limit" in prompt
    assert "add the helper CTEs and change projections, joins, GROUP BY expressions, and correlated references required" in prompt
    assert "within only the producer and consumer blocks participating in that pattern" in prompt
    assert "Preserve the original correlation or join-key grain and project every key needed downstream." in prompt
    assert "You may add one helper CTE" not in prompt
    assert "Copy every unrelated query block, CTE, UNION ALL branch, join, predicate, and select-list expression verbatim" in prompt
    assert "Do not decompose or rebuild the full statement into a new CTE architecture." in prompt
    assert "do not change any UNION ALL branch projection count" in prompt
    assert "reference a grouping key after it has been removed by aggregation" in prompt


def test_long_asta_awr_01_prompt_does_not_treat_unrelated_patterns_as_blockers():
    llm = read("db/adb/asta_llm_pkg.sql")
    prompt = llm[llm.index("FUNCTION build_tuning_prompt("):llm.index("END build_tuning_prompt;")]
    boundary = "Long-SQL rewrite boundary: target exactly one repeated-access pattern"
    clarification = "Other repeated-access patterns elsewhere do not block an isolated rewrite"
    assert boundary in prompt
    assert clarification in prompt
    assert prompt.index(boundary) < prompt.index(clarification) < prompt.index("IF l_mode IN ('A', 'B') THEN")
    assert "correlated scalar MIN or SUM lookups may be pre-aggregated by their existing correlation keys" in prompt
    assert "LEFT JOINed only into their immediate consumer while unrelated UNION ALL producers remain unchanged" in prompt


def test_sql_only_candidate_preflights_asta_awr_01_semantic_contract():
    llm = read("db/adb/asta_llm_pkg.sql")
    sql_only = llm[llm.index("FUNCTION generate_sql_only_tuning("):llm.index("END generate_sql_only_tuning;")]
    contract = "Before returning SQL, perform a semantic preflight against the original"
    assert contract in sql_only
    assert sql_only.index(contract) < sql_only.index("'DIAGNOSIS:'")
    assert "preserve all filter predicates, join conditions, outer-join null extension, row grain, and duplicate multiplicity" in sql_only
    assert "preserve GROUP BY and analytic PARTITION BY grains plus scalar-aggregate empty-input behavior" in sql_only
    assert "Trace every alias.column reference to a column projected by that exact source, CTE, or inline view" in sql_only
    assert "never invent a column, drop a UNION ALL branch, or replace an original expression with a placeholder" in sql_only
    assert "Return NO_REWRITE if any check cannot be satisfied." in sql_only


def test_sql_only_candidate_preserves_asta_awr_01_wildcard_scalar_aggregate_semantics():
    """Exact/wildcard lifting must retain one-row NULL behavior without fan-out."""
    llm = read("db/adb/asta_llm_pkg.sql")
    sql_only = llm[llm.index("FUNCTION generate_sql_only_tuning("):llm.index("END generate_sql_only_tuning;")]
    contract = "For a correlated MIN or SUM whose outer DECODE maps ''-'' to all inner COLOR_CD or SIZE_CD values"
    assert contract in sql_only
    assert sql_only.index(contract) < sql_only.index("'DIAGNOSIS:'")
    assert "separate exact and wildcard grains with GROUPING SETS and GROUPING flags" in sql_only
    assert "LEFT JOIN at most one aggregate row from the original immediate consumer" in sql_only
    assert "Preserve the scalar aggregate result of one NULL value when no inner row matches" in sql_only
    assert "never use a detail-grain wildcard join or COALESCE that changes this empty-input result" in sql_only
    assert "Return NO_REWRITE if these semantics cannot be preserved." in sql_only


def test_sql_only_long_candidate_limits_asta_awr_01_to_one_complete_rewrite():
    llm = read("db/adb/asta_llm_pkg.sql")
    sql_only = llm[llm.index("FUNCTION generate_sql_only_tuning("):llm.index("END generate_sql_only_tuning;")]
    boundary = "Long-SQL candidate boundary: rewrite exactly one repeated-access pattern completely across its producer and consumer blocks"
    assert "IF NVL(DBMS_LOB.GETLENGTH(p_sql), 0) >= 12000 THEN" in sql_only
    assert boundary in sql_only
    assert sql_only.index(boundary) < sql_only.index("'DIAGNOSIS:'")
    assert "Add every helper CTE, projected join key, GROUP BY expression, join, and correlated-reference change required for that one pattern" in sql_only
    assert "copying every unrelated CTE, UNION ALL branch, predicate, and select-list expression verbatim" in sql_only
    assert "Do not redesign the full statement" in sql_only
    assert "change any set-operation branch projection count" in sql_only
    assert "reference a grouping key after aggregation removed it" in sql_only
