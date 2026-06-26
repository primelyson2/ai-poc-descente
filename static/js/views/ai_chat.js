/** views/ai_chat.js — 메뉴 [AI Chat].
 * Chat설정(변수 / Team / User Prompt)을 골라 메시지를 보내면 백엔드(/api/chat/send)가
 * DBMS_CLOUD_AI_AGENT.RUN_TEAM 을 호출해 응답한다. Multi Turn ON 시 conversation_id 유지.
 */
(function () {
  const GREETING = "안녕하세요! Oracle AI Chat 입니다. Chat설정을 선택하고 메시지를 입력하세요.";
  // Team 드롭다운(설정 팝업)용 폴백 — /api/agents/tree 실패 시 사용
  const MOCK_TEAMS = ["SALES_ANALYST_TEAM", "DATA_DISCOVERY_TEAM", "SUPPORT_TEAM"];
  // 새 Chat설정 추가 시 기본값 (이미지 예시 기준)
  const DEFAULT_VARIABLES = "l_base_date VARCHAR2(8) := TO_CHAR(SYSDATE, 'YYYYMMDD');";
  const DEFAULT_USER_PROMPT =
    "[INSTRUCTION]\n" +
    "기준일: ' || l_base_date || '\n" +
    "action: showsql\n" +
    "결과형식: 컬럼명 한글\n\n" +
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

  // User Prompt 위험 패턴 점검 (차단 아님, 저장 시 경고용).
  // variables 는 PL/SQL 선언이라 ;/-- 가 정상이므로 검사 대상이 아니다.
  function userPromptWarnings(text) {
    const t = text || "";
    const issues = [];
    // 작은따옴표가 홀수면 PL/SQL 문자열 리터럴이 깨질 수 있음
    if (((t.match(/'/g) || []).length) % 2 === 1) {
      issues.push("작은따옴표(') 개수가 홀수 — 문자열이 깨질 수 있습니다 (변수 연결은 ' || 변수 || ' 형태로)");
    }
    if (/;/.test(t)) issues.push("세미콜론(;) 포함 — 프롬프트 안에서는 보통 불필요합니다");
    if (/--/.test(t)) issues.push("주석(--) 포함");
    if (/execute\s+immediate/i.test(t)) issues.push("EXECUTE IMMEDIATE 포함 — 임의 PL/SQL 실행 위험");
    return issues;
  }

  // 현재 시각 HH:MM
  function nowLabel() {
    const d = new Date();
    const hh = String(d.getHours()).padStart(2, "0");
    const mm = String(d.getMinutes()).padStart(2, "0");
    return `${hh}:${mm}`;
  }

  const nf = (v) => (v == null || v === "") ? v : Number(v).toLocaleString();

  // ====================================================================
  // Thinking 과정 popup — AI Agent Team Test [2. Team 실행] 탭과 동일한 카드 UI.
  // conversation_id 로 /api/agents/conversations/{id}/timeline 를 조회해 thinking 을 얻는다.
  // ====================================================================

  const THINK_CARET =
    '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="9 18 15 12 9 6"/></svg>';

  // 단계별 타임라인과 동일한 태그 배지(TEAM/TASK) + 이름 텍스트
  function thinkBadge(kind, name) {
    const wrap = document.createElement("span");
    wrap.className = "think-tagline";
    const tag = document.createElement("span");
    tag.className = "tree-tag tag-" + kind;
    tag.textContent = kind.toUpperCase();
    const label = document.createElement("span");
    label.className = "think-tagname";
    label.textContent = name;
    wrap.appendChild(tag);
    wrap.appendChild(label);
    return wrap;
  }

  // thinking({rows,error}) 을 host 에 카드로 렌더 (agent_test.renderThinking 과 동일 동작).
  function renderThinkingInto(host, thinking) {
    host.innerHTML = "";
    thinking = thinking || {};
    if (thinking.error) {
      const ta = document.createElement("textarea");
      ta.readOnly = true;
      ta.rows = 3;
      ta.style.width = "100%";
      ta.style.fontFamily = "var(--font-mono)";
      ta.style.fontSize = "var(--fs-sm)";
      ta.style.color = "var(--danger)";
      ta.value = "Thinking 조회 실패:\n" + thinking.error;
      host.appendChild(ta);
      return;
    }
    const rows = thinking.rows || [];
    if (!rows.length) {
      host.innerHTML = '<div class="empty-state muted">표시할 thinking 단계가 없습니다.</div>';
      return;
    }
    const stack = document.createElement("div");
    stack.className = "stack";
    rows.forEach((r) => {
      const card = document.createElement("div");
      card.className = "think-card";

      const headRow = document.createElement("button");
      headRow.type = "button";
      headRow.className = "think-row title think-head";
      headRow.setAttribute("aria-expanded", "false");

      const caret = document.createElement("span");
      caret.className = "think-caret";
      caret.innerHTML = THINK_CARET;

      const headMain = document.createElement("div");
      headMain.className = "think-head-main";

      const titleLine = document.createElement("div");
      titleLine.className = "think-title";
      const no = r.step_no != null ? `${nf(r.step_no)}. ` : "";
      titleLine.textContent = no + (r.step_title || "");

      const pathLine = document.createElement("div");
      pathLine.className = "think-path";
      if (r.team_name) pathLine.appendChild(thinkBadge("team", r.team_name));
      if (r.task_name) pathLine.appendChild(thinkBadge("task", r.task_name));

      headMain.appendChild(titleLine);
      headMain.appendChild(pathLine);
      headRow.appendChild(caret);
      headRow.appendChild(headMain);

      const promptRow = document.createElement("div");
      promptRow.className = "think-row prompt";
      promptRow.hidden = true;
      promptRow.textContent = r.raw_prompt == null ? "" : String(r.raw_prompt);

      headRow.addEventListener("click", () => {
        const open = card.classList.toggle("open");
        promptRow.hidden = !open;
        headRow.setAttribute("aria-expanded", open ? "true" : "false");
      });

      card.appendChild(headRow);
      card.appendChild(promptRow);
      stack.appendChild(card);
    });
    host.appendChild(stack);
  }

  // thinking 단계들을 복사용 평문으로 직렬화 (agent_test.buildThinkingText 와 동일 형식).
  function buildThinkingText(rows) {
    const clean = (s) => (s == null ? "" : String(s).replace(/\r\n?/g, "\n").trim());
    return rows.map((r, i) => {
      const no = r.step_no != null ? r.step_no : i + 1;
      const title = clean(r.step_title);
      const path = [
        r.team_name ? `TEAM: ${r.team_name}` : "",
        r.task_name ? `TASK: ${r.task_name}` : "",
      ].filter(Boolean).join("  |  ");
      const body = clean(r.raw_prompt);
      return [`### Step ${no}. ${title}`.trim(), path, "", body]
        .filter((x, idx) => !(idx === 1 && !path)).join("\n");
    }).join("\n\n---\n\n");
  }

  async function copyToClipboard(text) {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
        return true;
      }
    } catch (e) { /* 폴백 */ }
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.left = "-9999px";
      document.body.appendChild(ta);
      ta.focus();
      ta.select();
      const ok = document.execCommand("copy");
      ta.remove();
      return ok;
    } catch (e) {
      return false;
    }
  }

  // conversation_id 로 thinking 을 조회해 모달로 표시.
  // preThinking: 전송 응답에 동봉돼 이미 받은 thinking({rows,error}). 있으면 추가 왕복 없이 즉시 표시.
  async function openThinkingModal(convId, preThinking) {
    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    backdrop.innerHTML = `
      <div class="modal" style="width:820px; max-width:94vw;">
        <div class="modal-header">
          <h2>Thinking 과정 <span class="muted" style="font-weight:400; font-size:var(--fs-sm);">conv_id: ${window.escapeHtml(convId)}</span></h2>
          <div class="row" style="gap:var(--space-2);">
            <button class="btn btn-ghost" id="thk-copy" type="button" disabled>복사</button>
            <button class="btn btn-ghost" id="thk-close" type="button">✕</button>
          </div>
        </div>
        <div class="modal-body" id="thk-body">
          <div class="empty-state"><span class="spinner"></span> 조회 중...</div>
        </div>
      </div>
    `;
    const close = () => { backdrop.remove(); document.removeEventListener("keydown", onKey); };
    const onKey = (e) => { if (e.key === "Escape") close(); };
    // 바깥 클릭으로는 닫지 않음 — 닫기는 X 버튼으로만 (실수 닫힘 방지)
    backdrop.querySelector("#thk-close").addEventListener("click", close);
    document.addEventListener("keydown", onKey);
    document.body.appendChild(backdrop);

    const body = backdrop.querySelector("#thk-body");
    const copyBtn = backdrop.querySelector("#thk-copy");
    let thinking = { rows: [], error: null };
    if (preThinking && (preThinking.rows || preThinking.error)) {
      // 전송 응답에 동봉된 데이터 즉시 사용 (왕복 없음)
      thinking = preThinking;
    } else {
      try {
        const data = await window.API.get(`/api/agents/conversations/${encodeURIComponent(convId)}/timeline`);
        thinking = data.thinking || { rows: [], error: null };
      } catch (e) {
        if (backdrop.isConnected) body.innerHTML = '<div class="empty-state muted">Thinking 조회 실패</div>';
        return;
      }
    }
    if (!backdrop.isConnected) return;
    renderThinkingInto(body, thinking);

    const rows = thinking.rows || [];
    if (rows.length) {
      copyBtn.disabled = false;
      copyBtn.addEventListener("click", async () => {
        const ok = await copyToClipboard(buildThinkingText(rows));
        window.Toast.show(ok ? `Thinking ${rows.length}단계 복사됨` : "복사 실패", ok ? "success" : "error");
      });
    }
  }

  async function render() {
    const main = document.getElementById("main");
    main.innerHTML = "";

    const title = document.createElement("div");
    title.className = "view-title";
    title.innerHTML = `<h1>AI Chat</h1>
      <span class="sub">Chat설정의 Team 으로 <strong>RUN_TEAM</strong> 호출 · Multi Turn 시 대화 컨텍스트 유지</span>`;
    main.appendChild(title);

    // Team 드롭다운(설정 팝업 안)용 목록 — /api/agents/tree 실패 시 목업으로 진행.
    let teams = MOCK_TEAMS.slice();
    try {
      const tree = await window.API.get("/api/agents/tree");
      const names = (tree.teams || []).map((t) => t.name).filter(Boolean);
      if (names.length) teams = names;
    } catch (e) {
      teams = MOCK_TEAMS.slice();
    }

    let multiTurn = false;  // Multi Turn 활성/비활성 상태
    let convId = "";        // Multi Turn ON 시 유지되는 conversation_id

    const panel = document.createElement("div");
    panel.className = "panel chat-panel";
    panel.innerHTML = `
      <div class="panel-header chat-toolbar">
        <div class="row" style="gap:var(--space-3); align-items:center;">
          <label style="color:var(--text-muted); font-size:var(--fs-sm);">Chat설정</label>
          <select id="chat-config" style="min-width:200px;"></select>
          <button class="btn" id="chat-config-add" type="button">추가</button>
          <button class="btn" id="chat-config-update" type="button">수정</button>
        </div>
        <div class="row" style="gap:var(--space-3); align-items:center;">
          <button class="btn btn-ghost" id="chat-new">＋ 새 대화</button>
          <label style="color:var(--text-muted); font-size:var(--fs-sm);">Multi Turn</label>
          <button class="switch" id="chat-multiturn" type="button"
            role="switch" aria-checked="false" title="Multi Turn 대화 컨텍스트 유지 여부">
            <span class="switch-knob"></span>
          </button>
        </div>
      </div>
      <div class="chat-messages" id="chat-messages"></div>
      <div class="chat-saved-row">
        <input type="text" id="chat-save-title" placeholder="저장할 제목" />
        <button class="btn" id="chat-save-add" type="button">추가</button>
        <button class="btn" id="chat-save-update" type="button">수정</button>
        <select id="chat-saved"></select>
      </div>
      <div class="chat-input-row">
        <textarea id="chat-input" rows="1" placeholder="메시지를 입력하세요 (Enter 전송, Shift+Enter 줄바꿈)"></textarea>
        <button class="btn btn-primary" id="chat-send">전송</button>
      </div>
    `;
    main.appendChild(panel);

    const messagesEl = panel.querySelector("#chat-messages");
    const inputEl = panel.querySelector("#chat-input");
    const sendBtn = panel.querySelector("#chat-send");

    let busy = false;

    function scrollToBottom() {
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    // debug: 디버깅용 메타 정보 객체 (conv_id, elapsed_ms, team, multi_turn 등). 있으면 말풍선 아래 표시.
    function addMessage(role, text, debug) {
      const msg = document.createElement("div");
      msg.className = `chat-msg ${role}`;
      const bubble = document.createElement("div");
      bubble.className = "chat-bubble";
      bubble.textContent = text;  // 텍스트로만 삽입 (XSS 방지, 줄바꿈은 CSS pre-wrap)
      const meta = document.createElement("div");
      meta.className = "chat-meta";
      const metaText = document.createElement("span");
      metaText.textContent = `${role === "user" ? "나" : "AI"} · ${nowLabel()}`;
      meta.appendChild(metaText);
      // conversation_id 가 있으면 메타("AI · 시각") 옆에 Thinking 과정 popup 버튼 추가
      if (debug && debug.conversation_id) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "btn btn-ghost btn-mini";
        btn.textContent = "🧠 Thinking";
        // 전송 응답에 동봉된 thinking 을 그대로 넘겨 추가 왕복 제거
        btn.addEventListener("click", () => openThinkingModal(debug.conversation_id, debug.thinking));
        meta.appendChild(btn);
      }
      msg.appendChild(bubble);
      msg.appendChild(meta);
      if (debug) msg.appendChild(buildDebug(debug));
      // 단계별 소요시간 인라인 (접이식) — timeline 이 있으면 답변 아래에 표시
      if (debug && debug.timeline && debug.timeline.length) {
        msg.appendChild(buildStepTimes(debug.timeline, debug.multi_turn));
      }
      messagesEl.appendChild(msg);
      scrollToBottom();
      return msg;
    }

    // 디버깅 정보 라인 — conversation_id / elapsed / team / multi turn.
    function buildDebug(d) {
      const el = document.createElement("div");
      el.className = "chat-debug";
      const parts = [];
      if (d.conversation_id) parts.push(`conv_id: ${d.conversation_id}`);
      if (d.elapsed_ms != null) parts.push(`elapsed: ${Number(d.elapsed_ms).toLocaleString()} ms`);
      if (d.team) parts.push(`team: ${d.team}`);
      parts.push(`multi turn: ${d.multi_turn ? "ON" : "OFF"}`);
      el.textContent = "🛠 " + parts.join("  ·  ");
      return el;
    }

    // 단계별 소요시간 — Agent Team Test 2탭과 동일한 timeline 데이터를 접이식 목록으로.
    // 트리 들여쓰기(level) + 타입 배지(TEAM/AGENT/TASK/TOOL) + 구간 ms.
    function buildStepTimes(timeline, multiTurnOn) {
      const details = document.createElement("details");
      details.className = "chat-steptimes";
      const total = Math.max(0, ...timeline.map((t) => t.end_ms || 0));
      const summary = document.createElement("summary");
      summary.textContent = `⏱ 단계별 시간 (${timeline.length}단계 · 총 ${nf(total)} ms)`
        + (multiTurnOn ? " · 이 대화 누적" : "");
      details.appendChild(summary);

      const list = document.createElement("div");
      list.className = "steptimes-list";
      timeline.forEach((seg) => {
        const level = seg.level || 0;
        const row = document.createElement("div");
        row.className = "steptimes-row";
        const label = document.createElement("span");
        label.className = "steptimes-label";
        label.style.paddingLeft = `${level * 16}px`;
        if (seg.type) {
          const tag = document.createElement("span");
          tag.className = "tree-tag tag-" + seg.type;
          tag.textContent = seg.type.toUpperCase();
          label.appendChild(tag);
          label.appendChild(document.createTextNode(" "));
        }
        label.appendChild(document.createTextNode(seg.label || ""));
        const dur = document.createElement("span");
        dur.className = "steptimes-dur";
        dur.textContent = `${nf((seg.end_ms || 0) - (seg.start_ms || 0))} ms`;
        row.appendChild(label);
        row.appendChild(dur);
        list.appendChild(row);
      });
      details.appendChild(list);
      return details;
    }

    function addTyping() {
      const msg = document.createElement("div");
      msg.className = "chat-msg bot";
      msg.innerHTML = `<div class="chat-bubble chat-typing"><span></span><span></span><span></span></div>`;
      messagesEl.appendChild(msg);
      scrollToBottom();
      return msg;
    }

    function autoGrow() {
      inputEl.style.height = "auto";
      inputEl.style.height = Math.min(inputEl.scrollHeight, 160) + "px";
    }

    async function send() {
      const text = inputEl.value.trim();
      if (!text || busy) return;

      // 선택된 Chat설정 확보 (변수/Team/User Prompt 의 출처)
      const cfgName = configSel.value;
      const cfg = cfgName ? loadConfigs().find((c) => c.name === cfgName) : null;
      if (!cfg) {
        window.Toast.show("Chat설정을 선택하세요 (없으면 [추가])", "warn");
        return;
      }

      busy = true;
      sendBtn.disabled = true;

      addMessage("user", text);
      inputEl.value = "";
      autoGrow();

      const typing = addTyping();
      try {
        const res = await window.API.post("/api/chat/send", {
          team: cfg.team,
          variables: cfg.variables,
          user_prompt: cfg.userPrompt,
          message: text,
          multi_turn: multiTurn,
          // Multi Turn ON 이면 직전 conversation_id 를 넘겨 컨텍스트 유지
          conversation_id: multiTurn ? convId : "",
        });
        typing.remove();
        if (multiTurn && res.conversation_id) convId = res.conversation_id;
        else if (!multiTurn) convId = "";
        addMessage("bot", res.answer || "(빈 응답)", {
          conversation_id: res.conversation_id,
          elapsed_ms: res.elapsed_ms,
          team: cfg.team,
          multi_turn: multiTurn,
          timeline: res.timeline || [],
          thinking: res.thinking || { rows: [], error: null },
        });
      } catch (e) {
        typing.remove();
        addMessage("bot", "오류: " + errMsg(e, "전송 실패"), {
          team: cfg.team,
          multi_turn: multiTurn,
        });
      } finally {
        busy = false;
        sendBtn.disabled = false;
        inputEl.focus();
      }
    }

    function resetChat() {
      messagesEl.innerHTML = "";
      convId = "";  // 새 대화 → conversation 초기화
      addMessage("bot", GREETING);
    }

    sendBtn.addEventListener("click", send);
    inputEl.addEventListener("input", autoGrow);
    inputEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        send();
      }
    });
    // Multi Turn 토글 — ON 이면 .on 클래스로 색상/노브 위치가 바뀐다.
    const multiTurnBtn = panel.querySelector("#chat-multiturn");
    function setMultiTurn(val) {
      multiTurn = !!val;
      multiTurnBtn.setAttribute("aria-checked", multiTurn ? "true" : "false");
      multiTurnBtn.classList.toggle("on", multiTurn);
    }
    multiTurnBtn.addEventListener("click", () => {
      setMultiTurn(!multiTurn);
      convId = "";  // 모드 전환 시 대화 컨텍스트 초기화 (다음 전송부터 새 conversation)
    });

    panel.querySelector("#chat-new").addEventListener("click", resetChat);

    // --- Chat설정 저장/불러오기 (localStorage, 세션 간 유지) ---
    // 하나의 설정은 현재 채팅 구성(현재는 Multi Turn 상태)을 담는다.
    const CONFIG_KEY = "aiChat.savedConfigs";
    const configSel = panel.querySelector("#chat-config");
    const configAddBtn = panel.querySelector("#chat-config-add");
    const configUpdateBtn = panel.querySelector("#chat-config-update");

    const loadConfigs = () => {
      try { return JSON.parse(window.Store.get(CONFIG_KEY)) || []; }
      catch (e) { return []; }
    };
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

    // 추가 — 빈 팝업을 열어 새 설정을 입력받아 저장
    configAddBtn.addEventListener("click", () => {
      openConfigModal("add", {
        name: "",
        team: teams[0] || "",
        variables: DEFAULT_VARIABLES,
        userPrompt: DEFAULT_USER_PROMPT,
      });
    });

    // 수정 — 드롭다운에서 선택한 설정을 팝업에 채워서 수정
    configUpdateBtn.addEventListener("click", () => {
      const name = configSel.value;
      if (!name) { window.Toast.show("수정할 설정을 선택하세요", "error"); return; }
      const found = loadConfigs().find((c) => c.name === name);
      if (!found) { window.Toast.show("저장된 설정을 찾을 수 없습니다", "error"); return; }
      openConfigModal("edit", found);
    });

    // 설정 입력/수정 팝업. mode='add'|'edit', cfg=초기값({name,team,variables,userPrompt})
    function openConfigModal(mode, cfg) {
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
              <label>Team</label>
              <select id="cfg-team"></select>
            </div>
            <div class="stack-sm">
              <label>변수</label>
              <textarea id="cfg-variables" rows="3" style="font-family:var(--font-mono); font-size:var(--fs-sm);"></textarea>
            </div>
            <div class="stack-sm">
              <label>User Prompt</label>
              <textarea id="cfg-prompt" rows="8" style="font-family:var(--font-mono); font-size:var(--fs-sm);"></textarea>
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
      // 바깥 클릭으로는 닫지 않음 — 닫기는 X 버튼으로만 (실수 닫힘 방지)
      document.addEventListener("keydown", onKey);
      document.body.appendChild(backdrop);

      // Team 드롭다운 채우기 (현재 값이 목록에 없으면 보존)
      const teamSel = backdrop.querySelector("#cfg-team");
      const teamOpts = teams.slice();
      if (cfg.team && !teamOpts.includes(cfg.team)) teamOpts.unshift(cfg.team);
      teamOpts.forEach((t) => {
        const o = document.createElement("option");
        o.value = t; o.textContent = t;
        teamSel.appendChild(o);
      });

      const nameEl = backdrop.querySelector("#cfg-name");
      const varsEl = backdrop.querySelector("#cfg-variables");
      const promptEl = backdrop.querySelector("#cfg-prompt");
      nameEl.value = cfg.name || "";
      teamSel.value = cfg.team || "";
      varsEl.value = cfg.variables || "";
      promptEl.value = cfg.userPrompt || "";

      backdrop.querySelector("#cfg-close").addEventListener("click", close);
      backdrop.querySelector("#cfg-cancel").addEventListener("click", close);
      backdrop.querySelector("#cfg-save").addEventListener("click", () => {
        const name = nameEl.value.trim();
        if (!name) { window.Toast.show("설정 이름을 입력하세요", "error"); nameEl.focus(); return; }
        const list = loadConfigs();
        // 중복 이름 검사 — 수정 시 자기 자신(원래 이름)은 제외
        if (list.some((c) => c.name === name && c.name !== origName)) {
          window.Toast.show("이미 있는 이름입니다", "error");
          return;
        }
        const entry = { name, team: teamSel.value, variables: varsEl.value, userPrompt: promptEl.value };
        if (mode === "edit") {
          const idx = list.findIndex((c) => c.name === origName);
          if (idx >= 0) list[idx] = entry; else list.push(entry);
        } else {
          list.push(entry);
        }
        window.Store.set(CONFIG_KEY, JSON.stringify(list));
        refreshConfigs(name);
        // 위험 패턴은 차단하지 않고 경고만 (저장은 진행) — PoC, 작성자는 신뢰된 테스터
        const warns = userPromptWarnings(promptEl.value);
        if (warns.length) {
          window.Toast.show(`저장됨 (주의: ${warns[0]})`, "warn");
        } else {
          window.Toast.show(`'${name}' ${mode === "add" ? "저장" : "수정"}됨`, "success");
        }
        close();
      });

      setTimeout(() => nameEl.focus(), 50);
    }

    // --- 메시지 저장/불러오기 (localStorage, 세션 간 유지) ---
    const SAVED_KEY = "aiChat.savedMessages";
    const saveTitle = panel.querySelector("#chat-save-title");
    const saveAddBtn = panel.querySelector("#chat-save-add");
    const saveUpdateBtn = panel.querySelector("#chat-save-update");
    const savedSel = panel.querySelector("#chat-saved");

    const loadSaved = () => {
      try { return JSON.parse(window.Store.get(SAVED_KEY)) || []; }
      catch (e) { return []; }
    };
    const refreshSaved = (selectTitle) => {
      const list = loadSaved();
      savedSel.innerHTML = "";
      const ph = document.createElement("option");
      ph.value = "";
      ph.textContent = list.length ? "저장된 메시지…" : "(저장된 메시지 없음)";
      savedSel.appendChild(ph);
      list.forEach((m) => {
        const o = document.createElement("option");
        o.value = m.title;
        o.textContent = m.title;
        savedSel.appendChild(o);
      });
      if (selectTitle != null) savedSel.value = selectTitle;
    };
    refreshSaved();

    // 추가 — 제목칸의 새 title 로 현재 입력 메시지를 신규 저장 (중복 title 거부)
    saveAddBtn.addEventListener("click", () => {
      const title = saveTitle.value.trim();
      const text = inputEl.value;
      if (!title) { window.Toast.show("추가할 제목을 입력하세요", "error"); saveTitle.focus(); return; }
      if (!text.trim()) { window.Toast.show("저장할 메시지가 비어 있습니다", "error"); return; }
      const list = loadSaved();
      if (list.some((m) => m.title === title)) {
        window.Toast.show("이미 있는 제목입니다. [수정]을 사용하세요", "error");
        return;
      }
      list.push({ title, text });
      window.Store.set(SAVED_KEY, JSON.stringify(list));
      refreshSaved(title);
      saveTitle.value = "";
      window.Toast.show(`'${title}' 저장됨`, "success");
    });

    // 수정 — 콤보에서 선택한 기존 title 의 메시지를 현재 입력 내용으로 갱신
    saveUpdateBtn.addEventListener("click", () => {
      const title = savedSel.value;
      if (!title) { window.Toast.show("수정할 항목을 콤보에서 선택하세요", "error"); return; }
      const text = inputEl.value;
      if (!text.trim()) { window.Toast.show("저장할 메시지가 비어 있습니다", "error"); return; }
      const list = loadSaved();
      const idx = list.findIndex((m) => m.title === title);
      if (idx < 0) { window.Toast.show("저장된 항목을 찾을 수 없습니다", "error"); return; }
      list[idx].text = text;
      window.Store.set(SAVED_KEY, JSON.stringify(list));
      window.Toast.show(`'${title}' 수정됨`, "success");
    });

    // 선택 — 저장된 메시지를 입력창으로 불러오기
    savedSel.addEventListener("change", () => {
      const title = savedSel.value;
      if (!title) return;
      const found = loadSaved().find((m) => m.title === title);
      if (found) { inputEl.value = found.text; autoGrow(); inputEl.focus(); }
    });

    // 초기 인사
    addMessage("bot", GREETING);
    setTimeout(() => inputEl.focus(), 50);
  }

  window.Views = window.Views || {};
  window.Views.aiChat = render;
})();
