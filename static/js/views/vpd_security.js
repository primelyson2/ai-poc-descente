/** views/vpd_security.js — 메뉴 [Select AI Security - VPD]
 *
 * Oracle VPD(행 수준 보안)를 4단계로 설정·테스트한다. 2개 탭:
 *   · 탭1 [VPD 설정] : 공통 파라미터({NAME}/{SCHEMA}/{TABLE}) 입력 → 1·2·3단계 스크립트 치환
 *                      → [설정 실행](/api/vpd/run-script) + 등록 정책 목록(/api/vpd/policies)
 *   · 탭2 [VPD 테스트]: (1) Application Context 선택→세터 호출·SESSION_CONTEXT 확인(/api/vpd/set-context)
 *                      (2) 프로파일·질문→showsql 생성(/api/vpd/showsql)→실행 시 컨텍스트 세팅 후 SQL 실행(/api/vpd/exec-sql)
 *
 * 명명 규칙(vpd.sql 템플릿과 동일):
 *   컨텍스트 OAC_{NAME} · 세터 프로시저 PRC_OAC_SETINFO_{NAME}(MANAGER/EMPLID) · 함수 F_VPD_POLICY_{NAME} · 정책 VPD_POLICY_{NAME}
 */
(function () {
  const STATE_KEY = "oai.vpd.state.v6";   // 파라미터 + 편집한 단계 스크립트 + 테스트 입력
  // 기본값은 플레이스홀더 그대로 — 초기 스크립트에 {NAME}/{SCHEMA}/{TABLE} 가 표시된다.
  const DEFAULT_PARAMS = { NAME: "{NAME}", SCHEMA: "{SCHEMA}", TABLE: "{TABLE}", STMT: "SELECT" };
  const DEFAULT_TEST = { setBlock: "", question: "직원 목록을 주세요", profile: "" };

  const loadState = () => {
    try { const s = JSON.parse(localStorage.getItem(STATE_KEY) || "{}");
      return { params: { ...DEFAULT_PARAMS, ...(s.params || {}) }, steps: s.steps || {}, test: { ...DEFAULT_TEST, ...(s.test || {}) }, ctxSchema: s.ctxSchema || "" };
    } catch (e) { return { params: { ...DEFAULT_PARAMS }, steps: {}, test: { ...DEFAULT_TEST }, ctxSchema: "" }; }
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
      `CREATE OR REPLACE CONTEXT OAC_${N} USING PRC_OAC_SETINFO_${N};`,
      "",
      `CREATE OR REPLACE PROCEDURE PRC_OAC_SETINFO_${N}(`,
      "  -- ** 이 부분 수정 **",
      "  P_MANAGER VARCHAR2,",
      "  P_EMPLID  VARCHAR2",
      ") IS",
      "BEGIN",
      "  -- ** 이 부분 수정 **",
      `  DBMS_SESSION.SET_CONTEXT('OAC_${N}', 'MANAGER', P_MANAGER);`,
      `  DBMS_SESSION.SET_CONTEXT('OAC_${N}', 'EMPLID',  P_EMPLID);`,
      "END;",
      "/",
    ].join("\n");
  }
  function gen2(p) {
    const N = p.NAME;
    return [
      "-- 2. VPD 정책 함수 (WHERE 술어 반환) — 예시 로직은 대상 컬럼에 맞게 수정",
      "-- P_SCHEMA: 대상 객체의 스키마",
      "-- P_OBJECT: 대상 객체 이름(table/view)",
      `CREATE OR REPLACE FUNCTION F_VPD_POLICY_${N}(`,
      "  P_SCHEMA VARCHAR2, P_OBJECT VARCHAR2",
      ") RETURN VARCHAR2 AS",
      "  -- ** 이 부분 수정 **",
      `  V_MANAGER VARCHAR2(100) := SYS_CONTEXT('OAC_${N}','MANAGER');`,
      `  V_EMPLID  VARCHAR2(100) := SYS_CONTEXT('OAC_${N}','EMPLID');`,
      "BEGIN",
      "  -- ** 이 부분 수정 **",
      "  IF V_EMPLID IS NULL THEN",
      "    RETURN '1=0';                                   -- 컨텍스트 미설정 → 안전 차단",
      "  END IF;",
      "  V_EMPLID := REPLACE(V_EMPLID, '''', '''''');      -- 인젝션 방지",
      "  IF V_MANAGER = 'Y' THEN",
      "    -- 본인 + 직속 부하 (자기참조 서브쿼리 대신 직접 조건 — VPD 재귀 회피)",
      "    RETURN 'MANAGER_ID = ' || V_EMPLID || ' OR EMPLOYEE_ID = ' || V_EMPLID;",
      "  ELSE",
      "    RETURN 'EMPLOYEE_ID = ' || V_EMPLID;            -- 본인만",
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
      "    statement_types => 'SELECT'",
      "  );",
      "END;",
      "/",
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
            ${paramInput("NAME","{NAME} — VPD 제어 기준 이름", p.NAME, "컨텍스트/세터 프로시저/함수/정책 이름 접미사 (예: MANAGER)")}
            ${paramInput("SCHEMA","{SCHEMA} — 대상/함수 스키마", p.SCHEMA, "대상 객체가 있는 DB 스키마")}
            ${paramInput("TABLE","{TABLE} — 대상 객체(테이블/뷰)", p.TABLE, "VPD 를 적용할 객체")}
          </div>
        </div>
      </div>
      ${stepPanel(1,"Oracle Application Context","vp-s1",15)}
      ${stepPanel(2,"VPD 정책 함수 생성","vp-s2",24)}
      ${stepPanel(3,"VPD 정책 설정 (ADD_POLICY)","vp-s3",13)}
      <div class="panel"><div class="panel-body row" style="gap:8px; justify-content:flex-end;">
        <button class="btn" id="vp-all" type="button">전체 설정 스크립트</button>
        <button class="btn btn-primary" id="vp-run" type="button">설정 실행 (DB 적용)</button>
      </div></div>
      <div class="panel">
        <div class="panel-header"><h2>등록된 VPD 정책 <span class="muted" style="font-size:var(--fs-sm);">ALL_POLICIES</span></h2>
          <button class="btn btn-ghost" id="vp-listreload" type="button">↻ 새로고침</button>
        </div>
        <div class="panel-body" id="vp-list"></div>
      </div>
      <div class="panel">
        <div class="panel-header"><h2>Application Context <span class="muted" style="font-size:var(--fs-sm);">DBA_CONTEXT — namespace / schema / package(USING)</span></h2>
          <div class="row" style="gap:8px;">
            <input type="text" id="vp-ctx-schema" placeholder="SCHEMA 검색 (부분일치, 비우면 전체)" style="font-family:var(--font-mono); font-size:var(--fs-sm); width:240px;">
            <button class="btn btn-ghost" id="vp-ctxreload" type="button">↻ 조회</button>
          </div>
        </div>
        <div class="panel-body" id="vp-ctx"></div>
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

    $("#vp-reset").addEventListener("click", () => {
      // 파라미터 입력을 기본(플레이스홀더)으로 되돌린 뒤 스크립트 재생성
      host.querySelectorAll("input[data-param]").forEach((el) => { el.value = DEFAULT_PARAMS[el.dataset.param] || ""; });
      regen();
      window.Toast.show("{NAME}/{SCHEMA}/{TABLE} 기본 스크립트로 초기화했습니다", "success");
    });
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
          loadContexts(host, loadState().ctxSchema || "");  // Application Context 도 자동 재조회
        } catch (e) { window.Toast.show(errMsg(e, "설정 실행 실패"), "error"); }
      }, "실행 (DB 적용)");
    });
    $("#vp-listreload").addEventListener("click", () => loadList(host));
    loadList(host);

    // Application Context 조회 — SCHEMA 검색어를 localStorage(state.ctxSchema)에 저장/복원
    const ctxSchemaEl = $("#vp-ctx-schema");
    ctxSchemaEl.value = loadState().ctxSchema || "";
    const runCtx = () => {
      const v = ctxSchemaEl.value.trim();
      const x = loadState(); x.ctxSchema = v; saveState(x);
      loadContexts(host, v);
    };
    $("#vp-ctxreload").addEventListener("click", runCtx);
    ctxSchemaEl.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); runCtx(); } });
    ctxSchemaEl.addEventListener("change", () => { const x = loadState(); x.ctxSchema = ctxSchemaEl.value.trim(); saveState(x); });
    loadContexts(host, ctxSchemaEl.value.trim());
  }

  // ── Application Context 목록 (DBA_CONTEXT, SCHEMA 부분일치 필터) ────
  async function loadContexts(host, schema) {
    const h = host.querySelector("#vp-ctx");
    if (!h) return;
    h.innerHTML = '<div class="empty-state"><span class="spinner"></span> 조회 중...</div>';
    const qs = (schema || "").trim() ? ("?schema=" + encodeURIComponent(schema.trim())) : "";
    let rows;
    try { rows = await window.API.get("/api/vpd/contexts" + qs); }
    catch (e) { h.innerHTML = `<div class="empty-state muted">${window.escapeHtml(errMsg(e, "Application Context 조회 실패"))}</div>`; return; }
    h.innerHTML = "";
    h.appendChild(window.SimpleTable.create(
      [
        { key: "namespace", label: "NAMESPACE" },
        { key: "schema", label: "SCHEMA" },
        { key: "package", label: "PACKAGE (USING)" },
        { key: "_act", label: "", headerAlign: "center", align: "center", format: (_v, row) => buildContextActions(row, host) },
      ],
      rows || [],
      { className: "keep-case", emptyText: "정의된 Application Context 가 없습니다." }
    ));
  }

  function buildContextActions(row, host) {
    const box = document.createElement("div");
    box.className = "row"; box.style.gap = "6px"; box.style.justifyContent = "center";
    box.addEventListener("click", (e) => e.stopPropagation());
    const del = document.createElement("button");
    del.className = "btn btn-primary"; del.textContent = "삭제";
    del.addEventListener("click", () => showContextDeleteModal(row, host));
    box.appendChild(del);
    return box;
  }

  // Application Context 삭제 — "USING 객체(Package/프로시저/함수)도 함께 삭제할지" 물어본 뒤 실행.
  function showContextDeleteModal(row, host) {
    const ns = row.namespace, sch = row.schema, pkg = row.package;
    const hasUsing = !!(sch && pkg);
    const usingLabel = hasUsing ? `${sch}.${pkg}` : "";
    const dropCtx = `DROP CONTEXT ${ns};`;
    const dropUsing = hasUsing ? `DROP PROCEDURE ${usingLabel};` : "";  // USING 객체는 프로시저로 가정
    const bd = modal(`
      <div class="modal" style="width:680px; max-width:95vw;">
        <div class="modal-header"><h2>Application Context 삭제 — ${window.escapeHtml(ns)}</h2>
          <button class="btn btn-ghost" id="cd-close">✕</button></div>
        <div class="modal-body stack">
          <div>컨텍스트 <b>${window.escapeHtml(ns)}</b> 를 삭제합니다.</div>
          ${hasUsing ? `
          <label class="row" style="gap:8px; align-items:center; cursor:pointer;">
            <input type="checkbox" id="cd-pkg"> USING 객체 <code>${window.escapeHtml(usingLabel)}</code> <span class="muted">(PROCEDURE)</span> 도 함께 삭제
          </label>` : `<div class="muted" style="font-size:var(--fs-sm);">USING 객체 정보가 없어 컨텍스트만 삭제합니다.</div>`}
          <label style="font-size:var(--fs-sm); color:var(--text-muted);">실행 스크립트</label>
          <pre id="cd-sql" style="white-space:pre; margin:0; font-family:var(--font-mono); font-size:var(--fs-sm); background:var(--surface-alt); padding:var(--space-3); border-radius:var(--radius-md); overflow:auto; max-height:40vh;"></pre>
        </div>
        <div class="modal-footer row end" style="gap:8px;">
          <button class="btn btn-ghost" id="cd-cancel">취소</button>
          <button class="btn btn-primary" id="cd-run">삭제 실행</button>
        </div>
      </div>`);
    const chk = bd.querySelector("#cd-pkg"), pre = bd.querySelector("#cd-sql");
    const refresh = () => { pre.textContent = (chk && chk.checked) ? `${dropCtx}\n\n${dropUsing}` : dropCtx; };
    refresh();
    if (chk) chk.addEventListener("change", refresh);
    bd.querySelector("#cd-close").addEventListener("click", () => bd.remove());
    bd.querySelector("#cd-cancel").addEventListener("click", () => bd.remove());
    bd.querySelector("#cd-run").addEventListener("click", async () => {
      const withPkg = !!(chk && chk.checked);
      const btn = bd.querySelector("#cd-run"); btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> 삭제 중...';
      try {
        const res = await window.API.post("/api/vpd/context/drop", {
          namespace: ns, drop_package: withPkg, schema: sch, package: pkg,
        });
        if (withPkg && res && res.package_error) {
          window.Toast.show(`컨텍스트 '${ns}' 삭제됨 · USING 객체 삭제 실패: ${res.package_error}`, "error");
        } else if (withPkg && res && res.package_dropped) {
          window.Toast.show(`컨텍스트 '${ns}' + USING 객체 '${usingLabel}' 삭제됨`, "success");
        } else {
          window.Toast.show(`컨텍스트 '${ns}' 삭제됨`, "success");
        }
        loadContexts(host, loadState().ctxSchema || "");
      } catch (e) { window.Toast.show(errMsg(e, "삭제 실패"), "error"); }
      finally { bd.remove(); }
    });
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
    toggle.className = "btn btn-primary"; toggle.textContent = on ? "사용중지" : "재개";
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
    del.addEventListener("click", () => showPolicyDeleteModal(row, host, key));
    box.appendChild(del);
    return box;
  }

  // 정책 삭제 — "정책 함수도 함께 삭제할지" 물어본 뒤 실행.
  function showPolicyDeleteModal(row, host, key) {
    // 정책 함수 대상: package 컬럼이 있으면 패키지, 없으면 standalone 함수.
    const isPkg = !!row.package;
    const fSchema = row.pf_owner, fObj = isPkg ? row.package : row.function;
    const fLabel = `${fSchema}.${fObj}`;
    const dropPolicy = `BEGIN\n  DBMS_RLS.DROP_POLICY(object_schema => '${row.object_owner}', object_name => '${row.object_name}', policy_name => '${row.policy_name}');\nEND;\n/`;
    const dropFn = `DROP ${isPkg ? "PACKAGE" : "FUNCTION"} ${fLabel};`;
    const bd = modal(`
      <div class="modal" style="width:680px; max-width:95vw;">
        <div class="modal-header"><h2>정책 삭제 — ${window.escapeHtml(row.policy_name)}</h2>
          <button class="btn btn-ghost" id="pd-close">✕</button></div>
        <div class="modal-body stack">
          <div>정책 <b>${window.escapeHtml(row.policy_name)}</b> <span class="muted">(${window.escapeHtml(row.object_owner)}.${window.escapeHtml(row.object_name)})</span> 를 삭제합니다.</div>
          <label class="row" style="gap:8px; align-items:center; cursor:pointer;">
            <input type="checkbox" id="pd-fn"> 정책 함수 <code>${window.escapeHtml(fLabel)}</code> 도 함께 삭제
          </label>
          <label style="font-size:var(--fs-sm); color:var(--text-muted);">실행 스크립트</label>
          <pre id="pd-sql" style="white-space:pre; margin:0; font-family:var(--font-mono); font-size:var(--fs-sm); background:var(--surface-alt); padding:var(--space-3); border-radius:var(--radius-md); overflow:auto; max-height:40vh;"></pre>
        </div>
        <div class="modal-footer row end" style="gap:8px;">
          <button class="btn btn-ghost" id="pd-cancel">취소</button>
          <button class="btn btn-primary" id="pd-run">삭제 실행</button>
        </div>
      </div>`);
    const chk = bd.querySelector("#pd-fn"), pre = bd.querySelector("#pd-sql");
    const refresh = () => { pre.textContent = chk.checked ? `${dropPolicy}\n\n${dropFn}` : dropPolicy; };
    refresh();
    chk.addEventListener("change", refresh);
    bd.querySelector("#pd-close").addEventListener("click", () => bd.remove());
    bd.querySelector("#pd-cancel").addEventListener("click", () => bd.remove());
    bd.querySelector("#pd-run").addEventListener("click", async () => {
      const withFn = chk.checked;
      const btn = bd.querySelector("#pd-run"); btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> 삭제 중...';
      try {
        const res = await window.API.post("/api/vpd/policy/drop", {
          ...key, drop_function: withFn, function_schema: fSchema, function_name: fObj, function_is_package: isPkg,
        });
        if (withFn && res && res.function_error) {
          window.Toast.show(`정책 '${row.policy_name}' 삭제됨 · 함수 삭제 실패: ${res.function_error}`, "error");
        } else if (withFn && res && res.function_dropped) {
          window.Toast.show(`정책 '${row.policy_name}' + 함수 '${fLabel}' 삭제됨`, "success");
        } else {
          window.Toast.show(`정책 '${row.policy_name}' 삭제됨`, "success");
        }
        loadList(host);
      } catch (e) { window.Toast.show(errMsg(e, "삭제 실패"), "error"); }
      finally { bd.remove(); }
    });
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
  // 흐름: (1) Application Context 선택 → 세터 호출 코드 생성 → 파라미터 입력·실행 → SESSION_CONTEXT 확인
  //       (2) AI Profile·질문 → showsql 로 SQL 생성 → [실행] 시 (1)의 컨텍스트를 같은 세션에 세팅 후 실행
  async function renderTestTab(host) {
    const st = loadState();
    host.innerHTML = `
      <div class="panel">
        <div class="panel-header"><h2>1) 컨텍스트 설정 &amp; 확인 <span class="muted" style="font-size:var(--fs-sm);">Application Context 선택 → 세터 호출 → SESSION_CONTEXT 조회</span></h2>
          <div class="row" style="gap:8px;">
            <input type="text" id="vt-ctx-schema" placeholder="SCHEMA 검색 (부분일치, 비우면 전체)" style="font-family:var(--font-mono); font-size:var(--fs-sm); width:240px;">
            <button class="btn btn-ghost" id="vt-ctxreload" type="button">↻ 조회</button>
          </div>
        </div>
        <div class="panel-body stack">
          <div class="muted" style="font-size:var(--fs-sm);">아래 목록에서 컨텍스트를 <b>선택</b>하면 세터 호출 코드(<code>BEGIN 패키지(); END;</code>)가 만들어집니다. 파라미터를 채우고 <b>[컨텍스트 설정 실행]</b>을 누르면 그 세션에서 실행한 뒤 <code>SESSION_CONTEXT</code>를 조회합니다.</div>
          <div id="vt-ctxlist"></div>
          <label style="display:block; font-weight:600;">세터 호출 코드 <span class="muted" style="font-size:var(--fs-sm);">(파라미터 입력 후 실행)</span></label>
          <textarea id="vt-setblock" rows="4" style="width:100%; font-family:var(--font-mono); font-size:var(--fs-sm);" placeholder="위 목록에서 컨텍스트를 선택하면 자동 생성됩니다">${window.escapeHtml(st.test.setBlock || "")}</textarea>
          <div class="row" style="justify-content:flex-end;"><button class="btn btn-primary" id="vt-setrun" type="button">컨텍스트 설정 실행</button></div>
          <label style="display:block; font-weight:600;">SESSION_CONTEXT <span class="muted" style="font-size:var(--fs-sm);">(설정 결과 — namespace / attribute / value)</span></label>
          <div id="vt-sessctx"></div>
        </div>
      </div>
      <div class="panel">
        <div class="panel-header"><h2>2) AI 질의 테스트 <span class="muted" style="font-size:var(--fs-sm);">showsql 로 SQL 생성 → 실행(위 컨텍스트를 같은 세션에 세팅해 VPD 적용)</span></h2></div>
        <div class="panel-body stack">
          <div class="row" style="gap:12px; align-items:flex-end; flex-wrap:wrap;">
            <div class="stack-sm" style="flex:0 0 240px;">
              <label>AI Profile</label>
              <select id="vt-profile"><option value="">불러오는 중…</option></select>
            </div>
            <div class="stack-sm" style="flex:1; min-width:220px;">
              <label>질문</label>
              <input type="text" id="vt-q" value="${window.escapeAttr(st.test.question || "")}" style="width:100%;">
            </div>
            <div><button class="btn" id="vt-gen" type="button">SQL 생성 (showsql)</button></div>
          </div>
          <label style="display:block; font-weight:600;">생성된 SQL <span class="muted" style="font-size:var(--fs-sm);">(실행 전 확인·수정 가능)</span></label>
          <textarea id="vt-sql" rows="6" style="width:100%; font-family:var(--font-mono); font-size:var(--fs-sm);" placeholder="[SQL 생성] 을 누르면 showsql 결과가 표시됩니다"></textarea>
          <div class="row" style="justify-content:flex-end;"><button class="btn btn-primary" id="vt-exec" type="button">실행</button></div>
          <div id="vt-out"></div>
        </div>
      </div>`;

    const $ = (s) => host.querySelector(s);
    const setEl = $("#vt-setblock"), sessOut = $("#vt-sessctx");
    const profileSel = $("#vt-profile"), qEl = $("#vt-q"), sqlEl = $("#vt-sql"), out = $("#vt-out");

    const persist = () => { const x = loadState(); x.test = { setBlock: setEl.value, question: qEl.value, profile: profileSel.value }; saveState(x); };
    [setEl, qEl, profileSel].forEach((el) => el.addEventListener("change", persist));

    // ── (1) 컨텍스트 목록 로드 + 선택 → 세터 호출 코드 생성 ──
    // schema 검색어는 VPD 설정 탭의 Application Context 검색과 같은 state.ctxSchema 를 공유한다.
    async function loadCtxList(schema) {
      const h = $("#vt-ctxlist");
      h.innerHTML = '<div class="empty-state"><span class="spinner"></span> 조회 중...</div>';
      const qs = (schema || "").trim() ? ("?schema=" + encodeURIComponent(schema.trim())) : "";
      let rows;
      try { rows = await window.API.get("/api/vpd/contexts" + qs); }
      catch (e) { h.innerHTML = `<div class="empty-state muted">${window.escapeHtml(errMsg(e, "Application Context 조회 실패"))}</div>`; return; }
      h.innerHTML = "";
      h.appendChild(window.SimpleTable.create(
        [
          { key: "namespace", label: "NAMESPACE" },
          { key: "schema", label: "SCHEMA" },
          { key: "package", label: "PACKAGE (USING)" },
        ],
        rows || [],
        { className: "keep-case", emptyText: "정의된 Application Context 가 없습니다.",
          onRowClick: (row) => {
            if (!row.package) { window.Toast.show("이 컨텍스트에는 USING 패키지가 없습니다", "warn"); return; }
            setEl.value = `BEGIN\n  ${row.package}();\nEND;`;
            persist();
            window.Toast.show(`'${row.namespace}' 세터 호출 코드를 생성했습니다 — 파라미터를 채워 실행하세요`, "success");
          } }
      ));
    }
    // SCHEMA 검색 — VPD 설정 탭과 동일한 저장값(state.ctxSchema)을 공유
    const ctxSchemaEl = $("#vt-ctx-schema");
    ctxSchemaEl.value = loadState().ctxSchema || "";
    const runCtxList = () => {
      const v = ctxSchemaEl.value.trim();
      const x = loadState(); x.ctxSchema = v; saveState(x);
      loadCtxList(v);
    };
    $("#vt-ctxreload").addEventListener("click", runCtxList);
    ctxSchemaEl.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); runCtxList(); } });
    ctxSchemaEl.addEventListener("change", () => { const x = loadState(); x.ctxSchema = ctxSchemaEl.value.trim(); saveState(x); });
    loadCtxList(ctxSchemaEl.value.trim());

    // ── (1) 컨텍스트 설정 실행 → SESSION_CONTEXT 조회 ──
    $("#vt-setrun").addEventListener("click", async () => {
      const block = setEl.value.trim();
      if (!block) { window.Toast.show("세터 호출 코드를 입력하세요 (위 목록에서 컨텍스트 선택)", "warn"); return; }
      persist();
      sessOut.innerHTML = '<div class="empty-state"><span class="spinner"></span> 실행 중...</div>';
      let res;
      try { res = await window.API.post("/api/vpd/set-context", { block }); }
      catch (e) { sessOut.innerHTML = `<div class="empty-state muted">${window.escapeHtml(errMsg(e, "컨텍스트 설정 실패"))}</div>`; return; }
      if (res.error) { sessOut.innerHTML = `<div class="empty-state muted">${window.escapeHtml(res.error)}</div>`; return; }
      sessOut.innerHTML = "";
      sessOut.appendChild(window.SimpleTable.create(
        [
          { key: "namespace", label: "NAMESPACE" },
          { key: "attribute", label: "ATTRIBUTE" },
          { key: "value", label: "VALUE" },
        ],
        res.session_context || [],
        { className: "keep-case", emptyText: "설정된 세션 컨텍스트가 없습니다." }
      ));
      window.Toast.show("컨텍스트 설정 실행 완료", "success");
    });

    // ── 프로파일 로드 ──
    try {
      const profiles = await window.API.get("/api/profiles");
      const names = (profiles || []).filter((p) => p.status === "ENABLED").map((p) => p.profile_name);
      profileSel.innerHTML = names.length ? names.map((n) => `<option value="${window.escapeAttr(n)}">${window.escapeHtml(n)}</option>`).join("")
        : `<option value="">사용 가능한 Profile 없음</option>`;
      if (st.test.profile && names.includes(st.test.profile)) profileSel.value = st.test.profile;
    } catch (e) { profileSel.innerHTML = `<option value="">Profile 로드 실패</option>`; }

    // ── (2) showsql 로 SQL 생성 (실행 안 함) ──
    $("#vt-gen").addEventListener("click", async () => {
      const profile = profileSel.value;
      if (!profile) { window.Toast.show("AI Profile 을 선택하세요", "warn"); return; }
      if (!qEl.value.trim()) { window.Toast.show("질문을 입력하세요", "warn"); return; }
      persist();
      const btn = $("#vt-gen"); btn.disabled = true; const old = btn.textContent; btn.textContent = "생성 중...";
      out.innerHTML = "";
      try {
        const res = await window.API.post("/api/vpd/showsql", { profile, question: qEl.value });
        if (res.error) { window.Toast.show(res.error, "error"); }
        else { sqlEl.value = res.sql || ""; window.Toast.show("SQL 생성 완료 — 확인 후 [실행]", "success"); }
      } catch (e) { window.Toast.show(errMsg(e, "SQL 생성 실패"), "error"); }
      finally { btn.disabled = false; btn.textContent = old; }
    });

    // ── (2) 실행 — 컨텍스트(세터 블록)를 같은 세션에 세팅 후 SQL 실행 → 결과 ──
    $("#vt-exec").addEventListener("click", async () => {
      const sql = sqlEl.value.trim();
      if (!sql) { window.Toast.show("실행할 SQL 이 없습니다 ([SQL 생성] 먼저)", "warn"); return; }
      persist();
      out.innerHTML = '<div class="empty-state"><span class="spinner"></span> 실행 중...</div>';
      let res;
      try { res = await window.API.post("/api/vpd/exec-sql", { sql, set_block: setEl.value.trim() }); }
      catch (e) { out.innerHTML = `<div class="empty-state muted">${window.escapeHtml(errMsg(e, "실행 실패"))}</div>`; return; }
      out.innerHTML = "";
      if (res.error) { out.appendChild(divFromHtml(`<div class="empty-state muted">${window.escapeHtml(res.error)}</div>`)); return; }
      const rl = document.createElement("label"); lbl_style(rl);
      rl.textContent = `실행 결과 (VPD 적용, ${(res.rows || []).length}행${res.truncated ? "+" : ""})`; out.appendChild(rl);
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
