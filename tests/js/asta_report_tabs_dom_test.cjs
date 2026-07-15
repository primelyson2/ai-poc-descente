"use strict";

const assert = require("node:assert/strict");

class FakeElement {
  constructor(tagName) {
    this.tagName = String(tagName).toUpperCase();
    this.children = [];
    this.attributes = {};
    this.eventListeners = {};
    this.hidden = false;
    this.textContent = "";
    this.className = "";
    this.parentNode = null;
    this.tabIndex = 0;
    this.scrollTop = 0;
  }
  append(...nodes) { nodes.forEach((node) => this.appendChild(node)); }
  appendChild(node) { node.parentNode = this; this.children.push(node); return node; }
  replaceChildren(...nodes) { this.children = []; this.append(...nodes); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name] ?? null; }
  addEventListener(type, listener) { (this.eventListeners[type] ||= []).push(listener); }
  dispatchEvent(event) {
    event.target ||= this;
    event.currentTarget = this;
    event.preventDefault ||= () => { event.defaultPrevented = true; };
    (this.eventListeners[event.type] || []).forEach((listener) => listener(event));
  }
  focus() { fakeDocument.activeElement = this; }
  scrollTo(options) { this.scrollTop = options?.top || 0; }
  matches(selector) {
    if (selector.startsWith(".")) return this.className.split(/\s+/).includes(selector.slice(1));
    const role = selector.match(/^\[role="([^"]+)"\]$/);
    if (role) return this.getAttribute("role") === role[1];
    const data = selector.match(/^\[([^=]+)="([^"]+)"\]$/);
    if (data) return this.getAttribute(data[1]) === data[2];
    if (selector === "table" || selector === "pre" || selector === "code") return this.tagName === selector.toUpperCase();
    if (selector === "pre code") return false;
    return false;
  }
  querySelectorAll(selector) {
    if (selector === "pre code") {
      return this.querySelectorAll("pre").flatMap((pre) => pre.querySelectorAll("code"));
    }
    const result = [];
    for (const child of this.children) {
      if (child.matches(selector)) result.push(child);
      result.push(...child.querySelectorAll(selector));
    }
    return result;
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
}

const fakeDocument = {
  activeElement: null,
  createElement(tagName) { return new FakeElement(tagName); },
};
global.document = fakeDocument;

function allText(node) {
  return [node.textContent, ...node.children.map((child) => allText(child))].join(" ");
}

const tabsApi = require("../../static/js/extensions/asta_report_tabs.js");

const report = [
  "# SQL 튜닝 결과서",
  "## 결론",
  "개선 후보를 채택합니다.",
  "## 병목 진단",
  "반복 스캔입니다.",
  "- SQL 변경 내용: 반복 스칼라 조회를 한 번의 조인으로 변경",
  "- 변경 위치: SELECT 절의 반복 조회",
  "## 튜닝 전/후 수치 비교",
  "| 구분 | Elapsed |",
  "| --- | ---: |",
  "| Before | 2.8s |",
  "| After | 1.6s |",
  "## 튜닝전 SQL",
  "```sql",
  "SELECT 'VISIBLE_LITERAL' AS sample FROM dual",
  "```",
  "## 튜닝 전 XPLAN",
  "```text",
  "| 10 | TABLE ACCESS FULL | SECRET_TABLE |",
  "```",
  "## 튜닝 후 SQL",
  "```sql",
  "SELECT /* ASTA */ 'AFTER_LITERAL' AS sample FROM dual",
  "```",
  "## 튜닝후 XPLAN",
  "```text",
  "| 10 | HASH JOIN ANTI | |",
  "```",
  "### 사용자 참고사항 반영",
  "OLTP 요청을 반영했습니다.",
  "### 과거 유사 튜닝 사례 - 참고 정보",
  "참고 사례입니다.",
  "### Oracle SQL Tuning Advisor 요약",
  "없음 <script>globalThis.__pwned = true</script> [bad](javascript:alert(1))",
  "### DBA 검토 사항",
  "검토 내용입니다.",
  "- 비교 판정: verdict=`IMPROVED`, equivalence=`VERIFIED`, reason=`OLTP_BUFFER_READS_IMPROVED`.",
  "## 테이블 통계 및 인덱스 정보",
  "통계 정보",
  "### 테이블 통계",
  "262 rows",
  "## 테이블 통계 및 인덱스 정보",
  "object_info 표시 중 오류: ORA-40478",
].join("\r\n");

