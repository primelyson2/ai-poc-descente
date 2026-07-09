/** views/vpd_security.js — 메뉴 [Select AI Security - VPD]
 *
 * Oracle VPD(행 수준 보안) 설정을 문서화된 4단계 절차로 안내한다. 2개 탭:
 *   · 탭1 [VPD 설정] : 공통 파라미터({NAME}/{SCHEMA}/{TABLE})를 입력하면 1·2·3단계 스크립트가 치환됨
 *                      + 등록(저장)된 정책 목록
 *   · 탭2 [VPD 테스트]: 4) 컨텍스트 값 세팅 + `select ai showsql` 검증
 *
 * ※ 서버 로직 없는 프런트 전용(mock) — DBMS_RLS 를 실제 실행하지 않는다.
 *   각 단계는 실행될 스크립트를 [스크립트 보기]로 확인/복사한다(추후 /api/vpd 연동 시 실행으로 교체).
 *
 * 명명 규칙(vpd.sql 템플릿과 동일):
 *   컨텍스트 OAC_{NAME} · 패키지 PKG_OAC_{NAME}(SET_OBJECT) · 함수 F_VPD_POLICY_{NAME} · 정책 VPD_POLICY_{NAME}
 */
(function () {
  const STATE_KEY = "oai.vpd.state.v2";   // 파라미터 + 편집한 단계 스크립트 + 테스트 입력 (v2: {NAME}/{SCHEMA}/{TABLE} 모델)
  const MOCK_KEY = "oai.vpd.mock.v2";     // 등록(저장)된 정책 목록(mock)

  // 공통 파라미터(치환 플레이스홀더)
  const DEFAULT_PARAMS = { NAME: "DEPT", SCHEMA: "SELECT_AI_USER", TABLE: "EMPLOYEE", STMT: "SELECT" };
  const DEFAULT_TEST = { value: "개발부", question: "직원 목록을 주세요" };

  const loadState = () => {
    try { const s = JSON.parse(localStorage.getItem(STATE_KEY) || "{}");
      return { params: { ...DEFAULT_PARAMS, ...(s.params || {}) },
               steps: s.steps || {}, test: { ...DEFAULT_TEST, ...(s.test || {}) } };
    } catch (e) { return { params: { ...DEFAULT_PARAMS }, steps: {}, test: { ...DEFAULT_TEST } }; }
  };
  const saveState = (st) => localStorage.setItem(STATE_KEY, JSON.stringify(st));
  const loadMock = () => { try { const a = JSON.parse(localStorage.getItem(MOCK_KEY) || "[]"); return Array.isArray(a) ? a : []; } catch (e) { return []; } };
  const saveMock = (l) => localStorage.setItem(MOCK_KEY, JSON.stringify(l));
  const nextId = (l) => l.reduce((m, r) => Math.max(m, r.id || 0), 0) + 1;

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
      "    -- 컨텍스트명은 CREATE CONTEXT 와 반드시 동일해야 한다.",
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
      "    RETURN '1=0';                 -- 값 미설정: 아무 것도 안 보임",
      "  ELSIF V_OBJECT = '인사부' THEN",
      "    RETURN '1=1';                 -- 특정 값(예: 인사부): 전체 조회",
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
      "-- 4-2. select ai showsql 로 생성된 SQL 확인(VPD 가 WHERE 절을 자동 주입)",
      `select ai showsql ${t.question || ""};`,
    ].join("\n");
  }

  // ── 진입점 ─────────────────────────────────────────────
  async function render() {
    const main = document.getElementById("main");
    main.innerHTML = "";
    const title = document.createElement("div");
    title.className = "view-title";
    title.innerHTML = `<h1>Select AI Security - VPD</h1>
      <span class="sub">공통 파라미터를 입력하면 VPD 4단계 스크립트가 치환됩니다. <b style="color:#c74634">(프런트 전용 mock — DBMS_RLS 미실행)</b></span>`;
    main.appendChild(title);
    main.appendChild(window.Tabs.create([
      { id: "setup", label: "VPD 설정 (1·2·3단계)", render: renderSetupTab },
      { id: "test", label: "VPD 테스트 (4단계)", render: renderTestTab },
    ]));
  }

  // ── 탭1: VPD 설정 ──────────────────────────────────────
  function renderSetupTab(host) {
    const st = loadState();
    const p = st.params;
    host.innerHTML = `
      <div class="panel">
        <div class="panel-header"><h2>공통 파라미터 <span class="muted" style="font-size:var(--fs-sm);">입력하면 아래 1·2·3단계 스크립트가 치환됩니다</span></h2>
          <button class="btn" id="vp-reset" type="button">기본 스크립트로 초기화</button>
        </div>
        <div class="panel-body">
          <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:12px;">
            ${paramInput("NAME","{NAME} — VPD 제어 기준 이름", p.NAME, "컨텍스트/패키지/함수/정책 이름 접미사 + 컨텍스트 속성 키 (예: DEPT)")}
            ${paramInput("SCHEMA","{SCHEMA} — 대상/함수 스키마", p.SCHEMA, "대상 객체가 있는 DB 스키마")}
            ${paramInput("TABLE","{TABLE} — 대상 객체(테이블/뷰)", p.TABLE, "VPD 를 적용할 객체")}
          </div>
        </div>
      </div>
      ${stepPanel(1,"① Oracle Application Context","vp-s1",15)}
      ${stepPanel(2,"② VPD 정책 함수 생성","vp-s2",16)}
      ${stepPanel(3,"③ VPD 정책 설정 (ADD_POLICY)","vp-s3",12)}
      <div class="panel"><div class="panel-body row" style="gap:8px; justify-content:flex-end;">
        <button class="btn" id="vp-all" type="button">전체 설정 스크립트</button>
        <button class="btn btn-primary" id="vp-save" type="button">설정 저장(mock)</button>
      </div></div>
      <div class="panel">
        <div class="panel-header"><h2>등록된 VPD 정책 <span class="muted" style="font-size:var(--fs-sm);">ALL_POLICIES (mock)</span></h2>
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
    // 최초: 편집본 있으면 유지, 없으면 파라미터로 생성
    s1.value = st.steps.s1 != null ? st.steps.s1 : gen1(p);
    s2.value = st.steps.s2 != null ? st.steps.s2 : gen2(p);
    s3.value = st.steps.s3 != null ? st.steps.s3 : gen3(p);

    // 파라미터 입력 → 즉시 치환(라이브)
    host.querySelectorAll("input[data-param]").forEach((el) => el.addEventListener("input", regen));
    // 단계 스크립트 직접 편집도 저장
    [["s1", s1], ["s2", s2], ["s3", s3]].forEach(([k, el]) =>
      el.addEventListener("input", () => { const x = loadState(); x.steps[k] = el.value; saveState(x); }));

    $("#vp-reset").addEventListener("click", () => { regen(); window.Toast.show("파라미터 기준으로 1·2·3단계를 다시 채웠습니다", "success"); });
    host.querySelectorAll("[data-step]").forEach((btn) =>
      btn.addEventListener("click", () => showScriptModal(btn.dataset.title, { 1: s1, 2: s2, 3: s3 }[btn.dataset.step].value)));
    $("#vp-all").addEventListener("click", () =>
      showScriptModal("전체 설정 스크립트 (1 → 2 → 3)", [s1.value, s2.value, s3.value].join("\n\n")));
    $("#vp-save").addEventListener("click", () => {
      const cur = collectParams(host);
      if (!cur.NAME || !cur.SCHEMA || !cur.TABLE) { window.Toast.show("{NAME}·{SCHEMA}·{TABLE} 를 입력하세요", "warn"); return; }
      showScriptModal(`설정 저장 — VPD_POLICY_${cur.NAME}`, [s1.value, s2.value, s3.value].join("\n\n"), () => {
        const list = loadMock();
        const rec = {
          id: nextId(list),
          object_owner: cur.SCHEMA.toUpperCase(), object_name: cur.TABLE.toUpperCase(),
          policy_name: `VPD_POLICY_${cur.NAME}`.toUpperCase(),
          function_schema: cur.SCHEMA.toUpperCase(), policy_function: `F_VPD_POLICY_${cur.NAME}`.toUpperCase(),
          statement_types: cur.STMT.toUpperCase(), enable: "YES", function_sql: s2.value,
        };
        const idx = list.findIndex((r) => r.object_owner === rec.object_owner && r.object_name === rec.object_name && r.policy_name === rec.policy_name);
        if (idx >= 0) { rec.id = list[idx].id; list[idx] = rec; } else list.push(rec);
        saveMock(list); loadList(host);
        window.Toast.show(`정책 '${rec.policy_name}' 저장됨(mock)`, "success");
      }, "저장(mock)");
    });
    $("#vp-listreload").addEventListener("click", () => { loadList(host); window.Toast.show("새로고침", "info"); });

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

  // ── 등록 정책 목록 ─────────────────────────────────────
  function loadList(host) {
    const listHost = host.querySelector("#vp-list");
    if (!listHost) return;
    listHost.innerHTML = "";
    listHost.appendChild(window.SimpleTable.create(
      [
        { key: "object_owner", label: "스키마" },
        { key: "object_name", label: "객체" },
        { key: "policy_name", label: "정책명" },
        { key: (r) => `${r.function_schema}.${r.policy_function}`, label: "정책 함수" },
        { key: "statement_types", label: "적용문", headerAlign: "center", align: "center" },
        { key: "enable", label: "사용", headerAlign: "center", align: "center", format: enableBadge },
        { key: "_act", label: "", headerAlign: "center", align: "center", format: (_v, row) => buildActions(row, host) },
      ],
      loadMock(),
      { className: "keep-case", emptyText: "저장된 VPD 정책이 없습니다. 위 파라미터 입력 후 [설정 저장]을 누르세요.",
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
    const toggle = document.createElement("button");
    toggle.className = "btn btn-ghost"; toggle.textContent = on ? "사용중지" : "재개";
    toggle.addEventListener("click", () => {
      const list = loadMock(); const t = list.find((r) => r.id === row.id); if (!t) return;
      t.enable = on ? "NO" : "YES"; saveMock(list); loadList(host);
      window.Toast.show(`정책 '${row.policy_name}' ${on ? "사용중지" : "재개"}`, "success");
    });
    box.appendChild(toggle);
    const del = document.createElement("button");
    del.className = "btn btn-primary"; del.textContent = "삭제";
    del.addEventListener("click", () => {
      const sql = ["-- VPD 정책 삭제", "BEGIN",
        `  DBMS_RLS.DROP_POLICY(object_schema => '${row.object_owner}', object_name => '${row.object_name}', policy_name => '${row.policy_name}');`,
        "END;", "/"].join("\n");
      showScriptModal(`정책 삭제 — ${row.policy_name}`, sql, () => {
        saveMock(loadMock().filter((r) => r.id !== row.id)); loadList(host);
        window.Toast.show(`정책 '${row.policy_name}' 삭제됨`, "success");
      }, "삭제(mock)");
    });
    box.appendChild(del);
    return box;
  }
  function showDetailModal(row) {
    const ro = (label, value) => `
      <div class="stack-sm">
        <label style="font-size:var(--fs-sm); color:var(--text-muted);">${label}</label>
        <pre style="white-space:pre-wrap; word-break:break-word; margin:0; font-family:var(--font-mono); font-size:var(--fs-sm); background:var(--surface-alt); padding:var(--space-2) var(--space-3); border-radius:var(--radius-md); max-height:260px; overflow:auto;">${window.escapeHtml(value != null && String(value).trim() !== "" ? String(value) : "—")}</pre>
      </div>`;
    const bd = modal(`
      <div class="modal" style="width:820px; max-width:95vw;">
        <div class="modal-header"><h2>VPD 정책 상세 <span class="muted" style="font-size:var(--fs-sm);">(읽기전용)</span></h2>
          <button class="btn btn-ghost" id="m-close">✕</button></div>
        <div class="modal-body stack">
          <div class="row" style="gap:12px;">
            <div style="flex:1;min-width:0;">${ro("스키마", row.object_owner)}</div>
            <div style="flex:1;min-width:0;">${ro("객체", row.object_name)}</div>
            <div style="flex:1;min-width:0;">${ro("사용", row.enable)}</div>
          </div>
          <div class="row" style="gap:12px;">
            <div style="flex:1;min-width:0;">${ro("정책명", row.policy_name)}</div>
            <div style="flex:1;min-width:0;">${ro("적용문", row.statement_types)}</div>
          </div>
          ${ro("정책 함수", `${row.function_schema}.${row.policy_function}`)}
          ${ro("정책 함수 소스", row.function_sql)}
          <div class="row end"><button class="btn btn-ghost" id="m-close2">닫기</button></div>
        </div>
      </div>`);
    bd.querySelector("#m-close").addEventListener("click", () => bd.remove());
    bd.querySelector("#m-close2").addEventListener("click", () => bd.remove());
  }

  // ── 탭2: VPD 테스트 ────────────────────────────────────
  function renderTestTab(host) {
    const st = loadState();
    host.innerHTML = `
      <div class="panel">
        <div class="panel-header"><h2>4단계 — VPD 테스트</h2></div>
        <div class="panel-body stack">
          <div class="muted" style="font-size:var(--fs-sm);">컨텍스트 값을 세팅한 뒤 <code>select ai showsql</code> 로 생성 SQL 을 확인합니다. VPD 가 WHERE 절을 자동 주입하므로, 같은 질문이라도 값에 따라 결과가 달라집니다. (설정 탭의 {NAME}/{SCHEMA} 를 사용)</div>
          <div class="row" style="gap:12px; align-items:flex-end;">
            <div class="stack-sm" style="flex:0 0 220px;">
              <label>컨텍스트 값 ({NAME})</label>
              <input type="text" id="vt-val" list="vt-val-list" value="${window.escapeAttr(st.test.value)}" style="font-family:var(--font-mono);">
              <datalist id="vt-val-list"><option value="개발부"><option value="인사부"><option value="영업부"></datalist>
            </div>
            <div class="stack-sm" style="flex:1;">
              <label>질문 (select ai showsql &lt;질문&gt;)</label>
              <input type="text" id="vt-q" value="${window.escapeAttr(st.test.question)}" style="width:100%;">
            </div>
          </div>
          <div class="row" style="gap:8px; justify-content:flex-end;">
            <button class="btn btn-primary" id="vt-script" type="button">테스트 스크립트 보기</button>
          </div>
          <div class="stack-sm">
            <label>미리보기</label>
            <pre id="vt-prev" style="white-space:pre; margin:0; font-family:var(--font-mono); font-size:var(--fs-sm); background:var(--surface-alt); padding:var(--space-3); border-radius:var(--radius-md); overflow:auto; min-height:140px;"></pre>
          </div>
        </div>
      </div>`;
    const valEl = host.querySelector("#vt-val"), qEl = host.querySelector("#vt-q"), prev = host.querySelector("#vt-prev");
    const refresh = () => {
      const x = loadState(); x.test = { value: valEl.value, question: qEl.value }; saveState(x);
      prev.textContent = genTest(x.params, x.test);
    };
    valEl.addEventListener("input", refresh);
    qEl.addEventListener("input", refresh);
    host.querySelector("#vt-script").addEventListener("click", () => {
      const x = loadState();
      showScriptModal(`VPD 테스트 스크립트 — ${valEl.value || ""}`, genTest(x.params, { value: valEl.value, question: qEl.value }));
    });
    refresh();
  }

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
          <div class="muted" style="font-size:var(--fs-sm); margin-top:8px;">※ 프런트 전용 mock — 실제 DB 에는 실행되지 않습니다. 위 스크립트를 SQL 툴에서 실행하세요.</div>
        </div>
        ${onApply ? `<div class="modal-footer row end" style="gap:8px;">
          <button class="btn btn-ghost" id="s-cancel">닫기</button>
          <button class="btn btn-primary" id="s-apply">${window.escapeHtml(applyLabel || "반영")}</button></div>` : ""}
      </div>`);
    bd.querySelector("#s-pre").textContent = sql;
    bd.querySelector("#s-close").addEventListener("click", () => bd.remove());
    if (bd.querySelector("#s-cancel")) bd.querySelector("#s-cancel").addEventListener("click", () => bd.remove());
    bd.querySelector("#s-copy").addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(sql); window.Toast.show("클립보드에 복사됨", "success"); }
      catch (_) { window.Toast.show("복사 실패", "error"); }
    });
    if (onApply) bd.querySelector("#s-apply").addEventListener("click", () => { onApply(); bd.remove(); });
  }

  window.Views = window.Views || {};
  window.Views.vpdSecurity = render;
})();
