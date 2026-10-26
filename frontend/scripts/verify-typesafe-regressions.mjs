import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import vm from "node:vm";
import ts from "typescript";

// Execute production hooks/handlers with deterministic effects, network replies,
// and timers. No browser, new dependencies, or external services are required.
const require = createRequire(import.meta.url);
const flush = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
const transpile = url => ts.transpileModule(readFileSync(url, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 } }).outputText;
// A relative import the test did not stub runs as the REAL source module (e.g.
// Backlog's ../format), so a new pure helper import cannot break the harness
// and the code under test still sees its true behaviour. Stubs always win.
function realModule(from, name, resolve) {
  const base = new URL(name, from);
  const url = [".ts", ".tsx", "/index.ts", "/index.tsx"].map(ext => new URL(base.href + ext)).find(u => existsSync(u));
  if (!url) throw new Error(`harness cannot resolve ${name} from ${from.pathname}`);
  const exports = {};
  vm.runInNewContext(transpile(url), { exports, require: n => resolve(n, url) });
  return exports;
}
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
  const entry = new URL(file, import.meta.url), loaded = new Map();
  const resolve = (name, from) => {
    if (name === "react") return react;
    if (from === entry && name in dependencies) return dependencies[name];
    if (!name.startsWith(".")) return require(name);
    const key = new URL(name, from).href;
    if (!loaded.has(key)) loaded.set(key, realModule(from, name, resolve));
    return loaded.get(key);
  };
  vm.runInNewContext(transpile(entry), { exports, require: name => resolve(name, entry), setTimeout: schedule, setInterval: schedule, clearTimeout: id => timers.delete(id), clearInterval: id => timers.delete(id), EventSource: class { constructor() { throw new Error("SSE unavailable"); } } });
  return { exports, timers, unmount() { for (const effect of effects) effect?.cleanup?.(); slots.length=0; effects.length=0; timers.clear(); }, render(fn) { cursor = 0; const result = fn(); for (const effect of effects) if (effect?.fn) { const fn = effect.fn; delete effect.fn; effect.cleanup = fn(); } return result; } };
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
  const h = harness("../src/screens/plan/usePlan.ts", { "../../api": { canReview: () => true, isGuest: () => false, getSessionGeneration:()=>0, getActiveProduct:()=>1, api: { backlogPlan: async () => plan, saveBacklogPlan: async body => { saved = body; return plan; } } } });
  const render = () => h.exports.usePlan();
  h.render(render); await flush();
  const controller = h.render(render), draft = controller.draft;
  controller.change({...draft,included:draft.included.filter(x=>x!==1),excluded:[...draft.excluded,1]});
  await controller.flush();
  assert.deepEqual(JSON.parse(JSON.stringify(saved)), { included: [2], excluded: [4, 1], capacity_days: 20,overrides:{},kind:"bugs" });
});

test("capacity edits preserve only saved pins and exclusions", async () => {
  let saved;
  const plan = { proposed: [{ investigation_id: 1 }], deferred: [{ investigation_id: 3 }], included: [], excluded: [], capacity_days: 20, projected_stars: 0, resolution_rate: 0, notes: {} };
  const h = harness("../src/screens/plan/usePlan.ts", { "../../api": { canReview: () => true,isGuest:()=>false,getSessionGeneration:()=>0,getActiveProduct:()=>1,api: { backlogPlan: async () => plan, saveBacklogPlan: async body => { saved = body; return plan; } } } });
  const render = () => h.exports.usePlan();
  h.render(render); await flush();
  const controller=h.render(render);controller.change({...controller.draft,capacity_days:40});
  await controller.flush();
  assert.deepEqual(JSON.parse(JSON.stringify(saved)), { included: [], excluded: [], capacity_days: 40,overrides:{},kind:"bugs" });
});

