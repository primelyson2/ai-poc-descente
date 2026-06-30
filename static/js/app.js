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
    api:       { render: () => window.Views.apiAdmin(),       label: "API관리" },
    databases: { render: () => window.Views.databaseAdmin(),  label: "Database 관리" },
    access:    { render: () => window.Views.accessAdmin(),    label: "Tool관리" },
  };
  // DB 비의존 라우트 — 접속 가능한 DB 가 없어도 진입 가능(등록/복구/키 관리 경로).
  // 'api' 는 현재 서버 로직 없는 프런트 전용 테스트 버전이라 DB 없이도 진입 가능.
  const DB_INDEPENDENT = new Set(["databases", "access", "api"]);
  const DEFAULT_ROUTE = "profiles";

  function currentRoute() {
    const hash = (window.location.hash || "").replace(/^#\/?/, "");
    return ROUTES[hash] ? hash : DEFAULT_ROUTE;
  }

  function setActiveNav(route) {
    document.querySelectorAll(".nav-item").forEach((el) => {
      el.classList.toggle("active", el.dataset.route === route);
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

  function init() {
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
