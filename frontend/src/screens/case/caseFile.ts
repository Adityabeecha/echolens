import type { Citation, CitationMap, Evidence, GuardResult, Investigation } from "../../api";
import type { StampVariant } from "../../components/casefile/stampFor";
import { stampFor } from "../../components/casefile/stampFor";

// What the problem page decides from a case, kept out of the JSX so the story,
// the reasons and the exhibits can never disagree about which letter is which.

const EV_REF = /\[(ev_\d+)\]/g;
const LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";

/** Sources where the words are a user speaking. */
export const USER_VOICE = new Set(["play_store", "app_store", "chrome_web_store", "csv", "csv_reviews", "in_app",
  "support", "zendesk", "forum", "discord", "reddit", "hacker_news", "stack_overflow"]);
const DEV_SOURCES = new Set(["github", "github_issues", "github_prs", "github_commits", "github_activity",
  "github_discussions"]);

export interface Exhibit {
  letter: string;
  id: string;
  evidence: Evidence;
  citation: Citation | null;
  kind: string;
  date: string;
  /** ISO day, when known: drives "N days after the update". */
  iso: string | null;
  quote: string;
  highlight: string | null;
  url: string | null;
  cited: boolean;
}

export interface Sentence { text: string; letters: string[] }

/** "Play Store review ★1", "GitHub issue #2841", "Release note"… */
export function kindOf(e: Evidence, c: Citation | null): string {
  const s = e.source;
  if (s === "play_store") return `Play Store review${c?.rating ? ` ★${c.rating}` : ""}`;
  if (s === "app_store") return `App Store review${c?.rating ? ` ★${c.rating}` : ""}`;
  if (s === "release_notes") return "Release note";
  if (s === "github_commits" || /^commit /.test(e.ref)) return "Commit";
  if (DEV_SOURCES.has(s)) {
    const n = e.ref.match(/#(\d+)$/);
    return `GitHub issue${n ? ` #${n[1]}` : ""}`;
  }
  if (s === "reddit") return "Reddit post";
  if (s === "hacker_news") return "Hacker News comment";
  if (s === "stack_overflow") return "Stack Overflow question";
  if (s === "zendesk" || s === "support") return "Support ticket";
  return s.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

const shortDay = (iso: string) => {
  const d = new Date(`${iso}T00:00:00Z`);
  return Number.isNaN(d.getTime()) ? iso
    : d.toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" });
};

/** The prose split into sentences, each with the letters it cites. */
function splitProse(prose: string): string[] {
  return prose.split(/(?<=[.!?](?:\s*\[ev_\d+\])*)\s+(?=[A-Z0-9“"(])/).map((s) => s.trim()).filter(Boolean);
}

/**
 * Letters A, B, C… in order of first citation in the prose; exhibits the prose
 * never cites follow, so every piece of proof still has a letter.
 */
export function buildExhibits(inv: Investigation, map: CitationMap | null): { exhibits: Exhibit[]; sentences: Sentence[] } {
  const prose = inv.finding?.prose ?? "";
  const raw = map?.sentences?.length ? map.sentences : splitProse(prose);
  const byId = new Map(inv.evidence.map((e) => [e.id, e]));
  const order: string[] = [];
  for (const s of raw) for (const m of s.matchAll(EV_REF)) if (byId.has(m[1]) && !order.includes(m[1])) order.push(m[1]);
  const citedCount = order.length;
  for (const e of inv.evidence) if (!order.includes(e.id)) order.push(e.id);
  const cites = new Map((map?.citations ?? []).map((c) => [c.id, c]));
  const exhibits = order.map((id, i): Exhibit => {
    const e = byId.get(id)!;
    const c = cites.get(id) ?? null;
    return {
      letter: LETTERS[i] ?? String(i + 1), id, evidence: e, citation: c,
      kind: kindOf(e, c), iso: c?.date ?? null, date: c?.date ? shortDay(c.date) : "date not recorded",
      quote: e.snippet, highlight: c?.highlight ?? null, url: c?.url ?? refHref(e), cited: i < citedCount,
    };
  });
  const letterOf = new Map(exhibits.map((x) => [x.id, x.letter]));
  const sentences = raw.map((s) => ({
    text: s.replace(EV_REF, "").replace(/\s+([.,;:!?])/g, "$1").replace(/\s{2,}/g, " ").trim(),
    letters: [...new Set([...s.matchAll(EV_REF)].map((m) => letterOf.get(m[1])).filter((l): l is string => !!l))],
  })).filter((s) => s.text);
  return { exhibits, sentences };
}

/** A ref that is a real address gets a link; anything else stays text. */
function refHref(e: Evidence): string | null {
  if (/^https?:\/\//i.test(e.ref)) return e.ref;
  const gh = e.ref.match(/([\w.-]+\/[\w.-]+)#(\d+)$/);
  return gh ? `https://github.com/${gh[1]}/issues/${gh[2]}` : null;
}

export function verdictOf(inv: Investigation): StampVariant {
  const f = inv.finding;
  return stampFor({
    status: inv.case_status, support_level: f?.support_level ?? null, needs_review: f?.needs_review ?? null,
    trust: f?.trust ?? null, fix: f?.fix ? { status: f.fix.status } : null,
  });
}

/** A drafted cause the claim-grounding check refused: never a conclusion. */
export const isBlockedDraft = (inv: Investigation) => (inv.finding?.grounding_violations?.length ?? 0) > 0;

const guard = (inv: Investigation, key: GuardResult["key"]) => inv.guards?.find((g) => g.key === key) ?? null;
const tip = (g: GuardResult | null) => (g ? `${g.label}: ${g.detail}` : undefined);

const daysBetween = (a: string, b: string) =>
  Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86_400_000);

/** The proof behind the supported cause, as exhibits. */
function supporting(inv: Investigation, exhibits: Exhibit[]): Exhibit[] {
  const h = inv.hypotheses.find((x) => x.id === inv.finding?.supported_hypothesis);
  const ids = new Set(h?.evidence_for ?? []);
  const pool = ids.size ? exhibits.filter((x) => ids.has(x.id)) : exhibits.filter((x) => x.cited);
  return pool.filter((x) => !x.evidence.rejected);
}

/** "Started 2 days after the update": a release exhibit, then the first complaint after it. */
export function afterUpdate(inv: Investigation, exhibits: Exhibit[]): { days: number; release: Exhibit; first: Exhibit } | null {
  if (guard(inv, "temporal_order")?.status === "blocked") return null;
  const pool = supporting(inv, exhibits);
  const release = pool.find((x) => x.evidence.source === "release_notes" && x.iso);
  if (!release?.iso) return null;
  const complaints = pool.filter((x) => USER_VOICE.has(x.evidence.source) && x.iso && x.iso >= release.iso!)
    .sort((a, b) => a.iso!.localeCompare(b.iso!));
  const first = complaints[0];
  return first ? { days: daysBetween(release.iso, first.iso!), release, first } : null;
}

export interface Reason { id: string; text: string; letters: string[]; tip?: string }

/** One plain reason per honesty check that held, with the exhibits behind it. */
export function reasonsFor(inv: Investigation, exhibits: Exhibit[]): Reason[] {
  const out: Reason[] = [];
  const pool = supporting(inv, exhibits);
  const two = guard(inv, "two_source");
  const users = pool.filter((x) => USER_VOICE.has(x.evidence.source));
  const devs = pool.filter((x) => DEV_SOURCES.has(x.evidence.source) || /^commit /.test(x.evidence.ref));
  const notes = pool.filter((x) => x.evidence.source === "release_notes");
  if (inv.finding && !isBlockedDraft(inv)) {
    if (users.length) out.push({ id: "users", letters: users.map((x) => x.letter), tip: tip(two),
      text: users.length > 1 ? "Users describe the same thing, in their own words"
        : "A user describes it in their own words" });
    if (devs.length) out.push({ id: "devs", letters: devs.map((x) => x.letter), tip: tip(two),
      text: "Your developers already logged it on GitHub" });
    if (notes.length) out.push({ id: "notes", letters: notes.map((x) => x.letter), tip: tip(two),
      text: "The release notes name the change" });
  }
  const order = afterUpdate(inv, exhibits);
  if (order && guard(inv, "temporal_order")?.status === "pass") {
    out.push({ id: "order", letters: [order.release.letter, order.first.letter], tip: tip(guard(inv, "temporal_order")),
      text: order.days === 0 ? "The update came first — complaints began the same day"
        : `The update came first — complaints began ${order.days} ${order.days === 1 ? "day" : "days"} later` });
  }
  const byId = new Map(exhibits.map((x) => [x.id, x.letter]));
  for (const h of inv.hypotheses.filter((x) => x.status === "rejected").slice(0, 2)) {
    out.push({ id: `disprove-${h.id}`, tip: `Ruled out: ${h.statement}`,
      letters: h.evidence_against.map((id) => byId.get(id)).filter((l): l is string => !!l),
      text: `We tried another explanation and ruled it out: ${lower(h.statement)}` });
  }
  const cite = guard(inv, "citation");
  if (cite?.status === "pass" && exhibits.some((x) => x.cited)) {
    out.push({ id: "cited", letters: exhibits.filter((x) => x.cited).map((x) => x.letter), tip: tip(cite),
      text: "Every sentence above points to an exhibit" });
  }
  return out;
}

const lower = (s: string) => s ? s.charAt(0).toLowerCase() + s.slice(1).replace(/\.$/, "") : s;

/** What would turn this hunch into a confirmed problem, named exactly. */
export function missingFor(inv: Investigation, exhibits: Exhibit[], minItems = 2): string[] {
  const out: string[] = [];
  const f = inv.finding;
  if (isBlockedDraft(inv)) {
    out.push("Proof for every sentence of the cause — the draft named a cause it couldn't point to, so it isn't shown as a conclusion.");
  }
  const order = guard(inv, "temporal_order");
  if (order?.status === "blocked") {
    out.push("A cause that came before the first complaint — an update can't explain complaints that started before it shipped.");
  }
  if (f?.needs_review) out.push(`Replacement proof — a reviewer struck an exhibit (${f.needs_review.reason.replace(/\.$/, "")}).`);
  const pool = supporting(inv, exhibits.length ? exhibits : []);
  const kinds = new Set(pool.map((x) => (USER_VOICE.has(x.evidence.source) ? "user"
    : DEV_SOURCES.has(x.evidence.source) ? "dev" : x.evidence.source)));
  const two = guard(inv, "two_source");
  if (two?.status !== "pass" && !isBlockedDraft(inv)) {
    if (kinds.size <= 1) {
      out.push(kinds.has("dev")
        ? "A second kind of source: users describing the same thing in reviews."
        : "A second kind of source: a GitHub issue, release note or crash report.");
    }
    if (pool.length < minItems) {
      const n = minItems - pool.length;
      out.push(`${n} more ${n === 1 ? "piece" : "pieces"} of proof that agree${pool.length ? " with what's here" : ""}.`);
    }
  }
  if (f?.what_would_settle_it && inv.status !== "resolved") out.push(`What would settle it: ${f.what_would_settle_it}`);
  return [...new Set(out)];
}

/** Sentences kept apart because nothing proves them. */
export function notProven(inv: Investigation): string[] {
  const f = inv.finding;
  if (!f) return [];
  return [...(f.working_hypotheses ?? []), ...(isBlockedDraft(inv) && f.rejected_draft ? [f.rejected_draft.replace(EV_REF, "").trim()] : [])]
    .filter(Boolean);
}
