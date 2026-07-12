"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const source = fs.readFileSync(
  path.resolve(__dirname, "../../static/js/extensions/tuning_assistant.js"),
  "utf8",
);
const start = source.indexOf("function progressDrawerSteps(steps)");
const end = source.indexOf("\n  /** 상세보기", start);
assert.ok(start >= 0 && end > start, "progressDrawerSteps source must be extractable");
const progressDrawerSteps = new Function(`return (${source.slice(start, end).trim()})`)();

const internal = [
  [1, "REQUEST_RECEIVED"],
  [2, "ORDS_DISPATCH"],
  [3, "SQL_GUARD"],
  [4, "BEFORE_EVIDENCE"],
  [5, "LLM_REWRITE"],
  [6, "AFTER_EVIDENCE"],
  [7, "BEFORE_AFTER_COMPARE"],
  [8, "FINAL_REPORT"],
  [9, "VECTOR_SAVE"],
].map(([seq, code]) => ({
  seq,
  code,
  label: code,
  status: seq <= 3 ? "DONE" : "PENDING",
  elapsed_ms: 10,
}));

const visible = progressDrawerSteps(internal);
assert.deepEqual(visible.map((step) => step.seq), ["1", 2, 3, 4, 5, 6, 7]);
assert.deepEqual(visible.map((step) => step.code), [
  "REQUEST_PREPARATION",
  "BEFORE_EVIDENCE",
  "LLM_REWRITE",
  "AFTER_EVIDENCE",
  "BEFORE_AFTER_COMPARE",
  "FINAL_REPORT",
  "VECTOR_SAVE",
]);
assert.equal(visible[0].label, "요청 및 분석 준비");
assert.deepEqual(visible.slice(1).map((step) => step.internal_seq), [4, 5, 6, 7, 8, 9]);

console.log("asta_progress_sequence_test: PASS");
