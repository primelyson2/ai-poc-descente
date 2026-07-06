(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.AstaReportTabs = api;
})(typeof window !== "undefined" ? window : globalThis, function () {
  "use strict";

  const TAB_DEFINITIONS = Object.freeze([
    { id: "overview", label: "요약" },
    { id: "before", label: "튜닝 전" },
    { id: "after", label: "튜닝 후" },
    { id: "details", label: "상세 분석" },
    { id: "objects", label: "객체 정보" },
  ]);

  const SECTION_RULES = Object.freeze([
    [2, "결론", "overview"],
    [2, "병목 진단", "overview"],
    [2, "튜닝전/후 수치 비교", "overview"],
    [2, "oracle sql tuning advisor 요약", "overview"],
    [2, "튜닝전 sql", "before"],
    [2, "튜닝전 xplan", "before"],
    [2, "튜닝후 sql", "after"],
    [2, "튜닝후 xplan", "after"],
    [3, "사용자 참고사항 반영", "details"],
    [3, "과거 유사 튜닝 사례 - 참고 정보", "details"],
    [3, "oracle sql tuning advisor 요약", "overview"],
    [3, "dba 검토 사항", "details"],
    [2, "작업 수행 이력", "details"],
    [2, "단계별 수행 체크", "details"],
    [2, "테이블 통계 및 인덱스 정보", "objects"],
    [3, "테이블 통계", "objects"],
  ]);

  function normalizeHeading(value) {
    return String(value || "")
      .normalize("NFC")
      .replace(/[\u2010-\u2015\u2212]/g, "-")
      .replace(/\s+/g, " ")
      .trim()
      .replace(/튜닝\s+전/g, "튜닝전")
      .replace(/튜닝\s+후/g, "튜닝후")
      .replace(/\s*-\s*/g, " - ")
      .toLowerCase();
  }

  const RULE_BY_KEY = new Map(SECTION_RULES.map(([level, heading, tab]) => [
    `${level}:${normalizeHeading(heading)}`,
    { level, heading: normalizeHeading(heading), tab },
  ]));

  function parseHeadings(markdown) {
    const text = String(markdown || "").replace(/\r\n?/g, "\n");
    const lines = text.split("\n");
    const headings = [];
    let fenced = false;
    let fenceMarker = "";
    let offset = 0;
    lines.forEach((line, index) => {
      const fence = line.match(/^\s*(`{3,}|~{3,})/);
      if (fence) {
        const marker = fence[1][0];
        if (!fenced) { fenced = true; fenceMarker = marker; }
        else if (marker === fenceMarker) { fenced = false; fenceMarker = ""; }
      } else if (!fenced) {
        const match = line.match(/^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$/);
        if (match) {
          headings.push({
            level: match[1].length,
            title: match[2].trim(),
            start: offset,
            line: index + 1,
          });
        }
      }
      offset += line.length + (index < lines.length - 1 ? 1 : 0);
    });
    headings.forEach((heading, index) => {
      heading.end = text.length;
      for (let next = index + 1; next < headings.length; next += 1) {
        if (headings[next].level <= heading.level) {
          heading.end = headings[next].start;
          break;
        }
      }
    });
    return { text, headings };
  }

  function mergeRanges(ranges) {
    const sorted = ranges.slice().sort((left, right) => left.start - right.start || left.end - right.end);
    const merged = [];
    sorted.forEach((range) => {
      const last = merged[merged.length - 1];
      if (last && range.start <= last.end) last.end = Math.max(last.end, range.end);
      else merged.push({ ...range });
    });
    return merged;
  }

  function classifyReportSections(markdown) {
    const parsed = parseHeadings(markdown);
    const occurrences = new Map();
    parsed.headings.forEach((heading) => {
      const key = `${heading.level}:${normalizeHeading(heading.title)}`;
      if (!RULE_BY_KEY.has(key)) return;
      const entries = occurrences.get(key) || [];
      entries.push(heading);
      occurrences.set(key, entries);
    });
    const rangesByTab = Object.fromEntries(TAB_DEFINITIONS.map((tab) => [tab.id, []]));
    const reasonCodes = [];
    occurrences.forEach((entries, key) => {
      if (entries.length !== 1) {
        if (!reasonCodes.includes("AMBIGUOUS_REPORT_SECTION")) reasonCodes.push("AMBIGUOUS_REPORT_SECTION");
        return;
      }
      const rule = RULE_BY_KEY.get(key);
      rangesByTab[rule.tab].push({ start: entries[0].start, end: entries[0].end });
    });
    const tabs = {};
    TAB_DEFINITIONS.forEach((tab) => {
      tabs[tab.id] = mergeRanges(rangesByTab[tab.id]).map((range) => parsed.text.slice(range.start, range.end).trim());
    });
    return { tabs, reasonCodes };
  }

  function appendTextElement(parent, tagName, text, className) {
    const element = document.createElement(tagName);
    if (className) element.className = className;
    element.textContent = text;
    parent.appendChild(element);
    return element;
  }

  function splitTableRow(line) {
    return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
  }

  function renderTable(parent, lines, start) {
    if (start + 1 >= lines.length || !/^\s*\|?\s*:?-{3,}/.test(lines[start + 1])) return 0;
    const header = splitTableRow(lines[start]);
    const separator = splitTableRow(lines[start + 1]);
    if (header.length !== separator.length || !separator.every((cell) => /^:?-{3,}:?$/.test(cell))) return 0;
    const table = document.createElement("table");
    table.className = "tuning-report-table";
    const thead = document.createElement("thead");
    const headerRow = document.createElement("tr");
    header.forEach((cell) => appendTextElement(headerRow, "th", cell));
    thead.appendChild(headerRow);
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    let cursor = start + 2;
    while (cursor < lines.length && /^\s*\|.*\|\s*$/.test(lines[cursor])) {
      const cells = splitTableRow(lines[cursor]);
      const row = document.createElement("tr");
      header.forEach((_, index) => appendTextElement(row, "td", cells[index] || ""));
      tbody.appendChild(row);
      cursor += 1;
    }
    table.appendChild(tbody);
    parent.appendChild(table);
    return cursor - start;
  }

  function renderSafeMarkdown(parent, markdown) {
    const lines = String(markdown || "").replace(/\r\n?/g, "\n").split("\n");
    let index = 0;
    while (index < lines.length) {
      const line = lines[index];
      const fence = line.match(/^\s*(`{3,}|~{3,})([^\s]*)\s*$/);
      if (fence) {
        const marker = fence[1][0];
        const codeLines = [];
        index += 1;
        while (index < lines.length && !new RegExp(`^\\s*${marker}{3,}\\s*$`).test(lines[index])) {
          codeLines.push(lines[index]);
          index += 1;
        }
        if (index < lines.length) index += 1;
        const pre = document.createElement("pre");
        pre.className = "tuning-report-code";
        const code = document.createElement("code");
        if (fence[2]) code.setAttribute("data-language", fence[2].toLowerCase());
        code.textContent = codeLines.join("\n");
        pre.appendChild(code);
        parent.appendChild(pre);
        continue;
      }
      const heading = line.match(/^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$/);
      if (heading) {
        appendTextElement(parent, `h${heading[1].length}`, heading[2].trim());
        index += 1;
        continue;
      }
      const tableLength = line.includes("|") ? renderTable(parent, lines, index) : 0;
      if (tableLength) { index += tableLength; continue; }
      const list = line.match(/^\s*(?:[-*+] |\d+[.)] )(.*)$/);
      if (list) {
        const ordered = /^\s*\d/.test(line);
        const listElement = document.createElement(ordered ? "ol" : "ul");
        while (index < lines.length) {
          const item = lines[index].match(/^\s*(?:[-*+] |\d+[.)] )(.*)$/);
          if (!item || /^\s*\d/.test(lines[index]) !== ordered) break;
          appendTextElement(listElement, "li", item[1]);
          index += 1;
        }
        parent.appendChild(listElement);
        continue;
      }
      if (!line.trim()) { index += 1; continue; }
      const paragraph = [line.trim()];
      index += 1;
      while (index < lines.length && lines[index].trim() && !/^(#{1,6})[ \t]+/.test(lines[index]) && !/^\s*(`{3,}|~{3,})/.test(lines[index])) {
        if (lines[index].includes("|") && renderTable.length) break;
        paragraph.push(lines[index].trim());
        index += 1;
      }
      appendTextElement(parent, "p", paragraph.join(" "));
    }
  }

  function renderReportTabs(container, markdown) {
    const classified = classifyReportSections(markdown);
    const tabList = document.createElement("div");
    tabList.className = "tuning-report-tablist";
    tabList.setAttribute("role", "tablist");
    tabList.setAttribute("aria-label", "SQL 튜닝 결과서 구역");
    const panelHost = document.createElement("div");
    panelHost.className = "tuning-report-panels";
    const tabs = [];
    const panels = [];

    const activate = (nextIndex, focus) => {
      tabs.forEach((tab, index) => {
        const selected = index === nextIndex;
        tab.setAttribute("aria-selected", selected ? "true" : "false");
        tab.tabIndex = selected ? 0 : -1;
        panels[index].hidden = !selected;
      });
      panels[nextIndex].scrollTop = 0;
      if (typeof container.scrollTo === "function") container.scrollTo({ top: 0, behavior: "auto" });
      if (focus) tabs[nextIndex].focus();
    };

    TAB_DEFINITIONS.forEach((definition, index) => {
      const tabId = `asta-report-tab-${definition.id}`;
      const panelId = `asta-report-panel-${definition.id}`;
      const tab = document.createElement("button");
      tab.type = "button";
      tab.id = tabId;
      tab.className = "tuning-report-tab";
      tab.textContent = definition.label;
      tab.setAttribute("role", "tab");
      tab.setAttribute("aria-controls", panelId);
      tab.setAttribute("aria-selected", index === 0 ? "true" : "false");
      tab.tabIndex = index === 0 ? 0 : -1;
      const panel = document.createElement("section");
      panel.id = panelId;
      panel.className = "tuning-report-panel";
      panel.setAttribute("role", "tabpanel");
      panel.setAttribute("aria-labelledby", tabId);
      panel.setAttribute("data-asta-report-panel", definition.id);
      panel.hidden = index !== 0;
      const sections = classified.tabs[definition.id];
      if (!sections.length) appendTextElement(panel, "p", "표시할 내용이 없습니다.", "tuning-report-empty");
      else sections.forEach((section) => renderSafeMarkdown(panel, section));
      tab.addEventListener("click", () => activate(index, false));
      tab.addEventListener("keydown", (event) => {
        const keys = { ArrowRight: (index + 1) % tabs.length, ArrowLeft: (index - 1 + tabs.length) % tabs.length, Home: 0, End: tabs.length - 1 };
        if (!(event.key in keys)) return;
        event.preventDefault();
        activate(keys[event.key], true);
      });
      tabs.push(tab);
      panels.push(panel);
      tabList.appendChild(tab);
      panelHost.appendChild(panel);
    });
    container.replaceChildren(tabList, panelHost);
    return { tabs, panels, reasonCodes: classified.reasonCodes };
  }

  return { TAB_DEFINITIONS, normalizeHeading, classifyReportSections, renderSafeMarkdown, renderReportTabs };
});
