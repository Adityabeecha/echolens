import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import vm from "node:vm";
import ts from "typescript";

const source = readFileSync(new URL("../src/components/casefile/stampFor.ts", import.meta.url), "utf8");
const exports = {};
vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, { exports });
for (const [input, verdict] of [
  [{ status: "resolved" }, "hunch"],
  [{ support_level: "supported" }, "confirmed"],
  [{ trust: { two_source_ok: true } }, "confirmed"],
  [{ status: "needs_human", support_level: "supported" }, "hunch"],
  [{ support_level: "single_channel" }, "hunch"],
  [{ support_level: "supported", needs_review: true }, "hunch"],
  [{ support_level: "supported", trust: { two_source_ok: false } }, "hunch"],
  [{ trust: { two_source_ok: true }, needs_review: { reason: "Struck proof", at: "2026-10-25", eid: "A" } }, "hunch"],
  [{ support_level: "supported", capped: true }, "hunch"],
  [{ status: "watching" }, "hunch"],
  [{ intent: "feature_request" }, "request"],
  [{ case_status: "verified_fixed" }, "fixWorked"],
  [{ finding: { fix: { status: "confirmed" } } }, "fixWorked"],
  [{ fix: { status: "persists_reopened" } }, "reopened"],
  [{ status: "running", finding: { support_level: "supported" } }, "live"],
  [{ status: "queued" }, "live"],
]) assert.equal(exports.stampFor(input), verdict, JSON.stringify(input));

// Screen builders must be able to pass the existing API objects without casts.
const fixture = fileURLToPath(new URL("stamp-api-types.ts", import.meta.url)).replaceAll("\\", "/");
const code = `import type { CaseRow, Investigation, Finding } from '../src/api';
import { stampFor } from '../src/components/casefile/stampFor';
declare const row: CaseRow; declare const investigation: Investigation; declare const finding: Finding;
stampFor(row); stampFor(investigation); stampFor(finding);`;
const options = { noEmit: true, strict: true, skipLibCheck: true, types: ["vite/client"], target: ts.ScriptTarget.ES2022,
  module: ts.ModuleKind.ESNext, moduleResolution: ts.ModuleResolutionKind.Bundler };
const host = ts.createCompilerHost(options);
const getSourceFile = host.getSourceFile.bind(host);
host.getSourceFile = (file, ...args) => file === fixture
  ? ts.createSourceFile(file, code, options.target, true) : getSourceFile(file, ...args);
const diagnostics = ts.getPreEmitDiagnostics(ts.createProgram([fixture], options, host));
assert.equal(diagnostics.length, 0, ts.formatDiagnosticsWithColorAndContext(diagnostics, {
  getCanonicalFileName: (file) => file, getCurrentDirectory: () => process.cwd(), getNewLine: () => "\n",
}));
console.log("PASS approved verdicts distinguish proof, hunches, requests, fixes and live work");
console.log("PASS case rows, investigations and findings fit the shared verdict helper");