const root = new FakeElement("div");
const result = tabsApi.renderReportTabs(root, report);
const tabs = root.querySelectorAll('[role="tab"]');
const panels = root.querySelectorAll('[role="tabpanel"]');

assert.deepEqual(tabs.map((tab) => tab.textContent), [
  "분석결과", "튜닝 전", "SQL 변경", "튜닝 후", "객체 정보",
]);
assert.equal(tabs.length, 5);
assert.equal(panels.length, 5);
assert.equal(root.querySelectorAll('[role="tablist"]').length, 1);
assert.equal(tabs[0].getAttribute("aria-selected"), "true");
assert.equal(panels[0].hidden, false);
assert.ok(panels.slice(1).every((panel) => panel.hidden));
assert.ok(tabs.every((tab) => tab.getAttribute("aria-controls")));

assert.match(allText(panels[0]), /Oracle SQL Tuning Advisor 요약/);
assert.match(allText(panels[0]), /없음 <script>globalThis.__pwned/);
assert.doesNotMatch(allText(panels[4]), /Oracle SQL Tuning Advisor 요약/);
assert.equal(root.querySelectorAll(".tuning-gate-host").length, 0, "Gate host must not be rendered");

assert.equal(panels[0].querySelectorAll(".tuning-report-table").length, 1, "comparison Markdown must be an HTML table");
assert.match(allText(panels[2]), /SQL 변경 비교/);
assert.match(allText(panels[2]), /무엇을 어디서 바꿨나/);
assert.match(allText(panels[2]), /반복 스칼라 조회를 한 번의 조인으로 변경/);
assert.match(allText(panels[2]), /SELECT 절의 반복 조회/);
assert.match(allText(panels[2]), /줄 추가/);
assert.match(allText(panels[2]), /1줄 삭제/);
assert.match(allText(panels[2]), /VISIBLE_LITERAL/);
assert.match(allText(panels[2]), /AFTER_LITERAL/);
assert.equal(panels[2].querySelectorAll(".tuning-sql-side-by-side").length, 1);
assert.equal(panels[2].querySelectorAll(".tuning-sql-diff-pane-before").length, 1);
assert.equal(panels[2].querySelectorAll(".tuning-sql-diff-pane-after").length, 1);
assert.ok(panels[2].querySelectorAll(".tuning-sql-diff-remove").length >= 1);
assert.ok(panels[2].querySelectorAll(".tuning-sql-diff-add").length >= 1);
assert.match(panels[1].textContent + panels[1].querySelectorAll("pre code").map((node) => node.textContent).join(""), /VISIBLE_LITERAL/);
assert.match(panels[3].querySelectorAll("pre code").map((node) => node.textContent).join(""), /AFTER_LITERAL/);
assert.equal(globalThis.__pwned, undefined);
assert.equal(root.querySelectorAll("script").length, 0);
assert.equal(root.querySelectorAll("a").length, 0);
assert.match(allText(panels[4]), /262 rows/);
assert.match(allText(panels[4]), /object_info 표시 중 오류/);

const sameSqlDifferentLayout = tabsApi.buildSqlLineDiff(
  "select a,b from dual where a=1 and b = 'x'",
  "SELECT A,\n  B\nFROM DUAL\nWHERE A = 1\n  AND B='x'",
);
assert.ok(sameSqlDifferentLayout.every((row) => row.type === "context"), "format-only differences must stay context");

