// Number formatting, in one place.
//
// The same quantity used to appear three ways: "$0.00" where the real figure
// was $0.0031, "45 min" beside "1m 20s", "9.0%" beside "9%". A number that is
// formatted differently on two screens reads as two different numbers.

/** Costs are fractions of a cent per call — show enough precision to be real. */
export function money(x: number | null | undefined): string {
  const v = Number(x ?? 0);
  if (!Number.isFinite(v)) return "—";
  if (v > 0 && v < 0.0001) return "<$0.0001";
  if (v > 0 && v < 1) return `$${v.toFixed(4)}`;
  return `$${v.toFixed(2)}`;
}

export function pct(x: number | null | undefined, digits = 0): string {
  if (x == null || !Number.isFinite(Number(x))) return "—";
  return `${Number(x).toFixed(digits)}%`;
}

/** "45s" · "1m 20s" · "2h 5m". Never a raw minute count. */
export function duration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(Number(seconds))) return "—";
  const s = Math.max(0, Math.round(Number(seconds)));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rest = s % 60;
  if (m < 60) return rest ? `${m}m ${rest}s` : `${m}m`;
  const h = Math.floor(m / 60);
  const mm = m % 60;
  return mm ? `${h}h ${mm}m` : `${h}h`;
}

/** How old something is, in the shortest honest form. */
export function age(days: number | null | undefined): string {
  if (days == null || !Number.isFinite(Number(days))) return "—";
  const d = Math.max(0, Math.round(Number(days)));
  if (d === 0) return "today";
  if (d === 1) return "1 day old";
  if (d < 30) return `${d} days old`;
  const months = Math.round(d / 30);
  return months === 1 ? "1 month old" : `${months} months old`;
}

/** "12 min ago" · "3 h ago" · "2 days ago", from an age in minutes. */
export function ago(minutes: number | null | undefined): string {
  if (minutes == null || !Number.isFinite(Number(minutes))) return "never";
  const m = Math.max(0, Math.round(Number(minutes)));
  if (m < 1) return "just now";
  if (m < 60) return `${m} min ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} h ago`;
  const d = Math.floor(h / 24);
  return d === 1 ? "1 day ago" : `${d} days ago`;
}

/** A date the reader can place, from an ISO string. */
export function when(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export function count(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(Number(n))) return "—";
  return Number(n).toLocaleString();
}

/** "~9% of recent negative reviews" — the impact line, worded the same everywhere. */
export function impactLine(impact?: { affected_pct: number; affected_volume: number } | null): string | null {
  if (!impact || !impact.affected_volume) return null;
  return `~${pct(impact.affected_pct)} of recent negative reviews`;
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return n === 1 ? one : many;
}

/** Human names for evidence/finding sources. Never show PLAY_STORE to a reader. */
const SOURCE_LABELS: Record<string, string> = {
  play_store: "Play Store",
  app_store: "App Store",
  release_notes: "Release notes",
  github: "GitHub",
  github_issues: "GitHub issues",
  github_prs: "GitHub PRs",
  reddit: "Reddit",
  zendesk: "Zendesk",
  discord: "Discord",
  csv: "CSV import",
  csv_reviews: "CSV import",
  in_app: "In-app feedback",
};

export function sourceLabel(raw: string | null | undefined): string {
  if (!raw) return "Unknown source";
  const key = String(raw).trim().toLowerCase().replace(/[\s-]+/g, "_");
  if (SOURCE_LABELS[key]) return SOURCE_LABELS[key];
  const words = key.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** "Based on ev_001, ev_001, ev_002" -> "Based on ev_001, ev_002". */
export function dedupeEvidenceIds(text: string | null | undefined): string {
  if (!text) return "";
  return text.replace(/ev_\d+(?:\s*,\s*ev_\d+)+/g, (run) =>
    Array.from(new Set(run.split(/\s*,\s*/))).join(", "));
}
