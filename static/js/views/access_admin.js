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
    title.innerHTML = `<h1>접근 키 관리</h1>
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

    document.getElementById("ak-gen").addEventListener("click", () => {
      document.getElementById("ak-new").value = randomKey(24);
    });
    document.getElementById("ak-save").addEventListener("click", saveKey);
    document.getElementById("ak-email-save").addEventListener("click", saveEmail);

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
