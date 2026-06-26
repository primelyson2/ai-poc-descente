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
      const colHeader = document.createElement("div");
      colHeader.className = "row";
      colHeader.style.justifyContent = "space-between";
      colHeader.style.marginTop = "var(--space-5)";
      colHeader.style.marginBottom = "var(--space-3)";
      const annDis = data.annotations_supported ? "" : "disabled";
      colHeader.innerHTML = `
        <h3 style="margin:0;">컬럼 레벨</h3>
        <div class="row" style="gap:var(--space-2);">
          <button class="btn" data-action="download-comments" title="COLUMN, COMMENT 두 열을 xlsx 로 다운로드">Download</button>
          <input type="file" id="om-comment-upload-file" accept=".xlsx,.xls" style="display:none;" />
          <button class="btn" data-action="upload-comments" title="comment_upload.xlsx (COLUMN, COMMENT) 업로드">Upload</button>
          <button class="btn" data-action="download-annotations" title="모든 컬럼 Annotation 을 COLUMN, Key, Value 로 xlsx 다운로드" ${annDis}>Annotation Download</button>
          <input type="file" id="om-annot-upload-file" accept=".xlsx,.xls" style="display:none;" />
          <button class="btn" data-action="upload-annotations" title="COLUMN, Key, Value xlsx 업로드 — 즉시 DB 반영(동일 키는 값 Update)" ${annDis}>Annotation Upload</button>
        </div>`;
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
            format: makeAiSuggestCell(owner, tableName, () => profileSel.value, dirty) },
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

      // Upload: comment_upload.xlsx 를 읽어 매칭되는 컬럼의 Comment 칸을 채운다(검토 후 일괄 저장).
      const uploadFile = colHeader.querySelector("#om-comment-upload-file");
      colHeader.querySelector('[data-action="upload-comments"]').addEventListener("click",
        () => uploadFile.click());
      uploadFile.addEventListener("change", (ev) =>
        handleCommentUpload(ev, body, data.columns || [], dirty));

      // Download: 현재 화면의 COLUMN/COMMENT 두 열만 xlsx 로 내보낸다(템플릿 겸 백업).
      colHeader.querySelector('[data-action="download-comments"]').addEventListener("click",
        () => handleCommentDownload(body, owner, tableName, data.columns || []));

      // Annotation Download: 현재 테이블 모든 컬럼의 Annotation 을 COLUMN/Key/Value 로 내보낸다.
      const annDownBtn = colHeader.querySelector('[data-action="download-annotations"]');
      if (annDownBtn && !annDownBtn.disabled) {
        annDownBtn.addEventListener("click",
          () => handleAnnotationDownload(tableName, data.columns || []));
      }
      // Annotation Upload: COLUMN/Key/Value xlsx 를 읽어 즉시 DB 반영(ADD OR REPLACE) 후 새로고침.
      const annUploadFile = colHeader.querySelector("#om-annot-upload-file");
      const annUpBtn = colHeader.querySelector('[data-action="upload-annotations"]');
      if (annUpBtn && !annUpBtn.disabled) {
        annUpBtn.addEventListener("click", () => annUploadFile.click());
        annUploadFile.addEventListener("change", (ev) =>
          handleAnnotationUpload(ev, owner, tableName, () => loadDetail(owner, tableName)));
      }
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
  //  클릭 → 모달에서 컬럼 데이터 100행 기반 코멘트 추천(SELECT AI chat) → [적용] 시 Comment 칸 반영 + 즉시 DB 저장.
  function makeAiSuggestCell(owner, tableName, getProfile, dirty) {
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
          // [적용] → 같은 행 Comment 칸에 반영 후 곧바로 DB 저장(컬럼 코멘트 PUT).
          onApply: async (text) => {
            const ta = document.querySelector(
              `#om-detail-body textarea[data-field="comment"][data-column="${CSS.escape(row.name)}"]`
            );
            if (ta) ta.value = text;
            try {
              await window.API.put(
                `/api/objects/${encodeURIComponent(owner)}/${encodeURIComponent(tableName)}/columns/${encodeURIComponent(row.name)}/comment`,
                { text }
              );
              // 저장 성공 → dirty 해제(강조 제거). 실패 시엔 dirty 로 남겨 일괄저장으로 재시도 가능.
              if (dirty && dirty.comment) dirty.comment.delete(row.name);
              if (ta && ta.parentElement) ta.parentElement.classList.remove("dirty");
              window.Toast.show(`${row.name} 코멘트 저장됨`, "success");
            } catch (err) {
              if (ta) {
                if (dirty && dirty.comment) dirty.comment.add(row.name);
                if (ta.parentElement) ta.parentElement.classList.add("dirty");
              }
              window.Toast.show(errMsg(err, "저장 실패"), "error");
            }
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
          <details id="ai-prompt-wrap" style="display:none;">
            <summary style="cursor:pointer; font-size:var(--fs-sm); color:var(--text-muted); user-select:none;">사용한 프롬프트 보기 <span class="muted">— 수정 후 [다시 추천] 하면 수정된 프롬프트로 실행됩니다</span></summary>
            <textarea id="ai-prompt" rows="10" style="white-space:pre; width:100%; box-sizing:border-box; margin:var(--space-2) 0 0; font-family:var(--font-mono); font-size:var(--fs-sm); background:var(--surface-alt); padding:var(--space-3); border-radius:var(--radius-md); max-height:300px; overflow:auto; resize:vertical;"></textarea>
          </details>
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
    // 바깥 클릭으로는 닫지 않음 — 닫기는 X 버튼으로만 (실수 닫힘 방지)
    backdrop.querySelector("#ai-close").addEventListener("click", close);

    const statusEl = backdrop.querySelector("#ai-status");
    const resultEl = backdrop.querySelector("#ai-result");
    const textEl = backdrop.querySelector("#ai-text");
    const applyBtn = backdrop.querySelector("#ai-apply");
    const retryBtn = backdrop.querySelector("#ai-retry");
    const promptWrap = backdrop.querySelector("#ai-prompt-wrap");
    const promptEl = backdrop.querySelector("#ai-prompt");

    // useEditedPrompt=true 이면 textarea 의 (수정된) 프롬프트를 그대로 백엔드에 전달해 실행.
    //   false(최초 호출)면 백엔드가 샘플/컨텍스트로 프롬프트를 새로 구성한다.
    async function fetchSuggestion(useEditedPrompt) {
      if (!profileName) {
        statusEl.style.display = "";
        statusEl.className = "empty-state muted";
        statusEl.textContent = "Profile 이 선택되지 않았습니다.";
        return;
      }
      const payload = { profile_name: profileName };
      if (useEditedPrompt) {
        const edited = promptEl.value.trim();
        if (!edited) { window.Toast.show("프롬프트가 비어 있습니다", "warn"); promptWrap.open = true; return; }
        payload.prompt = edited;
      }
      statusEl.style.display = "";
      statusEl.className = "empty-state";
      statusEl.innerHTML = '<span class="spinner"></span> 추천 생성 중...';
      resultEl.style.display = "none";
      promptWrap.style.display = "none";
      if (!useEditedPrompt) promptWrap.open = false;
      applyBtn.disabled = true;
      retryBtn.style.display = "none";
      try {
        const res = await window.API.post(
          `/api/objects/${encodeURIComponent(owner)}/${encodeURIComponent(tableName)}/columns/${encodeURIComponent(column)}/suggest-comment`,
          payload
        );
        statusEl.style.display = "none";
        // 추천에 사용한 실제 프롬프트 — 수정 가능
        promptEl.value = res.prompt || "";
        resultEl.style.display = "";
        textEl.value = res.suggestion || "";
        const basis = (res.sample_count != null) ? `샘플 ${res.sample_count}건 기반` : "수정된 프롬프트 기반";
        resultEl.querySelector("label").innerHTML =
          `추천 코멘트 <span class="muted" style="font-size:var(--fs-sm);">— ${basis}, 적용 전 수정 가능</span>`;
        applyBtn.disabled = !(res.suggestion || "").trim();
      } catch (err) {
        statusEl.style.display = "";
        statusEl.className = "empty-state muted";
        statusEl.textContent = errMsg(err, "추천 생성 실패");
      }
      // 성공/실패 공통: 프롬프트가 있으면 표시(수정본으로 재실행 시 펼친 채로 유지), 재시도 버튼 노출
      promptWrap.style.display = promptEl.value ? "" : "none";
      if (useEditedPrompt) promptWrap.open = true;
      retryBtn.style.display = "";
    }

    applyBtn.addEventListener("click", () => {
      const text = textEl.value.trim();
      if (!text) { window.Toast.show("추천 내용이 비어 있습니다", "warn"); return; }
      onApply && onApply(text);
      close();
    });
    // 다시 추천 — 표시된(수정 가능) 프롬프트가 있으면 그 내용으로 실행, 없으면(최초 실패 등)
    //   샘플 기반으로 새로 구성해 재생성.
    retryBtn.addEventListener("click", () => fetchSuggestion(!!promptEl.value.trim()));

    document.addEventListener("keydown", onKey);
    document.body.appendChild(backdrop);
    fetchSuggestion(false);
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
              <input id="am-name" type="text" placeholder="name (예: AGG_BASIS, 집계기준)" style="width:200px;" />
              <textarea id="am-value" rows="1" class="textarea-auto" placeholder="value (한글 설명 가능)" style="flex:1;"></textarea>
              <button class="btn btn-primary" id="am-add">추가</button>
            </div>
            <div class="muted" style="font-size:var(--fs-sm);">이름(name)은 영문 식별자 또는 한글 모두 가능합니다. 영문은 대문자로 저장됩니다.</div>
          </div>
        </div>
      </div>
    `;

    function close() {
      onChanged && onChanged(annotations);
      backdrop.remove();
    }

    // 바깥 클릭으로는 닫지 않음 — 닫기는 X 버튼으로만 (실수 닫힘 방지)
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
      // 영문 식별자/한글 모두 허용. 큰따옴표(")만 quoted identifier 안전을 위해 금지.
      if (name.includes('"')) {
        window.Toast.show('annotation 이름에 큰따옴표(")는 사용할 수 없습니다', "error");
        nameInp.focus();
        return;
      }
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

  // ───── Comment xlsx 업로드 ─────
  // comment_upload.xlsx (1행 헤더 COLUMN, COMMENT) 를 읽어, 매칭되는 컬럼의
  // Comment 입력칸을 채우고 dirty 표시만 한다. 실제 DB 반영은 "Comment 일괄 저장".
  function handleCommentUpload(ev, body, columns, dirty) {
    const input = ev.target;
    const file = input.files && input.files[0];
    if (!file) return;
    if (typeof XLSX === "undefined") {
      window.Toast.show("xlsx 라이브러리 로드 실패 — 새로고침 후 다시 시도하세요", "error");
      input.value = "";
      return;
    }

    // 테이블 실제 컬럼명(대문자) → 컬럼명 lookup. xlsx 는 CamelCase 일 수 있어 대문자로 매칭.
    const colByUpper = new Map();
    columns.forEach((c) => colByUpper.set(String(c.name).toUpperCase(), c.name));

    const reader = new FileReader();
    reader.onload = () => {
      try {
        const wb = XLSX.read(reader.result, { type: "array" });
        const ws = wb.Sheets[wb.SheetNames[0]];
        if (!ws) throw new Error("시트를 찾을 수 없습니다");
        const rows = XLSX.utils.sheet_to_json(ws, { header: 1, blankrows: false });
        if (!rows.length) throw new Error("빈 파일입니다");

        // 헤더 행에서 COLUMN / COMMENT 열 인덱스 탐색(대소문자·공백 무시).
        const header = (rows[0] || []).map((h) => String(h == null ? "" : h).trim().toUpperCase());
        const ci = header.indexOf("COLUMN");
        const mi = header.indexOf("COMMENT");
        if (ci === -1 || mi === -1) {
          window.Toast.show("헤더(COLUMN, COMMENT)를 찾을 수 없습니다", "error");
          return;
        }

        let filled = 0;
        const unmatched = [];
        for (let r = 1; r < rows.length; r++) {
          const row = rows[r] || [];
          const rawName = row[ci];
          if (rawName == null || String(rawName).trim() === "") continue;
          const key = String(rawName).trim().toUpperCase();
          const colName = colByUpper.get(key);
          if (!colName) { unmatched.push(String(rawName).trim()); continue; }
          const comment = row[mi] == null ? "" : String(row[mi]);
          const inp = body.querySelector(
            `textarea[data-field="comment"][data-column="${CSS.escape(colName)}"]`);
          if (!inp) { unmatched.push(String(rawName).trim()); continue; }
          inp.value = comment;
          dirty.comment.add(colName);
          inp.parentElement.classList.add("dirty");
          filled++;
        }

        if (filled === 0) {
          window.Toast.show("매칭되는 컬럼이 없습니다. 컬럼명을 확인하세요.", "warn");
        } else {
          window.Toast.show(
            `${filled}개 컬럼 Comment 를 채웠습니다. 검토 후 'Comment 일괄 저장' 하세요.`, "success");
        }
        if (unmatched.length) {
          const shown = unmatched.slice(0, 10).join(", ");
          const more = unmatched.length > 10 ? ` 외 ${unmatched.length - 10}개` : "";
          window.Toast.show(`매칭 안 된 컬럼 ${unmatched.length}개: ${shown}${more}`, "warn");
        }
      } catch (e) {
        window.Toast.show("업로드 실패: " + (e.message || "잘못된 파일"), "error");
      } finally {
        input.value = "";
      }
    };
    reader.onerror = () => {
      window.Toast.show("파일을 읽지 못했습니다", "error");
      input.value = "";
    };
    reader.readAsArrayBuffer(file);
  }

  // ───── Comment xlsx 다운로드 ─────
  // 현재 테이블의 COLUMN / COMMENT 두 열만 xlsx 로 내보낸다(Upload 템플릿과 동일 형식).
  // 화면의 입력칸 현재값을 우선 사용(미저장 편집분 포함), 없으면 메타데이터 comment.
  function handleCommentDownload(body, owner, tableName, columns) {
    if (typeof XLSX === "undefined") {
      window.Toast.show("xlsx 라이브러리 로드 실패 — 새로고침 후 다시 시도하세요", "error");
      return;
    }
    if (!columns.length) {
      window.Toast.show("내보낼 컬럼이 없습니다", "warn");
      return;
    }
    const aoa = [["COLUMN", "COMMENT"]];
    columns.forEach((c) => {
      const inp = body.querySelector(
        `textarea[data-field="comment"][data-column="${CSS.escape(c.name)}"]`);
      const comment = inp ? inp.value : (c.comment || "");
      aoa.push([c.name, comment]);
    });
    try {
      const ws = XLSX.utils.aoa_to_sheet(aoa);
      ws["!cols"] = [{ wch: 30 }, { wch: 50 }];
      const wb = XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(wb, ws, "Sheet1");
      XLSX.writeFile(wb, `comment_${tableName}.xlsx`);
      window.Toast.show(`${columns.length}개 컬럼을 xlsx 로 내보냈습니다`, "success");
    } catch (e) {
      window.Toast.show("다운로드 실패: " + (e.message || ""), "error");
    }
  }

  // ───── Annotation xlsx 다운로드/업로드 ─────
  // 현재 테이블 모든 컬럼의 Annotation 을 COLUMN / Key / Value 3열로 내보낸다(컬럼당 여러 행).
  function handleAnnotationDownload(tableName, columns) {
    if (typeof XLSX === "undefined") {
      window.Toast.show("xlsx 라이브러리 로드 실패 — 새로고침 후 다시 시도하세요", "error");
      return;
    }
    const aoa = [["COLUMN", "Key", "Value"]];
    columns.forEach((c) => {
      const ann = c.annotations || {};
      Object.keys(ann).forEach((k) => aoa.push([c.name, k, ann[k] == null ? "" : String(ann[k])]));
    });
    try {
      const ws = XLSX.utils.aoa_to_sheet(aoa);
      ws["!cols"] = [{ wch: 30 }, { wch: 24 }, { wch: 40 }];
      const wb = XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(wb, ws, "Sheet1");
      XLSX.writeFile(wb, `annotation_${tableName}.xlsx`);
      if (aoa.length === 1) {
        window.Toast.show("Annotation 이 없어 헤더만 내보냈습니다(템플릿)", "warn");
      } else {
        window.Toast.show(`${aoa.length - 1}건 Annotation 을 xlsx 로 내보냈습니다`, "success");
      }
    } catch (e) {
      window.Toast.show("다운로드 실패: " + (e.message || ""), "error");
    }
  }

  // COLUMN / Key / Value xlsx 를 읽어, 행마다 해당 컬럼 Annotation 을 즉시 DB 에 반영한다.
  // bulk 엔드포인트가 컬럼별로 ALTER ... ANNOTATIONS (ADD OR REPLACE ...) → 동일 키는 값 Update.
  async function handleAnnotationUpload(ev, owner, tableName, reload) {
    const input = ev.target;
    const file = input.files && input.files[0];
    if (!file) return;
    if (typeof XLSX === "undefined") {
      window.Toast.show("xlsx 라이브러리 로드 실패 — 새로고침 후 다시 시도하세요", "error");
      input.value = "";
      return;
    }
    const reader = new FileReader();
    reader.onload = async () => {
      try {
        const wb = XLSX.read(reader.result, { type: "array" });
        const ws = wb.Sheets[wb.SheetNames[0]];
        if (!ws) throw new Error("시트를 찾을 수 없습니다");
        const rows = XLSX.utils.sheet_to_json(ws, { header: 1, blankrows: false });
        if (!rows.length) throw new Error("빈 파일입니다");

        const header = (rows[0] || []).map((h) => String(h == null ? "" : h).trim().toUpperCase());
        const ci = header.indexOf("COLUMN");
        const ki = header.indexOf("KEY");
        const vi = header.indexOf("VALUE");
        if (ci === -1 || ki === -1 || vi === -1) {
          window.Toast.show("헤더(COLUMN, Key, Value)를 찾을 수 없습니다", "error");
          return;
        }

        const items = [];
        const skipped = [];
        for (let r = 1; r < rows.length; r++) {
          const row = rows[r] || [];
          const col = row[ci] == null ? "" : String(row[ci]).trim();
          const key = row[ki] == null ? "" : String(row[ki]).trim();
          const val = row[vi] == null ? "" : String(row[vi]);
          if (!col || !key) {
            if (col || key) skipped.push(r + 1);
            continue;
          }
          items.push({ name: col, annotation: { name: key, value: val } });
        }
        if (!items.length) {
          window.Toast.show("반영할 Annotation 행이 없습니다(COLUMN·Key 필요)", "warn");
          return;
        }

        await window.API.post(
          `/api/objects/${encodeURIComponent(owner)}/${encodeURIComponent(tableName)}/columns/bulk`,
          { columns: items }
        );
        window.Toast.show(`${items.length}건 Annotation 을 DB 에 반영했습니다`, "success");
        if (skipped.length) {
          window.Toast.show(`COLUMN/Key 누락으로 건너뛴 행: ${skipped.slice(0, 10).join(", ")}`, "warn");
        }
        if (typeof reload === "function") await reload();
      } catch (e) {
        const d = e && e.payload && e.payload.detail;
        const at = d && d.failed_column ? ` (${d.failed_column} 에서 중단)` : "";
        window.Toast.show(errMsg(e, "Annotation 업로드 실패") + at, "error");
      } finally {
        input.value = "";
      }
    };
    reader.onerror = () => {
      window.Toast.show("파일을 읽지 못했습니다", "error");
      input.value = "";
    };
    reader.readAsArrayBuffer(file);
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
