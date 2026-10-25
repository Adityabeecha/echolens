import { useId, useMemo, useState } from "react";
import { useElementWidth } from "../../hooks";

// Daily complaints with release pins — the "when did this start, and what
// shipped right before it" chart.
//
// Hand-rolled SVG (no chart library): bars or a line for the main series, an
// optional overlay line (e.g. one case's theme), and a vertical pin per
// release labelled "v3.2.0 shipped" or "hotfix v3.2.1". Responsive to its
// container, keyboard-explorable (Tab in, ←/→ to move, Home/End), and the
// tooltip text is mirrored into a polite live region for screen readers.

export interface TimelinePoint {
  /** ISO day, "2026-07-11". */
  date: string;
  value: number;
}
export interface TimelineRelease {
  version: string;
  date: string;
  kind: "release" | "hotfix";
}

const M = { top: 34, right: 10, bottom: 24, left: 34 };

function niceMax(v: number): number {
  if (v <= 4) return 4;
  const p = 10 ** Math.floor(Math.log10(v));
  const n = v / p;
  // Fine steps, so a peak of 26 tops out at 30, not 50 (half the plot empty).
  const step = [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10].find((s) => n <= s) ?? 10;
  return step * p;
}

const shortDate = (iso: string) => {
  const d = new Date(`${iso}T00:00:00Z`);
  return Number.isNaN(d.getTime()) ? iso
    : d.toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" });
};

const withV = (version: string) => (/^v/i.test(version) ? version : `v${version}`);

