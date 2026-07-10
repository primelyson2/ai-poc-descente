/** views/vpd_security.js — 메뉴 [Select AI Security - VPD]
 *
 * Oracle VPD(행 수준 보안)를 4단계로 설정·테스트한다. 2개 탭:
 *   · 탭1 [VPD 설정] : 공통 파라미터({NAME}/{SCHEMA}/{TABLE}) 입력 → 1·2·3단계 스크립트 치환
 *                      → [설정 실행](/api/vpd/run-script) + 등록 정책 목록(/api/vpd/policies)
 *   · 탭2 [VPD 테스트]: 프로파일 선택 + 컨텍스트 값 세팅 → select ai showsql 생성·실행(/api/vpd/test)
 *
 * 명명 규칙(vpd.sql 템플릿과 동일):
 *   컨텍스트 OAC_{NAME} · 패키지 PKG_OAC_{NAME}(SET_OBJECT) · 함수 F_VPD_POLICY_{NAME} · 정책 VPD_POLICY_{NAME}
 */
(function () {
  const STATE_KEY = "oai.vpd.state.v3";   // 파라미터 + 편집한 단계 스크립트 + 테스트 입력
  const DEFAULT_PARAMS = { NAME: "DEPT", SCHEMA: "SELECT_AI_USER", TABLE: "EMPLOYEE", STMT: "SELECT" };
  const DEFAULT_TEST = { value: "개발부", question: "직원 목록을 주세요", profile: "" };

  const loadState = () => {
    try { const s = JSON.parse(localStorage.getItem(STATE_KEY) || "{}");
      return { params: { ...DEFAULT_PARAMS, ...(s.params || {}) }, steps: s.steps || {}, test: { ...DEFAULT_TEST, ...(s.test || {}) } };
    } catch (e) { return { params: { ...DEFAULT_PARAMS }, steps: {}, test: { ...DEFAULT_TEST } }; }
  };
  const saveState = (st) => localStorage.setItem(STATE_KEY, JSON.stringify(st));

  function errMsg(err, fallback) {
    const p = err && err.payload; const d = p && (p.detail || p.error);
    if (d) return typeof d === "string" ? d : (d.error || d.message || JSON.stringify(d));
    return (err && err.message) || fallback || "요청 실패";
  }

  // ── 단계별 스크립트 템플릿 ({NAME}/{SCHEMA}/{TABLE} 치환) ──────────────
  function gen1(p) {
    const N = p.NAME;
    return [
      "-- 1. Oracle Application Context (세션별 값 저장 → VPD 기준값)",
      `CREATE CONTEXT OAC_${N} USING PKG_OAC_${N};`,
      "",
      `CREATE OR REPLACE PACKAGE PKG_OAC_${N} AS`,
      "  PROCEDURE SET_OBJECT(P_OBJECT VARCHAR2);",
      "END;",
      "/",
      "",
      `CREATE OR REPLACE PACKAGE BODY PKG_OAC_${N} AS`,
      "  PROCEDURE SET_OBJECT(P_OBJECT VARCHAR2) IS",
      "  BEGIN",
      `    DBMS_SESSION.SET_CONTEXT('OAC_${N}','${N}', P_OBJECT);`,
      "  END;",
      "END;",
      "/",
    ].join("\n");
  }
  function gen2(p) {
    const N = p.NAME;
    return [
      "-- 2. VPD 정책 함수 (WHERE 술어 반환) — 예시 로직은 대상 컬럼에 맞게 수정",
      `CREATE OR REPLACE FUNCTION F_VPD_POLICY_${N}(`,
      "  P_SCHEMA VARCHAR2, P_OBJECT VARCHAR2",
      ") RETURN VARCHAR2 AS",
      `  V_OBJECT VARCHAR2(100) := SYS_CONTEXT('OAC_${N}','${N}');`,
      "BEGIN",
      "  IF V_OBJECT IS NULL THEN",
      "    RETURN '1=0';",
      "  ELSIF V_OBJECT = '인사부' THEN",
      "    RETURN '1=1';",
      "  ELSE",
      "    V_OBJECT := REPLACE(V_OBJECT, '''', '''''');",
      "    RETURN 'DEPT_NAME = ''' || V_OBJECT || '''';",
      "  END IF;",
      "END;",
      "/",
    ].join("\n");
  }
  function gen3(p) {
    return [
      `-- 3. VPD 정책 설정 — ${p.SCHEMA}.${p.TABLE} 에 정책 연결`,
      "BEGIN",
      "  DBMS_RLS.ADD_POLICY(",
      `    object_schema   => '${p.SCHEMA}',`,
      `    object_name     => '${p.TABLE}',`,
      `    policy_name     => 'VPD_POLICY_${p.NAME}',`,
      `    function_schema => '${p.SCHEMA}',`,
      `    policy_function => 'F_VPD_POLICY_${p.NAME}',`,
      `    statement_types => '${p.STMT}'`,
      "  );",
      "END;",
      "/",
    ].join("\n");
  }
  function genTest(p, t) {
    return [
      "-- 4-1. 컨텍스트 값 설정",
      "BEGIN",
      `  ${p.SCHEMA}.PKG_OAC_${p.NAME}.SET_OBJECT('${(t.value || "").replace(/'/g, "''")}');`,
      "END;",
      "/",
      "",
      "-- 4-2. select ai showsql (VPD 가 실행 시 WHERE 를 자동 주입)",
      `select ai showsql ${t.question || ""};`,
    ].join("\n");
  }

  async function render() {
    const main = document.getElementById("main");
    main.innerHTML = "";
    const title = document.createElement("div");
    title.className = "view-title";
    title.innerHTML = `<h1>Select AI Security - VPD</h1>
      <span class="sub">공통 파라미터를 입력해 VPD 스크립트를 만들고 DB 에 적용·테스트합니다.</span>`;
    main.appendChild(title);
    main.appendChild(window.Tabs.create([
      { id: "setup", label: "VPD 설정", render: renderSetupTab },
      { id: "test", label: "VPD 테스트", render: renderTestTab },
    ]));
  }

  // ── 탭1: VPD 설정 ──────────────────────────────────────
  function renderSetupTab(host) {
    const st = loadState();
    const p = st.params;
    host.innerHTML = `
      <div class="panel">
        <div class="panel-header"><h2>공통 파라미터 <span class="muted" style="font-size:var(--fs-sm);">입력하면 아래 스크립트가 치환됩니다</span></h2>
          <button class="btn" id="vp-reset" type="button">기본 스크립트로 초기화</button>
        </div>
        <div class="panel-body">
          <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;">
            ${paramInput("NAME","{NAME} — VPD 제어 기준 이름", p.NAME, "컨텍스트/패키지/함수/정책 이름 접미사 + 컨텍스트 속성 키 (예: DEPT)")}
            ${paramInput("SCHEMA","{SCHEMA} — 대상/함수 스키마", p.SCHEMA, "대상 객체가 있는 DB 스키마")}
            ${paramInput("TABLE","{TABLE} — 대상 객체(테이블/뷰)", p.TABLE, "VPD 를 적용할 객체")}
          </div>
        </div>
      </div>
      ${stepPanel(1,"Oracle Application Context","vp-s1",15)}
      ${stepPanel(2,"VPD 정책 함수 생성","vp-s2",16)}
      ${stepPanel(3,"VPD 정책 설정 (ADD_POLICY)","vp-s3",12)}
      <div class="panel"><div class="panel-body row" style="gap:8px; justify-content:flex-end;">
        <button class="btn" id="vp-all" type="button">전체 설정 스크립트</button>
        <button class="btn btn-primary" id="vp-run" type="button">설정 실행 (DB 적용)</button>
      </div></div>
      <div class="panel">
        <div class="panel-header"><h2>등록된 VPD 정책 <span class="muted" style="font-size:var(--fs-sm);">ALL_POLICIES</span></h2>
          <button class="btn btn-ghost" id="vp-listreload" type="button">↻ 새로고침</button>
        </div>
        <div class="panel-body" id="vp-list"></div>
      </div>`;

    const $ = (s) => host.querySelector(s);
    const s1 = $("#vp-s1"), s2 = $("#vp-s2"), s3 = $("#vp-s3");
    const regen = () => {
      const cur = collectParams(host);
      s1.value = gen1(cur); s2.value = gen2(cur); s3.value = gen3(cur);
      const x = loadState(); x.params = cur; x.steps = { s1: s1.value, s2: s2.value, s3: s3.value }; saveState(x);
    };
    s1.value = st.steps.s1 != null ? st.steps.s1 : gen1(p);
    s2.value = st.steps.s2 != null ? st.steps.s2 : gen2(p);
    s3.value = st.steps.s3 != null ? st.steps.s3 : gen3(p);

    host.querySelectorAll("input[data-param]").forEach((el) => el.addEventListener("input", regen));
    [["s1", s1], ["s2", s2], ["s3", s3]].forEach(([k, el]) =>
      el.addEventListener("input", () => { const x = loadState(); x.steps[k] = el.value; saveState(x); }));

    $("#vp-reset").addEventListener("click", () => { regen(); window.Toast.show("파라미터 기준으로 스크립트를 다시 채웠습니다", "success"); });
    host.querySelectorAll("[data-step]").forEach((btn) =>
      btn.addEventListener("click", () => showScriptModal(btn.dataset.title, { 1: s1, 2: s2, 3: s3 }[btn.dataset.step].value)));
    $("#vp-all").addEventListener("click", () => showScriptModal("전체 설정 스크립트 (1 → 2 → 3)", [s1.value, s2.value, s3.value].join("\n\n")));

    // 설정 실행 — 스크립트 확인 → [실행] → /api/vpd/run-script
    $("#vp-run").addEventListener("click", () => {
      const full = [s1.value, s2.value, s3.value].join("\n\n");
      showScriptModal("설정 실행 — DB 에 반영", full, async () => {
        try {
          const res = await window.API.post("/api/vpd/run-script", { script: full });
          const fails = (res.results || []).filter((r) => !r.ok);
          if (fails.length) {
            window.Toast.show(`${res.ok_count}/${res.total} 성공, ${res.fail_count} 실패`, "error");
            fails.forEach((f) => window.Toast.show(`실패#${f.i}: ${f.error}`, "error"));
          } else {
            window.Toast.show(`설정 실행 완료 (${res.ok_count}/${res.total} 문장)`, "success");
          }
          loadList(host);
        } catch (e) { window.Toast.show(errMsg(e, "설정 실행 실패"), "error"); }
      }, "실행 (DB 적용)");
    });
    $("#vp-listreload").addEventListener("click", () => loadList(host));
    loadList(host);
  }

  const paramInput = (key, label, val, hint) => `
    <div class="stack-sm">
      <label style="font-size:var(--fs-sm);">${label}</label>
      <input type="text" data-param="${key}" value="${window.escapeAttr(val || "")}" style="font-family:var(--font-mono); font-size:var(--fs-sm);">
      ${hint ? `<span class="muted" style="font-size:11.5px;">${hint}</span>` : ""}
    </div>`;
  const stepPanel = (n, title, id, rows) => `
    <div class="panel">
      <div class="panel-header"><h2>${title}</h2>
        <button class="btn btn-ghost" data-step="${n}" data-title="${title} 스크립트" type="button">스크립트 보기</button>
      </div>
      <div class="panel-body">
        <textarea id="${id}" rows="${rows}" style="width:100%; font-family:var(--font-mono); font-size:var(--fs-sm);"></textarea>
      </div>
    </div>`;
  function collectParams(host) {
    const o = {}; host.querySelectorAll("input[data-param]").forEach((el) => o[el.dataset.param] = el.value.trim());
    return { ...DEFAULT_PARAMS, ...o };
  }

  // ── 등록 정책 목록 (ALL_POLICIES) ──────────────────────
  const stmtTypes = (r) => ["sel", "ins", "upd", "del", "idx"]
    .filter((k) => String(r[k]).toUpperCase() === "YES")
    .map((k) => ({ sel: "SELECT", ins: "INSERT", upd: "UPDATE", del: "DELETE", idx: "INDEX" }[k])).join(",");
  const fnName = (r) => r.package ? `${r.pf_owner}.${r.package}.${r.function}` : `${r.pf_owner}.${r.function}`;

  async function loadList(host) {
    const listHost = host.querySelector("#vp-list");
    if (!listHost) return;
    listHost.innerHTML = '<div class="empty-state"><span class="spinner"></span> 조회 중...</div>';
    let rows;
    try { rows = await window.API.get("/api/vpd/policies"); }
    catch (e) { listHost.innerHTML = `<div class="empty-state muted">${window.escapeHtml(errMsg(e, "정책 조회 실패"))}</div>`; return; }
    listHost.innerHTML = "";
    listHost.appendChild(window.SimpleTable.create(
      [
        { key: "object_owner", label: "스키마" },
        { key: "object_name", label: "객체" },
        { key: "policy_name", label: "정책명" },
        { key: (r) => fnName(r), label: "정책 함수" },
        { key: (r) => stmtTypes(r), label: "적용문", headerAlign: "center", align: "center" },
        { key: "enable", label: "사용", headerAlign: "center", align: "center", format: enableBadge },
        { key: "_act", label: "", headerAlign: "center", align: "center", format: (_v, row) => buildActions(row, host) },
      ],
      rows || [],
      { className: "keep-case", emptyText: "등록된 VPD 정책이 없습니다. 위에서 [설정 실행]으로 정책을 만드세요.",
        onRowClick: (row) => showDetailModal(row) }
    ));
  }
  function enableBadge(v) {
    const on = String(v).toUpperCase() === "YES";
    const s = document.createElement("span"); s.textContent = on ? "YES" : "NO";
    s.style.cssText = `font-size:11.5px;font-weight:700;padding:2px 8px;border-radius:999px;color:#fff;background:${on ? "#1a7f5a" : "#8a8f98"}`;
    return s;
  }
  function buildActions(row, host) {
    const box = document.createElement("div");
    box.className = "row"; box.style.gap = "6px"; box.style.justifyContent = "center";
    box.addEventListener("click", (e) => e.stopPropagation());
    const on = String(row.enable).toUpperCase() === "YES";
    const key = { object_schema: row.object_owner, object_name: row.object_name, policy_name: row.policy_name };
    const toggle = document.createElement("button");
    toggle.className = "btn btn-ghost"; toggle.textContent = on ? "사용중지" : "재개";
    toggle.addEventListener("click", async () => {
      try {
        await window.API.post("/api/vpd/policy/enable", { ...key, enable: !on });
        window.Toast.show(`정책 '${row.policy_name}' ${on ? "사용중지" : "재개"}`, "success");
        loadList(host);
      } catch (e) { window.Toast.show(errMsg(e, "변경 실패"), "error"); }
    });
    box.appendChild(toggle);
    const del = document.createElement("button");
    del.className = "btn btn-primary"; del.textContent = "삭제";
    del.addEventListener("click", () => {
      const sql = `BEGIN\n  DBMS_RLS.DROP_POLICY(object_schema => '${row.object_owner}', object_name => '${row.object_name}', policy_name => '${row.policy_name}');\nEND;\n/`;
      showScriptModal(`정책 삭제 — ${row.policy_name}`, sql, async () => {
        try { await window.API.post("/api/vpd/policy/drop", key); window.Toast.show(`정책 '${row.policy_name}' 삭제됨`, "success"); loadList(host); }
        catch (e) { window.Toast.show(errMsg(e, "삭제 실패"), "error"); }
      }, "삭제 실행");
    });
    box.appendChild(del);
    return box;
  }
  function showDetailModal(row) {
    const ro = (label, value) => `
      <div class="stack-sm">
        <label style="font-size:var(--fs-sm); color:var(--text-muted);">${label}</label>
        <pre style="white-space:pre-wrap; word-break:break-word; margin:0; font-family:var(--font-mono); font-size:var(--fs-sm); background:var(--surface-alt); padding:var(--space-2) var(--space-3); border-radius:var(--radius-md); max-height:200px; overflow:auto;">${window.escapeHtml(value != null && String(value).trim() !== "" ? String(value) : "—")}</pre>
      </div>`;
    const bd = modal(`
      <div class="modal" style="width:760px; max-width:95vw;">
        <div class="modal-header"><h2>VPD 정책 상세 <span class="muted" style="font-size:var(--fs-sm);">(ALL_POLICIES)</span></h2>
          <button class="btn btn-ghost" id="m-close">✕</button></div>
        <div class="modal-body stack">
          <div class="row" style="gap:12px;">
            <div style="flex:1;min-width:0;">${ro("스키마", row.object_owner)}</div>
            <div style="flex:1;min-width:0;">${ro("객체", row.object_name)}</div>
            <div style="flex:1;min-width:0;">${ro("사용", row.enable)}</div>
          </div>
          ${ro("정책명", row.policy_name)}
          ${ro("정책 함수", fnName(row))}
          ${ro("적용문", stmtTypes(row))}
          <div class="row end"><button class="btn btn-ghost" id="m-close2">닫기</button></div>
        </div>
      </div>`);
    bd.querySelector("#m-close").addEventListener("click", () => bd.remove());
    bd.querySelector("#m-close2").addEventListener("click", () => bd.remove());
  }

  // ── 탭2: VPD 테스트 ────────────────────────────────────
  async function renderTestTab(host) {
    const st = loadState();
    host.innerHTML = `
      <div class="panel">
        <div class="panel-header"><h2>VPD 테스트</h2></div>
        <div class="panel-body stack">
          <div class="muted" style="font-size:var(--fs-sm);">프로파일과 컨텍스트 값을 정하고 실행하면, 같은 세션에서 컨텍스트를 세팅한 뒤 <code>select ai showsql</code> 로 SQL 을 만들고 그 SQL 을 실행합니다. VPD 가 실행 시 WHERE 를 자동 주입하므로 값에 따라 결과가 달라집니다. (설정 탭의 {NAME}=<b>${window.escapeHtml(st.params.NAME)}</b> / {SCHEMA}=<b>${window.escapeHtml(st.params.SCHEMA)}</b> 사용)</div>
          <div class="row" style="gap:12px; align-items:flex-end; flex-wrap:wrap;">
            <div class="stack-sm" style="flex:0 0 240px;">
              <label>AI Profile</label>
              <select id="vt-profile"><option value="">불러오는 중…</option></select>
            </div>
            <div class="stack-sm" style="flex:0 0 200px;">
              <label>컨텍스트 값 ({NAME})</label>
              <input type="text" id="vt-val" list="vt-val-list" value="${window.escapeAttr(st.test.value)}" style="font-family:var(--font-mono);">
              <datalist id="vt-val-list"><option value="개발부"><option value="인사부"><option value="영업부"></datalist>
            </div>
            <div class="stack-sm" style="flex:1; min-width:220px;">
              <label>질문</label>
              <input type="text" id="vt-q" value="${window.escapeAttr(st.test.question)}" style="width:100%;">
            </div>
            <div><button class="btn btn-primary" id="vt-run" type="button">테스트 실행</button></div>
          </div>
          <div id="vt-out"></div>
        </div>
      </div>`;
    const profileSel = host.querySelector("#vt-profile");
    const valEl = host.querySelector("#vt-val"), qEl = host.querySelector("#vt-q"), out = host.querySelector("#vt-out");
    // 프로파일 로드
    try {
      const profiles = await window.API.get("/api/profiles");
      const enabled = (profiles || []).filter((p) => p.status === "ENABLED");
      const names = enabled.map((p) => p.profile_name);
      profileSel.innerHTML = names.length ? names.map((n) => `<option value="${window.escapeAttr(n)}">${window.escapeHtml(n)}</option>`).join("")
        : `<option value="">사용 가능한 Profile 없음</option>`;
      if (st.test.profile && names.includes(st.test.profile)) profileSel.value = st.test.profile;
    } catch (e) { profileSel.innerHTML = `<option value="">Profile 로드 실패</option>`; }

    const persist = () => { const x = loadState(); x.test = { value: valEl.value, question: qEl.value, profile: profileSel.value }; saveState(x); };
    [valEl, qEl, profileSel].forEach((el) => el.addEventListener("change", persist));

    host.querySelector("#vt-run").addEventListener("click", async () => {
      const cur = loadState().params;
      const profile = profileSel.value;
      if (!profile) { window.Toast.show("AI Profile 을 선택하세요", "warn"); return; }
      if (!qEl.value.trim()) { window.Toast.show("질문을 입력하세요", "warn"); return; }
      persist();
      out.innerHTML = '<div class="empty-state"><span class="spinner"></span> 실행 중...</div>';
      let res;
      try {
        res = await window.API.post("/api/vpd/test", {
          schema: cur.SCHEMA, name: cur.NAME, value: valEl.value, question: qEl.value, profile,
        });
      } catch (e) { out.innerHTML = `<div class="empty-state muted">${window.escapeHtml(errMsg(e, "테스트 실패"))}</div>`; return; }
      out.innerHTML = "";
      if (res.sql) {
        const lbl = document.createElement("label"); lbl_style(lbl); lbl.textContent = "생성된 SQL (select ai showsql)"; out.appendChild(lbl);
        const pre = document.createElement("pre");
        pre.style.cssText = "white-space:pre; margin:0 0 12px; font-family:var(--font-mono); font-size:var(--fs-sm); background:var(--surface-alt); padding:var(--space-3); border-radius:var(--radius-md); overflow:auto; max-height:200px;";
        pre.textContent = res.sql; out.appendChild(pre);
      }
      if (res.error) {
        out.appendChild(divFromHtml(`<div class="empty-state muted">${window.escapeHtml(res.error)}${res.stage ? " (" + res.stage + ")" : ""}</div>`));
        return;
      }
      const rl = document.createElement("label"); lbl_style(rl); rl.textContent = `실행 결과 (VPD 적용, 최대 ${(res.rows || []).length}행)`; out.appendChild(rl);
      const cols = (res.columns || []).map((c) => ({ key: c, label: c }));
      out.appendChild(window.SimpleTable.create(cols, (res.rows || []).map((r) => rowObj(res.columns, r)),
        { className: "keep-case", emptyText: "조회된 행이 없습니다 (컨텍스트 값에 해당하는 데이터 없음/VPD 차단)." }));
    });
  }
  const lbl_style = (el) => { el.style.cssText = "display:block; font-weight:600; margin:6px 0 6px;"; };
  const rowObj = (cols, arr) => { const o = {}; (cols || []).forEach((c, i) => o[c] = arr[i]); return o; };
  function divFromHtml(html) { const d = document.createElement("div"); d.innerHTML = html; return d.firstElementChild || d; }

  // ── 공용 모달/스크립트 팝업 ────────────────────────────
  function modal(html) {
    const bd = document.createElement("div"); bd.className = "modal-backdrop"; bd.innerHTML = html;
    const onKey = (ev) => { if (ev.key === "Escape") { bd.remove(); document.removeEventListener("keydown", onKey); } };
    document.addEventListener("keydown", onKey); document.body.appendChild(bd); return bd;
  }
  function showScriptModal(title, sql, onApply, applyLabel) {
    const bd = modal(`
      <div class="modal" style="width:840px; max-width:95vw;">
        <div class="modal-header"><h2>${window.escapeHtml(title)}</h2>
          <div class="row" style="gap:8px;">
            <button class="btn btn-ghost" id="s-copy">복사</button>
            <button class="btn btn-ghost" id="s-close">✕</button>
          </div></div>
        <div class="modal-body">
          <pre id="s-pre" style="white-space:pre; margin:0; font-family:var(--font-mono); font-size:var(--fs-sm); background:var(--surface-alt); padding:var(--space-3); border-radius:var(--radius-md); overflow:auto; max-height:62vh;"></pre>
        </div>
        ${onApply ? `<div class="modal-footer row end" style="gap:8px;">
          <button class="btn btn-ghost" id="s-cancel">닫기</button>
          <button class="btn btn-primary" id="s-apply">${window.escapeHtml(applyLabel || "실행")}</button></div>` : ""}
      </div>`);
    bd.querySelector("#s-pre").textContent = sql;
    bd.querySelector("#s-close").addEventListener("click", () => bd.remove());
    if (bd.querySelector("#s-cancel")) bd.querySelector("#s-cancel").addEventListener("click", () => bd.remove());
    bd.querySelector("#s-copy").addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(sql); window.Toast.show("클립보드에 복사됨", "success"); }
      catch (_) { window.Toast.show("복사 실패", "error"); }
    });
    if (onApply) bd.querySelector("#s-apply").addEventListener("click", async () => {
      const btn = bd.querySelector("#s-apply"); btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> 실행 중...';
      try { await onApply(); } finally { bd.remove(); }
    });
  }

  window.Views = window.Views || {};
  window.Views.vpdSecurity = render;
})();
