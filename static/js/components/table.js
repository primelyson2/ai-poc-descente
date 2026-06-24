/** table.js — 단순 테이블 컴포넌트.
 *  columns: [{key, label, format?, align?, headerAlign?, className?}]
 *  rows:    [obj, ...]
 *  options: { onRowClick?(row, tr), rowClassName?(row), emptyText?, className? }
 */
(function () {
  function create(columns, rows, opts = {}) {
    const table = document.createElement("table");
    table.className = "table" + (opts.className ? " " + opts.className : "");

    const thead = document.createElement("thead");
    const trh = document.createElement("tr");
    columns.forEach((c) => {
      const th = document.createElement("th");
      th.textContent = c.label;
      const ha = c.headerAlign || c.align;
      if (ha) th.style.textAlign = ha;
      trh.appendChild(th);
    });
    thead.appendChild(trh);
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    if (!rows || rows.length === 0) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = columns.length;
      td.className = "muted";
      td.style.textAlign = "center";
      td.style.padding = "20px";
      td.textContent = opts.emptyText || "데이터가 없습니다";
      tr.appendChild(td);
      tbody.appendChild(tr);
    } else {
      rows.forEach((row) => {
        const tr = document.createElement("tr");
        if (opts.rowClassName) {
          const cn = opts.rowClassName(row);
          if (cn) tr.className = cn;
        }
        columns.forEach((c) => {
          const td = document.createElement("td");
          if (c.className) td.className = c.className;
          if (c.align) td.style.textAlign = c.align;
          const raw = typeof c.key === "function" ? c.key(row) : row[c.key];
          const value = c.format ? c.format(raw, row) : raw;
          if (value instanceof Node) {
            td.appendChild(value);
          } else if (value === null || value === undefined || value === "") {
            td.innerHTML = '<span class="muted">—</span>';
          } else {
            td.textContent = value;
          }
          tr.appendChild(td);
        });
        if (opts.onRowClick) tr.addEventListener("click", () => opts.onRowClick(row, tr));
        tbody.appendChild(tr);
      });
    }
    table.appendChild(tbody);
    return table;
  }

  window.SimpleTable = { create };
})();
