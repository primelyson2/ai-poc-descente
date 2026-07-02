/** views/nl2sql.js — 메뉴 [Select AI Test - Table list].
 * Chat설정(AI Profile + User Prompt 템플릿)을 골라 질문/조회할 컬럼/정렬기준을 입력하고
 * Data요청을 누르면 백엔드(/api/nl2sql/run)가 DBMS_CLOUD_AI.GENERATE(action=>'showsql')로
 * SQL을 만들고 그 SELECT를 실행해 컬럼 헤더 + 데이터 행을 Table list에 렌더한다.
 * 결과는 Download(CSV)로 내려받을 수 있다.
 *
 * 자리표시자: ##메시지##(질문) / ##조회할 컬럼## / ##정렬기준## 를 입력값으로 치환.
 * 입력 3종은 각각 "저장할 제목 + 추가/수정 + 저장된 프롬프트" 콤보로 빠르게 채울 수 있다.
 */
(function () {
  const CONFIG_KEY = "nl2sql.savedConfigs";
  // 입력 필드별 저장 프롬프트 키 (DB별 격리는 Store 가 처리)
  const Q_KEY = "nl2sql.savedQuestions";
  const COL_KEY = "nl2sql.savedColumns";
  const SORT_KEY = "nl2sql.savedSorts";

  // 새 Chat설정 추가 시 기본 User Prompt (목업 예시 기준)
  const DEFAULT_USER_PROMPT =
    "[INSTRUCTION]\n" +
    ">기준일: 20260629\n" +
    ">결과형식\n" +
    "테이블 형태로 다음 컬럼을 추출\n" +
    "- ##조회할 컬럼##\n" +
    "정렬기준\n" +
    "- ##정렬기준##\n\n" +
    "[QUESTION]\n" +
    "##메시지##";

  // API 오류 메시지 추출
  function errMsg(err, fallback) {
    const p = err && err.payload;
    const d = p && (p.detail || p.error);
    if (d) {
      if (typeof d === "string") return d;
      return d.error || d.message || JSON.stringify(d);
    }
    return (err && err.message) || fallback || "요청 실패";
  }

  const loadConfigs = () => {
    try { return JSON.parse(window.Store.get(CONFIG_KEY)) || []; }
    catch (e) { return []; }
  };

  // 입력 필드 + (제목/추가/수정/콤보) 저장 프롬프트 콤보 연결.
  // shape: [{title, prompt}] — Profile Test 화면과 동일 규약.
  function wireSavedPrompts(key, inputEl, titleEl, addBtn, updBtn, selEl) {
    const load = () => {
      try { return JSON.parse(window.Store.get(key)) || []; }
      catch (e) { return []; }
    };
    const refresh = (selectTitle) => {
      const list = load();
      selEl.innerHTML = "";
      const ph = document.createElement("option");
      ph.value = "";
      ph.textContent = list.length ? "저장된 프롬프트…" : "(저장된 프롬프트 없음)";
      selEl.appendChild(ph);
      [...list].sort((a, b) => a.title.localeCompare(b.title)).forEach((p) => {
        const o = document.createElement("option");
        o.value = p.title;
        o.textContent = p.title;
        selEl.appendChild(o);
      });
      if (selectTitle != null) selEl.value = selectTitle;
    };
    refresh();

    addBtn.addEventListener("click", () => {
      const title = titleEl.value.trim();
      const prompt = inputEl.value;
      if (!title) { window.Toast.show("추가할 제목을 입력하세요", "error"); titleEl.focus(); return; }
      if (!prompt.trim()) { window.Toast.show("내용이 비어 있습니다", "error"); return; }
      const list = load();
      if (list.some((p) => p.title === title)) {
        window.Toast.show("이미 있는 제목입니다. [수정]으로 변경하세요", "error");
        return;
      }
      list.push({ title, prompt });
      window.Store.set(key, JSON.stringify(list));
      refresh(title);
      titleEl.value = "";
      window.Toast.show(`'${title}' 추가됨`, "success");
    });

    updBtn.addEventListener("click", () => {
      const title = selEl.value;
      if (!title) { window.Toast.show("수정할 항목을 콤보에서 선택하세요", "error"); return; }
      const prompt = inputEl.value;
      if (!prompt.trim()) { window.Toast.show("내용이 비어 있습니다", "error"); return; }
      const list = load();
      const idx = list.findIndex((p) => p.title === title);
      if (idx < 0) { window.Toast.show("저장된 항목을 찾을 수 없습니다", "error"); return; }
      list[idx].prompt = prompt;
      window.Store.set(key, JSON.stringify(list));
      window.Toast.show(`'${title}' 수정됨`, "success");
    });

    selEl.addEventListener("change", () => {
      const title = selEl.value;
      if (!title) return;
      const found = load().find((p) => p.title === title);
      if (found) inputEl.value = found.prompt;
    });
  }

  // 필드 블록 HTML (라벨 + 저장 콤보 + 입력) — id 접두사로 구분
  function fieldBlockHtml(prefix, label, placeholder) {
    return `
      <div class="stack-sm">
        <div class="row" style="justify-content:space-between; gap:var(--space-2);">
          <label style="font-weight:600;">${label}</label>
          <div class="row" style="gap:var(--space-2);">
            <input type="text" id="${prefix}-title" placeholder="저장할 제목" style="width:120px;" />
            <button class="btn" id="${prefix}-add" type="button">추가</button>
            <button class="btn" id="${prefix}-update" type="button">수정</button>
            <select id="${prefix}-saved" style="min-width:140px;"></select>
          </div>
        </div>
        <input type="text" id="${prefix}-input" style="width:100%;" placeholder="${placeholder}" />
      </div>
    `;
  }

  async function render() {
    const main = document.getElementById("main");
    main.innerHTML = "";

    const panel = document.createElement("div");
    panel.className = "stack";
    panel.innerHTML = `
      <div class="row">
        <label style="width:90px;">Chat설정</label>
        <select id="nl-config" style="min-width:220px;"></select>
        <button class="btn" id="nl-config-add" type="button">추가</button>
        <button class="btn" id="nl-config-update" type="button">수정</button>
      </div>
      <div class="row" style="align-items:stretch; gap:var(--space-4);">
        <div class="stack" style="flex:1;">
          ${fieldBlockHtml("nl-q", "질문", "질문입력")}
          ${fieldBlockHtml("nl-cols", "조회할 컬럼", "예시: 판매일자, 나이, 브랜드, 채널, 사용 쿠폰, 등급, 제품코드, 제품명")}
          ${fieldBlockHtml("nl-sort", "정렬기준", "예시: 판매일자(오름차순), 나이(내림차순)")}
        </div>
        <div style="display:flex; min-width:130px;">
          <button class="btn btn-primary" id="nl-run" type="button" style="flex:1; min-width:120px; font-size:2em; display:flex; align-items:center; justify-content:center; text-align:center;">실행</button>
        </div>
      </div>
      <label style="font-weight:600;">답변</label>
      <div id="nl-sql-area"></div>
      <div class="row" id="nl-download-bar" style="display:none; justify-content:space-between; align-items:center;">
        <span id="nl-timing" class="muted" style="font-size:var(--fs-sm);"></span>
        <div class="row" style="gap:var(--space-3); align-items:center;">
          <button class="btn btn-ai-test" id="nl-analyze" type="button" style="display:none;">AI분석</button>
          <a id="nl-download" role="button" tabindex="0" style="color:#0066cc; text-decoration:underline; cursor:pointer; display:none;">Download</a>
        </div>
      </div>
      <div id="nl-result"><div class="empty-state muted">Chat설정을 선택하고 질문을 입력한 뒤 Data요청을 누르세요.</div></div>
    `;
    main.appendChild(panel);

    const configSel = panel.querySelector("#nl-config");
    const sqlArea = panel.querySelector("#nl-sql-area");
    const resultArea = panel.querySelector("#nl-result");

    // 최근 결과(다운로드용)
    let lastResult = null;

    const refreshConfigs = (selectName) => {
      const list = loadConfigs();
      configSel.innerHTML = "";
      const ph = document.createElement("option");
      ph.value = "";
      ph.textContent = list.length ? "설정 선택…" : "(저장된 설정 없음)";
      configSel.appendChild(ph);
      list.forEach((c) => {
        const o = document.createElement("option");
        o.value = c.name;
        o.textContent = c.name;
        configSel.appendChild(o);
      });
      if (selectName != null) configSel.value = selectName;
    };
    refreshConfigs();

    panel.querySelector("#nl-config-add").addEventListener("click", () => {
      openConfigModal("add", { name: "", profile: "", userPrompt: DEFAULT_USER_PROMPT }, refreshConfigs);
    });
    panel.querySelector("#nl-config-update").addEventListener("click", () => {
      const name = configSel.value;
      if (!name) { window.Toast.show("수정할 설정을 선택하세요", "error"); return; }
      const found = loadConfigs().find((c) => c.name === name);
      if (!found) { window.Toast.show("저장된 설정을 찾을 수 없습니다", "error"); return; }
      openConfigModal("edit", found, refreshConfigs);
    });

    // 필드별 저장 프롬프트 콤보 연결
    const qInput = panel.querySelector("#nl-q-input");
    const colInput = panel.querySelector("#nl-cols-input");
    const sortInput = panel.querySelector("#nl-sort-input");
    wireSavedPrompts(Q_KEY, qInput, panel.querySelector("#nl-q-title"),
      panel.querySelector("#nl-q-add"), panel.querySelector("#nl-q-update"), panel.querySelector("#nl-q-saved"));
    wireSavedPrompts(COL_KEY, colInput, panel.querySelector("#nl-cols-title"),
      panel.querySelector("#nl-cols-add"), panel.querySelector("#nl-cols-update"), panel.querySelector("#nl-cols-saved"));
    wireSavedPrompts(SORT_KEY, sortInput, panel.querySelector("#nl-sort-title"),
      panel.querySelector("#nl-sort-add"), panel.querySelector("#nl-sort-update"), panel.querySelector("#nl-sort-saved"));

    const downloadBar = panel.querySelector("#nl-download-bar");
    const timingEl = panel.querySelector("#nl-timing");
    const downloadLink = panel.querySelector("#nl-download");
    const analyzeBtn = panel.querySelector("#nl-analyze");
    panel.querySelector("#nl-run").addEventListener("click", async () => {
      const res = await runQuery(configSel, qInput, colInput, sortInput, sqlArea, resultArea);
      lastResult = res;
      // 실행 시간표 + AI분석 + Download (조회 결과가 있을 때만 표시)
      if (res && res.total_ms != null) {
        timingEl.textContent = fmtTiming(res);
        const hasRows = (res.rows || []).length > 0;
        analyzeBtn.style.display = hasRows ? "" : "none";
        downloadLink.style.display = hasRows ? "" : "none";
        downloadBar.style.display = "flex";
      } else {
        downloadBar.style.display = "none";
      }
    });

    // AI분석 — 직전 생성 SQL 로 최대 100행을 조회해 페르소나 프롬프트와 함께 LLM 분석.
    analyzeBtn.addEventListener("click", () => {
      openAnalyzeModal(lastResult);
    });

    // Download — 표시용 100행이 아니라 SQL 을 다시 실행해 전체 row 를 CSV 로 받는다.
    panel.querySelector("#nl-download").addEventListener("click", async () => {
      if (!lastResult || !lastResult.sql) {
        window.Toast.show("다운로드할 데이터가 없습니다", "error");
        return;
      }
      const orig = downloadLink.textContent;
      downloadLink.textContent = "전체 조회 중…";
      downloadLink.style.pointerEvents = "none";
      try {
        const exp = await window.API.post("/api/nl2sql/export", { sql: lastResult.sql });
        if (!exp || !(exp.rows || []).length) {
          window.Toast.show("다운로드할 데이터가 없습니다", "error");
          return;
        }
        downloadCsv(exp.columns, exp.rows, (configSel.value || "table_list"));
      } catch (err) {
        window.Toast.show(errMsg(err, "다운로드 실패"), "error");
      } finally {
        downloadLink.textContent = orig;
        downloadLink.style.pointerEvents = "";
      }
    });
  }

  // 실행 시간표 문자열 — "총시간 X ms (SQL생성 Y ms, SQL실행 Z ms)"
  function fmtTiming(res) {
    const ms = (v) => (v == null ? "-" : Number(v).toLocaleString() + " ms");
    return `총시간 ${ms(res.total_ms)} (SQL생성 ${ms(res.gen_ms)}, SQL실행 ${ms(res.exec_ms)})`;
  }

  // 실행 — 요청 완료 시 응답 객체(res) 반환(시간표/다운로드용), 요청 전 검증/네트워크 실패 시 null
  async function runQuery(configSel, qInput, colInput, sortInput, sqlArea, resultArea) {
    const name = configSel.value;
    if (!name) { window.Toast.show("Chat설정을 선택하세요", "error"); return null; }
    const cfg = loadConfigs().find((c) => c.name === name);
    if (!cfg) { window.Toast.show("저장된 설정을 찾을 수 없습니다", "error"); return null; }
    if (!cfg.profile) { window.Toast.show("설정에 AI Profile이 없습니다 — 수정에서 지정하세요", "error"); return null; }

    const message = qInput.value.trim();
    if (!message) { window.Toast.show("질문을 입력하세요", "error"); return null; }
    const columns = colInput.value;
    const sort_by = sortInput.value;

    const runBtn = document.getElementById("nl-run");
    runBtn.disabled = true;
    sqlArea.innerHTML = "";
    resultArea.innerHTML = `<div class="empty-state muted">실행 중…</div>`;

    let res;
    try {
      res = await window.API.post("/api/nl2sql/run", {
        profile_name: cfg.profile, user_prompt: cfg.userPrompt || "",
        message, columns, sort_by,
      });
    } catch (err) {
      resultArea.innerHTML = "";
      resultArea.appendChild(errBox(errMsg(err, "Data요청 실패")));
      return null;
    } finally {
      runBtn.disabled = false;
    }

    // 생성된 SQL 표시 (있으면) — 접이식, 기본 접힘(open 미설정)
    sqlArea.innerHTML = "";
    if (res.sql) {
      const det = document.createElement("details");
      det.style.position = "relative";
      const sum = document.createElement("summary");
      sum.className = "muted";
      sum.style.fontSize = "var(--fs-sm)";
      sum.style.cursor = "pointer";
      sum.textContent = "생성된 SQL";
      // 오른쪽 상단 SQL 복사 버튼 (summary 클릭으로 접힘 토글되지 않도록 이벤트 차단)
      const copyBtn = document.createElement("button");
      copyBtn.className = "btn";
      copyBtn.type = "button";
      copyBtn.textContent = "Copy";
      copyBtn.style.position = "absolute";
      copyBtn.style.top = "0";
      copyBtn.style.right = "0";
      copyBtn.style.fontSize = "var(--fs-sm)";
      copyBtn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        navigator.clipboard.writeText(res.sql).then(
          () => window.Toast.show("SQL 복사됨", "success"),
          () => window.Toast.show("복사 실패", "error")
        );
      });
      const pre = document.createElement("pre");
      pre.style.whiteSpace = "pre-wrap";
      pre.textContent = res.sql;
      det.appendChild(sum);
      det.appendChild(copyBtn);
      det.appendChild(pre);
      sqlArea.appendChild(det);
    }

    resultArea.innerHTML = "";
    if (res.error) {
      resultArea.appendChild(errBox(res.error));
      return res;
    }
    const cols = (res.columns || []).map((nm, i) => ({ key: (row) => row[i], label: nm }));
    if (res.truncated) {
      const note = document.createElement("div");
      note.className = "muted";
      note.style.fontSize = "var(--fs-sm)";
      note.style.marginBottom = "var(--space-2)";
      note.textContent = "※ 처음 100행만 표시합니다. (전체는 Download)";
      resultArea.appendChild(note);
    }
    const table = window.SimpleTable.create(cols, res.rows || [], { emptyText: "결과가 없습니다" });
    resultArea.appendChild(table);
    return res;
  }

  function errBox(msg) {
    const d = document.createElement("div");
    d.className = "empty-state";
    d.style.color = "var(--danger, #c74634)";
    d.style.whiteSpace = "pre-wrap";
    d.textContent = msg;
    return d;
  }

  // 결과 테이블 → CSV 다운로드 (Excel 호환 위해 BOM 추가)
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
    a.download = (baseName || "table_list").replace(/[^\w가-힣.-]+/g, "_") + ".csv";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  // Chat설정 입력/수정 팝업. mode='add'|'edit', cfg={name,profile,userPrompt}
  async function openConfigModal(mode, cfg, onSaved) {
    const origName = cfg.name || "";
    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    backdrop.innerHTML = `
      <div class="modal" style="width:640px; max-width:92vw;">
        <div class="modal-header">
          <h2>Chat설정 ${mode === "add" ? "추가" : "수정"}</h2>
          <button class="btn btn-ghost" id="cfg-close" type="button">✕</button>
        </div>
        <div class="modal-body stack">
          <div class="stack-sm">
            <label>Chat설정</label>
            <input type="text" id="cfg-name" placeholder="설정 이름" />
          </div>
          <div class="stack-sm">
            <label>AI Profile</label>
            <select id="cfg-profile"></select>
          </div>
          <div class="stack-sm">
            <label>User Prompt</label>
            <textarea id="cfg-prompt" rows="10" style="font-family:var(--font-mono); font-size:var(--fs-sm);"></textarea>
          </div>
        </div>
        <div class="modal-footer row end" style="gap:var(--space-2);">
          <button class="btn" id="cfg-cancel" type="button">취소</button>
          <button class="btn btn-primary" id="cfg-save" type="button">저장</button>
        </div>
      </div>
    `;
    const close = () => { backdrop.remove(); document.removeEventListener("keydown", onKey); };
    const onKey = (e) => { if (e.key === "Escape") close(); };
    document.addEventListener("keydown", onKey);
    document.body.appendChild(backdrop);

    const nameEl = backdrop.querySelector("#cfg-name");
    const profileSel = backdrop.querySelector("#cfg-profile");
    const promptEl = backdrop.querySelector("#cfg-prompt");
    nameEl.value = cfg.name || "";
    promptEl.value = cfg.userPrompt || "";

    // AI Profile 드롭다운 — ENABLED 만. 현재 값이 목록에 없으면 보존.
    profileSel.innerHTML = `<option value="">불러오는 중…</option>`;
    try {
      const profiles = await window.API.get("/api/profiles");
      const enabled = (profiles || []).filter((p) => p.status === "ENABLED");
      profileSel.innerHTML = "";
      const names = enabled.map((p) => p.profile_name);
      if (cfg.profile && !names.includes(cfg.profile)) names.unshift(cfg.profile);
      if (names.length === 0) {
        profileSel.innerHTML = `<option value="">사용 가능한 Profile이 없습니다</option>`;
      } else {
        names.forEach((nm) => {
          const o = document.createElement("option");
          o.value = nm; o.textContent = nm;
          profileSel.appendChild(o);
        });
      }
      profileSel.value = cfg.profile || (names[0] || "");
    } catch (e) {
      profileSel.innerHTML = "";
      const o = document.createElement("option");
      o.value = cfg.profile || "";
      o.textContent = cfg.profile || "Profile 목록 로드 실패";
      profileSel.appendChild(o);
      profileSel.value = cfg.profile || "";
    }

    backdrop.querySelector("#cfg-close").addEventListener("click", close);
    backdrop.querySelector("#cfg-cancel").addEventListener("click", close);
    backdrop.querySelector("#cfg-save").addEventListener("click", () => {
      const name = nameEl.value.trim();
      if (!name) { window.Toast.show("설정 이름을 입력하세요", "error"); nameEl.focus(); return; }
      const list = loadConfigs();
      if (list.some((c) => c.name === name && c.name !== origName)) {
        window.Toast.show("이미 있는 이름입니다", "error");
        return;
      }
      const entry = { name, profile: profileSel.value, userPrompt: promptEl.value };
      if (mode === "edit") {
        const idx = list.findIndex((c) => c.name === origName);
        if (idx >= 0) list[idx] = entry; else list.push(entry);
      } else {
        list.push(entry);
      }
      window.Store.set(CONFIG_KEY, JSON.stringify(list));
      if (onSaved) onSaved(name);
      window.Toast.show(`'${name}' ${mode === "add" ? "저장" : "수정"}됨`, "success");
      close();
    });

    setTimeout(() => nameEl.focus(), 50);
  }

  // ────────────────────────────────────────────────────────────────
  // AI분석 — 직전 생성 SQL 로 최대 100행을 조회해 페르소나 프롬프트와 함께
  //   DBMS_CLOUD_AI.GENERATE(action=>'chat') 로 자연어 분석 결과를 만든다.
  //   · 페르소나: 서버 T_ANALYSIS_PERSONA (/api/personas CRUD).
  //   · 분석 실행: POST /api/nl2sql/analyze.
  // ────────────────────────────────────────────────────────────────
  const MOCK_PROFILES = ["AIF_NL2SQL_PROFILE", "OCI_GENERATE_PROFILE"];

  // 페르소나 목록 조회 — 서버 T_ANALYSIS_PERSONA (/api/personas). 실패 시 빈 배열.
  async function fetchPersonas() {
    try {
      const list = await window.API.get("/api/personas");
      return Array.isArray(list) ? list : [];
    } catch (e) {
      return [];
    }
  }

  // AI Profile 드롭다운 — 있으면 실제 /api/profiles(ENABLED), 실패/없으면 목업.
  async function fillProfileSelect(sel) {
    sel.innerHTML = `<option value="">불러오는 중…</option>`;
    let names = [];
    try {
      const profiles = await window.API.get("/api/profiles");
      names = (profiles || []).filter((p) => p.status === "ENABLED").map((p) => p.profile_name);
    } catch (e) {}
    if (!names.length) names = MOCK_PROFILES.slice();
    sel.innerHTML = "";
    names.forEach((nm) => {
      const o = document.createElement("option");
      o.value = nm;
      o.textContent = nm;
      sel.appendChild(o);
    });
    sel.value = names[0] || "";
  }

  function fillPersonaSelect(sel, list, selectId) {
    sel.innerHTML = "";
    if (!list.length) {
      sel.innerHTML = `<option value="">(등록된 페르소나 없음)</option>`;
      return;
    }
    list.forEach((p) => {
      const o = document.createElement("option");
      o.value = String(p.id);
      o.textContent = p.persona_name;
      sel.appendChild(o);
    });
    sel.value = selectId != null && list.some((p) => String(p.id) === String(selectId))
      ? String(selectId) : String(list[0].id);
  }

  // 분석 결과 렌더 — 분석 텍스트 + 복사 + 타이밍 + 접이식(사용한 프롬프트).
  function renderAnalysisResult(host, res, usedPrompt) {
    const analysis = (res && res.analysis) || "";
    host.innerHTML = "";
    const box = document.createElement("div");
    box.className = "panel";
    box.innerHTML = `<div class="panel-header"><h2>분석 결과</h2>
        <button class="btn btn-mini" id="an-copy" type="button">복사</button></div>`;
    const body = document.createElement("div");
    body.className = "panel-body";

    if (res && res.truncated) {
      const note = document.createElement("div");
      note.className = "muted";
      note.style.fontSize = "var(--fs-sm)";
      note.style.marginBottom = "var(--space-2)";
      note.textContent = "※ 최대 100행 기준으로 분석했습니다.";
      body.appendChild(note);
    }

    const pre = document.createElement("pre");
    pre.style.whiteSpace = "pre-wrap";
    pre.style.margin = "0";
    pre.textContent = analysis || "(빈 응답)";
    body.appendChild(pre);

    if (res && res.total_ms != null) {
      const ms = (v) => (v == null ? "-" : Number(v).toLocaleString() + " ms");
      const t = document.createElement("div");
      t.className = "muted";
      t.style.fontSize = "var(--fs-sm)";
      t.style.marginTop = "var(--space-2)";
      t.textContent = `총시간 ${ms(res.total_ms)} (데이터조회 ${ms(res.exec_ms)}, 분석생성 ${ms(res.gen_ms)})`;
      body.appendChild(t);
    }

    // 접이식: 사용한 프롬프트(서버가 조립한 최종 프롬프트 우선)
    const shownPrompt = (res && res.prompt) || usedPrompt || "";
    if (shownPrompt) {
      const det = document.createElement("details");
      det.style.marginTop = "var(--space-3)";
      const sum = document.createElement("summary");
      sum.className = "muted";
      sum.style.cursor = "pointer";
      sum.style.fontSize = "var(--fs-sm)";
      sum.textContent = "사용한 프롬프트";
      const ppre = document.createElement("pre");
      ppre.style.whiteSpace = "pre-wrap";
      ppre.textContent = shownPrompt;
      det.appendChild(sum);
      det.appendChild(ppre);
      body.appendChild(det);
    }

    box.appendChild(body);
    host.appendChild(box);
    box.querySelector("#an-copy").addEventListener("click", () => {
      navigator.clipboard.writeText(analysis).then(
        () => window.Toast.show("분석 결과 복사됨", "success"),
        () => window.Toast.show("복사 실패", "error")
      );
    });
  }

  // 공통 모달 셸 생성 (backdrop + Escape/✕ 닫기). 반환: {backdrop, close}
  function makeModal(innerHtml) {
    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    backdrop.innerHTML = innerHtml;
    const close = () => { backdrop.remove(); document.removeEventListener("keydown", onKey); };
    const onKey = (e) => { if (e.key === "Escape") close(); };
    document.addEventListener("keydown", onKey);
    document.body.appendChild(backdrop);
    return { backdrop, close };
  }

  // AI분석 팝업
  function openAnalyzeModal(lastResult) {
    const hasReal = lastResult && Array.isArray(lastResult.columns) && lastResult.columns.length &&
      Array.isArray(lastResult.rows) && lastResult.rows.length && lastResult.sql;
    if (!hasReal) {
      window.Toast.show("먼저 질문을 실행해 데이터를 조회하세요", "error");
      return;
    }
    const sql = lastResult.sql;
    const rowCount = lastResult.rows.length;

    const { backdrop, close } = makeModal(`
      <div class="modal" style="width:760px; max-width:94vw;">
        <div class="modal-header">
          <h2>AI 분석</h2>
          <button class="btn btn-ghost" id="an-close" type="button">✕</button>
        </div>
        <div class="modal-body stack">
          <div class="row" style="gap:var(--space-4);">
            <div class="stack-sm" style="flex:1;">
              <label>AI Profile</label>
              <select id="an-profile"></select>
            </div>
            <div class="stack-sm" style="flex:1;">
              <label>페르소나</label>
              <div class="row" style="gap:var(--space-2);">
                <select id="an-persona" style="flex:1;"></select>
                <button class="btn" id="an-persona-manage" type="button">관리</button>
              </div>
            </div>
          </div>
          <div class="stack-sm">
            <label>결과샘플 (분석 프롬프트 · 수정가능)</label>
            <textarea id="an-prompt" rows="8" style="font-family:var(--font-mono); font-size:var(--fs-sm);"></textarea>
            <span class="muted" style="font-size:var(--fs-sm);">※ [분석 시작] 시 직전 생성 SQL 로 최대 100행(현재 ${rowCount}행)을 조회해 위 프롬프트와 함께 분석합니다.</span>
          </div>
          <div id="an-result"><div class="empty-state muted">Profile·페르소나를 고르고 [분석 시작]을 누르세요.</div></div>
        </div>
        <div class="modal-footer row end" style="gap:var(--space-2);">
          <button class="btn" id="an-cancel" type="button">닫기</button>
          <button class="btn btn-primary" id="an-run" type="button">분석 시작</button>
        </div>
      </div>
    `);

    const profileSel = backdrop.querySelector("#an-profile");
    const personaSel = backdrop.querySelector("#an-persona");
    const promptEl = backdrop.querySelector("#an-prompt");
    const resultEl = backdrop.querySelector("#an-result");

    fillProfileSelect(profileSel);

    let personas = [];
    const applyPersona = () => {
      const p = personas.find((x) => String(x.id) === personaSel.value);
      promptEl.value = p ? p.prompt_tmpl : "";
    };
    const reloadPersonas = async (selectId) => {
      personas = await fetchPersonas();
      fillPersonaSelect(personaSel, personas, selectId);
      applyPersona();
    };
    reloadPersonas();
    personaSel.addEventListener("change", applyPersona);

    backdrop.querySelector("#an-persona-manage").addEventListener("click", () => {
      openPersonaManageModal(() => reloadPersonas(personaSel.value));
    });

    backdrop.querySelector("#an-close").addEventListener("click", close);
    backdrop.querySelector("#an-cancel").addEventListener("click", close);

    backdrop.querySelector("#an-run").addEventListener("click", async () => {
      const profile = profileSel.value;
      if (!profile) { window.Toast.show("AI Profile 을 선택하세요", "error"); return; }
      if (!promptEl.value.trim()) { window.Toast.show("분석 프롬프트가 비어 있습니다", "error"); return; }
      const runBtn = backdrop.querySelector("#an-run");
      runBtn.disabled = true;
      resultEl.innerHTML = `<div class="empty-state muted"><span class="spinner"></span> 분석 중…</div>`;
      let res;
      try {
        res = await window.API.post("/api/nl2sql/analyze", {
          sql, profile_name: profile, prompt: promptEl.value,
        });
      } catch (err) {
        resultEl.innerHTML = "";
        resultEl.appendChild(errBox(errMsg(err, "분석 실패")));
        return;
      } finally {
        runBtn.disabled = false;
      }
      if (res.error) {
        resultEl.innerHTML = "";
        resultEl.appendChild(errBox(res.error));
        return;
      }
      renderAnalysisResult(resultEl, res, promptEl.value);
    });

    setTimeout(() => profileSel.focus(), 50);
  }

  // 페르소나 관리 모달 (서버 T_ANALYSIS_PERSONA CRUD)
  function openPersonaManageModal(onSaved) {
    const { backdrop, close } = makeModal(`
      <div class="modal" style="width:860px; max-width:96vw;">
        <div class="modal-header">
          <h2>페르소나 관리</h2>
          <button class="btn btn-ghost" id="pm-close" type="button">✕</button>
        </div>
        <div class="modal-body row" style="gap:var(--space-4); align-items:stretch;">
          <div class="stack" style="flex:1; min-width:260px;">
            <div id="pm-list"></div>
            <button class="btn" id="pm-new" type="button">+ 새 페르소나</button>
          </div>
          <div class="stack" style="flex:1.3;">
            <div class="stack-sm"><label>이름</label><input type="text" id="pm-name" /></div>
            <div class="stack-sm"><label>설명</label><input type="text" id="pm-desc" /></div>
            <div class="stack-sm"><label>분석 프롬프트 템플릿</label>
              <textarea id="pm-tmpl" rows="10" style="font-family:var(--font-mono); font-size:var(--fs-sm);"></textarea></div>
          </div>
        </div>
        <div class="modal-footer row" style="justify-content:space-between; gap:var(--space-2);">
          <button class="btn btn-ghost" id="pm-delete" type="button">삭제</button>
          <div class="row" style="gap:var(--space-2);">
            <button class="btn" id="pm-close2" type="button">닫기</button>
            <button class="btn btn-primary" id="pm-save" type="button">저장</button>
          </div>
        </div>
      </div>
    `);

    const listEl = backdrop.querySelector("#pm-list");
    const nameEl = backdrop.querySelector("#pm-name");
    const descEl = backdrop.querySelector("#pm-desc");
    const tmplEl = backdrop.querySelector("#pm-tmpl");
    let list = [];
    let editingId = null;

    const fillForm = (p) => {
      editingId = p ? p.id : null;
      nameEl.value = p ? p.persona_name : "";
      descEl.value = p ? p.description || "" : "";
      tmplEl.value = p ? p.prompt_tmpl : "";
    };
    const renderList = () => {
      const cols = [
        { key: "persona_name", label: "이름" },
        { key: "description", label: "설명" },
      ];
      const table = window.SimpleTable.create(cols, list, {
        onRowClick: (row) => { fillForm(row); renderList(); },
        rowClassName: (row) => (row.id === editingId ? "selected" : ""),
        emptyText: "등록된 페르소나가 없습니다",
      });
      listEl.innerHTML = "";
      listEl.appendChild(table);
    };
    const reload = async (selectId) => {
      list = await fetchPersonas();
      const sel = list.find((p) => p.id === selectId);
      fillForm(sel || null);
      renderList();
    };
    reload();

    backdrop.querySelector("#pm-new").addEventListener("click", () => { fillForm(null); renderList(); });

    backdrop.querySelector("#pm-save").addEventListener("click", async () => {
      const name = nameEl.value.trim();
      if (!name) { window.Toast.show("이름을 입력하세요", "error"); nameEl.focus(); return; }
      if (!tmplEl.value.trim()) { window.Toast.show("프롬프트 템플릿을 입력하세요", "error"); return; }
      const body = { persona_name: name, description: descEl.value, prompt_tmpl: tmplEl.value };
      const btn = backdrop.querySelector("#pm-save");
      btn.disabled = true;
      try {
        if (editingId != null) await window.API.put(`/api/personas/${editingId}`, body);
        else await window.API.post("/api/personas", body);
      } catch (err) {
        window.Toast.show(errMsg(err, "저장 실패"), "error");
        return;
      } finally {
        btn.disabled = false;
      }
      window.Toast.show("저장됨", "success");
      await reload(editingId);
      if (onSaved) onSaved();
    });

    backdrop.querySelector("#pm-delete").addEventListener("click", async () => {
      if (editingId == null) { window.Toast.show("삭제할 페르소나를 목록에서 선택하세요", "error"); return; }
      try {
        await window.API.delete(`/api/personas/${editingId}`);
      } catch (err) {
        window.Toast.show(errMsg(err, "삭제 실패"), "error");
        return;
      }
      window.Toast.show("삭제됨", "success");
      await reload(null);
      if (onSaved) onSaved();
    });

    backdrop.querySelector("#pm-close").addEventListener("click", close);
    backdrop.querySelector("#pm-close2").addEventListener("click", close);
  }

  window.Views = window.Views || {};
  window.Views.nl2sql = render;
})();
