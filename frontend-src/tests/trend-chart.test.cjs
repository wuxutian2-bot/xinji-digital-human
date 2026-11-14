const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");
const React = require("react");
const { act, create } = require("react-test-renderer");
const cache = new Map();
function load(filename) {
  const absolute = path.resolve(__dirname, "../src/renderer/src", filename);
  if (cache.has(absolute)) return cache.get(absolute).exports;
  const module = { exports: {} };
  cache.set(absolute, module);
  const code = ts.transpileModule(fs.readFileSync(absolute, "utf8"), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      jsx: ts.JsxEmit.ReactJSX,
    },
  }).outputText;
  function localRequire(name) {
    if (name.startsWith("@/") || name.startsWith(".")) {
      const base = name.startsWith("@/")
        ? path.resolve(__dirname, "../src/renderer/src", name.slice(2))
        : path.resolve(path.dirname(absolute), name);
      return load([base + ".ts", base + ".tsx"].find(fs.existsSync));
    }
    return require(name);
  }
  new Function("require", "module", "exports", code)(
    localRequire,
    module,
    module.exports,
  );
  return module.exports;
}
const { TrendChart, TrendSignals } = load(
  "components/companion/trend-chart.tsx",
);
function trend(version = "daily_v3") {
  const metric = {
    mean: 0.4,
    change: null,
    observed_days: 3,
    eligible_for_decision: true,
    previous_daily_means: {},
    daily_means: { "2026-11-02": 0.2, "2026-11-03": 0.3, "2026-11-05": 0.5 },
    daily_smoothed: {
      "2026-11-02": 0.2,
      "2026-11-03": 0.25,
      "2026-11-05": 0.4,
    },
    daily_intervals: {
      "2026-11-02": [0.1, 0.3],
      "2026-11-03": [0.15, 0.35],
      "2026-11-05": [0.3, 0.5],
    },
    alert: "rising",
    alert_started_at: "2026-11-03",
  };
  const empty = {
    ...metric,
    observed_days: 0,
    daily_means: {},
    daily_smoothed: {},
    daily_intervals: {},
    alert: null,
  };
  return {
    version,
    settings: { timezone: "Asia/Shanghai" },
    previous_window: { start: "2026-11-02T00:00:00+08:00" },
    sources: {
      system_estimate: { dimensions: { stress: metric } },
      user_report: { dimensions: { stress: empty } },
      user_correction: { dimensions: { stress: empty } },
    },
    preferred_sources: { stress: "system_estimate" },
    source_disagreement: { stress: [] },
  };
}
function render(component, value) {
  let view;
  act(() => {
    view = create(
      React.createElement(component, { trend: value, dimension: "stress" }),
    );
  });
  return view;
}
test("v3 draws an interval band without crossing a missing day and marks the alert", () => {
  const view = render(TrendChart, trend());
  assert.equal(view.root.findAllByType("circle").length, 3);
  const bands = view.root.findAllByType("polygon");
  assert.equal(bands.length, 1);
  assert.match(bands[0].props.points, /40,/);
  assert.doesNotMatch(bands[0].props.points, /178,/);
  assert.match(JSON.stringify(view.toJSON()), /连续上升信号起点/);
  act(() => view.unmount());
});
test("v2 uses its original daily points and does not show v3 alerts or intervals", () => {
  const value = trend("daily_v2");
  const view = render(TrendChart, value);
  assert.equal(view.root.findAllByType("polygon").length, 0);
  assert.equal(view.root.findAllByType("circle").length, 3);
  assert.doesNotMatch(JSON.stringify(view.toJSON()), /连续上升信号起点/);
  act(() => view.unmount());
  const signal = render(TrendSignals, value);
  assert.equal(signal.toJSON(), null);
  act(() => signal.unmount());
});
test("source conflict explains self report precedence and insufficient self report days", () => {
  const value = trend();
  value.preferred_sources.stress = "user_report";
  value.source_disagreement.stress = ["2026-11-03"];
  value.sources.user_report.dimensions.stress.eligible_for_decision = false;
  const view = render(TrendSignals, value);
  const text = JSON.stringify(view.toJSON());
  assert.match(text, /本维度优先参考你的自报/);
  assert.match(text, /自报天数不足或记录已过期/);
  act(() => view.unmount());
});
