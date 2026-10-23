import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";

// Render the production JSX with deterministic hooks and local API fixtures.
// No browser, network, or extra dependencies are needed.
function harness(file, stubs = {}) {
  const slots = []; let cursor = 0;
  const react = {
    useState(initial) { const i = cursor++; if (!(i in slots)) slots[i] = initial;
      return [slots[i], x => { slots[i] = typeof x === "function" ? x(slots[i]) : x; }]; },
    useEffect() {}, useRef(x) { return { current: x }; }, useMemo(fn) { return fn(); },
  };
  const jsx = (type, props) => ({ type, props: props ?? {} });
  const passthrough = p => jsx("div", { children: [p.title, p.children] });
  const cache = new Map();
  function load(url) {
    if (cache.has(url.href)) return cache.get(url.href);
    const exports = {}; cache.set(url.href, exports);
    const require = name => {
      if (name === "react") return react;
      if (name === "react/jsx-runtime") return { jsx, jsxs: jsx, Fragment: "fragment" };
      if (name in stubs) return stubs[name];
      if (name.endsWith("/ui")) return new Proxy({}, { get: () => passthrough });
      if (name.endsWith("/components/Icon")) return { Icon: () => null };
      if (name.endsWith("/components/CaseCard")) return { CaseCard: passthrough };
      if (name.endsWith("/components/Toast")) return { withToast: fn => fn() };
      if (name === "./TraceTab") return { TraceRow: () => null };
      const base = new URL(name, url);
      const child = [".ts", ".tsx"].map(ext => new URL(base.href + ext)).find(existsSync);
      if (!child) throw new Error(`Unexpected import ${name}`);
      return load(child);
    };
    const code = ts.transpileModule(readFileSync(url, "utf8"), { compilerOptions: {
      module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022,
    } }).outputText;
    vm.runInNewContext(code, { exports, require, setTimeout, clearTimeout,
      requestAnimationFrame: () => {}, URL, console });
    return exports;
  }
  const mod = load(new URL(file, import.meta.url));
  function expand(node) {
    if (Array.isArray(node)) return node.map(expand);
    if (!node || typeof node !== "object") return node;
    if (typeof node.type === "function") return expand(node.type(node.props));
    return { ...node, props: { ...node.props, children: expand(node.props.children) } };
  }
  return { mod, render(fn) { cursor = 0; return expand(fn(mod)); } };
}
const text = node => Array.isArray(node) ? node.map(text).join("") :
  node && typeof node === "object" ? text(node.props.children) : node == null || node === false ? "" : String(node);
const find = (node, pred) => {
  if (Array.isArray(node)) return node.flatMap(n => find(n, pred));
  if (!node || typeof node !== "object") return [];
  return [...(pred(node) ? [node] : []), ...find(node.props.children, pred)];
};
const tests = [];
const test = (name, fn) => tests.push([name, fn]);

function casesFixture(quotes = 1) {
  const signals = [
    { slug: "battery", title: "Battery drain", z: 2.8 },
    { slug: "battery-issues", title: "Battery reports", z: 2.1 },
    { slug: "spike", title: "1-star reviews are spiking", z: 4.0 },
    { slug: "drop", title: "Rating falling", z: 3.1 },
    { slug: "standalone", title: "Export crashes", z: 3.7 },
  ].map(s => ({ ...s, type: "manual", age_days: null, window: "7d" }));
  const board = { cases: [], signals, counts: {}, incidents: [
    { key: "battery", lead: "battery", title: "Battery drain", z: 2.8, members: ["battery", "battery-issues"] },
    { key: "spike", lead: "spike", title: "1-star reviews are spiking", z: 4.0, members: ["spike", "drop"] },
  ] };
  let calls = 0;
  const h = harness("../src/screens/Cases.tsx", {
    "../api": { api: {}, canReview: () => false },
    "../hooks": { useAsync: () => ({ data: calls++ % 2 === 0 ? board : {
      candidates: [], requests: [{ slug: "dark", statement: "Dark mode", count: quotes,
        verbatims: Array(quotes).fill("Please add dark mode"), trend: [] }],
    } }) },
  });
  return h.render(m => m.Cases({ productName: "Polish", params: { signals: "1" }, setParams() {} }));
}
test("Cases interleaves incidents and standalone signals by severity and z", () => {
  const titles = find(casesFixture(), n => n.type === "input" && n.props.type === "checkbox")
    .map(n => n.props["aria-label"] ?? "standalone");
  assert.deepEqual(titles, ["Select incident: 1-star reviews are spiking", "Select: Export crashes", "Select incident: Battery drain"]);
});
for (const n of [1, 2]) test(`Requests pluralizes ${n} example reviews`, () => {
  assert.ok(find(casesFixture(n), node => node.type === "button" && text(node).trim() === `show ${n} example review${n === 1 ? "" : "s"}`).length > 0);
});

