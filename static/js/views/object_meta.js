/** views/object_meta.js — 메뉴 [1] Profile Object Comment & Annotation (상하구조).
 *  컬럼 그리드: 각 행마다 Comment / Annotation 개별 저장 버튼 + 하단 일괄 저장 2개. */
(function () {
  async function render() {
    const main = document.getElementById("main");
    main.innerHTML = "";

    // 헤더
    const title = document.createElement("div");
    title.className = "view-title";
    title.innerHTML = `<h1>Profile Object Comment & Annotation</h1>
      <span class="sub">선택한 Profile 의 object_list 테이블 메타데이터를 조회·수정합니다.</span>`;
    main.appendChild(title);

    const splitWrap = document.createElement("div");
    splitWrap.className = "split-vert";
    main.appendChild(splitWrap);

    // ── 상단 패널: Profile 선택 + Object List 테이블 ──
    const topPanel = document.createElement("div");
    topPanel.className = "panel";
    topPanel.innerHTML = `
      <div class="panel-header">
        <div class="row">
          <label for="om-profile">AI Profile</label>
          <select id="om-profile" style="min-width:240px;"></select>
        </div>
        <button class="btn btn-ghost" id="om-refresh">↻ 새로고침</button>
      </div>
      <div class="panel-body">
        <div id="om-object-list" class="empty-state muted">Profile 을 선택하면 object_list 가 표시됩니다.</div>
      </div>
    `;
    splitWrap.appendChild(topPanel);

    // ── 하단 패널: 선택 테이블 편집 ──
    const bottomPanel = document.createElement("div");
    bottomPanel.className = "panel";
    bottomPanel.innerHTML = `
      <div class="panel-header">
        <h2 id="om-detail-title">테이블 선택 시 표시</h2>
        <span id="om-annot-flag" class="badge"></span>
      </div>
      <div class="panel-body" id="om-detail-body">
        <div class="empty-state muted">상단에서 테이블을 선택하세요.</div>
      </div>
    `;
    splitWrap.appendChild(bottomPanel);

    // Profile 목록 로드 — object_list 가 설정된 Profile 만 노출 (메뉴 [1] 의 작업 대상)
    let profiles = [];
    try {
      const all = await window.API.get("/api/profiles");
      profiles = all.filter((p) => p.has_object_list === "Y");
    } catch (e) {
      window.Toast.show(errMsg(e, "Profile 목록 로드 실패"), "error");
      return;
    }

    const profileSel = document.getElementById("om-profile");
    if (profiles.length === 0) {
      profileSel.innerHTML = `<option disabled selected>object_list 가 설정된 Profile 이 없습니다</option>`;
      document.getElementById("om-object-list").innerHTML =
        '<div class="empty-state muted">사용 가능한 Profile 이 없습니다.</div>';
      return;
    }
    profileSel.innerHTML = profiles.map((p) =>
      `<option value="${p.profile_name}">${p.profile_name}</option>`
    ).join("");

    async function loadObjectList() {
      const name = profileSel.value;
      const host = document.getElementById("om-object-list");
      host.innerHTML = '<div class="empty-state"><span class="spinner"></span> 조회 중...</div>';
      let objects = [];
      try {
        objects = await window.API.get(`/api/profiles/${encodeURIComponent(name)}/objects`);
      } catch (e) {
        host.innerHTML = '<div class="empty-state muted">조회 실패</div>';
        return;
      }
      host.innerHTML = "";
      const table = window.SimpleTable.create(
        [
          { key: "owner",         label: "Owner" },
          { key: "table",         label: "Table" },
          { key: "table_comment", label: "Table Comment" },
        ],
        objects,
        {
          rowClassName: (r) => (r.table_comment ? "" : "warn-row"),
          onRowClick: (row, tr) => {
            host.querySelectorAll("tr.selected").forEach((el) => el.classList.remove("selected"));
            tr.classList.add("selected");
            loadDetail(row.owner, row.table);
          },
          emptyText: "object_list 가 비어 있습니다",
        }
      );
      host.appendChild(table);
    }

    async function loadDetail(owner, tableName) {
      document.getElementById("om-detail-title").textContent = `${owner}.${tableName}`;
      const body = document.getElementById("om-detail-body");
      body.innerHTML = '<div class="empty-state"><span class="spinner"></span> 조회 중...</div>';

      let data;
      try {
        data = await window.API.get(`/api/objects/${encodeURIComponent(owner)}/${encodeURIComponent(tableName)}/metadata`);
      } catch (e) {
        body.innerHTML = '<div class="empty-state muted">메타데이터 조회 실패</div>';
        return;
      }

      const flag = document.getElementById("om-annot-flag");
      if (data.annotations_supported) {
        flag.textContent = "Annotations: 지원";
        flag.className = "badge ok";
      } else {
        flag.textContent = "Annotations: 미지원";
        flag.className = "badge disabled";
      }

      body.innerHTML = "";
      // 테이블 레벨
      const tableLvl = document.createElement("div");
      tableLvl.className = "stack";
      tableLvl.innerHTML = `
        <h3>테이블 레벨</h3>
        <div class="row" style="align-items:flex-start;">
          <label style="width:90px; padding-top:6px;">Comment</label>
          <textarea id="om-tbl-comment" rows="1" class="textarea-auto" style="flex:1;">${escapeHtml(data.table.comment)}</textarea>
          <button class="btn btn-primary" data-action="save-tbl-comment">저장</button>
        </div>
        <div class="row" style="align-items:flex-start;">
          <label style="width:90px; padding-top:6px;">Annotation</label>
          <div id="om-tbl-annot-display" style="flex:1; display:flex; flex-direction:column; gap:4px; align-items:flex-start;"></div>
          <button class="btn btn-primary" data-action="manage-tbl-annot" ${data.annotations_supported ? "" : "disabled"}>+ Annotation 추가</button>
        </div>
      `;
      body.appendChild(tableLvl);
      renderAnnotationChips(
        document.getElementById("om-tbl-annot-display"),
        data.table.annotations || {}
      );

      // 컬럼 레벨 그리드
      const colHeader = document.createElement("h3");
      colHeader.textContent = "컬럼 레벨";
      colHeader.style.marginTop = "var(--space-5)";
      body.appendChild(colHeader);

      const dirty = { comment: new Set() };

      const colTable = window.SimpleTable.create(
        [
          { key: "name",        label: "Column" },
          { key: "data_type",   label: "Data Type" },
          { key: "comment",     label: "Comment",
            format: makeCommentEditor(owner, tableName, dirty) },
          { key: "annotations", label: "Annotation",
            format: makeAnnotationCell(owner, tableName, data.annotations_supported) },
          { key: "_ai", label: "AI 추천", headerAlign: "center", align: "center",
            format: makeAiSuggestCell(owner, tableName, () => profileSel.value) },
        ],
        data.columns,
        { emptyText: "컬럼이 없습니다" }
      );
      colTable.classList.add("col-grid");
      body.appendChild(colTable);

      // 하단 일괄 저장: Comment 만 (Annotation 은 모달에서 개별 처리)
      const bulkRow = document.createElement("div");
      bulkRow.className = "row end";
      bulkRow.style.marginTop = "var(--space-4)";
      bulkRow.style.gap = "var(--space-2)";
      bulkRow.innerHTML = `
        <button class="btn btn-primary" data-action="bulk-comment">Comment 일괄 저장</button>
      `;
      body.appendChild(bulkRow);

      // 액션 핸들러
      tableLvl.querySelector('[data-action="save-tbl-comment"]').addEventListener("click", async () => {
        const text = document.getElementById("om-tbl-comment").value;
        try {
          await window.API.put(
            `/api/objects/${encodeURIComponent(owner)}/${encodeURIComponent(tableName)}/comment`,
            { text }
          );
          window.Toast.show("테이블 코멘트 저장", "success");
        } catch (err) { window.Toast.show(errMsg(err, "저장 실패"), "error"); }
      });
      const tblAnnotBtn = tableLvl.querySelector('[data-action="manage-tbl-annot"]');
      if (!tblAnnotBtn.disabled) {
        tblAnnotBtn.addEventListener("click", () => {
          openAnnotationModal({
            owner, tableName,
            column: null,
            current: data.table.annotations || {},
            onChanged: (newAnnotations) => {
              data.table.annotations = newAnnotations;
              renderAnnotationChips(
                document.getElementById("om-tbl-annot-display"),
                newAnnotations
              );
            },
          });
        });
      }
      bulkRow.querySelector('[data-action="bulk-comment"]').addEventListener("click",
        () => bulkSaveComment(body, owner, tableName, dirty));
    }

    profileSel.addEventListener("change", loadObjectList);
    document.getElementById("om-refresh").addEventListener("click", loadObjectList);
    await loadObjectList();
  }

  // ───── 셀 에디터: Comment ─────
  function makeCommentEditor(owner, tableName, dirty) {
    return (value, row) => {
      const wrap = document.createElement("div");
      wrap.className = "cell-with-save";
      const input = document.createElement("textarea");
      input.rows = 1;
      input.className = "textarea-auto";
      input.value = value || "";
      input.dataset.field = "comment";
      input.dataset.column = row.name;
      input.addEventListener("input", () => {
        dirty.comment.add(row.name);
        wrap.classList.add("dirty");
      });

      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn btn-mini";
      btn.textContent = "저장";
      btn.title = `${row.name} 코멘트만 저장`;
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        try {
          await window.API.put(
            `/api/objects/${encodeURIComponent(owner)}/${encodeURIComponent(tableName)}/columns/${encodeURIComponent(row.name)}/comment`,
            { text: input.value }
          );
          dirty.comment.delete(row.name);
          wrap.classList.remove("dirty");
          window.Toast.show(`${row.name} 코멘트 저장`, "success");
        } catch (err) {
          window.Toast.show(errMsg(err, "저장 실패"), "error");
        } finally {
          btn.disabled = false;
        }
      });

      wrap.appendChild(input);
      wrap.appendChild(btn);
      return wrap;
    };
  }

  // ───── 셀: Annotation (display + 추가 버튼) ─────
  function makeAnnotationCell(owner, tableName, supported) {
    return (value, row) => {
      if (!supported) {
        const span = document.createElement("span");
        span.className = "muted";
        span.textContent = "미지원";
        return span;
      }
      const wrap = document.createElement("div");
      wrap.className = "row";
      wrap.style.gap = "6px";
      wrap.style.alignItems = "flex-start";

      const display = document.createElement("div");
      display.style.display = "flex";
      display.style.flexDirection = "column";
      display.style.gap = "4px";
      display.style.alignItems = "flex-start";
      display.style.flex = "1";
      renderAnnotationChips(display, row.annotations || {});

      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn btn-mini";
      btn.textContent = "+ 추가";
      btn.title = `${row.name} annotation 관리`;
      btn.addEventListener("click", () => {
        openAnnotationModal({
          owner, tableName,
          column: row.name,
          current: row.annotations || {},
          onChanged: (newAnnotations) => {
            row.annotations = newAnnotations;
            renderAnnotationChips(display, newAnnotations);
          },
        });
      });

      wrap.appendChild(display);
      wrap.appendChild(btn);
      return wrap;
    };
  }

  // ───── 셀: AI 추천 버튼 ─────
  //  클릭 → 모달에서 컬럼 데이터 100행 기반 코멘트 추천(SELECT AI chat) → [적용] 시 Comment 칸에 반영.
  function makeAiSuggestCell(owner, tableName, getProfile) {
    return (value, row) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn btn-mini";
      btn.textContent = "AI 추천";
      btn.title = `${row.name} 컬럼 데이터 기반 코멘트 추천`;
      btn.addEventListener("click", () => {
        openAiSuggestModal({
          owner, tableName,
          column: row.name,
          dataType: row.data_type,
          profileName: getProfile(),
          onApply: (text) => {
            // 같은 행의 Comment textarea 에 반영 + dirty 표시(input 이벤트로 처리)
            const ta = document.querySelector(
              `#om-detail-body textarea[data-field="comment"][data-column="${CSS.escape(row.name)}"]`
            );
            if (!ta) { window.Toast.show("Comment 칸을 찾지 못했습니다", "error"); return; }
            ta.value = text;
            ta.dispatchEvent(new Event("input", { bubbles: true }));
            window.Toast.show(`${row.name} 코멘트에 적용됨 (저장 필요)`, "success");
          },
        });
      });
      return btn;
    };
  }

  // ───── AI 코멘트 추천 모달 ─────
  function openAiSuggestModal({ owner, tableName, column, dataType, profileName, onApply }) {
    const target = `${owner}.${tableName}.${column}`;
    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    backdrop.innerHTML = `
      <div class="modal" style="width:640px;">
        <div class="modal-header">
          <h2>AI 코멘트 추천 — ${escapeHtml(target)}</h2>
          <button class="btn btn-ghost" id="ai-close">✕</button>
        </div>
        <div class="modal-body stack">
          <div class="muted" style="font-size:var(--fs-sm);">
            Profile <b>${escapeHtml(profileName || "(미선택)")}</b> · 컬럼 데이터 100행을 조회해 SELECT AI(chat) 로 추천합니다.
          </div>
          <div id="ai-status" class="empty-state"><span class="spinner"></span> 추천 생성 중...</div>
          <div class="stack-sm" id="ai-result" style="display:none;">
            <label>추천 코멘트 <span class="muted" style="font-size:var(--fs-sm);">— 적용 전 수정 가능</span></label>
            <textarea id="ai-text" rows="3" class="textarea-auto"></textarea>
          </div>
          <div class="row end" style="gap:8px;">
            <button class="btn btn-ghost" id="ai-retry" style="display:none;">다시 추천</button>
            <button class="btn btn-primary" id="ai-apply" disabled>적용</button>
          </div>
        </div>
      </div>
    `;

    const close = () => { backdrop.remove(); document.removeEventListener("keydown", onKey); };
    const onKey = (e) => { if (e.key === "Escape") close(); };
    backdrop.addEventListener("click", (e) => { if (e.target === backdrop) close(); });
    backdrop.querySelector("#ai-close").addEventListener("click", close);

    const statusEl = backdrop.querySelector("#ai-status");
    const resultEl = backdrop.querySelector("#ai-result");
    const textEl = backdrop.querySelector("#ai-text");
    const applyBtn = backdrop.querySelector("#ai-apply");
    const retryBtn = backdrop.querySelector("#ai-retry");

    async function fetchSuggestion() {
      if (!profileName) {
        statusEl.style.display = "";
        statusEl.className = "empty-state muted";
        statusEl.textContent = "Profile 이 선택되지 않았습니다.";
        return;
      }
      statusEl.style.display = "";
      statusEl.className = "empty-state";
      statusEl.innerHTML = '<span class="spinner"></span> 추천 생성 중...';
      resultEl.style.display = "none";
      applyBtn.disabled = true;
      retryBtn.style.display = "none";
      try {
        const res = await window.API.post(
          `/api/objects/${encodeURIComponent(owner)}/${encodeURIComponent(tableName)}/columns/${encodeURIComponent(column)}/suggest-comment`,
          { profile_name: profileName }
        );
        statusEl.style.display = "none";
        resultEl.style.display = "";
        textEl.value = res.suggestion || "";
        resultEl.querySelector("label").innerHTML =
          `추천 코멘트 <span class="muted" style="font-size:var(--fs-sm);">— 샘플 ${res.sample_count}건 기반, 적용 전 수정 가능</span>`;
        applyBtn.disabled = !(res.suggestion || "").trim();
        retryBtn.style.display = "";
      } catch (err) {
        statusEl.style.display = "";
        statusEl.className = "empty-state muted";
        statusEl.textContent = errMsg(err, "추천 생성 실패");
        retryBtn.style.display = "";
      }
    }

    applyBtn.addEventListener("click", () => {
      const text = textEl.value.trim();
      if (!text) { window.Toast.show("추천 내용이 비어 있습니다", "warn"); return; }
      onApply && onApply(text);
      close();
    });
    retryBtn.addEventListener("click", fetchSuggestion);

    document.addEventListener("keydown", onKey);
    document.body.appendChild(backdrop);
    fetchSuggestion();
  }

  // ───── Annotation 칩 렌더링 (display only) ─────
  function renderAnnotationChips(host, annotations) {
    host.innerHTML = "";
    const entries = Object.entries(annotations || {});
    if (entries.length === 0) {
      const m = document.createElement("span");
      m.className = "muted";
      m.style.fontSize = "var(--fs-sm)";
      m.textContent = "(없음)";
      host.appendChild(m);
      return;
    }
    for (const [k, v] of entries) {
      const chip = document.createElement("span");
      chip.className = "annot-chip";
      chip.textContent = `${k} = ${v}`;
      host.appendChild(chip);
    }
  }

  // ───── Annotation 관리 모달 (테이블/컬럼 공용) ─────
  function openAnnotationModal({ owner, tableName, column, current, onChanged }) {
    const isColumn = !!column;
    const annotations = { ...(current || {}) };
    const target = `${owner}.${tableName}${isColumn ? "." + column : ""}`;

    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    backdrop.innerHTML = `
      <div class="modal" style="width:640px;">
        <div class="modal-header">
          <h2>Annotation 관리 — ${escapeHtml(target)}</h2>
          <button class="btn btn-ghost" id="am-close">✕</button>
        </div>
        <div class="modal-body stack">
          <div class="stack-sm">
            <label>기존 Annotation</label>
            <div id="am-list" class="stack-sm"></div>
          </div>
          <div class="stack-sm">
            <label>새 항목 추가</label>
            <div class="row" style="gap:6px; align-items:flex-start;">
              <input id="am-name" type="text" placeholder="name" style="width:200px;" />
              <textarea id="am-value" rows="1" class="textarea-auto" placeholder="value" style="flex:1;"></textarea>
              <button class="btn btn-primary" id="am-add">추가</button>
            </div>
          </div>
        </div>
      </div>
    `;

    function close() {
      onChanged && onChanged(annotations);
      backdrop.remove();
    }

    backdrop.addEventListener("click", (e) => { if (e.target === backdrop) close(); });
    backdrop.querySelector("#am-close").addEventListener("click", close);

    function urlFor(annName) {
      const base = `/api/objects/${encodeURIComponent(owner)}/${encodeURIComponent(tableName)}`;
      if (isColumn) {
        return `${base}/columns/${encodeURIComponent(column)}/annotation` + (annName ? `/${encodeURIComponent(annName)}` : "");
      }
      return `${base}/annotation` + (annName ? `/${encodeURIComponent(annName)}` : "");
    }

    function renderList() {
      const host = backdrop.querySelector("#am-list");
      host.innerHTML = "";
      const entries = Object.entries(annotations);
      if (entries.length === 0) {
        host.innerHTML = '<div class="muted">(없음)</div>';
        return;
      }
      for (const [name, value] of entries) {
        const row = document.createElement("div");
        row.className = "row";
        row.style.gap = "6px";
        row.style.alignItems = "center";
        const chip = document.createElement("span");
        chip.className = "annot-chip";
        chip.style.flex = "1";
        chip.textContent = `${name} = ${value}`;
        const del = document.createElement("button");
        del.className = "btn btn-ghost btn-mini";
        del.textContent = "삭제";
        del.addEventListener("click", async () => {
          del.disabled = true;
          try {
            await window.API.delete(urlFor(name));
            delete annotations[name];
            renderList();
            window.Toast.show(`${name} 삭제됨`, "success");
          } catch (err) {
            window.Toast.show(errMsg(err, "삭제 실패"), "error");
          } finally {
            del.disabled = false;
          }
        });
        row.appendChild(chip);
        row.appendChild(del);
        host.appendChild(row);
      }
    }

    backdrop.querySelector("#am-add").addEventListener("click", async () => {
      const nameInp = backdrop.querySelector("#am-name");
      const valInp = backdrop.querySelector("#am-value");
      const name = nameInp.value.trim();
      const value = valInp.value;
      if (!name) { window.Toast.show("name 이 필요합니다", "warn"); return; }
      const addBtn = backdrop.querySelector("#am-add");
      addBtn.disabled = true;
      try {
        await window.API.put(urlFor(null), { name, value });
        // Oracle 은 unquoted identifier 를 대문자로 저장 → 표시도 대문자로 통일
        annotations[name.toUpperCase()] = value;
        nameInp.value = "";
        valInp.value = "";
        renderList();
        window.Toast.show(`${name} 적용됨`, "success");
      } catch (err) {
        window.Toast.show(errMsg(err, "적용 실패"), "error");
      } finally {
        addBtn.disabled = false;
      }
    });

    document.body.appendChild(backdrop);
    renderList();
  }

  // ───── 일괄 저장 ─────
  async function bulkSaveComment(body, owner, tableName, dirty) {
    const inputs = body.querySelectorAll('textarea[data-field="comment"]');
    const cols = [];
    inputs.forEach((inp) => {
      if (dirty.comment.has(inp.dataset.column)) {
        cols.push({ name: inp.dataset.column, comment: inp.value });
      }
    });
    if (cols.length === 0) { window.Toast.show("변경된 코멘트가 없습니다", "warn"); return; }
    try {
      await window.API.post(`/api/objects/${encodeURIComponent(owner)}/${encodeURIComponent(tableName)}/columns/bulk`,
                            { columns: cols });
      cols.forEach((c) => {
        dirty.comment.delete(c.name);
        const inp = body.querySelector(`textarea[data-field="comment"][data-column="${CSS.escape(c.name)}"]`);
        if (inp) inp.parentElement.classList.remove("dirty");
      });
      window.Toast.show(`${cols.length}개 컬럼 코멘트 일괄 저장`, "success");
    } catch (err) {
      const d = err && err.payload && err.payload.detail;
      const col = d && d.failed_column ? ` (${d.failed_column} 행에서 중단)` : "";
      window.Toast.show(errMsg(err, "코멘트 일괄 저장 실패") + col, "error");
    }
  }

  // ───── 유틸 ─────
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

  function escapeAttr(v) {
    if (v === null || v === undefined) return "";
    return String(v).replace(/"/g, "&quot;");
  }

  function escapeHtml(v) {
    if (v === null || v === undefined) return "";
    return String(v)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  window.Views = window.Views || {};
  window.Views.objectMeta = render;
})();
