const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");
const React = require("react");
const { act, create } = require("react-test-renderer");

function harness() {
  const cache = new Map();
  const context = { turns: [], busy: false, mutate() {} };
  function load(file) {
    const absolute = path.resolve(
      __dirname,
      "../src/renderer/src/components/companion",
      file,
    );
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
      if (name === "./companion-context")
        return { useCompanion: () => context };
      if (name === "@/context/ai-state-context")
        return { useAiState: () => ({}) };
      if (name.startsWith(".")) {
        const base = path.resolve(path.dirname(absolute), name);
        return load([base + ".tsx", base + ".ts"].find(fs.existsSync));
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
  return {
    context,
    ...load("types.ts"),
    ...load("arbitration-details.tsx"),
    ...load("companion-controls.tsx"),
  };
}

function turn(id, reason, role = "intent") {
  return {
    id,
    final_strategy: "supportive_listening",
    feedback: "unspecified",
    intent: { primary: "venting", advice_preference: "declined" },
    trace: {
      source: "rules",
      coordination: {
        proposed_strategy: "validate_and_ground",
        winner_role: role,
        reason_codes: [reason],
        proposals: [
          {
            role,
            suggested_strategy: "supportive_listening",
            evidence_codes: [reason],
            confidence: "high",
          },
        ],
      },
    },
  };
}

test("reply explanation follows the matching turn and stays collapsed initially", () => {
  const h = harness();
  h.context.turns = [
    turn("first", "advice_declined"),
    turn("second", "explicit_closure"),
  ];
  let view;
  act(() => {
    view = create(
      React.createElement(h.ReplyControls, {
        turnId: "first",
        answer: "我在听。",
      }),
    );
  });
  const detail = view.root.findAllByType("details")[0];
  assert.equal(detail.props.open, undefined);
  assert.equal(
    detail.findByType("summary").children.join(""),
    "为什么这样回应",
  );
  assert.match(detail.findByType("p").children.join(""), /暂时不想听建议/);
  act(() => {
    view.update(
      React.createElement(h.ReplyControls, {
        turnId: "second",
        answer: "再见。",
      }),
    );
  });
  assert.match(
    view.root.findAllByType("details")[0].findByType("p").children.join(""),
    /结束交流/,
  );
  act(() => view.unmount());
});

test("safety replacements and removed history explain the actual final response", () => {
  const h = harness();
  const value = turn("one", "advice_requested");
  value.trace.output_safety_override = true;
  assert.match(h.responseExplanation(value), /安全调整/);
  value.trace.output_safety_override = false;
  value.trace.coordination.winner_role = "history";
  value.trace.coordination.reason_codes = [];
  value.history_invalidated = true;
  assert.match(h.responseExplanation(value), /历史已被修改/);
  value.trace.coordination.winner_role = "safety";
  value.trace.coordination.reason_codes = ["protocol_control_ignored"];
  assert.match(h.responseExplanation(value), /本轮的安全边界/);
});

test("legacy messages render an honest fallback and timeline survives missing fields", () => {
  const h = harness();
  assert.match(h.responseExplanation(), /未记录/);
  const value = turn("legacy", "listen_requested");
  value.trace.coordination = {
    proposed_strategy: "supportive_listening",
    reason_codes: [],
  };
  let view;
  act(() => {
    view = create(
      React.createElement(
        "ol",
        null,
        React.createElement(h.ArbitrationSteps, { turn: value }),
      ),
    );
  });
  const text = JSON.stringify(view.toJSON());
  assert.match(text, /历史记录未保存角色提议/);
  assert.match(text, /胜出角色未记录/);
  act(() => view.unmount());
});

test("timeline shows coded proposals, unknown dimensions and unconfirmed playback facts", () => {
  const h = harness();
  const value = turn("one", "advice_declined");
  value.state_estimate = {
    risk_level: "low",
    observed_dimensions: ["stress"],
    emotion: { stress: 0, anxiety: null, low_mood: null },
  };
  let view;
  act(() => {
    view = create(
      React.createElement(
        "ol",
        null,
        React.createElement(h.ArbitrationSteps, { turn: value }),
      ),
    );
  });
  const text = JSON.stringify(view.toJSON());
  assert.match(text, /压力 0\/1/);
  assert.match(text, /焦虑感 未观测/);
  assert.match(text, /用户拒绝建议/);
  assert.match(text, /仲裁胜出/);
  assert.match(text, /支持性倾听/);
  act(() => view.unmount());
});
