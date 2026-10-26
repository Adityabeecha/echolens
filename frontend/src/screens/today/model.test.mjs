import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";

function load(path, imports = {}) {
  const exports = {};
  const source = readFileSync(new URL(path, import.meta.url), "utf8");
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText,
    { exports, require: (name) => { assert.ok(name in imports, name); return imports[name]; } });
  return exports;
}
const stamps = load("../../components/casefile/stampFor.ts");
const model = load("./model.ts", { "../../components/casefile/stampFor": stamps });
const row = (id, rank, status, extra = {}) => ({ id, decision_rank: rank, status, title:`Problem ${id}`, ...extra });
const confirmed = row(1, 1, "needs_review", { trust:{ two_source_ok:true, distinct_sources:3 }, confidence:.89 });
const hunch = row(2, 2, "needs_human", { confidence:.72 });

const ordered = model.openProblems([hunch, row(3, 0, "verified_fixed"), confirmed,
  row(4, 0, "resolved", { decision:{ hidden:true } }), row(5, 0, "dismissed")], []);
assert.deepEqual(Array.from(ordered, x=>x.id), [1,2], "closed and parked work cannot displace the backend's first decision");
assert.equal(model.headline({ focus:confirmed, count:2, drag:.84 }), "One bug costs about 0.84 stars.");
assert.equal(model.headline({ focus:hunch, count:2, drag:.84 }), "Two problems are worth your time this week.", "a hunch cannot claim a proven rating loss");
assert.equal(model.headline({ focus:confirmed, count:1, drag:null }), "One problem is worth your time this week.");
assert.equal(model.headline({ count:0, hasData:false }), "Your first review is the starting point.");
assert.equal(model.headline({ count:0, hasData:true }), "Nothing needs you right now.");
assert.equal(model.headline({ count:0, hasData:true, spikes:3 }), "Three review spikes are ready for a decision.");
assert.equal(model.headline({ count:0, hasData:true, stale:1 }), "One feedback source needs attention.");
assert.deepEqual(Array.from(model.openProblems([confirmed,hunch], [{ investigation_id:1,status:"watching" }]), x=>x.id), [2]);
assert.equal(model.liveStep({ kind:"TOOL",text:"search_github_issues(query='sync')" }), "Checking GitHub…");
assert.equal(model.liveStep({ kind:"TOOL",text:"import json; print(result)" }), "Checking a source…");
assert.equal(model.liveStep(null), "Waiting for the next step…");
assert.equal(model.fixSentence({ baseline_rate:6, post_rate:0, fixed_in_version:"3.1.4" }),
  "Complaints fell from 6 a day to zero after version 3.1.4.");
assert.equal(model.fixSentence({ baseline_rate:.02, post_rate:.001, fixed_in_version:null }),
  "Complaints fell from 0.02 a day to 0.001 after the fix.");
assert.equal(model.fixSentence({ baseline_rate:null, post_rate:null, fixed_in_version:null }),
  "The complaint watch confirmed this fix. Open the proof for the comparison.");
assert.equal(model.fixTitle("large-video crash share of negative reviews"), "Your large-video crash fix worked.");
assert.equal(model.watchProgress({ status:"watching",release_seen_at:"2026-10-20",fix_date:"2026-10-01",window_days:14 }, new Date("2026-10-25T12:00:00Z")), "day 6 of 14");
assert.equal(model.watchProgress({ status:"waiting_for_release",fix_date:"2026-10-01" }, new Date("2026-10-25")), "waiting for the fixed version to reach reviewers");
assert.equal(model.watchProgress({ status:"watching",fix_date:"2026-10-01",window_days:14 }, new Date("2026-10-25")), "14-day watch complete · checking the result");
assert.equal(model.plainWords("case #12: hypothesis after an anomaly"), "problem #12: possible cause after a spike");
console.log("PASS Today: rank, honest headlines, live steps, measured fixes and release-based watch dates (20 checks)");
