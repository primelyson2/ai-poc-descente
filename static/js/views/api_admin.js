/** views/api_admin.js — 메뉴 [API관리] (상하구조).
 *  Autonomous Database 의 ORDS REST API(모듈/템플릿/핸들러)를 등록·관리한다.
 *  현재는 **서버 로직 없이 프런트(HTML)만** 구현한 테스트 버전:
 *   - 탭1 [API 생성]   : 모듈/템플릿/핸들러 값을 입력하면 실행 스크립트(ORDS.DEFINE_*)를 즉시 생성.
 *   - 탭2 [생성 내역]  : USER_ORDS_MODULES/TEMPLATES/HANDLERS/PARAMETERS 를 흉내낸 mock 으로 조회 UI.
 *   - 탭3 [호출 테스트]: Method/URL/인증/Body 를 받아 curl 을 만들고 fetch 로 실제 호출을 시도.
 *  추후 백엔드(app/routers/api_admin.py)가 붙으면 mock → 실제 쿼리/DDL 로 교체.
 */
(function () {
  // 화면 전환·탭 전환에도 입력값이 유지되도록 DB 스코프 localStorage 에 보관.
  const STORE_KEY = "apiAdmin.model";

  const DEFAULT_MODEL = {
    // 모듈 (ORDS.DEFINE_MODULE)
    module_name: "term-recommend",
    base_path: "term-recommend/",
    module_items_per_page: 0,
    status: "PUBLISHED",
    comments: "용어추천서비스",
    // 템플릿 (ORDS.DEFINE_TEMPLATE)
    pattern: "ask",
    // 핸들러 (ORDS.DEFINE_HANDLER)
    method: "POST",
    source_type: "plsql/block",
    handler_items_per_page: 0,
    source: `DECLARE
    v_conv_id  VARCHAR2(256);
    v_result   CLOB;
    v_pos      PLS_INTEGER := 1;
    v_chunk    VARCHAR2(2000 CHAR);
BEGIN
    v_conv_id := DBMS_CLOUD_AI.CREATE_CONVERSATION();

    v_result := DBMS_CLOUD_AI_AGENT.RUN_TEAM(
        team_name   => 'TEAM_TERM_RECOMMENDER',
        user_prompt => '명칭추천: ' || :col_name || CHR(10)
                    || '데이터샘플: ' || NVL(:data_sample, ''),
        params      => '{"conversation_id": "' || v_conv_id || '"}'
    );

    OWA_UTIL.MIME_HEADER('application/json', TRUE);
    WHILE v_pos <= DBMS_LOB.GETLENGTH(v_result) LOOP
        v_chunk := DBMS_LOB.SUBSTR(v_result, 2000, v_pos);
        HTP.PRN(v_chunk);
        v_pos := v_pos + LENGTH(v_chunk);
    END LOOP;

EXCEPTION
    WHEN OTHERS THEN
        HTP.PRN(
            JSON_OBJECT(
                'sqlcode'   VALUE SQLCODE,
                'sqlerrm'   VALUE SQLERRM,
                'backtrace' VALUE DBMS_UTILITY.FORMAT_ERROR_BACKTRACE
                RETURNING VARCHAR2(32767)
            )
        );
END;`,
    // 호출 (curl / 호출 테스트 공용)
    base_url: "https://g3a5735b34e0774-paidb.adb.ap-seoul-1.oraclecloudapps.com/ords/genai",
    auth_user: "GENAI",
    auth_pass: "",
    call_body: `{
  "col_name": "협력사명",
  "data_sample": "ABC상사, 가나무역, ..."
}`,
  };

  let model = { ...DEFAULT_MODEL };

  function loadModel() {
    try {
      const raw = window.Store.get(STORE_KEY);
      if (raw) model = { ...DEFAULT_MODEL, ...JSON.parse(raw) };
      else model = { ...DEFAULT_MODEL };
    } catch (_) {
      model = { ...DEFAULT_MODEL };
    }
  }
  function saveModel() {
    try {
      window.Store.set(STORE_KEY, JSON.stringify(model));
    } catch (_) {}
  }

  // ── 공통 헬퍼 ──────────────────────────────────────────────
  const PRE_STYLE =
    "white-space:pre; margin:0; font-family:var(--font-mono); font-size:var(--fs-sm); background:var(--surface-alt); padding:var(--space-3); border-radius:var(--radius-md); overflow:auto;";

  // base_url 끝 슬래시 + base_path/pattern 을 합쳐 최종 호출 URL 을 만든다.
  function buildCallUrl(m) {
    const root = (m.base_url || "").replace(/\/+$/, "");
    const path = (m.base_path || "").replace(/^\/+/, "");
    const pat = (m.pattern || "").replace(/^\/+/, "");
    return `${root}/${path}${pat}`;
  }

  function basicAuthHeader(m) {
    if (!m.auth_user && !m.auth_pass) return "";
    try {
      return "Basic " + btoa(`${m.auth_user}:${m.auth_pass}`);
    } catch (_) {
      return "";
    }
  }

  // ── 스크립트 생성 ──────────────────────────────────────────
  function generateScript(m) {
    const moduleIpp = Number(m.module_items_per_page) || 0;
    const handlerIpp = Number(m.handler_items_per_page) || 0;
    const callUrl = buildCallUrl(m);
    const authHeader = basicAuthHeader(m);
    const authLine = authHeader ? ` \\\n -H "Authorization: ${authHeader}"` : "";
    const bodyOneLine = (m.call_body || "{}").replace(/\s*\n\s*/g, " ").trim();

    return `-- ============================================================
-- Step 1: 모듈 생성
-- ============================================================
BEGIN
    ORDS.DEFINE_MODULE(
        p_module_name    => '${m.module_name}',
        p_base_path      => '${m.base_path}',
        p_items_per_page => ${moduleIpp},
        p_status         => '${m.status}',
        p_comments       => '${m.comments}'
    );
    COMMIT;
END;
/

-- ============================================================
-- Step 2: ${m.module_name} 템플릿 생성
-- ============================================================
BEGIN
    ORDS.DEFINE_TEMPLATE(
        p_module_name => '${m.module_name}',
        p_pattern     => '${m.pattern}'
    );
    COMMIT;
END;
/

-- ============================================================
-- Step 3: ${m.module_name} 핸들러 생성 (${m.method})
-- ============================================================
BEGIN
    ORDS.DEFINE_HANDLER(
        p_module_name    => '${m.module_name}',
        p_pattern        => '${m.pattern}',
        p_method         => '${m.method}',
        p_source_type    => '${m.source_type}',
        p_source         => q'[
${m.source}]',
        p_items_per_page => ${handlerIpp}
    );
    COMMIT;
END;
/

-- ============================================================
-- 삭제하기 — 모듈 통째로 삭제 (하위 템플릿/핸들러 모두 삭제됨)
-- ============================================================
BEGIN
    ORDS.DELETE_MODULE(
        p_module_name => '${m.module_name}'
    );
    COMMIT;
END;
/

-- ============================================================
-- 호출 (curl)
-- ============================================================
curl -s -X ${m.method} "${callUrl}" \\
 -H "Content-Type: application/json"${authLine} \\
 -d '${bodyOneLine}'`;
  }

  // ── 탭1: API 생성 ──────────────────────────────────────────
  function renderCreate(host) {
    host.innerHTML = `
      <div class="split-vert">
        <div class="panel">
          <div class="panel-header"><h2>① 모듈 (ORDS.DEFINE_MODULE)</h2>
            <button class="btn btn-mini" id="api-reset">기본값 복원</button>
          </div>
          <div class="panel-body">
            <div class="db-form">
              <div class="field">
                <label for="f-module-name">모듈명 (p_module_name)</label>
                <input id="f-module-name" type="text" value="${window.escapeAttr(model.module_name)}" />
              </div>
              <div class="field">
                <label for="f-base-path">기본 경로 (p_base_path)</label>
                <input id="f-base-path" type="text" value="${window.escapeAttr(model.base_path)}" placeholder="term-recommend/" />
              </div>
              <div class="field">
                <label for="f-status">상태 (p_status)</label>
                <select id="f-status">
                  <option value="PUBLISHED">PUBLISHED</option>
                  <option value="NOT_PUBLISHED">NOT_PUBLISHED</option>
                </select>
              </div>
              <div class="field">
                <label for="f-module-ipp">items_per_page (p_items_per_page)</label>
                <input id="f-module-ipp" type="number" min="0" value="${window.escapeAttr(model.module_items_per_page)}" />
              </div>
              <div class="field field-wide">
                <label for="f-comments">설명 (p_comments)</label>
                <input id="f-comments" type="text" value="${window.escapeAttr(model.comments)}" />
              </div>
            </div>
          </div>
        </div>

        <div class="panel">
          <div class="panel-header"><h2>② 템플릿 (ORDS.DEFINE_TEMPLATE)</h2></div>
          <div class="panel-body">
            <div class="db-form">
              <div class="field">
                <label for="f-pattern">URI 패턴 (p_pattern)</label>
                <input id="f-pattern" type="text" value="${window.escapeAttr(model.pattern)}" placeholder="ask" />
              </div>
            </div>
          </div>
        </div>

        <div class="panel">
          <div class="panel-header"><h2>③ 핸들러 (ORDS.DEFINE_HANDLER)</h2></div>
          <div class="panel-body">
            <div class="db-form">
              <div class="field">
                <label for="f-method">메서드 (p_method)</label>
                <select id="f-method">
                  <option value="POST">POST</option>
                  <option value="GET">GET</option>
                  <option value="PUT">PUT</option>
                  <option value="DELETE">DELETE</option>
                </select>
              </div>
              <div class="field">
                <label for="f-source-type">소스 타입 (p_source_type)</label>
                <input id="f-source-type" type="text" value="${window.escapeAttr(model.source_type)}" placeholder="plsql/block" />
              </div>
              <div class="field">
                <label for="f-handler-ipp">items_per_page (p_items_per_page)</label>
                <input id="f-handler-ipp" type="number" min="0" value="${window.escapeAttr(model.handler_items_per_page)}" />
              </div>
              <div class="field field-wide">
                <label for="f-source">소스 (p_source — q'[ ]' 로 감싸짐)</label>
                <textarea id="f-source" rows="14" style="font-family:var(--font-mono); font-size:var(--fs-sm);">${window.escapeHtml(model.source)}</textarea>
              </div>
            </div>
          </div>
        </div>

        <div class="panel scroll">
          <div class="panel-header"><h2>생성된 실행 스크립트</h2>
            <button class="btn btn-mini" id="api-copy-script">복사</button>
          </div>
          <div class="panel-body">
            <pre id="api-script" style="${PRE_STYLE}"></pre>
          </div>
        </div>
      </div>`;

    // 셀렉트 초기값
    host.querySelector("#f-status").value = model.status;
    host.querySelector("#f-method").value = model.method;

    const refresh = () => {
      model.module_name = host.querySelector("#f-module-name").value;
      model.base_path = host.querySelector("#f-base-path").value;
      model.status = host.querySelector("#f-status").value;
      model.module_items_per_page = host.querySelector("#f-module-ipp").value;
      model.comments = host.querySelector("#f-comments").value;
      model.pattern = host.querySelector("#f-pattern").value;
      model.method = host.querySelector("#f-method").value;
      model.source_type = host.querySelector("#f-source-type").value;
      model.handler_items_per_page = host.querySelector("#f-handler-ipp").value;
      model.source = host.querySelector("#f-source").value;
      saveModel();
      host.querySelector("#api-script").textContent = generateScript(model);
    };

    host.querySelectorAll("input, select, textarea").forEach((el) => {
      el.addEventListener("input", refresh);
      el.addEventListener("change", refresh);
    });

    host.querySelector("#api-reset").addEventListener("click", () => {
      model = { ...DEFAULT_MODEL };
      saveModel();
      renderCreate(host);
    });

    host.querySelector("#api-copy-script").addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(generateScript(model));
        window.Toast.show("스크립트를 복사했습니다", "success");
      } catch (_) {
        window.Toast.show("복사 실패", "error");
      }
    });

    refresh();
  }

  // ── 탭2: 생성 내역 조회 (mock) ─────────────────────────────
  // USER_ORDS_MODULES / _TEMPLATES / _HANDLERS / _PARAMETERS 를 흉내낸 샘플.
  const MOCK = {
    modules: [
      { id: 101, name: "term-recommend", base_path: "term-recommend/", status: "PUBLISHED", comments: "용어추천서비스" },
      { id: 102, name: "order_nlq", base_path: "order_nlq/", status: "PUBLISHED", comments: "주문 자연어 질의" },
      { id: 103, name: "sql_analysis", base_path: "sql_analysis/", status: "NOT_PUBLISHED", comments: "SQL 분석 서비스" },
    ],
    templates: {
      101: [{ id: 201, uri_template: "ask", priority: 0 }],
      102: [{ id: 202, uri_template: "ask", priority: 0 }],
      103: [
        { id: 203, uri_template: "search-dict", priority: 0 },
        { id: 204, uri_template: "explain", priority: 0 },
      ],
    },
    handlers: {
      201: [{ id: 301, method: "POST", source_type: "plsql/block", items_per_page: 0 }],
      202: [{ id: 302, method: "POST", source_type: "plsql/block", items_per_page: 0 }],
      203: [{ id: 303, method: "POST", source_type: "plsql/block", items_per_page: 0 }],
      204: [{ id: 304, method: "GET", source_type: "plsql/block", items_per_page: 25 }],
    },
    parameters: {
      301: [
        { name: "col_name", bind_variable: "col_name", source_type: "BODY", param_type: "STRING", access_method: "IN" },
        { name: "data_sample", bind_variable: "data_sample", source_type: "BODY", param_type: "STRING", access_method: "IN" },
      ],
      302: [{ name: "question", bind_variable: "question", source_type: "BODY", param_type: "STRING", access_method: "IN" }],
      303: [{ name: "keyword", bind_variable: "keyword", source_type: "BODY", param_type: "STRING", access_method: "IN" }],
      304: [],
    },
  };

  function renderList(host) {
    host.innerHTML = `
      <div class="split-vert">
        <div class="panel">
          <div class="panel-header"><h2>모듈 (USER_ORDS_MODULES)</h2>
            <span class="badge disabled">mock 데이터</span>
          </div>
          <div class="panel-body" id="api-modules"></div>
        </div>
        <div class="panel">
          <div class="panel-header"><h2 id="api-detail-title">상세 — 모듈을 선택하세요</h2></div>
          <div class="panel-body" id="api-detail">
            <div class="empty-state">위에서 모듈을 클릭하면 템플릿·핸들러·파라미터가 표시됩니다.</div>
          </div>
        </div>
      </div>`;

    const modCols = [
      { key: "id", label: "ID", align: "right" },
      { key: "name", label: "모듈명" },
      { key: "base_path", label: "기본 경로" },
      {
        key: "status",
        label: "상태",
        format: (v) => {
          const b = document.createElement("span");
          b.className = "badge " + (v === "PUBLISHED" ? "ok" : "disabled");
          b.textContent = v;
          return b;
        },
      },
      { key: "comments", label: "설명" },
    ];

    const modHost = host.querySelector("#api-modules");
    let selectedTr = null;
    modHost.innerHTML = "";
    modHost.appendChild(
      window.SimpleTable.create(modCols, MOCK.modules, {
        className: "table-grid keep-case",
        onRowClick: (row, tr) => {
          if (selectedTr) selectedTr.classList.remove("selected");
          tr.classList.add("selected");
          selectedTr = tr;
          renderModuleDetail(host, row);
        },
      })
    );
  }

  function renderModuleDetail(host, mod) {
    host.querySelector("#api-detail-title").textContent = `상세 — ${mod.name}`;
    const detail = host.querySelector("#api-detail");
    detail.innerHTML = "";

    const templates = MOCK.templates[mod.id] || [];
    templates.forEach((tpl) => {
      const handlers = MOCK.handlers[tpl.id] || [];

      const block = document.createElement("div");
      block.className = "stack";
      block.style.marginBottom = "var(--space-4)";

      const head = document.createElement("div");
      head.className = "row";
      head.innerHTML = `<span class="tree-tag tag-team">TEMPLATE</span>
        <strong style="font-family:var(--font-mono);">${window.escapeHtml(tpl.uri_template)}</strong>
        <span class="muted">priority ${tpl.priority}</span>`;
      block.appendChild(head);

      // 핸들러 + 파라미터
      handlers.forEach((h) => {
        const params = MOCK.parameters[h.id] || [];
        const hWrap = document.createElement("div");
        hWrap.style.marginLeft = "var(--space-4)";

        const hHead = document.createElement("div");
        hHead.className = "row";
        hHead.style.margin = "var(--space-2) 0";
        hHead.innerHTML = `<span class="tree-tag tag-agent">${window.escapeHtml(h.method)}</span>
          <span class="muted">${window.escapeHtml(h.source_type)}</span>
          <span class="muted">items_per_page ${h.items_per_page}</span>`;
        hWrap.appendChild(hHead);

        const pCols = [
          { key: "name", label: "파라미터" },
          { key: "bind_variable", label: "바인드 변수" },
          { key: "source_type", label: "소스" },
          { key: "param_type", label: "타입" },
          { key: "access_method", label: "방향" },
        ];
        hWrap.appendChild(
          window.SimpleTable.create(pCols, params, {
            className: "table-grid keep-case",
            emptyText: "파라미터 없음",
          })
        );
        block.appendChild(hWrap);
      });

      detail.appendChild(block);
    });

    // 참고용 조회 SQL
    const sqlNote = document.createElement("div");
    sqlNote.className = "field-hint";
    sqlNote.style.marginTop = "var(--space-3)";
    sqlNote.innerHTML = `실제 환경에서는 아래처럼 조회합니다:`;
    detail.appendChild(sqlNote);

    const pre = document.createElement("pre");
    pre.style.cssText = PRE_STYLE;
    pre.textContent = `SELECT h.*
FROM USER_ORDS_HANDLERS h
WHERE h.TEMPLATE_ID IN (
    SELECT t.ID FROM USER_ORDS_TEMPLATES t
    WHERE t.MODULE_ID IN (
        SELECT m.ID FROM USER_ORDS_MODULES m
        WHERE m.NAME = '${mod.name}'
    )
);`;
    detail.appendChild(pre);
  }

  // ── 탭3: 호출 테스트 ───────────────────────────────────────
  function renderCall(host) {
    host.innerHTML = `
      <div class="split-vert">
        <div class="panel">
          <div class="panel-header"><h2>요청 설정</h2></div>
          <div class="panel-body">
            <div class="db-form">
              <div class="field">
                <label for="c-method">Method</label>
                <select id="c-method">
                  <option value="POST">POST</option>
                  <option value="GET">GET</option>
                  <option value="PUT">PUT</option>
                  <option value="DELETE">DELETE</option>
                </select>
              </div>
              <div class="field">
                <label for="c-content-type">Content-Type</label>
                <input id="c-content-type" type="text" value="application/json" />
              </div>
              <div class="field field-wide">
                <label for="c-url">호출 URL</label>
                <input id="c-url" type="text" value="${window.escapeAttr(buildCallUrl(model))}" />
              </div>
              <div class="field">
                <label for="c-user">Basic 인증 — 사용자</label>
                <input id="c-user" type="text" value="${window.escapeAttr(model.auth_user)}" autocomplete="off" />
              </div>
              <div class="field">
                <label for="c-pass">Basic 인증 — 비밀번호</label>
                <input id="c-pass" type="password" value="${window.escapeAttr(model.auth_pass)}" autocomplete="off" />
              </div>
              <div class="field field-wide">
                <label for="c-body">Body (JSON)</label>
                <textarea id="c-body" rows="6" style="font-family:var(--font-mono); font-size:var(--fs-sm);">${window.escapeHtml(model.call_body)}</textarea>
              </div>
            </div>
            <div class="row" style="margin-top: var(--space-3);">
              <button class="btn btn-primary" id="c-send">호출</button>
              <button class="btn" id="c-copy-curl">curl 복사</button>
              <span class="field-hint" style="margin:0;">브라우저에서 직접 호출하므로 대상 ORDS 의 <strong>CORS</strong> 설정에 따라 차단될 수 있습니다.</span>
            </div>
          </div>
        </div>

        <div class="panel scroll">
          <div class="panel-header"><h2>응답</h2><span id="c-status" class="badge disabled">대기</span></div>
          <div class="panel-body">
            <pre id="c-response" style="${PRE_STYLE}">아직 호출하지 않았습니다.</pre>
          </div>
        </div>
      </div>`;

    host.querySelector("#c-method").value = model.method;

    const collect = () => {
      model.method = host.querySelector("#c-method").value;
      model.auth_user = host.querySelector("#c-user").value;
      model.auth_pass = host.querySelector("#c-pass").value;
      model.call_body = host.querySelector("#c-body").value;
      saveModel();
      return {
        method: model.method,
        url: host.querySelector("#c-url").value.trim(),
        contentType: host.querySelector("#c-content-type").value.trim(),
        body: model.call_body,
      };
    };

    const buildCurl = (req) => {
      const auth = basicAuthHeader(model);
      const authLine = auth ? ` \\\n -H "Authorization: ${auth}"` : "";
      const ctLine = req.contentType ? ` \\\n -H "Content-Type: ${req.contentType}"` : "";
      const bodyLine =
        req.method === "GET" || !req.body ? "" : ` \\\n -d '${req.body.replace(/\s*\n\s*/g, " ").trim()}'`;
      return `curl -s -X ${req.method} "${req.url}"${ctLine}${authLine}${bodyLine}`;
    };

    host.querySelector("#c-copy-curl").addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(buildCurl(collect()));
        window.Toast.show("curl 명령을 복사했습니다", "success");
      } catch (_) {
        window.Toast.show("복사 실패", "error");
      }
    });

    host.querySelector("#c-send").addEventListener("click", async () => {
      const req = collect();
      const btn = host.querySelector("#c-send");
      const badge = host.querySelector("#c-status");
      const out = host.querySelector("#c-response");
      if (!req.url) {
        window.Toast.show("호출 URL 을 입력하세요", "warn");
        return;
      }
      btn.disabled = true;
      badge.textContent = "호출 중…";
      badge.className = "badge disabled";
      out.textContent = "요청 중…";

      const headers = {};
      if (req.contentType) headers["Content-Type"] = req.contentType;
      const auth = basicAuthHeader(model);
      if (auth) headers["Authorization"] = auth;

      const opts = { method: req.method, headers };
      if (req.method !== "GET" && req.body) opts.body = req.body;

      const t0 = performance.now();
      try {
        const res = await fetch(req.url, opts);
        const elapsed = Math.round(performance.now() - t0);
        const text = await res.text();
        let pretty = text;
        try {
          pretty = JSON.stringify(JSON.parse(text), null, 2);
        } catch (_) {}
        badge.textContent = `${res.status} ${res.statusText} · ${elapsed}ms`;
        badge.className = "badge " + (res.ok ? "ok" : "danger");
        out.textContent = pretty || "(빈 응답)";
      } catch (err) {
        const elapsed = Math.round(performance.now() - t0);
        badge.textContent = `실패 · ${elapsed}ms`;
        badge.className = "badge danger";
        out.textContent =
          "호출 실패: " +
          (err && err.message ? err.message : err) +
          "\n\n네트워크 오류이거나 대상 ORDS 의 CORS 정책으로 차단되었을 수 있습니다.\n위 'curl 복사' 로 터미널에서 직접 호출해 보세요.";
      } finally {
        btn.disabled = false;
      }
    });
  }

  // ── 진입점 ─────────────────────────────────────────────────
  async function render() {
    loadModel();
    const main = document.getElementById("main");
    main.innerHTML = "";

    const title = document.createElement("div");
    title.className = "view-title";
    title.innerHTML = `<h1>API관리</h1>
      <span class="sub">Autonomous Database 의 ORDS REST API(모듈·템플릿·핸들러)를 생성·조회·호출 테스트합니다. (현재 프런트 전용 테스트 버전)</span>`;
    main.appendChild(title);

    const tabs = window.Tabs.create([
      { id: "create", label: "API 생성", render: renderCreate },
      { id: "list", label: "생성 내역 조회", render: renderList },
      { id: "call", label: "호출 테스트", render: renderCall },
    ]);
    main.appendChild(tabs);
  }

  window.Views = window.Views || {};
  window.Views.apiAdmin = render;
})();
