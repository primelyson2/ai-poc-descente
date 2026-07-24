/** views/history2.js — 메뉴 [Select AI Test - History2]
 *
 * SELECT AI 대화 이력(USER_CLOUD_AI_CONVERSATION_PROMPTS)을 읽기전용 조회한다.
 * conversation 으로 실행된 질의(prompt)·응답(prompt_response)이 영구 저장된 것.
 *   · 목록: created / profile_name / prompt_action / conversation_id / prompt(질의)
 *   · 필터: 시작·종료일시 + 텍스트(prompt/응답 LIKE) + Profile + Action
 *   · 행 클릭 → 읽기전용 상세 모달(질의·응답 전체 + 복사)
 *   · 백엔드: GET /api/history2/prompts, /api/history2/facets (app/routers/history2.py)
 */
(function () {
  function errMsg(err, fallback) {
    const p = err && err.payload; const d = p && (p.detail || p.error);
    if (d) return typeof d === "string" ? d : (d.error || d.message || JSON.stringify(d));
    return (err && err.message) || fallback || "요청 실패";
  }
  function divFromHtml(html) { const d = document.createElement("div"); d.innerHTML = html; return d.firstElementChild || d; }

  async function render() {
    const main = document.getElementById("main");
    main.innerHTML = "";
    const title = document.createElement("div");
    title.className = "view-title";
    title.innerHTML = `<h1>Select AI Test - History2</h1>
      <span class="sub">USER_CLOUD_AI_CONVERSATION_PROMPTS (SELECT AI 대화 이력) 을 조회합니다.</span>`;
    main.appendChild(title);

    // 보관기간 안내
    const note = document.createElement("div");
    note.style.cssText = "margin:8px 0 12px; padding:10px 14px; background:var(--surface-alt); border-left:3px solid var(--primary); border-radius:var(--radius-md); font-size:var(--fs-sm); color:var(--text-muted);";
    note.innerHTML = `
      <strong>보관기간 안내</strong> — 이 이력은 대화(conversation) 단위로 <strong>기본 7일 보관 후 자동 삭제</strong>됩니다.
      장기 보관하려면 대화 생성 시 보관일수를 지정하세요:
      <code>DBMS_CLOUD_AI.CREATE_CONVERSATION(attributes =&gt; '{"retention_days":365}')</code>.
      이미 만든 대화는 <code>UPDATE_CONVERSATION</code> 으로 변경 가능.`;
    main.appendChild(note);

    const panel = document.createElement("div");
    panel.className = "panel";
    panel.innerHTML = `
      <div class="panel-header"><h2>대화 이력 <span class="muted" style="font-size:var(--fs-sm);">USER_CLOUD_AI_CONVERSATION_PROMPTS · 최신순</span></h2>
        <button class="btn btn-ghost" id="h2-reload" type="button">↻ 새로고침</button>
      </div>
      <div class="panel-body stack">
        <div class="row" style="gap:12px; align-items:flex-end; flex-wrap:wrap;">
          <div class="stack-sm"><label style="font-size:var(--fs-sm);">시작일시</label>
            <input type="datetime-local" id="h2-start" step="1"></div>
          <div class="stack-sm"><label style="font-size:var(--fs-sm);">종료일시</label>
            <input type="datetime-local" id="h2-end" step="1"></div>
          <div class="stack-sm"><label style="font-size:var(--fs-sm);">Profile</label>
            <select id="h2-profile" style="min-width:140px;"><option value="">(전체)</option></select></div>
          <div class="stack-sm"><label style="font-size:var(--fs-sm);">Action</label>
            <select id="h2-action" style="min-width:120px;"><option value="">(전체)</option></select></div>
          <div class="stack-sm" style="flex:1; min-width:200px;"><label style="font-size:var(--fs-sm);">텍스트 검색 (질의·응답 LIKE, 대소문자 무시)</label>
            <input type="text" id="h2-text" placeholder="포함할 텍스트" style="width:100%;"></div>
          <div><button class="btn btn-primary" id="h2-search" type="button">조회</button></div>
          <div><button class="btn btn-ghost" id="h2-clear" type="button">초기화</button></div>
        </div>
        <div id="h2-list"></div>
      </div>`;
    main.appendChild(panel);

    panel.querySelector("#h2-reload").addEventListener("click", loadHistory);
    panel.querySelector("#h2-search").addEventListener("click", loadHistory);
    panel.querySelector("#h2-clear").addEventListener("click", () => {
      ["h2-start", "h2-end", "h2-text"].forEach((id) => { const el = document.getElementById(id); if (el) el.value = ""; });
      const pf = document.getElementById("h2-profile"); if (pf) pf.value = "";
      const ac = document.getElementById("h2-action"); if (ac) ac.value = "";
      loadHistory();
    });
    panel.querySelector("#h2-text").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); loadHistory(); } });

    await loadFacets();
    loadHistory();
  }

  async function loadFacets() {
    try {
      const f = await window.API.get("/api/history2/facets");
      const fill = (id, arr) => {
        const sel = document.getElementById(id);
        if (!sel) return;
        (arr || []).forEach((v) => {
          const o = document.createElement("option");
          o.value = v; o.textContent = v;
          sel.appendChild(o);
        });
      };
      fill("h2-profile", f.profiles);
      fill("h2-action", f.actions);
    } catch (_) { /* facets 실패해도 조회는 가능 — 드롭다운만 비어있음 */ }
  }

  async function loadHistory() {
    const host = document.getElementById("h2-list");
    if (!host) return;
    const val = (id) => (document.getElementById(id)?.value || "").trim();
    const qs = new URLSearchParams({ limit: "20" });
    if (val("h2-start")) qs.set("start", val("h2-start"));
    if (val("h2-end")) qs.set("end", val("h2-end"));
    if (val("h2-text")) qs.set("text", val("h2-text"));
    if (val("h2-profile")) qs.set("profile", val("h2-profile"));
    if (val("h2-action")) qs.set("action", val("h2-action"));
    const url = "/api/history2/prompts?" + qs.toString();
    host.innerHTML = '<div class="empty-state"><span class="spinner"></span> 조회 중...</div>';
    let rows;
    try { rows = await window.API.get(url); }
    catch (e) { host.innerHTML = `<div class="empty-state muted">${window.escapeHtml(errMsg(e, "대화 이력 조회 실패"))}</div>`; return; }
    host.innerHTML = "";
    host.appendChild(window.SimpleTable.create(
      [
        { key: "created", label: "생성일시", headerAlign: "center" },
        { key: "profile_name", label: "Profile" },
        { key: "prompt_action", label: "Action", headerAlign: "center", align: "center" },
        { key: "conversation_id", label: "conversation_id" },
        { key: "prompt", label: "질의(prompt)" },
        { key: "_eval", label: "평가", headerAlign: "center", align: "center", format: (_v, row) => buildEvalBtn(row) },
      ],
      rows || [],
      { className: "keep-case", onRowClick: (row) => showDetailModal(row),
        emptyText: "조회 조건에 해당하는 대화 이력이 없습니다." }
    ));
  }

  // ── 읽기전용 상세 모달 (질의/응답 + 복사) ──
  function showDetailModal(row) {
    const roField = (label, value, copyId) => `
      <div class="stack-sm">
        <div class="row" style="justify-content:space-between; align-items:center; gap:8px;">
          <label style="font-size:var(--fs-sm); color:var(--text-muted);">${label}</label>
          ${copyId ? `<button class="btn btn-ghost" data-copy="${copyId}" type="button" style="padding:2px 10px; font-size:var(--fs-sm);">복사</button>` : ""}
        </div>
        <pre style="white-space:pre-wrap; word-break:break-word; margin:0; font-family:var(--font-mono); font-size:var(--fs-sm); background:var(--surface-alt); padding:var(--space-2) var(--space-3); border-radius:var(--radius-md); max-height:280px; overflow:auto;">${window.escapeHtml(value != null && String(value).trim() !== "" ? String(value) : "—")}</pre>
      </div>`;

    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    backdrop.innerHTML = `
      <div class="modal" style="width:900px; max-width:95vw;">
        <div class="modal-header">
          <h2>대화 이력 상세 <span class="muted" style="font-size:var(--fs-sm);">USER_CLOUD_AI_CONVERSATION_PROMPTS · 읽기전용</span></h2>
          <button class="btn btn-ghost" id="h2d-close">✕</button>
        </div>
        <div class="modal-body stack">
          <div class="row" style="gap:12px;">
            <div style="flex:1; min-width:0;">${roField("생성일시", row.created)}</div>
            <div style="flex:1; min-width:0;">${roField("Profile", row.profile_name)}</div>
            <div style="flex:1; min-width:0;">${roField("Action", row.prompt_action)}</div>
          </div>
          <div class="row" style="gap:12px;">
            <div style="flex:1; min-width:0;">${roField("conversation_id", row.conversation_id)}</div>
            <div style="flex:1; min-width:0;">${roField("conversation_title", row.conversation_title)}</div>
          </div>
          ${roField("질의 (prompt)", row.prompt, "prompt")}
          ${roField("응답 (prompt_response)", row.prompt_response, "resp")}
          <div class="row end">
            <button class="btn btn-ghost" id="h2d-close2">닫기</button>
          </div>
        </div>
      </div>`;
    const close = () => { backdrop.remove(); document.removeEventListener("keydown", onKey); };
    const onKey = (e) => { if (e.key === "Escape") close(); };
    backdrop.querySelector("#h2d-close").addEventListener("click", close);
    backdrop.querySelector("#h2d-close2").addEventListener("click", close);
    const copyMap = {
      prompt: row.prompt == null ? "" : String(row.prompt),
      resp: row.prompt_response == null ? "" : String(row.prompt_response),
    };
    backdrop.querySelectorAll("[data-copy]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try { await navigator.clipboard.writeText(copyMap[btn.dataset.copy] || ""); window.Toast.show("클립보드에 복사됨", "success"); }
        catch (_) { window.Toast.show("복사 실패", "error"); }
      });
    });
    document.addEventListener("keydown", onKey);
    document.body.appendChild(backdrop);
  }

  // ── 평가(LLM-as-judge) — History 화면과 동일 로직(/api/history/evaluate 재사용) ──
  function buildEvalBtn(row) {
    const btn = document.createElement("button");
    btn.className = "btn btn-primary";
    btn.textContent = "평가";
    btn.style.cssText = "padding:4px 12px; font-size:var(--fs-sm);";
    btn.addEventListener("click", (e) => { e.stopPropagation(); showEvaluateModal(row); });
    return btn;
  }
  function mkBadge(verdict) {
    const bg = verdict === "적정" ? "#1a7f5a" : verdict === "비적정" ? "#C74634"
      : verdict === "판정불가" ? "#b8860b" : "#8a8f98";
    const s = document.createElement("span");
    s.textContent = verdict || "—";
    s.style.cssText = `display:inline-block;font-size:12px;font-weight:700;padding:3px 12px;border-radius:999px;color:#fff;background:${bg}`;
    return s;
  }
  async function showEvaluateModal(row) {
    const roField = (label, value, copyId) => `
      <div class="stack-sm">
        <div class="row" style="justify-content:space-between; align-items:center; gap:8px;">
          <label style="font-size:var(--fs-sm); color:var(--text-muted);">${label}</label>
          ${copyId ? `<button class="btn btn-ghost" data-copy="${copyId}" type="button" style="padding:2px 10px; font-size:var(--fs-sm);">복사</button>` : ""}
        </div>
        <pre style="white-space:pre-wrap; word-break:break-word; margin:0; font-family:var(--font-mono); font-size:var(--fs-sm); background:var(--surface-alt); padding:var(--space-2) var(--space-3); border-radius:var(--radius-md); max-height:200px; overflow:auto;">${window.escapeHtml(value != null && String(value).trim() !== "" ? String(value) : "—")}</pre>
      </div>`;

    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    backdrop.innerHTML = `
      <div class="modal" style="width:900px; max-width:95vw;">
        <div class="modal-header">
          <h2>SQL 평가 <span class="muted" style="font-size:var(--fs-sm);">생성 SQL 품질 심사 (LLM-as-judge)</span></h2>
          <button class="btn btn-ghost" id="ev-close">✕</button>
        </div>
        <div class="modal-body stack">
          ${roField("질의 (prompt)", row.prompt, "prompt")}
          ${roField("응답 (prompt_response)", row.prompt_response, "resp")}
          <div class="row" style="gap:12px; align-items:flex-end; flex-wrap:wrap;">
            <div class="stack-sm" style="flex:0 0 280px;">
              <label style="font-size:var(--fs-sm);">평가 수행 AI Profile <span class="muted" style="font-size:var(--fs-sm);">(이 행의 Profile)</span></label>
              <input type="text" id="ev-profile" value="${window.escapeAttr(row.profile_name || "")}" readonly style="background:var(--surface-alt);">
            </div>
            <div><button class="btn btn-primary" id="ev-run" type="button">평가 실행</button></div>
          </div>
          <div id="ev-out"></div>
          <div class="row end"><button class="btn btn-ghost" id="ev-close2">닫기</button></div>
        </div>
      </div>`;

    const close = () => { backdrop.remove(); document.removeEventListener("keydown", onKey); };
    const onKey = (e) => { if (e.key === "Escape") close(); };
    backdrop.querySelector("#ev-close").addEventListener("click", close);
    backdrop.querySelector("#ev-close2").addEventListener("click", close);
    document.addEventListener("keydown", onKey);

    const copyMap = { prompt: row.prompt == null ? "" : String(row.prompt), resp: row.prompt_response == null ? "" : String(row.prompt_response) };
    backdrop.querySelectorAll("[data-copy]").forEach((btn) => btn.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(copyMap[btn.dataset.copy] || ""); window.Toast.show("클립보드에 복사됨", "success"); }
      catch (_) { window.Toast.show("복사 실패", "error"); }
    }));

    document.body.appendChild(backdrop);

    // 평가 Profile 은 이 행의 Profile(row.profile_name)을 그대로 사용한다.
    const out = backdrop.querySelector("#ev-out");
    backdrop.querySelector("#ev-run").addEventListener("click", async () => {
      const profile = (row.profile_name || "").trim();
      if (!profile) { window.Toast.show("이 행에 Profile 정보가 없어 평가할 수 없습니다", "warn"); return; }
      const btn = backdrop.querySelector("#ev-run"); btn.disabled = true; const old = btn.textContent;
      btn.innerHTML = '<span class="spinner"></span> 평가 중...';
      out.innerHTML = '<div class="empty-state"><span class="spinner"></span> 심사 중...</div>';
      let res;
      try { res = await window.API.post("/api/history/evaluate", { profile, prompt: row.prompt, sql: row.prompt_response }); }
      catch (e) { out.innerHTML = `<div class="empty-state muted">${window.escapeHtml(errMsg(e, "평가 실패"))}</div>`; btn.disabled = false; btn.textContent = old; return; }
      out.innerHTML = "";
      const head = document.createElement("div");
      head.className = "row"; head.style.cssText = "gap:12px; align-items:center; margin:4px 0 8px;";
      const lbl = document.createElement("span"); lbl.style.cssText = "font-weight:600;"; lbl.textContent = "판정:";
      head.appendChild(lbl); head.appendChild(mkBadge(res.verdict));
      const ctx = document.createElement("span");
      ctx.className = "muted"; ctx.style.cssText = "font-size:var(--fs-sm);";
      ctx.textContent = res.schema_included ? "· 스키마 컨텍스트(comment/annotation) 포함됨" : "· 스키마 컨텍스트 미포함(질문 원문만)";
      head.appendChild(ctx);
      out.appendChild(head);
      out.appendChild(divFromHtml(`
        <div class="stack-sm">
          <label style="font-size:var(--fs-sm); color:var(--text-muted);">사유</label>
          <pre style="white-space:pre-wrap; word-break:break-word; margin:0; font-family:var(--font-mono); font-size:var(--fs-sm); background:var(--surface-alt); padding:var(--space-2) var(--space-3); border-radius:var(--radius-md); max-height:220px; overflow:auto;">${window.escapeHtml((res.reason || "").trim() || "—")}</pre>
        </div>`));
      if (res.error) out.appendChild(divFromHtml(`<div class="empty-state muted">오류: ${window.escapeHtml(res.error)}</div>`));
      out.appendChild(divFromHtml(`
        <details style="margin-top:8px;">
          <summary style="cursor:pointer; font-size:var(--fs-sm); color:var(--text-muted);">심사 프롬프트(스키마 컨텍스트 포함) 보기</summary>
          <div class="stack-sm" style="margin-top:8px;">
            <label style="font-size:var(--fs-sm); color:var(--text-muted);">eval_prompt</label>
            <pre style="white-space:pre-wrap; word-break:break-word; margin:0; font-family:var(--font-mono); font-size:var(--fs-sm); background:var(--surface-alt); padding:var(--space-2) var(--space-3); border-radius:var(--radius-md); max-height:220px; overflow:auto;">${window.escapeHtml(res.eval_prompt || "—")}</pre>
          </div>
        </details>`));
      btn.disabled = false; btn.textContent = old;
    });
  }

  window.Views = window.Views || {};
  window.Views.history2 = render;
})();