const verdictSummary = panels[0].querySelector(".tuning-verdict-summary");
const verdictToggle = panels[0].querySelector(".tuning-verdict-help-toggle");
const verdictHelp = panels[0].querySelector(".tuning-verdict-help");
assert.ok(verdictSummary, "conclusion must emphasize the canonical verdict");
assert.match(allText(verdictSummary), /IMPROVED/);
assert.match(allText(verdictSummary), /결과가 일치하고 성능 기준 통과/);
assert.match(allText(verdictSummary), /코드 리뷰와 별도 테스트 후 적용 검토/);
assert.equal(verdictToggle.textContent, "?");
assert.equal(verdictToggle.getAttribute("aria-expanded"), "false");
assert.equal(verdictHelp.hidden, true);
assert.ok(verdictHelp.parentNode.className.includes("tuning-verdict-help-anchor"));
assert.equal(verdictHelp.querySelectorAll(".tuning-verdict-guide-row").length, 7);
verdictToggle.dispatchEvent({ type: "click" });
assert.equal(verdictToggle.getAttribute("aria-expanded"), "true");
assert.equal(verdictHelp.hidden, false);
assert.ok(verdictHelp.parentNode.className.includes("tuning-verdict-help-open"));
verdictToggle.dispatchEvent({ type: "click" });
assert.equal(verdictHelp.hidden, true);
assert.ok(!verdictHelp.parentNode.className.includes("tuning-verdict-help-open"));

assert.equal(tabsApi.extractReportVerdict("- 비교 판정: verdict=`NON_EQUIVALENT`"), "NON_EQUIVALENT");
assert.equal(tabsApi.extractReportVerdict("- 비교 판정: verdict=`ANALYSIS_ONLY`, equivalence=`NOT_EVALUATED`"), "ANALYSIS_ONLY");
assert.equal(tabsApi.extractReportVerdict("- 최종 판정: `NO_REWRITE`"), "NO_REWRITE");
assert.equal(tabsApi.extractReportVerdict("## 결론\n판정 정보 없음"), null);

const noAdvisorRoot = new FakeElement("div");
tabsApi.renderReportTabs(noAdvisorRoot, [
  "# SQL 튜닝 결과서",
  "## 결론",
  "- Run ID: `OADT2-ASTA-modern`",
  "- 최종 판정: `IMPROVED`",
  "- 권장 행동: 코드 리뷰 후 적용 검토",
].join("\n\n"));
const noAdvisorOverview = noAdvisorRoot.querySelectorAll('[role="tabpanel"]')[0];
assert.ok(noAdvisorOverview.querySelector(".tuning-verdict-summary"), "modern report without Advisor must render verdict summary");
assert.equal(noAdvisorOverview.querySelector(".tuning-verdict-help-toggle").textContent, "?");
assert.match(allText(noAdvisorOverview.querySelector(".tuning-verdict-summary")), /IMPROVED/);
assert.doesNotMatch(allText(noAdvisorOverview), /Oracle SQL Tuning Advisor/);

assert.deepEqual(tabsApi.VERDICT_GUIDE.map(({ code, meaning, action }) => [code, meaning, action]), [
  ["IMPROVED", "결과가 일치하고 성능 기준 통과", "코드 리뷰와 별도 테스트 후 적용 검토"],
  ["ANALYSIS_ONLY", "튜닝 후보 제안/분석 완료, 성능 개선 여부 미검증", "운영 적용 전 Source 실측·동등성 검증"],
  ["NOT_IMPROVED", "결과는 같지만 충분한 성능 개선 없음", "원본 SQL 유지"],
  ["CANDIDATE_FAILED", "개선 SQL 실행 중 오류 발생", "개선 SQL 사용 금지, Run ID 전달"],
  ["NON_EQUIVALENT", "원본과 개선 SQL 결과/컬럼 구성이 다름", "개선 SQL 사용 금지"],
  ["NO_REWRITE", "안전한 개선안을 생성하지 못함", "원본 SQL 유지, 참고사항 보완"],
  ["INSUFFICIENT_EVIDENCE", "결과 일치 또는 성능 검증 근거 부족", "원본 SQL 유지, 재검증 요청"],
]);

