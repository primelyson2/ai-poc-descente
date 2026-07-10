(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.AstaReportTabs = api;
})(typeof window !== "undefined" ? window : globalThis, function () {
  "use strict";

  const TAB_DEFINITIONS = Object.freeze([
    { id: "overview", label: "요약" },
    { id: "before", label: "튜닝 전" },
    { id: "changes", label: "SQL 변경" },
    { id: "after", label: "튜닝 후" },
    { id: "details", label: "상세 분석" },
    { id: "objects", label: "객체 정보" },
  ]);

  const VERDICT_GUIDE = Object.freeze([
    { code: "IMPROVED", meaning: "결과가 일치하고 성능 기준 통과", action: "코드 리뷰와 별도 테스트 후 적용 검토", tone: "success" },
    { code: "ANALYSIS_ONLY", meaning: "튜닝 후보 제안/분석 완료, 성능 개선 여부 미검증", action: "운영 적용 전 Source 실측·동등성 검증", tone: "warning" },
    { code: "NOT_IMPROVED", meaning: "결과는 같지만 충분한 성능 개선 없음", action: "원본 SQL 유지", tone: "warning" },
    { code: "CANDIDATE_FAILED", meaning: "개선 SQL 실행 중 오류 발생", action: "개선 SQL 사용 금지, Run ID 전달", tone: "danger" },
    { code: "NON_EQUIVALENT", meaning: "원본과 개선 SQL 결과/컬럼 구성이 다름", action: "개선 SQL 사용 금지", tone: "danger" },
    { code: "NO_REWRITE", meaning: "안전한 개선안을 생성하지 못함", action: "원본 SQL 유지, 참고사항 보완", tone: "warning" },
    { code: "INSUFFICIENT_EVIDENCE", meaning: "결과 일치 또는 성능 검증 근거 부족", action: "원본 SQL 유지, 재검증 요청", tone: "warning" },
  ]);
  const VERDICT_BY_CODE = new Map(VERDICT_GUIDE.map((item) => [item.code, item]));

  const SECTION_RULES = Object.freeze([
    [2, "결론", "overview"],
    [2, "병목 진단", "overview"],
    [2, "튜닝전/후 수치 비교", "overview"],
    [2, "oracle sql tuning advisor 요약", "overview"],
    [2, "튜닝전 sql", "before"],
    [2, "튜닝전 xplan", "before"],
    [2, "튜닝전 예상 plan", "before"],
    [2, "튜닝후 sql", "after"],
    [2, "튜닝후 xplan", "after"],
    [2, "튜닝후 예상 plan", "after"],
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

  function extractReportVerdict(markdown) {
    const text = String(markdown || "");
    const codePattern = "(IMPROVED|ANALYSIS_ONLY|NOT_IMPROVED|CANDIDATE_FAILED|NON_EQUIVALENT|NO_REWRITE|INSUFFICIENT_EVIDENCE)";
    const patterns = [
      new RegExp("비교\\s*판정[^\\n]*?verdict\\s*=\\s*\\x60?" + codePattern, "i"),
      new RegExp("(?:최종\\s*)?판정\\s*:\\s*(?:\\*\\*)?\\s*\\x60?" + codePattern, "i"),
      new RegExp("\\bverdict\\s*=\\s*\\x60?" + codePattern, "i"),
    ];
    for (const pattern of patterns) {
      const match = text.match(pattern);
      if (match) return String(match[1]).toUpperCase();
    }
    return null;
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
        const rule = RULE_BY_KEY.get(key);
        if (rule.tab === "objects") {
          entries.forEach((entry) => rangesByTab.objects.push({ start: entry.start, end: entry.end }));
          return;
        }
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

  function renderVerdictConclusion(parent, headingRow, verdict) {
    const current = VERDICT_BY_CODE.get(verdict);
    if (!current) return;
    headingRow.className = "tuning-verdict-heading";
    const helpId = "asta-verdict-help";
    const anchor = document.createElement("div");
    anchor.className = "tuning-verdict-help-anchor";
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "tuning-verdict-help-toggle";
    toggle.textContent = "?";
    toggle.setAttribute("aria-label", "판정 기준 설명 보기");
    toggle.setAttribute("aria-controls", helpId);
    toggle.setAttribute("aria-expanded", "false");
    anchor.appendChild(toggle);
    headingRow.appendChild(anchor);

    const summary = document.createElement("section");
    summary.className = `tuning-verdict-summary tuning-verdict-${current.tone}`;
    summary.setAttribute("aria-label", `현재 판정 ${current.code}`);
    appendTextElement(summary, "strong", current.code, "tuning-verdict-badge");
    const copy = document.createElement("div");
    appendTextElement(copy, "span", current.meaning, "tuning-verdict-meaning");
    appendTextElement(copy, "span", `권장 조치 · ${current.action}`, "tuning-verdict-action");
    summary.appendChild(copy);
    parent.appendChild(summary);

    const help = document.createElement("section");
    help.id = helpId;
    help.setAttribute("id", helpId);
    help.className = "tuning-verdict-help";
    help.hidden = true;
    appendTextElement(help, "h3", "판정 기준");
    const table = document.createElement("table");
    table.className = "tuning-verdict-guide";
    const thead = document.createElement("thead");
    const headerRow = document.createElement("tr");
    ["판정", "의미", "권장 조치"].forEach((label) => appendTextElement(headerRow, "th", label));
    thead.appendChild(headerRow);
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    VERDICT_GUIDE.forEach((item) => {
      const row = document.createElement("tr");
      row.className = `tuning-verdict-guide-row${item.code === verdict ? " tuning-verdict-guide-current" : ""}`;
      if (item.code === verdict) row.setAttribute("aria-current", "true");
      appendTextElement(row, "td", item.code);
      appendTextElement(row, "td", item.meaning);
      appendTextElement(row, "td", item.action);
      tbody.appendChild(row);
    });
    table.appendChild(tbody);
    help.appendChild(table);
    anchor.appendChild(help);

    toggle.addEventListener("click", () => {
      help.hidden = !help.hidden;
      toggle.setAttribute("aria-expanded", help.hidden ? "false" : "true");
      anchor.className = help.hidden
        ? "tuning-verdict-help-anchor"
        : "tuning-verdict-help-anchor tuning-verdict-help-open";
    });
  }

  function renderSafeMarkdown(parent, markdown, options = null) {
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
        if (options?.verdict && !options.verdictRendered && heading[1].length === 2 && normalizeHeading(heading[2]) === "결론") {
          options.verdictRendered = true;
          const headingRow = document.createElement("div");
          headingRow.className = "tuning-verdict-heading";
          appendTextElement(headingRow, "h2", heading[2].trim());
          parent.appendChild(headingRow);
          renderVerdictConclusion(parent, headingRow, options.verdict);
        } else {
          appendTextElement(parent, `h${heading[1].length}`, heading[2].trim());
        }
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

  function extractFirstSqlFence(sections) {
    for (const section of sections || []) {
      const match = String(section || "").match(/```sql\s*\n([\s\S]*?)\n```/i);
      if (match) return match[1].replace(/\r\n?/g, "\n").trim();
    }
    return "";
  }

  function extractReportBullet(sections, label) {
    const escaped = String(label).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const pattern = new RegExp(`^\\s*-\\s*${escaped}\\s*:\\s*(.+)$`, "mi");
    for (const section of sections || []) {
      const match = String(section || "").match(pattern);
      if (match) return match[1].trim();
    }
    return "";
  }

  /** Small-lookahead line diff: bounded for long customer SQL and deterministic. */
  function buildSqlLineDiff(beforeSql, afterSql) {
    const before = String(beforeSql || "").replace(/\r\n?/g, "\n").split("\n");
    const after = String(afterSql || "").replace(/\r\n?/g, "\n").split("\n");
    const rows = [];
    let oldIndex = 0;
    let newIndex = 0;
    const lookahead = 40;
    const push = (type, text, oldLine, newLine) => rows.push({ type, text, oldLine, newLine });
    while (oldIndex < before.length || newIndex < after.length) {
      if (oldIndex < before.length && newIndex < after.length && before[oldIndex] === after[newIndex]) {
        push("context", before[oldIndex], oldIndex + 1, newIndex + 1);
        oldIndex += 1;
        newIndex += 1;
        continue;
      }
      if (oldIndex >= before.length) {
        push("add", after[newIndex], null, newIndex + 1);
        newIndex += 1;
        continue;
      }
      if (newIndex >= after.length) {
        push("remove", before[oldIndex], oldIndex + 1, null);
        oldIndex += 1;
        continue;
      }
      let removeCount = null;
      let addCount = null;
      for (let distance = 1; distance <= lookahead; distance += 1) {
        if (removeCount == null && oldIndex + distance < before.length && before[oldIndex + distance] === after[newIndex]) removeCount = distance;
        if (addCount == null && newIndex + distance < after.length && after[newIndex + distance] === before[oldIndex]) addCount = distance;
        if (removeCount != null && addCount != null) break;
      }
      if (addCount != null && (removeCount == null || addCount <= removeCount)) {
        for (let count = 0; count < addCount; count += 1) {
          push("add", after[newIndex], null, newIndex + 1);
          newIndex += 1;
        }
      } else if (removeCount != null) {
        for (let count = 0; count < removeCount; count += 1) {
          push("remove", before[oldIndex], oldIndex + 1, null);
          oldIndex += 1;
        }
      } else {
        push("remove", before[oldIndex], oldIndex + 1, null);
        push("add", after[newIndex], null, newIndex + 1);
        oldIndex += 1;
        newIndex += 1;
      }
    }
    return rows;
  }

  /** Align each contiguous remove/add block so both panes keep matching rows. */
  function alignSqlDiffRows(rows) {
    const aligned = [];
    let index = 0;
    while (index < rows.length) {
      if (rows[index].type === "context") {
        aligned.push({ before: rows[index], after: rows[index] });
        index += 1;
        continue;
      }
      const removed = [];
      const added = [];
      while (index < rows.length && rows[index].type !== "context") {
        if (rows[index].type === "remove") removed.push(rows[index]);
        if (rows[index].type === "add") added.push(rows[index]);
        index += 1;
      }
      const count = Math.max(removed.length, added.length);
      for (let offset = 0; offset < count; offset += 1) {
        aligned.push({ before: removed[offset] || null, after: added[offset] || null });
      }
    }
    return aligned;
  }

  function renderSqlDiffPane(title, side, alignedRows) {
    const pane = document.createElement("section");
    pane.className = `tuning-sql-diff-pane tuning-sql-diff-pane-${side}`;
    appendTextElement(pane, "h3", title, "tuning-sql-diff-pane-title");
    const body = document.createElement("div");
    body.className = "tuning-sql-diff-pane-body";
    alignedRows.forEach((pair) => {
      const item = side === "before" ? pair.before : pair.after;
      const counterpart = side === "before" ? pair.after : pair.before;
      const line = document.createElement("div");
      let state = "empty";
      if (item?.type === "context") state = "context";
      else if (item && side === "before") state = "remove";
      else if (item && side === "after") state = "add";
      line.className = `tuning-sql-diff-line tuning-sql-diff-${state}`;
      const lineNumber = side === "before" ? item?.oldLine : item?.newLine;
      appendTextElement(line, "span", lineNumber == null ? "" : String(lineNumber), "tuning-sql-diff-line-number");
      appendTextElement(line, "span", state === "add" ? "+" : state === "remove" ? "-" : " ", "tuning-sql-diff-marker");
      appendTextElement(line, "code", item?.text || (counterpart ? " " : " "), "tuning-sql-diff-code");
      body.appendChild(line);
    });
    pane.appendChild(body);
    return pane;
  }

  function renderSqlDiff(parent, beforeSql, afterSql, changeSummary, changeLocation) {
    if (!beforeSql || !afterSql) {
      appendTextElement(parent, "p", "비교할 원본 SQL과 튜닝 SQL이 모두 필요합니다.", "tuning-report-empty");
      return;
    }
    const rows = buildSqlLineDiff(beforeSql, afterSql);
    const added = rows.filter((row) => row.type === "add").length;
    const removed = rows.filter((row) => row.type === "remove").length;
    appendTextElement(parent, "h2", "SQL 변경 비교");
    if (changeSummary || changeLocation) {
      const explanation = document.createElement("div");
      explanation.className = "tuning-sql-change-explanation";
      appendTextElement(explanation, "h3", "무엇을 어디서 바꿨나");
      const list = document.createElement("ul");
      if (changeSummary) appendTextElement(list, "li", `변경 내용: ${changeSummary}`);
      if (changeLocation) appendTextElement(list, "li", `변경 위치: ${changeLocation}`);
      explanation.appendChild(list);
      parent.appendChild(explanation);
    }
    appendTextElement(
      parent,
      "p",
      added || removed
        ? `${added}줄 추가 · ${removed}줄 삭제 — +는 튜닝 SQL에 추가, -는 원본 SQL에서 제거된 줄입니다.`
        : "원본 SQL과 튜닝 SQL 사이에 줄 단위 변경이 없습니다.",
      "tuning-sql-diff-summary",
    );
    const alignedRows = alignSqlDiffRows(rows);
    const comparison = document.createElement("div");
    comparison.className = "tuning-sql-side-by-side";
    comparison.appendChild(renderSqlDiffPane("튜닝 전", "before", alignedRows));
    comparison.appendChild(renderSqlDiffPane("튜닝 후", "after", alignedRows));
    parent.appendChild(comparison);
  }

  function renderReportTabs(container, markdown) {
    const classified = classifyReportSections(markdown);
    const verdict = extractReportVerdict(markdown);
    const overviewRenderOptions = { verdict, verdictRendered: false };
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
      if (definition.id === "changes") {
        renderSqlDiff(
          panel,
          extractFirstSqlFence(classified.tabs.before),
          extractFirstSqlFence(classified.tabs.after),
          extractReportBullet(classified.tabs.overview, "SQL 변경 내용"),
          extractReportBullet(classified.tabs.overview, "변경 위치"),
        );
      } else if (!sections.length) appendTextElement(panel, "p", "표시할 내용이 없습니다.", "tuning-report-empty");
      else sections.forEach((section) => renderSafeMarkdown(panel, section, definition.id === "overview" ? overviewRenderOptions : null));
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

  return { TAB_DEFINITIONS, VERDICT_GUIDE, normalizeHeading, extractReportVerdict, classifyReportSections, buildSqlLineDiff, alignSqlDiffRows, renderSafeMarkdown, renderReportTabs };
});