function evidenceFixture(status, fix, needsReview = false) {
  const h = harness("../src/screens/case/Inspector.tsx", {
    "../../api": { api: {}, canReview: () => false }, "../../hooks": { useTrace: () => ({ steps: [] }) },
  });
  return h.render(m => m.EvidenceDetail({ evidence: { id: "ev_1", source: "play_store", ref: "r1",
    snippet: "Battery drains", supports: ["h1"], contradicts: [],
    retrieved_by: 'search_reviews({"query":"battery drain","rating_max":2,"date_from":"2026-10-16","date_to":"2026-10-23"})',
  }, inv: { hypotheses: [{ id: "h1", statement: "Background sync", status: "supported" }],
    finding: { status, fix: fix ? { status: fix } : null, needs_review: needsReview ? {} : null } } }));
}
for (const [status, fix, needsReview] of [["draft", null], ["approved", null], ["approved", "watching"],
  ["draft", "confirmed"], ["approved", "regressed"], ["approved", "confirmed", true]]) {
  test(`Inspector avoids proven for ${status}/${fix}/review=${!!needsReview}`, () => {
    const html = text(evidenceFixture(status, fix, needsReview));
    assert.ok(html.includes("supported hypothesis")); assert.ok(!html.includes("proven cause"));
  });
}
test("Inspector permits proven only after approval and a verified fix", () => {
  assert.ok(text(evidenceFixture("approved", "confirmed")).includes("proven cause"));
});
test("Found by is readable and preserves the raw tool call", () => {
  const tree = evidenceFixture("draft", null);
  assert.ok(text(tree).includes("Search reviews for 'battery drain', 1\u20132\u2605, Oct 16\u201323"));
  assert.ok(find(tree, n => n.props.title?.includes('search_reviews({')).length > 0);
});

test("Ask queues the named incident through the Cases API", async () => {
  const queued = [], forced = [];
  const h = harness("../src/screens/Chat.tsx", { "../api": { canReview: () => true, api: {
    chatStream: async (q, cb, force) => { forced.push(force); return { type: "answer", text: "The strongest is battery drain",
      basis: { kind: "signals", label: "Waiting", caution: "Uninvestigated" },
      next_step: { kind: "investigate", question: "Battery drain", slug: "battery", allowed: true } }; },
    queueThemes: async (...args) => { queued.push(args); return { queued: [{ queue_id: 8 }], already: [] }; },
  } } });
  const render = () => h.render(m => m.Chat({ productName: "Polish", onOpenInvestigation() {} }));
  let tree = render();
  await find(tree, n => n.type === "button" && text(n).includes("biggest unresolved"))[0].props.onClick();
  tree = render();
  await find(tree, n => n.type === "button" && text(n).trim() === "Start investigation")[0].props.onClick();
  assert.deepEqual(JSON.parse(JSON.stringify(queued)), [[["battery"], { battery: "Battery drain" }, "quick", null]]);
  assert.deepEqual(forced, [false]);
  assert.ok(text(render()).includes("Queued for investigation"));
});

test("Ask respects an explicit absence of an investigation target", async () => {
  const h = harness("../src/screens/Chat.tsx", { "../api": { canReview: () => true, api: {
    chatStream: async () => ({ type: "answer", text: "No waiting incidents", can_investigate: true,
      next_step: null }),
  } } });
  const render = () => h.render(m => m.Chat({ productName: "Polish", onOpenInvestigation() {} }));
  await find(render(), n => n.type === "button" && text(n).includes("biggest unresolved"))[0].props.onClick();
  assert.ok(!text(render()).includes("Investigate again anyway"));
});

test("Ask still investigates literal topic questions without a signal target", async () => {
  const calls = [];
  const h = harness("../src/screens/Chat.tsx", { "../api": { canReview: () => true, api: {
    chatStream: async (q, cb, force) => { calls.push([q, force]); return force
      ? { type: "investigation", text: "Opening", investigation_id: 9 }
      : { type: "answer", text: "No findings", next_step: {
          kind: "investigate", question: "Tell me about battery drain", allowed: true } }; },
  } } });
  const render = () => h.render(m => m.Chat({ productName: "Polish", onOpenInvestigation() {} }));
  await find(render(), n => n.type === "button" && text(n) === "Tell me about battery drain")[0].props.onClick();
  await find(render(), n => n.type === "button" && text(n).trim() === "Start investigation")[0].props.onClick();
  assert.deepEqual(calls, [["Tell me about battery drain", false], ["Tell me about battery drain", true]]);
});

let failures = 0;
for (const [name, fn] of tests) {
  try { await fn(); console.log(`PASS ${name}`); }
  catch (e) { failures++; console.error(`FAIL ${name}: ${e.stack}`); }
}
console.log(`${tests.length - failures}/${tests.length} polish checks passed`);
if (failures) process.exitCode = 1;
