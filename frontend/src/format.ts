// Number formatting, in one place.
//
// The same quantity used to appear three ways: "$0.00" where the real figure
// was $0.0031, "45 min" beside "1m 20s", "9.0%" beside "9%". A number that is
// formatted differently on two screens reads as two different numbers.

/** Costs are fractions of a cent per call — show enough precision to be real. */
export function money(x: number | null | undefined): string {
  const v = Number(x ?? 0);
  if (!Number.isFinite(v)) return "—";
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

/** "~9% of negative reviews" — the impact line, worded the same everywhere. */
export function impactLine(impact?: { affected_pct: number; affected_volume: number } | null): string | null {
  if (!impact || !impact.affected_volume) return null;
  return `~${pct(impact.affected_pct)} of negative reviews`;
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return n === 1 ? one : many;
}