tabs[1].dispatchEvent({ type: "click" });
assert.equal(tabs[1].getAttribute("aria-selected"), "true");
assert.equal(panels[1].hidden, false);
assert.equal(panels[0].hidden, true);

tabs[1].dispatchEvent({ type: "keydown", key: "ArrowRight" });
assert.equal(fakeDocument.activeElement, tabs[2]);
assert.equal(tabs[2].getAttribute("aria-selected"), "true");
tabs[2].dispatchEvent({ type: "keydown", key: "End" });
assert.equal(fakeDocument.activeElement, tabs[4]);
tabs[4].dispatchEvent({ type: "keydown", key: "Home" });
assert.equal(fakeDocument.activeElement, tabs[0]);
tabs[0].dispatchEvent({ type: "keydown", key: "ArrowLeft" });
assert.equal(fakeDocument.activeElement, tabs[4]);

const missingRoot = new FakeElement("div");
tabsApi.renderReportTabs(missingRoot, "## 결론\n내용만 있음");
const missingPanels = missingRoot.querySelectorAll('[role="tabpanel"]');
assert.equal(missingPanels[1].querySelector(".tuning-report-empty").textContent, "표시할 내용이 없습니다.");
assert.match(missingPanels[2].querySelector(".tuning-report-empty").textContent, /비교할 원본 SQL과 튜닝 SQL/);
assert.equal(missingPanels[4].querySelector(".tuning-report-empty").textContent, "표시할 내용이 없습니다.");

const duplicate = tabsApi.classifyReportSections("## 튜닝 전 SQL\nA\n## 튜닝전 SQL\nB\n## 결론\nOK");
assert.equal(duplicate.tabs.before.length, 0, "duplicate heading must fail closed");
assert.ok(duplicate.reasonCodes.includes("AMBIGUOUS_REPORT_SECTION"));
assert.equal(duplicate.tabs.overview.length, 1, "an ambiguous section must not poison other tabs");

const advisorH2 = tabsApi.classifyReportSections("## Oracle SQL Tuning Advisor 요약\nCOMPLETED\n## 결론\nOK");
assert.equal(advisorH2.tabs.overview.length, 1, "adjacent Overview ranges may be merged");
assert.match(advisorH2.tabs.overview[0], /Oracle SQL Tuning Advisor 요약\nCOMPLETED/);

const duplicateAdvisor = tabsApi.classifyReportSections(
  "### Oracle SQL Tuning Advisor 요약\nA\n### Oracle SQL Tuning Advisor 요약\nB",
);
assert.equal(duplicateAdvisor.tabs.overview.length, 0, "duplicate Advisor heading must fail closed");
assert.ok(duplicateAdvisor.reasonCodes.includes("AMBIGUOUS_REPORT_SECTION"));

const estimatedReport = [
  "## 튜닝 전 SQL",
  "```sql",
  "SELECT 1 FROM dual",
  "```",
  "## 튜닝 전 예상 Plan",
  "```text",
  "Plan hash value: 123",
  "| 0 | SELECT STATEMENT |",
  "```",
  "## 튜닝 후 예상 Plan",
  "```text",
  "Plan hash value: 456",
  "```",
].join("\n");
const estimatedRoot = new FakeElement("div");
tabsApi.renderReportTabs(estimatedRoot, estimatedReport);
const estimatedPanels = estimatedRoot.querySelectorAll('[role="tabpanel"]');
assert.match(allText(estimatedPanels[1]), /튜닝 전 예상 Plan/);
assert.match(estimatedPanels[1].querySelectorAll("pre code").map((node) => node.textContent).join("\n"), /Plan hash value: 123/);
assert.match(allText(estimatedPanels[3]), /튜닝 후 예상 Plan/);
assert.match(estimatedPanels[3].querySelectorAll("pre code").map((node) => node.textContent).join("\n"), /Plan hash value: 456/);

assert.equal(result.tabs.length, 5);
console.log("asta_report_tabs_dom_test: PASS");