test("trace polling stops after a terminal reply", async () => {
  let calls = 0;
  const h = harness("../src/hooks.ts", { "./api": { api: { trace: async () => { calls++; return { status: "resolved", steps: [] }; } } } });
  h.render(() => h.exports.useTrace(1)); await flush();
  assert.equal(h.timers.size, 0);
  assert.equal(calls, 1);
  assert.equal(h.render(() => h.exports.useTrace(1)).status, "resolved");
});

test("serial plan saves keep newer edits and the originating product", async () => {
  let active=1;const old=deferred(),saves=[];
  const plan={proposed:[],deferred:[],included:[],excluded:[],capacity_days:20,overrides:{}};
  const h=harness("../src/screens/plan/usePlan.ts",{"../../api":{canReview:()=>true,isGuest:()=>false,getSessionGeneration:()=>0,getActiveProduct:()=>active,api:{backlogPlan:async()=>plan,
    saveBacklogPlan:async(body,kind,pid)=>{saves.push({days:body.capacity_days,pid});return saves.length===1?old.promise:{...plan,capacity_days:body.capacity_days};}}}});
  const render=()=>h.exports.usePlan();h.render(render);await flush();
  let c=h.render(render);c.change({...c.draft,capacity_days:30});const first=c.flush();await flush();
  c=h.render(render);c.change({...c.draft,capacity_days:40});const second=c.flush();active=2;
  assert.equal(saves.length,1);old.resolve({...plan,capacity_days:30});await first;await second;
  assert.deepEqual(saves,[{days:30,pid:1},{days:40,pid:1}]);assert.equal(h.render(render).draft.capacity_days,40);
});

test("a failed plan save leaves edits available for a successful retry", async () => {
  let attempts=0;const plan={proposed:[],deferred:[],included:[],excluded:[],capacity_days:20,overrides:{}};
  const h=harness("../src/screens/plan/usePlan.ts",{"../../api":{canReview:()=>true,isGuest:()=>false,getSessionGeneration:()=>0,getActiveProduct:()=>1,api:{backlogPlan:async()=>plan,
    saveBacklogPlan:async body=>{if(++attempts===1)throw Error("offline");return {...plan,capacity_days:body.capacity_days};}}}});
  const render=()=>h.exports.usePlan();h.render(render);await flush();const c=h.render(render);c.change({...c.draft,capacity_days:35});
  assert.equal(await c.flush(),false);assert.equal(h.render(render).draft.capacity_days,35);
  assert.equal(await h.render(render).flush(),true);assert.equal(h.render(render).error,null);assert.equal(attempts,2);
});

test("returning to Plan waits for its previous instance's save", async () => {
  const pending=deferred();let reads=0,writes=0;
  let plan={proposed:[],deferred:[],included:[],excluded:[],capacity_days:20,overrides:{}};
  const h=harness("../src/screens/plan/usePlan.ts",{"../../api":{canReview:()=>true,isGuest:()=>false,getSessionGeneration:()=>0,getActiveProduct:()=>1,getSessionGeneration:()=>0,api:{backlogPlan:async()=>{reads++;return plan;},
    saveBacklogPlan:async body=>{if(++writes===1)await pending.promise;plan={...plan,...body};return plan;}}}});
  const render=()=>h.exports.usePlan();h.render(render);await flush();let c=h.render(render);
  c.change({...c.draft,excluded:[1]});const save=c.flush();await flush();h.unmount();h.render(render);await flush();
  assert.equal(reads,1,"a remount must not read before the departing save commits");
  h.unmount();h.render(render);await flush();assert.equal(reads,1,"an unloaded remount must preserve the original handoff");
  pending.resolve();await save;await flush();c=h.render(render);assert.deepEqual(Array.from(c.draft.excluded),[1]);
  c.change({...c.draft,capacity_days:30});await c.flush();assert.equal(plan.capacity_days,30);assert.deepEqual(Array.from(plan.excluded),[1]);
});

