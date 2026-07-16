/** views/nl2sql.js — 메뉴 [Select AI Test - Table list].
 * Chat설정(AI Profile + User Prompt 템플릿)을 골라 질문/조회할 컬럼/정렬기준을 입력하고
 * Data요청을 누르면 백엔드(/api/nl2sql/run)가 DBMS_CLOUD_AI.GENERATE(action=>'showsql')로
 * SQL을 만들고 그 SELECT를 실행해 컬럼 헤더 + 데이터 행을 Table list에 렌더한다.
 * 결과는 Download(CSV)로 내려받을 수 있다.
 *
 * 자리표시자: ##메시지##(질문) / ##조회할 컬럼## / ##정렬기준## 를 입력값으로 치환.
 * 입력 3종은 각각 "저장할 제목 + 추가/수정 + 저장된 프롬프트" 콤보로 빠르게 채울 수 있다.
 */
(function () {
  const CONFIG_KEY = "nl2sql.savedConfigs";
  // 입력 필드별 저장 프롬프트 키 (DB별 격리는 Store 가 처리)
  const Q_KEY = "nl2sql.savedQuestions";
  const COL_KEY = "nl2sql.savedColumns";
  const SORT_KEY = "nl2sql.savedSorts";

  // 새 Chat설정 추가 시 기본 User Prompt (목업 예시 기준)
  const DEFAULT_USER_PROMPT =
    "[INSTRUCTION]\n" +
    ">기준일: ##기준일##\n" +
    ">결과형식\n" +
    "테이블 형태로 다음 컬럼을 추출\n" +
    "- ##조회할 컬럼##\n" +
    "정렬기준\n" +
    "- ##정렬기준##\n\n" +
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

  const loadConfigs = () => {
    try { return JSON.parse(window.Store.get(CONFIG_KEY)) || []; }
    catch (e) { return []; }
  };

  // 입력 필드 + (제목/추가/수정/콤보) 저장 프롬프트 콤보 연결.
  // shape: [{title, prompt}] — Profile Test 화면과 동일 규약.
  function wireSavedPrompts(key, inputEl, titleEl, addBtn, updBtn, delBtn, selEl) {
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
      if (!prompt.trim()) { window.Toast.show("내용이 비어 있습니다", "error"); return; }
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
      if (!prompt.trim()) { window.Toast.show("내용이 비어 있습니다", "error"); return; }
      const list = load();
      const idx = list.findIndex((p) => p.title === title);
      if (idx < 0) { window.Toast.show("저장된 항목을 찾을 수 없습니다", "error"); return; }
      list[idx].prompt = prompt;
      window.Store.set(key, JSON.stringify(list));
      window.Toast.show(`'${title}' 수정됨`, "success");
    });

    delBtn.addEventListener("click", () => {
      const title = selEl.value;
      if (!title) { window.Toast.show("삭제할 항목을 콤보에서 선택하세요", "error"); return; }
      if (!window.confirm(`저장된 프롬프트 '${title}' 를 삭제할까요?`)) return;
      const list = load().filter((p) => p.title !== title);
      window.Store.set(key, JSON.stringify(list));
      refresh("");   // 선택 초기화(입력값은 유지)
      window.Toast.show(`'${title}' 삭제됨`, "success");
    });

    selEl.addEventListener("change", () => {
      const title = selEl.value;
      if (!title) return;
      const found = load().find((p) => p.title === title);
      if (found) inputEl.value = found.prompt;
    });
  }

  // 필드 블록 HTML (라벨 + 저장 콤보 + 입력) — id 접두사로 구분
  // rows > 1 이면 여러 줄 textarea, 아니면 한 줄 input 으로 입력칸을 렌더한다.
  function fieldBlockHtml(prefix, label, placeholder, rows) {
    const field = rows && rows > 1
      ? `<textarea id="${prefix}-input" rows="${rows}" style="width:100%; resize:vertical; font-family:inherit;" placeholder="${placeholder}"></textarea>`
      : `<input type="text" id="${prefix}-input" style="width:100%;" placeholder="${placeholder}" />`;
    return `
      <div class="stack-sm">
        <div class="row" style="justify-content:space-between; gap:var(--space-2);">
          <label style="font-weight:600;">${label}</label>
          <div class="row" style="gap:var(--space-2);">
            <input type="text" id="${prefix}-title" placeholder="저장할 제목" style="width:120px;" />
            <button class="btn" id="${prefix}-add" type="button">추가</button>
            <button class="btn" id="${prefix}-update" type="button">수정</button>
            <button class="btn" id="${prefix}-delete" type="button">삭제</button>
            <select id="${prefix}-saved" style="min-width:140px;"></select>
          </div>
        </div>
        ${field}
      </div>
    `;
  }

  // ── prompt05: DB 모드 팝업(빌더 / 질문검색 / 컬럼선택·평가) ──────────────
  function divFromHtml(html) { const d = document.createElement("div"); d.innerHTML = html; return d.firstElementChild || d; }
  function modalBackdrop(html) {
    const bd = document.createElement("div"); bd.className = "modal-backdrop"; bd.innerHTML = html;
    const onKey = (e) => { if (e.key === "Escape") close(); };
    function close() { bd.remove(); document.removeEventListener("keydown", onKey); }
    bd._close = close;
    document.addEventListener("keydown", onKey);
    document.body.appendChild(bd);
    return bd;
  }

  // 질문선택 빌더 — 질문/조회컬럼을 정해 화면(qInput/colInput)으로 전달.
  function openQuestionBuilder(opts) {
    const st = { questionId: null };
    const curQ = (opts.qInput.value || "").trim();
    const parseCols = (v) => (v || "").split(",").map((s) => s.trim()).filter(Boolean);
    const bd = modalBackdrop(`
      <div class="modal" style="width:720px; max-width:95vw;">
        <div class="modal-header"><h2>질문 선택</h2><button class="btn btn-ghost" id="qb-close">✕</button></div>
        <div class="modal-body stack">
          <div class="stack-sm">
            <label style="font-size:var(--fs-sm);">질문</label>
            <div class="row" style="gap:6px;">
              <input type="text" id="qb-q" style="flex:1;" placeholder="질문을 입력하거나 검색에서 선택">
              <button class="btn" id="qb-q-search" type="button">질문 검색</button>
            </div>
          </div>
          <div class="stack-sm">
            <label style="font-size:var(--fs-sm);">조회할 컬럼</label>
            <div class="row" style="gap:6px;">
              <input type="text" id="qb-cols" style="flex:1;" placeholder="컬럼을 직접 입력(콤마 구분)하거나 컬럼 선택에서 지정">
              <button class="btn" id="qb-cols-pick" type="button">컬럼 선택</button>
            </div>
          </div>
        </div>
        <div class="modal-footer row end" style="gap:8px;">
          <button class="btn btn-ghost" id="qb-cancel" type="button">취소</button>
          <button class="btn btn-primary" id="qb-done" type="button">선택완료</button>
        </div>
      </div>`);
    const qEl = bd.querySelector("#qb-q"), colsEl = bd.querySelector("#qb-cols");
    qEl.value = curQ; colsEl.value = (opts.colInput.value || "").trim();
    qEl.addEventListener("input", () => { st.questionId = null; });  // 직접 편집 → 신규 질문
    bd.querySelector("#qb-close").addEventListener("click", () => bd._close());
    bd.querySelector("#qb-cancel").addEventListener("click", () => bd._close());
    bd.querySelector("#qb-q-search").addEventListener("click", () =>
      openQuestionSearch((picked) => { qEl.value = picked.question; st.questionId = picked.id; }));
    bd.querySelector("#qb-cols-pick").addEventListener("click", () => {
      const question = qEl.value.trim();
      if (!question) { window.Toast.show("질문을 먼저 입력/선택하세요", "warn"); return; }
      // 질문 자동 저장 없음 — 검색에서 고른 질문이면 st.questionId 로 그 질문의 컬럼을,
      // 아니면 '모든 조회칼럼' 으로 선택한다. (질문 등록은 '+ 새 질문 등록' 에서만)
      openColumnSelect({
        questionId: st.questionId, question, preselectedStr: colsEl.value, getProfile: opts.getProfile,
        onDone: (names) => { colsEl.value = names.join(", "); },
      });
    });
    bd.querySelector("#qb-done").addEventListener("click", () => {
      const question = qEl.value.trim();
      if (!question) { window.Toast.show("질문을 입력/선택하세요", "warn"); return; }
      // 질문 자동 저장 없음 — 화면에만 반영. (질문 등록은 '+ 새 질문 등록' 에서만)
      opts.qInput.value = question;
      opts.colInput.value = parseCols(colsEl.value).join(", ");
      opts.sortInput.value = "";  // DB 모드는 정렬기준 없음
      if (typeof opts.onDone === "function") opts.onDone();
      window.Toast.show("질문/컬럼을 화면에 반영했습니다", "success");
      bd._close();
    });
  }

  // 질문 검색 팝업 (text-like) + 새 질문 등록.
  function openQuestionSearch(onPick) {
    const bd = modalBackdrop(`
      <div class="modal" style="width:640px; max-width:95vw;">
        <div class="modal-header"><h2>질문 검색</h2><button class="btn btn-ghost" id="qs-close">✕</button></div>
        <div class="modal-body stack">
          <div class="row" style="gap:6px;">
            <input type="text" id="qs-search" style="flex:1;" placeholder="질문 검색어(부분일치) 또는 새 질문 내용">
            <button class="btn" id="qs-go" type="button">검색</button>
            <button class="btn btn-primary" id="qs-new" type="button">+ 새 질문 등록</button>
          </div>
          <div id="qs-list"></div>
        </div>
      </div>`);
    const search = bd.querySelector("#qs-search"), listEl = bd.querySelector("#qs-list");
    const load = async () => {
      const q = search.value.trim();
      listEl.innerHTML = '<div class="empty-state"><span class="spinner"></span> 조회 중...</div>';
      let rows;
      try { rows = await window.API.get("/api/nl2sql/questions" + (q ? "?q=" + encodeURIComponent(q) : "")); }
      catch (e) { listEl.innerHTML = `<div class="empty-state muted">${window.escapeHtml(errMsg(e, "질문 조회 실패"))}</div>`; return; }
      listEl.innerHTML = "";
      listEl.appendChild(window.SimpleTable.create(
        [
          { key: "id", label: "ID", headerAlign: "center", align: "center" },
          { key: "question", label: "질문" },
          { key: "_del", label: "", headerAlign: "center", align: "center", format: (_v, row) => {
              const btn = document.createElement("button");
              btn.className = "btn btn-primary"; btn.textContent = "삭제";
              btn.style.cssText = "padding:2px 10px; font-size:var(--fs-sm);";
              btn.addEventListener("click", async (e) => {
                e.stopPropagation();  // 행 선택과 분리
                if (!window.confirm(`질문 '${row.question}' 과(와) 연결된 조회컬럼을 모두 삭제할까요?`)) return;
                try { await window.API.delete(`/api/nl2sql/questions/${row.id}`); window.Toast.show("질문/연결 컬럼을 삭제했습니다", "success"); load(); }
                catch (err) { window.Toast.show(errMsg(err, "삭제 실패"), "error"); }
              });
              return btn;
            } },
        ],
        rows || [],
        { className: "keep-case", emptyText: "저장된 질문이 없습니다. [+ 새 질문 등록]으로 추가하세요.",
          onRowClick: (row) => { onPick({ id: row.id, question: row.question }); bd._close(); } }
      ));
    };
    bd.querySelector("#qs-close").addEventListener("click", () => bd._close());
    bd.querySelector("#qs-go").addEventListener("click", load);
    search.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); load(); } });
    bd.querySelector("#qs-new").addEventListener("click", async () => {
      const question = search.value.trim();
      if (!question) { window.Toast.show("등록할 질문 내용을 입력하세요", "warn"); return; }
      try { const r = await window.API.post("/api/nl2sql/questions", { question }); onPick({ id: r.id, question: r.question }); bd._close(); window.Toast.show("질문을 등록했습니다", "success"); }
      catch (e) { window.Toast.show(errMsg(e, "질문 등록 실패"), "error"); }
    });
    // 팝업 열릴 때 자동 조회하지 않음 — [검색] 또는 Enter 로만 조회.
    listEl.innerHTML = '<div class="empty-state muted">검색어를 입력하고 [검색]을 누르세요. (전체를 보려면 빈 상태로 검색)</div>';
    search.focus();
  }

  // 컬럼 선택 팝업 — 질문 컬럼/전체(모든 조회칼럼), 추가, 관련성 평가.
  function openColumnSelect(opts) {
    // Tool관리 하위 옵션 — '질문-조회컬럼 관련성평가' 가 켜져 있을 때만 평가 UI 노출.
    const evalOn = !!(window.MenuConfig && window.MenuConfig.isColEvalOn && window.MenuConfig.isColEvalOn());
    // 이전 선택 원본 문자열(쉼표 분해 없이 DB 항목 원자 단위로 매칭). '모든 조회칼럼' 기본 uncheck.
    const preStr = (opts.preselectedStr || "").trim();
    const bd = modalBackdrop(`
      <div class="modal" style="width:760px; max-width:95vw;">
        <div class="modal-header"><h2>컬럼 선택</h2><button class="btn btn-ghost" id="cs-close">✕</button></div>
        <div class="modal-body stack">
          <label class="row" style="gap:6px; align-items:center; cursor:pointer;">
            <input type="checkbox" id="cs-all"> 모든 조회칼럼 (질문 상관없이 전체)
          </label>
          <div class="row" style="gap:6px;">
            <input type="text" id="cs-new" style="flex:1;" placeholder="새 컬럼명 추가">
            <button class="btn" id="cs-add" type="button">추가</button>
          </div>
          <div id="cs-list" style="max-height:220px; overflow:auto;"></div>
          ${evalOn ? `
          <div class="row" style="gap:8px; align-items:center;">
            <button class="btn" id="cs-eval" type="button" disabled>관련성 평가</button>
            <span class="muted" style="font-size:var(--fs-sm);">'모든 조회칼럼' 선택 후 컬럼을 고르면 질문과의 관련성을 평가합니다</span>
          </div>
          <div id="cs-eval-out"></div>` : ""}
        </div>
        <div class="modal-footer row end" style="gap:8px;">
          <button class="btn btn-ghost" id="cs-cancel" type="button">취소</button>
          <button class="btn btn-primary" id="cs-done" type="button">선택완료</button>
        </div>
      </div>`);
    const allChk = bd.querySelector("#cs-all"), listEl = bd.querySelector("#cs-list");
    const evalBtn = bd.querySelector("#cs-eval"), evalOut = bd.querySelector("#cs-eval-out");
    const checkedSet = new Set();
    const seen = new Set();  // preStr 자동복원을 이미 적용한 컬럼(사용자 수동해제 보존)
    // 이전 선택 문자열에 '하나의 항목으로' 들어있는 DB 컬럼만 매칭(쉼표로 쪼개지 않고 원자 단위).
    const isSel = (n) => !!preStr && (preStr === n || preStr.startsWith(n + ", ") || preStr.endsWith(", " + n) || preStr.indexOf(", " + n + ", ") >= 0);
    const visibleChecked = () => Array.from(listEl.querySelectorAll('input[type="checkbox"]:checked')).map((c) => c.value);
    const syncEvalBtn = () => { if (evalBtn) evalBtn.disabled = !(allChk.checked && visibleChecked().length > 0); };
    const render = (rows) => {
      listEl.innerHTML = "";
      // DB에서 조회된 컬럼만 표시(쉼표 분해로 만든 조각은 넣지 않음).
      const loaded = (rows || []).map((r) => r.column_name).filter(Boolean);
      // 처음 등장한 DB 컬럼 중 이전 선택 문자열에 포함된 것만 체크 복원(수동 변경은 보존).
      loaded.forEach((n) => { if (!seen.has(n)) { seen.add(n); if (isSel(n)) checkedSet.add(n); } });
      if (!loaded.length) { listEl.innerHTML = "<div class=\"empty-state muted\">등록된 컬럼이 없습니다. 위에서 추가하거나 '모든 조회칼럼'을 켜세요.</div>"; syncEvalBtn(); return; }
      loaded.forEach((n) => {
        const row = document.createElement("label");
        row.className = "row"; row.style.cssText = "gap:8px; align-items:center; padding:2px 0; cursor:pointer;";
        const cb = document.createElement("input"); cb.type = "checkbox"; cb.value = n; cb.checked = checkedSet.has(n);
        cb.addEventListener("change", () => { cb.checked ? checkedSet.add(n) : checkedSet.delete(n); syncEvalBtn(); });
        const sp = document.createElement("span"); sp.textContent = n;
        row.appendChild(cb); row.appendChild(sp); listEl.appendChild(row);
      });
      syncEvalBtn();
    };
    const load = async () => {
      listEl.innerHTML = '<div class="empty-state"><span class="spinner"></span> 조회 중...</div>';
      const url = allChk.checked ? "/api/nl2sql/columns"
        : (opts.questionId != null ? `/api/nl2sql/questions/${opts.questionId}/columns` : null);
      if (!url) { render([]); return; }
      let rows;
      try { rows = await window.API.get(url); }
      catch (e) { listEl.innerHTML = `<div class="empty-state muted">${window.escapeHtml(errMsg(e, "컬럼 조회 실패"))}</div>`; return; }
      render(rows);
    };
    allChk.addEventListener("change", () => { if (evalOut) evalOut.innerHTML = ""; load(); });
    bd.querySelector("#cs-add").addEventListener("click", async () => {
      const name = bd.querySelector("#cs-new").value.trim();
      if (!name) { window.Toast.show("컬럼명을 입력하세요", "warn"); return; }
      try { await window.API.post("/api/nl2sql/columns", { question_id: opts.questionId, column_name: name }); }
      catch (e) { window.Toast.show(errMsg(e, "컬럼 추가 실패"), "error"); return; }
      checkedSet.add(name); bd.querySelector("#cs-new").value = "";
      window.Toast.show("컬럼을 추가했습니다", "success"); load();
    });
    if (evalBtn) evalBtn.addEventListener("click", async () => {
      const cols = visibleChecked();
      const profile = opts.getProfile ? opts.getProfile() : "";
      if (!profile) { window.Toast.show("Chat설정에서 AI Profile 을 선택하세요", "warn"); return; }
      evalBtn.disabled = true; const old = evalBtn.textContent; evalBtn.innerHTML = '<span class="spinner"></span> 평가 중...';
      evalOut.innerHTML = '<div class="empty-state"><span class="spinner"></span> 심사 중...</div>';
      let res;
      try { res = await window.API.post("/api/nl2sql/columns/evaluate", { profile, question: opts.question, columns: cols }); }
      catch (e) { evalOut.innerHTML = `<div class="empty-state muted">${window.escapeHtml(errMsg(e, "평가 실패"))}</div>`; evalBtn.textContent = old; syncEvalBtn(); return; }
      // 평가 결과는 팝업 하단 영역(#cs-eval-out)에만 렌더 — 메인 화면은 건드리지 않음.
      // 영역을 스크롤 고정해 결과가 길어도 팝업 상단(체크박스 목록)이 밀리지 않게 한다.
      evalOut.innerHTML = "";
      evalOut.style.cssText = "margin-top:6px; max-height:320px; overflow:auto;";
      if (res.error) { evalOut.appendChild(divFromHtml(`<div class="empty-state muted">${window.escapeHtml(res.error)}</div>`)); }
      else {
        evalOut.appendChild(window.SimpleTable.create(
          [{ key: "name", label: "컬럼" },
           { key: (r) => (r.relevant === true ? "관련" : r.relevant === false ? "무관" : "미판정"), label: "판정", headerAlign: "center", align: "center" },
           { key: "reason", label: "사유" }],
          res.columns || [], { className: "keep-case", emptyText: "평가 결과 없음" }));
        if (res.summary) evalOut.appendChild(divFromHtml(`<div class="muted" style="font-size:var(--fs-sm); margin-top:6px; white-space:pre-wrap;">${window.escapeHtml(res.summary)}</div>`));
      }
      // 평가에 사용한 프롬프트(스키마 컨텍스트 포함) — 접이식
      evalOut.appendChild(divFromHtml(`
        <details style="margin-top:8px;">
          <summary style="cursor:pointer; font-size:var(--fs-sm); color:var(--text-muted);">평가에 사용한 프롬프트 보기</summary>
          <pre style="white-space:pre-wrap; word-break:break-word; margin:6px 0 0; font-family:var(--font-mono); font-size:var(--fs-sm); background:var(--surface-alt); padding:var(--space-2) var(--space-3); border-radius:var(--radius-md); max-height:260px; overflow:auto;">${window.escapeHtml(res.eval_prompt || "—")}</pre>
        </details>`));
      evalBtn.textContent = old; syncEvalBtn();
    });
    bd.querySelector("#cs-close").addEventListener("click", () => bd._close());
    bd.querySelector("#cs-cancel").addEventListener("click", () => bd._close());
    bd.querySelector("#cs-done").addEventListener("click", () => {
      if (typeof opts.onDone === "function") opts.onDone(Array.from(checkedSet));
      bd._close();
    });
    load();
  }

  // comment추천 — 직전 실행(생성 SQL·질문·컬럼) + 목표 SQL 로 comment/annotation 개선 분석.
  function openCommentRecommend(run) {
    const bd = modalBackdrop(`
      <div class="modal" style="width:900px; max-width:95vw;">
        <div class="modal-header"><h2>comment 추천 <span class="muted" style="font-size:var(--fs-sm);">comment/annotation 개선 분석</span></h2>
          <button class="btn btn-ghost" id="cr-close">✕</button></div>
        <div class="modal-body stack">
          <div class="muted" style="font-size:var(--fs-sm);">직전 [실행]의 생성 SQL·질문을 기준으로, 아래 <b>생성되어야 할 SQL</b> 처럼 나오게 하려면 comment/annotation 을 어떻게 고쳐야 하는지 분석합니다.</div>
          <div class="stack-sm">
            <label style="font-size:var(--fs-sm);">직전 생성 SQL (showsql 결과)</label>
            <pre style="white-space:pre; margin:0; font-family:var(--font-mono); font-size:var(--fs-sm); background:var(--surface-alt); padding:var(--space-2) var(--space-3); border-radius:var(--radius-md); max-height:180px; overflow:auto;">${window.escapeHtml(run.sql || "—")}</pre>
          </div>
          <div class="stack-sm">
            <label style="font-size:var(--fs-sm);">생성되어야 할 SQL (고객 목표)</label>
            <textarea id="cr-desired" rows="8" style="width:100%; font-family:var(--font-mono); font-size:var(--fs-sm);" placeholder="고객이 원하는 SQL 을 붙여넣으세요"></textarea>
          </div>
          <div class="row" style="justify-content:flex-end;"><button class="btn btn-primary" id="cr-run" type="button">분석</button></div>
          <details id="cr-prompt" style="margin-top:4px;">
            <summary style="cursor:pointer; font-size:var(--fs-sm); color:var(--text-muted);">분석 실행 프롬프트 보기</summary>
            <pre id="cr-prompt-pre" style="white-space:pre-wrap; word-break:break-word; margin:6px 0 0; font-family:var(--font-mono); font-size:var(--fs-sm); background:var(--surface-alt); padding:var(--space-2) var(--space-3); border-radius:var(--radius-md); max-height:300px; overflow:auto;">분석을 실행하면 여기에 표시됩니다.</pre>
          </details>
          <div id="cr-out"></div>
        </div>
        <div class="modal-footer row end"><button class="btn btn-ghost" id="cr-close2" type="button">닫기</button></div>
      </div>`);
    bd.querySelector("#cr-close").addEventListener("click", () => bd._close());
    bd.querySelector("#cr-close2").addEventListener("click", () => bd._close());
    const out = bd.querySelector("#cr-out");
    bd.querySelector("#cr-run").addEventListener("click", async () => {
      const desired = bd.querySelector("#cr-desired").value.trim();
      if (!desired) { window.Toast.show("생성되어야 할 SQL 을 입력하세요", "warn"); return; }
      if (!run.profile) { window.Toast.show("Chat설정에 AI Profile 이 없습니다", "warn"); return; }
      const btn = bd.querySelector("#cr-run"); btn.disabled = true; const old = btn.textContent; btn.innerHTML = '<span class="spinner"></span> 분석 중...';
      out.innerHTML = '<div class="empty-state"><span class="spinner"></span> 분석 중... (showprompt + LLM)</div>';
      let res;
      try {
        res = await window.API.post("/api/nl2sql/comment-recommend", {
          profile: run.profile, user_prompt: run.user_prompt, message: run.message,
          columns: run.columns, sort_by: run.sort_by, generated_sql: run.sql, desired_sql: desired,
        });
      } catch (e) { out.innerHTML = `<div class="empty-state muted">${window.escapeHtml(errMsg(e, "분석 실패"))}</div>`; btn.disabled = false; btn.textContent = old; return; }
      out.innerHTML = "";
      if (res.error) out.appendChild(divFromHtml(`<div class="empty-state muted">${window.escapeHtml(res.error)}</div>`));
      if (res.analysis) {
        out.appendChild(divFromHtml(`<label style="display:block; font-weight:600; margin:4px 0 6px;">분석 결과${res.model ? ` <span class="muted" style="font-size:var(--fs-sm);">(사용LLM: ${window.escapeHtml(res.model)})</span>` : ""}</label>`));
        out.appendChild(divFromHtml(`<div style="white-space:pre-wrap; word-break:break-word; background:var(--surface-alt); padding:var(--space-3); border-radius:var(--radius-md); max-height:50vh; overflow:auto;">${window.escapeHtml(res.analysis)}</div>`));
      }
      // 실행 프롬프트는 팝업 하단의 전용 접이식(#cr-prompt)에 채운다(default 접힘 유지).
      const promptPre = bd.querySelector("#cr-prompt-pre");
      if (promptPre) promptPre.textContent = res.analysis_prompt || "—";
      btn.disabled = false; btn.textContent = old;
    });
  }

  async function render() {
    const main = document.getElementById("main");
    main.innerHTML = "";

    const title = document.createElement("div");
    title.className = "view-title";
    title.innerHTML = `<h1>Select AI Test - Table list</h1>
      <span class="sub">질문을 SQL로 변환/실행해 표로 조회합니다</span>`;
    main.appendChild(title);

    const panel = document.createElement("div");
    panel.className = "stack";
    panel.innerHTML = `
      <div class="row">
        <label style="width:90px;">Chat설정</label>
        <select id="nl-config" style="min-width:220px;"></select>
        <button class="btn" id="nl-config-add" type="button">추가</button>
        <button class="btn" id="nl-config-update" type="button">수정</button>
      </div>
      <div class="row" style="align-items:center;">
        <label style="width:90px;">질문관리방식</label>
        <label style="display:flex; align-items:center; gap:4px; cursor:pointer;"><input type="radio" name="nl-qsource" value="local"> local storage</label>
        <label style="display:flex; align-items:center; gap:4px; cursor:pointer;"><input type="radio" name="nl-qsource" value="db"> DB</label>
      </div>
      <div class="row" style="align-items:stretch; gap:var(--space-4);">
        <div class="stack" style="flex:1;">
          <div class="row" style="gap:8px;">
            <button class="btn" id="nl-comment-rec" type="button">comment추천</button>
            <button class="btn btn-primary" id="nl-db-pick" type="button">질문 선택</button>
          </div>
          <div id="nl-local-fields" class="stack">
            ${fieldBlockHtml("nl-q", "질문", "질문입력", 3)}
            ${fieldBlockHtml("nl-cols", "조회할 컬럼", "예시: 판매일자, 나이, 브랜드, 채널, 사용 쿠폰, 등급, 제품코드, 제품명")}
            ${fieldBlockHtml("nl-sort", "정렬기준", "예시: 판매일자(오름차순), 나이(내림차순)")}
          </div>
          <div id="nl-db-fields" class="stack" style="display:none;">
            <div class="stack-sm">
              <label style="font-size:var(--fs-sm);">질문 <span class="muted" style="font-size:11.5px;">([질문 선택]으로 채우거나 직접 입력 가능)</span></label>
              <textarea id="nl-db-q" rows="3" style="width:100%; resize:vertical; font-family:inherit;" placeholder="질문입력"></textarea>
            </div>
            <div class="stack-sm">
              <label style="font-size:var(--fs-sm);">조회할 컬럼 <span class="muted" style="font-size:11.5px;">(직접 입력 가능)</span></label>
              <input type="text" id="nl-db-cols" style="width:100%;" placeholder="예시: 판매일자, 나이, 브랜드, 채널">
            </div>
          </div>
        </div>
        <div style="display:flex; min-width:130px;">
          <button class="btn btn-primary" id="nl-run" type="button" style="flex:1; min-width:120px; font-size:2em; display:flex; align-items:center; justify-content:center; text-align:center;">실행</button>
        </div>
      </div>
      <label style="font-weight:600;">답변</label>
      <div id="nl-sql-area"></div>
      <div class="row" id="nl-download-bar" style="display:none; justify-content:space-between; align-items:center;">
        <span id="nl-timing" class="muted" style="font-size:var(--fs-sm);"></span>
        <div class="row" style="gap:var(--space-3); align-items:center;">
          <button class="btn btn-ai-test" id="nl-analyze" type="button" style="display:none;">AI분석</button>
          <button class="btn btn-ai-test" id="nl-persona-manage" type="button" style="display:none;">페르소나 관리</button>
          <a id="nl-download" role="button" tabindex="0" style="color:#0066cc; text-decoration:underline; cursor:pointer; display:none;">Download</a>
        </div>
      </div>
      <div id="nl-result"><div class="empty-state muted">Chat설정을 선택하고 질문을 입력한 뒤 Data요청을 누르세요.</div></div>
    `;
    main.appendChild(panel);

    const configSel = panel.querySelector("#nl-config");
    const sqlArea = panel.querySelector("#nl-sql-area");
    const resultArea = panel.querySelector("#nl-result");

    // 최근 결과(다운로드용)
    let lastResult = null;
    let lastRun = null;   // comment추천 용 — 직전 실행의 { profile, user_prompt, message, columns, sort_by, sql }

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

    panel.querySelector("#nl-config-add").addEventListener("click", () => {
      openConfigModal("add", { name: "", profile: "", userPrompt: DEFAULT_USER_PROMPT, mode: "dbms_cloud_ai" }, refreshConfigs);
    });
    panel.querySelector("#nl-config-update").addEventListener("click", () => {
      const name = configSel.value;
      if (!name) { window.Toast.show("수정할 설정을 선택하세요", "error"); return; }
      const found = loadConfigs().find((c) => c.name === name);
      if (!found) { window.Toast.show("저장된 설정을 찾을 수 없습니다", "error"); return; }
      openConfigModal("edit", found, refreshConfigs);
    });

    // 필드별 저장 프롬프트 콤보 연결
    const qInput = panel.querySelector("#nl-q-input");
    const colInput = panel.querySelector("#nl-cols-input");
    const sortInput = panel.querySelector("#nl-sort-input");
    wireSavedPrompts(Q_KEY, qInput, panel.querySelector("#nl-q-title"),
      panel.querySelector("#nl-q-add"), panel.querySelector("#nl-q-update"),
      panel.querySelector("#nl-q-delete"), panel.querySelector("#nl-q-saved"));
    wireSavedPrompts(COL_KEY, colInput, panel.querySelector("#nl-cols-title"),
      panel.querySelector("#nl-cols-add"), panel.querySelector("#nl-cols-update"),
      panel.querySelector("#nl-cols-delete"), panel.querySelector("#nl-cols-saved"));
    wireSavedPrompts(SORT_KEY, sortInput, panel.querySelector("#nl-sort-title"),
      panel.querySelector("#nl-sort-add"), panel.querySelector("#nl-sort-update"),
      panel.querySelector("#nl-sort-delete"), panel.querySelector("#nl-sort-saved"));

    // ── prompt05: 질문관리방식(local/DB) 라디오 + DB 모드 빌더 ──
    const QSRC_KEY = "nl2sql.questionSource";  // Store(DB별)
    const dbQ = panel.querySelector("#nl-db-q"), dbCols = panel.querySelector("#nl-db-cols");
    // 빌더/전환 시 소스(qInput·colInput) → DB 모드 입력란으로 반영
    const refreshDbSummary = () => { dbQ.value = qInput.value; dbCols.value = colInput.value; };
    // DB 모드 입력란 직접 편집 → 소스에 반영(runQuery 는 qInput/colInput 을 읽음)
    dbQ.addEventListener("input", () => { qInput.value = dbQ.value; sortInput.value = ""; });
    dbCols.addEventListener("input", () => { colInput.value = dbCols.value; });
    const applyQSource = (src) => {
      const isDb = src === "db";
      panel.querySelector("#nl-local-fields").style.display = isDb ? "none" : "";
      panel.querySelector("#nl-db-fields").style.display = isDb ? "" : "none";
      panel.querySelector("#nl-db-pick").style.display = isDb ? "" : "none";  // 질문선택은 DB 모드만
      if (isDb) refreshDbSummary();
    };
    const savedSrc = window.Store.get(QSRC_KEY) || "local";
    panel.querySelectorAll('input[name="nl-qsource"]').forEach((r) => {
      r.checked = r.value === savedSrc;
      r.addEventListener("change", () => { if (r.checked) { window.Store.set(QSRC_KEY, r.value); applyQSource(r.value); } });
    });
    applyQSource(savedSrc);
    panel.querySelector("#nl-db-pick").addEventListener("click", () => openQuestionBuilder({
      qInput, colInput, sortInput,
      getProfile: () => { const c = loadConfigs().find((x) => x.name === configSel.value); return (c && c.profile) || ""; },
      onDone: refreshDbSummary,
    }));
    panel.querySelector("#nl-comment-rec").addEventListener("click", () => {
      if (!lastRun || !lastRun.sql) { window.Toast.show("먼저 [실행]으로 SQL 을 생성하세요", "warn"); return; }
      openCommentRecommend(lastRun);
    });

    const downloadBar = panel.querySelector("#nl-download-bar");
    const timingEl = panel.querySelector("#nl-timing");
    const downloadLink = panel.querySelector("#nl-download");
    const analyzeBtn = panel.querySelector("#nl-analyze");
    const personaBtn = panel.querySelector("#nl-persona-manage");
    panel.querySelector("#nl-run").addEventListener("click", async () => {
      // 실행 시작 시점의 질문/컬럼/정렬 스냅샷(comment추천 재사용용)
      const snap = { message: qInput.value.trim(), columns: colInput.value, sort_by: sortInput.value, cfgName: configSel.value };
      const res = await runQuery(configSel, qInput, colInput, sortInput, sqlArea, resultArea);
      lastResult = res;
      if (res && res.sql) {
        const cfg = loadConfigs().find((c) => c.name === snap.cfgName);
        lastRun = { profile: cfg && cfg.profile, user_prompt: (cfg && cfg.userPrompt) || "",
          message: snap.message, columns: snap.columns, sort_by: snap.sort_by, sql: res.sql };
      }
      // 실행 시간표 + AI분석 + Download (조회 결과가 있을 때만 표시)
      if (res && res.total_ms != null) {
        timingEl.textContent = fmtTiming(res);
        const hasRows = (res.rows || []).length > 0;
        // AI분석/페르소나 관리 버튼은 Tool관리 메뉴관리의 'AI분석' 하위옵션이 켜져 있을 때만 노출.
        const analyzeOn = !window.MenuConfig || !window.MenuConfig.isAnalyzeOn || window.MenuConfig.isAnalyzeOn();
        analyzeBtn.style.display = (hasRows && analyzeOn) ? "" : "none";
        personaBtn.style.display = (hasRows && analyzeOn) ? "" : "none";
        downloadLink.style.display = hasRows ? "" : "none";
        downloadBar.style.display = "flex";
      } else {
        downloadBar.style.display = "none";
      }
    });

    // AI분석 — 직전 생성 SQL 로 최대 100행을 조회해 페르소나 프롬프트와 함께 LLM 분석.
    analyzeBtn.addEventListener("click", () => {
      openAnalyzeModal(lastResult);
    });

    // 페르소나 관리 — AI분석 팝업을 열지 않고도 바로 페르소나 CRUD 팝업을 연다.
    personaBtn.addEventListener("click", () => {
      openPersonaManageModal(() => {});
    });

    // Download — 표시용 100행이 아니라 SQL 을 다시 실행해 전체 row 를 CSV 로 받는다.
    panel.querySelector("#nl-download").addEventListener("click", async () => {
      if (!lastResult || !lastResult.sql) {
        window.Toast.show("다운로드할 데이터가 없습니다", "error");
        return;
      }
      const orig = downloadLink.textContent;
      downloadLink.textContent = "전체 조회 중…";
      downloadLink.style.pointerEvents = "none";
      try {
        const exp = await window.API.post("/api/nl2sql/export", { sql: lastResult.sql });
        if (!exp || !(exp.rows || []).length) {
          window.Toast.show("다운로드할 데이터가 없습니다", "error");
          return;
        }
        downloadCsv(exp.columns, exp.rows, (configSel.value || "table_list"));
      } catch (err) {
        window.Toast.show(errMsg(err, "다운로드 실패"), "error");
      } finally {
        downloadLink.textContent = orig;
        downloadLink.style.pointerEvents = "";
      }
    });
  }

  // 실행 시간표 문자열 — "총시간 X ms (SQL생성 Y ms, SQL실행 Z ms)"
  function fmtTiming(res) {
    const ms = (v) => (v == null ? "-" : Number(v).toLocaleString() + " ms");
    return `총시간 ${ms(res.total_ms)} (SQL생성 ${ms(res.gen_ms)}, SQL실행 ${ms(res.exec_ms)})`;
  }

  // 실행 — 요청 완료 시 응답 객체(res) 반환(시간표/다운로드용), 요청 전 검증/네트워크 실패 시 null
  async function runQuery(configSel, qInput, colInput, sortInput, sqlArea, resultArea) {
    const name = configSel.value;
    if (!name) { window.Toast.show("Chat설정을 선택하세요", "error"); return null; }
    const cfg = loadConfigs().find((c) => c.name === name);
    if (!cfg) { window.Toast.show("저장된 설정을 찾을 수 없습니다", "error"); return null; }
    if (!cfg.profile) { window.Toast.show("설정에 AI Profile이 없습니다 — 수정에서 지정하세요", "error"); return null; }

    const message = qInput.value.trim();
    if (!message) { window.Toast.show("질문을 입력하세요", "error"); return null; }
    const columns = colInput.value;
    if (!columns.trim()) { window.Toast.show("조회할 컬럼을 입력하세요", "error"); return null; }
    const sort_by = sortInput.value;

    const runBtn = document.getElementById("nl-run");
    runBtn.disabled = true;
    sqlArea.innerHTML = "";
    resultArea.innerHTML = `<div class="empty-state muted">실행 중…</div>`;

    let res;
    try {
      res = await window.API.post("/api/nl2sql/run", {
        profile_name: cfg.profile, user_prompt: cfg.userPrompt || "",
        message, columns, sort_by, mode: cfg.mode || "dbms_cloud_ai",
      });
    } catch (err) {
      resultArea.innerHTML = "";
      resultArea.appendChild(errBox(errMsg(err, "Data요청 실패")));
      return null;
    } finally {
      runBtn.disabled = false;
    }

    // 생성된 SQL 표시 (있으면) — 접이식, 기본 접힘(open 미설정)
    sqlArea.innerHTML = "";
    if (res.sql) {
      const det = document.createElement("details");
      det.style.position = "relative";
      const sum = document.createElement("summary");
      sum.className = "muted";
      sum.style.fontSize = "var(--fs-sm)";
      sum.style.cursor = "pointer";
      sum.textContent = "생성된 SQL";
      // 오른쪽 상단 SQL 복사 버튼 (summary 클릭으로 접힘 토글되지 않도록 이벤트 차단)
      const copyBtn = document.createElement("button");
      copyBtn.className = "btn";
      copyBtn.type = "button";
      copyBtn.textContent = "Copy";
      copyBtn.style.position = "absolute";
      copyBtn.style.top = "0";
      copyBtn.style.right = "0";
      copyBtn.style.fontSize = "var(--fs-sm)";
      copyBtn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        navigator.clipboard.writeText(res.sql).then(
          () => window.Toast.show("SQL 복사됨", "success"),
          () => window.Toast.show("복사 실패", "error")
        );
      });
      const pre = document.createElement("pre");
      pre.style.whiteSpace = "pre-wrap";
      pre.textContent = res.sql;
      det.appendChild(sum);
      det.appendChild(copyBtn);
      det.appendChild(pre);
      sqlArea.appendChild(det);
    }

    resultArea.innerHTML = "";
    if (res.error) {
      resultArea.appendChild(errBox(res.error));
      return res;
    }
    const cols = (res.columns || []).map((nm, i) => ({ key: (row) => row[i], label: nm }));
    if (res.truncated) {
      const note = document.createElement("div");
      note.className = "muted";
      note.style.fontSize = "var(--fs-sm)";
      note.style.marginBottom = "var(--space-2)";
      note.textContent = "※ 처음 100행만 표시합니다. (전체는 Download)";
      resultArea.appendChild(note);
    }
    const table = window.SimpleTable.create(cols, res.rows || [], { emptyText: "결과가 없습니다" });
    resultArea.appendChild(table);
    return res;
  }

  function errBox(msg) {
    const d = document.createElement("div");
    d.className = "empty-state";
    d.style.color = "var(--danger, #c74634)";
    d.style.whiteSpace = "pre-wrap";
    d.textContent = msg;
    return d;
  }

  // 결과 테이블 → CSV 다운로드 (Excel 호환 위해 BOM 추가)
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
    a.download = (baseName || "table_list").replace(/[^\w가-힣.-]+/g, "_") + ".csv";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  // Chat설정 입력/수정 팝업. mode='add'|'edit', cfg={name,profile,userPrompt}
  async function openConfigModal(mode, cfg, onSaved) {
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
            <label>AI Profile</label>
            <select id="cfg-profile"></select>
          </div>
          <div class="stack-sm">
            <label>호출Mode</label>
            <div class="row" style="gap:var(--space-4);">
              <label style="font-weight:400; display:flex; align-items:center; gap:6px; cursor:pointer;">
                <input type="radio" name="cfg-mode" value="dbms_cloud_ai"> dbms_cloud_ai
              </label>
              <label style="font-weight:400; display:flex; align-items:center; gap:6px; cursor:pointer;">
                <input type="radio" name="cfg-mode" value="select_ai"> select ai
              </label>
            </div>
          </div>
          <div class="stack-sm">
            <label>User Prompt</label>
            <textarea id="cfg-prompt" rows="10" style="font-family:var(--font-mono); font-size:var(--fs-sm);"></textarea>
            <span class="muted" style="font-size:var(--fs-sm); line-height:1.7;">
              자리표시자 — 실행 시 자동 치환됩니다:<br>
              · <code>##기준일##</code> : 실행 시점의 오늘 날짜(YYYYMMDD)<br>
              · <code>##조회할 컬럼##</code> : 화면의 <b>조회할 컬럼</b> 입력값<br>
              · <code>##정렬기준##</code> : 화면의 <b>정렬기준</b> 입력값<br>
              · <code>##메시지##</code> : 화면의 <b>질문</b> 입력값 <span class="muted">(필수 — 프롬프트에 반드시 포함)</span>
            </span>
          </div>
        </div>
        <div class="modal-footer row" style="justify-content:space-between; align-items:center; gap:var(--space-2);">
          <a id="cfg-script" role="button" tabindex="0" style="color:#0066cc; text-decoration:underline; cursor:pointer; font-size:var(--fs-sm);">script 보기</a>
          <div class="row" style="gap:var(--space-2);">
            <button class="btn" id="cfg-cancel" type="button">취소</button>
            <button class="btn btn-primary" id="cfg-save" type="button">저장</button>
          </div>
        </div>
      </div>
    `;
    const close = () => { backdrop.remove(); document.removeEventListener("keydown", onKey); };
    const onKey = (e) => { if (e.key === "Escape") close(); };
    document.addEventListener("keydown", onKey);
    document.body.appendChild(backdrop);

    const nameEl = backdrop.querySelector("#cfg-name");
    const profileSel = backdrop.querySelector("#cfg-profile");
    const promptEl = backdrop.querySelector("#cfg-prompt");
    nameEl.value = cfg.name || "";
    promptEl.value = cfg.userPrompt || "";

    // 호출Mode 라디오 — 저장값(없으면 dbms_cloud_ai) 반영. getMode()로 현재 선택 읽음.
    const initMode = cfg.mode === "select_ai" ? "select_ai" : "dbms_cloud_ai";
    const modeRadio = backdrop.querySelector(`input[name="cfg-mode"][value="${initMode}"]`);
    if (modeRadio) modeRadio.checked = true;
    const getMode = () =>
      (backdrop.querySelector('input[name="cfg-mode"]:checked') || {}).value || "dbms_cloud_ai";

    // AI Profile 드롭다운 — ENABLED 만. 현재 값이 목록에 없으면 보존.
    profileSel.innerHTML = `<option value="">불러오는 중…</option>`;
    try {
      const profiles = await window.API.get("/api/profiles");
      const enabled = (profiles || []).filter((p) => p.status === "ENABLED");
      profileSel.innerHTML = "";
      const names = enabled.map((p) => p.profile_name);
      if (cfg.profile && !names.includes(cfg.profile)) names.unshift(cfg.profile);
      if (names.length === 0) {
        profileSel.innerHTML = `<option value="">사용 가능한 Profile이 없습니다</option>`;
      } else {
        names.forEach((nm) => {
          const o = document.createElement("option");
          o.value = nm; o.textContent = nm;
          profileSel.appendChild(o);
        });
      }
      profileSel.value = cfg.profile || (names[0] || "");
    } catch (e) {
      profileSel.innerHTML = "";
      const o = document.createElement("option");
      o.value = cfg.profile || "";
      o.textContent = cfg.profile || "Profile 목록 로드 실패";
      profileSel.appendChild(o);
      profileSel.value = cfg.profile || "";
    }

    backdrop.querySelector("#cfg-close").addEventListener("click", close);
    backdrop.querySelector("#cfg-cancel").addEventListener("click", close);

    // script 보기 — 이 Chat설정(Profile + User Prompt)으로 실행되는 DB 스크립트를 팝업으로.
    backdrop.querySelector("#cfg-script").addEventListener("click", () => {
      const profile = profileSel.value || "<AI Profile 미선택>";
      const commonNote =
        "-- ##조회할 컬럼##, ##정렬기준##, ##메시지## 는 실행 시 화면 입력값으로 치환됩니다.\n" +
        "-- ##기준일## 은 실행 시 오늘 날짜(YYYYMMDD)로 자동 치환됩니다.\n";
      let script;
      if (getMode() === "select_ai") {
        script =
          "-- Select AI Test - Table list 실행 스크립트 (호출Mode: select ai)\n" +
          commonNote +
          "EXEC DBMS_CLOUD_AI.SET_PROFILE('" + profile + "');\n" +
          "select ai showsql \n" +
          '"' + (promptEl.value || "") + '"\n' +
          "-- 위 select ai showsql 이 생성한 SELECT 문을 앱이 실행해 결과(최대 100행)를 표시합니다.";
      } else {
        // q-quote 리터럴(q'~ … ~') — 내부 작은따옴표를 '' 로 이스케이프할 필요가 없다.
        const lit = "q'~" + (promptEl.value || "") + "~'";
        script =
          "-- Select AI Test - Table list 실행 스크립트 (호출Mode: dbms_cloud_ai)\n" +
          commonNote +
          "SELECT DBMS_CLOUD_AI.GENERATE(\n" +
          "         prompt       => " + lit + ",\n" +
          "         profile_name => '" + profile + "',\n" +
          "         action       => 'showsql'\n" +
          "       ) AS r\n" +
          "FROM dual;\n" +
          "-- 위에서 생성된 SELECT 문을 앱이 실행해 결과(최대 100행)를 표시합니다.";
      }
      openScriptModal(script);
    });
    backdrop.querySelector("#cfg-save").addEventListener("click", () => {
      const name = nameEl.value.trim();
      if (!name) { window.Toast.show("설정 이름을 입력하세요", "error"); nameEl.focus(); return; }
      const list = loadConfigs();
      if (list.some((c) => c.name === name && c.name !== origName)) {
        window.Toast.show("이미 있는 이름입니다", "error");
        return;
      }
      const entry = { name, profile: profileSel.value, userPrompt: promptEl.value, mode: getMode() };
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

  // ────────────────────────────────────────────────────────────────
  // AI분석 — 직전 생성 SQL 로 최대 100행을 조회해 페르소나 프롬프트와 함께
  //   DBMS_CLOUD_AI.GENERATE(action=>'chat') 로 자연어 분석 결과를 만든다.
  //   · 페르소나: 서버 T_ANALYSIS_PERSONA (/api/personas CRUD).
  //   · 분석 실행: POST /api/nl2sql/analyze.
  // ────────────────────────────────────────────────────────────────
  const MOCK_PROFILES = ["AIF_NL2SQL_PROFILE", "OCI_GENERATE_PROFILE"];

  // 페르소나 목록 조회 — 서버 T_ANALYSIS_PERSONA (/api/personas). 실패 시 빈 배열.
  async function fetchPersonas() {
    try {
      const list = await window.API.get("/api/personas");
      return Array.isArray(list) ? list : [];
    } catch (e) {
      return [];
    }
  }

  // AI Profile 드롭다운 — 있으면 실제 /api/profiles(ENABLED), 실패/없으면 목업.
  async function fillProfileSelect(sel) {
    sel.innerHTML = `<option value="">불러오는 중…</option>`;
    let names = [];
    try {
      const profiles = await window.API.get("/api/profiles");
      names = (profiles || []).filter((p) => p.status === "ENABLED").map((p) => p.profile_name);
    } catch (e) {}
    if (!names.length) names = MOCK_PROFILES.slice();
    sel.innerHTML = "";
    names.forEach((nm) => {
      const o = document.createElement("option");
      o.value = nm;
      o.textContent = nm;
      sel.appendChild(o);
    });
    sel.value = names[0] || "";
  }

  function fillPersonaSelect(sel, list, selectId) {
    sel.innerHTML = "";
    if (!list.length) {
      sel.innerHTML = `<option value="">(등록된 페르소나 없음)</option>`;
      return;
    }
    list.forEach((p) => {
      const o = document.createElement("option");
      o.value = String(p.id);
      o.textContent = p.persona_name;
      sel.appendChild(o);
    });
    sel.value = selectId != null && list.some((p) => String(p.id) === String(selectId))
      ? String(selectId) : String(list[0].id);
  }

  // 분석 결과 렌더 — 분석 텍스트 + 복사 + 타이밍 + 접이식(사용한 프롬프트).
  function renderAnalysisResult(host, res, usedPrompt) {
    const analysis = (res && res.analysis) || "";
    host.innerHTML = "";
    const box = document.createElement("div");
    box.className = "panel";
    box.innerHTML = `<div class="panel-header"><h2>분석 결과</h2>
        <button class="btn btn-mini" id="an-copy" type="button">복사</button></div>`;
    const body = document.createElement("div");
    body.className = "panel-body";

    if (res && res.truncated) {
      const note = document.createElement("div");
      note.className = "muted";
      note.style.fontSize = "var(--fs-sm)";
      note.style.marginBottom = "var(--space-2)";
      note.textContent = "※ 최대 100행 기준으로 분석했습니다.";
      body.appendChild(note);
    }

    const pre = document.createElement("pre");
    pre.style.whiteSpace = "pre-wrap";
    pre.style.margin = "0";
    pre.textContent = analysis || "(빈 응답)";
    body.appendChild(pre);

    if (res && res.total_ms != null) {
      const ms = (v) => (v == null ? "-" : Number(v).toLocaleString() + " ms");
      const t = document.createElement("div");
      t.className = "muted";
      t.style.fontSize = "var(--fs-sm)";
      t.style.marginTop = "var(--space-2)";
      t.textContent = `총시간 ${ms(res.total_ms)} (데이터조회 ${ms(res.exec_ms)}, 분석생성 ${ms(res.gen_ms)})`;
      body.appendChild(t);
    }

    // 접이식: 사용한 프롬프트(서버가 조립한 최종 프롬프트 우선)
    const shownPrompt = (res && res.prompt) || usedPrompt || "";
    if (shownPrompt) {
      const det = document.createElement("details");
      det.style.marginTop = "var(--space-3)";
      const sum = document.createElement("summary");
      sum.className = "muted";
      sum.style.cursor = "pointer";
      sum.style.fontSize = "var(--fs-sm)";
      sum.textContent = "사용한 프롬프트";
      const ppre = document.createElement("pre");
      ppre.style.whiteSpace = "pre-wrap";
      ppre.textContent = shownPrompt;
      det.appendChild(sum);
      det.appendChild(ppre);
      body.appendChild(det);
    }

    box.appendChild(body);
    host.appendChild(box);
    box.querySelector("#an-copy").addEventListener("click", () => {
      navigator.clipboard.writeText(analysis).then(
        () => window.Toast.show("분석 결과 복사됨", "success"),
        () => window.Toast.show("복사 실패", "error")
      );
    });
  }

  // 공통 모달 셸 생성 (backdrop + Escape/✕ 닫기). 반환: {backdrop, close}
  function makeModal(innerHtml) {
    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    backdrop.innerHTML = innerHtml;
    const close = () => { backdrop.remove(); document.removeEventListener("keydown", onKey); };
    const onKey = (e) => { if (e.key === "Escape") close(); };
    document.addEventListener("keydown", onKey);
    document.body.appendChild(backdrop);
    return { backdrop, close };
  }

  // AI분석 팝업
  function openAnalyzeModal(lastResult) {
    const hasReal = lastResult && Array.isArray(lastResult.columns) && lastResult.columns.length &&
      Array.isArray(lastResult.rows) && lastResult.rows.length && lastResult.sql;
    if (!hasReal) {
      window.Toast.show("먼저 질문을 실행해 데이터를 조회하세요", "error");
      return;
    }
    const sql = lastResult.sql;
    const rowCount = lastResult.rows.length;

    const { backdrop, close } = makeModal(`
      <div class="modal" style="width:760px; max-width:94vw;">
        <div class="modal-header">
          <h2>AI 분석</h2>
          <button class="btn btn-ghost" id="an-close" type="button">✕</button>
        </div>
        <div class="modal-body stack">
          <div class="row" style="gap:var(--space-4);">
            <div class="stack-sm" style="flex:1;">
              <label>AI Profile</label>
              <select id="an-profile"></select>
            </div>
            <div class="stack-sm" style="flex:1;">
              <label>페르소나</label>
              <div class="row" style="gap:var(--space-2);">
                <select id="an-persona" style="flex:1;"></select>
                <button class="btn" id="an-persona-manage" type="button">관리</button>
              </div>
            </div>
          </div>
          <div class="stack-sm">
            <label>결과샘플 (분석 프롬프트 · 수정가능)</label>
            <textarea id="an-prompt" rows="8" style="font-family:var(--font-mono); font-size:var(--fs-sm);"></textarea>
            <span class="muted" style="font-size:var(--fs-sm);">※ [분석 시작] 시 직전 생성 SQL 로 최대 100행(현재 ${rowCount}행)을 조회해 위 프롬프트와 함께 분석합니다.</span>
          </div>
          <div id="an-result"><div class="empty-state muted">Profile·페르소나를 고르고 [분석 시작]을 누르세요.</div></div>
        </div>
        <div class="modal-footer row end" style="gap:var(--space-2);">
          <button class="btn" id="an-cancel" type="button">닫기</button>
          <button class="btn btn-primary" id="an-run" type="button">분석 시작</button>
        </div>
      </div>
    `);

    const profileSel = backdrop.querySelector("#an-profile");
    const personaSel = backdrop.querySelector("#an-persona");
    const promptEl = backdrop.querySelector("#an-prompt");
    const resultEl = backdrop.querySelector("#an-result");

    fillProfileSelect(profileSel);

    let personas = [];
    const applyPersona = () => {
      const p = personas.find((x) => String(x.id) === personaSel.value);
      promptEl.value = p ? p.prompt_tmpl : "";
    };
    const reloadPersonas = async (selectId) => {
      personas = await fetchPersonas();
      fillPersonaSelect(personaSel, personas, selectId);
      applyPersona();
    };
    reloadPersonas();
    personaSel.addEventListener("change", applyPersona);

    backdrop.querySelector("#an-persona-manage").addEventListener("click", () => {
      openPersonaManageModal(() => reloadPersonas(personaSel.value));
    });

    backdrop.querySelector("#an-close").addEventListener("click", close);
    backdrop.querySelector("#an-cancel").addEventListener("click", close);

    backdrop.querySelector("#an-run").addEventListener("click", async () => {
      const profile = profileSel.value;
      if (!profile) { window.Toast.show("AI Profile 을 선택하세요", "error"); return; }
      if (!promptEl.value.trim()) { window.Toast.show("분석 프롬프트가 비어 있습니다", "error"); return; }
      const runBtn = backdrop.querySelector("#an-run");
      runBtn.disabled = true;
      resultEl.innerHTML = `<div class="empty-state muted"><span class="spinner"></span> 분석 중…</div>`;
      let res;
      try {
        res = await window.API.post("/api/nl2sql/analyze", {
          sql, profile_name: profile, prompt: promptEl.value,
        });
      } catch (err) {
        resultEl.innerHTML = "";
        resultEl.appendChild(errBox(errMsg(err, "분석 실패")));
        return;
      } finally {
        runBtn.disabled = false;
      }
      if (res.error) {
        resultEl.innerHTML = "";
        resultEl.appendChild(errBox(res.error));
        return;
      }
      renderAnalysisResult(resultEl, res, promptEl.value);
    });

    setTimeout(() => profileSel.focus(), 50);
  }

  // 페르소나 관리 모달 (서버 T_ANALYSIS_PERSONA CRUD)
  function openPersonaManageModal(onSaved) {
    const { backdrop, close } = makeModal(`
      <div class="modal" style="width:860px; max-width:96vw;">
        <div class="modal-header">
          <h2>페르소나 관리</h2>
          <button class="btn btn-ghost" id="pm-close" type="button">✕</button>
        </div>
        <div class="modal-body row" style="gap:var(--space-4); align-items:stretch;">
          <div class="stack" style="flex:1; min-width:260px;">
            <div id="pm-list"></div>
            <button class="btn" id="pm-new" type="button">+ 새 페르소나</button>
          </div>
          <div class="stack" style="flex:1.3;">
            <div class="stack-sm"><label>이름</label><input type="text" id="pm-name" /></div>
            <div class="stack-sm"><label>설명</label><input type="text" id="pm-desc" /></div>
            <div class="stack-sm"><label>분석 프롬프트 템플릿</label>
              <textarea id="pm-tmpl" rows="10" style="font-family:var(--font-mono); font-size:var(--fs-sm);"></textarea></div>
          </div>
        </div>
        <div class="modal-footer row" style="justify-content:space-between; gap:var(--space-2);">
          <button class="btn btn-ghost" id="pm-delete" type="button">삭제</button>
          <div class="row" style="gap:var(--space-2);">
            <button class="btn" id="pm-close2" type="button">닫기</button>
            <button class="btn btn-primary" id="pm-save" type="button">저장</button>
          </div>
        </div>
      </div>
    `);

    const listEl = backdrop.querySelector("#pm-list");
    const nameEl = backdrop.querySelector("#pm-name");
    const descEl = backdrop.querySelector("#pm-desc");
    const tmplEl = backdrop.querySelector("#pm-tmpl");
    let list = [];
    let editingId = null;

    const fillForm = (p) => {
      editingId = p ? p.id : null;
      nameEl.value = p ? p.persona_name : "";
      descEl.value = p ? p.description || "" : "";
      tmplEl.value = p ? p.prompt_tmpl : "";
    };
    const renderList = () => {
      const cols = [
        { key: "persona_name", label: "이름" },
        { key: "description", label: "설명" },
      ];
      const table = window.SimpleTable.create(cols, list, {
        onRowClick: (row) => { fillForm(row); renderList(); },
        rowClassName: (row) => (row.id === editingId ? "selected" : ""),
        emptyText: "등록된 페르소나가 없습니다",
      });
      listEl.innerHTML = "";
      listEl.appendChild(table);
    };
    const reload = async (selectId) => {
      list = await fetchPersonas();
      const sel = list.find((p) => p.id === selectId);
      fillForm(sel || null);
      renderList();
    };
    reload();

    backdrop.querySelector("#pm-new").addEventListener("click", () => { fillForm(null); renderList(); });

    backdrop.querySelector("#pm-save").addEventListener("click", async () => {
      const name = nameEl.value.trim();
      if (!name) { window.Toast.show("이름을 입력하세요", "error"); nameEl.focus(); return; }
      if (!tmplEl.value.trim()) { window.Toast.show("프롬프트 템플릿을 입력하세요", "error"); return; }
      const body = { persona_name: name, description: descEl.value, prompt_tmpl: tmplEl.value };
      const btn = backdrop.querySelector("#pm-save");
      btn.disabled = true;
      try {
        if (editingId != null) await window.API.put(`/api/personas/${editingId}`, body);
        else await window.API.post("/api/personas", body);
      } catch (err) {
        window.Toast.show(errMsg(err, "저장 실패"), "error");
        return;
      } finally {
        btn.disabled = false;
      }
      window.Toast.show("저장됨", "success");
      await reload(editingId);
      if (onSaved) onSaved();
    });

    backdrop.querySelector("#pm-delete").addEventListener("click", async () => {
      if (editingId == null) { window.Toast.show("삭제할 페르소나를 목록에서 선택하세요", "error"); return; }
      try {
        await window.API.delete(`/api/personas/${editingId}`);
      } catch (err) {
        window.Toast.show(errMsg(err, "삭제 실패"), "error");
        return;
      }
      window.Toast.show("삭제됨", "success");
      await reload(null);
      if (onSaved) onSaved();
    });

    backdrop.querySelector("#pm-close").addEventListener("click", close);
    backdrop.querySelector("#pm-close2").addEventListener("click", close);
  }

  // 실행 스크립트 미리보기 팝업 (Chat설정 팝업 위에 겹쳐 뜬다).
  function openScriptModal(script) {
    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    backdrop.innerHTML = `
      <div class="modal" style="width:720px; max-width:92vw;">
        <div class="modal-header">
          <h2>실행 스크립트</h2>
          <button class="btn btn-ghost" id="sc-close" type="button">✕</button>
        </div>
        <div class="modal-body">
          <div style="position:relative;">
            <button class="btn btn-mini" id="sc-copy" type="button" style="position:absolute; top:0; right:0;">Copy</button>
            <pre id="sc-pre" style="white-space:pre-wrap; margin:0; font-family:var(--font-mono); font-size:var(--fs-sm);"></pre>
          </div>
        </div>
      </div>`;
    backdrop.querySelector("#sc-pre").textContent = script;
    // Escape 는 이 팝업만 닫는다(capture + stopImmediatePropagation 으로 하위 Chat설정 모달 유지).
    const close = () => { backdrop.remove(); document.removeEventListener("keydown", onKey, true); };
    const onKey = (e) => { if (e.key === "Escape") { e.stopImmediatePropagation(); close(); } };
    document.addEventListener("keydown", onKey, true);
    document.body.appendChild(backdrop);
    backdrop.querySelector("#sc-close").addEventListener("click", close);
    backdrop.querySelector("#sc-copy").addEventListener("click", () => {
      navigator.clipboard.writeText(script).then(
        () => window.Toast.show("스크립트 복사됨", "success"),
        () => window.Toast.show("복사 실패", "error"));
    });
  }

  window.Views = window.Views || {};
  window.Views.nl2sql = render;
})();
