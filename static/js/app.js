/**
 * app.js — 해시 라우터 + 메뉴 활성화 + DB 변경 시 현재 view 재렌더.
 */
(function () {
  const ROUTES = {
    objects:   { render: () => window.Views.objectMeta(),     label: "AI Profile Object Meta" },
    profiles:  { render: () => window.Views.profileTest(),    label: "AI Profile Test" },
    agents:    { render: () => window.Views.agentTest(),      label: "AI Agent Team Test" },
    chat:      { render: () => window.Views.aiChat(),         label: "AI Chat" },
    nl2sql:    { render: () => window.Views.nl2sql(),         label: "Select AI Test - Table list" },
    predefined:{ render: () => window.Views.predefinedQuery(), label: "Select AI Test - Predefined Query" },
    persona:   { render: () => window.Views.personaAnalysis(), label: "Select AI Test - 페르소나분석" },
    api:       { render: () => window.Views.apiAdmin(),       label: "API관리" },
    databases: { render: () => window.Views.databaseAdmin(),  label: "Database 관리" },
    access:    { render: () => window.Views.accessAdmin(),    label: "Tool관리" },
  };
  Object.assign(ROUTES, window.AppExtensions?.routes || {});
  // DB 비의존 라우트 — 접속 가능한 DB 가 없어도 진입 가능(등록/복구/키 관리 경로).
  // 'api' 는 현재 서버 로직 없는 프런트 전용 테스트 버전이라 DB 없이도 진입 가능.
  const DB_INDEPENDENT = new Set(["databases", "access", "api"]);
  Object.entries(window.AppExtensions?.routes || {}).forEach(([route, config]) => {
    if (config?.dbIndependent) DB_INDEPENDENT.add(route);
  });
  const DEFAULT_ROUTE = "profiles";
  const NAV_COLLAPSED_KEY = "oadt2.nav.collapsed";

  // ── 메뉴 노출 관리 ──────────────────────────────────────────────
  // Tool관리(access) 화면의 "메뉴 관리"에서 좌측 메뉴별 조회여부를 켜고 끈다.
  // Database 관리(databases)·Tool관리(access) 는 관리 진입점이라 항상 노출한다.
  // 설정은 전역 localStorage 키(DB 무관 도구 설정) 에 "숨긴 라우트 배열" 로 저장.
  const MENU_KEY = "oai.menu.hidden";
  const ALWAYS_ON = new Set(["databases", "access"]);
  // nav 순서(index.html)와 동일한 순서로 관리 대상 메뉴를 정의한다.
  const MANAGED_MENUS = [
    { route: "profiles",   label: "AI Profile Test" },
    { route: "agents",     label: "AI Agent Team Test" },
    { route: "objects",    label: "AI Profile Object Meta" },
    { route: "nl2sql",     label: "Select AI Test - Table list" },
    { route: "predefined", label: "Select AI Test - Predefined Query" },
    { route: "persona",    label: "Select AI Test - 페르소나분석" },
    { route: "chat",       label: "AI Chat" },
    { route: "api",        label: "API관리(개발중)" },
  ];
  function getHiddenMenus() {
    try {
      const arr = JSON.parse(localStorage.getItem(MENU_KEY) || "[]");
      return Array.isArray(arr) ? arr.filter((r) => !ALWAYS_ON.has(r)) : [];
    } catch (_) { return []; }
  }
  function isMenuHidden(route) {
    return !ALWAYS_ON.has(route) && getHiddenMenus().includes(route);
  }
  function firstVisibleRoute() {
    const hidden = getHiddenMenus();
    const m = MANAGED_MENUS.find((x) => !hidden.includes(x.route));
    return m ? m.route : "databases"; // 모두 숨겨도 항상 노출되는 관리 메뉴로 폴백
  }
  function applyMenuVisibility() {
    const hidden = getHiddenMenus();
    document.querySelectorAll(".nav-item").forEach((el) => {
      const r = el.dataset.route;
      el.style.display = r && hidden.includes(r) && !ALWAYS_ON.has(r) ? "none" : "";
    });
  }

  function currentRoute() {
    const hash = (window.location.hash || "").replace(/^#\/?/, "");
    let route = ROUTES[hash] ? hash : DEFAULT_ROUTE;
    // 숨긴 메뉴로 진입하면 첫 노출 메뉴로 대체(직접 URL/이전 hash 대비).
    if (isMenuHidden(route)) route = firstVisibleRoute();
    return route;
  }

  function setActiveNav(route) {
    document.querySelectorAll(".nav-item").forEach((el) => {
      el.classList.toggle("active", el.dataset.route === route);
    });
  }

  function setNavCollapsed(collapsed, persist = true) {
    const shell = document.querySelector(".app-shell");
    const button = document.getElementById("nav-toggle");
    if (!shell) return;
    shell.classList.toggle("nav-collapsed", Boolean(collapsed));
    if (button) {
      button.setAttribute("aria-expanded", String(!collapsed));
      button.setAttribute("aria-label", collapsed ? "메뉴 펼치기" : "메뉴 접기");
      button.title = collapsed ? "메뉴 펼치기" : "메뉴 접기";
    }
    if (persist) localStorage.setItem(NAV_COLLAPSED_KEY, collapsed ? "1" : "0");
  }

  function initNavToggle() {
    const saved = localStorage.getItem(NAV_COLLAPSED_KEY);
    const shouldCollapse = saved == null ? window.matchMedia("(max-width: 720px)").matches : saved === "1";
    setNavCollapsed(shouldCollapse, saved != null);
    document.addEventListener("click", (event) => {
      const button = event.target?.closest?.("#nav-toggle");
      if (!button) return;
      event.preventDefault();
      const collapsed = document.querySelector(".app-shell")?.classList.contains("nav-collapsed");
      setNavCollapsed(!collapsed);
    });
  }

  // 렌더 직렬화 — 뷰 render() 들이 async 라, 직전 렌더가 끝나기 전에 다음 렌더가
  // 시작하면 늦게 도착한 API 응답이 새 화면의 #main 에 함께 append 되어 두 메뉴가
  // 겹쳐 보인다. 체인으로 묶어 한 번에 하나씩만 실행한다.
  let inFlight = Promise.resolve();
  function scheduleRender() {
    inFlight = inFlight.then(render).catch(() => {});
    return inFlight;
  }

  function renderNoDatabase(main) {
    // 접속 가능한 DB 가 없을 때의 안내 화면. Database 관리에서 등록/연결을 유도한다.
    main.innerHTML = `
      <div class="empty-state stack" style="gap: var(--space-4);">
        <div style="font-size: var(--fs-lg); color: var(--text);">접속 가능한 DB가 없습니다</div>
        <div>등록된 데이터베이스가 없거나 모두 연결에 실패했습니다.<br/>Database 관리에서 DB를 등록하거나 연결 상태를 확인하세요.</div>
        <div class="row" style="justify-content: center;">
          <button class="btn btn-primary" id="goto-db-admin">Database 관리로 이동</button>
          <button class="btn btn-ghost" id="retry-db">다시 시도</button>
        </div>
      </div>`;
    const go = document.getElementById("goto-db-admin");
    if (go) go.addEventListener("click", () => { window.location.hash = "#/databases"; });
    const retry = document.getElementById("retry-db");
    if (retry) retry.addEventListener("click", async () => {
      if (window.DBSelector) await window.DBSelector.reload();
      scheduleRender();
    });
  }

  async function render() {
    const route = currentRoute();
    setActiveNav(route);
    const main = document.getElementById("main");

    // DB 상태를 아직 모르면(첫 populate 전) 렌더를 미룬다. ready 후 waitDb 가 재호출.
    if (!window.DBSelector || !window.DBSelector.ready) {
      main.innerHTML = '<div class="empty-state"><span class="spinner"></span> Loading...</div>';
      return;
    }

    // Database 관리·접근 키 관리 화면은 DB 가 없어도 진입 가능해야 한다(등록/복구/키 관리 경로).
    // 그 외 데이터 화면은 접속 가능한 DB 가 없으면 안내 화면으로 대체.
    if (!DB_INDEPENDENT.has(route) && window.DBSelector && !window.DBSelector.hasAvailable()) {
      renderNoDatabase(main);
      return;
    }

    main.innerHTML = '<div class="empty-state"><span class="spinner"></span> Loading...</div>';
    try {
      await ROUTES[route].render();
    } catch (err) {
      console.error(err);
      main.innerHTML = `<div class="empty-state">렌더링 실패: ${err.message}</div>`;
      window.Toast.show("뷰 렌더링 실패: " + err.message, "error");
    }
  }

  // Tool관리 화면(access_admin.js)이 메뉴 노출을 켜고 끌 때 쓴다.
  window.MenuConfig = {
    MANAGED: MANAGED_MENUS,
    ALWAYS_ON,
    getHidden: getHiddenMenus,
    isHidden: isMenuHidden,
    apply: applyMenuVisibility,
    setHidden(route, hidden) {
      if (ALWAYS_ON.has(route)) return; // 항상 노출 메뉴는 무시
      const set = new Set(getHiddenMenus());
      if (hidden) set.add(route); else set.delete(route);
      localStorage.setItem(MENU_KEY, JSON.stringify([...set]));
      applyMenuVisibility();
      // 지금 보고 있는 메뉴를 숨겼다면 첫 노출 메뉴로 이동.
      const rawHash = (window.location.hash || "").replace(/^#\/?/, "");
      if (hidden && rawHash === route) scheduleRender();
    },
  };

  function init() {
    initNavToggle();
    applyMenuVisibility();
    document.querySelectorAll(".nav-item").forEach((el) => {
      el.addEventListener("click", () => {
        window.location.hash = `#/${el.dataset.route}`;
      });
    });
    if (!window.location.hash) {
      window.location.hash = `#/${DEFAULT_ROUTE}`;
    }
    window.addEventListener("hashchange", scheduleRender);
    window.addEventListener("db:changed", () => {
      // 현재 view 재렌더. (선택된 DB 가 모든 후속 API 호출에 자동 첨부됨)
      scheduleRender();
    });

    // DBSelector populate 가 끝나면(ready) 첫 렌더. 등록 DB 가 0개여도 ready 는
    // true 가 되므로, '접속 가능한 DB가 없습니다' 화면이 정상적으로 노출된다.
    const waitDb = setInterval(() => {
      if (window.DBSelector && window.DBSelector.ready) {
        clearInterval(waitDb);
        scheduleRender();
      }
    }, 50);
    setTimeout(() => clearInterval(waitDb), 5000); // fail-safe
  }

  window.addEventListener("DOMContentLoaded", init);
})();