test("a failed departing save restores the unsaved draft on return", async () => {
  const pending=deferred();let writes=0;
  const plan={proposed:[],deferred:[],included:[],excluded:[],capacity_days:20,overrides:{}};
  const h=harness("../src/screens/plan/usePlan.ts",{"../../api":{canReview:()=>true,isGuest:()=>false,getSessionGeneration:()=>0,getActiveProduct:()=>1,getSessionGeneration:()=>0,api:{backlogPlan:async()=>plan,
    saveBacklogPlan:async body=>{if(++writes===1){await pending.promise;throw Error("offline");}return {...plan,...body};}}}});
  const render=()=>h.exports.usePlan();h.render(render);await flush();let c=h.render(render);
  c.change({...c.draft,capacity_days:35});const save=c.flush();await flush();h.unmount();h.render(render);pending.resolve();await save;await flush();
  c=h.render(render);assert.equal(c.draft.capacity_days,35);assert.equal(c.pending,true);assert.match(c.error,/still here/);
  assert.equal(await c.flush(),true);assert.equal(writes,2);
});

test("queued plan writes and failed drafts never move into a new sign-in", async () => {
  const pending=deferred();let generation=0,writes=0;
  const plan={proposed:[],deferred:[],included:[],excluded:[],capacity_days:20,overrides:{}};
  const h=harness("../src/screens/plan/usePlan.ts",{"../../api":{canReview:()=>true,isGuest:()=>false,getActiveProduct:()=>1,getSessionGeneration:()=>generation,api:{backlogPlan:async()=>plan,
    saveBacklogPlan:async body=>{writes++;await pending.promise;return {...plan,...body};}}}});
  const render=()=>h.exports.usePlan();h.render(render);await flush();let c=h.render(render);
  c.change({...c.draft,capacity_days:30});const first=c.flush();await flush();c=h.render(render);c.change({...c.draft,capacity_days:40});const second=c.flush();
  h.unmount();generation++;pending.resolve();await first;assert.equal(await second,false);assert.equal(writes,1);
  h.render(render);await flush();assert.equal(h.render(render).draft.capacity_days,20);assert.equal(h.render(render).pending,false);
});

test("read-only plan previews do not turn into failed saves on return", async () => {
  const plan={proposed:[],deferred:[],included:[],excluded:[],capacity_days:20,overrides:{}};
  const h=harness("../src/screens/plan/usePlan.ts",{"../../api":{canReview:()=>false,isGuest:()=>false,getActiveProduct:()=>1,getSessionGeneration:()=>0,
    api:{backlogPlan:async()=>plan,saveBacklogPlan:()=>assert.fail("read-only write")}}});
  const render=()=>h.exports.usePlan();h.render(render);await flush();let c=h.render(render);c.change({...c.draft,capacity_days:40});
  h.unmount();h.render(render);await flush();c=h.render(render);assert.equal(c.draft.capacity_days,20);assert.equal(c.error,null);
});

test("sending a plan stops if sign-in changes while its save finishes", async () => {
  const pending=deferred();let generation=0,sends=0;
  const h=harness("../src/screens/plan/PlanExport.tsx",{
    "../../api":{getActiveProduct:()=>1,getSessionGeneration:()=>generation,canReview:()=>true,isGuest:()=>false,api:{exportPlan:async()=>{sends++;return {results:[]};}}},
    "../../hooks":{useAsync:()=>({data:{trackers:[{id:"github",configured:true}]},loading:false})},"../../nav":{formatRoute:()=>""},"../../ui":ui,
  });
  const render=()=>h.exports.PlanExport({kind:"bugs",count:1,flush:()=>pending.promise});
  nodes(h.render(render)).find(n=>n.type==="Button"&&n.props.children==="Send the plan to…").props.onClick();
  nodes(h.render(render)).find(n=>n.type==="Button"&&n.props.children==="GitHub Issues").props.onClick();
  generation++;pending.resolve(true);await flush();assert.equal(sends,0);
});

let failed = 0;
for (const [name, fn] of tests) { try { await fn(); console.log(`PASS ${name}`); } catch (error) { failed++; console.error(`FAIL ${name}\n${error.stack}`); } }
if (failed) process.exitCode = 1;
