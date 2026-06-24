/** views/agent_test.js — 메뉴 [3] AI Agent Team Test (2 탭, 상하구조). */
(function () {
  // 노드 상세(detail) 응답 캐시. 같은 노드 재선택 시 재요청 없이 즉시 표시.
  // 키: "<kind>:<name>". DB 전환 시 뷰 전체가 재렌더되므로 render() 진입 때 비운다.
  const detailCache = new Map();

  // profile_name 속성 드롭다운 후보 — 현재 DB 의 AI Profile 목록 (/api/profiles).
  let PROFILE_NAMES = [];

  // 숫자 천단위 콤마 (null/빈값은 그대로).
  const nf = (v) => (v == null || v === "") ? v : Number(v).toLocaleString();

  async function render() {
    const main = document.getElementById("main");
    main.innerHTML = "";
    detailCache.clear();

    // 트리(/tree)와 Profile 목록(/profiles)은 서로 무관하므로 병렬로 요청한다.
    // - /tree : 화면 본문(트리) — 지연의 본체. 먼저 await 해 화면을 막지 않게 한다.
    // - /profiles : 상세 패널의 profile_name 드롭다운용. 실패해도 화면은 계속(자유 입력 폴백).
    //   둘을 직렬로 await 하면 트리가 profiles 왕복까지 기다리므로 동시에 출발시킨다.
    const treeP = window.API.get("/api/agents/tree");
    const profilesP = window.API.get("/api/profiles");

    const title = document.createElement("div");
    title.className = "view-title";
    title.innerHTML = `<h1>AI Agent Team Test</h1>
      <span class="sub">Team / Agent / Task / Tool 조회 + Team 실행 시 단계별 시간 추적.</span>`;
    main.appendChild(title);

    // /tree 한 번으로 트리 데이터 + 팀 목록을 모두 확보 (별도 /teams 왕복 제거).
    let treeData = { teams: [], tools_meta: {} };
    try {
      treeData = await treeP;
    } catch (e) {
      // 트리 실패 시에도 떠 있는 profiles 요청의 unhandled rejection 을 방지
      profilesP.catch(() => {});
      main.appendChild(divFromHTML('<div class="empty-state muted">Team 트리 로드 실패</div>'));
      return;
    }

    try {
      const profiles = await profilesP;
      PROFILE_NAMES = (profiles || []).map((p) => p.profile_name).filter(Boolean);
    } catch (e) {
      PROFILE_NAMES = [];
    }
    const teams = (treeData.teams || []).map((t) => ({ name: t.name, status: t.status }));

    const tabs = window.Tabs.create([
      { id: "tree", label: "1. Team / Agent / Task / Tool",   render: (host) => renderTab1(host, treeData) },
      { id: "run",  label: "2. Team 실행 및 단계별 속도",     render: (host) => renderTab2(host, teams) },
    ]);
    main.appendChild(tabs);
  }

  // --- Tab 1: 상단 트리 + 하단 상세 ---
  // treeData 는 render() 에서 /api/agents/tree 로 미리 받아 전달 (재요청 없음).
  function renderTab1(host, treeData) {
    host.innerHTML = "";
    const wrap = document.createElement("div");
    wrap.className = "split-vert";
    host.appendChild(wrap);

    const topPanel = document.createElement("div");
    topPanel.className = "panel scroll";
    topPanel.innerHTML = `
      <div class="panel-header"><h2>Team 트리</h2></div>
      <div class="panel-body" id="at-tree"></div>
    `;
    wrap.appendChild(topPanel);

    const bottomPanel = document.createElement("div");
    bottomPanel.className = "panel";
    bottomPanel.innerHTML = `
      <div class="panel-header">
        <h2 id="at-detail-title">노드 선택 시 표시</h2>
        <button class="btn btn-primary" id="at-gen-sql" disabled>Select AI Agent 구문 생성</button>
      </div>
      <div class="panel-body" id="at-detail">
        <div class="empty-state muted">상단 트리에서 노드를 선택하세요.</div>
      </div>
    `;
    wrap.appendChild(bottomPanel);

    const toolsMeta = treeData.tools_meta || {};
    const treeNodes = (treeData.teams || []).map((t) => {
      const taskMap = new Map((t.tasks || []).map((tk) => [tk.name, tk]));
      const agentNodes = (t.agents || []).map((a) => {
        const taskNodes = (a.tasks || []).map((taskName) => {
          const tk = taskMap.get(taskName) || { name: taskName, tools: [] };
          return {
            id: `task:${t.name}:${a.name}:${tk.name}`,
            label: tk.name,
            tag: "Task",
            subtitle: summary("task", tk),
            type: "task",
            meta: { kind: "task", name: tk.name },
            children: (tk.tools || []).map((toolName) => ({
              id: `tool:${t.name}:${a.name}:${tk.name}:${toolName}`,
              label: toolName,
              tag: "Tool",
              subtitle: summary("tool", { name: toolName, ...(toolsMeta[toolName] || {}) }),
              type: "tool",
              meta: { kind: "tool", name: toolName },
            })),
          };
        });
        return {
          id: `agent:${t.name}:${a.name}`,
          label: a.name,
          tag: "Agent",
          subtitle: summary("agent", a),
          type: "agent",
          meta: { kind: "agent", name: a.name },
          children: taskNodes,
        };
      });
      return {
        id: `team:${t.name}`,
        label: t.name,
        tag: "Team",
        subtitle: summary("team", t),
        type: "team",
        meta: { kind: "team", name: t.name },
        children: agentNodes,
      };
    });

    document.getElementById("at-tree").innerHTML = "";
    let activeKey = null;  // 가장 최근 선택 — 늦게 온 응답이 현재 선택을 덮어쓰지 않게.
    const tree = window.Tree.create(treeNodes, {
      onSelect: async (node) => {
        if (!node.meta) return;
        const title = document.getElementById("at-detail-title");
        const body = document.getElementById("at-detail");
        title.textContent = `${node.meta.kind.toUpperCase()} — ${node.meta.name}`;

        // Team 노드일 때만 "Select AI Agent 구문 생성" 버튼 활성화
        const genBtn = document.getElementById("at-gen-sql");
        const isTeam = node.meta.kind === "team";
        genBtn.disabled = !isTeam;
        genBtn.dataset.team = isTeam ? node.meta.name : "";

        const cacheKey = `${node.meta.kind}:${node.meta.name}`;
        activeKey = cacheKey;

        // 캐시 적중 시 네트워크 없이 즉시 렌더
        const cached = detailCache.get(cacheKey);
        if (cached) {
          body.innerHTML = "";
          body.appendChild(renderAttributes(cached, node.meta));
          return;
        }

        body.innerHTML = '<div class="empty-state"><span class="spinner"></span> 조회 중...</div>';
        let detail = {};
        try {
          const path = pathFor(node.meta);
          detail = await window.API.get(path);
        } catch (e) {
          if (activeKey === cacheKey) body.innerHTML = '<div class="empty-state muted">조회 실패</div>';
          return;
        }
        detailCache.set(cacheKey, detail);
        if (activeKey !== cacheKey) return;  // 그 사이 다른 노드를 선택했으면 렌더 생략
        body.innerHTML = "";
        body.appendChild(renderAttributes(detail, node.meta));
      },
    });
    document.getElementById("at-tree").appendChild(tree);

    // "Select AI Agent 구문 생성" — 선택된 Team 하위 Agent/Tool/Task + Team 의 CREATE 구문 팝업
    document.getElementById("at-gen-sql").addEventListener("click", async () => {
      const btn = document.getElementById("at-gen-sql");
      const teamName = btn.dataset.team;
      if (!teamName) return;
      btn.disabled = true;
      const prev = btn.innerHTML;
      btn.innerHTML = '<span class="spinner"></span> 생성 중...';
      try {
        const sql = await buildTeamAgentSql(treeData, teamName);
        showSqlModal(`Select AI Agent 구문 — ${teamName}`, sql);
      } catch (e) {
        window.Toast.show(errMsg(e, "구문 생성 실패"), "error");
      } finally {
        btn.disabled = false;
        btn.innerHTML = prev;
      }
    });
  }

  // 트리 노드 subtitle 생성
  //   team  — 표시 안 함
  //   agent — role 전체
  //   task  — instruction 전체
  //   tool  — instruction 전체
  function summary(kind, obj) {
    // 줄바꿈은 유지하고 공백/탭만 정리 (CSS white-space: pre-wrap 로 렌더)
    const clean = (s) =>
      (s ? String(s).replace(/\r\n?/g, "\n").replace(/[ \t]+/g, " ").replace(/\n{3,}/g, "\n\n").trim() : "");
    if (kind === "agent") return clean(obj.role);
    if (kind === "task")  return clean(obj.instruction);
    if (kind === "tool")  return clean(obj.instruction);
    return "";
  }

  function pathFor(meta) {
    if (meta.kind === "team")  return `/api/agents/teams/${encodeURIComponent(meta.name)}`;
    if (meta.kind === "agent") return `/api/agents/${encodeURIComponent(meta.name)}`;
    if (meta.kind === "task")  return `/api/agents/tasks/${encodeURIComponent(meta.name)}`;
    if (meta.kind === "tool")  return `/api/agents/tools/${encodeURIComponent(meta.name)}`;
    return "/api/agents/teams";
  }

  // ====================================================================
  // Select AI Agent 구문 생성 — Team 하위 Agent/Tool/Task + Team CREATE 블록
  // ====================================================================

  // 상세(detail) 응답을 캐시 우선으로 가져온다 (트리 onSelect 와 동일 캐시 공유)
  async function fetchDetailCached(meta) {
    const key = `${meta.kind}:${meta.name}`;
    let d = detailCache.get(key);
    if (!d) { d = await window.API.get(pathFor(meta)); detailCache.set(key, d); }
    return d;
  }

  // attribute_value 를 타입에 맞게 변환 — JSON 배열/객체, 숫자, 그 외 문자열
  function coerceAttrValue(raw) {
    if (raw == null) return "";
    const s = String(raw).trim();
    if (s.startsWith("[") || s.startsWith("{")) {
      try { return JSON.parse(s); } catch (_) { /* fall through */ }
    }
    if (/^-?\d+(\.\d+)?$/.test(s)) return Number(s);
    return String(raw);
  }

  // 속성 행 배열 → attributes JSON 객체
  function attrsToObject(attributes) {
    const obj = {};
    for (const a of attributes || []) {
      if (!a || !a.attribute_name) continue;
      obj[a.attribute_name] = coerceAttrValue(a.attribute_value);
    }
    return obj;
  }

  // object_type → DBMS_CLOUD_AI_AGENT DROP/CREATE 프로시저 + 인자명
  const AGENT_DDL = {
    AGENT: { drop: "DROP_AGENT", create: "CREATE_AGENT", arg: "agent_name" },
    TOOL:  { drop: "DROP_TOOL",  create: "CREATE_TOOL",  arg: "tool_name" },
    TASK:  { drop: "DROP_TASK",  create: "CREATE_TASK",  arg: "task_name" },
    TEAM:  { drop: "DROP_TEAM",  create: "CREATE_TEAM",  arg: "team_name" },
  };

  function genAgentBlock(type, name, attributes) {
    const ddl = AGENT_DDL[type];
    const json = JSON.stringify(attrsToObject(attributes), null, 2)
      .replace(/'/g, "''");  // PL/SQL 문자열 안의 single-quote 이스케이프
    return `BEGIN
    DBMS_CLOUD_AI_AGENT.${ddl.drop}(${ddl.arg} => '${name}', force => true);

    DBMS_CLOUD_AI_AGENT.${ddl.create}(
        ${ddl.arg} => '${name}',
        attributes => '${json}'
    );
END;
/`;
  }

  // treeData + teamName 으로 Agent → Tool → Task → Team 순 CREATE 구문 문자열 생성
  async function buildTeamAgentSql(treeData, teamName) {
    const teamNode = (treeData.teams || []).find((t) => t.name === teamName);
    if (!teamNode) throw new Error("팀 정보를 찾을 수 없습니다");

    const agentNames = (teamNode.agents || []).map((a) => a.name).filter(Boolean);
    const taskNames = (teamNode.tasks || []).map((t) => t.name).filter(Boolean);
    const toolNames = [...new Set((teamNode.tasks || []).flatMap((t) => t.tools || []))].filter(Boolean);

    const [teamD, agentDs, taskDs, toolDs] = await Promise.all([
      fetchDetailCached({ kind: "team", name: teamName }),
      Promise.all(agentNames.map((n) => fetchDetailCached({ kind: "agent", name: n }))),
      Promise.all(taskNames.map((n) => fetchDetailCached({ kind: "task", name: n }))),
      Promise.all(toolNames.map((n) => fetchDetailCached({ kind: "tool", name: n }))),
    ]);

    const parts = [];
    if (agentDs.length) {
      parts.push("-- agent");
      agentDs.forEach((d, i) => parts.push(genAgentBlock("AGENT", agentNames[i], d.attributes)));
    }
    if (toolDs.length) {
      parts.push("-- tool");
      toolDs.forEach((d, i) => parts.push(genAgentBlock("TOOL", toolNames[i], d.attributes)));
    }
    if (taskDs.length) {
      parts.push("-- task");
      taskDs.forEach((d, i) => parts.push(genAgentBlock("TASK", taskNames[i], d.attributes)));
    }
    parts.push("-- Team");
    parts.push(genAgentBlock("TEAM", teamName, teamD.attributes));

    return parts.join("\n\n");
  }

  function showSqlModal(title, sql) {
    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    backdrop.innerHTML = `
      <div class="modal" style="width:820px;">
        <div class="modal-header">
          <h2>${window.escapeHtml(title)}</h2>
          <div class="row">
            <button class="btn btn-ghost" id="at-sql-copy">복사</button>
            <button class="btn btn-ghost" id="at-sql-close">✕</button>
          </div>
        </div>
        <div class="modal-body">
          <pre id="at-sql-pre" style="white-space:pre; margin:0; font-family:var(--font-mono); font-size:var(--fs-sm); background:var(--surface-alt); padding:var(--space-3); border-radius:var(--radius-md); overflow:auto;"></pre>
        </div>
      </div>
    `;
    backdrop.querySelector("#at-sql-pre").textContent = sql;
    const close = () => { backdrop.remove(); document.removeEventListener("keydown", onKey); };
    const onKey = (e) => { if (e.key === "Escape") close(); };
    backdrop.addEventListener("click", (e) => { if (e.target === backdrop) close(); });
    backdrop.querySelector("#at-sql-close").addEventListener("click", close);
    backdrop.querySelector("#at-sql-copy").addEventListener("click", async () => {
      const ok = await copyToClipboard(sql);
      window.Toast.show(ok ? "클립보드에 복사됨" : "복사 실패 — 직접 선택해 복사하세요", ok ? "success" : "error");
    });
    document.addEventListener("keydown", onKey);
    document.body.appendChild(backdrop);
  }

  function renderAttributes(detail, meta) {
    const wrap = document.createElement("div");
    wrap.className = "stack";
    // 헤더 메타 라인
    const head = document.createElement("div");
    head.className = "muted";
    head.style.fontSize = "var(--fs-sm)";
    const keys = Object.keys(detail).filter((k) => k !== "attributes" && typeof detail[k] !== "object");
    head.textContent = keys.map((k) => `${k}: ${detail[k]}`).join("  ·  ") || "(메타 정보 없음)";
    wrap.appendChild(head);

    const attrs = detail.attributes || [];
    if (attrs.length) {
      wrap.appendChild(window.SimpleTable.create(
        [
          { key: "attribute_name", label: "Attribute" },
          {
            key: "attribute_value", label: "Value",
            format: (_v, attr) => buildAttrValueCell(meta, attr),
          },
        ],
        attrs
      ));
    } else {
      const empty = document.createElement("div");
      empty.className = "empty-state muted";
      empty.textContent = "추가 속성이 없습니다";
      wrap.appendChild(empty);
    }
    return wrap;
  }

  // profile_name 속성 전용 입력 — 현재 DB 의 AI Profile 목록을 드롭다운으로.
  // 현재 값이 목록에 없으면 그 값을 옵션으로 추가해 유실 방지.
  function buildProfileSelect(currentValue) {
    const sel = document.createElement("select");
    sel.style.flex = "1";
    sel.style.fontFamily = "var(--font-mono)";
    sel.style.fontSize = "var(--fs-sm)";
    sel.style.minHeight = "32px";
    const cur = currentValue == null ? "" : String(currentValue);
    const options = PROFILE_NAMES.slice();
    if (cur && !options.includes(cur)) options.unshift(cur);
    options.forEach((p) => {
      const o = document.createElement("option");
      o.value = p;
      o.textContent = p;
      sel.appendChild(o);
    });
    sel.value = cur;
    return sel;
  }

  // 속성 Value 셀 — 입력(profile_name=드롭다운, 그 외=textarea) + 저장 버튼.
  // 클릭 시 DBMS_CLOUD_AI_AGENT.SET_ATTRIBUTE 호출.
  function buildAttrValueCell(meta, attr) {
    const wrap = document.createElement("div");
    wrap.className = "row";
    wrap.style.gap = "6px";
    wrap.style.alignItems = "flex-start";

    const isProfile = attr.attribute_name === "profile_name" && PROFILE_NAMES.length > 0;
    const isToolParams = attr.attribute_name === "tool_params" && PROFILE_NAMES.length > 0;
    let input;
    let profileLink = null;
    let belowEl = null;  // 입력 아래 추가 요소 (tool_params 의 profile 드롭다운)
    if (isProfile) {
      input = buildProfileSelect(attr.attribute_value);
      // 드롭다운 옆 상세 링크 — 현재 선택된 Profile 의 속성 팝업 (AI Profile Test 와 동일)
      profileLink = document.createElement("a");
      profileLink.href = "#";
      profileLink.textContent = "상세";
      profileLink.style.flexShrink = "0";
      profileLink.style.alignSelf = "center";
      profileLink.style.whiteSpace = "nowrap";
      profileLink.addEventListener("click", (e) => {
        e.preventDefault();
        const pn = input.value;
        if (!pn) { window.Toast.show("Profile 을 선택하세요", "warn"); return; }
        if (window.ProfileDetail) window.ProfileDetail.open(pn);
      });
    } else {
      input = document.createElement("textarea");
      input.rows = 1;
      input.className = "textarea-auto";
      input.value = attr.attribute_value == null ? "" : String(attr.attribute_value);
      input.style.flex = "1";
      input.style.fontFamily = "var(--font-mono)";
      input.style.fontSize = "var(--fs-sm)";
    }

    if (isToolParams) belowEl = buildToolParamsProfileRow(input);

    const btn = document.createElement("button");
    btn.className = "btn btn-ghost";
    btn.textContent = "저장";
    btn.style.flexShrink = "0";

    btn.addEventListener("click", async () => {
      const newVal = input.value;
      btn.disabled = true;
      const prev = btn.innerHTML;
      btn.innerHTML = '<span class="spinner"></span>';
      try {
        await window.API.put(attrUrlFor(meta, attr.attribute_name), { value: newVal });
        attr.attribute_value = newVal;
        window.Toast.show(`${attr.attribute_name} 저장됨`, "success");
      } catch (err) {
        window.Toast.show(errMsg(err, "저장 실패"), "error");
      } finally {
        btn.disabled = false;
        btn.innerHTML = prev;
      }
    });

    if (belowEl) {
      // 입력(textarea) 아래에 profile 드롭다운을 두기 위해 세로 컬럼으로 묶는다
      const col = document.createElement("div");
      col.className = "stack-sm";
      col.style.flex = "1";
      input.style.width = "100%";
      input.style.flex = "none";
      col.appendChild(input);
      col.appendChild(belowEl);
      wrap.appendChild(col);
    } else {
      wrap.appendChild(input);
      if (profileLink) wrap.appendChild(profileLink);
    }
    wrap.appendChild(btn);
    return wrap;
  }

  // tool_params(JSON) 의 profile_name 을 드롭다운으로 선택 — 변경 시 위 textarea 의 JSON 갱신.
  function buildToolParamsProfileRow(input) {
    const row = document.createElement("div");
    row.className = "row";
    row.style.gap = "6px";
    row.style.alignItems = "center";

    const label = document.createElement("span");
    label.className = "muted";
    label.style.fontSize = "var(--fs-sm)";
    label.style.flexShrink = "0";
    label.textContent = "profile name:";

    const sel = document.createElement("select");
    sel.style.fontFamily = "var(--font-mono)";
    sel.style.fontSize = "var(--fs-sm)";
    sel.style.minHeight = "30px";

    // textarea JSON 에서 현재 profile_name 추출 (파싱 실패/비객체는 빈 값)
    const readProfile = () => {
      try {
        const o = JSON.parse(input.value);
        return (o && typeof o === "object" && !Array.isArray(o)) ? (o.profile_name || "") : "";
      } catch (e) { return ""; }
    };

    const fill = (cur) => {
      sel.innerHTML = "";
      const ph = document.createElement("option");
      ph.value = ""; ph.textContent = "(선택)";
      sel.appendChild(ph);
      const opts = PROFILE_NAMES.slice();
      if (cur && !opts.includes(cur)) opts.unshift(cur);  // 목록에 없는 현재 값도 보존
      opts.forEach((p) => {
        const o = document.createElement("option");
        o.value = p; o.textContent = p;
        sel.appendChild(o);
      });
      sel.value = cur || "";
    };
    fill(readProfile());

    // 드롭다운 변경 → JSON 의 profile_name 갱신 (다른 키는 보존)
    sel.addEventListener("change", () => {
      let obj;
      try { obj = JSON.parse(input.value); } catch (e) { obj = null; }
      if (!obj || typeof obj !== "object" || Array.isArray(obj)) obj = {};
      if (sel.value) obj.profile_name = sel.value;
      else delete obj.profile_name;
      input.value = JSON.stringify(obj);
      input.dispatchEvent(new Event("input"));  // textarea auto-grow 등 반영
    });

    // textarea 를 직접 편집해도 드롭다운을 동기화 (위→아래)
    input.addEventListener("input", () => {
      const cur = readProfile();
      if (cur && !Array.from(sel.options).some((o) => o.value === cur)) {
        const o = document.createElement("option");
        o.value = cur; o.textContent = cur;
        sel.appendChild(o);
      }
      if (sel.value !== cur) sel.value = cur;
    });

    // 드롭다운 옆 상세 링크 — 현재 선택된 Profile 의 속성 팝업 (AI Profile Test 와 동일)
    const detailLink = document.createElement("a");
    detailLink.href = "#";
    detailLink.textContent = "상세";
    detailLink.style.flexShrink = "0";
    detailLink.style.whiteSpace = "nowrap";
    detailLink.addEventListener("click", (e) => {
      e.preventDefault();
      const pn = sel.value;
      if (!pn) { window.Toast.show("Profile 을 선택하세요", "warn"); return; }
      if (window.ProfileDetail) window.ProfileDetail.open(pn);
    });

    row.appendChild(label);
    row.appendChild(sel);
    row.appendChild(detailLink);
    return row;
  }

  function attrUrlFor(meta, attrName) {
    const an = encodeURIComponent(attrName);
    const n = encodeURIComponent(meta.name);
    if (meta.kind === "team")  return `/api/agents/teams/${n}/attributes/${an}`;
    if (meta.kind === "task")  return `/api/agents/tasks/${n}/attributes/${an}`;
    if (meta.kind === "tool")  return `/api/agents/tools/${n}/attributes/${an}`;
    return `/api/agents/${n}/attributes/${an}`;  // agent
  }

  function errMsg(err, fallback) {
    const p = err && err.payload;
    const d = p && (p.detail || p.error);
    if (d) {
      if (typeof d === "string") return d;
      const t = d.error || d.message || JSON.stringify(d);
      return d.database ? `${t} (${d.database})` : t;
    }
    return (err && err.message) || fallback || "요청 실패";
  }

  // --- Tab 2: 실행 + 단계별 Gantt ---
  function renderTab2(host, teams) {
    host.innerHTML = "";
    const wrap = document.createElement("div");
    wrap.className = "split-vert";
    host.appendChild(wrap);

    const topPanel = document.createElement("div");
    topPanel.className = "panel";
    topPanel.innerHTML = `
      <div class="panel-header"><h2>Team 실행</h2></div>
      <div class="panel-body stack">
        <div class="row">
          <label style="width:90px">Team</label>
          <select id="at-team" style="min-width:240px;">
            ${teams.map((t) => `<option value="${t.name}">${t.name}</option>`).join("")}
          </select>
          <span id="at-status" class="status-pill"><span class="dot"></span> 대기</span>
        </div>
        <div class="stack-sm">
          <div class="row" style="justify-content: space-between;">
            <label>User Prompt</label>
            <div class="row" style="gap:6px;">
              <input type="text" id="at-prompt-title" placeholder="저장할 제목" style="width:130px;">
              <button class="btn" id="at-prompt-add">추가</button>
              <button class="btn" id="at-prompt-update">수정</button>
              <select id="at-prompt-saved" style="min-width:150px;"></select>
            </div>
          </div>
          <textarea id="at-prompt" rows="3">배송 주소 관련 컬럼이 있는 테이블을 찾아줘</textarea>
        </div>
        <div class="row end">
          <button class="btn btn-primary" id="at-run">▶ 실행</button>
        </div>
      </div>
    `;
    wrap.appendChild(topPanel);

    // --- User Prompt 저장/불러오기 (localStorage, 세션 간 유지) ---
    const PROMPTS_KEY = "agentTest.savedPrompts";
    const titleInput = document.getElementById("at-prompt-title");
    const addBtn = document.getElementById("at-prompt-add");
    const updateBtn = document.getElementById("at-prompt-update");
    const savedSel = document.getElementById("at-prompt-saved");
    const promptTa = document.getElementById("at-prompt");

    const loadSaved = () => {
      try { return JSON.parse(localStorage.getItem(PROMPTS_KEY)) || []; }
      catch (e) { return []; }
    };
    const refreshCombo = (selectTitle) => {
      const list = loadSaved();
      savedSel.innerHTML = "";
      const ph = document.createElement("option");
      ph.value = "";
      ph.textContent = list.length ? "저장된 프롬프트…" : "(저장된 프롬프트 없음)";
      savedSel.appendChild(ph);
      list.forEach((p) => {
        const o = document.createElement("option");
        o.value = p.title;
        o.textContent = p.title;
        savedSel.appendChild(o);
      });
      if (selectTitle != null) savedSel.value = selectTitle;
    };
    refreshCombo();

    // 추가 — 제목칸의 새 title 로 현재 프롬프트를 신규 저장 (중복 title 은 거부)
    addBtn.addEventListener("click", () => {
      const title = titleInput.value.trim();
      const prompt = promptTa.value;
      if (!title) { window.Toast.show("추가할 제목을 입력하세요", "error"); titleInput.focus(); return; }
      if (!prompt.trim()) { window.Toast.show("User Prompt 가 비어 있습니다", "error"); return; }
      const list = loadSaved();
      if (list.some((p) => p.title === title)) {
        window.Toast.show("이미 있는 제목입니다. [저장]으로 수정하세요", "error");
        return;
      }
      list.push({ title, prompt });
      localStorage.setItem(PROMPTS_KEY, JSON.stringify(list));
      refreshCombo(title);
      titleInput.value = "";
      window.Toast.show(`'${title}' 추가됨`, "success");
    });

    // 저장 — 콤보에서 선택한 기존 title 의 프롬프트를 현재 내용으로 수정
    updateBtn.addEventListener("click", () => {
      const title = savedSel.value;
      if (!title) { window.Toast.show("수정할 항목을 콤보에서 선택하세요", "error"); return; }
      const prompt = promptTa.value;
      if (!prompt.trim()) { window.Toast.show("User Prompt 가 비어 있습니다", "error"); return; }
      const list = loadSaved();
      const idx = list.findIndex((p) => p.title === title);
      if (idx < 0) { window.Toast.show("저장된 항목을 찾을 수 없습니다", "error"); return; }
      list[idx].prompt = prompt;
      localStorage.setItem(PROMPTS_KEY, JSON.stringify(list));
      window.Toast.show(`'${title}' 수정됨`, "success");
    });

    savedSel.addEventListener("change", () => {
      const title = savedSel.value;
      if (!title) return;
      const found = loadSaved().find((p) => p.title === title);
      if (found) promptTa.value = found.prompt;
    });

    const thinkPanel = document.createElement("div");
    thinkPanel.className = "panel";
    thinkPanel.innerHTML = `
      <div class="panel-header">
        <h2>Thinking 과정</h2>
        <div class="row" style="gap:var(--space-3);">
          <span id="at-think-count" class="muted"></span>
          <button class="btn btn-ghost" id="at-think-suggest">AI 추천</button>
          <button class="btn btn-ghost" id="at-think-copy" disabled>복사</button>
        </div>
      </div>
      <div class="panel-body" id="at-thinking">
        <div class="empty-state muted">[실행] 후 표시됩니다.</div>
      </div>
    `;
    wrap.appendChild(thinkPanel);

    document.getElementById("at-think-copy").addEventListener("click", copyThinking);
    document.getElementById("at-think-suggest").addEventListener("click", () => {
      const teamName = document.getElementById("at-team").value;
      const thinkingText = lastThinkingRows.length ? buildThinkingText(lastThinkingRows) : "";
      openAgentSuggestModal(teamName, thinkingText);
    });

    const midPanel = document.createElement("div");
    midPanel.className = "panel";
    midPanel.innerHTML = `
      <div class="panel-header">
        <h2>단계별 타임라인</h2>
        <span id="at-conv-id" class="muted"></span>
      </div>
      <div class="panel-body" id="at-timeline">
        <div class="empty-state muted">[실행] 후 표시됩니다.</div>
      </div>
    `;
    wrap.appendChild(midPanel);

    const botPanel = document.createElement("div");
    botPanel.className = "panel";
    botPanel.innerHTML = `
      <div class="panel-header"><h2>최종 결과 & 로그</h2></div>
      <div class="panel-body stack" id="at-output">
        <div class="empty-state muted">[실행] 후 표시됩니다.</div>
      </div>
    `;
    wrap.appendChild(botPanel);

    document.getElementById("at-run").addEventListener("click", async () => {
      const team_name = document.getElementById("at-team").value;
      const user_prompt = document.getElementById("at-prompt").value;
      const status = document.getElementById("at-status");
      const btn = document.getElementById("at-run");
      btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> 실행 중...';
      setStatus(status, "running", "실행 중");

      try {
        const data = await window.API.post("/api/agents/teams/run", { team_name, user_prompt });
        document.getElementById("at-conv-id").textContent = `conversation_id: ${data.conversation_id}  ·  total ${nf(data.total_elapsed_ms)} ms`;
        renderThinking(data.thinking);
        renderTimeline(data.timeline || [], data.total_elapsed_ms);
        renderOutput(data);
        setStatus(status, "done", "완료");
      } catch (e) {
        setStatus(status, "error", "오류");
        window.Toast.show("실행 실패", "error");
      } finally {
        btn.disabled = false; btn.innerHTML = "▶ 실행";
      }
    });
  }

  function setStatus(el, cls, text) {
    el.className = "status-pill " + cls;
    el.innerHTML = `<span class="dot"></span> ${text}`;
  }

  // Thinking 카드 펼침 caret 아이콘
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

  // Thinking 과정 — 제공된 SQL 실행 결과를 단계별 readonly 카드로 표시.
  // 복사 버튼이 사용할, 현재 화면에 렌더된 thinking 데이터.
  let lastThinkingRows = [];

  function renderThinking(thinking) {
    const host = document.getElementById("at-thinking");
    const count = document.getElementById("at-think-count");
    const copyBtn = document.getElementById("at-think-copy");
    host.innerHTML = "";
    thinking = thinking || {};
    lastThinkingRows = [];
    if (copyBtn) copyBtn.disabled = true;

    // f_agent_step_title 미존재 등 쿼리 실패 → ORA 오류를 그대로 노출
    if (thinking.error) {
      if (count) count.textContent = "";
      const ta = document.createElement("textarea");
      ta.readOnly = true;
      ta.rows = 3;
      ta.style.fontFamily = "var(--font-mono)";
      ta.style.fontSize = "var(--fs-sm)";
      ta.style.color = "var(--danger)";
      ta.value = "Thinking 조회 실패:\n" + thinking.error;
      host.appendChild(ta);
      return;
    }

    const rows = thinking.rows || [];
    if (count) count.textContent = `${rows.length} steps`;
    if (!rows.length) {
      host.innerHTML = '<div class="empty-state muted">표시할 thinking 단계가 없습니다.</div>';
      return;
    }
    lastThinkingRows = rows;
    if (copyBtn) copyBtn.disabled = false;

    const stack = document.createElement("div");
    stack.className = "stack";
    rows.forEach((r) => {
      const card = document.createElement("div");
      card.className = "think-card";

      // ① 제목 박스 (클릭하면 펼침/접힘) — step_no. step_title + 팀/태스크 배지
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

      // ② LLM 원문 (줄바꿈 유지) — 기본 접힘, 헤더 클릭 시 펼침
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

  // 화면에 표시된 thinking 단계들을 LLM 질의용 평문으로 직렬화.
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
      return [`### Step ${no}. ${title}`.trim(), path, "", body].filter((x, idx) => !(idx === 1 && !path)).join("\n");
    }).join("\n\n---\n\n");
  }

  async function copyThinking() {
    if (!lastThinkingRows.length) {
      window.Toast.show("복사할 thinking 단계가 없습니다", "warn");
      return;
    }
    const text = buildThinkingText(lastThinkingRows);
    const ok = await copyToClipboard(text);
    window.Toast.show(
      ok ? `Thinking ${lastThinkingRows.length}단계 복사됨` : "복사 실패 — 직접 선택해 복사하세요",
      ok ? "success" : "error"
    );
  }

  // ====================================================================
  // AI 추천 모달 — 선택 팀의 Agent role / Task·Tool instruction 을 조회해
  //   [추천] 시 개선안을 옆 컬럼에 표시(수정 가능), [적용] 시 SET_ATTRIBUTE 로 반영.
  // ====================================================================
  async function openAgentSuggestModal(teamName, thinkingText) {
    if (!teamName) { window.Toast.show("Team 을 선택하세요", "warn"); return; }

    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    backdrop.innerHTML = `
      <div class="modal" style="width:1100px;">
        <div class="modal-header">
          <h2>AI 추천 — ${window.escapeHtml(teamName)}</h2>
          <button class="btn btn-ghost" id="ags-close">✕</button>
        </div>
        <div class="modal-body">
          <div class="row" style="gap:12px; align-items:center; margin-bottom:var(--space-3);">
            <label style="width:90px;">AI Profile</label>
            <select id="ags-profile" style="min-width:240px;"><option>로딩 중…</option></select>
            <span class="muted" style="font-size:var(--fs-sm);">— SELECT AI(chat) 호출에 사용</span>
          </div>
          <div class="muted" style="font-size:var(--fs-sm); margin-bottom:var(--space-3);">
            저장된 Agent role / Task·Tool instruction 을 조회했습니다. [추천] 으로 개선안을 받아 수정 후 [적용] 하면 반영됩니다.${thinkingText ? "" : " <b>(아직 실행 전이라 Thinking 컨텍스트 없이 추천합니다)</b>"}
          </div>
          <div id="ags-list"><div class="empty-state"><span class="spinner"></span> 조회 중...</div></div>
        </div>
      </div>`;

    const close = () => { backdrop.remove(); document.removeEventListener("keydown", onKey); };
    const onKey = (e) => { if (e.key === "Escape") close(); };
    backdrop.addEventListener("click", (e) => { if (e.target === backdrop) close(); });
    backdrop.querySelector("#ags-close").addEventListener("click", close);
    document.addEventListener("keydown", onKey);
    document.body.appendChild(backdrop);

    const listHost = backdrop.querySelector("#ags-list");
    const profileSel = backdrop.querySelector("#ags-profile");
    let tree, profiles;
    try {
      [tree, profiles] = await Promise.all([
        window.API.get("/api/agents/tree"),
        window.API.get("/api/profiles").catch(() => []),
      ]);
    } catch (e) {
      listHost.innerHTML = `<div class="empty-state muted">${errMsg(e, "트리 조회 실패")}</div>`;
      return;
    }

    // AI Profile 드롭다운 — ENABLED 우선, 없으면 전체. chat 호출에 사용.
    const enabled = (profiles || []).filter((p) => p.status === "ENABLED");
    const pool = enabled.length ? enabled : (profiles || []);
    profileSel.innerHTML = pool.length
      ? pool.map((p) => `<option value="${window.escapeAttr(p.profile_name)}">${window.escapeHtml(p.profile_name)}</option>`).join("")
      : '<option value="">(사용 가능한 Profile 없음)</option>';

    const team = (tree.teams || []).find((t) => t.name === teamName);
    if (!team) { listHost.innerHTML = '<div class="empty-state muted">팀을 찾을 수 없습니다</div>'; return; }

    // 팀의 첫 Agent 가 쓰는 profile 이 목록에 있으면 기본 선택값으로
    const defProfile = (team.agents || []).map((a) => a.profile_name).find(Boolean);
    if (defProfile && pool.some((p) => p.profile_name === defProfile)) profileSel.value = defProfile;

    const getProfile = () => profileSel.value;
    const toolsMeta = tree.tools_meta || {};
    const taskByName = {};
    (team.tasks || []).forEach((t) => { taskByName[t.name] = t; });

    const stack = document.createElement("div");
    stack.className = "stack";
    (team.agents || []).forEach((agent) => {
      stack.appendChild(buildSuggestItem({
        kind: "agent", name: agent.name, current: agent.role || "", getProfile, thinkingText, depth: 0,
      }));
      (agent.tasks || []).forEach((taskName) => {
        const task = taskByName[taskName];
        if (!task) return;
        stack.appendChild(buildSuggestItem({
          kind: "task", name: task.name, current: task.instruction || "", getProfile, thinkingText, depth: 1,
        }));
        (task.tools || []).forEach((toolName) => {
          const tm = toolsMeta[toolName] || {};
          stack.appendChild(buildSuggestItem({
            kind: "tool", name: toolName, current: tm.instruction || "", getProfile, thinkingText, depth: 2,
          }));
        });
      });
    });

    listHost.innerHTML = "";
    if (!stack.children.length) {
      listHost.innerHTML = '<div class="empty-state muted">표시할 Agent/Task/Tool 이 없습니다</div>';
      return;
    }
    listHost.appendChild(stack);
  }

  // 적용(반영) 엔드포인트 — agent.role / task.instruction / tool.instruction
  function suggestApplyUrl(kind, name) {
    const n = encodeURIComponent(name);
    if (kind === "agent") return `/api/agents/${n}/attributes/role`;
    if (kind === "task")  return `/api/agents/tasks/${n}/attributes/instruction`;
    return `/api/agents/tools/${n}/attributes/instruction`;  // tool
  }

  // 추천 모달의 항목 1개(현재값 | 추천(수정가능) + 추천/적용 버튼)
  function buildSuggestItem({ kind, name, current, getProfile, thinkingText, depth }) {
    const attrLabel = kind === "agent" ? "role" : "instruction";
    const item = document.createElement("div");
    item.className = "panel";
    item.style.marginLeft = (depth * 24) + "px";
    item.style.padding = "var(--space-3)";

    const head = document.createElement("div");
    head.className = "row";
    head.style.justifyContent = "space-between";
    head.style.alignItems = "center";
    const left = document.createElement("div");
    left.appendChild(thinkBadge(kind, name));
    const actions = document.createElement("div");
    actions.className = "row";
    actions.style.gap = "6px";
    const recoBtn = document.createElement("button");
    recoBtn.type = "button";
    recoBtn.className = "btn btn-mini";
    recoBtn.textContent = "추천";
    const applyBtn = document.createElement("button");
    applyBtn.type = "button";
    applyBtn.className = "btn btn-primary btn-mini";
    applyBtn.textContent = "적용";
    applyBtn.disabled = true;
    actions.appendChild(recoBtn);
    actions.appendChild(applyBtn);
    head.appendChild(left);
    head.appendChild(actions);

    const cols = document.createElement("div");
    cols.className = "row";
    cols.style.gap = "12px";
    cols.style.alignItems = "stretch";
    cols.style.marginTop = "var(--space-2)";

    const curCol = document.createElement("div");
    curCol.style.flex = "1";
    curCol.innerHTML = `<label class="muted" style="font-size:var(--fs-sm);">현재 ${attrLabel}</label>`;
    const curText = document.createElement("div");
    curText.style.whiteSpace = "pre-wrap";
    curText.style.fontSize = "var(--fs-sm)";
    curText.style.background = "var(--surface-alt)";
    curText.style.padding = "var(--space-2)";
    curText.style.borderRadius = "var(--radius-md)";
    curText.style.maxHeight = "180px";
    curText.style.overflow = "auto";
    curText.textContent = current || "(비어 있음)";
    curCol.appendChild(curText);

    const recoCol = document.createElement("div");
    recoCol.style.flex = "1";
    recoCol.innerHTML = `<label class="muted" style="font-size:var(--fs-sm);">추천 ${attrLabel} (수정 가능)</label>`;
    const recoTa = document.createElement("textarea");
    recoTa.rows = 7;
    recoTa.placeholder = "[추천] 클릭 시 표시됩니다";
    recoTa.style.fontSize = "var(--fs-sm)";
    recoCol.appendChild(recoTa);

    cols.appendChild(curCol);
    cols.appendChild(recoCol);
    item.appendChild(head);
    item.appendChild(cols);

    recoBtn.addEventListener("click", async () => {
      recoBtn.disabled = true;
      const prev = recoBtn.textContent;
      recoBtn.innerHTML = '<span class="spinner"></span>';
      const profile = getProfile();
      if (!profile) { window.Toast.show("AI Profile 을 선택하세요", "warn"); recoBtn.disabled = false; recoBtn.textContent = prev; return; }
      try {
        const res = await window.API.post("/api/agents/suggest-attribute", {
          kind, name, current, thinking: thinkingText, profile_name: profile,
        });
        recoTa.value = res.suggestion || "";
        applyBtn.disabled = !(res.suggestion || "").trim();
      } catch (e) {
        window.Toast.show(errMsg(e, "추천 실패"), "error");
      } finally {
        recoBtn.disabled = false;
        recoBtn.textContent = prev;
      }
    });

    applyBtn.addEventListener("click", async () => {
      const val = recoTa.value.trim();
      if (!val) { window.Toast.show("추천 내용이 비어 있습니다", "warn"); return; }
      applyBtn.disabled = true;
      const prev = applyBtn.textContent;
      applyBtn.innerHTML = '<span class="spinner"></span>';
      try {
        await window.API.put(suggestApplyUrl(kind, name), { value: val });
        curText.textContent = val;   // 반영 결과를 '현재' 칸에도 표시
        current = val;
        window.Toast.show(`${name} ${attrLabel} 적용됨`, "success");
        applyBtn.textContent = "적용됨";
      } catch (e) {
        window.Toast.show(errMsg(e, "적용 실패"), "error");
        applyBtn.disabled = false;
        applyBtn.textContent = prev;
      }
    });

    return item;
  }

  // navigator.clipboard 우선, 비보안 컨텍스트(예: http://<ip>:8000)에서는 textarea 폴백.
  async function copyToClipboard(text) {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
        return true;
      }
    } catch (e) { /* 폴백으로 진행 */ }
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

  function renderTimeline(timeline, total) {
    const host = document.getElementById("at-timeline");
    host.innerHTML = "";
    if (!timeline.length) {
      host.innerHTML = '<div class="empty-state muted">timeline 정보가 없습니다 (DB 시간 컬럼 미존재)</div>';
      return;
    }
    const max = Math.max(total || 0, ...timeline.map((t) => t.end_ms || 0));
    const gantt = document.createElement("div");
    gantt.className = "gantt";
    timeline.forEach((seg) => {
      const level = seg.level || 0;
      const row = document.createElement("div");
      row.className = "gantt-row";
      const label = document.createElement("div");
      label.className = `gantt-label level-${level}`;
      const name = seg.label || seg.step || "";
      // 트리 들여쓰기 + Tab1 트리와 동일한 타입 배지 (Team→Agent→Task→Tool)
      label.style.paddingLeft = `${level * 18}px`;
      if (seg.type) {
        const tag = document.createElement("span");
        tag.className = "tree-tag tag-" + seg.type;
        tag.textContent = seg.type.toUpperCase();
        label.appendChild(tag);
        label.appendChild(document.createTextNode(" "));
      }
      label.appendChild(document.createTextNode(name));
      label.title = name;
      const track = document.createElement("div");
      track.className = "gantt-track";
      const bar = document.createElement("div");
      bar.className = `gantt-bar ${seg.type}`;
      const left = (seg.start_ms / max) * 100;
      const width = ((seg.end_ms - seg.start_ms) / max) * 100;
      bar.style.left = `${left}%`;
      bar.style.width = `${Math.max(width, 0.5)}%`;
      track.appendChild(bar);
      const dur = document.createElement("div");
      dur.className = "gantt-duration";
      dur.textContent = `${nf(seg.end_ms - seg.start_ms)} ms`;
      row.appendChild(label);
      row.appendChild(track);
      row.appendChild(dur);

      // 클릭 → 해당 Team/Agent/Task/Tool 속성 팝업 (Tab1 상세와 동일 데이터 재사용)
      if (seg.type && name) {
        row.classList.add("clickable");
        row.title = `${name} — 클릭하여 속성 보기`;
        row.addEventListener("click", () => showNodeModal({ kind: seg.type, name }));
      }
      gantt.appendChild(row);
    });
    host.appendChild(gantt);
  }

  // 타임라인 노드 클릭 시 속성을 모달로 표시. pathFor/renderAttributes/detailCache 재사용.
  async function showNodeModal(meta) {
    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    backdrop.innerHTML = `
      <div class="modal" style="width:680px;">
        <div class="modal-header">
          <h2>${window.escapeHtml(meta.kind.toUpperCase())} — ${window.escapeHtml(meta.name)}</h2>
          <button class="btn btn-ghost" id="at-node-close">✕</button>
        </div>
        <div class="modal-body" id="at-node-body">
          <div class="empty-state"><span class="spinner"></span> 조회 중...</div>
        </div>
      </div>
    `;
    const close = () => { backdrop.remove(); document.removeEventListener("keydown", onKey); };
    const onKey = (e) => { if (e.key === "Escape") close(); };
    backdrop.addEventListener("click", (e) => { if (e.target === backdrop) close(); });
    backdrop.querySelector("#at-node-close").addEventListener("click", close);
    document.addEventListener("keydown", onKey);
    document.body.appendChild(backdrop);

    const body = backdrop.querySelector("#at-node-body");
    const cacheKey = `${meta.kind}:${meta.name}`;
    try {
      let detail = detailCache.get(cacheKey);
      if (!detail) {
        detail = await window.API.get(pathFor(meta));
        detailCache.set(cacheKey, detail);
      }
      if (!backdrop.isConnected) return;
      body.innerHTML = "";
      body.appendChild(renderAttributes(detail, meta));
    } catch (e) {
      if (backdrop.isConnected) body.innerHTML = '<div class="empty-state muted">속성 조회 실패</div>';
    }
  }

  function renderOutput(data) {
    const host = document.getElementById("at-output");
    host.innerHTML = "";

    const result = document.createElement("div");
    result.className = "stack-sm";
    result.innerHTML = `
      <label>최종 결과 (CLOB)</label>
      <textarea readonly rows="5" style="font-family:var(--font-mono); font-size:var(--fs-sm);">${window.escapeHtml(data.result)}</textarea>
    `;
    host.appendChild(result);

    const logs = data.raw_logs || {};
    const blocks = [
      { title: "Task History", rows: logs.task_history || [],
        columns: [
          { key: "task_order", label: "Order", className: "metric" },
          { key: "task_name",  label: "Task" },
          { key: "status",     label: "Status" },
          { key: "input",      label: "Input" },
          { key: "output",     label: "Output" },
          { key: "elapsed_ms", label: "Elapsed (ms)", className: "metric", format: nf },
        ] },
      { title: "Tool History", rows: logs.tool_history || [],
        columns: [
          { key: "task_order", label: "Order", className: "metric" },
          { key: "tool_name",  label: "Tool" },
          { key: "input",      label: "Input" },
          { key: "output",     label: "Output" },
          { key: "elapsed_ms", label: "Elapsed (ms)", className: "metric", format: nf },
        ] },
    ];
    blocks.forEach((b) => {
      const details = document.createElement("details");
      details.className = "log-block";

      const summary = document.createElement("summary");
      const titleSpan = document.createElement("span");
      titleSpan.textContent = `${b.title} (${b.rows.length})`;
      summary.appendChild(titleSpan);

      const copyBtn = document.createElement("button");
      copyBtn.type = "button";
      copyBtn.className = "btn btn-ghost btn-mini";
      copyBtn.textContent = "복사";
      copyBtn.style.float = "right";
      copyBtn.disabled = !b.rows.length;
      copyBtn.addEventListener("click", async (e) => {
        e.preventDefault();   // summary 클릭 → details 토글 방지
        e.stopPropagation();
        const ok = await copyToClipboard(buildTableText(b.columns, b.rows));
        window.Toast.show(
          ok ? `${b.title} ${b.rows.length}행 복사됨` : "복사 실패 — 직접 선택해 복사하세요",
          ok ? "success" : "error"
        );
      });
      summary.appendChild(copyBtn);

      details.appendChild(summary);
      details.appendChild(window.SimpleTable.create(b.columns, b.rows, { className: "keep-case" }));
      host.appendChild(details);
    });
  }

  // 표 데이터를 LLM 질의용 평문으로 직렬화 — 레코드 단위 "라벨: 값" (여러 줄 값 보존).
  function buildTableText(columns, rows) {
    if (!rows.length) return "";
    return rows.map((r) =>
      columns.map((c) => `${c.label}: ${r[c.key] == null ? "" : String(r[c.key])}`).join("\n")
    ).join("\n\n---\n\n");
  }

  function divFromHTML(html) { const d = document.createElement("div"); d.innerHTML = html; return d; }

  window.Views = window.Views || {};
  window.Views.agentTest = render;
})();
