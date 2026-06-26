/** views/profile_test.js — 메뉴 [2] AI Profile Test (2 탭, 상하구조). */
(function () {
  let chartInstance = null;
  let REGIONS = [];  // region 속성 드롭다운 후보 (project/regions.txt)
  let MODELS = {};   // region -> model 후보 (project/models.txt)

  // region/model 후보 로드. force=true 면 항상 재요청, false 면 비어 있을 때만.
  async function ensureMeta(force) {
    if (force || !REGIONS.length) {
      try { REGIONS = await window.API.get("/api/regions"); }
      catch (e) { if (force) REGIONS = []; }
    }
    if (force || !Object.keys(MODELS).length) {
      try { MODELS = await window.API.get("/api/models"); }
      catch (e) { if (force) MODELS = {}; }
    }
  }

  async function render() {
    const main = document.getElementById("main");
    main.innerHTML = "";

    // region / model 후보 목록 — 실패해도 화면은 계속 (드롭다운 대신 자유 입력으로 폴백)
    await ensureMeta(true);

    const title = document.createElement("div");
    title.className = "view-title";
    title.innerHTML = `<h1>AI Profile Test</h1>
      <span class="sub">생성된 AI Profile 조회 + 동일 프롬프트의 응답 속도 비교.</span>`;
    main.appendChild(title);

    // Profile 데이터 한번 로드 후 두 탭에서 공유
    let profiles = [];
    try {
      profiles = await window.API.get("/api/profiles");
    } catch (e) {
      const msg = errMsg(e, "Profile 목록 로드 실패");
      main.appendChild(div(`<div class="empty-state muted">${msg}</div>`));
      return;
    }

    const tabs = window.Tabs.create([
      { id: "list", label: "1. Profile 목록 / 속성", render: (host) => renderTab1(host, profiles) },
      { id: "bench", label: "2. 속도 측정 및 비교", render: (host) => renderTab2(host, profiles) },
      { id: "feedback", label: "3. Feedback 관리", render: (host) => renderTab3(host, profiles) },
    ]);
    main.appendChild(tabs);
  }

  // --- Tab 1 ---
  async function renderTab1(host, profiles) {
    host.innerHTML = "";
    const wrap = document.createElement("div");
    wrap.className = "split-vert";
    host.appendChild(wrap);

    const topPanel = document.createElement("div");
    topPanel.className = "panel";
    topPanel.innerHTML = `
      <div class="panel-header">
        <h2>Profile 목록</h2>
        <button class="btn btn-ghost" id="pt-refresh">↻ 새로고침</button>
      </div>
      <div class="panel-body" id="pt-list"></div>
    `;
    wrap.appendChild(topPanel);

    const bottomPanel = document.createElement("div");
    bottomPanel.className = "panel";
    bottomPanel.innerHTML = `
      <div class="panel-header">
        <h2 id="pt-attr-title">Profile 속성</h2>
        <button class="btn btn-primary" id="pt-gen-sql" disabled>AI Profile 구문 생성</button>
      </div>
      <div class="panel-body" id="pt-attr">
        <div class="empty-state muted">상단에서 Profile 을 선택하세요</div>
      </div>
    `;
    wrap.appendChild(bottomPanel);

    // 현재 선택된 Profile / 속성 — 헤더 버튼이 참조
    let currentProfileName = null;
    let currentAttrs = [];
    document.getElementById("pt-gen-sql").addEventListener("click", () => {
      if (!currentProfileName) return;
      const sql = buildCreateProfileSql(currentProfileName, currentAttrs);
      showSqlModal(`CREATE PROFILE — ${currentProfileName}`, sql);
    });

    function renderList() {
      const list = document.getElementById("pt-list");
      list.innerHTML = "";
      const table = window.SimpleTable.create(
        [
          { key: "profile_name", label: "Profile Name" },
          { key: "status",       label: "Status",
            format: (v) => {
              const span = document.createElement("span");
              span.className = "badge " + (v === "ENABLED" ? "ok" : "disabled");
              span.textContent = v;
              return span;
            }},
          { key: "description",  label: "Description" },
          { key: "_test", label: "", headerAlign: "center",
            format: (_v, row) => {
              const btn = document.createElement("button");
              btn.className = "btn-ai-test";
              btn.textContent = "AI Test";
              btn.disabled = row.status !== "ENABLED";
              btn.addEventListener("click", (e) => {
                e.stopPropagation();  // 행 선택(속성 로드) 이벤트와 분리
                openProfileTestModal(row.profile_name);
              });
              return btn;
            }},
        ],
        profiles,
        {
          onRowClick: async (row, tr) => {
            list.querySelectorAll("tr.selected").forEach((el) => el.classList.remove("selected"));
            tr.classList.add("selected");
            document.getElementById("pt-attr-title").textContent = `속성 - ${row.profile_name}`;
            const genBtn = document.getElementById("pt-gen-sql");
            genBtn.disabled = true;
            const attrHost = document.getElementById("pt-attr");
            attrHost.innerHTML = '<div class="empty-state"><span class="spinner"></span> 조회 중...</div>';
            try {
              const attrs = await window.API.get(`/api/profiles/${encodeURIComponent(row.profile_name)}/attributes`);
              currentProfileName = row.profile_name;
              currentAttrs = attrs;
              attrHost.innerHTML = "";
              attrHost.appendChild(buildProfileAttrTable(row.profile_name, attrs));
              genBtn.disabled = false;
            } catch (e) {
              attrHost.innerHTML = '<div class="empty-state muted">조회 실패</div>';
            }
          },
        }
      );
      list.appendChild(table);
    }
    renderList();
    document.getElementById("pt-refresh").addEventListener("click", async () => {
      try {
        const fresh = await window.API.get("/api/profiles");
        profiles.splice(0, profiles.length, ...fresh);
        renderList();
        window.Toast.show("Profile 목록 갱신", "success");
      } catch (e) { window.Toast.show("새로고침 실패", "error"); }
    });
  }

  // --- Tab 2 ---
  function renderTab2(host, profiles) {
    host.innerHTML = "";
    const wrap = document.createElement("div");
    wrap.className = "split-vert";
    host.appendChild(wrap);

    // 상단: 폼
    const formPanel = document.createElement("div");
    formPanel.className = "panel";
    formPanel.innerHTML = `
      <div class="panel-header"><h2>측정 조건</h2></div>
      <div class="panel-body">
        <div class="benchmark-form">
          <div class="col-prompt stack-sm">
            <div class="row" style="justify-content: space-between;">
              <label>프롬프트</label>
              <div class="row" style="gap:6px;">
                <input type="text" id="bm-prompt-title" placeholder="저장할 제목" style="width:130px;">
                <button class="btn" id="bm-prompt-add">추가</button>
                <button class="btn" id="bm-prompt-update">수정</button>
                <select id="bm-prompt-saved" style="min-width:150px;"></select>
              </div>
            </div>
            <textarea id="bm-prompt" rows="3">Oracle이 어떤 회사인지 설명해줘. 300자 이내로 설명해줘.</textarea>
          </div>
          <div class="stack-sm">
            <label>Action</label>
            <select id="bm-action">
              <option value="chat" selected>chat</option>
              <option value="runsql">runsql</option>
              <option value="narrate">narrate</option>
              <option value="showsql">showsql</option>
              <option value="explainsql">explainsql</option>
            </select>
          </div>
          <div class="stack-sm">
            <label>반복 횟수 (1-10)</label>
            <input type="number" id="bm-iter" min="1" max="10" value="3" />
          </div>
          <div class="col-prompt stack-sm">
            <label>AI Profile 선택 <span class="muted" id="bm-profile-hint"></span></label>
            <select id="bm-profile" style="max-width:320px;"></select>
          </div>
          <div class="col-prompt stack-sm">
            <label>LLM Model 다중 선택 <span class="muted" id="bm-models-hint"></span></label>
            <div class="checklist" id="bm-models"></div>
          </div>
          <div class="col-prompt row end">
            <button class="btn btn-primary" id="bm-run">▶ 실행</button>
          </div>
        </div>
      </div>
    `;
    wrap.appendChild(formPanel);

    // object_list 가 필요한 action — 해당 action 선택 시 has_object_list='Y' 만 노출
    const OBJECT_LIST_ACTIONS = new Set(["runsql", "narrate", "showsql"]);
    // profile_name -> { region, model } 캐시 (속성 재조회 방지)
    const profileMetaCache = {};

    async function getProfileMeta(name) {
      if (profileMetaCache[name]) return profileMetaCache[name];
      const attrs = await window.API.get(`/api/profiles/${encodeURIComponent(name)}/attributes`);
      const valueOf = (n) => {
        const a = attrs.find((x) => x.attribute_name === n);
        return a && a.attribute_value != null ? String(a.attribute_value) : "";
      };
      const meta = { region: valueOf("region"), model: valueOf("model") };
      profileMetaCache[name] = meta;
      return meta;
    }

    // 단일 Profile <select> 채우기 — action 에 따라 object_list 필요 Profile 만 노출
    function renderProfileSelect() {
      const action = document.getElementById("bm-action").value;
      const sel = document.getElementById("bm-profile");
      const requiresObjects = OBJECT_LIST_ACTIONS.has(action);
      const pool = requiresObjects ? profiles.filter((p) => p.has_object_list === "Y") : profiles;
      const visible = pool.filter((p) => p.status === "ENABLED");
      const prev = sel.value;
      sel.innerHTML = "";
      if (visible.length === 0) {
        const o = document.createElement("option");
        o.value = "";
        o.textContent = requiresObjects
          ? `${action} 에 사용 가능한 Profile (object_list 설정) 이 없습니다`
          : "사용 가능한 Profile 이 없습니다";
        sel.appendChild(o);
        renderModelChecklist();
        return;
      }
      visible.forEach((p) => {
        const o = document.createElement("option");
        o.value = p.profile_name;
        o.textContent = p.profile_name;
        sel.appendChild(o);
      });
      sel.value = visible.some((p) => p.profile_name === prev) ? prev : visible[0].profile_name;
      renderModelChecklist();
    }

    // 선택된 Profile 의 region 에 해당하는 model 후보를 체크리스트로 — 현재 model 은 기본 체크
    async function renderModelChecklist() {
      const sel = document.getElementById("bm-profile");
      const host = document.getElementById("bm-models");
      const hint = document.getElementById("bm-models-hint");
      const pHint = document.getElementById("bm-profile-hint");
      const name = sel.value;
      pHint.textContent = "";
      hint.textContent = "";
      if (!name) {
        host.innerHTML = `<div class="muted">Profile 을 먼저 선택하세요</div>`;
        return;
      }
      host.innerHTML = `<div class="muted"><span class="spinner"></span> 모델 목록 조회 중...</div>`;
      let meta;
      try {
        meta = await getProfileMeta(name);
      } catch (e) {
        host.innerHTML = `<div class="muted">${errMsg(e, "속성 조회 실패")}</div>`;
        return;
      }
      if (sel.value !== name) return;  // 조회 도중 선택이 바뀌면 무시
      pHint.textContent = meta.region ? `· region: ${meta.region}` : "· region 속성 없음";
      hint.textContent = meta.model ? `· 현재 모델: ${meta.model}` : "";
      const candidates = (MODELS && MODELS[meta.region]) || [];
      if (candidates.length === 0) {
        host.innerHTML = `<div class="muted">region '${window.escapeHtml(meta.region || "?")}' 의 모델 후보가 없습니다 (models.txt 확인)</div>`;
        return;
      }
      // 후보에 현재 model 이 없으면 맨 앞에 추가해 비교 대상에서 누락되지 않게
      const models = (meta.model && !candidates.includes(meta.model))
        ? [meta.model, ...candidates] : candidates.slice();
      host.innerHTML = models.map((m) => {
        const checked = m === meta.model ? "checked" : "";
        return `<label><input type="checkbox" value="${window.escapeAttr(m)}" ${checked}/> ${window.escapeHtml(m)}</label>`;
      }).join("");
    }

    renderProfileSelect();
    document.getElementById("bm-action").addEventListener("change", renderProfileSelect);
    document.getElementById("bm-profile").addEventListener("change", renderModelChecklist);

    // --- 프롬프트 저장/불러오기 (localStorage, 세션 간 유지) — 테스트 모달과 동일 라이브러리 공유 ---
    const BM_PROMPTS_KEY = "profileTest.savedPrompts";
    const bmPromptEl = document.getElementById("bm-prompt");
    const bmTitleInput = document.getElementById("bm-prompt-title");
    const bmAddBtn = document.getElementById("bm-prompt-add");
    const bmUpdateBtn = document.getElementById("bm-prompt-update");
    const bmSavedSel = document.getElementById("bm-prompt-saved");

    const bmLoadSaved = () => {
      try { return JSON.parse(window.Store.get(BM_PROMPTS_KEY)) || []; }
      catch (e) { return []; }
    };
    const bmRefreshCombo = (selectTitle) => {
      const list = bmLoadSaved();
      bmSavedSel.innerHTML = "";
      const ph = document.createElement("option");
      ph.value = "";
      ph.textContent = list.length ? "저장된 프롬프트…" : "(저장된 프롬프트 없음)";
      bmSavedSel.appendChild(ph);
      list.forEach((p) => {
        const o = document.createElement("option");
        o.value = p.title;
        o.textContent = p.title;
        bmSavedSel.appendChild(o);
      });
      if (selectTitle != null) bmSavedSel.value = selectTitle;
    };
    bmRefreshCombo();

    // 추가 — 제목칸의 새 title 로 현재 프롬프트를 신규 저장 (중복 title 은 거부)
    bmAddBtn.addEventListener("click", () => {
      const title = bmTitleInput.value.trim();
      const prompt = bmPromptEl.value;
      if (!title) { window.Toast.show("추가할 제목을 입력하세요", "error"); bmTitleInput.focus(); return; }
      if (!prompt.trim()) { window.Toast.show("프롬프트가 비어 있습니다", "error"); return; }
      const list = bmLoadSaved();
      if (list.some((p) => p.title === title)) {
        window.Toast.show("이미 있는 제목입니다. [저장]으로 수정하세요", "error");
        return;
      }
      list.push({ title, prompt });
      window.Store.set(BM_PROMPTS_KEY, JSON.stringify(list));
      bmRefreshCombo(title);
      bmTitleInput.value = "";
      window.Toast.show(`'${title}' 추가됨`, "success");
    });

    // 저장 — 콤보에서 선택한 기존 title 의 프롬프트를 현재 내용으로 수정
    bmUpdateBtn.addEventListener("click", () => {
      const title = bmSavedSel.value;
      if (!title) { window.Toast.show("수정할 항목을 콤보에서 선택하세요", "error"); return; }
      const prompt = bmPromptEl.value;
      if (!prompt.trim()) { window.Toast.show("프롬프트가 비어 있습니다", "error"); return; }
      const list = bmLoadSaved();
      const idx = list.findIndex((p) => p.title === title);
      if (idx < 0) { window.Toast.show("저장된 항목을 찾을 수 없습니다", "error"); return; }
      list[idx].prompt = prompt;
      window.Store.set(BM_PROMPTS_KEY, JSON.stringify(list));
      window.Toast.show(`'${title}' 수정됨`, "success");
    });

    bmSavedSel.addEventListener("change", () => {
      const title = bmSavedSel.value;
      if (!title) return;
      const found = bmLoadSaved().find((p) => p.title === title);
      if (found) bmPromptEl.value = found.prompt;
    });

    // 중단: 결과 테이블
    const resultPanel = document.createElement("div");
    resultPanel.className = "panel";
    resultPanel.innerHTML = `
      <div class="panel-header"><h2>측정 결과</h2></div>
      <div class="panel-body" id="bm-result"><div class="empty-state muted">[실행] 을 눌러 측정을 시작하세요.</div></div>
    `;
    wrap.appendChild(resultPanel);

    // 하단: 차트
    const chartPanel = document.createElement("div");
    chartPanel.className = "panel";
    chartPanel.innerHTML = `
      <div class="panel-header"><h2>비교 차트 (평균 응답시간 ms)</h2></div>
      <div class="panel-body" style="height:300px;">
        <canvas id="bm-chart"></canvas>
      </div>
    `;
    wrap.appendChild(chartPanel);

    document.getElementById("bm-run").addEventListener("click", async () => {
      const prompt = document.getElementById("bm-prompt").value;
      const action = document.getElementById("bm-action").value;
      const iterations = parseInt(document.getElementById("bm-iter").value, 10) || 1;
      const profile_name = document.getElementById("bm-profile").value;
      const models = Array.from(document.querySelectorAll("#bm-models input:checked")).map((c) => c.value);
      if (!profile_name) { window.Toast.show("Profile 을 선택하세요", "warn"); return; }
      if (models.length === 0) { window.Toast.show("LLM Model 을 1개 이상 선택하세요", "warn"); return; }

      // 실행할 때마다 프롬프트 끝에 '.' 을 누적해 동일 입력 캐싱으로 인한 속도 왜곡을 방지.
      // 카운터는 localStorage 에 저장 → 새로고침/재접속 후에도 계속 증가.
      const RUN_COUNT_KEY = "profileTest.runCount";
      const runCount = (parseInt(window.Store.get(RUN_COUNT_KEY) || "0", 10) || 0) + 1;
      window.Store.set(RUN_COUNT_KEY, String(runCount));
      const promptForRun = prompt + ".".repeat(runCount);

      const btn = document.getElementById("bm-run");
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner"></span> 실행 중...';
      const resultHost = document.getElementById("bm-result");

      // 모델을 1개씩 순차 측정 — 매 회차 어떤 모델을 측정 중인지 진행상황을 갱신
      const done = [];
      try {
        for (let i = 0; i < models.length; i++) {
          renderBenchmarkProgress(resultHost, profile_name, models, done, i);
          const data = await window.API.post("/api/profiles/benchmark",
            { prompt: promptForRun, action, profile_name, models: [models[i]], iterations });
          done.push((data.results && data.results[0]) ||
            { profile_name, model: models[i], runs: [], avg_ms: null, min_ms: null, max_ms: null });
        }
        const combined = { iterations, profile_name, results: done };
        renderBenchmarkResult(resultHost, combined);
        renderChart(combined);
      } catch (e) {
        const msg = errMsg(e, "측정 실패");
        if (done.length) {
          // 이미 끝난 모델 결과는 보존하고 오류만 안내
          const combined = { iterations, profile_name, results: done };
          renderBenchmarkResult(resultHost, combined);
          renderChart(combined);
          window.Toast.show(`${msg} (${done.length}/${models.length} 모델만 완료)`, "error");
        } else {
          resultHost.innerHTML = `<div class="empty-state muted">${msg}</div>`;
          window.Toast.show(msg, "error");
        }
      } finally {
        btn.disabled = false;
        btn.innerHTML = "▶ 실행";
      }
    });
  }

  // ====================================================================
  // --- Tab 3: Feedback 관리 (서버 연동) ---
  //   - GET  /api/profiles/{name}/feedback/vectab : <PROFILE>_FEEDBACK_VECINDEX$VECTAB (display only)
  //   - GET  /api/profiles/feedback/mapped-sql    : v$mapped_sql (NL2SQL 실행 내역 + sql_id)
  //   - POST /api/profiles/{name}/feedback        : DBMS_CLOUD_AI.FEEDBACK 실행
  // ====================================================================

  // 현재 선택된 Profile 명 — 셀 안의 버튼들이 클릭 시점에 읽는다.
  function fbProfile() {
    const sel = document.getElementById("fb-profile");
    return sel ? sel.value : "";
  }

  // <PROFILE_NAME>_FEEDBACK_VECINDEX$VECTAB — feedback 사용 시 자동 생성되는 Vector Table 명
  function vectorTableName(profile) {
    return profile ? `${profile}_FEEDBACK_VECINDEX$VECTAB` : "<PROFILE_NAME>_FEEDBACK_VECINDEX$VECTAB";
  }

  // PL/SQL 문자열 리터럴용 single-quote 이스케이프
  function fbSqlLit(s) {
    return String(s == null ? "" : s).replace(/'/g, "''");
  }

  // sql_id 기반 — 기존 실행된 SQL 에 피드백 추가(=update). 미리보기/복사용 스크립트.
  function buildFeedbackAddByIdSql(profile, sqlId, feedbackType) {
    return `BEGIN
    DBMS_CLOUD_AI.FEEDBACK(
        profile_name  => '${fbSqlLit(profile)}',
        sql_id        => '${fbSqlLit(sqlId)}',
        feedback_type => '${fbSqlLit(feedbackType)}',
        operation     => 'add'  -- add(update) / delete
    );
END;
/`;
  }

  // sql_id 기반 — 저장된 피드백 삭제(operation=delete). 미리보기/복사용 스크립트.
  function buildFeedbackDeleteByIdSql(profile, sqlId, feedbackType) {
    return `BEGIN
    DBMS_CLOUD_AI.FEEDBACK(
        profile_name  => '${fbSqlLit(profile)}',
        sql_id        => '${fbSqlLit(sqlId)}',
        feedback_type => '${fbSqlLit(feedbackType)}',
        operation     => 'delete'
    );
END;
/`;
  }

  // sql_text 기반 — 저장된 피드백 삭제(operation=delete). sql_id 가 없는 행 삭제에 사용. 미리보기/복사용 스크립트.
  function buildFeedbackDeleteByTextSql(profile, sqlText, feedbackType, response) {
    return `BEGIN
    DBMS_CLOUD_AI.FEEDBACK(
        profile_name  => '${fbSqlLit(profile)}',
        sql_text      => '${fbSqlLit(sqlText)}',
        feedback_type => '${fbSqlLit(feedbackType)}',
        response      => '${fbSqlLit(response)}',
        operation     => 'delete'
    );
END;
/`;
  }

  // sql_text 기반 — 사전 실행 없이 프롬프트 + 기대 응답(SQL)으로 피드백 등록. 미리보기/복사용 스크립트.
  //   feedbackContent 는 선택 — 값이 있을 때만 feedback_content 줄을 추가한다.
  function buildFeedbackByTextSql(profile, sqlText, feedbackType, response, feedbackContent) {
    const fcLine = feedbackContent
      ? `,\n        feedback_content => '${fbSqlLit(feedbackContent)}'`
      : "";
    return `BEGIN
    DBMS_CLOUD_AI.FEEDBACK(
        profile_name  => '${fbSqlLit(profile)}',
        sql_text      => '${fbSqlLit(sqlText)}',
        feedback_type => '${fbSqlLit(feedbackType)}',
        response      => '${fbSqlLit(response)}'${fcLine}
    );
END;
/`;
  }

  // FEEDBACK 스크립트 확인 팝업 — 스크립트를 보여주고 [반영] 클릭 시 onApply() 실행.
  // onApply 가 throw 하면 모달을 유지해 사용자가 오류를 보고 재시도할 수 있게 한다.
  function showFeedbackConfirmModal(title, sql, onApply) {
    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    backdrop.innerHTML = `
      <div class="modal" style="width:760px;">
        <div class="modal-header">
          <h2>${window.escapeHtml(title)}</h2>
          <button class="btn btn-ghost" id="fbm-close">✕</button>
        </div>
        <div class="modal-body stack">
          <label class="muted" style="font-size:var(--fs-sm);">아래 스크립트를 실행합니다.</label>
          <pre id="fbm-pre" style="white-space:pre; margin:0; font-family:var(--font-mono); font-size:var(--fs-sm); background:var(--surface-alt); padding:var(--space-3); border-radius:var(--radius-md); overflow:auto;"></pre>
          <div class="row end" style="gap:8px;">
            <button class="btn btn-ghost" id="fbm-copy">복사</button>
            <button class="btn btn-primary" id="fbm-apply">반영</button>
          </div>
        </div>
      </div>
    `;
    backdrop.querySelector("#fbm-pre").textContent = sql;
    const close = () => { backdrop.remove(); document.removeEventListener("keydown", onKey); };
    const onKey = (e) => { if (e.key === "Escape") close(); };
    backdrop.addEventListener("click", (e) => { if (e.target === backdrop) close(); });
    backdrop.querySelector("#fbm-close").addEventListener("click", close);
    backdrop.querySelector("#fbm-copy").addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(sql); window.Toast.show("클립보드에 복사됨", "success"); }
      catch (_) { window.Toast.show("복사 실패", "error"); }
    });
    const applyBtn = backdrop.querySelector("#fbm-apply");
    applyBtn.addEventListener("click", async () => {
      applyBtn.disabled = true;
      const prev = applyBtn.innerHTML;
      applyBtn.innerHTML = '<span class="spinner"></span> 반영 중...';
      try {
        await onApply();
        close();
      } catch (e) {
        // onApply 내부에서 토스트 처리 — 모달은 유지하고 버튼만 복구
        applyBtn.disabled = false;
        applyBtn.innerHTML = prev;
      }
    });
    document.addEventListener("keydown", onKey);
    document.body.appendChild(backdrop);
  }

  function renderTab3(host, profiles) {
    host.innerHTML = "";
    const wrap = document.createElement("div");
    wrap.className = "split-vert";
    host.appendChild(wrap);

    // 사용 가능한 Profile (ENABLED 우선, 없으면 전체)
    const enabled = profiles.filter((p) => p.status === "ENABLED");
    const pool = enabled.length ? enabled : profiles;
    const profileOptions = pool.map((p) =>
      `<option value="${window.escapeAttr(p.profile_name)}">${window.escapeHtml(p.profile_name)}</option>`).join("");

    // ---- 상단: Profile 선택 + Vector Table ----
    const topPanel = document.createElement("div");
    topPanel.className = "panel";
    topPanel.innerHTML = `
      <div class="panel-header"><h2>피드백 대상 Profile</h2></div>
      <div class="panel-body stack-sm">
        <div class="row" style="gap:12px; align-items:center;">
          <label style="width:90px;">Profile</label>
          <select id="fb-profile" style="min-width:260px;">${profileOptions}</select>
        </div>
        <div class="row" style="gap:12px; align-items:center;">
          <label style="width:90px;">Vector Table</label>
          <input id="fb-vectab" readonly style="min-width:380px; font-family:var(--font-mono); font-size:var(--fs-sm);">
        </div>
        <div class="muted" style="font-size:var(--fs-sm);">
          · 같은 <b>sql_id</b> 에 대한 피드백은 <b>1건만 유지</b>됩니다 (<code>operation =&gt; 'add'</code> 가 곧 update).
        </div>
      </div>
    `;
    wrap.appendChild(topPanel);

    // ---- Vector Table 내용 (저장된 Feedback, display only) ----
    const vectabPanel = document.createElement("div");
    vectabPanel.className = "panel";
    vectabPanel.innerHTML = `
      <div class="panel-header">
        <h2>Vector Table 내용 <span class="muted" style="font-size:var(--fs-sm);">저장된 Feedback (display only)</span></h2>
        <button class="btn btn-ghost" id="fb-vectab-reload">↻ 조회</button>
      </div>
      <div class="panel-body" id="fb-vectab-list"></div>
    `;
    wrap.appendChild(vectabPanel);

    // ---- Feedback 추가 ① 실행된 내역에서 (v$mapped_sql) ----
    const histPanel = document.createElement("div");
    histPanel.className = "panel";
    histPanel.innerHTML = `
      <div class="panel-header">
        <h2>Feedback 추가 — 실행된 내역에서 <span class="muted" style="font-size:var(--fs-sm);">v$mapped_sql</span></h2>
        <button class="btn btn-ghost" id="fb-hist-reload">↻ 내역 조회</button>
      </div>
      <div class="panel-body" id="fb-hist"></div>
    `;
    wrap.appendChild(histPanel);

    // ---- Feedback 추가 ② 실행내역 없이 (sql_text + response) ----
    const directPanel = document.createElement("div");
    directPanel.className = "panel";
    directPanel.innerHTML = `
      <div class="panel-header">
        <h2>Feedback 추가 — 실행내역 없이 <span class="muted" style="font-size:var(--fs-sm);">sql_text + response + feedback_content</span></h2>
        <button class="btn btn-primary" id="fb-gen-direct">추가</button>
      </div>
      <div class="panel-body stack-sm">
        <div class="stack-sm">
          <label>SQL Text <span class="muted" style="font-size:var(--fs-sm);">— 자연어 프롬프트 또는 SELECT AI 구문</span></label>
          <textarea id="fb-sql-text" rows="2">select ai showsql how many movies</textarea>
        </div>
        <div class="row" style="gap:12px; align-items:center;">
          <label style="width:90px;">Feedback</label>
          <input type="hidden" id="fb-direct-type" value="negative">
          <span>negative</span>
          <span class="muted" style="font-size:var(--fs-sm);">— 고정</span>
        </div>
        <div class="stack-sm">
          <label>Response <span class="muted" style="font-size:var(--fs-sm);">— 기대하는(교정된) SQL. negative 일 때 권장</span></label>
          <textarea id="fb-response" rows="3" style="font-family:var(--font-mono); font-size:var(--fs-sm);">SELECT SUM(1) FROM "ADB_USER"."MOVIES"</textarea>
        </div>
        <div class="stack-sm">
          <label>Feedback Content <span class="muted" style="font-size:var(--fs-sm);">— 자연어 피드백(선택). 입력 시 feedback_content 로 전달</span></label>
          <textarea id="fb-feedback-content" rows="2"></textarea>
        </div>
      </div>
    `;
    wrap.appendChild(directPanel);

    const vectabInput = document.getElementById("fb-vectab");

    // --- Vector Table 내용 조회 (display only) ---
    async function loadVectab() {
      const profile = fbProfile();
      const listHost = document.getElementById("fb-vectab-list");
      if (!profile) {
        listHost.innerHTML = '<div class="empty-state muted">Profile 을 선택하세요.</div>';
        return;
      }
      listHost.innerHTML = '<div class="empty-state"><span class="spinner"></span> 조회 중...</div>';
      let data;
      try {
        data = await window.API.get(`/api/profiles/${encodeURIComponent(profile)}/feedback/vectab`);
      } catch (e) {
        listHost.innerHTML = `<div class="empty-state muted">${errMsg(e, "Vector Table 조회 실패")}</div>`;
        return;
      }
      if (fbProfile() !== profile) return;  // 그 사이 Profile 변경 시 무시
      if (!data.exists) {
        listHost.innerHTML = '<div class="empty-state muted">vector table 없음</div>';
        return;
      }
      const cols = (data.columns || []).map((c) => ({ key: c, label: c }));
      listHost.innerHTML = "";
      if (!cols.length) {
        listHost.innerHTML = '<div class="empty-state muted">컬럼 정보가 없습니다.</div>';
        return;
      }
      // 행 끝에 액션(수정/삭제) 버튼 컬럼 추가.
      cols.push({ key: "_act", label: "", headerAlign: "center",
        format: (_v, row) => buildVectabActions(row, loadVectab) });
      listHost.appendChild(window.SimpleTable.create(cols, data.rows || [], { className: "keep-case" }));
      if (!(data.rows || []).length) {
        listHost.appendChild(divFromHtml('<div class="empty-state muted">저장된 Feedback 이 없습니다.</div>'));
      }
    }

    // --- v$mapped_sql 실행 내역 조회 ---
    async function loadMappedSql() {
      const histHost = document.getElementById("fb-hist");
      histHost.innerHTML = '<div class="empty-state"><span class="spinner"></span> 조회 중...</div>';
      let rows;
      try {
        rows = await window.API.get("/api/profiles/feedback/mapped-sql");
      } catch (e) {
        histHost.innerHTML = `<div class="empty-state muted">${errMsg(e, "v$mapped_sql 조회 실패")}</div>`;
        return;
      }
      histHost.innerHTML = "";
      histHost.appendChild(window.SimpleTable.create(
        [
          { key: "sql_fulltext", label: "Sql_fulltext" },
          { key: "sql_id", label: "sql_id" },
          { key: "mapped_sql_text", label: "Mapped_sql_text" },
          { key: "translation_timestamp", label: "timestamp", headerAlign: "center" },
          { key: "_add", label: "", headerAlign: "center",
            format: (_v, row) => buildMappedAddBtn(row, loadVectab) },
        ],
        rows || [],
        { className: "keep-case" }
      ));
      if (!(rows || []).length) {
        histHost.appendChild(divFromHtml('<div class="empty-state muted">실행 내역이 없습니다 (v$mapped_sql 비어 있음).</div>'));
      }
    }

    // v$mapped_sql 행의 "추가" 버튼 — 스크립트 팝업을 띄우고 [반영] 클릭 시 실제 FEEDBACK 실행.
    function buildMappedAddBtn(row, onDone) {
      const btn = document.createElement("button");
      btn.className = "btn btn-primary";
      btn.textContent = "추가";
      btn.title = "feedback_type=positive, operation=add (같은 sql_id 는 1건만 유지되어 update 됨)";
      btn.addEventListener("click", () => {
        const profile = fbProfile();
        if (!profile) { window.Toast.show("Profile 을 선택하세요", "warn"); return; }
        if (!row.sql_id) { window.Toast.show("sql_id 가 없습니다", "warn"); return; }
        const sql = buildFeedbackAddByIdSql(profile, row.sql_id, "positive");
        showFeedbackConfirmModal(`FEEDBACK (add) — ${row.sql_id}`, sql, async () => {
          try {
            await window.API.post(`/api/profiles/${encodeURIComponent(profile)}/feedback`,
              { sql_id: row.sql_id, feedback_type: "positive", operation: "add" });
            window.Toast.show(`피드백 추가됨 (${row.sql_id})`, "success");
            if (typeof onDone === "function") onDone();
          } catch (e) {
            window.Toast.show(errMsg(e, "피드백 추가 실패"), "error");
            throw e;  // 모달 유지 (사용자가 오류 확인 후 재시도)
          }
        });
      });
      return btn;
    }

    // vectab 행의 액션 셀 — [수정](response 편집) + [삭제] 버튼을 한 칸에 배치.
    function buildVectabActions(row, onDone) {
      const sqlId = (row.sql_id || "").trim();
      const sqlText = (row.sql_text || "").trim();
      if (!sqlId && !sqlText) return divFromHtml('<span class="muted">—</span>');

      const box = document.createElement("div");
      box.className = "row";
      box.style.gap = "6px";
      box.style.justifyContent = "center";

      // 수정 — response 만 바꿔 재등록(operation=add). response 전달은 sql_text 모드만 가능하므로
      //        sql_text 가 있는 행에만 노출한다. 단 positive 는 response 가 시스템 파생값이고
      //        positive+response 조합을 Oracle 이 거부하므로 negative 행에만 노출한다.
      if (sqlText && (row.feedback_type || "").trim().toLowerCase() === "negative") {
        const editBtn = document.createElement("button");
        editBtn.className = "btn btn-ghost";
        editBtn.textContent = "수정";
        editBtn.title = "response 를 수정해 다시 저장 (operation=add)";
        editBtn.addEventListener("click", () => showVectabEditModal(row, onDone));
        box.appendChild(editBtn);
      }

      box.appendChild(buildVectabDeleteBtn(row, onDone));
      return box;
    }

    // vectab 행의 "수정" 팝업 — content/feedback_type/sql_id/sql_text 는 읽기전용으로 보여주고
    //   response 만 편집한다. [저장] 시 sql_text 모드로 FEEDBACK(operation=add) 재등록(같은 항목은
    //   1건만 유지되어 response 가 갱신됨).
    function showVectabEditModal(row, onDone) {
      const profile = fbProfile();
      if (!profile) { window.Toast.show("Profile 을 선택하세요", "warn"); return; }

      const sqlText = (row.sql_text || "").trim();
      const ft = row.feedback_type || "positive";

      // 읽기전용 필드 한 칸을 만드는 헬퍼.
      const roField = (label, value) => `
        <div class="stack-sm">
          <label style="font-size:var(--fs-sm); color:var(--text-muted);">${label}</label>
          <pre style="white-space:pre-wrap; word-break:break-word; margin:0; font-family:var(--font-mono); font-size:var(--fs-sm); background:var(--surface-alt); padding:var(--space-2) var(--space-3); border-radius:var(--radius-md); max-height:120px; overflow:auto;">${window.escapeHtml(value || "—")}</pre>
        </div>`;

      const backdrop = document.createElement("div");
      backdrop.className = "modal-backdrop";
      backdrop.innerHTML = `
        <div class="modal" style="width:760px;">
          <div class="modal-header">
            <h2>Feedback 수정 — response</h2>
            <button class="btn btn-ghost" id="fbe-close">✕</button>
          </div>
          <div class="modal-body stack">
            ${roField("content", row.content)}
            <div class="row" style="gap:12px;">
              <div style="flex:1; min-width:0;">${roField("feedback_type", row.feedback_type)}</div>
              <div style="flex:1; min-width:0;">${roField("sql_id", row.sql_id)}</div>
            </div>
            ${roField("sql_text", row.sql_text)}
            <div class="stack-sm">
              <label>response <span class="muted" style="font-size:var(--fs-sm);">— 수정 가능</span></label>
              <textarea id="fbe-response" rows="6" class="textarea-auto" style="font-family:var(--font-mono); font-size:var(--fs-sm);"></textarea>
            </div>
            <div class="stack-sm">
              <label>feedback_content <span class="muted" style="font-size:var(--fs-sm);">— 자연어 피드백(선택). 수정 가능</span></label>
              <textarea id="fbe-feedback-content" rows="2" class="textarea-auto"></textarea>
            </div>
            <div class="row end" style="gap:8px;">
              <button class="btn btn-ghost" id="fbe-cancel">닫기</button>
              <button class="btn btn-primary" id="fbe-save">저장</button>
            </div>
          </div>
        </div>
      `;
      const respEl = backdrop.querySelector("#fbe-response");
      respEl.value = row.response || "";
      const fcEl = backdrop.querySelector("#fbe-feedback-content");
      fcEl.value = row.feedback_content || "";

      const close = () => { backdrop.remove(); document.removeEventListener("keydown", onKey); };
      const onKey = (e) => { if (e.key === "Escape") close(); };
      backdrop.addEventListener("click", (e) => { if (e.target === backdrop) close(); });
      backdrop.querySelector("#fbe-close").addEventListener("click", close);
      backdrop.querySelector("#fbe-cancel").addEventListener("click", close);

      const saveBtn = backdrop.querySelector("#fbe-save");
      saveBtn.addEventListener("click", async () => {
        const response = respEl.value.trim();
        if (!response) { window.Toast.show("response 가 비어 있습니다", "warn"); return; }
        const feedbackContent = fcEl.value.trim();
        saveBtn.disabled = true;
        const prev = saveBtn.innerHTML;
        saveBtn.innerHTML = '<span class="spinner"></span> 저장 중...';
        try {
          await window.API.post(`/api/profiles/${encodeURIComponent(profile)}/feedback`,
            { sql_text: sqlText, feedback_type: ft, response, feedback_content: feedbackContent, operation: "add" });
          window.Toast.show("response 수정됨", "success");
          close();
          if (typeof onDone === "function") onDone();
        } catch (e) {
          // 실패 시 모달 유지 + 버튼 복구 (사용자가 오류 확인 후 재시도)
          window.Toast.show(errMsg(e, "수정 실패"), "error");
          saveBtn.disabled = false;
          saveBtn.innerHTML = prev;
        }
      });

      document.addEventListener("keydown", onKey);
      document.body.appendChild(backdrop);
    }

    // vectab 행의 "삭제" 버튼 — 스크립트 팝업을 띄우고 [반영] 클릭 시 FEEDBACK(operation=delete) 실행.
    //   - sql_id 가 있으면 sql_id 기반 삭제
    //   - sql_id 가 없으면 sql_text + feedback_type + response 기반 삭제
    function buildVectabDeleteBtn(row, onDone) {
      const sqlId = (row.sql_id || "").trim();
      const sqlText = (row.sql_text || "").trim();
      if (!sqlId && !sqlText) return divFromHtml('<span class="muted">—</span>');

      const btn = document.createElement("button");
      btn.className = "btn btn-primary";
      btn.textContent = "삭제";
      btn.title = "operation=delete (이 행의 저장된 피드백을 삭제)";
      btn.addEventListener("click", () => {
        const profile = fbProfile();
        if (!profile) { window.Toast.show("Profile 을 선택하세요", "warn"); return; }

        let sql, payload, label;
        if (sqlId) {
          sql = buildFeedbackDeleteByIdSql(profile, sqlId, row.feedback_type || "positive");
          payload = { sql_id: sqlId, operation: "delete" };
          label = sqlId;
        } else {
          const ft = row.feedback_type || "negative";
          sql = buildFeedbackDeleteByTextSql(profile, sqlText, ft, row.response || "");
          payload = { sql_text: sqlText, feedback_type: ft, response: row.response || "", operation: "delete" };
          label = sqlText;
        }

        showFeedbackConfirmModal(`FEEDBACK (delete) — ${label}`, sql, async () => {
          try {
            await window.API.post(`/api/profiles/${encodeURIComponent(profile)}/feedback`, payload);
            window.Toast.show("피드백 삭제됨", "success");
            if (typeof onDone === "function") onDone();
          } catch (e) {
            window.Toast.show(errMsg(e, "피드백 삭제 실패"), "error");
            throw e;  // 모달 유지 (사용자가 오류 확인 후 재시도)
          }
        });
      });
      return btn;
    }

    // Profile 변경 → Vector Table 명 갱신 + 내용 재조회
    document.getElementById("fb-profile").addEventListener("change", () => {
      vectabInput.value = vectorTableName(fbProfile());
      loadVectab();
    });

    document.getElementById("fb-vectab-reload").addEventListener("click", loadVectab);
    document.getElementById("fb-hist-reload").addEventListener("click", loadMappedSql);

    // 직접 입력 → 스크립트 팝업을 띄우고 [반영] 클릭 시 FEEDBACK(sql_text) 실제 실행
    document.getElementById("fb-gen-direct").addEventListener("click", () => {
      const profile = fbProfile();
      if (!profile) { window.Toast.show("Profile 을 선택하세요", "warn"); return; }
      const sqlText = document.getElementById("fb-sql-text").value.trim();
      if (!sqlText) { window.Toast.show("SQL Text 를 입력하세요", "warn"); return; }
      const type = document.getElementById("fb-direct-type").value;
      const response = document.getElementById("fb-response").value;
      const feedbackContent = document.getElementById("fb-feedback-content").value.trim();
      const sql = buildFeedbackByTextSql(profile, sqlText, type, response, feedbackContent);
      showFeedbackConfirmModal(`FEEDBACK (sql_text) — ${profile}`, sql, async () => {
        try {
          await window.API.post(`/api/profiles/${encodeURIComponent(profile)}/feedback`,
            { sql_text: sqlText, feedback_type: type, response, feedback_content: feedbackContent });
          window.Toast.show("피드백 등록됨", "success");
          loadVectab();
        } catch (e) {
          window.Toast.show(errMsg(e, "피드백 등록 실패"), "error");
          throw e;  // 모달 유지 (사용자가 오류 확인 후 재시도)
        }
      });
    });

    // 진입 시 초기화 — Vector Table 명/내용 + 실행 내역 조회
    vectabInput.value = vectorTableName(fbProfile());
    loadVectab();
    loadMappedSql();
  }

  // 간단 HTML → element (Tab3 보조)
  function divFromHtml(html) { const d = document.createElement("div"); d.innerHTML = html; return d.firstElementChild || d; }

  // 모델별 순차 측정 진행상황 — 완료(✓)/측정중(스피너)/대기(·) 상태를 목록으로 표시
  function renderBenchmarkProgress(host, profileName, models, done, currentIndex) {
    const rows = models.map((m, i) => {
      let icon, nameMuted = false, extra;
      if (i < currentIndex) {
        const r = done[i];
        icon = "✓";
        extra = r && r.avg_ms != null
          ? `평균 ${Number(r.avg_ms).toLocaleString()} ms`
          : "오류";
      } else if (i === currentIndex) {
        icon = '<span class="spinner"></span>';
        extra = "측정 중...";
      } else {
        icon = "·"; nameMuted = true; extra = "대기";
      }
      return `<div class="row" style="gap:8px; padding:4px 0; align-items:center;">
        <span style="width:18px; text-align:center;">${icon}</span>
        <span style="font-family:var(--font-mono); ${nameMuted ? "color:var(--text-muted);" : ""}">${window.escapeHtml(m)}</span>
        <span class="muted" style="font-size:var(--fs-sm);">· ${extra}</span>
      </div>`;
    }).join("");
    host.innerHTML = `
      <div class="stack-sm">
        <div class="muted">Profile <b>${window.escapeHtml(profileName)}</b> · 모델 ${Math.min(currentIndex + 1, models.length)}/${models.length} 측정 중</div>
        ${rows}
      </div>`;
  }

  function renderBenchmarkResult(host, data) {
    host.innerHTML = "";
    const iters = data.iterations || (data.results[0]?.runs.length ?? 1);
    const fmtNum = (v) => (v == null || v === "") ? v : Number(v).toLocaleString();
    const columns = [
      { key: (r) => r.model || r.profile_name, label: "Model",
        format: (v, row) => {
          const span = document.createElement("span");
          span.textContent = v;
          span.style.cursor = "pointer";
          span.style.textDecoration = "underline dotted";
          span.title = "클릭하면 호출별 응답 보기";
          span.addEventListener("click", (e) => {
            e.stopPropagation();
            showModelRunsModal(row);
          });
          return span;
        }},
    ];
    for (let i = 1; i <= iters; i++) {
      columns.push({
        key: (r) => r.runs[i - 1],
        label: `#${i} (ms)`,
        className: "metric",
        headerAlign: "center",
        format: (cell) => {
          if (!cell) return "—";
          if (cell.error) {
            const td = document.createElement("span");
            td.className = "error";
            td.textContent = cell.error;
            return td;
          }
          const span = document.createElement("span");
          span.style.cursor = "pointer";
          span.style.textDecoration = "underline dotted";
          span.textContent = fmtNum(cell.elapsed_ms);
          span.addEventListener("click", (e) => {
            e.stopPropagation();
            showResponseModal(cell.response);
          });
          return span;
        },
      });
    }
    columns.push(
      { key: "avg_ms", label: "평균", className: "metric", headerAlign: "center", format: fmtNum },
      { key: "min_ms", label: "최소", className: "metric", headerAlign: "center", format: fmtNum },
      { key: "max_ms", label: "최대", className: "metric", headerAlign: "center", format: fmtNum },
    );
    host.appendChild(window.SimpleTable.create(columns, data.results, { className: "table-grid" }));
  }

  // 모델 셀 클릭 → 그 모델의 회차별 응답을 한 모달에 모아서 표시
  function showModelRunsModal(row) {
    const title = String(row.model || row.profile_name || "");
    const runs = row.runs || [];
    const itemsHtml = runs.map((run) => {
      const ms = run.elapsed_ms != null ? Number(run.elapsed_ms).toLocaleString() : "—";
      const isErr = !!run.error;
      const body = window.escapeHtml(isErr ? run.error : (run.response || ""));
      return `
        <div class="stack-sm" style="margin-bottom: var(--space-4);">
          <div class="row" style="justify-content: space-between; align-items:center;">
            <label>#${run.iteration}${isErr ? ' <span class="error">오류</span>' : ''}</label>
            <span class="muted" style="font-size:var(--fs-sm);">${ms} ms</span>
          </div>
          <pre class="${isErr ? "error" : ""}" style="white-space:pre-wrap; margin:0; font-family:var(--font); background:var(--surface-alt); padding:var(--space-3); border-radius:var(--radius-md);">${body}</pre>
        </div>`;
    }).join("");
    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    backdrop.innerHTML = `
      <div class="modal" style="width:760px;">
        <div class="modal-header">
          <h2>호출별 응답 — ${window.escapeHtml(title)}</h2>
          <button class="btn btn-ghost" id="mr-close">✕</button>
        </div>
        <div class="modal-body">
          ${runs.length ? itemsHtml : '<div class="empty-state muted">응답이 없습니다.</div>'}
        </div>
      </div>
    `;
    const close = () => { backdrop.remove(); document.removeEventListener("keydown", onKey); };
    const onKey = (e) => { if (e.key === "Escape") close(); };
    backdrop.addEventListener("click", (e) => { if (e.target === backdrop) close(); });
    backdrop.querySelector("#mr-close").addEventListener("click", close);
    document.addEventListener("keydown", onKey);
    document.body.appendChild(backdrop);
  }

  function showResponseModal(text) {
    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    backdrop.innerHTML = `
      <div class="modal">
        <div class="modal-header">
          <h2>LLM 응답</h2>
          <button class="btn btn-ghost" id="modal-close">✕</button>
        </div>
        <div class="modal-body">
          <pre style="white-space:pre-wrap; margin:0; font-family:var(--font);">${window.escapeHtml(text)}</pre>
        </div>
      </div>
    `;
    backdrop.addEventListener("click", (e) => { if (e.target === backdrop) backdrop.remove(); });
    backdrop.querySelector("#modal-close").addEventListener("click", () => backdrop.remove());
    document.body.appendChild(backdrop);
  }

  function renderChart(data) {
    const ctx = document.getElementById("bm-chart");
    if (!ctx) return;
    if (chartInstance) { chartInstance.destroy(); chartInstance = null; }
    chartInstance = new Chart(ctx, {
      type: "bar",
      data: {
        labels: data.results.map((r) => r.model || r.profile_name),
        datasets: [{
          label: "평균 응답시간 (ms)",
          data: data.results.map((r) => r.avg_ms || 0),
          backgroundColor: "#C74634",
          borderRadius: 4,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          y: { beginAtZero: true, ticks: { font: { family: "Inter" } } },
          x: { ticks: { font: { family: "Inter" } } },
        },
      },
    });
  }

  function div(html) { const d = document.createElement("div"); d.innerHTML = html; return d; }

  // 드롭다운 공통 스타일
  function styleSelect(sel) {
    sel.style.flex = "1";
    sel.style.fontFamily = "var(--font-mono)";
    sel.style.fontSize = "var(--fs-sm)";
    sel.style.minHeight = "32px";
    return sel;
  }

  // <select> 옵션을 options 로 채우고, 현재 값이 없으면 맨 앞에 추가해 유실 방지.
  function fillSelectOptions(sel, options, currentValue) {
    const cur = currentValue == null ? "" : String(currentValue);
    const opts = options.slice();
    if (cur && !opts.includes(cur)) opts.unshift(cur);
    sel.innerHTML = "";
    opts.forEach((v) => {
      const o = document.createElement("option");
      o.value = v;
      o.textContent = v;
      sel.appendChild(o);
    });
    sel.value = cur;
  }

  // region 속성 전용 입력 — project/regions.txt 후보를 드롭다운으로.
  // 변경 시 같은 테이블의 model 드롭다운 옵션을 region 에 맞게 갱신한다.
  function buildRegionSelect(currentValue, ctx) {
    const sel = styleSelect(document.createElement("select"));
    fillSelectOptions(sel, REGIONS, currentValue);
    sel.addEventListener("change", () => {
      if (ctx) {
        ctx.regionValue = sel.value;
        if (typeof ctx.syncModelOptions === "function") ctx.syncModelOptions();
      }
    });
    return sel;
  }

  // model 속성 전용 입력 — 현재 선택된 region(ctx.regionValue) 의 후보를 드롭다운으로.
  function buildModelSelect(currentValue, ctx) {
    const sel = styleSelect(document.createElement("select"));
    const apply = () => {
      const region = (ctx && ctx.regionValue) || "";
      const list = (MODELS && MODELS[region]) || [];
      // region 변경 시에는 select 의 현재 값을, 최초 렌더 시에는 속성 값을 보존
      const keep = sel.options.length ? sel.value : currentValue;
      fillSelectOptions(sel, list, keep);
    };
    apply();
    if (ctx) {
      ctx.modelSelect = sel;
      ctx.syncModelOptions = apply;
    }
    return sel;
  }

  // Profile 속성 편집 테이블 — region/model 드롭다운 연동 포함. 메뉴 [2] 패널과 상세 팝업이 공유.
  function buildProfileAttrTable(profileName, attrs) {
    // region <-> model 셀 연동용 컨텍스트 (속성 테이블 1개당 1개)
    const regionAttr = attrs.find((a) => a.attribute_name === "region");
    const attrCtx = {
      regionValue: regionAttr ? String(regionAttr.attribute_value ?? "") : "",
      modelSelect: null,        // model 드롭다운 element (있으면 region 변경 시 갱신)
      syncModelOptions: null,   // model 드롭다운 옵션 재계산 함수
    };
    return window.SimpleTable.create(
      [
        { key: "attribute_name", label: "Attribute" },
        {
          key: "attribute_value",
          label: "Value",
          format: (_v, attr) => buildEditableValueCell(profileName, attr, attrCtx),
        },
      ],
      attrs
    );
  }

  // Profile 상세 팝업 — 메뉴 [2] 의 속성 패널을 모달로 그대로 재현 (다른 화면에서 호출용).
  async function openProfileDetailModal(profileName) {
    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    backdrop.innerHTML = `
      <div class="modal" style="width:820px;">
        <div class="modal-header">
          <h2>속성 - ${window.escapeHtml(profileName)}</h2>
          <div class="row">
            <button class="btn btn-primary" id="pd-gen-sql" disabled>AI Profile 구문 생성</button>
            <button class="btn btn-ghost" id="pd-close">✕</button>
          </div>
        </div>
        <div class="modal-body" id="pd-body">
          <div class="empty-state"><span class="spinner"></span> 조회 중...</div>
        </div>
      </div>
    `;
    const close = () => { backdrop.remove(); document.removeEventListener("keydown", onKey); };
    const onKey = (e) => { if (e.key === "Escape") close(); };
    backdrop.addEventListener("click", (e) => { if (e.target === backdrop) close(); });
    backdrop.querySelector("#pd-close").addEventListener("click", close);
    document.addEventListener("keydown", onKey);
    document.body.appendChild(backdrop);

    await ensureMeta(false);  // 다른 화면에서 열렸으면 region/model 후보가 비어 있을 수 있음
    const body = backdrop.querySelector("#pd-body");
    let attrs = [];
    try {
      attrs = await window.API.get(`/api/profiles/${encodeURIComponent(profileName)}/attributes`);
    } catch (e) {
      if (backdrop.isConnected) body.innerHTML = `<div class="empty-state muted">${errMsg(e, "속성 조회 실패")}</div>`;
      return;
    }
    if (!backdrop.isConnected) return;
    body.innerHTML = "";
    body.appendChild(buildProfileAttrTable(profileName, attrs));

    const genBtn = backdrop.querySelector("#pd-gen-sql");
    genBtn.disabled = false;
    genBtn.addEventListener("click", () => {
      showSqlModal(`CREATE PROFILE — ${profileName}`, buildCreateProfileSql(profileName, attrs));
    });
  }

  // 속성 Value 셀 — 입력(region/model=드롭다운, 그 외=textarea) + [적용] 버튼.
  // 클릭 시 DBMS_CLOUD_AI.SET_ATTRIBUTE 호출.
  function buildEditableValueCell(profileName, attr, ctx) {
    const wrap = document.createElement("div");
    wrap.className = "row";
    wrap.style.gap = "6px";
    wrap.style.alignItems = "flex-start";

    const isRegion = attr.attribute_name === "region" && REGIONS.length > 0;
    const isModel = attr.attribute_name === "model" && MODELS && Object.keys(MODELS).length > 0;
    let input;
    if (isRegion) {
      input = buildRegionSelect(attr.attribute_value, ctx);
    } else if (isModel) {
      input = buildModelSelect(attr.attribute_value, ctx);
    } else {
      input = document.createElement("textarea");
      input.rows = 1;
      input.value = attr.attribute_value == null ? "" : String(attr.attribute_value);
      input.style.flex = "1";
      input.style.fontFamily = "var(--font-mono)";
      input.style.fontSize = "var(--fs-sm)";
      input.style.resize = "vertical";
      input.style.minHeight = "32px";
    }

    const btn = document.createElement("button");
    btn.className = "btn btn-ghost";
    btn.textContent = "적용";
    btn.style.flexShrink = "0";

    btn.addEventListener("click", async () => {
      const newVal = input.value;
      btn.disabled = true;
      const prev = btn.innerHTML;
      btn.innerHTML = '<span class="spinner"></span>';
      try {
        await window.API.put(
          `/api/profiles/${encodeURIComponent(profileName)}/attributes/${encodeURIComponent(attr.attribute_name)}`,
          { value: newVal }
        );
        attr.attribute_value = newVal;  // currentAttrs 와 동일 참조라 SQL 생성에도 반영
        window.Toast.show(`${attr.attribute_name} 적용됨`, "success");
      } catch (e) {
        window.Toast.show(errMsg(e, "적용 실패"), "error");
      } finally {
        btn.disabled = false;
        btn.innerHTML = prev;
      }
    });

    wrap.appendChild(input);
    wrap.appendChild(btn);
    return wrap;
  }

  // API 에러 메시지 추출 — FastAPI 의 {detail: {error, database}} 구조에 맞춤
  function errMsg(err, fallback) {
    const p = err && err.payload;
    const d = p && (p.detail || p.error);
    if (d) {
      if (typeof d === "string") return d;
      const txt = d.error || d.message || JSON.stringify(d);
      return d.database ? `${txt} (${d.database})` : txt;
    }
    return (err && err.message) || fallback || "요청 실패";
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

  // 객체/배열을 인라인 한 줄 JSON 으로 (key 뒤 ": ", 항목 뒤 ", ")
  function jsonInline(value) {
    if (value === null) return "null";
    if (typeof value !== "object") return JSON.stringify(value);
    if (Array.isArray(value)) {
      return "[" + value.map(jsonInline).join(", ") + "]";
    }
    const pairs = Object.entries(value).map(([k, v]) => JSON.stringify(k) + ": " + jsonInline(v));
    return "{" + pairs.join(", ") + "}";
  }

  // 최상위 속성값 — 배열은 한 항목씩 줄바꿈, 그 외는 인라인
  function formatTopValue(value) {
    if (Array.isArray(value)) {
      const items = value.map((it, i) =>
        "                " + jsonInline(it) + (i === value.length - 1 ? "" : ",")
      ).join("\n");
      return "[\n" + items + "\n            ]";
    }
    return jsonInline(value);
  }

  function buildCreateProfileSql(profileName, attrs) {
    const obj = {};
    for (const a of attrs || []) {
      if (!a || !a.attribute_name) continue;
      obj[a.attribute_name] = coerceAttrValue(a.attribute_value);
    }
    const keys = Object.keys(obj);
    const lines = keys.map((k, i) => {
      const comma = i === keys.length - 1 ? "" : ",";
      return `"${k}": ${formatTopValue(obj[k])}${comma}`;
    });
    const first = lines[0] || "";
    const rest = lines.slice(1).map((l) => "            " + l).join("\n");
    const attrBody = rest
      ? `{${first}\n${rest}\n            }`
      : `{${first}}`;
    // Oracle PL/SQL 문자열 안에서 single-quote 는 '' 로 이스케이프
    const attrJson = attrBody.replace(/'/g, "''");
    return `BEGIN
    dbms_cloud_ai.drop_profile(
        profile_name => '${profileName}',
        force => true
    );

    dbms_cloud_ai.create_profile(
        profile_name => '${profileName}',
        attributes =>
            '${attrJson}'
        );
END;`;
  }

  // 개별 Profile 테스트 모달 — 프롬프트 + action → /api/profiles/benchmark (iterations:1) 호출
  function openProfileTestModal(profileName) {
    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    backdrop.innerHTML = `
      <div class="modal" style="width:720px;">
        <div class="modal-header">
          <h2>Profile Test — ${profileName}</h2>
          <button class="btn btn-ghost" id="pt-modal-close">✕</button>
        </div>
        <div class="modal-body stack">
          <div class="stack-sm">
            <div class="row" style="justify-content: space-between;">
              <label>프롬프트</label>
              <div class="row" style="gap:6px; flex-wrap:nowrap;">
                <input type="text" id="ptm-prompt-title" placeholder="저장할 제목" style="width:130px;">
                <button class="btn" id="ptm-prompt-add">추가</button>
                <button class="btn" id="ptm-prompt-update">수정</button>
                <select id="ptm-prompt-saved" style="width:150px; flex:0 0 150px;"></select>
              </div>
            </div>
            <textarea id="ptm-prompt" rows="3">Oracle이 어떤 회사인지 설명해줘. 300자 이내로 설명해줘.</textarea>
          </div>
          <div class="row" style="gap:12px; align-items:flex-end;">
            <div class="stack-sm" style="flex:0 0 200px;">
              <label>Action</label>
              <select id="ptm-action">
                <option value="chat" selected>chat</option>
                <option value="runsql">runsql</option>
                <option value="narrate">narrate</option>
                <option value="showsql">showsql</option>
                <option value="explainsql">explainsql</option>
                <option value="showprompt">showprompt</option>
              </select>
            </div>
            <div style="flex:1"></div>
            <button class="btn btn-primary" id="ptm-run">▶ 실행</button>
          </div>
          <div class="stack-sm">
            <div class="row" style="justify-content: space-between; align-items:center;">
              <label>결과 <span id="ptm-elapsed" class="muted" style="font-size:var(--fs-sm);"></span></label>
              <button class="btn btn-ghost" id="ptm-result-copy">복사</button>
            </div>
            <textarea id="ptm-result" rows="10" readonly
              style="font-family:var(--font-mono); font-size:var(--fs-sm);"
              placeholder="[실행] 후 표시됩니다."></textarea>
          </div>
        </div>
      </div>
    `;
    backdrop.addEventListener("click", (e) => { if (e.target === backdrop) backdrop.remove(); });
    backdrop.querySelector("#pt-modal-close").addEventListener("click", () => backdrop.remove());

    // 결과 복사 — 클립보드 API 우선, 실패 시 execCommand fallback (showSqlModal 과 동일 패턴)
    backdrop.querySelector("#ptm-result-copy").addEventListener("click", async () => {
      const text = backdrop.querySelector("#ptm-result").value;
      if (!text) { window.Toast.show("복사할 결과가 없습니다", "warn"); return; }
      try {
        await navigator.clipboard.writeText(text);
        window.Toast.show("클립보드에 복사됨", "success");
      } catch (_) {
        const ta = document.createElement("textarea");
        ta.value = text; document.body.appendChild(ta); ta.select();
        try { document.execCommand("copy"); window.Toast.show("클립보드에 복사됨", "success"); }
        catch (e) { window.Toast.show("복사 실패", "error"); }
        ta.remove();
      }
    });

    // --- 프롬프트 저장/불러오기 (localStorage, 세션 간 유지) ---
    const PROMPTS_KEY = "profileTest.savedPrompts";
    const promptEl = backdrop.querySelector("#ptm-prompt");
    const titleInput = backdrop.querySelector("#ptm-prompt-title");
    const addBtn = backdrop.querySelector("#ptm-prompt-add");
    const updateBtn = backdrop.querySelector("#ptm-prompt-update");
    const savedSel = backdrop.querySelector("#ptm-prompt-saved");

    const loadSaved = () => {
      try { return JSON.parse(window.Store.get(PROMPTS_KEY)) || []; }
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
      const prompt = promptEl.value;
      if (!title) { window.Toast.show("추가할 제목을 입력하세요", "error"); titleInput.focus(); return; }
      if (!prompt.trim()) { window.Toast.show("프롬프트가 비어 있습니다", "error"); return; }
      const list = loadSaved();
      if (list.some((p) => p.title === title)) {
        window.Toast.show("이미 있는 제목입니다. [저장]으로 수정하세요", "error");
        return;
      }
      list.push({ title, prompt });
      window.Store.set(PROMPTS_KEY, JSON.stringify(list));
      refreshCombo(title);
      titleInput.value = "";
      window.Toast.show(`'${title}' 추가됨`, "success");
    });

    // 저장 — 콤보에서 선택한 기존 title 의 프롬프트를 현재 내용으로 수정
    updateBtn.addEventListener("click", () => {
      const title = savedSel.value;
      if (!title) { window.Toast.show("수정할 항목을 콤보에서 선택하세요", "error"); return; }
      const prompt = promptEl.value;
      if (!prompt.trim()) { window.Toast.show("프롬프트가 비어 있습니다", "error"); return; }
      const list = loadSaved();
      const idx = list.findIndex((p) => p.title === title);
      if (idx < 0) { window.Toast.show("저장된 항목을 찾을 수 없습니다", "error"); return; }
      list[idx].prompt = prompt;
      window.Store.set(PROMPTS_KEY, JSON.stringify(list));
      window.Toast.show(`'${title}' 수정됨`, "success");
    });

    savedSel.addEventListener("change", () => {
      const title = savedSel.value;
      if (!title) return;
      const found = loadSaved().find((p) => p.title === title);
      if (found) promptEl.value = found.prompt;
    });

    backdrop.querySelector("#ptm-run").addEventListener("click", async () => {
      const prompt = backdrop.querySelector("#ptm-prompt").value;
      const action = backdrop.querySelector("#ptm-action").value;
      if (!prompt.trim()) { window.Toast.show("프롬프트를 입력하세요", "warn"); return; }
      const runBtn = backdrop.querySelector("#ptm-run");
      const elapsed = backdrop.querySelector("#ptm-elapsed");
      const resultEl = backdrop.querySelector("#ptm-result");
      runBtn.disabled = true;
      runBtn.innerHTML = '<span class="spinner"></span> 실행 중...';
      elapsed.textContent = "";
      resultEl.value = "";
      try {
        const data = await window.API.post("/api/profiles/benchmark", {
          prompt, action, profile_names: [profileName], iterations: 1,
        });
        const run = (data.results && data.results[0] && data.results[0].runs[0]) || {};
        if (run.error) {
          resultEl.value = run.error;
          elapsed.textContent = `오류 · ${(run.elapsed_ms || 0).toLocaleString()} ms`;
        } else {
          resultEl.value = run.response || "";
          elapsed.textContent = `${(run.elapsed_ms || 0).toLocaleString()} ms`;
        }
      } catch (e) {
        const msg = errMsg(e, "실행 실패");
        resultEl.value = msg;
        elapsed.textContent = "오류";
        window.Toast.show(msg, "error");
      } finally {
        runBtn.disabled = false;
        runBtn.innerHTML = "▶ 실행";
      }
    });

    document.body.appendChild(backdrop);
    setTimeout(() => backdrop.querySelector("#ptm-prompt").focus(), 50);
  }

  function showSqlModal(title, sql) {
    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    backdrop.innerHTML = `
      <div class="modal" style="width:760px;">
        <div class="modal-header">
          <h2>${title}</h2>
          <div class="row">
            <button class="btn btn-ghost" id="sql-copy">복사</button>
            <button class="btn btn-ghost" id="sql-close">✕</button>
          </div>
        </div>
        <div class="modal-body">
          <pre id="sql-pre" style="white-space:pre; margin:0; font-family:var(--font-mono); font-size:var(--fs-sm); background:var(--surface-alt); padding:var(--space-3); border-radius:var(--radius-md); overflow:auto;"></pre>
        </div>
      </div>
    `;
    backdrop.querySelector("#sql-pre").textContent = sql;
    backdrop.addEventListener("click", (e) => { if (e.target === backdrop) backdrop.remove(); });
    backdrop.querySelector("#sql-close").addEventListener("click", () => backdrop.remove());
    backdrop.querySelector("#sql-copy").addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(sql);
        window.Toast.show("클립보드에 복사됨", "success");
      } catch (_) {
        // fallback
        const ta = document.createElement("textarea");
        ta.value = sql; document.body.appendChild(ta); ta.select();
        try { document.execCommand("copy"); window.Toast.show("클립보드에 복사됨", "success"); }
        catch (e) { window.Toast.show("복사 실패", "error"); }
        ta.remove();
      }
    });
    document.body.appendChild(backdrop);
  }

  window.Views = window.Views || {};
  window.Views.profileTest = render;
  // 다른 화면(예: AI Agent Team Test)에서 Profile 상세 팝업을 띄울 때 사용.
  window.ProfileDetail = { open: openProfileDetailModal };
})();
