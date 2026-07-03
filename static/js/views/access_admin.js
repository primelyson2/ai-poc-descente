/** views/access_admin.js — 메뉴 [접근 키 관리] (상하구조).
 *  관리자가 사전공유 접근 키를 설정/회전/확인한다. config.yaml 의 access_key 를 갱신.
 *  - 상단: 현재 상태(설정됨/미설정) + 현재 키(마스킹·표시토글·복사)
 *  - 하단: 새 키 입력(+ 랜덤 생성) + 저장
 *  키 변경 시 기존 쿠키가 모두 무효화되어 접속자 전원이 재로그인해야 한다.
 */
(function () {
  let revealed = false;
  let currentKey = "";
  let currentEmail = "";

  function errMsg(err, fallback) {
    const p = err && err.payload;
    if (p && p.detail && p.detail.error) return p.detail.error;
    return (err && err.message) || fallback;
  }

  function randomKey(len) {
    const chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789";
    const arr = new Uint32Array(len);
    crypto.getRandomValues(arr);
    return Array.from(arr, (n) => chars[n % chars.length]).join("");
  }

  // ── Select AI Action 노출 정책 (전역 localStorage 키 — DB 무관 도구 설정) ──
  // profile_test.js 의 applyActionGate 가 같은 키를 읽어 runsql/narrate 옵션을 노출/숨김한다.
  const ACTIONS_KEY = "oai.selectai.actions";
  function loadActions() {
    try { return JSON.parse(localStorage.getItem(ACTIONS_KEY) || "{}"); }
    catch (_) { return {}; }
  }
  function bindActionToggle(id, name) {
    const el = document.getElementById(id);
    if (!el) return;
    el.checked = loadActions()[name] === true;
    el.addEventListener("change", () => {
      const obj = loadActions();
      obj[name] = el.checked;
      localStorage.setItem(ACTIONS_KEY, JSON.stringify(obj));
      window.Toast.show(`Select AI Action '${name}' ${el.checked ? "노출" : "숨김"}`, "success");
    });
  }

  // 콤보에 등록된 DB 목록을 채운다(연결 불필요 — 클라이언트 데이터라 unavailable 포함).
  async function fillDbCombo() {
    const sel = document.getElementById("ls-db");
    if (!sel) return;
    try {
      const dbs = await window.API.get("/api/databases");
      sel.innerHTML = "";
      for (const db of dbs || []) {
        const opt = document.createElement("option");
        opt.value = db.name;
        opt.textContent = db.label || db.name;
        sel.appendChild(opt);
      }
      const cur = (window.DBSelector && window.DBSelector.current()) || "";
      if (cur && (dbs || []).some((d) => d.name === cur)) sel.value = cur;
    } catch (e) {
      sel.innerHTML = "";
    }
  }

  // 선택한 DB 의 데이터(키 `base::<db>`)만 모아 base 형태로 내보낸다.
  function exportLocalStorage() {
    const db = document.getElementById("ls-db").value;
    if (!db) {
      window.Toast.show("대상 DB 를 먼저 선택하세요", "warn");
      return;
    }
    const suffix = "::" + db;
    const data = {};
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k.endsWith(suffix)) data[k.slice(0, -suffix.length)] = localStorage.getItem(k);
    }
    if (Object.keys(data).length === 0) {
      window.Toast.show(`"${db}" 에 내보낼 데이터가 없습니다`, "warn");
      return;
    }
    const payload = { _type: "select-ai-localstorage", _version: 2, db, data };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `select-ai-localstorage-${db}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    window.Toast.show(`"${db}" 데이터를 파일로 내보냈습니다`, "success");
  }

  // 업로드한 파일의 데이터를 콤보에서 선택한 DB 스코프로 덮어쓰고(병합) 새로고침한다.
  function importLocalStorage(ev) {
    const input = ev.target;
    const file = input.files && input.files[0];
    if (!file) return;
    const targetDb = document.getElementById("ls-db").value;
    if (!targetDb) {
      window.Toast.show("대상 DB 를 먼저 선택하세요", "warn");
      input.value = "";
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const parsed = JSON.parse(reader.result);
        const data =
          parsed && parsed._type === "select-ai-localstorage" && parsed.data
            ? parsed.data
            : parsed;
        if (!data || typeof data !== "object" || Array.isArray(data)) {
          throw new Error("올바른 형식이 아닙니다");
        }
        let count = 0;
        for (const [base, v] of Object.entries(data)) {
          // base 가 이미 `::` 스코프를 포함하면(옛 전체덤프 파일) 그대로, 아니면 선택 DB 로 스코프.
          const key = base.includes("::") ? base : base + "::" + targetDb;
          localStorage.setItem(key, typeof v === "string" ? v : JSON.stringify(v));
          count++;
        }
        const srcDb = parsed && parsed.db;
        const moved = srcDb && srcDb !== targetDb ? ` ("${srcDb}" → "${targetDb}")` : "";
        window.Toast.show(`${count}개 항목을 "${targetDb}" 로 가져왔습니다${moved}. 새로고침합니다…`, "success");
        setTimeout(() => location.reload(), 800);
      } catch (e) {
        window.Toast.show("가져오기 실패: " + (e.message || "잘못된 파일"), "error");
      } finally {
        input.value = "";
      }
    };
    reader.onerror = () => {
      window.Toast.show("파일을 읽지 못했습니다", "error");
      input.value = "";
    };
    reader.readAsText(file);
  }

  function maskedView() {
    if (!currentKey) return '<span class="muted">미설정</span>';
    return revealed
      ? `<code id="ak-current">${currentKey}</code>`
      : `<code id="ak-current">${"•".repeat(Math.min(currentKey.length, 24))}</code>`;
  }

  async function render() {
    const main = document.getElementById("main");
    main.innerHTML = "";

    const title = document.createElement("div");
    title.className = "view-title";
    title.innerHTML = `<h1>Tool관리</h1>
      <span class="sub">접속에 필요한 사전공유 키를 설정·회전합니다. 사용자는 이 키를 받아 첫 화면에서 입력합니다.</span>`;
    main.appendChild(title);

    const wrap = document.createElement("div");
    wrap.className = "split-vert";
    main.appendChild(wrap);

    // ── 상단: 현재 상태 ──
    const statusPanel = document.createElement("div");
    statusPanel.className = "panel";
    statusPanel.innerHTML = `
      <div class="panel-header">
        <h2>현재 접근 키</h2>
        <span id="ak-status" class="badge"></span>
      </div>
      <div class="panel-body" id="ak-status-body">
        <div class="empty-state"><span class="spinner"></span> 조회 중...</div>
      </div>`;
    wrap.appendChild(statusPanel);

    // ── 하단: 설정/회전 ──
    const formPanel = document.createElement("div");
    formPanel.className = "panel";
    formPanel.innerHTML = `
      <div class="panel-header"><h2>키 설정 / 회전</h2></div>
      <div class="panel-body">
        <div class="field">
          <label for="ak-new">새 접근 키 (최소 8자)</label>
          <div class="row" style="gap:6px; flex-wrap:nowrap;">
            <input type="text" id="ak-new" placeholder="새 키를 입력하거나 랜덤 생성" autocomplete="off" style="flex:1;" />
            <button class="btn" id="ak-gen">랜덤 생성</button>
            <button class="btn btn-primary" id="ak-save">저장</button>
          </div>
          <span class="field-hint">저장하면 config.yaml 에 기록되고 즉시 적용됩니다. <strong>키를 바꾸면 기존 접속자는 모두 재로그인</strong>해야 합니다.</span>
        </div>
        <div class="field" style="margin-top: var(--space-4);">
          <label for="ak-email">관리자 이메일</label>
          <div class="row" style="gap:6px; flex-wrap:nowrap;">
            <input type="email" id="ak-email" placeholder="admin@example.com" autocomplete="off" style="flex:1;" />
            <button class="btn btn-primary" id="ak-email-save">저장</button>
          </div>
          <span class="field-hint">로그인 화면의 <strong>키 분실 신고</strong> 버튼을 누르면 현재 키가 이 주소로 자동 발송됩니다. 발송에는 config.yaml 의 <code>smtp</code> 설정이 필요합니다.</span>
        </div>
      </div>`;
    wrap.appendChild(formPanel);

    // ── Select AI Action 관리 (Action 드롭다운 노출 제어) ──
    const actionPanel = document.createElement("div");
    actionPanel.className = "panel";
    actionPanel.innerHTML = `
      <div class="panel-header"><h2>Select AI Action 관리</h2></div>
      <div class="panel-body">
        <div class="row" style="gap:24px; align-items:center;">
          <label class="row" style="gap:6px; align-items:center; cursor:pointer;">
            <input type="checkbox" id="act-runsql" /> <strong>runsql</strong>
          </label>
          <label class="row" style="gap:6px; align-items:center; cursor:pointer;">
            <input type="checkbox" id="act-narrate" /> <strong>narrate</strong>
          </label>
        </div>
        <span class="field-hint">체크한 Action 만 <strong>AI Profile Test</strong> 화면·팝업의 Action 목록에 노출됩니다. <code>runsql</code>·<code>narrate</code> 는 실제 SQL 실행과 데이터 노출을 동반하므로 <strong>기본 비활성</strong>입니다. (이 설정은 이 브라우저에 저장됩니다.)</span>
      </div>`;
    wrap.appendChild(actionPanel);

    // ── 메뉴 관리 (좌측 메뉴 노출 제어) ──
    // 체크한 메뉴만 좌측 nav 에 노출. Database 관리·Tool관리 는 항상 노출(관리 진입점).
    const menuPanel = document.createElement("div");
    menuPanel.className = "panel";
    const managed = (window.MenuConfig && window.MenuConfig.MANAGED) || [];
    const hiddenMenus = (window.MenuConfig && window.MenuConfig.getHidden()) || [];
    menuPanel.innerHTML = `
      <div class="panel-header"><h2>메뉴 관리</h2></div>
      <div class="panel-body">
        <div class="stack" id="menu-toggles" style="gap:8px;">
          ${managed
            .map(
              (m) => `
          <label class="row" style="gap:8px; align-items:center; cursor:pointer;">
            <input type="checkbox" data-menu-route="${m.route}" ${hiddenMenus.includes(m.route) ? "" : "checked"} />
            <strong>${m.label}</strong>
          </label>`
            )
            .join("")}
        </div>
        <span class="field-hint">체크한 메뉴만 좌측 메뉴에 노출됩니다. <strong>Database 관리·Tool관리</strong> 는 항상 노출됩니다. (이 설정은 이 브라우저에 저장됩니다.)</span>
      </div>`;
    wrap.appendChild(menuPanel);

    // ── 데이터 내보내기 / 가져오기 (localStorage) ──
    const dataPanel = document.createElement("div");
    dataPanel.className = "panel";
    dataPanel.innerHTML = `
      <div class="panel-header"><h2>Local Storage관리</h2></div>
      <div class="panel-body">
        <div class="row" style="gap:6px; flex-wrap:nowrap; align-items:center;">
          <label for="ls-db" class="muted">대상 DB</label>
          <select id="ls-db" style="min-width:160px;"></select>
          <button class="btn" id="ls-export">내보내기 (.json 다운로드)</button>
          <input type="file" id="ls-import-file" accept=".json,application/json" style="display:none;" />
          <button class="btn btn-primary" id="ls-import">가져오기 (파일 선택)</button>
        </div>
        <span class="field-hint"><strong>선택한 DB</strong> 에 저장된 설정·프롬프트(localStorage)만 파일로 내보냅니다. 가져오기는 파일 내용을 <strong>선택한 DB</strong> 로 병합합니다(다른 DB·다른 사용자에게 이식 가능). 같은 이름의 항목은 덮어써지고 페이지가 새로고침됩니다.</span>
      </div>`;
    wrap.appendChild(dataPanel);

    document.getElementById("ak-gen").addEventListener("click", () => {
      document.getElementById("ak-new").value = randomKey(24);
    });
    document.getElementById("ak-save").addEventListener("click", saveKey);
    document.getElementById("ak-email-save").addEventListener("click", saveEmail);

    bindActionToggle("act-runsql", "runsql");
    bindActionToggle("act-narrate", "narrate");

    menuPanel.querySelectorAll("input[data-menu-route]").forEach((cb) => {
      cb.addEventListener("change", () => {
        const route = cb.dataset.menuRoute;
        if (window.MenuConfig) window.MenuConfig.setHidden(route, !cb.checked);
        const label = (managed.find((m) => m.route === route) || {}).label || route;
        window.Toast.show(`메뉴 '${label}' ${cb.checked ? "노출" : "숨김"}`, "success");
      });
    });

    document.getElementById("ls-export").addEventListener("click", exportLocalStorage);
    const importFile = document.getElementById("ls-import-file");
    document.getElementById("ls-import").addEventListener("click", () => importFile.click());
    importFile.addEventListener("change", importLocalStorage);
    fillDbCombo();

    await loadStatus();
  }

  async function loadStatus() {
    const body = document.getElementById("ak-status-body");
    const badge = document.getElementById("ak-status");
    try {
      const data = await window.API.get("/api/auth/key");
      currentKey = data.key || "";
      currentEmail = data.admin_email || "";
      const emailInput = document.getElementById("ak-email");
      if (emailInput) emailInput.value = currentEmail;
      badge.textContent = data.set ? "설정됨" : "미설정";
      badge.className = "badge " + (data.set ? "ok" : "disabled");
      renderStatusBody(body);
    } catch (e) {
      badge.textContent = "오류";
      badge.className = "badge danger";
      body.innerHTML = `<div class="empty-state">조회 실패: ${errMsg(e, "")}</div>`;
    }
  }

  function renderStatusBody(body) {
    if (!currentKey) {
      body.innerHTML = `<div class="muted">아직 접근 키가 설정되지 않았습니다. 인증이 <strong>비활성</strong> 상태이며 누구나 접속할 수 있습니다. 아래에서 키를 설정하세요.</div>`;
      return;
    }
    const emailLine = currentEmail
      ? `<code>${currentEmail}</code>`
      : '<span class="muted">미설정 — 키 분실 복구 비활성</span>';
    body.innerHTML = `
      <div class="row" style="gap:8px; align-items:center;">
        <span class="muted">현재 키:</span>
        ${maskedView()}
        <button class="btn btn-mini" id="ak-toggle">${revealed ? "숨기기" : "표시"}</button>
        <button class="btn btn-mini" id="ak-copy">복사</button>
      </div>
      <div class="row" style="gap:8px; align-items:center; margin-top: var(--space-2);">
        <span class="muted">관리자 이메일:</span> ${emailLine}
      </div>
      <div class="field-hint">이 키를 사용자에게 전달하세요. 화면 첫 진입 시 입력하면 7일간 로그인이 유지됩니다.</div>`;
    document.getElementById("ak-toggle").addEventListener("click", () => {
      revealed = !revealed;
      renderStatusBody(body);
    });
    document.getElementById("ak-copy").addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(currentKey);
        window.Toast.show("접근 키를 복사했습니다", "success");
      } catch (e) {
        window.Toast.show("복사 실패 — 표시 후 수동 복사하세요", "error");
      }
    });
  }

  async function saveKey() {
    const input = document.getElementById("ak-new");
    const key = input.value.trim();
    if (key.length < 8) {
      window.Toast.show("접근 키는 최소 8자 이상이어야 합니다", "error");
      return;
    }
    const btn = document.getElementById("ak-save");
    btn.disabled = true;
    try {
      await window.API.put("/api/auth/key", { key });
      input.value = "";
      revealed = false;
      window.Toast.show("접근 키를 저장했습니다. 사용자에게 새 키를 전달하세요.", "success");
      // 헤더 로그아웃 버튼 노출(이전에 인증 비활성이었다면 이제 활성)
      const lo = document.getElementById("logout-btn");
      if (lo) lo.style.display = "";
      await loadStatus();
    } catch (e) {
      window.Toast.show(errMsg(e, "저장 실패"), "error");
    } finally {
      btn.disabled = false;
    }
  }

  async function saveEmail() {
    const input = document.getElementById("ak-email");
    const email = input.value.trim();
    const btn = document.getElementById("ak-email-save");
    btn.disabled = true;
    try {
      await window.API.put("/api/auth/admin-email", { email });
      window.Toast.show(
        email ? "관리자 이메일을 저장했습니다" : "관리자 이메일을 해제했습니다",
        "success"
      );
      await loadStatus();
    } catch (e) {
      window.Toast.show(errMsg(e, "저장 실패"), "error");
    } finally {
      btn.disabled = false;
    }
  }

  window.Views = window.Views || {};
  window.Views.accessAdmin = render;
})();
