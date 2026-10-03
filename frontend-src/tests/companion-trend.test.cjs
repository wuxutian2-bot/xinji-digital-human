const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");
const moduleValue = { exports: {} };
const source = fs.readFileSync(
  path.join(__dirname, "../src/renderer/src/utils/companion-trend.ts"),
  "utf8",
);
new Function(
  "module",
  "exports",
  ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS },
  }).outputText,
)(moduleValue, moduleValue.exports);
const { calendarDays, dailyValues } = moduleValue.exports;
test("calendar labels use report timezone across DST, without missing days", () => {
  const days = calendarDays("2026-03-07T00:00:00-05:00", "America/New_York");
  assert.equal(days.length, 14);
  assert.equal(days[0], "2026-03-07");
  assert.equal(days[13], "2026-03-20");
});
test("explicit zero remains zero, gaps remain unknown", () => {
  assert.deepEqual(dailyValues(["a", "b", "c"], { a: 0 }, { c: 0.7 }), [
    0,
    null,
    0.7,
  ]);
});
