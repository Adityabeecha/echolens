import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";

// Execute source modules with local DOM/API doubles. No external IO.
function harness(file, stubs = {}, globals = {}) {
  const state = [], effects = [], cache = new Map(); let cursor = 0;
  const jsx = (type, props) => ({ type, props: props ?? {} });
  const react = {
    useState(initial) { const i = cursor++; if (!(i in state)) state[i] = typeof initial === "function" ? initial() : initial;
      return [state[i], x => { state[i] = typeof x === "function" ? x(state[i]) : x; }]; },
    useRef(initial) { const i = cursor++; return state[i] ??= { current: initial }; },
    useCallback(fn) { cursor++; return fn; }, useMemo(fn) { return fn(); },
    useEffect(fn, deps) { const i = cursor++, old = effects[i];
      if (!old || deps?.some((d, j) => d !== old.deps?.[j])) {
        old?.cleanup?.(); effects[i] = { deps, fn };
      }
    },
  };
  const passthrough = p => jsx("div", { children: p.children });
  function load(url) {
    if (cache.has(url.href)) return cache.get(url.href);
    const exports = {}; cache.set(url.href, exports);
    const require = name => {
      if (name === "react") return react;
      if (name === "react/jsx-runtime") return { jsx, jsxs: jsx, Fragment: "fragment" };
      if (name in stubs) return stubs[name];
      if (name.endsWith("/ui")) return new Proxy({}, { get: () => passthrough });
      if (name.endsWith("/Icon")) return { Icon: () => null };
      if (name.endsWith("/CaseCard")) return { CaseCard: passthrough };
      if (name.endsWith("/Toast")) return { withToast: fn => fn() };
      const base = new URL(name, url);
      const next = [".ts", ".tsx"].map(ext => new URL(base.href + ext)).find(existsSync);
      if (!next) throw new Error(`Unexpected import ${name}`);
      return load(next);
    };
    const source = readFileSync(url, "utf8").replaceAll("import.meta.env.VITE_API_BASE", "undefined");
    const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS,
      jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 } }).outputText;
    vm.runInNewContext(code, { exports, require, setTimeout, clearTimeout,
      requestAnimationFrame: fn => { fn(); return 1; }, cancelAnimationFrame() {}, ...globals });
    return exports;
  }
  const mod = load(new URL(file, import.meta.url));
  const expand = node => {
    if (Array.isArray(node)) return node.map(expand);
    if (!node || typeof node !== "object") return node;
    if (typeof node.type === "function") return expand(node.type(node.props));
    return { ...node, props: { ...node.props, children: expand(node.props.children) } };
  };
  return { mod, render(fn, expandComponents = true) { cursor = 0;
    const node = fn(mod), result = expandComponents ? expand(node) : node;
    for (const effect of effects) if (effect?.fn) { const fn = effect.fn; delete effect.fn; effect.cleanup = fn(); }
    return result;
  }, unmount() { effects.forEach(e => e?.cleanup?.()); } };
}
const text = n => Array.isArray(n) ? n.map(text).join("") :
  n && typeof n === "object" ? text(n.props.children) : n == null || n === false ? "" : String(n);
const nodes = n => Array.isArray(n) ? n.flatMap(nodes) : n && typeof n === "object"
  ? [n, ...nodes(n.props.children)] : [];
const plain = value => JSON.parse(JSON.stringify(value));
const tests = [], test = (name, fn) => tests.push([name, fn]);
const filters = ["tab", "sev", "source", "range", "intent", "q"];

function memoryStorage() {
  const values = new Map();
  return { blocked: false, getItem(k) { if (this.blocked) throw Error("blocked"); return values.get(k) ?? null; },
    setItem(k, v) { if (this.blocked) throw Error("blocked"); values.set(k, v); }, removeItem(k) { values.delete(k); } };
}
function apiFixture() {
  const storage = memoryStorage(), calls = [];
  const h = harness("../src/api.ts", {}, { localStorage: storage, document: { cookie: "" },
    fetch: async (...args) => { calls.push(args); return { ok: true, json: async () => ({ views: [] }) }; },
  });
  return { ...h.mod, storage, calls };
}

