const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");
const React = require("react");
const { create, act } = require("react-test-renderer");

function load(file, mocks = {}, globals = {}) {
  const filename = path.resolve(__dirname, "../src/renderer/src", file);
  const module = { exports: {} };
  const source = ts.transpileModule(fs.readFileSync(filename, "utf8"), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      jsx: ts.JsxEmit.ReactJSX,
    },
  }).outputText;
  new Function("module", "exports", "require", ...Object.keys(globals), source)(
    module,
    module.exports,
    (name) => mocks[name] || require(name),
    ...Object.values(globals),
  );
  return module.exports;
}

function downloadHarness(response, clickThrows = false) {
  const calls = [],
    released = [],
    timers = [],
    anchors = [];
  const { downloadCompanionExport } = load(
    "utils/companion-export.ts",
    {},
    {
      fetch: async (...args) => {
        calls.push(args);
        return response;
      },
      document: {
        body: {
          appendChild(anchor) {
            anchor.appended = true;
          },
        },
        createElement(tag) {
          assert.equal(tag, "a");
          const anchor = {
            remove() {
              this.removed = true;
            },
            click() {
              this.clicked = true;
              if (clickThrows) throw new Error("click failed");
            },
          };
          anchors.push(anchor);
          return anchor;
        },
      },
      URL: {
        createObjectURL(blob) {
          assert(blob.size > 0);
          return "blob:synthetic-export";
        },
        revokeObjectURL(url) {
          released.push(url);
        },
      },
      setTimeout(callback, delay) {
        timers.push({ callback, delay });
      },
    },
  );
  return { downloadCompanionExport, calls, released, timers, anchors };
}

function okResponse(type = "application/json") {
  return {
    ok: true,
    headers: new Headers({
      "Content-Type": type,
      "Content-Disposition":
        'attachment; filename="xinji-data-20261115T120000Z.json"',
    }),
    blob: async () =>
      new Blob(['{"states":[],"turns":[],"actions":[]}'], { type }),
  };
}

test("download requests full server export and releases its temporary blob URL", async () => {
  const h = downloadHarness(okResponse());
  await h.downloadCompanionExport("http://localhost:12407");
  assert.equal(h.calls[0][0], "http://localhost:12407/api/companion/export");
  assert.equal(h.calls[0][1].cache, "no-store");
  assert.equal(h.anchors[0].download, "xinji-data-20261115T120000Z.json");
  assert.equal(h.anchors[0].href, "blob:synthetic-export");
  assert(h.anchors[0].clicked && h.anchors[0].removed);
  assert.equal(h.released.length, 0);
  assert.equal(h.timers[0].delay, 1000);
  h.timers[0].callback();
  assert.deepEqual(h.released, ["blob:synthetic-export"]);
});

test("HTTP errors, wrong response format and empty files cannot create a download", async () => {
  for (const response of [
    { ok: false, json: async () => ({ detail: "当前档案暂不可用" }) },
    okResponse("text/html"),
    { ...okResponse(), blob: async () => new Blob([]) },
  ]) {
    const h = downloadHarness(response);
    await assert.rejects(h.downloadCompanionExport("http://test"));
    assert.equal(h.anchors.length, 0);
  }
});

test("download cleanup also runs when a browser click fails", async () => {
  const h = downloadHarness(okResponse(), true);
  await assert.rejects(
    h.downloadCompanionExport("http://test"),
    /click failed/,
  );
  assert(h.anchors[0].removed);
  h.timers[0].callback();
  assert.equal(h.released.length, 1);
});

test("privacy export control shows the synthetic scope and only reports successful downloads", async () => {
  let success = true,
    count = 0;
  const context = {
    profile: { synthetic_demo: true },
    busy: false,
    exportData: async () => {
      count++;
      return success;
    },
  };
  const { DataExport } = load("components/companion/data-export.tsx", {
    "./companion-context": { useCompanion: () => context },
  });
  let view;
  await act(async () => {
    view = create(React.createElement(DataExport));
  });
  assert(JSON.stringify(view.toJSON()).includes("虚构记录"));
  assert.equal(view.root.findByType("button").props.disabled, false);
  await act(async () => {
    await view.root.findByType("button").props.onClick();
  });
  assert.equal(count, 1);
  assert(JSON.stringify(view.toJSON()).includes("已发起下载"));
  success = false;
  await act(async () => {
    await view.root.findByType("button").props.onClick();
  });
  assert(!JSON.stringify(view.toJSON()).includes("已发起下载"));
  context.busy = true;
  await act(async () => {
    view.update(React.createElement(DataExport));
  });
  assert.equal(view.root.findByType("button").props.disabled, true);
  context.busy = false;
  context.profile = null;
  await act(async () => {
    view.update(React.createElement(DataExport));
  });
  assert.equal(view.root.findByType("button").props.disabled, true);
  await act(async () => view.unmount());
});
