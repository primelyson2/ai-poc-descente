/** views/agent_history.js — 메뉴 [Select AI Test - Agent History]
 *
 * USER_AI_AGENT_TEAM_HISTORY 실행 내역을 읽기전용으로 조회한다.
 *   · 목록: 시작시각 / Team / 질문(첫 user 프롬프트) / 상태 / 소요ms / conversation_id
 *     백엔드: GET /api/agents/team-history (agents.py)
 *   · 행 클릭 → 상세 모달. AI Agent Team Test 의 "2. Team 실행 및 단계별 속도" 탭과 동일하게
 *     ① Thinking 과정 · ② 단계별 타임라인 · ③ 최종결과 & 로그 를 보여준다.
 *     - 상세 데이터: GET /api/agents/conversations/{conv_id}/timeline (기존 재사용)
 *     - 렌더: window.AgentTrace.{renderThinking,renderTimeline,renderOutput} (agent_test.js 노출)
 */
(function () {
  const nf = (n) => (n == null || n === "" ? "" : Number(n).toLocaleString());

  function errMsg(err, fallback) {
    const p = err && err.payload; const d = p && (p.detail || p.error);
    if (d) return typeof d === "string" ? d : (d.error || d.message || JSON.stringify(d));
    return (err && err.message) || fallback || "요청 실패";
  }

  async function render() {
    const main = document.getElementById("main");
    main.innerHTML = "";
    const title = document.createElement("div");
    title.className = "view-title";
    title.innerHTML = `<h1>Select AI Test - Agent History</h1>
      <span class="sub">AI Agent Team 실행 내역(USER_AI_AGENT_TEAM_HISTORY)을 조회합니다. 행을 클릭하면 단계별 상세가 표시됩니다.</span>`;
    main.appendChild(title);

    const panel = document.createElement("div");
    panel.className = "panel";
    panel.innerHTML = `
      <div class="panel-header"><h2>Agent 실행 내역 <span class="muted" style="font-size:var(--fs-sm);">USER_AI_AGENT_TEAM_HISTORY · 최신순 · 20건</span></h2>
        <button class="btn btn-ghost" id="ah-reload" type="button">↻ 새로고침</button>
      </div>
      <div class="panel-body stack">
        <div class="row" style="gap:12px; align-items:flex-end; flex-wrap:wrap;">
          <div class="stack-sm" style="flex:1; min-width:220px;"><label style="font-size:var(--fs-sm);">질문 검색 (LIKE, 대소문자 무시)</label>
            <input type="text" id="ah-q" placeholder="질문에 포함할 텍스트" style="width:100%;"></div>
          <div class="stack-sm"><label style="font-size:var(--fs-sm);">시작일시(≥)</label>
            <input type="datetime-local" id="ah-start" step="1"></div>
          <div class="stack-sm"><label style="font-size:var(--fs-sm);">종료일시(≤)</label>
            <input type="datetime-local" id="ah-end" step="1"></div>
          <div><button class="btn btn-primary" id="ah-search" type="button">조회</button></div>
          <div><button class="btn btn-ghost" id="ah-clear" type="button">초기화</button></div>
        </div>
        <div id="ah-list"></div>
      </div>`;
    main.appendChild(panel);

    panel.querySelector("#ah-reload").addEventListener("click", loadHistory);
    panel.querySelector("#ah-search").addEventListener("click", loadHistory);
    panel.querySelector("#ah-clear").addEventListener("click", () => {
      ["ah-q", "ah-start", "ah-end"].forEach((id) => { const el = document.getElementById(id); if (el) el.value = ""; });
      loadHistory();
    });
    // 질문 검색창에서 Enter → 조회
    panel.querySelector("#ah-q").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); loadHistory(); } });
    loadHistory();
  }

  async function loadHistory() {
    const host = document.getElementById("ah-list");
    if (!host) return;
    const val = (id) => (document.getElementById(id)?.value || "").trim();
    const qs = new URLSearchParams({ limit: "20" });
    if (val("ah-q")) qs.set("question", val("ah-q"));
    if (val("ah-start")) qs.set("start", val("ah-start"));
    if (val("ah-end")) qs.set("end", val("ah-end"));
    host.innerHTML = '<div class="empty-state"><span class="spinner"></span> 조회 중...</div>';
    let rows;
    try { rows = await window.API.get("/api/agents/team-history?" + qs.toString()); }
    catch (e) { host.innerHTML = `<div class="empty-state muted">${window.escapeHtml(errMsg(e, "실행 내역 조회 실패"))}</div>`; return; }
    host.innerHTML = "";
    host.appendChild(window.SimpleTable.create(
      [
        { key: "start_date", label: "시작시각", headerAlign: "center" },
        { key: "team_name", label: "Team" },
        { key: "question", label: "질문" },
        { key: "state", label: "상태", headerAlign: "center", align: "center" },
        { key: "elapsed_ms", label: "소요(ms)", headerAlign: "center", align: "right", format: nf },
        { key: "conversation_id", label: "conversation_id" },
      ],
      rows || [],
      { className: "keep-case", onRowClick: (row) => showTraceModal(row),
        emptyText: "조회된 실행 내역이 없습니다." }
    ));
  }

  // 행 클릭 → 상세 모달. Tab2 의 3영역을 재사용하기 위해 동일 ID 컨테이너를 만든다.
  async function showTraceModal(row) {
    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    backdrop.innerHTML = `
      <div class="modal" style="width:1080px; max-width:96vw;">
        <div class="modal-header">
          <h2>Agent 실행 상세 <span class="muted" style="font-size:var(--fs-sm);">${window.escapeHtml(row.team_name || "")} · 읽기전용</span></h2>
          <button class="btn btn-ghost" id="ah-close">✕</button>
        </div>
        <div class="modal-body stack" style="max-height:80vh; overflow:auto;">
          <div class="muted" style="font-size:var(--fs-sm); font-family:var(--font-mono);">
            <span id="at-conv-id"></span>
          </div>
          <div class="panel">
            <div class="panel-header">
              <h2>Thinking 과정 <span id="at-think-count" class="muted" style="font-size:var(--fs-sm);"></span></h2>
              <div class="row" style="gap:var(--space-3);">
                <button class="btn btn-ghost" id="ah-think-suggest" disabled>AI 추천</button>
                <button class="btn btn-ghost" id="ah-think-analyze" disabled>Thinking과정분석</button>
              </div>
            </div>
            <div class="panel-body"><div id="at-thinking"></div></div>
          </div>
          <div class="panel">
            <div class="panel-header"><h2>단계별 타임라인</h2></div>
            <div class="panel-body"><div id="at-timeline"></div></div>
          </div>
          <div class="panel">
            <div class="panel-header"><h2>최종 결과 &amp; 로그</h2></div>
            <div class="panel-body"><div id="at-output"></div></div>
          </div>
          <div class="row end">
            <button class="btn btn-ghost" id="ah-close2">닫기</button>
          </div>
        </div>
      </div>`;
    const close = () => { backdrop.remove(); document.removeEventListener("keydown", onKey); };
    const onKey = (e) => { if (e.key === "Escape") close(); };
    // 바깥 클릭으로는 닫지 않음 — X/닫기/ESC 로만.
    backdrop.querySelector("#ah-close").addEventListener("click", close);
    backdrop.querySelector("#ah-close2").addEventListener("click", close);
    document.addEventListener("keydown", onKey);
    document.body.appendChild(backdrop);

    const convId = row.conversation_id;
    const convEl = backdrop.querySelector("#at-conv-id");
    if (!convId) { convEl.textContent = "conversation_id 없음 — 상세를 조회할 수 없습니다."; return; }
    convEl.innerHTML = '<span class="spinner"></span> 조회 중...';

    let data;
    try { data = await window.API.get(`/api/agents/conversations/${encodeURIComponent(convId)}/timeline`); }
    catch (e) {
      if (backdrop.isConnected) convEl.textContent = "상세 조회 실패: " + errMsg(e, "");
      return;
    }
    if (!backdrop.isConnected) return;
    if (!window.AgentTrace) { convEl.textContent = "AgentTrace 렌더러를 찾을 수 없습니다."; return; }

    const timeline = data.timeline || [];
    const total = timeline.length ? Math.max(...timeline.map((t) => t.end_ms || 0)) : 0;
    const result = deriveResult(data.raw_logs || {});

    convEl.textContent = `conversation_id: ${convId}` + (total ? `  ·  total ${nf(total)} ms` : "");
    window.AgentTrace.renderThinking(data.thinking);
    window.AgentTrace.renderTimeline(timeline, total);
    window.AgentTrace.renderOutput({ result, raw_logs: data.raw_logs });

    // Thinking 헤더 [AI 추천]·[Thinking과정분석] 버튼 배선 — AI Agent Team Test 2탭과 동일 동작.
    // team 이름은 History 행에, thinking 텍스트는 조회한 thinking.rows 에서 만든다.
    const teamName = row.team_name || "";
    const thinkingRows = (data.thinking && data.thinking.rows) || [];
    const thinkingText = thinkingRows.length ? window.AgentTrace.buildThinkingText(thinkingRows) : "";
    const suggestBtn = backdrop.querySelector("#ah-think-suggest");
    const analyzeBtn = backdrop.querySelector("#ah-think-analyze");
    if (suggestBtn && analyzeBtn) {
      const ready = !!(teamName && thinkingText);
      suggestBtn.disabled = !ready;
      analyzeBtn.disabled = !ready;
      suggestBtn.addEventListener("click", () => window.AgentTrace.openAgentSuggestModal(teamName, thinkingText));
      analyzeBtn.addEventListener("click", () => window.AgentTrace.openThinkingAnalyzeModal(teamName, thinkingText));
    }
  }

  // timeline 엔드포인트엔 최종결과(result)가 없으므로 raw_logs 에서 파생한다.
  //  1순위: conversation_prompts 중 role 이 assistant 인 마지막 항목
  //  2순위: task_history 마지막 output
  //  없으면 빈 문자열(renderOutput 이 처리)
  function deriveResult(rawLogs) {
    const convo = rawLogs.conversation_prompts || [];
    for (let i = convo.length - 1; i >= 0; i--) {
      const role = String(convo[i].role || "");
      if (role.startsWith("assistant") && convo[i].content) return String(convo[i].content);
    }
    const tasks = rawLogs.task_history || [];
    for (let i = tasks.length - 1; i >= 0; i--) {
      if (tasks[i].output) return String(tasks[i].output);
    }
    return "";
  }

  window.Views = window.Views || {};
  window.Views.agentHistory = render;
})();
