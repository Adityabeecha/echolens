// The case verdict, said the same way everywhere.
//
// Six states, each a colour + a glyph + words, so state never rests on colour
// alone. Colour follows the fixed semantics in DESIGN_SYSTEM.md: amber is a
// calm single-source lead, emerald a verified fix, coral ONLY a confirmed
// regression; everything else is neutral or the indigo accent.

export type StatusKind =
  | "smoking_gun"
  | "working_lead"
  | "fix_watch"
  | "verified_fix"
  | "regressed"
  | "resolved";

const META: Record<StatusKind, { label: string; short: string; hint: string }> = {
  smoking_gun: {
    label: "Smoking gun", short: "Smoking gun",
    hint: "The cause is confirmed by two or more independent sources.",
  },
  working_lead: {
    label: "Working lead — awaiting 2nd source", short: "Working lead",
    hint: "One source points here. Confidence stays capped until a second, independent source agrees.",
  },
  fix_watch: {
    label: "Fix watch", short: "Fix watch",
    hint: "A fix shipped. EchoLens is watching whether the complaints actually stop.",
  },
  verified_fix: {
    label: "Verified fix", short: "Verified fix",
    hint: "Complaints dropped after the fix shipped — measured, not assumed.",
  },
  regressed: {
    label: "Regressed", short: "Regressed",
    hint: "The problem came back after it was fixed, confirmed across sources.",
  },
  resolved: {
    label: "Resolved", short: "Resolved",
    hint: "Closed. Nothing more to do here.",
  },
};

/**
 * Which badge a case earns, from fields the API already returns: the case
 * status, the finding's `support_level`, and the fix-watch status. Null when
 * none of the six applies (still running, queued, dismissed…).
 */
export function statusKindFor(caseStatus?: string | null, supportLevel?: string | null,
                              fixStatus?: string | null): StatusKind | null {
  if (caseStatus === "regressed" || fixStatus === "regressed") return "regressed";
  if (caseStatus === "verified_fixed" || fixStatus === "confirmed") return "verified_fix";
  if (fixStatus === "watching" || fixStatus === "waiting_for_release" || fixStatus === "issue_open") {
    return "fix_watch";
  }
  if (supportLevel === "single_channel") return "working_lead";
  if (supportLevel === "supported") return "smoking_gun";
  if (caseStatus === "resolved") return "resolved";
  return null;
}

export function StatusBadge({ kind, compact = false }: {
  kind: StatusKind;
  /** The short label ("Working lead") for tight rows; the full one is the tooltip. */
  compact?: boolean;
}) {
  const m = META[kind];
  return (
    <span className={`el-status el-status--${kind}`} title={compact ? `${m.label}. ${m.hint}` : m.hint}>
      <StatusGlyph kind={kind} />
      <span>{compact ? m.short : m.label}</span>
    </span>
  );
}

/** A 12px shape per state: target, half-ring, eye, check, return arrow, dot. */
function StatusGlyph({ kind }: { kind: StatusKind }) {
  const common = { width: 12, height: 12, viewBox: "0 0 12 12", fill: "none", "aria-hidden": true as const };
  switch (kind) {
    case "smoking_gun":
      return <svg {...common}><circle cx="6" cy="6" r="4.5" stroke="currentColor" strokeWidth="1.4" /><circle cx="6" cy="6" r="1.8" fill="currentColor" /></svg>;
    case "working_lead":
      return <svg {...common}><circle cx="6" cy="6" r="4.5" stroke="currentColor" strokeWidth="1.4" strokeDasharray="2.2 2" /><circle cx="6" cy="6" r="1.5" fill="currentColor" /></svg>;
    case "fix_watch":
      return <svg {...common}><path d="M1.2 6S3 2.6 6 2.6 10.8 6 10.8 6 9 9.4 6 9.4 1.2 6 1.2 6Z" stroke="currentColor" strokeWidth="1.3" /><circle cx="6" cy="6" r="1.4" fill="currentColor" /></svg>;
    case "verified_fix":
      return <svg {...common}><path d="m2.2 6.3 2.4 2.4 5.2-5.4" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" /></svg>;
    case "regressed":
      return <svg {...common}><path d="M9.6 4.2A4 4 0 1 0 10 7.6M9.8 1.8v2.6H7.2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>;
    default:
      return <svg {...common}><circle cx="6" cy="6" r="2.4" fill="currentColor" /></svg>;
  }
}
