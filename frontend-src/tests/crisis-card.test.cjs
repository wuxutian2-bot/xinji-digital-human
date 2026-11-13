const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");
const React = require("react");
const { act, create } = require("react-test-renderer");

// Exercise the real providers, subscription, card and event handler. Only browser
// transport and native <dialog> methods are substituted in the Node renderer.
function harness() {
  const listeners = new Set();
  const posts = [];
  const notifications = [];
  const cache = new Map();
  let failEvent = false;
  const mocks = {
    "@/context/chat-history-context": {
      useChatHistory: () => ({ currentHistoryUid: "h1" }),
    },
    "@/context/websocket-context": {
      useWebSocket: () => ({ baseUrl: "http://test", sendMessage() {} }),
    },
    "@/services/websocket-service": {
      wsService: {
        onMessage(callback) {
          listeners.add(callback);
          return { unsubscribe: () => listeners.delete(callback) };
        },
        onStateChange() {
          return { unsubscribe() {} };
        },
        getCurrentState: () => "OPEN",
      },
    },
    "@/components/ui/toaster": {
      toaster: { create: (value) => notifications.push(value) },
    },
  };
  function load(filename) {
    const absolute = path.resolve(__dirname, "../src/renderer/src", filename);
    if (cache.has(absolute)) return cache.get(absolute).exports;
    const module = { exports: {} };
    cache.set(absolute, module);
    const source = ts.transpileModule(fs.readFileSync(absolute, "utf8"), {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        jsx: ts.JsxEmit.ReactJSX,
        target: ts.ScriptTarget.ES2022,
      },
    }).outputText;
    const localRequire = (name) => {
      if (mocks[name]) return mocks[name];
      if (name.endsWith(".css")) return {};
      if (name.startsWith("@/") || name.startsWith(".")) {
        const base = name.startsWith("@/")
          ? path.resolve(__dirname, "../src/renderer/src", name.slice(2))
          : path.resolve(path.dirname(absolute), name);
        const file = [base + ".ts", base + ".tsx"].find(fs.existsSync);
        return load(file);
      }
      return require(name);
    };
    new Function("require", "module", "exports", source)(
      localRequire,
      module,
      module.exports,
    );
    return module.exports;
  }
  const { CrisisProvider } = load("components/companion/crisis-context.tsx");
  const { CompanionProvider } = load(
    "components/companion/companion-context.tsx",
  );
  const { CrisisSupport } = load("components/companion/crisis-card.tsx");
  const nativeDialog = {
    open: false,
    querySelector: () => ({ focus() {} }),
    showModal() {
      this.open = true;
    },
    close() {
      this.open = false;
    },
  };
  let renderer;
  return {
    posts,
    notifications,
    nativeDialog,
    get root() {
      return renderer.root;
    },
    async mount(t) {
      const originalFetch = global.fetch;
      const originalWindow = global.window;
      global.window = { location: { search: "" } };
      global.fetch = async (url, options) => {
        if (options.method === "POST")
          posts.push({ url, body: JSON.parse(options.body) });
        return {
          ok: !(failEvent && url.endsWith("/events")),
          json: async () =>
            url.endsWith("/profile")
              ? { trial_mode: false }
              : url.endsWith("/trend")
                ? { trend: null, review: [] }
                : [],
        };
      };
      t.after(() => {
        act(() => renderer.unmount());
        global.fetch = originalFetch;
        global.window = originalWindow;
        assert.equal(listeners.size, 0);
      });
      await act(async () => {
        renderer = create(
          React.createElement(
            CrisisProvider,
            null,
            React.createElement(
              CompanionProvider,
              null,
              React.createElement(CrisisSupport),
            ),
          ),
          {
            createNodeMock: (element) =>
              element.type === "dialog" ? nativeDialog : null,
          },
        );
      });
    },
    async emit(message) {
      await act(async () => {
        for (const listener of listeners) listener(message);
      });
    },
    async confirm() {
      await act(async () => this.root.findByType("button").props.onClick());
    },
    failEvents() {
      failEvent = true;
    },
  };
}

