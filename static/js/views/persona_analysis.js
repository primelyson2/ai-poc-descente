/** views/persona_analysis.js — 메뉴 [Select AI Test - 페르소나분석].
 * 2단계 실행:
 *   1) [실행]      → /api/persona-analysis/gen-sql : 추출 SQL 만 생성해 먼저 보여준다(수정 가능).
 *   2) [계속 진행] → /api/persona-analysis/analyze  : (확인/수정한) SQL 실행(최대 100행) + 분석(chat).
 * 답변: [1] 생성된 SQL(+showprompt 참고) → [계속 진행] → [2] 분석결과 → [3] 데이터표(+Download, ≤100행).
 */
(function () {
  function errMsg(err, fallback) {
    const p = err && err.payload;
    const d = p && (p.detail || p.error);
    if (d) { if (typeof d === "string") return d; return d.error || d.message || JSON.stringify(d); }
    return (err && err.message) || fallback || "요청 실패";
  }

  function errBox(msg) {
    const d = document.createElement("div");
    d.className = "empty-state";
    d.style.color = "var(--danger, #c74634)";
    d.style.whiteSpace = "pre-wrap";
    d.textContent = msg;
    return d;
  }

  async function fillProfileSelect(sel) {
    sel.innerHTML = `<option value="">불러오는 중…</option>`;
    let names = [];
    try {
      const profiles = await window.API.get("/api/profiles");
      names = (profiles || []).filter((p) => p.status === "ENABLED").map((p) => p.profile_name);
    } catch (e) {}
    sel.innerHTML = "";
    if (!names.length) { sel.innerHTML = `<option value="">사용 가능한 Profile 없음</option>`; return; }
    names.forEach((nm) => { const o = document.createElement("option"); o.value = nm; o.textContent = nm; sel.appendChild(o); });
    sel.value = names[0];
  }

  async function fetchPersonas() {
    try { const list = await window.API.get("/api/personas"); return Array.isArray(list) ? list : []; }
    catch (e) { return []; }
  }

  function fillPersonaSelect(sel, list) {
    sel.innerHTML = "";
    if (!list.length) { sel.innerHTML = `<option value="">(등록된 페르소나 없음)</option>`; return; }
    list.forEach((p) => { const o = document.createElement("option"); o.value = String(p.id); o.textContent = p.persona_name; sel.appendChild(o); });
    sel.value = String(list[0].id);
  }

  // 결과 테이블 → CSV (Excel 호환 위해 BOM).
  function downloadCsv(columns, rows, baseName) {
    const esc = (v) => {
      const s = v === null || v === undefined ? "" : String(v);
      return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
    };
    const lines = [columns.map(esc).join(",")];
    rows.forEach((r) => lines.push(r.map(esc).join(",")));
    const csv = "﻿" + lines.join("\r\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = (baseName || "persona_analysis").replace(/[^\w가-힣.-]+/g, "_") + ".csv";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  function fmtMs(v) { return v == null ? "-" : Number(v).toLocaleString() + " ms"; }

  // 접이식 details + Copy (제목, 내용, 기본 열림여부)
  function detailsBlock(title, content, open) {
    const det = document.createElement("details");
    det.style.position = "relative";
    if (open) det.open = true;
    const sum = document.createElement("summary");
    sum.className = "muted"; sum.style.cursor = "pointer"; sum.style.fontSize = "var(--fs-sm)";
    sum.textContent = title;
    const copy = document.createElement("button");
    copy.className = "btn"; copy.type = "button"; copy.textContent = "Copy";
    copy.style.position = "absolute"; copy.style.top = "0"; copy.style.right = "0"; copy.style.fontSize = "var(--fs-sm)";
    copy.addEventListener("click", (e) => {
      e.preventDefault(); e.stopPropagation();
      navigator.clipboard.writeText(content).then(
        () => window.Toast.show("복사됨", "success"),
        () => window.Toast.show("복사 실패", "error"));
    });
    const pre = document.createElement("pre");
    pre.style.whiteSpace = "pre-wrap"; pre.textContent = content;
    det.appendChild(sum); det.appendChild(copy); det.appendChild(pre);
    return det;
  }

  function panelWith(title) {
    const box = document.createElement("div");
    box.className = "panel";
    box.innerHTML = `<div class="panel-header"><h2>${title}</h2></div>`;
    const body = document.createElement("div");
    body.className = "panel-body";
    box.appendChild(body);
    return { box, body };
  }

  // ── [2] 분석결과 패널 ──
  function analysisPanel(res) {
    const { box, body } = panelWith("2. 분석결과");
    if (res.analysis) {
      const copy = document.createElement("button");
      copy.className = "btn btn-mini"; copy.type = "button"; copy.textContent = "복사";
      copy.addEventListener("click", () => navigator.clipboard.writeText(res.analysis).then(
        () => window.Toast.show("분석 결과 복사됨", "success"),
        () => window.Toast.show("복사 실패", "error")));
      box.querySelector(".panel-header").appendChild(copy);
      const pre = document.createElement("pre");
      pre.style.whiteSpace = "pre-wrap"; pre.style.margin = "0"; pre.textContent = res.analysis;
      body.appendChild(pre);
      const t = document.createElement("div");
      t.className = "muted"; t.style.fontSize = "var(--fs-sm)"; t.style.marginTop = "var(--space-2)";
      t.textContent = `총시간 ${fmtMs(res.total_ms)} (조회 ${fmtMs(res.exec_ms)}, 분석 ${fmtMs(res.analyze_ms)})`;
      body.appendChild(t);
    } else {
      body.appendChild(errBox(res.error || "분석 결과가 없습니다"));
    }
    return box;
  }

  // ── [3] 데이터 표 + Download (≤100행, 이미 조회된 행만) ──
  function tablePanel(res) {
    const { box, body } = panelWith("3. 데이터");
    if ((res.rows || []).length) {
      const link = document.createElement("a");
      link.textContent = "Download";
      link.setAttribute("role", "button"); link.tabIndex = 0;
      link.style.cssText = "color:#0066cc; text-decoration:underline; cursor:pointer; font-size:var(--fs-sm);";
      link.addEventListener("click", () => {
        if (!(res.rows || []).length) { window.Toast.show("다운로드할 데이터가 없습니다", "error"); return; }
        downloadCsv(res.columns || [], res.rows, "persona_analysis");
      });
      box.querySelector(".panel-header").appendChild(link);
    }
    if (res.truncated) {
      const note = document.createElement("div");
      note.className = "muted"; note.style.fontSize = "var(--fs-sm)"; note.style.marginBottom = "var(--space-2)";
      note.textContent = "※ 조회·분석·다운로드는 최대 100행으로 제한됩니다.";
      body.appendChild(note);
    }
    const cols = (res.columns || []).map((nm, i) => ({ key: (row) => row[i], label: nm }));
    body.appendChild(window.SimpleTable.create(cols, res.rows || [], { emptyText: "결과가 없습니다" }));
    return box;
  }

  // 2단계 결과(분석 + 표)를 stage2 호스트에 렌더.
  function renderStage2(stageHost, res) {
    stageHost.innerHTML = "";
    if (res.analysis || res.error) stageHost.appendChild(analysisPanel(res));
    if ((res.columns || []).length || (res.rows || []).length) stageHost.appendChild(tablePanel(res));
  }

  // 1단계 결과(생성된 SQL) 렌더 + [계속 진행] 배선. ctx={profile, persona_prompt}
  function renderGenSql(host, res, ctx) {
    host.innerHTML = "";
    if (!res.sql && res.error) { host.appendChild(errBox(res.error)); return; }

    const { box, body } = panelWith("1. 생성된 SQL");
    // 생성된 SQL — 수정 가능(계속 진행 시 이 값이 실행됨)
    const sqlLabel = document.createElement("div");
    sqlLabel.className = "muted"; sqlLabel.style.fontSize = "var(--fs-sm)"; sqlLabel.style.marginBottom = "var(--space-1)";
    sqlLabel.textContent = "생성된 SQL (수정 가능) — [계속 진행] 시 이 SQL 이 실행됩니다.";
    const sqlArea = document.createElement("textarea");
    sqlArea.value = res.sql || "";
    sqlArea.rows = Math.min(16, Math.max(4, (res.sql || "").split("\n").length + 1));
    sqlArea.style.cssText = "width:100%; font-family:var(--font-mono); font-size:var(--fs-sm);";
    body.appendChild(sqlLabel);
    body.appendChild(sqlArea);
    if (res.showprompt) body.appendChild(detailsBlock("참고: showprompt (스키마 컨텍스트)", res.showprompt, false));

    const footer = document.createElement("div");
    footer.className = "row";
    footer.style.cssText = "justify-content:space-between; align-items:center; margin-top:var(--space-3);";
    const timing = document.createElement("span");
    timing.className = "muted"; timing.style.fontSize = "var(--fs-sm)";
    timing.textContent = `SQL생성 ${fmtMs(res.gen_ms)}`;
    const contBtn = document.createElement("button");
    contBtn.className = "btn btn-primary"; contBtn.type = "button"; contBtn.textContent = "계속 진행 (실행 + 분석)";
    footer.appendChild(timing);
    footer.appendChild(contBtn);
    body.appendChild(footer);
    host.appendChild(box);

    // 2단계 결과가 들어갈 자리
    const stageHost = document.createElement("div");
    host.appendChild(stageHost);

    contBtn.addEventListener("click", async () => {
      const sql = sqlArea.value.trim();
      if (!sql) { window.Toast.show("실행할 SQL 이 없습니다", "error"); return; }
      contBtn.disabled = true;
      stageHost.innerHTML = `<div class="empty-state muted"><span class="spinner"></span> SQL 실행 · 분석 중…</div>`;
      let res2;
      try {
        res2 = await window.API.post("/api/persona-analysis/analyze", {
          profile_name: ctx.profile, persona_prompt: ctx.persona_prompt, sql,
        });
      } catch (err) {
        stageHost.innerHTML = "";
        stageHost.appendChild(errBox(errMsg(err, "실행 실패")));
        return;
      } finally {
        contBtn.disabled = false;
      }
      renderStage2(stageHost, res2);
    });
  }

  async function render() {
    const main = document.getElementById("main");
    main.innerHTML = "";

    const panel = document.createElement("div");
    panel.className = "stack";
    panel.innerHTML = `
      <div class="view-title">
        <h1>Select AI Test - 페르소나분석</h1>
        <span class="sub">페르소나 + 질문으로 추출 SQL을 생성(1단계)하고, [계속 진행]으로 실행·분석(2단계)합니다.</span>
      </div>
      <div class="row" style="gap:var(--space-4); align-items:flex-end; flex-wrap:wrap;">
        <div class="stack-sm"><label>AI Profile</label><select id="pa-profile" style="min-width:200px;"></select></div>
        <div class="stack-sm">
          <label>페르소나</label>
          <div class="row" style="gap:var(--space-2);">
            <select id="pa-persona" style="min-width:200px;"></select>
            <button class="btn" id="pa-reload" type="button" title="페르소나 목록 새로고침">↻</button>
          </div>
        </div>
        <div class="stack-sm"><label>SQL 생성 방식</label>
          <select id="pa-mode" style="min-width:360px;">
            <option value="showsql">A) SQL생성(showsql, 페르소나기반질문사용) → SQL실행 → 분석(chat)</option>
            <option value="showprompt2">B) showprompt → SQL생성(페르소나기반 Prompt추가) → SQL실행 → 분석(chat)</option>
          </select>
        </div>
        <button class="btn btn-primary" id="pa-run" type="button" style="min-width:120px; font-size:1.2em;">실행 (SQL 생성)</button>
      </div>
      <div class="stack-sm">
        <label style="font-weight:600;">질문 (분석 대상/조건)</label>
        <input type="text" id="pa-question" style="width:100%;" placeholder="예: 르꼬끄골프 2025년 오프라인 매출을 브랜드·채널별로 조회" />
      </div>
      <div class="stack-sm">
        <label style="font-weight:600;">페르소나 프롬프트 <span class="muted" style="font-size:var(--fs-sm);">— 선택한 페르소나로 채워지며 수정 가능</span></label>
        <textarea id="pa-prompt" rows="6" style="font-family:var(--font-mono); font-size:var(--fs-sm);"></textarea>
      </div>
      <div id="pa-result"><div class="empty-state muted">AI Profile·페르소나·질문을 입력하고 [실행]을 누르세요.</div></div>
    `;
    main.appendChild(panel);

    const profileSel = panel.querySelector("#pa-profile");
    const personaSel = panel.querySelector("#pa-persona");
    const modeSel = panel.querySelector("#pa-mode");
    const questionEl = panel.querySelector("#pa-question");
    const promptEl = panel.querySelector("#pa-prompt");
    const resultEl = panel.querySelector("#pa-result");

    fillProfileSelect(profileSel);

    let personas = [];
    const applyPersona = () => {
      const p = personas.find((x) => String(x.id) === personaSel.value);
      promptEl.value = p ? p.prompt_tmpl : "";
    };
    const reloadPersonas = async () => {
      personas = await fetchPersonas();
      fillPersonaSelect(personaSel, personas);
      applyPersona();
    };
    reloadPersonas();
    personaSel.addEventListener("change", applyPersona);
    panel.querySelector("#pa-reload").addEventListener("click", reloadPersonas);

    // 1단계 — SQL 생성만.
    panel.querySelector("#pa-run").addEventListener("click", async () => {
      const profile = profileSel.value;
      const question = questionEl.value.trim();
      const persona_prompt = promptEl.value;
      if (!profile) { window.Toast.show("AI Profile 을 선택하세요", "error"); return; }
      if (!question) { window.Toast.show("질문을 입력하세요", "error"); questionEl.focus(); return; }
      if (!persona_prompt.trim()) { window.Toast.show("페르소나를 선택하세요", "error"); return; }

      const runBtn = panel.querySelector("#pa-run");
      runBtn.disabled = true;
      resultEl.innerHTML = `<div class="empty-state muted"><span class="spinner"></span> SQL 생성 중… (첫 호출은 다소 걸릴 수 있습니다)</div>`;
      let res;
      try {
        res = await window.API.post("/api/persona-analysis/gen-sql", {
          profile_name: profile, question, persona_prompt, mode: modeSel.value,
        });
      } catch (err) {
        resultEl.innerHTML = "";
        resultEl.appendChild(errBox(errMsg(err, "SQL 생성 실패")));
        return;
      } finally {
        runBtn.disabled = false;
      }
      renderGenSql(resultEl, res, { profile, persona_prompt });
    });
  }

  window.Views = window.Views || {};
  window.Views.personaAnalysis = render;
})();
