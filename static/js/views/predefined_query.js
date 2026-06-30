/** views/predefined_query.js — 메뉴 [Select AI Test - Predefined Query].
 * Predefined Query(=T_PREDEFINED_QUERY 행)를 드롭다운(표시=DESCRIPTION)으로 고르고,
 * [관리] 팝업에서 행을 추가/수정/삭제한다. 질문 + AI Profile 을 입력해 [실행] 하면
 * 백엔드(/api/predefined/execute)가 f_predefined_query(p_id, p_question, p_profile_name) 를
 * 호출하고 그 결과(CLOB 답변)를 답변 영역에 표시한다.
 */
(function () {
  // 질문 저장 프롬프트 키 (이 화면 전용 — DB별 격리는 Store 가 처리)
  const Q_KEY = "predefined.savedQuestions";
  // 편집 폼 필드 (T_PREDEFINED_QUERY 컬럼, 모두 NOT NULL)
  const FIELDS = [
    { key: "description", label: "DESCRIPTION (설명)", rows: 1 },
    { key: "nl_question", label: "NL_QUESTION (자연어 질의 예시)", rows: 2 },
    { key: "sql_text", label: "SQL_TEXT (바인드 :변수 포함 SQL)", rows: 6 },
    { key: "entity_prompt", label: "ENTITY_PROMPT (엔티티 추출 프롬프트)", rows: 4 },
    { key: "few_shot", label: "FEW_SHOT (답변 형식·톤 예시)", rows: 3 },
  ];

  function errMsg(err, fallback) {
    const p = err && err.payload;
    const d = p && (p.detail || p.error);
    if (d) {
      if (typeof d === "string") return d;
      return d.error || d.message || JSON.stringify(d);
    }
    return (err && err.message) || fallback || "요청 실패";
  }

  function errBox(msg) {
    const d = document.createElement("div");
    d.className = "empty-state";
    d.style.color = "var(--danger, #c74634)";
    d.style.whiteSpace = "pre-wrap";
    d.textContent = msg;
    return d;
  }

  // 입력 필드 + (제목/추가/수정/콤보) 저장 프롬프트 연결 — nl2sql 화면과 동일 규약 [{title,prompt}]
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
      if (!prompt.trim()) { window.Toast.show("질문이 비어 있습니다", "error"); return; }
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
      if (!prompt.trim()) { window.Toast.show("질문이 비어 있습니다", "error"); return; }
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

  async function render() {
    const main = document.getElementById("main");
    main.innerHTML = "";

    const panel = document.createElement("div");
    panel.className = "stack";
    panel.innerHTML = `
      <div class="row" style="align-items:center;">
        <label style="width:160px; font-weight:600;">Predefined Query</label>
        <select id="pq-select" style="flex:1; min-width:220px;"></select>
        <button class="btn" id="pq-manage" type="button">관리</button>
      </div>
      <div class="row" style="align-items:center;">
        <label style="width:160px; font-weight:600;">AI Profile</label>
        <select id="pq-profile" style="min-width:220px;"></select>
      </div>
      <div class="row" style="align-items:stretch; gap:var(--space-4);">
        <div class="stack" style="flex:1;">
          <div class="stack-sm">
            <div class="row" style="justify-content:space-between; gap:var(--space-2);">
              <label style="font-weight:600;">질문</label>
              <div class="row" style="gap:var(--space-2);">
                <input type="text" id="pq-q-title" placeholder="저장할 제목" style="width:120px;" />
                <button class="btn" id="pq-q-add" type="button">추가</button>
                <button class="btn" id="pq-q-update" type="button">수정</button>
                <select id="pq-q-saved" style="min-width:140px;"></select>
              </div>
            </div>
            <textarea id="pq-question" rows="2" style="width:100%;" placeholder="질문입력"></textarea>
          </div>
        </div>
        <div style="display:flex; min-width:130px;">
          <button class="btn btn-primary" id="pq-run" type="button" style="flex:1; min-width:120px; font-size:2em; display:flex; align-items:center; justify-content:center;">실행</button>
        </div>
      </div>
      <label style="font-weight:600;">답변</label>
      <div id="pq-answer" style="border:1px solid var(--border); border-radius:var(--radius-md); min-height:260px; padding:var(--space-3);">
        <div class="empty-state muted">Predefined Query 와 AI Profile 을 고르고 질문을 입력한 뒤 실행을 누르세요.</div>
      </div>
    `;
    main.appendChild(panel);

    const selectEl = panel.querySelector("#pq-select");
    const profileEl = panel.querySelector("#pq-profile");
    const questionEl = panel.querySelector("#pq-question");
    const answerEl = panel.querySelector("#pq-answer");

    let rows = [];  // T_PREDEFINED_QUERY 행 캐시 (선택 시 질문 자동입력에 사용)

    // Predefined Query 드롭다운 로드 (표시=DESCRIPTION, value=ID)
    async function loadList(selectId) {
      selectEl.innerHTML = `<option value="">불러오는 중…</option>`;
      try {
        rows = await window.API.get("/api/predefined");
      } catch (e) {
        rows = [];
        selectEl.innerHTML = `<option value="">${window.escapeHtml(errMsg(e, "목록 로드 실패"))}</option>`;
        return;
      }
      selectEl.innerHTML = "";
      if (!rows.length) {
        selectEl.innerHTML = `<option value="">(등록된 Predefined Query 없음 — [관리]에서 추가)</option>`;
        return;
      }
      rows.forEach((r) => {
        const o = document.createElement("option");
        o.value = String(r.id);
        o.textContent = `${r.id}. ${r.description}`;
        selectEl.appendChild(o);
      });
      if (selectId != null) selectEl.value = String(selectId);
      applyQuestionPrefill();
    }

    // 선택한 행의 NL_QUESTION 을 질문칸에 자동입력(수정 가능). 사용자가 이미 입력했으면 덮어쓰지 않음.
    function applyQuestionPrefill(force) {
      const r = rows.find((x) => String(x.id) === selectEl.value);
      if (r && (force || !questionEl.value.trim())) questionEl.value = r.nl_question || "";
    }
    selectEl.addEventListener("change", () => applyQuestionPrefill(true));

    // AI Profile 드롭다운 — ENABLED 만
    async function loadProfiles() {
      profileEl.innerHTML = `<option value="">불러오는 중…</option>`;
      try {
        const profiles = await window.API.get("/api/profiles");
        const enabled = (profiles || []).filter((p) => p.status === "ENABLED");
        profileEl.innerHTML = "";
        if (!enabled.length) {
          profileEl.innerHTML = `<option value="">사용 가능한 Profile 이 없습니다</option>`;
          return;
        }
        enabled.forEach((p) => {
          const o = document.createElement("option");
          o.value = p.profile_name;
          o.textContent = p.profile_name;
          profileEl.appendChild(o);
        });
      } catch (e) {
        profileEl.innerHTML = `<option value="">${window.escapeHtml(errMsg(e, "Profile 로드 실패"))}</option>`;
      }
    }

    await Promise.all([loadList(), loadProfiles()]);

    wireSavedPrompts(Q_KEY, questionEl, panel.querySelector("#pq-q-title"),
      panel.querySelector("#pq-q-add"), panel.querySelector("#pq-q-update"), panel.querySelector("#pq-q-saved"));

    panel.querySelector("#pq-manage").addEventListener("click", () => {
      openManageModal(() => loadList(selectEl.value || null));
    });

    panel.querySelector("#pq-run").addEventListener("click", async () => {
      const id = selectEl.value;
      const profile_name = profileEl.value;
      const question = questionEl.value.trim();
      if (!id) { window.Toast.show("Predefined Query 를 선택하세요", "error"); return; }
      if (!profile_name) { window.Toast.show("AI Profile 을 선택하세요", "error"); return; }
      if (!question) { window.Toast.show("질문을 입력하세요", "error"); return; }

      const btn = panel.querySelector("#pq-run");
      btn.disabled = true;
      answerEl.innerHTML = `<div class="empty-state muted"><span class="spinner"></span> 실행 중… (엔티티 추출 + SQL 실행 + 답변 생성)</div>`;
      try {
        const data = await window.API.post("/api/predefined/execute", { id, question, profile_name });
        answerEl.innerHTML = "";
        const pre = document.createElement("pre");
        pre.style.cssText = "white-space:pre-wrap; word-break:break-word; margin:0; font-family:var(--font);";
        pre.textContent = data.result || "(빈 응답)";
        answerEl.appendChild(pre);
      } catch (e) {
        answerEl.innerHTML = "";
        answerEl.appendChild(errBox(errMsg(e, "실행 실패")));
      } finally {
        btn.disabled = false;
      }
    });
  }

  // 관리 팝업 — 목록(상단) + 편집폼(하단) 한 화면에서 추가/수정/삭제. onChanged: 변경 시 메인 드롭다운 갱신용.
  async function openManageModal(onChanged) {
    let list = [];
    let editingId = null;  // null=새로 추가, 숫자=수정 대상

    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    backdrop.innerHTML = `
      <div class="modal" style="width:880px; max-width:94vw; max-height:88vh;">
        <div class="modal-header">
          <h2>Predefined Query 관리</h2>
          <button class="btn btn-ghost" id="pm-close" type="button">✕</button>
        </div>
        <div class="modal-body stack">
          <div id="pm-list" style="max-height:200px; overflow:auto; border:1px solid var(--border); border-radius:var(--radius-md);"></div>
          <div class="row" style="justify-content:space-between; align-items:center;">
            <strong id="pm-form-title">새 항목 추가</strong>
            <button class="btn" id="pm-new" type="button">＋ 새로 추가</button>
          </div>
          <div id="pm-form" class="stack"></div>
        </div>
        <div class="modal-footer row" style="justify-content:space-between; gap:var(--space-2);">
          <button class="btn" id="pm-delete" type="button" style="color:var(--danger,#c74634);">삭제</button>
          <div class="row" style="gap:var(--space-2);">
            <button class="btn" id="pm-cancel" type="button">닫기</button>
            <button class="btn btn-primary" id="pm-save" type="button">저장</button>
          </div>
        </div>
      </div>
    `;
    const close = () => { backdrop.remove(); document.removeEventListener("keydown", onKey); };
    const onKey = (e) => { if (e.key === "Escape") close(); };
    document.addEventListener("keydown", onKey);
    document.body.appendChild(backdrop);

    const listHost = backdrop.querySelector("#pm-list");
    const formHost = backdrop.querySelector("#pm-form");
    const formTitle = backdrop.querySelector("#pm-form-title");
    const deleteBtn = backdrop.querySelector("#pm-delete");

    // 편집 폼 그리기 (FIELDS 기반 textarea/input)
    formHost.innerHTML = FIELDS.map((f) => `
      <div class="stack-sm">
        <label>${f.label}</label>
        <textarea id="pm-${f.key}" rows="${f.rows}" style="width:100%; font-family:var(--font-mono); font-size:var(--fs-sm);"></textarea>
      </div>
    `).join("");
    const fieldEl = (k) => backdrop.querySelector(`#pm-${k}`);

    const fillForm = (row) => {
      FIELDS.forEach((f) => { fieldEl(f.key).value = row ? (row[f.key] || "") : ""; });
    };
    const setMode = (id) => {
      editingId = id;
      const row = id == null ? null : list.find((r) => String(r.id) === String(id));
      fillForm(row);
      formTitle.textContent = id == null ? "새 항목 추가" : `수정 — ID ${id}`;
      deleteBtn.style.display = id == null ? "none" : "";
    };

    const refreshList = async (keepId) => {
      listHost.innerHTML = `<div class="empty-state muted">불러오는 중…</div>`;
      try {
        list = await window.API.get("/api/predefined");
      } catch (e) {
        list = [];
        listHost.innerHTML = "";
        listHost.appendChild(errBox(errMsg(e, "목록 로드 실패")));
        return;
      }
      const cols = [
        { key: "id", label: "ID" },
        { key: "description", label: "DESCRIPTION" },
        { key: "nl_question", label: "NL_QUESTION" },
      ];
      const table = window.SimpleTable.create(cols, list, {
        emptyText: "등록된 항목이 없습니다",
        onRowClick: (row) => setMode(row.id),
      });
      listHost.innerHTML = "";
      listHost.appendChild(table);
      setMode(keepId != null ? keepId : null);
    };
    await refreshList();

    backdrop.querySelector("#pm-new").addEventListener("click", () => setMode(null));
    backdrop.querySelector("#pm-close").addEventListener("click", close);
    backdrop.querySelector("#pm-cancel").addEventListener("click", close);

    backdrop.querySelector("#pm-save").addEventListener("click", async () => {
      const body = {};
      for (const f of FIELDS) {
        const v = fieldEl(f.key).value;
        if (!v.trim()) { window.Toast.show(`${f.label} 는 필수입니다`, "error"); fieldEl(f.key).focus(); return; }
        body[f.key] = v;
      }
      try {
        if (editingId == null) {
          await window.API.post("/api/predefined", body);
          window.Toast.show("추가됨", "success");
        } else {
          await window.API.put(`/api/predefined/${editingId}`, body);
          window.Toast.show("수정됨", "success");
        }
        if (onChanged) onChanged();
        await refreshList(editingId);
      } catch (e) {
        window.Toast.show(errMsg(e, "저장 실패"), "error");
      }
    });

    deleteBtn.addEventListener("click", async () => {
      if (editingId == null) return;
      if (!confirm(`ID ${editingId} 항목을 삭제할까요?`)) return;
      try {
        await window.API.delete(`/api/predefined/${editingId}`);
        window.Toast.show("삭제됨", "success");
        if (onChanged) onChanged();
        await refreshList();
      } catch (e) {
        window.Toast.show(errMsg(e, "삭제 실패"), "error");
      }
    });
  }

  window.Views = window.Views || {};
  window.Views.predefinedQuery = render;
})();
