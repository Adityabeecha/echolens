// The status vocabulary — eight words, used everywhere, with no synonyms.
//
// The app used to say "Pending triage" on the feed, "Awaiting triage" in a
// section header, "Open" on Product Health and "Investigating" in the sidebar
// for states that either meant the same thing or differed in ways nobody could
// name. One list, one label per state, one colour per state.

import { C } from "./theme";

export type CaseStatus =
  | "queued"
  | "running"
  | "needs_review"
  | "needs_human"
  | "resolved"
  | "dismissed"
  | "verified_fixed"
  | "regressed";

export interface StatusMeta {
  label: string;
  color: string;
  bg: string;
  border: string;
  /** True for states where the machine is actively working. */
  pulse?: boolean;
  /** True for states that are waiting on the person reading the screen. */
  needsYou?: boolean;
}

const amber = (label: string, extra: Partial<StatusMeta> = {}): StatusMeta => ({
  label, color: C.accent, bg: "rgba(240,166,60,.1)", border: "rgba(240,166,60,.35)", ...extra,
});

export const STATUS: Record<CaseStatus, StatusMeta> = {
  queued: { label: "Queued", color: C.text3, bg: C.hover, border: C.border4 },
  running: amber("Running", { pulse: true }),
  needs_review: amber("Needs review", { needsYou: true }),
  needs_human: amber("Needs human", { needsYou: true }),
  resolved: {
    label: "Resolved", color: C.good, bg: "rgba(76,192,119,.1)", border: "rgba(76,192,119,.35)",
  },
  verified_fixed: {
    label: "Verified fixed", color: C.good,
    bg: "rgba(76,192,119,.1)", border: "rgba(76,192,119,.35)",
  },
  regressed: {
    label: "Regressed", color: C.bad, bg: "rgba(224,88,79,.1)", border: "rgba(224,88,79,.35)",
    needsYou: true,
  },
  dismissed: { label: "Dismissed", color: C.muted, bg: C.hover, border: C.border3 },
};

export function statusMeta(s: string): StatusMeta {
  return STATUS[s as CaseStatus] ?? { label: s, color: C.muted, bg: C.hover, border: C.border3 };
}

/** The one action a card offers, chosen by status. */
export function primaryActionFor(status: string): string {
  switch (status as CaseStatus) {
    case "needs_review": return "Review finding";
    case "needs_human": return "Decide";
    case "running": return "Watch live";
    case "queued": return "Cancel";
    case "regressed": return "See what came back";
    case "verified_fixed": return "See the proof";
    case "resolved": return "Open finding";
    default: return "Open case";
  }
}

/** Filter tabs, and which statuses each one holds. Every status has one home. */
export const CASE_TABS: { key: string; label: string; statuses: CaseStatus[] | null }[] = [
  { key: "all", label: "All", statuses: null },
  { key: "needs-review", label: "Needs review", statuses: ["needs_review", "needs_human", "regressed"] },
  { key: "running", label: "Running", statuses: ["running"] },
  { key: "queued", label: "Queued", statuses: ["queued"] },
  { key: "resolved", label: "Resolved", statuses: ["resolved", "verified_fixed"] },
  { key: "dismissed", label: "Dismissed", statuses: ["dismissed"] },
];

export const SEVERITY: Record<string, { label: string; color: string }> = {
  high: { label: "High", color: C.bad },
  medium: { label: "Medium", color: C.accent },
  low: { label: "Low", color: C.dim },
};
