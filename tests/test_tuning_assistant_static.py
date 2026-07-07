from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_tuning_assistant_extension_files_are_loaded_from_index():
    index = (ROOT / "static/index.html").read_text(encoding="utf-8")

    assert "/static/js/extensions/tuning_assistant.js" in index
    assert "/static/js/extensions/app_extensions.js" in index


def test_tuning_assistant_menu_is_registered_as_extension_not_hardcoded_route():
    ext = (ROOT / "static/js/extensions/app_extensions.js").read_text(encoding="utf-8")
    app = (ROOT / "static/js/app.js").read_text(encoding="utf-8")

    assert "AI SQL Tuning Assistant" in ext
    assert "tuning" in ext
    assert "window.AppExtensions" in app
    assert "Object.assign(ROUTES" in app


def test_tuning_assistant_view_has_asta_integration_placeholder():
    view = (ROOT / "static/js/extensions/tuning_assistant.js").read_text(encoding="utf-8")

    assert "window.Views.tuningAssistant" in view
    assert "ASTA" in view
    assert "/api/asta/analyze" in view


def test_tuning_assistant_uses_large_sql_editor_and_formats_before_report():
    index = (ROOT / "static/index.html").read_text(encoding="utf-8")
    view = (ROOT / "static/js/extensions/tuning_assistant.js").read_text(encoding="utf-8")

    assert "/static/vendor/sql-formatter/15.6.9/sql-formatter.min.js" in index
    assert "tuning-line-numbers" in view
    assert "formatSql(sql)" in view
    assert 'window.sqlFormatter.format(source' in view
    assert 'language: "plsql"' in view
    assert 'logicalOperatorNewline: "before"' in view
    assert "preserving the original SQL" in view
    assert "id=\"asta-sql\"" in view
    assert "SQL Formatting" in view
    assert "height: clamp(520px" in view
    assert "tuning-grid" in view


def test_tuning_assistant_header_text_removed_and_has_reset_button():
    view = (ROOT / "static/js/extensions/tuning_assistant.js").read_text(encoding="utf-8")

    assert "SQL을 넓은 에디터에 입력하면 먼저 읽기 좋은 SQL format" not in view
    assert "Format → Report" not in view
    assert "id=\"asta-reset" in view
    assert "신규분석(초기화)" in view
    assert "id=\"asta-run" in view
    assert "AI 분석 실행" in view
    assert "튜닝 보고서" not in view
    assert "튜닝보고서" not in view
    assert "id=\"asta-current-progress\"" in view
    assert "현재 진행" in view
    assert "id=\"asta-jump-progress" not in view
    assert "resetWorkspace" in view


def test_tuning_assistant_calls_astA_api_with_detailed_report_fallbacks():
    view = (ROOT / "static/js/extensions/tuning_assistant.js").read_text(encoding="utf-8")

    assert "api\\/asta" in view
    assert "source_db_id" in view
    assert "source_db_link" not in view
    assert "source_schema" not in view
    assert "id=\"asta-source-id\"" not in view
    assert "Endpoint 저장" not in view
    assert "ASTA Analyze URL" not in view
    assert "use_llm" in view
    assert "detailed_report_markdown" in view
    assert "pollRunProgress" in view
    assert "id=\"asta-tuning-notes\"" in view
    assert "tuning_context" in view
    assert "user_notes" in view
    assert "참고사항" in view
    assert "tuning-spinner" in view
    assert "현재 진행" in view
    assert "원본 SQL 실행 정보 수집" in view
    assert "원본 SQL 분석: 원본 SQL/XPLAN/metrics" not in view
    assert "progress polling timeout" not in view
    assert "const maxAttempts = 2400" in view
    assert "진행 상태 확인 시간이 초과되었습니다" in view
    assert "AI 분석이 종료되었습니다" in view
    assert "const current = isOverallComplete ? null" in view
    assert "!isOverallComplete &&" in view
    assert "tuning-current-progress" in view
    assert 'class="tuning-progress-drawer" hidden' in view
    assert "steps.map((step) => renderProgressDetailStep(step, isComplete))" in view
    assert "완료 단계" not in view
    assert '["READY", "IDLE", "PENDING"].includes(overall)' in view




