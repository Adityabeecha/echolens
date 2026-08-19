import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const css = readFileSync(new URL("../src/tokens.css", import.meta.url), "utf8");
const app = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const sidebar = readFileSync(new URL("../src/components/Sidebar.tsx", import.meta.url), "utf8");
const today = readFileSync(new URL("../src/screens/Today.tsx", import.meta.url), "utf8");
const evidence = readFileSync(new URL("../src/components/EvidenceSheet.tsx", import.meta.url), "utf8");
const newCase = readFileSync(new URL("../src/components/NewCaseModal.tsx", import.meta.url), "utf8");
const deleteProduct = readFileSync(new URL("../src/components/DeleteProductModal.tsx", import.meta.url), "utf8");

const requiredCss = [
  "HUMAN PRECISION UI",
  "--el-canvas-warm",
  "--el-nav-ink",
  "--el-accent-teal",
  "@media (max-width: 1200px)",
  "@media (max-width: 900px)",
  "@media (max-width: 720px)",
  "@media (max-width: 320px)",
  "env(safe-area-inset-bottom)",
  ":focus-visible",
  "prefers-reduced-motion",
  ".el-mobile-context",
  ".el-mobile-task-nav",
  ".el-attention-brief",
  ".el-overlay-panel",
];

for (const token of requiredCss) {
  assert.ok(css.includes(token), `responsive contract is missing ${token}`);
}

assert.ok(app.includes("el-mobile-context"), "App must expose the mobile product context bar");
assert.ok(sidebar.includes("el-mobile-task-nav"), "Sidebar must expose mobile task navigation");
assert.ok(today.includes("el-attention-brief"), "Today must expose the attention briefing composition");
assert.ok(today.includes("Reading today's signals"), "Today must not claim a settled state while loading");
assert.ok(today.includes('loading ? "Checking investigations"'), "Today header must keep activity unknown while loading");
assert.ok(evidence.includes('aria-label="Close evidence"'), "Evidence sheet close control needs an accessible name");
assert.ok(newCase.includes("useDialog(onClose, true, !busy)"), "New Case must keep focus contained while busy");
assert.ok(deleteProduct.includes("useDialog(onClose, true, !busy)"), "Delete Product must keep focus contained while busy");
assert.ok(css.includes(".el-nav-brand > span:last-child"), "Compact navigation must collapse brand copy");

console.log("Responsive UI contract verified.");
