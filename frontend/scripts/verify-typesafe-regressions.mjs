import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import vm from "node:vm";
import ts from "typescript";

// Execute production hooks/handlers with deterministic effects, network replies,
// and timers. No browser, new dependencies, or external services are required.
const require = createRequire(import.meta.url);
const flush = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
function harness(file, dependencies = {}) {
  const slots = [], effects = [], timers = new Map();
  let cursor = 0, nextTimer = 1;
  const react = {
    useState(initial) { const i = cursor++; if (!(i in slots)) slots[i] = initial; return [slots[i], value => { slots[i] = typeof value === "function" ? value(slots[i]) : value; }]; },
    useRef(initial) { const i = cursor++; return slots[i] ??= { current: initial }; },
    useCallback(fn) { cursor++; return fn; },
    useEffect(fn, deps) { const i = cursor++; const old = effects[i]; if (!old || deps.some((d, n) => d !== old.deps[n])) { old?.cleanup?.(); effects[i] = { deps, fn }; } },
  };
  const exports = {};
  const schedule = fn => { const id = nextTimer++; timers.set(id, fn); return id; };
  const source = ts.transpileModule(readFileSync(new URL(file, import.meta.url), "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 } }).outputText;
  vm.runInNewContext(source, { exports, require: name => name === "react" ? react : dependencies[name] ?? require(name), setTimeout: schedule, setInterval: schedule, clearTimeout: id => timers.delete(id), clearInterval: id => timers.delete(id), EventSource: class { constructor() { throw new Error("SSE unavailable"); } } });
  return { exports, timers, render(fn) { cursor = 0; const result = fn(); for (const effect of effects) if (effect?.fn) { const fn = effect.fn; delete effect.fn; effect.cleanup = fn(); } return result; } };
}
const tests = [];
function test(name, fn) { tests.push([name, fn]); }

test("a previous product's watcher reply cannot announce its case in the new product", async () => {
  const old = deferred(), fresh = deferred(); let calls = 0, announced = [];
  const h = harness("../src/hooks.ts", { "./api": { api: { investigations: () => (++calls === 1 ? old : fresh).promise } } });
  h.render(() => h.exports.useWorkWatcher(1, 0, () => {}, 4000, id => announced.push(id)));
  h.render(() => h.exports.useWorkWatcher(2, 0, () => {}, 4000, id => announced.push(id)));
  fresh.resolve({ investigations: [] }); await flush();
  old.resolve({ investigations: [{ id: 99, status: "running" }] }); await flush();
  assert.deepEqual(announced, []);
});

test("a pending trace response cannot overwrite the newly selected case", async () => {
  const old = deferred(), fresh = deferred();
  const h = harness("../src/hooks.ts", { "./api": { api: { trace: id => (id === 1 ? old : fresh).promise } } });
  h.render(() => h.exports.useTrace(1));
  h.render(() => h.exports.useTrace(2));
  fresh.resolve({ status: "running", steps: [{ seq: 1, detail: "new case" }] }); await flush();
  old.resolve({ status: "resolved", steps: [{ seq: 9, detail: "old case" }] }); await flush();
  const result = h.render(() => h.exports.useTrace(2));
  assert.equal(result.status, "running");
  assert.deepEqual(Array.from(result.steps, s => s.detail), ["new case"]);
});

test("slow trace polling never overlaps requests", async () => {
  const pending = deferred(); let calls = 0;
  const h = harness("../src/hooks.ts", { "./api": { api: { trace: () => { calls++; return pending.promise; } } } });
  h.render(() => h.exports.useTrace(1));
  for (const tick of [...h.timers.values()]) tick();
  assert.equal(calls, 1);
});

function nodes(tree) { if (tree == null || typeof tree !== "object") return []; if (Array.isArray(tree)) return tree.flatMap(nodes); return [tree, ...nodes(tree.props?.children)]; }
const theme = { C: {}, R: {}, S: {}, T: {} };
const ui = new Proxy({}, { get: (_, name) => String(name) });
test("dropping an automatic proposal preserves explicit overrides without excluding overflow", async () => {
  let saved;
  const plan = { proposed: [{ investigation_id: 1 }, { investigation_id: 2 }], deferred: [{ investigation_id: 3 }, { investigation_id: 4 }], included: [2], excluded: [4], capacity_days: 20, projected_stars: 0, resolution_rate: 0, notes: {} };
  const h = harness("../src/screens/Backlog.tsx", { "../api": { canReview: () => true, api: { backlogPlan: async () => plan, saveBacklogPlan: async body => { saved = body; return plan; } } }, "../theme": theme, "../ui": ui, "../components/Icon": ui });
  const render = () => h.exports.Backlog({});
  h.render(render); await flush();
  const tree = h.render(render);
  nodes(tree).find(n => n.props?.item?.investigation_id === 1).props.onToggle(); await flush();
  assert.deepEqual(JSON.parse(JSON.stringify(saved)), { included: [2], excluded: [4, 1], capacity_days: 20 });
});

test("capacity edits preserve only saved pins and exclusions", async () => {
  let saved;
  const plan = { proposed: [{ investigation_id: 1 }], deferred: [{ investigation_id: 3 }], included: [], excluded: [], capacity_days: 20, projected_stars: 0, resolution_rate: 0, notes: {} };
  const h = harness("../src/screens/Backlog.tsx", { "../api": { canReview: () => true, api: { backlogPlan: async () => plan, saveBacklogPlan: async body => { saved = body; return plan; } } }, "../theme": theme, "../ui": ui, "../components/Icon": ui });
  const render = () => h.exports.Backlog({});
  h.render(render); await flush();
  const input = () => nodes(h.render(render)).find(n => n.props?.["aria-label"] === "Capacity in engineer-days");
  input().props.onChange({ target: { value: "40" } });
  input().props.onBlur(); await flush();
  assert.deepEqual(JSON.parse(JSON.stringify(saved)), { included: [], excluded: [], capacity_days: 40 });
});

test("trace polling stops after a terminal reply", async () => {
  let calls = 0;
  const h = harness("../src/hooks.ts", { "./api": { api: { trace: async () => { calls++; return { status: "resolved", steps: [] }; } } } });
  h.render(() => h.exports.useTrace(1)); await flush();
  assert.equal(h.timers.size, 0);
  assert.equal(calls, 1);
  assert.equal(h.render(() => h.exports.useTrace(1)).status, "resolved");
});

let failed = 0;
for (const [name, fn] of tests) { try { await fn(); console.log(`PASS ${name}`); } catch (error) { failed++; console.error(`FAIL ${name}\n${error.stack}`); } }
if (failed) process.exitCode = 1;
