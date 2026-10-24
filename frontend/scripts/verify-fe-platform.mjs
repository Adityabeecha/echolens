import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync, cpSync, mkdirSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

// Clean URLs, the Costs redirect, request time limits and cancellation, and the
// Vercel same-origin proxy output. No browser, network or new dependency.
const require = createRequire(import.meta.url);
const ts = require("typescript");
const compile = path => ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8")
  .replaceAll("import.meta.env.VITE_API_BASE", "undefined"), { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const load = (path, globals = {}) => {
  const exports = {};
  vm.runInNewContext(compile(path), { exports, ...globals });
  return exports;
};
const tests = [];
const test = (name, fn) => tests.push([name, fn]);

const nav = load("../src/nav.ts", { window: { location: { pathname: "/", search: "", hash: "" } } });

test("routes format as clean paths and parse back", () => {
  const cases = [
    { screen: "today", productId: 2 },
    { screen: "cases", productId: 2, params: { tab: "running" } },
    { screen: "case", id: 34, tab: "trace", productId: 2 },
    { screen: "case", id: 34, tab: "finding", productId: 2 },
    { screen: "portfolio", productId: null },
  ];
  const paths = cases.map(nav.formatRoute);
  assert.deepEqual(paths, ["/p/2/today", "/p/2/cases?tab=running", "/p/2/cases/34/trace",
    "/p/2/cases/34", "/portfolio"]);
  for (const p of paths) assert.equal(nav.formatRoute(nav.parseRoute(p)), p);
});

test("old hash links redirect to the clean path, share links included", () => {
  assert.equal(nav.legacyHashTarget("#/p/2/today"), "/p/2/today");
  assert.equal(nav.legacyHashTarget("#/p/1/case/34/finding"), "/p/1/cases/34");
  assert.equal(nav.legacyHashTarget("#case/12"), "/cases/12");
  assert.equal(nav.legacyHashTarget("#/share/abcdefghijklmnop1234"), "/share/abcdefghijklmnop1234");
  assert.equal(nav.legacyHashTarget("#section-3"), null);
  assert.equal(nav.legacyHashTarget(""), null);
  assert.equal(nav.shareToken("/share/abcdefghijklmnop1234"), "abcdefghijklmnop1234");
  assert.equal(nav.shareToken("/p/1/today"), null);
});

test("costs links open Settings → Costs", () => {
  assert.equal(nav.formatRoute(nav.parseRoute("/p/3/costs")), "/p/3/settings?section=costs");
  assert.equal(nav.formatRoute(nav.parseRoute("#/p/3/costs")), "/p/3/settings?section=costs");
  assert.ok(nav.SETTINGS_SECTIONS.includes("costs"));
  const sidebar = readFileSync(new URL("../src/components/Sidebar.tsx", import.meta.url), "utf8");
  assert.ok(!/key: "costs"/.test(sidebar), "Costs is no longer a System nav entry");
});

// api.ts with a fetch that never answers until aborted, and timers we control.
function apiWith({ fireTimers = false } = {}) {
  const calls = [];
  const timers = [];
  const exports = load("../src/api.ts", {
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    document: { cookie: "" }, URLSearchParams, AbortController, DOMException, TypeError,
    setTimeout: (fn, ms) => { timers.push({ fn, ms }); if (fireTimers) queueMicrotask(fn); return timers.length; },
    clearTimeout() {},
    fetch: (url, init) => new Promise((resolve, reject) => {
      calls.push({ url, init });
      init.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
    }),
  });
  return { exports, calls, timers };
}

test("every call gets a time limit; slow calls get more", () => {
  const { exports } = apiWith();
  assert.equal(exports.timeoutFor("/cases?product_id=1"), 15000);
  assert.equal(exports.timeoutFor("/investigations"), 60000);
  assert.equal(exports.timeoutFor("/chat"), 60000);
  assert.equal(exports.timeoutFor("/collectors/run?product_id=1"), 60000);
  assert.equal(exports.timeoutFor("/investigations/4?product_id=1"), 15000);
});

test("a read that never answers ends as RequestTimeout", async () => {
  const { exports } = apiWith({ fireTimers: true });
  await assert.rejects(exports.api.cases(), (e) => e.name === "RequestTimeout");
  assert.match(exports.errorMessage(new exports.RequestTimeout("/x", 15000)), /Request timed out/);
});

test("a product switch cancels reads in flight, never writes", async () => {
  const { exports, calls } = apiWith();
  exports.startSession("csrf");
  exports.setActiveProduct(1);
  const read = exports.api.cases().catch((e) => e);
  const write = exports.api.cancelQueued(5).catch((e) => e);
  await Promise.resolve();
  exports.setActiveProduct(2);
  const err = await read;
  assert.equal(err.name, "AbortError");
  for (let i = 0; i < 8; i++) await Promise.resolve();   // the write awaits its CSRF header first
  const writeCall = calls.find((c) => c.init.method === "DELETE");
  assert.ok(writeCall && !writeCall.init.signal.aborted, "the write is still in flight");
  void write;
});

test("the Vercel proxy output is written only when ECHOLENS_API_ORIGIN is set", () => {
  const here = fileURLToPath(new URL("..", import.meta.url));
  const dir = mkdtempSync(join(tmpdir(), "el-vercel-"));
  try {
    mkdirSync(join(dir, "dist"));
    writeFileSync(join(dir, "dist", "index.html"), "<!doctype html>");
    cpSync(join(here, "vercel.json"), join(dir, "vercel.json"));
    const script = join(here, "build", "vercel-output.mjs");
    execFileSync(process.execPath, [script], { cwd: dir, env: { ...process.env, ECHOLENS_API_ORIGIN: "" } });
    assert.ok(!existsSync(join(dir, ".vercel")), "no proxy without the variable");
    execFileSync(process.execPath, [script], { cwd: dir,
      env: { ...process.env, ECHOLENS_API_ORIGIN: "https://api.example.code.run/" } });
    const cfg = JSON.parse(readFileSync(join(dir, ".vercel", "output", "config.json"), "utf8"));
    assert.deepEqual(cfg.routes[0], { src: "^/api/(.*)$", dest: "https://api.example.code.run/$1" });
    assert.deepEqual(cfg.routes.at(-1), { src: "^/(.*)$", dest: "/index.html" });
    const csp = cfg.routes[1].headers["Content-Security-Policy"];
    assert.match(csp, /connect-src 'self' https:\/\/accounts\.google\.com\/gsi\/;/);
    assert.ok(existsSync(join(dir, ".vercel", "output", "static", "index.html")));
    assert.throws(() => execFileSync(process.execPath, [script], { cwd: dir, stdio: "pipe",
      env: { ...process.env, ECHOLENS_API_ORIGIN: "http://insecure.example" } }));
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

let failed = 0;
for (const [name, fn] of tests) {
  try { await fn(); console.log(`PASS ${name}`); }
  catch (error) { failed++; console.error(`FAIL ${name}\n${error.stack}`); }
}
console.log(`${tests.length - failed}/${tests.length} platform checks passed`);
if (failed) process.exitCode = 1;
