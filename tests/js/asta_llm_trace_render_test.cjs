"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const source = fs.readFileSync("static/js/extensions/tuning_assistant.js", "utf8");
const start = source.indexOf("function normalizeLlmCalls(progress)");
const end = source.indexOf("  /** 단계 상태가 실제로 바뀔 때만", start);
assert.ok(start >= 0 && end > start, "LLM trace helpers must remain extractable");

const helpers = vm.runInNewContext(`
  const LLM_CALL_DETAIL_CACHE = new Map();
  const DEFAULT_ORDS_BASE_URL = "/api/asta";
  const window = {};
  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }
  function formatDuration(ms) { return String(ms) + "ms"; }
  async function fetchJson() { throw new Error("lazy fetch must not run while rendering"); }
  async function copyPlainText() {}
  ${source.slice(start, end)}
  ({ normalizeLlmCalls, renderLlmCallActivity, renderLlmCallDetail, llmCallSignature });
`);

const calls = helpers.normalizeLlmCalls({
  llm_calls: [{
    call_id: 7,
    stage: "CANDIDATE_SQL",
    attempt_no: 2,
    profile_name: "ASTA_GROK_GENAI_PROFILE",
    call_status: "RECEIVED",
    prompt_chars: 12345,
    response_chars: 6789,
    elapsed_ms: 3210,
  }],
});
assert.equal(calls.length, 1);
assert.equal(calls[0].call_id, 7);

const summary = helpers.renderLlmCallActivity(calls, "OADT2-ASTA-TRACE");
assert.match(summary, /개선 SQL 생성/);
assert.match(summary, /ASTA_GROK_GENAI_PROFILE/);
assert.match(summary, /응답 완료/);
assert.match(summary, /Prompt·응답 원문 보기/);
assert.doesNotMatch(summary, /ORIGINAL SQL/);
assert.doesNotMatch(summary, /provider-secret-response/);

const changedElapsed = [{ ...calls[0], elapsed_ms: 9999 }];
assert.equal(
  helpers.llmCallSignature(calls),
  helpers.llmCallSignature(changedElapsed),
  "elapsed-only polling updates must preserve loaded raw-detail DOM",
);

const detail = helpers.renderLlmCallDetail({
  call_id: 7,
  prompt: "ORIGINAL SQL <secret>",
  response: "provider-secret-response",
});
assert.match(detail, /tuning-llm-sensitive-note/);
assert.match(detail, /<details class="tuning-llm-raw-block">/);
assert.match(detail, /ORIGINAL SQL &lt;secret&gt;/);
assert.doesNotMatch(detail, /ORIGINAL SQL <secret>/);
assert.match(detail, /provider-secret-response/);

console.log("asta_llm_trace_render_test: PASS");
