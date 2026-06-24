/**
 * util.js — 전역 유틸. 가장 먼저 로드된다.
 * escapeHtml/escapeAttr: DB/LLM 등 서버 값을 innerHTML 템플릿에 넣기 전 이스케이프.
 *   (서버 응답에 HTML 이 섞여도 저장형 XSS·레이아웃 깨짐을 막는다. CSP 와 함께 심층 방어.)
 */
(function () {
  function escapeHtml(v) {
    return String(v == null ? "" : v)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }
  // 속성값용 — 따옴표까지 이스케이프하므로 escapeHtml 과 동일하게 안전.
  window.escapeHtml = escapeHtml;
  window.escapeAttr = escapeHtml;
})();
