/** tabs.js — 탭 컴포넌트.
 * Usage:
 *   const el = Tabs.create([
 *     { id: "t1", label: "Tab 1", render: (host) => { host.textContent = "A"; } },
 *     { id: "t2", label: "Tab 2", render: (host) => { host.textContent = "B"; } },
 *   ]);
 *   parent.appendChild(el);
 */
(function () {
  function create(tabs, { active = 0 } = {}) {
    const root = document.createElement("div");
    const tabBar = document.createElement("div");
    tabBar.className = "tabs";
    const body = document.createElement("div");

    let currentIdx = active;
    tabs.forEach((t, idx) => {
      const tabEl = document.createElement("div");
      tabEl.className = "tab" + (idx === currentIdx ? " active" : "");
      tabEl.textContent = t.label;
      tabEl.dataset.idx = idx;
      tabEl.addEventListener("click", () => {
        currentIdx = idx;
        Array.from(tabBar.children).forEach((c, i) => c.classList.toggle("active", i === currentIdx));
        body.innerHTML = "";
        tabs[currentIdx].render(body);
      });
      tabBar.appendChild(tabEl);
    });

    root.appendChild(tabBar);
    root.appendChild(body);
    // 초기 탭 렌더는 root 가 DOM 에 append 된 뒤로 지연 (view 가 document.getElementById 로 접근하는 경우 대비)
    queueMicrotask(() => tabs[currentIdx].render(body));
    return root;
  }

  window.Tabs = { create };
})();