export function TimelineChart({
  points, releases = [], overlay, mode = "bars", height = 200,
  unit = "negative reviews", overlayLabel = "matching this case", ariaLabel, formatDate = shortDate, minimal = false,
}: {
  points: TimelinePoint[];
  releases?: TimelineRelease[];
  /** A second series drawn as a line on the same axis (e.g. a case's theme). */
  overlay?: TimelinePoint[] | null;
  mode?: "bars" | "line";
  height?: number;
  /** Plural noun for the value, used in the tooltip: "12 negative reviews". */
  unit?: string;
  overlayLabel?: string;
  /** What the chart shows, for assistive tech. */
  ariaLabel: string;
  formatDate?: (iso: string) => string;
  /** The approved compact bars and pencil note; detailed charts retain axes. */
  minimal?: boolean;
}) {
  const m = minimal ? { top: releases.length > 1 ? 34 : 24, right: 0, bottom: 0, left: 0 } : M;
  const [ref, width] = useElementWidth<HTMLDivElement>();
  const [active, setActive] = useState<number | null>(null);
  const liveId = useId();
  const n = points.length;
  const innerW = Math.max(0, width - m.left - m.right);
  const innerH = Math.max(0, height - m.top - m.bottom);
  const band = n > 0 ? innerW / n : 0;
  const index = useMemo(() => new Map(points.map((p, i) => [p.date, i])), [points]);
  const over = useMemo(() => new Map((overlay ?? []).map((p) => [p.date, p.value])), [overlay]);
  const max = niceMax(Math.max(1, ...points.map((p) => p.value), ...(overlay ?? []).map((p) => p.value)));
  const x = (i: number) => m.left + band * i + band / 2;
  const y = (v: number) => m.top + innerH - (v / max) * innerH;

  // Pins on days inside the range, labels staggered over two rows when close.
  const pins = useMemo(() => {
    let lastX = -Infinity;
    let row = 0;
    return releases
      .filter((r) => index.has(r.date))
      .map((r) => {
        const px = m.left + band * (index.get(r.date) as number) + band / 2;
        row = px - lastX < 96 ? 1 - row : 0;
        lastX = px;
        return { ...r, px, row, label: r.kind === "hotfix" ? `hotfix ${withV(r.version)}`
          : minimal ? `version ${r.version.replace(/^v/i, "")} ships →` : `${withV(r.version)} shipped` };
      });
  }, [releases, index, band, minimal]);

  const tickEvery = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(innerW / 72))));
  const peak = points.reduce((best, p) => (p.value > best.value ? p : best), points[0] ?? { date: "", value: 0 });
  const summary = n === 0 ? `${ariaLabel}: no data` :
    `${ariaLabel}: ${n} days from ${formatDate(points[0].date)} to ${formatDate(points[n - 1].date)}; ` +
    `peak ${peak.value} ${unit} on ${formatDate(peak.date)}` +
    (pins.length ? `; ${pins.map((p) => `${p.label} ${formatDate(p.date)}`).join(", ")}` : "");

  const cur = active != null ? points[active] : null;
  const curReleases = cur ? releases.filter((r) => r.date === cur.date) : [];
  const tipText = cur ? `${formatDate(cur.date)}: ${cur.value} ${unit}` +
    (over.has(cur.date) ? `, ${over.get(cur.date)} ${overlayLabel}` : "") +
    (curReleases.length ? ` · ${curReleases.map((r) => (r.kind === "hotfix" ? `hotfix ${withV(r.version)}` : `${withV(r.version)} shipped`)).join(", ")}` : "")
    : "";

  const pick = (clientX: number, rect: DOMRect) => {
    if (band <= 0) return;
    const i = Math.floor((clientX - rect.left - m.left) / band);
    setActive(i >= 0 && i < n ? i : null);
  };

  const linePath = (series: TimelinePoint[]) => series
    .filter((p) => index.has(p.date))
    .map((p, k) => `${k === 0 ? "M" : "L"}${x(index.get(p.date) as number).toFixed(1)} ${y(p.value).toFixed(1)}`)
    .join(" ");

  return (
    <div ref={ref} className="el-chart" style={{ height }}>
      {width > 0 && (
        <svg
          width={width} height={height} className="el-chart__svg"
          role="img" aria-label={summary} tabIndex={n > 0 ? 0 : -1}
          onPointerMove={(e) => pick(e.clientX, e.currentTarget.getBoundingClientRect())}
          onPointerLeave={() => setActive(null)}
          onBlur={() => setActive(null)}
          onKeyDown={(e) => {
            if (n === 0) return;
            const step: Record<string, number> = { ArrowRight: 1, ArrowLeft: -1 };
            if (e.key in step) {
              e.preventDefault();
              setActive((a) => Math.min(n - 1, Math.max(0, (a ?? (step[e.key] > 0 ? -1 : n)) + step[e.key])));
            } else if (e.key === "Home") { e.preventDefault(); setActive(0); }
            else if (e.key === "End") { e.preventDefault(); setActive(n - 1); }
            else if (e.key === "Escape") setActive(null);
          }}
        >
          {/* gridlines: 0, half, max */}
          {!minimal && [0, 0.5, 1].map((f) => (
            <g key={f}>
              <line className="el-chart__grid" x1={m.left} x2={width - m.right} y1={y(max * f)} y2={y(max * f)} />
              <text className="el-chart__tick" x={m.left - 6} y={y(max * f) + 3.5} textAnchor="end">
                {Math.round(max * f)}
              </text>
            </g>
          ))}
          {!minimal && points.map((p, i) => i % tickEvery === 0 && (
            <text key={p.date} className="el-chart__tick" x={x(i)} y={height - 6} textAnchor="middle">
              {formatDate(p.date)}
            </text>
          ))}

          {mode === "bars" ? points.map((p, i) => {
            const h = Math.max(p.value > 0 ? 1.5 : 0, (p.value / max) * innerH);
            const w = Math.max(1, Math.min(18, band * 0.68));
            return (
              <rect key={p.date} className={`el-chart__bar${releases.some((r) => r.date <= p.date) ? " is-after" : ""}${active === i ? " is-active" : ""}`}
                    x={x(i) - w / 2} y={m.top + innerH - h} width={w} height={h} rx={Math.min(2, w / 3)} />
            );
          }) : (
            <path className="el-chart__line" d={linePath(points)} />
          )}

          {overlay && overlay.length > 0 && <path className="el-chart__overlay" d={linePath(overlay)} />}

          {pins.map((p) => (
            <g key={`${p.version}-${p.date}`} className={`el-chart__pin el-chart__pin--${p.kind}`}>
              <line x1={p.px} x2={p.px} y1={m.top - 4 - p.row * 13} y2={m.top + innerH} />
              <circle cx={p.px} cy={m.top - 4 - p.row * 13} r={2.6} />
              <text x={minimal ? (p.px < 160 ? 0 : p.px - 5) : p.px + 5} y={m.top - 7 - p.row * 13}
                    textAnchor={minimal ? (p.px < 160 ? "start" : "end") : p.px > width - 110 ? "end" : "start"}
                    dx={!minimal && p.px > width - 110 ? -10 : 0}>{p.label}</text>
            </g>
          ))}

          {cur && active != null && (
            <line className="el-chart__cursor" x1={x(active)} x2={x(active)} y1={m.top} y2={m.top + innerH} />
          )}
        </svg>
      )}
      {cur && active != null && width > 0 && (
        <div className="el-chart__tip" aria-hidden
             // Below the release-pin labels, never on top of them.
             style={{ left: Math.max(0, Math.min(Math.max(8, x(active) - 90), width - 188)), top: m.top + 6 }}>
          <div className="el-chart__tip-date">{formatDate(cur.date)}</div>
          <div><b className="el-num">{cur.value}</b> {unit}</div>
          {over.has(cur.date) && (
            <div className="el-chart__tip-overlay"><b className="el-num">{over.get(cur.date)}</b> {overlayLabel}</div>
          )}
          {curReleases.map((r) => (
            <div key={r.version} className="el-chart__tip-release">
              {r.kind === "hotfix" ? `hotfix ${withV(r.version)}` : `${withV(r.version)} shipped`}
            </div>
          ))}
        </div>
      )}
      <span id={liveId} className="el-sr-only" aria-live="polite">{tipText}</span>
      {n === 0 && <span className="el-chart__empty">No reviews in this period. Connect a source or choose a longer period.</span>}
    </div>
  );
}
