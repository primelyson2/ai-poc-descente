/** toast.js — 우상단 토스트 메시지. */
(function () {
  const container = document.getElementById("toast-container");

  function show(message, kind = "info", durationMs = 3500) {
    const el = document.createElement("div");
    el.className = `toast ${kind}`;
    el.textContent = message;
    container.appendChild(el);
    setTimeout(() => {
      el.style.opacity = "0";
      el.style.transition = "opacity 0.2s";
      setTimeout(() => el.remove(), 220);
    }, durationMs);
  }

  window.Toast = { show };
})();
