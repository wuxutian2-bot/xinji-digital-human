const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");

const cache = new Map();
function load(filename) {
  const absolute = path.resolve(
    __dirname,
    "../src/renderer/WebSDK/Framework/src",
    filename,
  );
  if (cache.has(absolute)) return cache.get(absolute).exports;
  const module = { exports: {} };
  cache.set(absolute, module);
  const code = ts.transpileModule(fs.readFileSync(absolute, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS },
  }).outputText;
  const localRequire = (name) =>
    name.startsWith(".")
      ? load(path.resolve(path.dirname(absolute), name + ".ts"))
      : require(name);
  new Function("require", "module", "exports", code)(
    localRequire,
    module,
    module.exports,
  );
  return module.exports;
}

test("Cubism JSON conversion preserves nested model configuration arrays and primitive values", () => {
  const { JsonMap, Value } = load("utils/cubismjson.ts");
  const { CubismJsonExtension } = load("utils/cubismjsonextension.ts");
  Value.staticInitializeNotForClientCall();
  const input = JSON.parse(
    '{"Version":3,"FileReferences":{"Textures":["a.png","b.png"],"Motions":{"Idle":[{"File":"idle.motion3.json"}]}},"Mixed":[false,0,"",null,[true,1.5],{}]}',
  );
  const root = CubismJsonExtension.parseJsonObject(input, new JsonMap());
  assert.equal(root.getValueByString("Version").toInt(), 3);
  const refs = root.getValueByString("FileReferences");
  const textures = refs.getValueByString("Textures");
  assert.equal(textures.getSize(), 2);
  assert.equal(textures.getValueByIndex(0).getRawString(), "a.png");
  assert.equal(
    refs
      .getValueByString("Motions")
      .getValueByString("Idle")
      .getValueByIndex(0)
      .getValueByString("File")
      .getRawString(),
    "idle.motion3.json",
  );
  const mixed = root.getValueByString("Mixed");
  assert.equal(mixed.getSize(), 6);
  assert.equal(mixed.getValueByIndex(0).toBoolean(), false);
  assert.equal(mixed.getValueByIndex(1).toFloat(), 0);
  assert.equal(mixed.getValueByIndex(2).getRawString(), "");
  assert.equal(mixed.getValueByIndex(3).isNull(), true);
  assert.equal(mixed.getValueByIndex(4).getValueByIndex(0).toBoolean(), true);
  assert.equal(mixed.getValueByIndex(4).getValueByIndex(1).toFloat(), 1.5);
  assert.equal(mixed.getValueByIndex(5).isMap(), true);
});

test("Cubism JSON conversion keeps empty arrays and empty objects distinct", () => {
  const { JsonMap } = load("utils/cubismjson.ts");
  const { CubismJsonExtension } = load("utils/cubismjsonextension.ts");
  const root = CubismJsonExtension.parseJsonObject(
    { list: [], object: {}, absent: null },
    new JsonMap(),
  );
  assert.equal(root.getValueByString("list").isArray(), true);
  assert.equal(root.getValueByString("list").getSize(), 0);
  assert.equal(root.getValueByString("object").isMap(), true);
  assert.equal(root.getValueByString("absent").isNull(), true);
});
