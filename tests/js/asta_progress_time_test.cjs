"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

process.env.TZ = "Asia/Seoul";
const source = fs.readFileSync("static/js/extensions/tuning_assistant.js", "utf8");
const start = source.indexOf("function normalizeAstaTimestamp(value)");
const end = source.indexOf("\n\n  function parseTimeMs", start);
assert.ok(start >= 0 && end > start);
const normalize = vm.runInNewContext(`(${source.slice(start, end).trim()})`);

const oracleTimestamp = "2026-07-06 15:05:11.432403";
assert.equal(normalize(oracleTimestamp), "2026-07-06T15:05:11.432Z");
assert.equal(
  new Date(normalize(oracleTimestamp)).getTime(),
  Date.parse("2026-07-06T15:05:11.432Z"),
  "timezone-less Oracle timestamps must not be interpreted as Asia/Seoul local time",
);
assert.equal(normalize("2026-07-06T15:05:11.432Z"), "2026-07-06T15:05:11.432Z");
console.log("asta_progress_time_test: PASS");
