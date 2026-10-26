import type { CaseRow, SpikeCategory } from "../../api";
import { StampVariant, stampFor } from "../../components/casefile/stampFor";
import { plural } from "../../format";

// What the Problems list decides about each row, kept out of the JSX so the
// tabs, the headline and the rows can never disagree.

export type ProblemTab = "all" | "confirmed" | "hunches" | "requests" | "watching" | "fixed";
export type ProblemSort = "important" | "newest" | "impact";

export const PROBLEM_TABS: { id: ProblemTab; label: string }[] = [
  { id: "all", label: "All" },
  { id: "confirmed", label: "Confirmed" },
  { id: "hunches", label: "Hunches" },
  { id: "requests", label: "Requests" },
  { id: "watching", label: "Watching" },
  { id: "fixed", label: "Fixed" },
];

export const SORTS: { id: ProblemSort; label: string }[] = [
  { id: "important", label: "Most important first" },
  { id: "newest", label: "Newest" },
  { id: "impact", label: "Biggest impact" },
];

/** Old Cases tabs still arrive in links and saved views: each keeps its filter. */
export const LEGACY_TABS: Record<string, { label: string; statuses: string[] }> = {
  "needs-review": { label: "Needs a decision", statuses: ["needs_review", "needs_human", "regressed"] },
  running: { label: "Being looked into", statuses: ["running"] },
  queued: { label: "Waiting to be looked into", statuses: ["queued"] },
  resolved: { label: "Finished", statuses: ["resolved", "verified_fixed"] },
  dismissed: { label: "Dismissed", statuses: ["dismissed"] },
};

/** A fix sent or shipped and not yet judged: the reviews are being watched. */
const WATCHING = new Set(["issue_open", "waiting_for_release", "watching"]);

export const verdictOf = (row: CaseRow): StampVariant => stampFor({
  status: row.status,
  support_level: row.support_level,
  needs_review: row.needs_review,
  trust: row.trust ?? null,
  intent: row.intent,
  fix: row.fix_status ? { status: row.fix_status } : null,
});

export const isWatching = (row: CaseRow) => !!row.fix_status && WATCHING.has(row.fix_status);

export function inTab(row: CaseRow, tab: ProblemTab): boolean {
  if (tab === "all") return true;
  if (tab === "watching") return isWatching(row);
  const v = verdictOf(row);
  if (tab === "fixed") return v === "fixWorked";
  if (tab === "requests") return v === "request";
  if (isWatching(row)) return false;          // it lives under Watching until judged
  return tab === "confirmed" ? v === "confirmed" : v === "hunch";
}

/** Waiting on a person: the same statuses the old "Needs review" tab counted. */
export const needsDecision = (row: CaseRow) => LEGACY_TABS["needs-review"].statuses.includes(row.status);

/** What a hunch is missing, in plain words. */
export function hunchGap(row: CaseRow): string {
  if (row.needs_review) return "a reviewer questioned the proof";
  if (row.status === "needs_human") return "needs your call";
  if (["failed", "insufficient_evidence", "budget_exhausted"].includes(row.status)) return "not enough proof yet";
  if (row.trust?.two_source_ok === false || ["single_channel", "single_source", "supported_single_channel"]
    .includes(row.support_level ?? "")) return "needs a second source";
  return "not proven yet";
}

const sure = (row: CaseRow) => row.confidence != null ? `we're ${Math.round(row.confidence * 100)}% sure` : null;
const share = (row: CaseRow) => row.impact && row.impact.affected_pct > 0
  ? `${Math.round(row.impact.affected_pct)}% of recent complaints` : null;

function opened(days: number): string {
  const d = Math.max(0, Math.round(days));
  if (d === 0) return "opened today";
  if (d < 30) return `opened ${d} ${plural(d, "day")} ago`;
  const m = Math.round(d / 30);
  return `opened ${m} ${plural(m, "month")} ago`;
}

/** The one muted line under a problem's title. */
export function detailLine(row: CaseRow): string {
  const v = verdictOf(row);
  const parts: (string | null)[] = [];
  if (row.status === "dismissed") {
    parts.push(`Dismissed — ${row.why}`);
  } else if (v === "live") {
    parts.push(row.status === "queued" ? row.why : row.iterations
      ? `Looking into it now · step ${row.iterations.done} of ${row.iterations.max}` : "Looking into it now");
  } else if (isWatching(row)) {
    parts.push(row.fix_status === "issue_open"
      ? `Sent to GitHub${row.issue_number ? ` #${row.issue_number}` : ""} · waiting for the fix`
      : "Fix shipped · watching the reviews", share(row));
  } else if (v === "fixWorked") {
    parts.push("The fix worked: complaints fell after it shipped");
  } else if (v === "reopened") {
    parts.push("Came back after the fix", share(row), sure(row));
  } else if (v === "request") {
    parts.push("Asked for by users", share(row));
  } else if (v === "hunch") {
    parts.push(hunchGap(row), share(row), sure(row));
  } else {
    parts.push(share(row), sure(row));
  }
  if (v !== "live" && row.age_days != null) parts.push(opened(row.age_days));
  const line = parts.filter(Boolean).join(" · ");
  return line ? line.charAt(0).toUpperCase() + line.slice(1) : "";
}

export function sortRows(rows: CaseRow[], sort: ProblemSort): CaseRow[] {
  const out = [...rows];
  const opened = (r: CaseRow) => (r.opened_at ? Date.parse(r.opened_at) : 0);
  if (sort === "newest") out.sort((a, b) => opened(b) - opened(a));
  else if (sort === "impact") out.sort((a, b) =>
    (b.impact?.affected_pct ?? -1) - (a.impact?.affected_pct ?? -1)
    || (b.severity_score ?? -1) - (a.severity_score ?? -1) || a.decision_rank - b.decision_rank);
  else out.sort((a, b) => a.decision_rank - b.decision_rank);
  return out;
}

/** "3 problems need a decision · 2 new spikes to look at" */
export function headline(decide: number, spikes: number, total: number): string {
  const d = decide > 0 ? `${decide} ${plural(decide, "problem needs", "problems need")} a decision` : "";
  const s = spikes > 0 ? `${spikes} new ${plural(spikes, "spike")} to look at` : "";
  if (d && s) return `${d} · ${s}`;
  if (d) return `${d}.`;
  if (s) return `Nothing needs a decision · ${s}`;
  return total > 0 ? "Nothing needs a decision right now." : "No problems yet.";
}

export const CATEGORY_GROUPS: { id: SpikeCategory; label: string; empty: string }[] = [
  { id: "bug", label: "Bugs", empty: "Something broke" },
  { id: "ux_confusion", label: "Confusing for users", empty: "People can't find or understand something" },
  { id: "performance", label: "Slow or draining", empty: "Speed, freezing, heat, battery or memory" },
  { id: "feature_request", label: "Requests", empty: "Things people ask for" },
];