test("guest saved views persist locally, scope to product, rename and delete", async () => {
  const { api, setGuest, calls, storage } = apiFixture(); setGuest(true);
  const view = await api.createSavedView("Review", { tab: "needs-review", q: "battery" }, 1);
  assert.equal((await api.savedViews(1)).views[0].name, "Review");
  assert.deepEqual(plain((await api.savedViews(2)).views), []);
  await api.updateSavedView(view.id, "Battery", view.params, 1);
  assert.equal((await api.savedViews(1)).views[0].name, "Battery");
  const reloaded = harness("../src/api.ts", {}, { localStorage: storage }).mod;
  assert.equal((await reloaded.api.savedViews(1)).views[0].name, "Battery");
  await api.deleteSavedView(view.id, 1);
  assert.deepEqual(plain((await api.savedViews(1)).views), []);
  assert.equal(calls.length, 0);
});
test("guest views tolerate blocked and malformed storage", async () => {
  const { api, setGuest, storage, calls } = apiFixture(); setGuest(true);
  storage.setItem("echolens_guest_views:8", "{bad-json");
  assert.deepEqual(plain((await api.savedViews(8)).views), []);
  storage.blocked = true;
  const view = await api.createSavedView("Works in memory", { q: "battery" }, 9);
  assert.equal((await api.savedViews(9)).views.length, 1);
  await api.updateSavedView(view.id, "Renamed", {}, 9);
  await api.deleteSavedView(view.id, 9);
  assert.equal(calls.length, 0);
});
test("guest names are unique and limited to twenty per product", async () => {
  const { api, setGuest } = apiFixture(); setGuest(true);
  for (let i = 0; i < 20; i++) await api.createSavedView(`View ${i}`, {}, 1);
  await assert.rejects(() => api.createSavedView("Overflow", {}, 1), /20/);
  await assert.rejects(() => api.createSavedView("View 1", {}, 2).then(() => api.createSavedView("View 1", {}, 2)), /name/i);
  assert.equal((await api.savedViews(2)).views.length, 1);
});
test("signed-in view mutations use cookie and CSRF helpers with explicit product scope", async () => {
  const { api, startSession, setActiveProduct, calls } = apiFixture();
  startSession("csrf"); setActiveProduct(99);
  await api.savedViews(2);
  await api.createSavedView("Review", { q: "battery" }, 2);
  await api.updateSavedView(7, "Renamed", {}, 2);
  await api.deleteSavedView(7, 2);
  assert.deepEqual(calls.map(([url]) => url), ["/api/views?product_id=2", "/api/views?product_id=2",
    "/api/views/7?product_id=2", "/api/views/7?product_id=2"]);
  assert.deepEqual(calls.slice(1).map(([, init]) => init.method), ["POST", "PUT", "DELETE"]);
  for (const [, init] of calls.slice(1)) {
    assert.equal(init.credentials, "include"); assert.equal(init.headers["X-CSRF-Token"], "csrf");
    assert.equal(init.headers.Authorization, undefined);
  }
});

function drawerFixture() {
  const shared = () => null;
  const document = { body: { style: { overflow: "auto" } }, documentElement: { style: { overflow: "scroll" } } };
  const listeners = new Map();
  const window = { addEventListener: (k, fn) => listeners.set(k, fn), removeEventListener: k => listeners.delete(k) };
  const h = harness("../src/components/AskDrawer.tsx", {
    "../screens/Chat": { AskConversation: shared }, "../hooks": { useDialog: () => ({ current: null }) },
  }, { document, window, navigator: { platform: "Win32" } });
  return { ...h, document, shared, listeners };
}
test("Ctrl K / Cmd K match the platform and ignore editable fields", () => {
  const { mod } = drawerFixture();
  const event = { key: "k", ctrlKey: true, metaKey: false, target: { closest: () => null } };
  assert.equal(mod.isAskShortcut(event, false), true);
  assert.equal(mod.isAskShortcut({ ...event, ctrlKey: false, metaKey: true }, true), true);
  assert.equal(mod.isAskShortcut(event, true), false);
  assert.equal(mod.isAskShortcut({ ...event, target: { closest: () => ({}) } }, false), false);
  assert.equal(mod.isAskShortcut({ ...event, target: { isContentEditable: true } }, false), false);
  assert.equal(mod.isAskShortcut({ ...event, altKey: true }, false), false);
  assert.equal(mod.isAskShortcut({ ...event, repeat: true }, false), false);
});
test("drawer is labelled, modal, shares Ask and restores scroll styles", () => {
  const h = drawerFixture();
  let restored = 0, closed = 0, stopped = false;
  const returnFocus = { isConnected: true, focus() { restored++; } };
  const tree = h.render(m => m.AskDrawer({ productId: 3, productName: "Lumo", returnFocus,
    onClose() { closed++; }, onOpenInvestigation() {} }), false);
  const dialog = nodes(tree).find(n => n.props.role === "dialog");
  assert.equal(String(dialog.props["aria-modal"]), "true");
  assert.ok(dialog.props["aria-labelledby"] || dialog.props["aria-label"]);
  assert.ok(nodes(tree).find(n => n.type === h.shared && n.props.productName === "Lumo"));
  assert.equal(h.document.body.style.overflow, "hidden");
  h.listeners.get("keydown")({ key: "Escape", preventDefault() {}, stopPropagation() { stopped = true; } });
  assert.equal(closed, 1); assert.equal(stopped, true);
  h.unmount();
  assert.equal(restored, 1, "restore the opener captured before background inert could blur it");
  assert.equal(h.document.body.style.overflow, "auto");
  assert.equal(h.document.documentElement.style.overflow, "scroll");
});
test("dialog traps focus, closes on Escape and returns focus", () => {
  const listeners = new Map(); let closed = 0;
  const document = { activeElement: null, addEventListener: (k, fn) => listeners.set(k, fn),
    removeEventListener: k => listeners.delete(k) };
  const control = () => ({ focus() { document.activeElement = this; }, hasAttribute: () => false, getAttribute: () => null });
  const previous = control(), first = control(), last = control(); document.activeElement = previous;
  const h = harness("../src/hooks.ts", { "./api": { api: {} } }, { document });
  h.render(m => { const ref = m.useDialog(() => closed++); ref.current = { querySelectorAll: () => [first, last] }; return null; });
  assert.equal(document.activeElement, first);
  const key = (key, shiftKey = false) => listeners.get("keydown")({ key, shiftKey, preventDefault() {}, stopPropagation() {} });
  document.activeElement = last; key("Tab"); assert.equal(document.activeElement, first);
  key("Tab", true); assert.equal(document.activeElement, last);
  key("Escape"); assert.equal(closed, 1);
  h.unmount(); assert.equal(document.activeElement, previous);
});

