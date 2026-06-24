/**
 * auth.js — 사전공유 키 로그인 게이트 (api.js 보다 먼저 로드).
 *   - 로드 시 /api/auth/status 확인 → enabled && !authenticated 면 로그인 오버레이
 *   - 로그인 성공 시 location.reload() (쿠키가 이후 모든 요청에 자동 첨부)
 *   - api.js 가 401 을 받으면 window.Auth.showLogin() 으로 재인증 유도 (세션 만료)
 *   - 인증 활성 시 헤더의 로그아웃 버튼 노출
 */
(function () {
  let overlayEl = null;
  let recoverable = false; // 관리자 이메일 등록 시 '키 분실 신고' 노출

  async function fetchStatus() {
    try {
      const res = await fetch("/api/auth/status", { credentials: "same-origin" });
      return await res.json();
    } catch (e) {
      return { enabled: false, authenticated: true };
    }
  }

  function buildOverlay() {
    const el = document.createElement("div");
    el.className = "auth-overlay";
    const recoverBtn = recoverable
      ? `<button type="button" class="btn btn-ghost" id="auth-recover">키 분실 신고</button>`
      : "";
    el.innerHTML = `
      <form class="auth-card" id="auth-form">
        <div class="auth-brand"><div class="brand-mark">O</div><span>Oracle AI Database Test Tool</span></div>
        <h2>접근 키 입력</h2>
        <p class="muted">관리자에게 전달받은 접근 키를 입력하세요.</p>
        <input type="password" id="auth-key" placeholder="접근 키" autocomplete="current-password" autofocus />
        <div class="auth-error" id="auth-error"></div>
        <div class="auth-info" id="auth-info"></div>
        <button type="submit" class="btn btn-primary" id="auth-submit">확인</button>
        ${recoverBtn}
      </form>`;
    return el;
  }

  async function reportLostKey() {
    const btn = document.getElementById("auth-recover");
    const info = document.getElementById("auth-info");
    const err = document.getElementById("auth-error");
    err.textContent = "";
    info.textContent = "";
    btn.disabled = true;
    const label = btn.textContent;
    btn.textContent = "발송 중…";
    try {
      const res = await fetch("/api/auth/recover", {
        method: "POST",
        credentials: "same-origin",
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        info.textContent = `현재 키를 관리자(${data.sent_to || "관리자"}) 에게 메일로 발송했습니다. 관리자에게 문의하세요.`;
        btn.style.display = "none";
      } else {
        err.textContent = (data.detail && data.detail.error) || "신고 처리에 실패했습니다";
      }
    } catch (e) {
      err.textContent = "요청 실패: " + e.message;
    } finally {
      btn.disabled = false;
      btn.textContent = label;
    }
  }

  function showLogin() {
    if (overlayEl) return; // 이미 떠 있음
    overlayEl = buildOverlay();
    document.body.appendChild(overlayEl);

    const form = overlayEl.querySelector("#auth-form");
    const input = overlayEl.querySelector("#auth-key");
    const errEl = overlayEl.querySelector("#auth-error");
    const submit = overlayEl.querySelector("#auth-submit");
    const recoverBtn = overlayEl.querySelector("#auth-recover");
    if (recoverBtn) recoverBtn.addEventListener("click", reportLostKey);
    setTimeout(() => input.focus(), 0);

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const key = input.value.trim();
      if (!key) return;
      errEl.textContent = "";
      submit.disabled = true;
      submit.textContent = "확인 중…";
      try {
        const res = await fetch("/api/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ key }),
        });
        if (res.ok) {
          window.location.reload();
          return;
        }
        const data = await res.json().catch(() => ({}));
        errEl.textContent = (data.detail && data.detail.error) || "접근 키가 올바르지 않습니다";
      } catch (err) {
        errEl.textContent = "요청 실패: " + err.message;
      } finally {
        submit.disabled = false;
        submit.textContent = "확인";
        input.select();
      }
    });
  }

  async function logout() {
    try {
      await fetch("/api/auth/logout", { method: "POST", credentials: "same-origin" });
    } catch (e) {
      /* 무시 */
    }
    window.location.reload();
  }

  function wireLogoutButton() {
    const btn = document.getElementById("logout-btn");
    if (!btn) return;
    btn.style.display = "";
    btn.addEventListener("click", logout);
  }

  async function init() {
    const st = await fetchStatus();
    recoverable = !!st.recoverable;
    if (st.enabled && !st.authenticated) {
      showLogin();
    } else if (st.enabled) {
      wireLogoutButton(); // 로그인된 상태에서만 로그아웃 버튼 노출
    }
  }

  window.Auth = { showLogin, logout, status: fetchStatus };
  window.addEventListener("DOMContentLoaded", init);
})();
