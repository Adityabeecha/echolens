import { Stamp, StampInput, stampFor } from "./casefile";

/** Compatibility names for screens awaiting their own approved redesign. */
export type StatusKind = "smoking_gun" | "working_lead" | "fix_watch" | "verified_fix" | "regressed" | "resolved" | "request" | "live";
export function statusKindFor(caseStatus?: string | null, supportLevel?: string | null,
                              fixStatus?: string | null): StatusKind | null {
  const verdict = stampFor({ status: caseStatus, support_level: supportLevel, fix: { status: fixStatus } });
  return ({ confirmed: "smoking_gun", hunch: "working_lead", request: "request",
    fixWorked: "verified_fix", reopened: "regressed", live: "live" } as const)[verdict];
}
const INPUT: Record<StatusKind, StampInput> = {
  smoking_gun: { support_level: "supported" }, working_lead: { support_level: "single_channel" },
  fix_watch: { status: "watching" }, verified_fix: { fix: { status: "confirmed" } },
  regressed: { status: "regressed" }, resolved: { status: "resolved" },
  request: { intent: "feature_request" }, live: { status: "running" },
};
export function StatusBadge({ kind, compact = false }: { kind: StatusKind; compact?: boolean }) {
  return <Stamp variant={stampFor(INPUT[kind])} compact={compact} rotation={-3} />;
}
