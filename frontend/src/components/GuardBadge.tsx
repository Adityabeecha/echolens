// One honesty check's result on a case (GuardResult from api.ts).
//
// In the UI a guard is an "honesty check"; the technical name lives in the
// tooltip. Only `capped` takes colour (amber — it is literally a single-source
// lead held down); pass, stripped and blocked are neutral and told apart by
// shape and words, because none of them is a regression or a verified fix.

export type GuardBadgeStatus = "pass" | "capped" | "stripped" | "blocked" | "not_applicable";

const WORD: Record<GuardBadgeStatus, string> = {
  pass: "Passed",
  capped: "Capped",
  stripped: "Trimmed",
  blocked: "Blocked",
  not_applicable: "Not needed",
};

export function GuardBadge({ status, label, detail }: {
  status: GuardBadgeStatus;
  /** The check's name, e.g. "Two-source rule". Omit for a bare status pill. */
  label?: string;
  /** What happened, from the payload's `detail`; shown as the tooltip. */
  detail?: string;
}) {
  const word = WORD[status] ?? status;
  return (
    <span className={`el-guard el-guard--${status}`} title={detail || undefined}>
      <GuardGlyph status={status} />
      {label && <span className="el-guard__label">{label}</span>}
      <span className="el-guard__status">{word}</span>
    </span>
  );
}

function GuardGlyph({ status }: { status: GuardBadgeStatus }) {
  const common = { width: 12, height: 12, viewBox: "0 0 12 12", fill: "none", "aria-hidden": true as const,
                   stroke: "currentColor", strokeWidth: 1.5, strokeLinecap: "round" as const };
  switch (status) {
    case "pass":
      return <svg {...common}><path d="m2.4 6.2 2.3 2.3 4.9-5" strokeLinejoin="round" /></svg>;
    case "capped":
      return <svg {...common}><path d="M2 3.2h8M3.5 9.5V6.2M6 9.5V4.8M8.5 9.5V6.6" /></svg>;
    case "stripped":
      return <svg {...common}><path d="M2 4h8M2 6.5h4.5M2 9h8" /><path d="M7.6 5.4 10 7.8" /></svg>;
    case "blocked":
      return <svg {...common}><circle cx="6" cy="6" r="4.3" /><path d="m3 9 6-6" /></svg>;
    default:
      return <svg {...common}><path d="M3 6h6" /></svg>;
  }
}