def test_tuning_assistant_reveals_hidden_sql_only_mode_from_last_assistant_t():
    view = (ROOT / "static/js/extensions/tuning_assistant.js").read_text(encoding="utf-8")

    assert "asta-sql-only-llm" in view
    assert 'id="asta-secret-trigger"' in view
    assert 'aria-label="Assistant 마지막 t"' in view
    assert 'getElementById("asta-secret-trigger").addEventListener("click"' in view
    assert "ctrlKey && event.altKey" not in view
    assert "llm-sql-only" in view
    assert "SQL 텍스트만 LLM으로 전송 중" in view
    assert "Oracle Database 기준으로 SQL 튜닝을 요청합니다." in view
    assert "Oracle 옵티마이저 관점" in view
    assert "SELECT/WITH 단일문" in view
    assert "oracleSqlOnlyPrompt" in view
    assert "user_prompt: oracleSqlOnlyPrompt" in view
    assert "SQL_ONLY_LLM" in view
    assert "FASTAPI_SQL_ONLY_LLM" not in view  # backend-only marker


def test_tuning_assistant_progress_shows_total_elapsed_time():
    view = (ROOT / "static/js/extensions/tuning_assistant.js").read_text(encoding="utf-8")

    assert "function totalElapsedMs(progress, steps, isComplete)" in view
    assert "elapsed_total_sec" in view
    assert "progress?.created_at" in view
    assert "전체 ${formatDuration(totalElapsed)}" in view
    assert "tuning-current-total" in view
    assert "현재 진행 단계와 전체 수행 시간을 표시합니다" in view


def test_tuning_assistant_profiles_are_loaded_dynamically():
    view = (ROOT / "static/js/extensions/tuning_assistant.js").read_text(encoding="utf-8")

    assert "fetchJson(\"/api/asta/profiles\")" in view
    assert "ASTA_GEMINI_PROFILE" in view
    assert "toUpperCase().startsWith(\"ASTA\")" in view
    assert "const DEFAULT_AI_PROFILE = \"ASTA_GROK_REASONING_PROFILE\"" in view
    assert "const preferredProfile = astaProfiles.find((profile) => profile.name === DEFAULT_AI_PROFILE)" in view
    assert "profile.name === preferredProfile.name" in view
    assert "profile.isDefault || profile.name === DEFAULT_AI_PROFILE" not in view


def test_tuning_assistant_persists_detailed_error_in_result_panel():
    view = (ROOT / "static/js/extensions/tuning_assistant.js").read_text(encoding="utf-8")

    assert "renderError(result, err)" in view
    assert "기술 정보 (문의 시 전달)" in view
    assert "문의 정보 복사" in view
    assert "window.__astaLastError" in view
    assert "err.payload" in view
    assert "조회 endpoint" in view
    assert "ASTA 오류 코드" in view


def test_tuning_assistant_treats_ords_not_found_body_as_copyable_error():
    view = (ROOT / "static/js/extensions/tuning_assistant.js").read_text(encoding="utf-8")

    assert 'bodyStatus === "NOT_FOUND"' in view
    assert 'errorCode === "RUN_NOT_FOUND"' in view
    assert 'errorCode === "REPORT_NOT_FOUND"' in view
    assert "err.queriedRunId = decodeURIComponent" in view


def test_tuning_assistant_exposes_customer_and_fourteen_verified_samples():
    view = (ROOT / "static/js/extensions/tuning_assistant.js").read_text(encoding="utf-8")

    assert "ASTA_SAMPLE_SQLS" in view
    assert view.count('id: "asta-awr-') == 15
    assert "7rcw6d3us86r7" in view
    assert "SESL0640.selectList" in view
    assert 'id: "asta-ui-' not in view
    assert 'id: "asta-batch-' not in view



def test_tuning_assistant_result_report_has_large_scroll_container():
    view = (ROOT / "static/js/extensions/tuning_assistant.js").read_text(encoding="utf-8")

    assert "tuning-report-scroll" in view
    assert "asta-report-scroll" in view
    assert "asta-report-bottom" not in view
    assert "asta-report-top" not in view
    assert "scrollTo({ top: reportScroller.scrollHeight" not in view
    assert "height:min(74vh, 900px)" in view
    assert "resize:vertical" in view
    assert "target.scrollIntoView" in view


