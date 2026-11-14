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
const { calendarDays, dailyValues, intervalBands } = moduleValue.exports;
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
test("interval bands preserve zero bounds and split at missing calendar days", () => {
  assert.deepEqual(
    intervalBands(["a", "b", "c", "d"], {
      a: [0, 0.2],
      b: [0.1, 0.3],
      d: [0.4, 0.6],
    }),
    [
      [
        { index: 0, lower: 0, upper: 0.2 },
        { index: 1, lower: 0.1, upper: 0.3 },
      ],
      [{ index: 3, lower: 0.4, upper: 0.6 }],
    ],
  );
  assert.deepEqual(intervalBands(["a"], {}), []);
});
