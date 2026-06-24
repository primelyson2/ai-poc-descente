/** views/database_admin.js — 메뉴 [4] Database 관리 (상하구조).
 *  상단: 등록된 ADB 목록(상태 배지) + "새 데이터베이스" 버튼
 *  하단: 등록/수정 폼 (Wallet zip 업로드 + DSN 선택 + 연결 테스트/삭제)
 *
 *  multipart 업로드라 API 래퍼(JSON) 대신 FormData + raw fetch 를 사용한다.
 */
(function () {
  let mode = "create"; // "create" | "edit"
  let editingName = null;

  async function render() {
    const main = document.getElementById("main");
    main.innerHTML = "";

    const title = document.createElement("div");
    title.className = "view-title";
    title.innerHTML = `<h1>Database 관리</h1>
      <span class="sub">테스트 대상 Oracle Autonomous Database 를 등록·수정합니다. Wallet(zip) 을 업로드하세요.</span>`;
    main.appendChild(title);

    const splitWrap = document.createElement("div");
    splitWrap.className = "split-vert";
    main.appendChild(splitWrap);

    // ── 상단: 목록 ──
    const listPanel = document.createElement("div");
    listPanel.className = "panel";
    listPanel.innerHTML = `
      <div class="panel-header">
        <h2>등록된 데이터베이스</h2>
        <button class="btn btn-primary" id="db-new">+ 새 데이터베이스</button>
      </div>
      <div class="panel-body" id="db-list"><div class="empty-state"><span class="spinner"></span> 조회 중...</div></div>
    `;
    splitWrap.appendChild(listPanel);

    // ── 하단: 폼 ──
    const formPanel = document.createElement("div");
    formPanel.className = "panel";
    formPanel.innerHTML = formTemplate();
    splitWrap.appendChild(formPanel);

    document.getElementById("db-new").addEventListener("click", () => setCreateMode());
    bindForm();
    await loadList();
    setCreateMode();
  }

  function formTemplate() {
    return `
      <div class="panel-header">
        <h2 id="db-form-title">새 데이터베이스 등록</h2>
        <span id="db-form-status" class="badge"></span>
      </div>
      <div class="panel-body">
        <div class="db-form">
          <div class="field">
            <label for="db-f-name">이름 (식별자)</label>
            <input type="text" id="db-f-name" placeholder="예: adb-prod (영문/숫자/_/-)" autocomplete="off" />
            <span class="field-hint">wallets/&lt;이름&gt;/ 폴더와 config 키로 사용됩니다. 등록 후 변경 불가.</span>
          </div>
          <div class="field">
            <label for="db-f-label">표시 이름</label>
            <input type="text" id="db-f-label" placeholder="예: 운영 (ADB)" autocomplete="off" />
            <span class="field-hint">헤더 드롭다운에 표시될 이름 (생략 시 이름과 동일).</span>
          </div>
          <div class="field">
            <label for="db-f-user">DB 사용자</label>
            <input type="text" id="db-f-user" placeholder="예: ADMIN" autocomplete="off" />
          </div>
          <div class="field">
            <label for="db-f-password">DB 비밀번호</label>
            <input type="password" id="db-f-password" autocomplete="new-password" />
            <span class="field-hint" id="db-f-password-hint"></span>
          </div>
          <div class="field field-wide">
            <label for="db-f-wallet">Wallet (zip)</label>
            <input type="file" id="db-f-wallet" accept=".zip" />
            <span class="field-hint" id="db-f-wallet-hint">ADB 콘솔에서 내려받은 Wallet zip 을 그대로 업로드하세요. (tnsnames.ora 포함)</span>
          </div>
          <div class="field">
            <label for="db-f-dsn">DSN (서비스)</label>
            <select id="db-f-dsn"><option value="" disabled selected>Wallet 업로드 후 선택</option></select>
            <span class="field-hint">보통 ..._high / ..._medium / ..._low 중 선택합니다.</span>
          </div>
          <div class="field">
            <label for="db-f-wallet-password">Wallet 비밀번호</label>
            <input type="password" id="db-f-wallet-password" autocomplete="new-password" />
            <span class="field-hint" id="db-f-wallet-password-hint"></span>
          </div>
        </div>
        <div class="row end" style="margin-top: var(--space-4); gap: var(--space-2);">
          <button class="btn btn-ghost" id="db-f-delete" style="display:none;">삭제</button>
          <button class="btn btn-ghost" id="db-f-test" style="display:none;">연결 테스트</button>
          <button class="btn btn-primary" id="db-f-save">저장</button>
        </div>
      </div>
    `;
  }

  // ───── 목록 ─────
  async function loadList() {
    const host = document.getElementById("db-list");
    let dbs = [];
    try {
      dbs = await window.API.get("/api/databases");
    } catch (e) {
      host.innerHTML = '<div class="empty-state muted">목록 조회 실패</div>';
      return;
    }
    host.innerHTML = "";
    const table = window.SimpleTable.create(
      [
        { key: "label", label: "표시 이름" },
        { key: "name", label: "이름" },
        { key: "is_default", label: "기본", align: "center",
          format: (v) => (v ? "★" : "") },
        { key: "status", label: "상태", align: "center", format: statusBadge },
      ],
      dbs,
      {
        onRowClick: (row, tr) => {
          host.querySelectorAll("tr.selected").forEach((el) => el.classList.remove("selected"));
          tr.classList.add("selected");
          setEditMode(row.name);
        },
        emptyText: "등록된 데이터베이스가 없습니다",
      }
    );
    host.appendChild(table);
  }

  function statusBadge(status) {
    const span = document.createElement("span");
    span.className = "badge " + (status === "ok" ? "ok" : "danger");
    span.textContent = status === "ok" ? "정상" : "연결 불가";
    return span;
  }

  // ───── 모드 전환 ─────
  function setCreateMode() {
    mode = "create";
    editingName = null;
    document.getElementById("db-form-title").textContent = "새 데이터베이스 등록";
    setFormStatus("");
    field("name").value = "";
    field("name").disabled = false;
    field("label").value = "";
    field("user").value = "";
    field("password").value = "";
    field("wallet").value = "";
    field("wallet-password").value = "";
    resetDsn();
    document.getElementById("db-f-password-hint").textContent = "필수.";
    document.getElementById("db-f-wallet-hint").textContent =
      "ADB 콘솔에서 내려받은 Wallet zip 을 그대로 업로드하세요. (tnsnames.ora 포함)";
    document.getElementById("db-f-wallet-password-hint").textContent = "Wallet 다운로드 시 지정한 비밀번호.";
    document.getElementById("db-f-delete").style.display = "none";
    document.getElementById("db-f-test").style.display = "none";
    document.querySelectorAll("#db-list tr.selected").forEach((el) => el.classList.remove("selected"));
  }

  async function setEditMode(name) {
    let d;
    try {
      d = await window.API.get(`/api/databases/${encodeURIComponent(name)}`);
    } catch (e) {
      window.Toast.show(errMsg(e, "상세 조회 실패"), "error");
      return;
    }
    mode = "edit";
    editingName = name;
    document.getElementById("db-form-title").textContent = `수정 — ${name}`;
    setFormStatus(d.status === "ok" ? "ok" : "danger", d.status === "ok" ? "정상" : "연결 불가");
    field("name").value = d.name;
    field("name").disabled = true;
    field("label").value = d.label || "";
    field("user").value = d.user || "";
    field("password").value = "";
    field("wallet").value = "";
    field("wallet-password").value = "";
    document.getElementById("db-f-password-hint").textContent = "변경 시에만 입력 (비우면 기존 유지).";
    document.getElementById("db-f-wallet-hint").textContent = d.has_wallet
      ? "Wallet 등록됨. 교체하려면 새 zip 을 업로드하세요 (비우면 기존 유지)."
      : "Wallet 이 없습니다. zip 을 업로드하세요.";
    document.getElementById("db-f-wallet-password-hint").textContent = d.has_wallet_password
      ? "설정됨. 변경하려면 새 값을 입력 후 저장하세요 (비우면 기존 유지)."
      : "변경 시에만 입력.";
    // DSN: 현재 값만 우선 표시 (Wallet 재업로드 시 목록 갱신)
    resetDsn();
    const dsnSel = field("dsn");
    dsnSel.innerHTML = `<option value="${escapeAttr(d.dsn)}" selected>${escapeHtml(d.dsn)}</option>`;
    document.getElementById("db-f-delete").style.display = "";
    document.getElementById("db-f-test").style.display = "";
  }

  // ───── 폼 바인딩 ─────
  function bindForm() {
    field("wallet").addEventListener("change", onWalletSelected);
    document.getElementById("db-f-save").addEventListener("click", onSave);
    document.getElementById("db-f-test").addEventListener("click", onTest);
    document.getElementById("db-f-delete").addEventListener("click", onDelete);
  }

  async function onWalletSelected() {
    const file = field("wallet").files[0];
    if (!file) return;
    const dsnSel = field("dsn");
    const prev = dsnSel.value;
    dsnSel.innerHTML = `<option value="" disabled selected>DSN 분석 중...</option>`;
    const fd = new FormData();
    fd.append("wallet", file);
    try {
      const res = await fetch("/api/databases/parse-wallet", { method: "POST", body: fd });
      const data = await res.json();
      if (!res.ok) throw { payload: data };
      fillDsnOptions(data.dsns || [], prev);
      window.Toast.show(`DSN ${(data.dsns || []).length}개 인식`, "success");
    } catch (e) {
      resetDsn();
      window.Toast.show(errMsg(e, "Wallet 분석 실패"), "error");
    }
  }

  function fillDsnOptions(dsns, preferred) {
    const sel = field("dsn");
    sel.innerHTML = "";
    if (dsns.length === 0) {
      sel.innerHTML = `<option value="" disabled selected>DSN 을 찾지 못했습니다</option>`;
      return;
    }
    // 우선순위: 직전 선택값 → ..._high → 첫 번째
    let chosen = dsns.includes(preferred) ? preferred : null;
    if (!chosen) chosen = dsns.find((d) => /_high$/i.test(d)) || dsns[0];
    for (const d of dsns) {
      const opt = document.createElement("option");
      opt.value = d;
      opt.textContent = d;
      if (d === chosen) opt.selected = true;
      sel.appendChild(opt);
    }
  }

  function resetDsn() {
    field("dsn").innerHTML = `<option value="" disabled selected>Wallet 업로드 후 선택</option>`;
  }

  // ───── 저장 (생성/수정) ─────
  async function onSave() {
    const name = field("name").value.trim();
    const user = field("user").value.trim();
    const dsn = field("dsn").value;
    const label = field("label").value.trim();
    const password = field("password").value;
    const walletPw = field("wallet-password").value;
    const walletFile = field("wallet").files[0];

    if (!name) return window.Toast.show("이름을 입력하세요", "warn");
    if (!user) return window.Toast.show("DB 사용자를 입력하세요", "warn");
    if (!dsn) return window.Toast.show("DSN 을 선택하세요 (Wallet 업로드 필요)", "warn");
    if (mode === "create" && !password) return window.Toast.show("DB 비밀번호를 입력하세요", "warn");
    if (mode === "create" && !walletFile) return window.Toast.show("Wallet zip 을 업로드하세요", "warn");

    const fd = new FormData();
    fd.append("user", user);
    fd.append("dsn", dsn);
    fd.append("label", label);
    fd.append("password", password);
    fd.append("wallet_password", walletPw);
    if (walletFile) fd.append("wallet", walletFile);

    const saveBtn = document.getElementById("db-f-save");
    saveBtn.disabled = true;
    saveBtn.textContent = "저장 중...";
    try {
      let url, method;
      if (mode === "create") {
        fd.append("name", name);
        url = "/api/databases";
        method = "POST";
      } else {
        // 수정 시 wallet_password 는 사용자가 값을 넣었을 때만 교체
        fd.append("replace_wallet_password", walletPw ? "true" : "false");
        url = `/api/databases/${encodeURIComponent(name)}`;
        method = "PUT";
      }
      const res = await fetch(url, { method, body: fd });
      const data = await res.json();
      if (!res.ok) throw { payload: data };

      await window.DBSelector.reload();
      await loadList();
      if (data.error) {
        // 설정은 저장됐지만 연결 실패 — 수정 모드로 두고 오류 노출
        setEditMode(name);
        window.Toast.show("저장됨 — 연결 실패: " + data.error, "error", 6000);
      } else {
        window.Toast.show(mode === "create" ? "등록 완료" : "수정 완료", "success");
        setEditMode(name);
      }
    } catch (e) {
      window.Toast.show(errMsg(e, "저장 실패"), "error", 6000);
    } finally {
      saveBtn.disabled = false;
      saveBtn.textContent = "저장";
    }
  }

  // ───── 연결 테스트 ─────
  async function onTest() {
    if (!editingName) return;
    const btn = document.getElementById("db-f-test");
    btn.disabled = true;
    btn.textContent = "테스트 중...";
    try {
      const data = await window.API.post(`/api/databases/${encodeURIComponent(editingName)}/test`, {});
      if (data.ok) {
        setFormStatus("ok", "정상");
        window.Toast.show("연결 성공", "success");
      } else {
        setFormStatus("danger", "연결 불가");
        window.Toast.show("연결 실패: " + (data.error || ""), "error", 6000);
      }
      await window.DBSelector.reload();
      await loadList();
    } catch (e) {
      window.Toast.show(errMsg(e, "테스트 실패"), "error");
    } finally {
      btn.disabled = false;
      btn.textContent = "연결 테스트";
    }
  }

  // ───── 삭제 ─────
  async function onDelete() {
    if (!editingName) return;
    if (!window.confirm(`'${editingName}' 등록을 삭제할까요? Wallet 폴더도 함께 삭제됩니다.`)) return;
    const btn = document.getElementById("db-f-delete");
    btn.disabled = true;
    try {
      await window.API.delete(`/api/databases/${encodeURIComponent(editingName)}`);
      window.Toast.show("삭제 완료", "success");
      await window.DBSelector.reload();
      await loadList();
      setCreateMode();
    } catch (e) {
      window.Toast.show(errMsg(e, "삭제 실패"), "error", 6000);
    } finally {
      btn.disabled = false;
    }
  }

  // ───── 유틸 ─────
  function field(suffix) {
    return document.getElementById("db-f-" + suffix);
  }
  function setFormStatus(kind, text) {
    const el = document.getElementById("db-form-status");
    if (!kind) {
      el.textContent = "";
      el.className = "badge";
      return;
    }
    el.textContent = text;
    el.className = "badge " + kind;
  }

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
  window.Views.databaseAdmin = render;
})();