def test_tuning_assistant_exposes_only_current_verified_sample_patterns():
    view = (ROOT / "static/js/extensions/tuning_assistant.js").read_text(encoding="utf-8")

    assert view.count('id: "asta-awr-') == 15
    assert "SESL0640.selectList" in view
    assert view.count('pattern: "') == 14
    for pattern in ("CORRELATED_EXISTS_COUNT", "CORRELATED_NOT_EXISTS", "CORRELATED_EXCLUSION_KEYS",
                    "DUPLICATE_CTE_SCAN", "FUNCTION_PREDICATE", "REDUNDANT_DISTINCT_GROUP",
                    "UNION_DUPLICATE_ELIMINATION", "COMPOSITE_EXISTS_RESCAN", "DUAL_EXISTS_CHAIN",
                    "SEMI_ANTI_MIXED", "DUPLICATE_INLINE_AGGREGATE", "EXISTS_NOT_EXISTS_CHAIN",
                    "REPEATED_GROUP_BY_CTE", "REDUNDANT_FUNCTION_FILTER"):
        assert f'pattern: "{pattern}"' in view


def test_tuning_assistant_removes_only_a_trailing_sql_terminator_before_submit():
    view = (ROOT / "static/js/extensions/tuning_assistant.js").read_text(encoding="utf-8")

    helper = view[view.index("function stripTrailingSqlTerminator"):view.index("function formatDuration")]
    assert 'text.endsWith(";")' in helper
    assert "text.slice(0, -1).trimEnd()" in helper
    assert view.count("const sql = stripTrailingSqlTerminator(sqlInput.value);") == 2


def test_vector_case_markup_is_interactive_without_trusting_report_html():
    view = (ROOT / "static/js/extensions/tuning_assistant.js").read_text(encoding="utf-8")

    assert "function renderTrustedVectorBlocks" in view
    assert 'document.createElement("details")' in view
    assert 'document.createElement("summary")' in view
    assert "code.textContent = decodeVectorEntities" in view
    assert "text.textContent = plainText" in view
    assert 'link.target = "_blank"' in view
    assert 'link.rel = "noopener"' in view
    assert "^\\/api\\/asta\\/runs\\/[A-Za-z0-9][A-Za-z0-9_.:-]*\\/report(?:\\/view)?$" in view
    assert "safeReportPath.test(match[2])" in view
    assert '`${match[2]}/view`' in view
    assert "javascript:" not in view[view.index("function renderTrustedVectorBlocks"):view.index("API 오류 객체")]
    assert '<pre id="asta-report-scroll"' not in view
    assert "${escapeHtml(window.__astaLastReport.report)}" not in view


def test_tuning_assistant_sample_sql_details_are_preserved():
    view = (ROOT / "static/js/extensions/tuning_assistant.js").read_text(encoding="utf-8")

    expected_sql_ids = ["7rcw6d3us86r7"]
    assert view.count('id: "asta-awr-') == 15
    for sql_id in expected_sql_ids:
        assert sql_id in view
    assert ":v_" not in view
    assert "FOR UPDATE NOWAIT" not in view.upper()
    assert "FROM DSNT.TGP_STYLE_M A" in view
    assert "CONF_CSM_AMT * 0.6 AS CONF_CSM_AMT" in view

def test_asta_error_toast_stays_visible_longer():
    view = (ROOT / "static/js/extensions/tuning_assistant.js").read_text(encoding="utf-8")

    assert "friendlyAstaIssue" in view
    assert "기술 정보 (문의 시 전달)" in view
    assert "15000" in view


