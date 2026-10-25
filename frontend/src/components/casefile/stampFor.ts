/** LIVE describes work in progress, not proof. */
export type StampVariant = "confirmed" | "hunch" | "request" | "fixWorked" | "reopened" | "live";

export interface StampInput {
  status?: string | null;
  case_status?: string | null;
  support_level?: string | null;
  intent?: string | null;
  primary_intent?: string | null;
  needs_review?: boolean | { reason: string; at: string; eid: string } | null;
  capped?: boolean;
  trust?: { two_source_ok?: boolean } | null;
  fix?: { status?: string | null } | null;
  finding?: StampInput | null;
}

/** A case row, investigation or finding. Missing proof earns a HUNCH. */
export function stampFor(input: StampInput): StampVariant {
  const finding = input.finding ?? input;
  const status = input.case_status ?? input.status;
  const fix = finding.fix?.status ?? input.fix?.status;
  if (status === "running" || status === "queued") return "live";
  if (status === "regressed" || ["regressed", "persists_reopened"].includes(fix ?? "")) return "reopened";
  if (status === "verified_fixed" || fix === "confirmed") return "fixWorked";
  if ([input.intent, input.primary_intent, status].includes("feature_request")) return "request";
  const trust = finding.trust ?? input.trust;
  if (input.needs_review || finding.needs_review || input.capped || finding.capped || trust?.two_source_ok === false ||
      ["needs_human", "insufficient_evidence", "budget_exhausted", "failed"].includes(status ?? "") ||
      ["single_channel", "single_source", "supported_single_channel", "capped", "unverified", "working_lead"].includes(finding.support_level ?? "")) return "hunch";
  if (finding.support_level === "supported" || trust?.two_source_ok) return "confirmed";
  return "hunch";
}
