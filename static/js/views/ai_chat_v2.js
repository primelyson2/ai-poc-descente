/**
 * ai_chat_v2.js — 메뉴 [AI Chat v2]
 *
 * SELECT AI narrate 기반 대화형 화면. AI Chat(ai_chat.js, RUN_TEAM)과 소스 분리(향후 분기 대비).
 *   · Chat설정: v2 전용 저장소(aiChat2.savedConfigs) — profile 기반 {name,profile,userPrompt,mode,retentionDays}
 *   · 하단 입력: 질문 + (선택) '추출할 정보 Guide'
 *   · 전송: POST /api/chat2/send → GENERATE(action=>'narrate') 자연어 답
 *   · Guide 미입력 시 프롬프트의 '질문 답변을 위해 추출할 정보' 블록은 백엔드에서 제거
 */
(function () {
  const GREETING = "안녕하세요! Oracle AI Chat v2 입니다. Chat설정을 선택하고 질문을 입력하세요.";
  const CONFIG_KEY = "aiChat2.savedConfigs";   // v2 전용(Table list nl2sql.savedConfigs 와 분리)
  const DEFAULT_USER_PROMPT =
    "[INSTRUCTION]\n" +
    ">기준일: ##기준일##\n" +
    ">질문 답변을 위해 추출할 정보\n" +
    "테이블 형태로 다음 정보를 추출\n" +
    "- ##조회할 정보##\n\n" +
    "[QUESTION]\n" +
    "##메시지##";

  function errMsg(err, fallback) {
    const p = err && err.payload; const d = p && (p.detail || p.error);
    if (d) return typeof d === "string" ? d : (d.error || d.message || JSON.stringify(d));
    return (err && err.message) || fallback || "요청 실패";
  }
  function nowLabel() {
    const d = new Date();
    return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  }
  const loadConfigs = () => {
    try { return JSON.parse(window.Store.get(CONFIG_KEY)) || []; }
    catch (e) { return []; }
  };

  async function render() {
    const main = document.getElementById("main");
    main.innerHTML = "";

    const title = document.createElement("div");
    title.className = "view-title";
    title.innerHTML = `<h1>AI Chat v2</h1>
      <span class="sub">Chat설정으로 <strong>SELECT AI narrate</strong> 실행 · 질문 + (선택) 추출할 정보 Guide</span>`;
    main.appendChild(title);

    let multiTurn = false;
    let convId = "";

    const panel = document.createElement("div");
    panel.className = "panel chat-panel";
    panel.innerHTML = `
      <div class="panel-header chat-toolbar">
        <div class="row" style="gap:var(--space-3); align-items:center;">
          <label style="color:var(--text-muted); font-size:var(--fs-sm);">Chat설정</label>
          <select id="c2-config" style="min-width:200px;"></select>
          <button class="btn" id="c2-config-add" type="button">추가</button>
          <button class="btn" id="c2-config-update" type="button">수정</button>
        </div>
        <div class="row" style="gap:var(--space-3); align-items:center;">
          <button class="btn btn-ghost" id="c2-new">＋ 새 대화</button>
          <label style="color:var(--text-muted); font-size:var(--fs-sm);">Multi Turn</label>
          <button class="switch" id="c2-multiturn" type="button" role="switch" aria-checked="false"
            title="Multi Turn 대화 컨텍스트 유지 여부"><span class="switch-knob"></span></button>
        </div>
      </div>
      <div class="chat-messages" id="c2-messages"></div>
      <div class="chat-input-area" style="padding:var(--space-3); border-top:1px solid var(--border); display:flex; flex-direction:column; gap:8px;">
        <label style="font-size:var(--fs-sm); color:var(--text-muted);">질문</label>
        <div style="display:flex; gap:8px; align-items:flex-end;">
          <textarea id="c2-input" rows="1" placeholder="질문을 입력하세요 (Enter 전송, Shift+Enter 줄바꿈)" style="flex:1; font-family:inherit;"></textarea>
          <button class="btn btn-primary" id="c2-send" type="button">전송</button>
        </div>
        <label style="font-size:var(--fs-sm); color:var(--text-muted);">질문 답변을 위해 추출할 정보 <span class="muted">(선택)</span></label>
        <textarea id="c2-extract" rows="2" placeholder="예: 조직코드, 조직명, 전시횟수 — 비우면 프롬프트에서 해당 안내가 제거됩니다" style="font-family:inherit;"></textarea>
      </div>`;
    main.appendChild(panel);

    const messagesEl = panel.querySelector("#c2-messages");
    const inputEl = panel.querySelector("#c2-input");
    const extractEl = panel.querySelector("#c2-extract");
    const sendBtn = panel.querySelector("#c2-send");
    const configSel = panel.querySelector("#c2-config");
    let busy = false;

    const scrollToBottom = () => { messagesEl.scrollTop = messagesEl.scrollHeight; };

    function addMessage(role, text, debug) {
      const msg = document.createElement("div");
      msg.className = `chat-msg ${role}`;
      const bubble = document.createElement("div");
      bubble.className = "chat-bubble";
      bubble.textContent = text;
      const meta = document.createElement("div");
      meta.className = "chat-meta";
      const metaText = document.createElement("span");
      metaText.textContent = `${role === "user" ? "나" : "AI"} · ${nowLabel()}`;
      meta.appendChild(metaText);
      msg.appendChild(bubble);
      msg.appendChild(meta);
      if (debug) {
        const dbg = document.createElement("div");
        dbg.className = "chat-debug";
        const parts = [];
        if (debug.conversation_id) parts.push(`conv_id: ${debug.conversation_id}`);
        if (debug.elapsed_ms != null) parts.push(`elapsed: ${Number(debug.elapsed_ms).toLocaleString()} ms`);
        if (debug.mode) parts.push(`mode: ${debug.mode}`);
        parts.push(`multi turn: ${debug.multi_turn ? "ON" : "OFF"}`);
        dbg.textContent = "🛠 " + parts.join("  ·  ");
        msg.appendChild(dbg);
      }
      messagesEl.appendChild(msg);
      scrollToBottom();
      return msg;
    }
    function addTyping() {
      const msg = document.createElement("div");
      msg.className = "chat-msg bot";
      msg.innerHTML = `<div class="chat-bubble chat-typing"><span class="spinner"></span> 생성 중…</div>`;
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
      const cfgName = configSel.value;
      const cfg = cfgName ? loadConfigs().find((c) => c.name === cfgName) : null;
      if (!cfg) { window.Toast.show("Chat설정을 선택하세요 (없으면 [추가])", "warn"); return; }
      if (!cfg.profile) { window.Toast.show("설정에 AI Profile이 없습니다 — 수정에서 지정하세요", "error"); return; }

      busy = true; sendBtn.disabled = true;
      addMessage("user", text);
      inputEl.value = ""; autoGrow();
      const typing = addTyping();
      try {
        const res = await window.API.post("/api/chat2/send", {
          profile_name: cfg.profile,
          user_prompt: cfg.userPrompt || "",
          message: text,
          extract_info: extractEl.value || "",
          mode: cfg.mode || "dbms_cloud_ai",
          retention_days: cfg.retentionDays || 7,
          multi_turn: multiTurn,
          conversation_id: multiTurn ? convId : "",
        });
        typing.remove();
        if (multiTurn && res.conversation_id) convId = res.conversation_id;
        else if (!multiTurn) convId = "";
        if (res.error) {
          addMessage("bot", "오류: " + res.error, { mode: cfg.mode, multi_turn: multiTurn });
        } else {
          addMessage("bot", res.answer || "(빈 응답)", {
            conversation_id: res.conversation_id, elapsed_ms: res.elapsed_ms,
            mode: cfg.mode, multi_turn: multiTurn,
          });
        }
      } catch (e) {
        typing.remove();
        addMessage("bot", "오류: " + errMsg(e, "전송 실패"), { mode: cfg.mode, multi_turn: multiTurn });
      } finally {
        busy = false; sendBtn.disabled = false; inputEl.focus();
      }
    }

    function resetChat() {
      messagesEl.innerHTML = ""; convId = "";
      addMessage("bot", GREETING);
    }

    sendBtn.addEventListener("click", send);
    inputEl.addEventListener("input", autoGrow);
    inputEl.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } });
    panel.querySelector("#c2-new").addEventListener("click", resetChat);

    const multiTurnBtn = panel.querySelector("#c2-multiturn");
    function setMultiTurn(val) {
      multiTurn = !!val;
      multiTurnBtn.setAttribute("aria-checked", multiTurn ? "true" : "false");
      multiTurnBtn.classList.toggle("on", multiTurn);
    }
    multiTurnBtn.addEventListener("click", () => { setMultiTurn(!multiTurn); convId = ""; });

    // --- Chat설정 select + 추가/수정 ---
    const refreshConfigs = (selectName) => {
      const list = loadConfigs();
      configSel.innerHTML = "";
      if (list.length === 0) {
        const o = document.createElement("option");
        o.value = ""; o.textContent = "(저장된 설정 없음)";
        configSel.appendChild(o);
      } else {
        list.forEach((c) => {
          const o = document.createElement("option");
          o.value = c.name; o.textContent = c.name;
          configSel.appendChild(o);
        });
        if (selectName) configSel.value = selectName;
      }
    };
    panel.querySelector("#c2-config-add").addEventListener("click", () => {
      openConfigModal("add", { name: "", profile: "", userPrompt: DEFAULT_USER_PROMPT, mode: "dbms_cloud_ai", retentionDays: 7 }, refreshConfigs);
    });
    panel.querySelector("#c2-config-update").addEventListener("click", () => {
      const name = configSel.value;
      if (!name) { window.Toast.show("수정할 설정을 선택하세요", "warn"); return; }
      const found = loadConfigs().find((c) => c.name === name);
      if (!found) { window.Toast.show("저장된 설정을 찾을 수 없습니다", "error"); return; }
      openConfigModal("edit", found, refreshConfigs);
    });

    refreshConfigs();
    resetChat();
  }

  // Chat설정 입력/수정 팝업 (v2 전용, profile 기반). mode='add'|'edit'.
  async function openConfigModal(mode, cfg, onSaved) {
    const origName = cfg.name || "";
    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    backdrop.innerHTML = `
      <div class="modal" style="width:640px; max-width:92vw;">
        <div class="modal-header">
          <h2>Chat설정 ${mode === "add" ? "추가" : "수정"}</h2>
          <button class="btn btn-ghost" id="c2c-close" type="button">✕</button>
        </div>
        <div class="modal-body stack">
          <div class="stack-sm"><label>Chat설정</label><input type="text" id="c2c-name" placeholder="설정 이름" /></div>
          <div class="stack-sm"><label>AI Profile</label><select id="c2c-profile"></select></div>
          <div class="stack-sm">
            <label>호출Mode</label>
            <div class="row" style="gap:var(--space-4);">
              <label style="font-weight:400; display:flex; align-items:center; gap:6px; cursor:pointer;"><input type="radio" name="c2c-mode" value="dbms_cloud_ai"> dbms_cloud_ai</label>
              <label style="font-weight:400; display:flex; align-items:center; gap:6px; cursor:pointer;"><input type="radio" name="c2c-mode" value="select_ai"> select ai</label>
            </div>
          </div>
          <div class="stack-sm">
            <label>대화보관기간</label>
            <div class="row" style="gap:6px; align-items:center;">
              <input type="number" id="c2c-retention" min="7" step="1" style="width:100px;"> <span>일</span>
              <span class="muted" style="font-size:var(--fs-sm);">기본 7일. 7 이상만.</span>
            </div>
          </div>
          <div class="stack-sm">
            <label>User Prompt</label>
            <textarea id="c2c-prompt" rows="10" style="font-family:var(--font-mono); font-size:var(--fs-sm);"></textarea>
            <span class="muted" style="font-size:var(--fs-sm); line-height:1.7;">
              자리표시자 — 실행 시 자동 치환됩니다:<br>
              · <code>##기준일##</code> : 오늘 날짜(YYYYMMDD)<br>
              · <code>##조회할 정보##</code> : 화면의 <b>추출할 정보 Guide</b> 입력값 (비우면 해당 안내 블록 제거)<br>
              · <code>##메시지##</code> : 화면의 <b>질문</b> 입력값 <span class="muted">(필수)</span>
            </span>
          </div>
        </div>
        <div class="modal-footer row end" style="gap:var(--space-2);">
          <button class="btn" id="c2c-cancel" type="button">취소</button>
          <button class="btn btn-primary" id="c2c-save" type="button">저장</button>
        </div>
      </div>`;
    const close = () => { backdrop.remove(); document.removeEventListener("keydown", onKey); };
    const onKey = (e) => { if (e.key === "Escape") close(); };
    document.addEventListener("keydown", onKey);
    document.body.appendChild(backdrop);

    const nameEl = backdrop.querySelector("#c2c-name");
    const profileSel = backdrop.querySelector("#c2c-profile");
    const retEl = backdrop.querySelector("#c2c-retention");
    const promptEl = backdrop.querySelector("#c2c-prompt");
    nameEl.value = cfg.name || "";
    promptEl.value = cfg.userPrompt || "";
    retEl.value = (cfg.retentionDays != null ? cfg.retentionDays : 7);
    const initMode = cfg.mode === "select_ai" ? "select_ai" : "dbms_cloud_ai";
    const modeRadio = backdrop.querySelector(`input[name="c2c-mode"][value="${initMode}"]`);
    if (modeRadio) modeRadio.checked = true;
    const getMode = () => (backdrop.querySelector('input[name="c2c-mode"]:checked') || {}).value || "dbms_cloud_ai";

    profileSel.innerHTML = `<option value="">불러오는 중…</option>`;
    try {
      const profiles = await window.API.get("/api/profiles");
      const names = (profiles || []).filter((p) => p.status === "ENABLED").map((p) => p.profile_name);
      if (cfg.profile && !names.includes(cfg.profile)) names.unshift(cfg.profile);
      profileSel.innerHTML = "";
      if (names.length === 0) {
        profileSel.innerHTML = `<option value="">사용 가능한 Profile이 없습니다</option>`;
      } else {
        names.forEach((nm) => { const o = document.createElement("option"); o.value = nm; o.textContent = nm; profileSel.appendChild(o); });
      }
      profileSel.value = cfg.profile || (names[0] || "");
    } catch (e) {
      profileSel.innerHTML = "";
      const o = document.createElement("option"); o.value = cfg.profile || ""; o.textContent = cfg.profile || "Profile 목록 로드 실패";
      profileSel.appendChild(o); profileSel.value = cfg.profile || "";
    }

    backdrop.querySelector("#c2c-close").addEventListener("click", close);
    backdrop.querySelector("#c2c-cancel").addEventListener("click", close);
    backdrop.querySelector("#c2c-save").addEventListener("click", () => {
      const name = nameEl.value.trim();
      if (!name) { window.Toast.show("설정 이름을 입력하세요", "error"); nameEl.focus(); return; }
      const rd = parseInt(retEl.value, 10);
      if (!Number.isFinite(rd) || rd < 7) { window.Toast.show("대화보관기간은 7 이상이어야 합니다", "error"); retEl.focus(); return; }
      const list = loadConfigs();
      if (list.some((c) => c.name === name && c.name !== origName)) { window.Toast.show("이미 있는 이름입니다", "error"); return; }
      const entry = { name, profile: profileSel.value, userPrompt: promptEl.value, mode: getMode(), retentionDays: rd };
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

  window.Views = window.Views || {};
  window.Views.aiChatV2 = render;
})();