function viewsFixture(params = { sev: "high", q: "old", intent: "bug" }) {
  const calls = [], applied = [];
  const saved = { id: 7, product_id: 2, name: "My view", params: { tab: "needs-review", q: "battery" } };
  const h = harness("../src/screens/Cases.tsx", {
    "../api": { CASE_VIEW_FILTERS: filters, isGuest: () => false, canReview: () => true,
      api: { createSavedView: async (...args) => calls.push(["create", ...args]),
        updateSavedView: async (...args) => calls.push(["update", ...args]),
        deleteSavedView: async (...args) => calls.push(["delete", ...args]) } },
    "../hooks": { useAsync: () => ({ data: { views: [saved] }, reload() {} }) },
  });
  const render = () => h.render(m => m.SavedViewsBar({ productId: 2, params, onApply: p => applied.push(p) }));
  const button = label => nodes(render()).find(n => n.type === "button" && (n.props["aria-label"] === label || text(n).trim() === label));
  return { h, render, button, calls, applied, saved };
}
test("applying a saved view replaces all six filters and excludes unrelated URL params", () => {
  const h = viewsFixture(); h.button("My view").props.onClick();
  assert.deepEqual(plain(h.applied[0]), { tab: "needs-review", sev: null, source: null,
    range: null, intent: null, q: "battery" });
});
test("Save view captures current filters and rename keeps the saved filters", async () => {
  const h = viewsFixture({ sev: "high", q: "live search", signals: "1" });
  h.button("Save view").props.onClick();
  const input = () => nodes(h.render()).find(n => n.type === "input" && n.props["aria-label"] === "View name");
  input().props.onChange({ target: { value: "New view" } });
  await nodes(h.render()).find(n => n.type === "form").props.onSubmit({ preventDefault() {} });
  assert.deepEqual(plain(h.calls[0]), ["create", "New view", { sev: "high", q: "live search" }, 2]);
  h.button("Rename My view").props.onClick(); input().props.onChange({ target: { value: "Renamed" } });
  await nodes(h.render()).find(n => n.type === "form").props.onSubmit({ preventDefault() {} });
  assert.deepEqual(plain(h.calls[1]), ["update", 7, "Renamed", h.saved.params, 2]);
  await h.button("Delete My view").props.onClick();
  assert.deepEqual(plain(h.calls[2]), ["delete", 7, 2]);
});

test("shared Ask falls back from streaming and retains explicit product scope", async () => {
  const calls = [];
  const h = harness("../src/screens/Chat.tsx", { "../api": { canReview: () => false, api: {
    chatStream: async (...args) => { calls.push(["stream", args[3]]); throw Error("stream unavailable"); },
    chat: async (...args) => { calls.push(["chat", args[2]]); return { type: "answer", text: "Fallback answer" }; },
  } } });
  const render = () => h.render(m => m.AskConversation({ productId: 2, productName: "Lumo", onOpenInvestigation() {} }));
  await nodes(render()).find(n => n.type === "button" && text(n).includes("biggest unresolved")).props.onClick();
  assert.deepEqual(calls, [["stream", 2], ["chat", 2]]);
  assert.ok(text(render()).includes("Fallback answer"));
});

let failed = 0;
for (const [name, fn] of tests) {
  try { await fn(); console.log(`PASS ${name}`); }
  catch (error) { failed++; console.error(`FAIL ${name}: ${error.stack}`); }
}
console.log(`${tests.length - failed}/${tests.length} Ask/views checks passed`);
if (failed) process.exitCode = 1;
