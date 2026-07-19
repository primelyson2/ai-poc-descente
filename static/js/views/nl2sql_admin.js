/**
 * nl2sql_admin.js — Select AI Test - 질문관리
 * 질문 등록/수정/삭제 + (선택 질문의) 조회컬럼 CRUD + 유사질문 CRUD.
 * 유사질문/질문 벡터는 서버에서 DBMS_VECTOR.UTL_TO_EMBEDDING 으로 임베딩(embed_params).
 * 백엔드: /api/nl2sql/questions(+/{id}), /columns(+/{id}), /questions/{id}/columns,
 *         /questions/{id}/similars, /similars(+/{id}).
 */
(function () {
  const EMBED_KEY = "nl2sql.embedParams";                 // Store(DB별) 임베딩 params
  const DEFAULT_EMBED = JSON.stringify({
    provider: "ocigenai",
    credential_name: "GENAI_VECTOR_CRED",
    url: "https://inference.generativeai.us-chicago-1.oci.oraclecloud.com/20231130/actions/embedText",
    model: "cohere.embed-v4.0",
  }, null, 2);

  function errMsg(err, fallback) {
    const p = err && err.payload;
    const d = p && (p.detail || p.error);
    if (d) {
      if (typeof d === "string") return d;
      return d.error || d.message || JSON.stringify(d);
    }
    return (err && err.message) || fallback || "요청 실패";
  }

  function modalBackdrop(html) {
    const bd = document.createElement("div"); bd.className = "modal-backdrop"; bd.innerHTML = html;
    const onKey = (e) => { if (e.key === "Escape") close(); };
    function close() { bd.remove(); document.removeEventListener("keydown", onKey); }
    bd._close = close;
    document.addEventListener("keydown", onKey);
    document.body.appendChild(bd);
    return bd;
  }

  // 텍스트 입력 모달(추가/수정 공용). onSave(value) 는 저장 성공 시 true 반환하면 닫힘.
  function openTextModal({ title, value = "", multiline = true, placeholder = "", onSave }) {
    const field = multiline
      ? `<textarea id="tm-val" rows="5" style="width:100%; font-size:var(--fs-sm);" placeholder="${window.escapeAttr(placeholder)}"></textarea>`
      : `<input type="text" id="tm-val" style="width:100%;" placeholder="${window.escapeAttr(placeholder)}" />`;
    const bd = modalBackdrop(`
      <div class="modal" style="width:560px; max-width:94vw;">
        <div class="modal-header"><h2>${window.escapeHtml(title)}</h2><button class="btn btn-ghost" id="tm-close" type="button">✕</button></div>
        <div class="modal-body stack">${field}</div>
        <div class="modal-footer row end" style="gap:var(--space-2);">
          <button class="btn" id="tm-cancel" type="button">취소</button>
          <button class="btn btn-primary" id="tm-save" type="button">저장</button>
        </div>
      </div>`);
    const valEl = bd.querySelector("#tm-val");
    valEl.value = value;
    bd.querySelector("#tm-close").addEventListener("click", () => bd._close());
    bd.querySelector("#tm-cancel").addEventListener("click", () => bd._close());
    bd.querySelector("#tm-save").addEventListener("click", async () => {
      const v = valEl.value.trim();
      if (!v) { window.Toast.show("내용을 입력하세요", "error"); return; }
      const ok = await onSave(v);
      if (ok) bd._close();
    });
    setTimeout(() => valEl.focus(), 50);
  }

  // 표 액션 셀(수정/삭제 등) — 행 클릭과 충돌하지 않도록 stopPropagation.
  function actionCell(buttons) {
    const wrap = document.createElement("div");
    wrap.className = "row"; wrap.style.gap = "6px";
    buttons.forEach((b) => {
      const btn = document.createElement("button");
      btn.className = "btn btn-mini"; btn.type = "button"; btn.textContent = b.label;
      if (b.danger) btn.style.color = "var(--primary)";
      btn.addEventListener("click", (e) => { e.stopPropagation(); b.on(); });
      wrap.appendChild(btn);
    });
    return wrap;
  }

  // 임베딩 성공/실패 토스트
  function embedToast(res, okMsg) {
    if (res && res.warning === "embed_failed") {
      window.Toast.show("임베딩 실패 — 텍스트만 저장했습니다(임베딩 모델/설정 확인)", "warn");
    } else {
      window.Toast.show(okMsg, "success");
    }
  }

  async function render() {
    const main = document.getElementById("main");
    main.innerHTML = "";

    const title = document.createElement("div");
    title.className = "view-title";
    title.innerHTML = `<h1>Select AI Test - 질문관리</h1>
      <span class="sub">질문·조회컬럼·유사질문을 등록/관리합니다 (유사질문·질문은 임베딩 벡터 생성)</span>`;
    main.appendChild(title);

    // 임베딩 설정(접이식)
    const embedInit = window.Store.get(EMBED_KEY) || DEFAULT_EMBED;
    const embedBox = document.createElement("details");
    embedBox.className = "panel";
    embedBox.style.marginBottom = "var(--space-3)";
    embedBox.innerHTML = `
      <summary style="cursor:pointer; padding:8px 4px; font-weight:600;">임베딩 설정 (DBMS_VECTOR.UTL_TO_EMBEDDING params)</summary>
      <div class="panel-body stack">
        <textarea id="na-embed" rows="6" style="width:100%; font-family:var(--font-mono); font-size:var(--fs-sm);"></textarea>
        <span class="field-hint">질문/유사질문 저장 시 이 params(JSON)로 임베딩합니다(<code>DBMS_VECTOR.UTL_TO_EMBEDDING</code>). 비우면 임베딩 없이 텍스트만 저장. 기본은 OCI GenAI(<code>cohere.embed-v4.0</code>) — 자격증명 <code>GENAI_VECTOR_CRED</code> 가 DB에 있어야 합니다. DB 내장 ONNX 모델을 쓰려면 <code>{"provider":"database","model":"&lt;모델명&gt;"}</code>. 준비 방법은 Guide_질문관리.md §3.1 참고.</span>
      </div>`;
    main.appendChild(embedBox);
    const embedEl = embedBox.querySelector("#na-embed");
    embedEl.value = embedInit;
    embedEl.addEventListener("change", () => window.Store.set(EMBED_KEY, embedEl.value.trim()));
    const getEmbed = () => (embedEl.value || "").trim();

    // 질문 목록 패널
    const qPanel = document.createElement("div");
    qPanel.className = "panel";
    qPanel.innerHTML = `
      <div class="panel-header"><h2>질문 목록</h2></div>
      <div class="panel-body stack">
        <div class="row" style="gap:6px;">
          <input type="text" id="na-search" placeholder="질문 검색(부분일치)" style="flex:1;" />
          <button class="btn" id="na-search-btn" type="button">검색</button>
          <button class="btn btn-primary" id="na-add-q" type="button">질문 추가</button>
        </div>
        <div id="na-qlist"></div>
      </div>`;
    main.appendChild(qPanel);

    // 선택 질문 상세(조회컬럼 / 유사질문 탭)
    const detail = document.createElement("div");
    detail.className = "panel";
    detail.innerHTML = `
      <div class="panel-header"><h2>선택 질문 상세</h2></div>
      <div class="panel-body" id="na-detail"><div class="muted">위 목록에서 질문을 선택하세요.</div></div>`;
    main.appendChild(detail);
    const detailBody = detail.querySelector("#na-detail");

    let selectedId = null;
    let selectedText = "";

    const searchEl = qPanel.querySelector("#na-search");
    const qlist = qPanel.querySelector("#na-qlist");

    async function loadQuestions() {
      const q = searchEl.value.trim();
      let rows = [];
      try {
        rows = await window.API.get("/api/nl2sql/questions" + (q ? "?q=" + encodeURIComponent(q) : ""));
      } catch (err) {
        window.Toast.show("질문 조회 실패: " + errMsg(err), "error");
        return;
      }
      const table = window.SimpleTable.create(
        [
          { key: "question", label: "질문" },
          { key: () => "", label: "관리", align: "right", headerAlign: "right",
            format: (_v, row) => actionCell([
              { label: "수정", on: () => editQuestion(row) },
              { label: "삭제", danger: true, on: () => deleteQuestion(row) },
            ]) },
        ],
        rows,
        {
          emptyText: "등록된 질문이 없습니다. [질문 추가]로 등록하세요.",
          rowClassName: (row) => (row.id === selectedId ? "active" : ""),
          onRowClick: (row) => selectQuestion(row),
        }
      );
      qlist.innerHTML = "";
      qlist.appendChild(table);
    }

    function selectQuestion(row) {
      selectedId = row.id; selectedText = row.question || "";
      // 목록 하이라이트 갱신
      qlist.querySelectorAll("tbody tr").forEach((tr) => tr.classList.remove("active"));
      renderDetail();
      // 선택 표시를 위해 목록 재조회(간단·정확)
      loadQuestions();
    }

    function renderDetail() {
      detailBody.innerHTML = "";
      if (selectedId == null) {
        detailBody.innerHTML = `<div class="muted">위 목록에서 질문을 선택하세요.</div>`;
        return;
      }
      const head = document.createElement("div");
      head.className = "stack-sm";
      head.style.marginBottom = "var(--space-2)";
      head.innerHTML = `<div class="muted" style="font-size:var(--fs-sm);">선택 질문</div>
        <div style="white-space:pre-wrap;">${window.escapeHtml(selectedText)}</div>`;
      detailBody.appendChild(head);

      const tabs = window.Tabs.create([
        { id: "cols", label: "조회컬럼", render: (host) => renderColumnsTab(host) },
        { id: "sims", label: "유사질문", render: (host) => renderSimilarsTab(host) },
      ]);
      detailBody.appendChild(tabs);
    }

    // ── 조회컬럼 탭 ──────────────────────────────────────────────
    async function renderColumnsTab(host) {
      host.innerHTML = "";
      const listBox = document.createElement("div");
      host.appendChild(listBox);

      const addRow = document.createElement("div");
      addRow.className = "row"; addRow.style.cssText = "gap:6px; margin-top:var(--space-2);";
      addRow.innerHTML = `<input type="text" id="na-col-new" placeholder="추가할 조회컬럼명" style="flex:1;" />
        <button class="btn btn-primary" id="na-col-add" type="button">+ 컬럼 추가</button>`;
      host.appendChild(addRow);

      async function reload() {
        let rows = [];
        try { rows = await window.API.get(`/api/nl2sql/questions/${selectedId}/columns`); }
        catch (err) { window.Toast.show("컬럼 조회 실패: " + errMsg(err), "error"); return; }
        const table = window.SimpleTable.create(
          [
            { key: "column_name", label: "조회컬럼" },
            { key: () => "", label: "관리", align: "right", headerAlign: "right",
              format: (_v, row) => actionCell([
                { label: "수정", on: () => editCol(row) },
                { label: "삭제", danger: true, on: () => delCol(row) },
              ]) },
          ],
          rows,
          { emptyText: "이 질문에 연결된 조회컬럼이 없습니다." }
        );
        listBox.innerHTML = ""; listBox.appendChild(table);
      }

      function editCol(row) {
        openTextModal({
          title: "조회컬럼 수정", value: row.column_name, multiline: false,
          onSave: async (v) => {
            try {
              await window.API.put(`/api/nl2sql/columns/${row.id}`, { column_name: v });
              window.Toast.show("수정됨", "success"); reload(); return true;
            } catch (err) { window.Toast.show("수정 실패: " + errMsg(err), "error"); return false; }
          },
        });
      }
      async function delCol(row) {
        if (!window.confirm(`조회컬럼 '${row.column_name}' 을(를) 삭제할까요?`)) return;
        try { await window.API.delete(`/api/nl2sql/columns/${row.id}`); window.Toast.show("삭제됨", "success"); reload(); }
        catch (err) { window.Toast.show("삭제 실패: " + errMsg(err), "error"); }
      }
      addRow.querySelector("#na-col-add").addEventListener("click", async () => {
        const inp = addRow.querySelector("#na-col-new");
        const name = inp.value.trim();
        if (!name) { window.Toast.show("컬럼명을 입력하세요", "error"); return; }
        try {
          await window.API.post("/api/nl2sql/columns", { column_name: name, question_id: selectedId });
          inp.value = ""; window.Toast.show("추가됨", "success"); reload();
        } catch (err) { window.Toast.show("추가 실패: " + errMsg(err), "error"); }
      });

      reload();
    }

    // ── 유사질문 탭 ──────────────────────────────────────────────
    async function renderSimilarsTab(host) {
      host.innerHTML = "";
      const listBox = document.createElement("div");
      host.appendChild(listBox);

      const addRow = document.createElement("div");
      addRow.className = "row"; addRow.style.cssText = "gap:6px; margin-top:var(--space-2); align-items:flex-start;";
      addRow.innerHTML = `<textarea id="na-sim-new" rows="2" placeholder="추가할 유사(대체 표현) 질문" style="flex:1; font-size:var(--fs-sm);"></textarea>
        <button class="btn btn-primary" id="na-sim-add" type="button">+ 유사질문 추가</button>`;
      host.appendChild(addRow);

      async function reload() {
        let rows = [];
        try { rows = await window.API.get(`/api/nl2sql/questions/${selectedId}/similars`); }
        catch (err) { window.Toast.show("유사질문 조회 실패: " + errMsg(err), "error"); return; }
        const table = window.SimpleTable.create(
          [
            { key: "similar_question", label: "유사질문" },
            { key: "has_vector", label: "벡터", align: "center", headerAlign: "center",
              format: (v) => (v ? "✓" : "—") },
            { key: () => "", label: "관리", align: "right", headerAlign: "right",
              format: (_v, row) => actionCell([
                { label: "수정", on: () => editSim(row) },
                { label: "삭제", danger: true, on: () => delSim(row) },
              ]) },
          ],
          rows,
          { emptyText: "이 질문에 연결된 유사질문이 없습니다." }
        );
        listBox.innerHTML = ""; listBox.appendChild(table);
      }

      function editSim(row) {
        openTextModal({
          title: "유사질문 수정", value: row.similar_question, multiline: true,
          onSave: async (v) => {
            try {
              const res = await window.API.put(`/api/nl2sql/similars/${row.id}`, { similar_question: v, embed_params: getEmbed() });
              embedToast(res, "수정됨"); reload(); return true;
            } catch (err) { window.Toast.show("수정 실패: " + errMsg(err), "error"); return false; }
          },
        });
      }
      async function delSim(row) {
        if (!window.confirm("이 유사질문을 삭제할까요?")) return;
        try { await window.API.delete(`/api/nl2sql/similars/${row.id}`); window.Toast.show("삭제됨", "success"); reload(); }
        catch (err) { window.Toast.show("삭제 실패: " + errMsg(err), "error"); }
      }
      addRow.querySelector("#na-sim-add").addEventListener("click", async () => {
        const inp = addRow.querySelector("#na-sim-new");
        const text = inp.value.trim();
        if (!text) { window.Toast.show("유사질문을 입력하세요", "error"); return; }
        try {
          const res = await window.API.post("/api/nl2sql/similars", { question_id: selectedId, similar_question: text, embed_params: getEmbed() });
          inp.value = ""; embedToast(res, "추가됨"); reload();
        } catch (err) { window.Toast.show("추가 실패: " + errMsg(err), "error"); }
      });

      reload();
    }

    // ── 질문 추가/수정/삭제 ──────────────────────────────────────
    function addQuestion() {
      openTextModal({
        title: "질문 추가", value: "", multiline: true, placeholder: "질문 내용",
        onSave: async (v) => {
          try {
            const res = await window.API.post("/api/nl2sql/questions", { question: v, embed_params: getEmbed() });
            embedToast(res, "질문이 추가되었습니다"); loadQuestions(); return true;
          } catch (err) { window.Toast.show("추가 실패: " + errMsg(err), "error"); return false; }
        },
      });
    }
    function editQuestion(row) {
      openTextModal({
        title: "질문 수정", value: row.question, multiline: true,
        onSave: async (v) => {
          try {
            const res = await window.API.put(`/api/nl2sql/questions/${row.id}`, { question: v, embed_params: getEmbed() });
            embedToast(res, "수정됨");
            if (row.id === selectedId) { selectedText = v; renderDetail(); }
            loadQuestions(); return true;
          } catch (err) { window.Toast.show("수정 실패: " + errMsg(err), "error"); return false; }
        },
      });
    }
    async function deleteQuestion(row) {
      if (!window.confirm(`질문을 삭제할까요? 연결된 조회컬럼·유사질문도 함께 삭제됩니다.\n\n${row.question}`)) return;
      try {
        await window.API.delete(`/api/nl2sql/questions/${row.id}`);
        window.Toast.show("삭제됨", "success");
        if (row.id === selectedId) { selectedId = null; selectedText = ""; renderDetail(); }
        loadQuestions();
      } catch (err) { window.Toast.show("삭제 실패: " + errMsg(err), "error"); }
    }

    qPanel.querySelector("#na-add-q").addEventListener("click", addQuestion);
    qPanel.querySelector("#na-search-btn").addEventListener("click", loadQuestions);
    searchEl.addEventListener("keydown", (e) => { if (e.key === "Enter") loadQuestions(); });

    loadQuestions();
  }

  window.Views = window.Views || {};
  window.Views.nl2sqlAdmin = render;
})();