const resources = [
  {
    name: "测试资源",
    number: "12356",
    description: "测试说明",
    available: "待核实",
  },
  {
    name: "测试急救",
    number: "120",
    description: "测试说明",
    available: "待核实",
  },
];
const message = (id = "c1", type = "crisis-support") => ({
  type,
  history_uid: "h1",
  turn_id: "turn-" + id,
  actions: {
    strategy: { primary: "crisis_support" },
    crisis_resources: resources,
    crisis_id: id,
  },
});

test("late audio from an older crisis cannot replace the newer resource card", async (t) => {
  const h = harness();
  await h.mount(t);
  await h.emit(message("c1"));
  const next = message("c2");
  next.actions.crisis_resources = [{ ...resources[0], name: "本轮资源" }];
  await h.emit(next);
  await h.emit(message("c1", "audio"));
  assert.equal(h.root.findByType("strong").children.join(""), "本轮资源");
});

test("crisis card renders on strategy, persists through messages, closes on confirmation and records event", async (t) => {
  const h = harness();
  await h.mount(t);
  assert.equal(h.nativeDialog.open, false);
  await h.emit(message());
  assert.equal(h.nativeDialog.open, true);
  assert.deepEqual(
    h.root.findAllByType("a").map((a) => a.props.href),
    ["tel:12356", "tel:120"],
  );
  assert.equal(h.root.findByType("button").children.join(""), "我现在安全");
  await h.emit({
    type: "audio",
    actions: { strategy: { primary: "supportive_listening" } },
  });
  await h.emit({ type: "history-data" });
  assert.equal(h.nativeDialog.open, true);
  let prevented = false;
  h.root.findByType("dialog").props.onCancel({
    preventDefault() {
      prevented = true;
    },
  });
  assert.equal(prevented, true);
  await h.confirm();
  assert.equal(h.nativeDialog.open, false);
  assert.equal(h.root.findAllByType("button").length, 0);
  assert.deepEqual(h.posts, [
    { url: "http://test/api/companion/events", body: { name: "crisis_ack" } },
  ]);
  await h.emit(message("c1", "audio"));
  assert.equal(h.nativeDialog.open, false);
  await h.emit(message("c2"));
  assert.equal(h.nativeDialog.open, true);
});

test("other-history messages are ignored; malformed resource links are never rendered", async (t) => {
  const h = harness();
  await h.mount(t);
  await h.emit({ ...message(), history_uid: "other" });
  assert.equal(h.nativeDialog.open, false);
  const incoming = message();
  incoming.actions.crisis_resources = [
    { ...resources[0], number: "javascript:alert(1)" },
    null,
  ];
  await h.emit(incoming);
  assert.equal(h.nativeDialog.open, true);
  assert.equal(h.root.findAllByType("a").length, 0);
  assert.equal(h.root.findAllByType("button").length, 1);
});

test("failed event storage does not trap the user or pretend to save confirmation", async (t) => {
  const h = harness();
  await h.mount(t);
  h.failEvents();
  await h.emit(message());
  await h.confirm();
  assert.equal(h.nativeDialog.open, false);
  assert.equal(h.notifications.length, 1);
  assert.match(h.notifications[0].title, /记录未保存/);
});

test("a new risk notification while acknowledgement is pending remains visible", async (t) => {
  const h = harness();
  await h.mount(t);
  let release;
  const previousFetch = global.fetch;
  global.fetch = (url, options) =>
    url.endsWith("/events")
      ? new Promise((resolve) => {
          release = () => resolve({ ok: true, json: async () => ({}) });
        })
      : previousFetch(url, options);
  await h.emit(message());
  await h.confirm();
  await h.emit(message("c2"));
  await act(async () => release());
  assert.equal(h.nativeDialog.open, true);
  await h.emit(message("c1", "audio"));
  assert.equal(h.nativeDialog.open, true);
});
