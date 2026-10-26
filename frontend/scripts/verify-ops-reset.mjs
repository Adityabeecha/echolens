import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import vm from "node:vm";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const compile = path => ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8")
  .replaceAll("import.meta.env", "({})"), { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText;
const jsx = (type, props) => ({ type, props });
const runtime = { jsx, jsxs: jsx, Fragment: "fragment" };
const nodes = tree => tree == null || typeof tree !== "object" ? [] : Array.isArray(tree)
  ? tree.flatMap(nodes) : [tree, ...nodes(tree.props?.children)];
const label = tree => tree == null ? "" : Array.isArray(tree) ? tree.map(label).join("")
  : typeof tree === "object" ? label(tree.props?.children) : String(tree);
const button = (tree, text) => nodes(tree).find(n => n.type === "button" && label(n) === text);

async function verifyApi() {
  const exports = {}, writes = [];
  vm.runInNewContext(compile("../src/api.ts"), { exports,
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    document: { cookie: "" }, fetch: async (url, init) => {
      writes.push({ url, init });
      return { ok: true, json: async () => ({ inserted: 1, error: null }) };
    }, URLSearchParams,
  });
  exports.startSession("csrf-reset-fixture");
  exports.setActiveProduct(11);
  assert.equal(typeof exports.api.collectorsReset, "function", "reset client must exist");
  await exports.api.collectorsReset("play_store", "com.example.app");
  assert.equal(writes.length, 1);
  assert.equal(writes[0].url, "/api/collectors/reset");
  assert.equal(writes[0].init.method, "POST");
  assert.equal(writes[0].init.credentials, "include");
  assert.equal(writes[0].init.headers["X-CSRF-Token"], "csrf-reset-fixture");
  assert.deepEqual(JSON.parse(writes[0].init.body), {
    source: "play_store", identifier: "com.example.app", product_id: 11,
  });
}

const format = {};
vm.runInNewContext(compile("../src/format.ts"), { exports: format });

function screen(role, status = "Healthy") {
  const exports = {}, slots = [], calls = [], dialogs = [];
  let cursor = 0, resolve, reject, reloads = 0;
  const pending = new Promise((a, b) => { resolve = a; reject = b; });
  const dependencies = {
    react: { useEffect() {}, useState(initial) { const i = cursor++; if (!(i in slots)) slots[i] = initial;
      return [slots[i], value => { slots[i] = typeof value === "function" ? value(slots[i]) : value; }]; } },
    "react/jsx-runtime": runtime,
    "../api": { isAdmin: () => role === "admin", canReview: () => role !== "viewer",
      api: { collectorsReset: (...args) => { calls.push(args); return pending; } } },
    "../format": format,
    "../hooks": { useAsync: () => ({ loading: false, error: null,
      reload: () => reloads++, data: { connected: [{ name: "Play Store", detail: "com.example.app",
        source: "play_store", identifier: "com.example.app", status, volume: "3" }], available: [] } }),
      useDialog: (...args) => { dialogs.push(args); return { current: null }; } },
    "../theme": { C: {}, R: {}, S: {}, T: {} },
    "../ui": new Proxy({}, { get: (_, key) => String(key) }),
    // Shared parts, the import panel and the stylesheet render as named stubs.
    "../components/casefile": new Proxy({}, { get: (_, key) => String(key) }),
    "./sources/ImportPanel": { ImportPanel: "ImportPanel" },
    "./settings/ps.css": {},
  };
  vm.runInNewContext(compile("../src/screens/Sources.tsx"), { exports,
    require: name => { assert.ok(name in dependencies, `unstubbed ${name}`); return dependencies[name]; },
  });
  return { calls, dialogs, resolve, reject, get reloads() { return reloads; },
    render() { cursor = 0; return exports.Sources({ productName: "Product A" }); } };
}

function verifyVisibility() {
  for (const role of ["viewer", "reviewer"]) {
    assert.equal(button(screen(role).render(), "Start over"), undefined, `${role} cannot reset`);
  }
  assert.ok(button(screen("admin").render(), "Start over"));
  assert.equal(button(screen("admin", "Syncing…").render(), "Start over").props.disabled, true);
}

async function verifyConfirmationAndResult(failure = false) {
  const h = screen("admin");
  button(h.render(), "Start over").props.onClick();
  let tree = h.render();
  const dialog = nodes(tree).find(n => n.props?.role === "dialog");
  assert.ok(dialog, "reset requires an accessible confirmation dialog");
  assert.match(label(dialog), /watermark/i);
  assert.match(label(dialog), /normal backfill/i);
  assert.match(label(dialog), /existing feedback.*kept/i);
  assert.match(label(dialog), /duplicate/i);
  assert.equal(h.calls.length, 0, "opening confirmation must not make a request");
  button(dialog, "Cancel").props.onClick();
  assert.equal(nodes(h.render()).some(n => n.props?.role === "dialog"), false);
  button(h.render(), "Start over").props.onClick();
  tree = h.render();
  const request = button(nodes(tree).find(n => n.props?.role === "dialog"), "Start over").props.onClick();
  tree = h.render();
  assert.equal(h.calls.length, 1);
  assert.deepEqual(Array.from(h.calls[0]), ["play_store", "com.example.app"]);
  assert.match(label(tree), /Re-syncing/);
  assert.ok(nodes(tree).some(n => n.props?.role === "status"), "running/result feedback must be announced");
  assert.equal(h.dialogs.at(-1)[2], false, "dialog cannot dismiss a running reset");
  if (failure) h.reject(new Error("Source is already collecting (409)"));
  else h.resolve({ fetched: 3, inserted: 1, skipped_duplicate: 2, error: null, duration_seconds: 1.2 });
  await request;
  tree = h.render();
  assert.equal(nodes(tree).some(n => n.props?.role === "dialog"), false);
  if (failure) assert.match(label(tree), /already collecting/);
  else {
    assert.match(label(tree), /1 new item/);
    assert.match(label(tree), /2 duplicate/);
    assert.match(label(tree), /1 new item, 2 duplicates skipped from 3 fetched in 1s\./);
    assert.equal(h.reloads, 1);
  }
}

await verifyApi();
verifyVisibility();
await verifyConfirmationAndResult();
await verifyConfirmationAndResult(true);
console.log("Source reset client, permissions, confirmation, progress, result and failure verified.");
