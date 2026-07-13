/** views/history.js — 메뉴 [Select AI Test - History]
 *
 * SELECT AI 실행 내역(v$mapped_sql)을 읽기전용으로 조회한다.
 * AI Profile Test 의 [Feedback 추가 - Positive] 팝업과 같은 내역을 상시 조회용 화면으로 뗀 것.
 *   · 목록: sql_fulltext / sql_id / mapped_sql_text / timestamp / use_count
 *   · 행 클릭 → 읽기전용 상세 모달(긴 SQL pretty-print, 'select ai showsql' 내부 SQL 추출)
 *   · 백엔드: GET /api/history/mapped-sql (전용 라우터 app/routers/history.py)
 */
(function () {
  function errMsg(err, fallback) {
    const p = err && err.payload; const d = p && (p.detail || p.error);
    if (d) return typeof d === "string" ? d : (d.error || d.message || JSON.stringify(d));
    return (err && err.message) || fallback || "요청 실패";
  }
  function divFromHtml(html) { const d = document.createElement("div"); d.innerHTML = html; return d.firstElementChild || d; }

  // sql_fulltext 가 'select ai showsql' 이면 mapped_sql_text 는 SELECT '<실제 SQL>' <alias> 형태다.
  // 이때 첫 리터럴('') 안의 실제 SQL 만 추출한다('' 이스케이프는 ' 로 복원). 그 외에는 원본 그대로.
  function extractInnerSql(mapped) {
    const s = String(mapped || "");
    const start = s.indexOf("'");
    if (start < 0) return null;
    let out = "", i = start + 1;
    while (i < s.length) {
      if (s[i] === "'") {
        if (s[i + 1] === "'") { out += "'"; i += 2; continue; }  // '' → '
        return out;  // 닫는 따옴표
      }
      out += s[i++];
    }
    return out;  // 닫는 따옴표가 없으면 있는 데까지
  }
  function mappedInnerSql(row) {
    if (/^\s*select\s+ai\s+showsql\b/i.test(row.sql_fulltext || "")) {
      const inner = extractInnerSql(row.mapped_sql_text);
      if (inner) return inner;
    }
    return row.mapped_sql_text;
  }

  async function render() {
    const main = document.getElementById("main");
    main.innerHTML = "";
    const title = document.createElement("div");
    title.className = "view-title";
    title.innerHTML = `<h1>Select AI Test - History</h1>
      <span class="sub">select ai 실행 내역(v$mapped_sql)을 조회합니다.</span>`;
    main.appendChild(title);

    const panel = document.createElement("div");
    panel.className = "panel";
    panel.innerHTML = `
      <div class="panel-header"><h2>실행 내역 <span class="muted" style="font-size:var(--fs-sm);">v$mapped_sql · select ai · 최신순</span></h2>
        <button class="btn btn-ghost" id="hist-reload" type="button">↻ 새로고침</button>
      </div>
      <div class="panel-body stack">
        <div class="row" style="gap:12px; align-items:flex-end; flex-wrap:wrap;">
          <div class="stack-sm"><label style="font-size:var(--fs-sm);">시작일시</label>
            <input type="datetime-local" id="hist-start" step="1"></div>
          <div class="stack-sm"><label style="font-size:var(--fs-sm);">종료일시</label>
            <input type="datetime-local" id="hist-end" step="1"></div>
          <div class="stack-sm" style="flex:1; min-width:220px;"><label style="font-size:var(--fs-sm);">sql_fulltext 검색 (LIKE, 대소문자 무시)</label>
            <input type="text" id="hist-text" placeholder="포함할 텍스트" style="width:100%;"></div>
          <div><button class="btn btn-primary" id="hist-search" type="button">조회</button></div>
          <div><button class="btn btn-ghost" id="hist-clear" type="button">초기화</button></div>
        </div>
        <div id="hist"></div>
      </div>`;
    main.appendChild(panel);

    panel.querySelector("#hist-reload").addEventListener("click", loadHistory);
    panel.querySelector("#hist-search").addEventListener("click", loadHistory);
    panel.querySelector("#hist-clear").addEventListener("click", () => {
      ["hist-start", "hist-end", "hist-text"].forEach((id) => { const el = document.getElementById(id); if (el) el.value = ""; });
      loadHistory();
    });
    // 검색어 입력창에서 Enter → 조회
    panel.querySelector("#hist-text").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); loadHistory(); } });
    loadHistory();
  }

  async function loadHistory() {
    const host = document.getElementById("hist");
    if (!host) return;
    const val = (id) => (document.getElementById(id)?.value || "").trim();
    const qs = new URLSearchParams();
    if (val("hist-start")) qs.set("start", val("hist-start"));
    if (val("hist-end")) qs.set("end", val("hist-end"));
    if (val("hist-text")) qs.set("text", val("hist-text"));
    const url = "/api/history/mapped-sql" + (qs.toString() ? "?" + qs.toString() : "");
    host.innerHTML = '<div class="empty-state"><span class="spinner"></span> 조회 중...</div>';
    let rows;
    try { rows = await window.API.get(url); }
    catch (e) { host.innerHTML = `<div class="empty-state muted">${window.escapeHtml(errMsg(e, "v$mapped_sql 조회 실패"))}</div>`; return; }
    host.innerHTML = "";
    host.appendChild(window.SimpleTable.create(
      [
        { key: "sql_fulltext", label: "Sql_fulltext" },
        { key: "sql_id", label: "sql_id" },
        { key: (r) => mappedInnerSql(r), label: "Mapped_sql_text" },
        { key: "translation_timestamp", label: "timestamp", headerAlign: "center" },
        { key: "use_count", label: "use_count", headerAlign: "center", align: "center" },
        { key: "_eval", label: "평가", headerAlign: "center", align: "center", format: (_v, row) => buildEvalBtn(row) },
      ],
      rows || [],
      { className: "keep-case", onRowClick: (row) => showDetailModal(row),
        emptyText: "조회 조건에 해당하는 실행 내역이 없습니다." }
    ));
  }

  // ── 읽기전용 상세 모달 (profile_test.js 의 showMappedViewModal 이식) ──
  function showDetailModal(row) {
    // 한 줄로 저장된 SQL 을 주요 절 앞에서 줄바꿈해 읽기 쉽게 만든다(표시용).
    const prettySql = (s) => s == null ? s : String(s).replace(
      /\s+(FROM|WHERE|AND|OR|GROUP\s+BY|ORDER\s+BY|HAVING|LEFT\s+JOIN|RIGHT\s+JOIN|FULL\s+JOIN|INNER\s+JOIN|JOIN|ON|UNION\s+ALL|UNION)\b/gi,
      "\n$1");

    // 목록과 동일하게 'select ai showsql' 의 바깥 SELECT 래퍼를 벗겨 내부 실제 SQL 을 표시.
    const mappedText = mappedInnerSql(row);
    const mappedDisplay = prettySql(mappedText);

    // copyId 를 주면 라벨 우측에 [복사] 버튼을 붙인다(표시된 값 그대로 클립보드로).
    const roField = (label, value, copyId) => `
      <div class="stack-sm">
        <div class="row" style="justify-content:space-between; align-items:center; gap:8px;">
          <label style="font-size:var(--fs-sm); color:var(--text-muted);">${label}</label>
          ${copyId ? `<button class="btn btn-ghost" data-copy="${copyId}" type="button" style="padding:2px 10px; font-size:var(--fs-sm);">복사</button>` : ""}
        </div>
        <pre style="white-space:pre-wrap; word-break:break-word; margin:0; font-family:var(--font-mono); font-size:var(--fs-sm); background:var(--surface-alt); padding:var(--space-2) var(--space-3); border-radius:var(--radius-md); max-height:240px; overflow:auto;">${window.escapeHtml(value != null && String(value).trim() !== "" ? String(value) : "—")}</pre>
      </div>`;

    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    backdrop.innerHTML = `
      <div class="modal" style="width:900px; max-width:95vw;">
        <div class="modal-header">
          <h2>실행 내역 상세 <span class="muted" style="font-size:var(--fs-sm);">v$mapped_sql · 읽기전용</span></h2>
          <button class="btn btn-ghost" id="mv-close">✕</button>
        </div>
        <div class="modal-body stack">
          <div class="row" style="gap:12px;">
            <div style="flex:1; min-width:0;">${roField("sql_id", row.sql_id)}</div>
            <div style="flex:1; min-width:0;">${roField("use_count", row.use_count)}</div>
            <div style="flex:1; min-width:0;">${roField("timestamp", row.translation_timestamp)}</div>
          </div>
          ${roField("sql_fulltext", row.sql_fulltext, "fulltext")}
          ${roField("mapped_sql_text", mappedDisplay, "mapped")}
          <div class="row end">
            <button class="btn btn-ghost" id="mv-close2">닫기</button>
          </div>
        </div>
      </div>`;
    const close = () => { backdrop.remove(); document.removeEventListener("keydown", onKey); };
    const onKey = (e) => { if (e.key === "Escape") close(); };
    // 바깥 클릭으로는 닫지 않음 — 닫기는 X/닫기 버튼 또는 ESC 로만.
    backdrop.querySelector("#mv-close").addEventListener("click", close);
    backdrop.querySelector("#mv-close2").addEventListener("click", close);
    // [복사] 버튼 — 표시된 값을 클립보드로 (sql_fulltext / mapped_sql_text)
    const copyMap = {
      fulltext: row.sql_fulltext == null ? "" : String(row.sql_fulltext),
      mapped: mappedDisplay == null ? "" : String(mappedDisplay),
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

  // ── 평가(LLM-as-judge) ─────────────────────────────────
  function buildEvalBtn(row) {
    const btn = document.createElement("button");
    btn.className = "btn btn-primary";
    btn.textContent = "평가";
    btn.style.cssText = "padding:4px 12px; font-size:var(--fs-sm);";
    btn.addEventListener("click", (e) => { e.stopPropagation(); showEvaluateModal(row); });
    return btn;
  }
  // verdict 배지 (profile_test.js mkBadge 와 동일 색상 규칙)
  function mkBadge(verdict) {
    const bg = verdict === "적정" ? "#1a7f5a" : verdict === "비적정" ? "#C74634"
      : verdict === "판정불가" ? "#b8860b" : "#8a8f98";
    const s = document.createElement("span");
    s.textContent = verdict || "—";
    s.style.cssText = `display:inline-block;font-size:12px;font-weight:700;padding:3px 12px;border-radius:999px;color:#fff;background:${bg}`;
    return s;
  }
  async function showEvaluateModal(row) {
    const prettySql = (s) => s == null ? s : String(s).replace(
      /\s+(FROM|WHERE|AND|OR|GROUP\s+BY|ORDER\s+BY|HAVING|LEFT\s+JOIN|RIGHT\s+JOIN|FULL\s+JOIN|INNER\s+JOIN|JOIN|ON|UNION\s+ALL|UNION)\b/gi,
      "\n$1");
    const evalSql = mappedInnerSql(row);
    const mappedDisplay = prettySql(evalSql);
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
          ${roField("sql_fulltext", row.sql_fulltext, "fulltext")}
          ${roField("mapped_sql_text", mappedDisplay, "mapped")}
          <div class="row" style="gap:12px; align-items:flex-end; flex-wrap:wrap;">
            <div class="stack-sm" style="flex:0 0 280px;">
              <label style="font-size:var(--fs-sm);">평가 수행 AI Profile</label>
              <select id="ev-profile"><option value="">불러오는 중…</option></select>
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

    // 복사 버튼
    const copyMap = { fulltext: row.sql_fulltext == null ? "" : String(row.sql_fulltext), mapped: mappedDisplay == null ? "" : String(mappedDisplay) };
    backdrop.querySelectorAll("[data-copy]").forEach((btn) => btn.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(copyMap[btn.dataset.copy] || ""); window.Toast.show("클립보드에 복사됨", "success"); }
      catch (_) { window.Toast.show("복사 실패", "error"); }
    }));

    document.body.appendChild(backdrop);

    // 프로파일 로드 (ENABLED)
    const profileSel = backdrop.querySelector("#ev-profile");
    try {
      const profiles = await window.API.get("/api/profiles");
      const names = (profiles || []).filter((p) => p.status === "ENABLED").map((p) => p.profile_name);
      profileSel.innerHTML = names.length ? names.map((n) => `<option value="${window.escapeAttr(n)}">${window.escapeHtml(n)}</option>`).join("")
        : `<option value="">사용 가능한 Profile 없음</option>`;
    } catch (e) { profileSel.innerHTML = `<option value="">Profile 로드 실패</option>`; }

    const out = backdrop.querySelector("#ev-out");
    backdrop.querySelector("#ev-run").addEventListener("click", async () => {
      const profile = profileSel.value;
      if (!profile) { window.Toast.show("평가 수행 AI Profile 을 선택하세요", "warn"); return; }
      const btn = backdrop.querySelector("#ev-run"); btn.disabled = true; const old = btn.textContent;
      btn.innerHTML = '<span class="spinner"></span> 평가 중...';
      out.innerHTML = '<div class="empty-state"><span class="spinner"></span> 심사 중...</div>';
      let res;
      try { res = await window.API.post("/api/history/evaluate", { profile, prompt: row.sql_fulltext, sql: evalSql }); }
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
  window.Views.history = render;
})();
