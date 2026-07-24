/** views/ai_chat_tl.js — 메뉴 [Select AI Test - AI Chat for Table list] (prompt11).
 * ai_chat.js 를 기반으로 하되(소스 분리 — 추후 기능 분리 대비 공유하지 않음),
 * 백엔드(/api/chat_tl/send)가 RUN_TEAM 답변(JSON: answers[{title,sql}])의 SQL 들을
 * 각각 실행해 주면 결과를 table 형태(5행 미리보기 + 전체 CSV 다운로드)로 표시한다.
 */
(function () {
  const GREETING = "안녕하세요! AI Chat for Table list 입니다. Chat설정을 선택하고 질문을 입력하면 SQL 실행 결과를 표로 보여드립니다.";
  // Team 드롭다운(설정 팝업)용 폴백 — /api/agents/tree 실패 시 사용
  const MOCK_TEAMS = ["SALES_ANALYST_TEAM", "DATA_DISCOVERY_TEAM", "SUPPORT_TEAM"];
  // 새 Chat설정 추가 시 기본값 — agent 가 아래 JSON 형식만 반환하도록 지시한다.
  // (PL/SQL 문자열 리터럴에 들어가므로 작은따옴표는 ' || 변수 || ' 연결 외에는 쓰지 않는다)
  const DEFAULT_VARIABLES = "l_base_date VARCHAR2(8) := TO_CHAR(SYSDATE, 'YYYYMMDD');";
  const DEFAULT_USER_PROMPT =
    "[INSTRUCTION]\n" +
    "기준일: ' || l_base_date || '\n" +
    "이 작업은 반드시 SQL Tool 호출로 시작합니다. Tool 호출 없이 답변을 작성하지 마세요.\n" +
    "- SQL Tool 호출 시 ACTION 은 반드시 정확히 \"showsql\" 을 사용합니다 (SQL 생성만, 실행 금지).\n" +
    "- 단순한 질문(하나의 SQL 로 답변 가능)은 1회, 복잡한 질문은 질문을 분해해 여러 번 호출합니다.\n" +
    "- 테이블/컬럼 이름을 직접 추측해 만들지 마세요. SQL Tool 이 반환한 SQL 만 사용합니다.\n" +
    "[최종 답변] 반드시 아래 JSON 형식만 반환합니다. JSON 외 다른 텍스트/마크다운/설명 금지.\n" +
    '{"answers": [{"title": "이 SQL 이 조회하는 내용 한 줄 설명", "sql": "SELECT ..."}], "note": "여러 SQL 결과를 종합할 때 참고할 설명(선택, 없으면 생략)"}\n\n' +
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
    if (/execute\s+immediate/i.test(t)) issues.push("EXECUTE IMMEDIATE 포함 — 임의 PL/SQL 실행 위험");
    return issues;
  }

  // 전송 시 백엔드가 실행하는 RUN_TEAM 익명블록을 재현(미리보기용).
  // app/plsql.py:build_run_team_block + app/routers/chat_tl.py:_user_prompt_expr 와 동일 규칙.
  function buildChatScript(team, variables, userPrompt) {
    const MSG_PH = "##메시지##";
    const up = userPrompt || "";
    const useMsg = up.includes(MSG_PH);
    const src = useMsg ? up.split(MSG_PH).join("' || :msg || '") : up;
    const userPromptSql = "'" + src + "'";
    const decls = (variables || "").trim();
    const declLine = decls ? "\n  " + decls : "";
    return (
      "DECLARE\n" +
      "  l_conv_id     VARCHAR2(256);\n" +
      "  l_answer      CLOB;\n" +
      "  l_user_prompt CLOB;" + declLine + "\n" +
      "BEGIN\n" +
      "  l_conv_id := DBMS_CLOUD_AI.CREATE_CONVERSATION();  -- Multi Turn 재사용 시 :in_conv\n" +
      "  l_user_prompt := " + userPromptSql + ";\n" +
      "  l_answer := DBMS_CLOUD_AI_AGENT.RUN_TEAM(\n" +
      "    team_name   => :team_name,\n" +
      "    user_prompt => l_user_prompt,\n" +
      "    params      => '{\"conversation_id\":\"' || l_conv_id || '\"}'\n" +
      "  );\n" +
      "  :out_conv := l_conv_id;\n" +
      "  :out_answer := l_answer;\n" +
      "END;\n" +
      "-- 이후 앱이 answer(JSON) 의 SQL 들을 각각 실행해 표로 표시합니다."
    );
  }

  // 스크립트 조회 팝업 — 실행 스크립트를 읽기전용으로 보여주고 복사 제공.
  function openScriptModal(title, team, script) {
    const esc = window.escapeHtml || ((v) => String(v == null ? "" : v));
    const bd = document.createElement("div");
    bd.className = "modal-backdrop";
    bd.innerHTML = `
      <div class="modal" style="width:720px; max-width:94vw;">
        <div class="modal-header">
          <h2>${esc(title)}</h2>
          <button class="btn btn-ghost" id="sc-close" type="button">✕</button>
        </div>
        <div class="modal-body stack">
          <label class="muted" style="font-size:var(--fs-sm);">전송 시 실행되는 스크립트입니다. 바인드: <code>:team_name</code> = '${esc(team || "")}', <code>:msg</code> = 입력 메시지.</label>
          <textarea readonly rows="16" style="font-family:var(--font-mono); font-size:var(--fs-sm); width:100%;">${esc(script)}</textarea>
        </div>
        <div class="modal-footer row end" style="gap:var(--space-2);">
          <button class="btn" id="sc-copy" type="button">복사</button>
          <button class="btn btn-primary" id="sc-ok" type="button">닫기</button>
        </div>
      </div>`;
    const close = () => bd.remove();
    document.body.appendChild(bd);
    // 바깥(어두운 영역) 클릭 시 닫기 — 미리보기라 실수 닫힘 허용
    bd.addEventListener("click", (e) => { if (e.target === bd) close(); });
    bd.querySelector("#sc-close").addEventListener("click", close);
    bd.querySelector("#sc-ok").addEventListener("click", close);
    bd.querySelector("#sc-copy").addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(script); window.Toast.show("스크립트를 복사했습니다", "success"); }
      catch (_) { window.Toast.show("복사 실패 — 텍스트를 직접 선택해 복사하세요", "error"); }
    });
  }

  // 현재 시각 HH:MM
  function nowLabel() {
    const d = new Date();
    const hh = String(d.getHours()).padStart(2, "0");
    const mm = String(d.getMinutes()).padStart(2, "0");
    return `${hh}:${mm}`;
  }

  const nf = (v) => (v == null || v === "") ? v : Number(v).toLocaleString();

  // 결과 테이블 → CSV 다운로드 (Excel 호환 위해 BOM 추가) — nl2sql.js downloadCsv 와 동일 방식
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
    a.download = (baseName || "ai_chat_tl").replace(/[^\w가-힣.-]+/g, "_") + ".csv";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  // ====================================================================
  // Thinking 과정 popup — AI Agent Team Test [2. Team 실행] 탭과 동일한 카드 UI.
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
    title.innerHTML = `<h1>AI Chat for Table list</h1>
      <span class="sub">Chat설정의 Team 으로 <strong>RUN_TEAM</strong> 호출(showsql) → 반환된 SQL 을 실행해 <strong>표</strong>로 답변 · 5행 미리보기 + 전체 CSV 다운로드</span>`;
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

    let multiTurn = true;   // Multi Turn 활성/비활성 상태 (이 메뉴는 기본 ON)
    let convId = "";        // Multi Turn ON 시 유지되는 conversation_id

    const panel = document.createElement("div");
    panel.className = "panel chat-panel";
    panel.innerHTML = `
      <div class="panel-header chat-toolbar">
        <div class="row" style="gap:var(--space-3); align-items:center;">
          <label style="color:var(--text-muted); font-size:var(--fs-sm);">Chat설정</label>
          <select id="ctl-config" style="min-width:200px;"></select>
          <button class="btn" id="ctl-config-add" type="button">추가</button>
          <button class="btn" id="ctl-config-update" type="button">수정</button>
        </div>
        <div class="row" style="gap:var(--space-3); align-items:center;">
          <button class="btn btn-ghost" id="ctl-new">＋ 새 대화</button>
          <label style="color:var(--text-muted); font-size:var(--fs-sm);">Multi Turn</label>
          <button class="switch" id="ctl-multiturn" type="button"
            role="switch" aria-checked="false" title="Multi Turn 대화 컨텍스트 유지 여부">
            <span class="switch-knob"></span>
          </button>
        </div>
      </div>
      <div class="chat-messages" id="ctl-messages"></div>
      <div class="chat-saved-row">
        <input type="text" id="ctl-save-title" placeholder="저장할 제목" />
        <button class="btn" id="ctl-save-add" type="button">추가</button>
        <button class="btn" id="ctl-save-update" type="button">수정</button>
        <button class="btn" id="ctl-save-delete" type="button">삭제</button>
        <select id="ctl-saved"></select>
      </div>
      <div class="chat-input-row">
        <textarea id="ctl-input" rows="1" placeholder="질문을 입력하세요 (Enter 전송, Shift+Enter 줄바꿈)"></textarea>
        <button class="btn btn-primary" id="ctl-send">전송</button>
      </div>
    `;
    main.appendChild(panel);

    const messagesEl = panel.querySelector("#ctl-messages");
    const inputEl = panel.querySelector("#ctl-input");
    const sendBtn = panel.querySelector("#ctl-send");

    let busy = false;

    function scrollToBottom() {
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    // debug: 디버깅용 메타 정보 객체 (conv_id, elapsed_ms, team, multi_turn 등). 있으면 말풍선 아래 표시.
    // content 가 DOM 노드면 그대로 삽입(표 답변), 문자열이면 텍스트로 삽입(XSS 방지).
    function addMessage(role, content, debug) {
      const msg = document.createElement("div");
      msg.className = `chat-msg ${role}`;
      const bubble = document.createElement("div");
      bubble.className = "chat-bubble";
      if (content instanceof Node) bubble.appendChild(content);
      else bubble.textContent = content;
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
      // 정상 답변으로 conversation 이 초기화된 경우 맨 아래 안내 1줄
      if (debug && debug.conv_reset) {
        const info = document.createElement("div");
        info.className = "chat-debug";
        info.textContent = "ℹ 오류없이 답변이 생성되어 프롬프트 초기화됩니다";
        msg.appendChild(info);
      }
      messagesEl.appendChild(msg);
      scrollToBottom();
      return msg;
    }

    // 디버깅 정보 라인 — conversation_id / elapsed / team / SQL수 / multi turn.
    function buildDebug(d) {
      const el = document.createElement("div");
      el.className = "chat-debug";
      const parts = [];
      if (d.conversation_id) parts.push(`conv_id: ${d.conversation_id}`);
      if (d.elapsed_ms != null) parts.push(`elapsed: ${Number(d.elapsed_ms).toLocaleString()} ms`);
      if (d.team) parts.push(`team: ${d.team}`);
      if (d.sql_count != null) parts.push(`SQL: ${d.sql_count}건`);
      parts.push(`multi turn: ${d.multi_turn ? "ON" : "OFF"}`);
      el.textContent = "🛠 " + parts.join("  ·  ");
      return el;
    }

    // 단계별 소요시간 — Agent Team Test 2탭과 동일한 timeline 데이터를 접이식 목록으로.
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

    // results([{title,sql,columns,rows,truncated,exec_ms,error,stage}]) + note → 표 답변 노드.
    // baseName 은 다운로드 파일명의 접두(<설정명>_<순번>.csv).
    function buildResultsNode(results, note, baseName) {
      const wrap = document.createElement("div");
      wrap.className = "stack";
      wrap.style.minWidth = "0";
      results.forEach((r, i) => {
        const sec = document.createElement("div");
        sec.className = "stack-sm";
        // 소제목 — 여러 SQL 이면 번호 붙임
        const head = document.createElement("div");
        head.style.fontWeight = "600";
        head.textContent = (results.length > 1 ? `${i + 1}. ` : "")
          + (r.title || (results.length > 1 ? `조회 ${i + 1}` : "조회 결과"));
        sec.appendChild(head);
        // 생성 SQL (접힌 상태)
        if (r.sql) {
          const det = document.createElement("details");
          const sum = document.createElement("summary");
          sum.textContent = "생성 SQL 보기";
          sum.style.cursor = "pointer";
          sum.style.fontSize = "var(--fs-sm)";
          sum.style.color = "var(--text-muted)";
          const pre = document.createElement("pre");
          pre.style.cssText = "font-family:var(--font-mono); font-size:var(--fs-sm); white-space:pre-wrap; margin:var(--space-2) 0 0; max-height:220px; overflow:auto;";
          pre.textContent = r.sql;
          det.appendChild(sum);
          det.appendChild(pre);
          sec.appendChild(det);
        }
        if (r.error) {
          // 실패 항목 — 에러를 그 자리에 그대로 노출 (다른 항목은 정상 표시)
          const err = document.createElement("div");
          err.style.cssText = "color:var(--danger, #c74634); font-size:var(--fs-sm); white-space:pre-wrap;";
          err.textContent = `실행 실패 (${r.stage || "error"}): ${r.error}`;
          sec.appendChild(err);
        } else {
          const cols = (r.columns || []).map((c, ci) => ({ key: (row) => row[ci], label: c }));
          const tblWrap = document.createElement("div");
          tblWrap.style.overflowX = "auto";
          tblWrap.appendChild(window.SimpleTable.create(cols, r.rows || [], { emptyText: "결과 없음 (0행)" }));
          sec.appendChild(tblWrap);
          // 하단: truncated 안내 · 실행시간 · 전체 다운로드 링크
          const foot = document.createElement("div");
          foot.className = "row";
          foot.style.cssText = "gap:var(--space-3); align-items:center; font-size:var(--fs-sm); flex-wrap:wrap;";
          const info = document.createElement("span");
          info.className = "muted";
          info.textContent = (r.truncated ? `처음 ${(r.rows || []).length}행만 표시` : `${(r.rows || []).length}행`)
            + (r.exec_ms != null ? ` · SQL실행 ${nf(r.exec_ms)} ms` : "");
          foot.appendChild(info);
          if ((r.rows || []).length) {
            const dl = document.createElement("a");
            dl.setAttribute("role", "button");
            dl.tabIndex = 0;
            dl.style.cssText = "color:#0066cc; text-decoration:underline; cursor:pointer;";
            dl.textContent = "전체 결과 다운로드 (CSV)";
            const doDownload = async () => {
              const orig = dl.textContent;
              dl.textContent = "전체 조회 중…";
              dl.style.pointerEvents = "none";
              try {
                const exp = await window.API.post("/api/chat_tl/export", { sql: r.sql });
                if (!exp || !(exp.rows || []).length) {
                  window.Toast.show("다운로드할 데이터가 없습니다", "error");
                  return;
                }
                const suffix = results.length > 1 ? `_${i + 1}` : "";
                downloadCsv(exp.columns, exp.rows, (baseName || "ai_chat_tl") + suffix);
              } catch (err2) {
                window.Toast.show(errMsg(err2, "다운로드 실패"), "error");
              } finally {
                dl.textContent = orig;
                dl.style.pointerEvents = "";
              }
            };
            dl.addEventListener("click", doDownload);
            dl.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); doDownload(); } });
            foot.appendChild(dl);
          }
          sec.appendChild(foot);
        }
        wrap.appendChild(sec);
      });
      // note — 여러 SQL 결과를 종합할 때 참고할 설명 (agent 가 제공했을 때만)
      if (note) {
        const p = document.createElement("div");
        p.style.cssText = "font-size:var(--fs-sm); white-space:pre-wrap; border-top:1px solid var(--border, #e0e0e0); padding-top:var(--space-2);";
        p.textContent = "📝 " + note;
        wrap.appendChild(p);
      }
      return wrap;
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
        const res = await window.API.post("/api/chat_tl/send", {
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
        const debug = {
          conversation_id: res.conversation_id,
          elapsed_ms: res.elapsed_ms,
          team: cfg.team,
          multi_turn: multiTurn,
          timeline: res.timeline || [],
          thinking: res.thinking || { rows: [], error: null },
        };
        const results = res.results || [];
        // 성공 판정(결과 있음 + 추출 실패 없음 + 모든 SQL 실행 무오류) → 자동 새 대화:
        // 대화 누적이 다음 질문의 프롬프트를 오염시키지 않도록 conversation 만 초기화 (화면 메시지 유지).
        // 오류가 있으면 conversation 을 유지해 후속 질문이 문맥을 이어받게 한다.
        const allOk = results.length > 0 && !res.stage && results.every((r) => !r.error);
        if (allOk) {
          convId = "";
          debug.conv_reset = true;
        }
        if (results.length) {
          debug.sql_count = results.length;
          addMessage("bot", buildResultsNode(results, res.note, cfgName), debug);
        } else {
          // stage=extract — SQL 을 못 찾음: answer 원문을 텍스트로 표시 (정보 손실 없음)
          const prefix = res.error ? `⚠ ${res.error}\n\n` : "";
          addMessage("bot", prefix + (res.answer || "(빈 응답)"), debug);
        }
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
    const multiTurnBtn = panel.querySelector("#ctl-multiturn");
    function setMultiTurn(val) {
      multiTurn = !!val;
      multiTurnBtn.setAttribute("aria-checked", multiTurn ? "true" : "false");
      multiTurnBtn.classList.toggle("on", multiTurn);
    }
    multiTurnBtn.addEventListener("click", () => {
      setMultiTurn(!multiTurn);
      convId = "";  // 모드 전환 시 대화 컨텍스트 초기화 (다음 전송부터 새 conversation)
    });
    setMultiTurn(multiTurn);  // 기본 ON — 토글 UI(색상/노브) 초기 상태 동기화

    panel.querySelector("#ctl-new").addEventListener("click", resetChat);

    // --- Chat설정 저장/불러오기 (localStorage, 세션 간 유지) — AI Chat 과 키 분리 ---
    const CONFIG_KEY = "aiChatTl.savedConfigs";
    const configSel = panel.querySelector("#ctl-config");
    const configAddBtn = panel.querySelector("#ctl-config-add");
    const configUpdateBtn = panel.querySelector("#ctl-config-update");

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
              <label>User Prompt <span class="muted" style="font-weight:400;">(agent 가 answers JSON 만 반환하도록 지시)</span></label>
              <textarea id="cfg-prompt" rows="10" style="font-family:var(--font-mono); font-size:var(--fs-sm);"></textarea>
            </div>
            <div class="row" style="justify-content:flex-start;">
              <a id="cfg-script" role="button" tabindex="0" style="color:#0066cc; text-decoration:underline; cursor:pointer; font-size:var(--fs-sm);">실행 스크립트 보기</a>
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
      // 하단 링크 — 현재 입력값(Team/변수/User Prompt) 기준 실행 스크립트를 팝업으로 조회
      const showScript = () => {
        const team = teamSel.value;
        if (!promptEl.value.trim()) { window.Toast.show("User Prompt 를 입력하면 스크립트를 볼 수 있습니다", "warn"); return; }
        openScriptModal("실행 스크립트 — RUN_TEAM", team, buildChatScript(team, varsEl.value, promptEl.value));
      };
      const scriptLink = backdrop.querySelector("#cfg-script");
      scriptLink.addEventListener("click", showScript);
      scriptLink.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); showScript(); } });
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

    // --- 메시지 저장/불러오기 (localStorage, 세션 간 유지) — AI Chat 과 키 분리 ---
    const SAVED_KEY = "aiChatTl.savedMessages";
    const saveTitle = panel.querySelector("#ctl-save-title");
    const saveAddBtn = panel.querySelector("#ctl-save-add");
    const saveUpdateBtn = panel.querySelector("#ctl-save-update");
    const saveDeleteBtn = panel.querySelector("#ctl-save-delete");
    const savedSel = panel.querySelector("#ctl-saved");

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

    // 삭제 — 콤보에서 선택한 저장 메시지를 localStorage 에서 제거
    saveDeleteBtn.addEventListener("click", () => {
      const title = savedSel.value;
      if (!title) { window.Toast.show("삭제할 항목을 콤보에서 선택하세요", "error"); return; }
      if (!window.confirm(`저장된 메시지 '${title}' 을(를) 삭제할까요?`)) return;
      const list = loadSaved();
      const next = list.filter((m) => m.title !== title);
      if (next.length === list.length) { window.Toast.show("저장된 항목을 찾을 수 없습니다", "error"); return; }
      window.Store.set(SAVED_KEY, JSON.stringify(next));
      refreshSaved();
      window.Toast.show(`'${title}' 삭제됨`, "success");
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
  window.Views.aiChatTl = render;
})();
