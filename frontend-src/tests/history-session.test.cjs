const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");
const moduleValue = { exports: {} };
const source = fs.readFileSync(
  path.join(__dirname, "../src/renderer/src/utils/history-session.ts"),
  "utf8",
);
new Function(
  "module",
  "exports",
  ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS },
  }).outputText,
)(moduleValue, moduleValue.exports);
const { initialHistoryRequest, historySelectionKey } = moduleValue.exports;

test("reload restores the last selected conversation, including an older one", () => {
  assert.deepEqual(
    initialHistoryRequest([{ uid: "latest" }, { uid: "older" }], "older"),
    {
      type: "fetch-and-set-history",
      history_uid: "older",
    },
  );
});
test("a missing or other-profile selection falls back to a returned history", () => {
  assert.deepEqual(initialHistoryRequest([{ uid: "personal" }], "demo"), {
    type: "fetch-and-set-history",
    history_uid: "personal",
  });
  assert.notEqual(
    historySelectionKey("ws://localhost:12393/client-ws", "personal"),
    historySelectionKey("ws://localhost:12401/client-ws", "personal"),
  );
  assert.notEqual(
    historySelectionKey("server", "personal"),
    historySelectionKey("server", "demo"),
  );
});
test("only an empty saved-history list starts a new conversation", () => {
  assert.deepEqual(initialHistoryRequest([], "stale"), {
    type: "create-new-history",
  });
  assert.equal(
    initialHistoryRequest([{ uid: "saved" }], null).type,
    "fetch-and-set-history",
  );
});
