/** tree.js — 단순 트리 컴포넌트.
 *  nodes: [{id, label, type, tag?, subtitle?, children?: [...]}]
 *    tag      — 노드 종류 배지 (예: "TEAM" / "AGENT")
 *    subtitle — name 우측에 muted 로 표시되는 요약 텍스트
 *  onSelect: (node) => void
 */
(function () {
  function create(nodes, { onSelect } = {}) {
    const root = document.createElement("div");
    root.className = "tree";
    const ul = renderList(nodes, onSelect, root);
    root.appendChild(ul);
    return root;
  }

  function renderList(nodes, onSelect, treeRoot) {
    const ul = document.createElement("ul");
    nodes.forEach((node) => {
      const li = document.createElement("li");
      const row = document.createElement("div");
      row.className = "tree-node";
      const hasChildren = node.children && node.children.length > 0;

      // Toggle 버튼 — children 이 있을 때만 클릭 가능
      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "tree-toggle" + (hasChildren ? " has-children" : "");
      toggle.setAttribute("aria-label", "토글");
      toggle.textContent = hasChildren ? "▸" : "";
      row.appendChild(toggle);

      if (node.tag) {
        const tag = document.createElement("span");
        tag.className = "tree-tag tag-" + (node.type || "default");
        tag.textContent = node.tag;
        row.appendChild(tag);
      }

      const label = document.createElement("span");
      label.className = "tree-label";
      label.textContent = node.label;
      row.appendChild(label);

      if (node.subtitle) {
        const sub = document.createElement("span");
        sub.className = "tree-subtitle";
        sub.textContent = node.subtitle;
        row.appendChild(sub);
      }

      li.appendChild(row);

      let childContainer = null;
      if (hasChildren) {
        childContainer = renderList(node.children, onSelect, treeRoot);
        childContainer.style.display = "none";
        li.appendChild(childContainer);
      }

      // 단일 핸들러: 토글 영역 클릭 → 펼침/접힘만, 그 외 → 선택 + onSelect 만
      row.addEventListener("click", (e) => {
        e.stopPropagation();
        const isToggleClick = hasChildren && (e.target === toggle || toggle.contains(e.target));
        if (isToggleClick) {
          const open = childContainer.style.display !== "none";
          childContainer.style.display = open ? "none" : "block";
          toggle.textContent = open ? "▸" : "▾";
          return;
        }
        treeRoot.querySelectorAll(".tree-node.selected").forEach((el) => el.classList.remove("selected"));
        row.classList.add("selected");
        if (onSelect) onSelect(node);
      });

      ul.appendChild(li);
    });
    return ul;
  }

  window.Tree = { create };
})();