def test_tuning_assistant_keeps_async_runs_running_until_poll_completion():
    view = (ROOT / "static/js/extensions/tuning_assistant.js").read_text(encoding="utf-8")

    running_check = 'data?.run_id && ["RUNNING", "QUEUED"].includes(String(data?.status || "").toUpperCase())'
    assert running_check in view
    async_pos = view.index(running_check)
    poll_pos = view.index("await pollRunProgress(baseUrl, data.run_id, progressTarget, result)")
    premature_progress_pos = view.index("finalProgress = await fetchJson")
    assert async_pos < poll_pos < premature_progress_pos
    assert "sqltune_time_limit" in view
    assert "hasAuthoritativeInlineProgress" in view
    assert "SOURCE_DIRECT_FALLBACK" in view
    assert "CONTROLLED_FALLBACK" in view
    assert "data?.run_id && !hasAuthoritativeInlineProgress" in view
    assert "sqltune_timeout_seconds" not in view


def test_tuning_assistant_disables_advisor_in_top_level_and_options_payload():
    view = (ROOT / "static/js/extensions/tuning_assistant.js").read_text(encoding="utf-8")
    start = view.index("const data = await fetchJson(url, {")
    end = view.index('if (["FAILED", "ERROR"].includes', start)
    payload = view[start:end]
    options_pos = payload.index("options: {")
    top_level = payload[:options_pos]
    options = payload[options_pos:]

    assert "run_advisor: false" in top_level
    assert "use_sqltune: false" in top_level
    assert "run_advisor: false" in options
    assert "use_sqltune: false" in options
    assert "run_advisor: true" not in payload
    assert "use_sqltune: true" not in payload


def test_tuning_assistant_hides_noninteractive_advisor_off_status():
    view = (ROOT / "static/js/extensions/tuning_assistant.js").read_text(encoding="utf-8")

    assert 'id="asta-advisor-status"' not in view
    assert "Oracle 튜닝 권고: 사용 안 함" not in view
    assert 'aria-label="Oracle 튜닝 권고 사용 상태"' not in view
    assert ".tuning-advisor-state" not in view


def test_tuning_assistant_has_iphone_mini_portrait_and_landscape_css():
    view = (ROOT / "static/js/extensions/tuning_assistant.js").read_text(encoding="utf-8")
    layout = (ROOT / "static/css/layout.css").read_text(encoding="utf-8")

    assert "max-width: 390px" in view
    assert "orientation: portrait" in view
    assert "max-height: 430px" in view
    assert "orientation: landscape" in view
    assert "100dvh" in view
    assert "contain:paint" not in view
    assert ".tuning-line-numbers { display:none; }" in view
    assert "height: 60dvh" in view
    assert "order:-1" not in view
    assert "grid-template-columns: 1fr; gap: 8px;" in view
    assert "max-width: 390px" in layout
    assert "max-height: 430px" in layout


def test_global_side_nav_can_be_collapsed():
    index = (ROOT / "static/index.html").read_text(encoding="utf-8")
    app = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    layout = (ROOT / "static/css/layout.css").read_text(encoding="utf-8")

    assert "id=\"nav-toggle\"" in index
    assert "NAV_COLLAPSED_KEY" in app
    assert "setNavCollapsed" in app
    assert "nav-collapsed" in layout


def test_tuning_assistant_logs_when_final_ords_progress_would_override_inline_fallback():
    view = (ROOT / "static/js/extensions/tuning_assistant.js").read_text(encoding="utf-8")

    assert "hasAuthoritativeInlineProgress" in view
    assert "console.warn" in view
    assert "asta-progress-stale-ords-suppressed" in view


def test_tuning_assistant_maps_new_11_stage_order_and_legacy_final_review():
    view = (ROOT / "static/js/extensions/tuning_assistant.js").read_text(encoding="utf-8")
    expected = ["REQUEST_RECEIVED", "ORDS_DISPATCH", "SQL_GUARD", "BEFORE_EVIDENCE",
                "SQL_TUNING_ADVISOR", "LLM_REWRITE", "AFTER_EVIDENCE",
                "BEFORE_AFTER_COMPARE", "VECTOR_KB", "FINAL_REPORT", "VECTOR_SAVE"]
    positions = [view.index(f'code: "{code}"') for code in expected]
    assert positions == sorted(positions)
    assert 'LLM_FINAL_REVIEW: 7' in view
    assert 'BEFORE_AFTER_COMPARE: 7' in view
    assert 'code: "LLM_FINAL_REVIEW"' not in view
