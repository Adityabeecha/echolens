import type { CaseRow, ConfirmedFix, FixWatchRow, LiveInvestigation } from "../../api";
import { stampFor } from "../../components/casefile/stampFor";

const ACTIVE = new Set(["resolved", "needs_review", "needs_human", "regressed"]);
const WATCHING = new Set(["issue_open", "waiting_for_release", "watching", "confirmed"]);

export function openProblems(rows: CaseRow[], watches: FixWatchRow[]): CaseRow[] {
  const inProgress = new Set(watches.filter(w => WATCHING.has(w.status)).map(w => w.investigation_id));
  return rows.filter(r => ACTIVE.has(r.status) && !r.decision?.hidden && !inProgress.has(r.id!))
    .sort((a, b) => a.decision_rank - b.decision_rank);
}

const numberWord = (n: number) => ["No", "One", "Two", "Three", "Four", "Five"][n] ?? String(n);
export function headline({ focus, count, drag, hasData = true, spikes = 0, stale = 0, readingFirst = false, product }: {
  focus?: CaseRow; count: number; drag?: number | null; hasData?: boolean; spikes?: number; stale?: number;
  readingFirst?: boolean; product?: string;
}): string {
  // Before the first read finishes, "Nothing needs you" is an all-clear nobody measured.
  if (readingFirst) return `Reading ${product ? `${product}'s` : "your"} first reviews…`;
  if (focus && stampFor(focus) === "confirmed" && drag != null && drag > 0) {
    return `One bug costs about ${drag.toFixed(2)} ${drag === 1 ? "star" : "stars"}.`;
  }
  if (count > 0) return `${numberWord(count)} ${count === 1 ? "problem is" : "problems are"} worth your time this week.`;
  // New spikes are news; a source that couldn't be read is housekeeping. On a
  // product's first day the headline led with the broken source and the three
  // spikes onboarding had just announced were nowhere on Today.
  if (spikes > 0) return `EchoLens found ${numberWord(spikes).toLowerCase()} ${spikes === 1 ? "spike" : "spikes"} worth a look.`;
  if (stale > 0) return `${numberWord(stale)} feedback ${stale === 1 ? "source needs" : "sources need"} attention.`;
  return hasData ? "Nothing needs you right now." : "Your first review is the starting point.";
}

/** Never display tool code as if it were an explanation for a developer. */
export function liveStep(step: LiveInvestigation["current_step"]): string {
  if (!step) return "Waiting for the next step…";
  const text = step.text.toLowerCase();
  if (step.kind === "TOOL") {
    if (text.includes("search_reviews")) return "Reading the reviews…";
    if (text.includes("release")) return "Checking release notes…";
    if (text.includes("github")) return "Checking GitHub…";
    return "Checking a source…";
  }
  return ({ THINK: "Testing a possible cause…", EVID: "Adding proof from a source…",
    UPDT: "Comparing the possible causes…", CHECK: "Checking that the proof holds up…",
    FAIL: "Checking a step that needs another look…", SPEC: "Taking a closer look…" } as Record<string, string>)[step.kind]
    ?? "Reviewing what the sources say…";
}

const rate = (n: number) => n === 0 ? "zero" : Number(n < 1 ? n.toPrecision(2) : n.toFixed(1)).toString();
export function fixTopic(metric: string): string {
  return plainWords(metric.replace(/\s+(?:share of|per week|complaints per|mentions).*$/i, "").trim() || "reported problem");
}
export function fixTitle(metric: string): string {
  return `Your ${fixTopic(metric)} fix worked.`;
}
export function fixSentence(fix: Partial<Pick<ConfirmedFix, "baseline_rate" | "post_rate" | "fixed_in_version">>): string {
  const before = fix.baseline_rate, after = fix.post_rate;
  if (before == null || after == null || !Number.isFinite(before) || !Number.isFinite(after) || after >= before) {
    return "The complaint watch confirmed this fix. Open the proof for the comparison.";
  }
  const version = fix.fixed_in_version?.replace(/^v/i, "");
  return `Complaints fell from ${rate(before)} a day to ${rate(after)} after ${version ? `version ${version}` : "the fix"}.`;
}

export function watchProgress(watch: Pick<FixWatchRow, "status" | "fix_date" | "release_seen_at" | "window_days">, now = new Date()): string {
  if (watch.status === "waiting_for_release") return "waiting for the fixed version to reach reviewers";
  if (watch.status === "issue_open") return "waiting for the fix to ship";
  const date = watch.release_seen_at ?? watch.fix_date;
  const start = date ? Date.parse(date) : NaN;
  const days = watch.window_days;
  if (!Number.isFinite(start) || !days) return "watching for the complaints to fall";
  const elapsed = Math.max(1, Math.floor((now.getTime() - start) / 86_400_000) + 1);
  return elapsed > days ? `${days}-day watch complete · checking the result` : `day ${elapsed} of ${days}`;
}

export function plainWords(text: string): string {
  return text.replace(/\bcases\b/gi, "problems").replace(/\bcase\b/gi, "problem")
    .replace(/\bfindings?\b/gi, "problem").replace(/\bhypotheses\b/gi, "possible causes")
    .replace(/\bhypothesis\b/gi, "possible cause").replace(/\ban anomaly\b/gi, "a spike").replace(/\banomal(?:y|ies)\b/gi, "spike")
    .replace(/\bworking lead\b/gi, "Hunch").replace(/\btriage\b/gi, "review").replace(/\bsignals?\b/gi, "spike");
}
