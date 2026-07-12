/**
 * 작성자: 도상훈
 * 파일 용도: 확장 view 메뉴 항목을 OADT2 사이드바에 주입한다.
 */
/**
 * app_extensions.js — 기존 앱 소스를 크게 건드리지 않고 메뉴/라우트 확장 등록.
 */
(function () {
  window.AppExtensions = window.AppExtensions || {};
  window.AppExtensions.routes = Object.assign({}, window.AppExtensions.routes, {
    tuning: {
      label: "AI SQL Tuning Assistant",
      render: () => window.Views.tuningAssistant(),
      dbIndependent: true,
    },
    tuningHistory: {
      label: "Tuning History",
      render: () => window.Views.tuningHistory(),
      dbIndependent: true,
    },
  });

  function insertMenu() {
    const sidenav = document.getElementById("sidenav");
    if (!sidenav || sidenav.querySelector('[data-route="tuning"]')) return;

    const item = document.createElement("div");
    item.className = "nav-item";
    item.dataset.route = "tuning";
    item.innerHTML = "<span>AI SQL Tuning Assistant</span>";

    const history = document.createElement("div");
    history.className = "nav-item";
    history.dataset.route = "tuningHistory";
    history.innerHTML = "<span>Tuning History</span>";

    const sep = sidenav.querySelector(".nav-sep");
    if (sep) {
      sidenav.insertBefore(item, sep);
      sidenav.insertBefore(history, sep);
    } else {
      sidenav.appendChild(item);
      sidenav.appendChild(history);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", insertMenu, { once: true });
  } else {
    insertMenu();
  }
})();
