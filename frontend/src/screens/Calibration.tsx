import { Calibration as Cal, api } from "../api";
import { useAsync } from "../hooks";
import { C, R, S, T, mono } from "../theme";
import { Centered, EmptyState, ErrorState, Label, ScreenHeader } from "../ui";

export function Calibration({ onGoCases }: { onGoCases: () => void }) {
  const { data, loading, error, reload } = useAsync(() => api.calibration(), []);
  if (loading && !data) return <Centered>Loading calibration…</Centered>;
  if (error || !data) {
    return (
      <div style={{ padding: 28 }}>
        <ErrorState title="Couldn't load calibration" onRetry={reload} />
      </div>
    );
  }

  // Nothing to plot until findings have been reviewed. Showing an empty chart
  // with axes reads as "we measured, and it's zero" — which is a lie.
  if (data.n_reviewed === 0) {
    return (
      <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
        <ScreenHeader title="Calibration" product={data.product}
                      subtitle="STATED CONFIDENCE VS YOUR VERDICTS" />
        <div style={{ flex: 1, overflow: "auto", padding: `${S[5]} ${S[6]}` }}>
          <EmptyState
            title={`No reviewed findings for ${data.product || "this product"} yet`}
            body="This screen checks EchoLens against itself: when it says it is 80% sure, is it right 80% of the time? It needs your verdicts to do that. Approve or challenge a few findings and the curve starts here."
            action="Review findings in Cases"
            onAction={onGoCases}
          />
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <ScreenHeader
        title="Calibration"
        product={data.product}
        subtitle="STATED CONFIDENCE VS YOUR VERDICTS"
        right={<span style={{ fontFamily: mono, fontSize: T.xs, color: C.muted }}>{data.n_reviewed} REVIEWED FINDINGS</span>}
      />
      <div style={{ flex: 1, overflow: "auto", padding: `${S[5]} ${S[6]}` }}>
        {data.headline && (
          <div style={{ fontSize: T.lg, fontWeight: 600, letterSpacing: "-.01em", color: C.text, maxWidth: 720, marginBottom: S[1] }}>
            {data.headline}
          </div>
        )}
        <p style={{ fontSize: T.base, color: C.muted, maxWidth: 720, lineHeight: "var(--el-lh-normal)", marginTop: 0 }}>
          Every reviewed finding compares the confidence EchoLens stated with whether you approved it. A point on the
          diagonal means the stated confidence matched reality.
        </p>

        {!data.sufficient && (
          <Notice color={C.accent}>
            The curve firms up at 20 reviewed findings — you have {data.n_reviewed}. It's shown now, but treat early
            points as noisy.
          </Notice>
        )}
        {data.overconfident && (
          <Notice color={C.bad}>
            Systematic overconfidence detected: stated confidence averages{" "}
            {fracPct(data.mean_stated_confidence)} but only {fracPct(data.overall_approval_rate)} of findings are approved
            (~{Math.round((data.overconfidence_gap ?? 0) * 100)} pts high). A corrective note is now injected into every
            new investigation's prompt.
          </Notice>
        )}

        <div style={{ display: "flex", gap: S[6], flexWrap: "wrap", marginTop: S[4], alignItems: "flex-start" }}>
          <CalibrationChart data={data} />
          <div style={{ flex: 1, minWidth: 280 }}>
            <Label style={{ marginBottom: S[2] }}>KNOWN WEAK SPOTS</Label>
            {data.weak_spots.spots.length === 0 ? (
              <div style={{ padding: `${S[5]} ${S[4]}`, border: `1px dashed ${C.border4}`, borderRadius: R.card, color: C.dim, fontSize: T.base }}>
                No challenges recorded for {data.product || "this product"} yet. When you challenge a finding, pick a
                reason — those roll up here and steer future investigations.
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: S[2] }}>
                {data.weak_spots.spots.map((w) => (
                  <div key={w.reason} style={{ padding: `${S[3]} ${S[4]}`, background: C.card, border: `1px solid ${C.border2}`, borderRadius: R.card }}>
                    <div style={{ display: "flex", alignItems: "center", gap: S[2] }}>
                      <span style={{ fontSize: T.base, fontWeight: 600, color: C.text2 }}>{w.label}</span>
                      <span style={{ fontFamily: mono, fontSize: T.micro, padding: `0 ${S[2]}`, borderRadius: R.card, background: `${C.bad}1f`, color: C.bad, marginLeft: "auto" }}>
                        {w.count}× challenged
                      </span>
                    </div>
                    <div style={{ fontSize: T.sm, color: C.muted, marginTop: S[1], lineHeight: "var(--el-lh-normal)" }}>{w.guidance}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function Notice({ children, color }: { children: React.ReactNode; color: string }) {
  return (
    <div style={{ maxWidth: 720, marginTop: S[3], padding: `${S[3]} ${S[4]}`, border: `1px solid ${color}55`, background: `${color}12`, borderRadius: R.control, fontSize: T.base, color: C.text3, lineHeight: "var(--el-lh-normal)" }}>
      {children}
    </div>
  );
}

/** Local: these values are 0..1 FRACTIONS, whereas format.ts `pct` takes an
 *  already-scaled percentage. Renamed so the two can never be confused — an
 *  accidental import of the shared one would render 0.85 as "1%". */
const fracPct = (x: number | null) => (x == null ? "—" : `${Math.round(x * 100)}%`);

function CalibrationChart({ data }: { data: Cal }) {
  const W = 340;
  const H = 300;
  const pad = 40;
  const plot = { x: pad, y: 14, w: W - pad - 12, h: H - pad - 14 };
  // data → pixel; confidence (x) and approval (y) both 0..1, y inverted
  const px = (v: number) => plot.x + v * plot.w;
  const py = (v: number) => plot.y + (1 - v) * plot.h;
  const pts = data.points.filter((p) => p.count > 0 && p.approval_rate != null);
  const maxCount = Math.max(1, ...pts.map((p) => p.count));

  return (
    <svg width={W} height={H} style={{ flex: "none", background: C.card, border: `1px solid ${C.border2}`, borderRadius: R.card }}>
      {/* gridlines */}
      {[0, 0.25, 0.5, 0.75, 1].map((g) => (
        <g key={g}>
          <line x1={px(g)} y1={py(0)} x2={px(g)} y2={py(1)} stroke={C.border} strokeWidth={1} />
          <line x1={px(0)} y1={py(g)} x2={px(1)} y2={py(g)} stroke={C.border} strokeWidth={1} />
          <text x={px(g)} y={H - 22} fill={C.faint} fontSize={9} fontFamily={mono} textAnchor="middle">
            {Math.round(g * 100)}
          </text>
          <text x={pad - 8} y={py(g) + 3} fill={C.faint} fontSize={9} fontFamily={mono} textAnchor="end">
            {Math.round(g * 100)}
          </text>
        </g>
      ))}
      {/* perfect-calibration diagonal */}
      <line x1={px(0)} y1={py(0)} x2={px(1)} y2={py(1)} stroke={C.border4} strokeWidth={1.5} strokeDasharray="4 4" />
      {/* the actual curve */}
      {pts.length > 1 && (
        <polyline
          points={pts.map((p) => `${px(p.midpoint)},${py(p.approval_rate as number)}`).join(" ")}
          fill="none"
          stroke={C.accent}
          strokeWidth={2}
        />
      )}
      {pts.map((p) => (
        <circle
          key={p.range}
          cx={px(p.midpoint)}
          cy={py(p.approval_rate as number)}
          r={4 + (p.count / maxCount) * 6}
          fill={`${C.accent}cc`}
          stroke={C.bg}
          strokeWidth={1}
        >
          <title>{`stated ${Math.round(p.midpoint * 100)}% → approved ${fracPct(p.approval_rate)} (${p.count})`}</title>
        </circle>
      ))}
      {/* axis captions */}
      <text x={px(0.5)} y={H - 6} fill={C.muted} fontSize={10} fontFamily={mono} textAnchor="middle">
        STATED CONFIDENCE
      </text>
      <text x={12} y={py(0.5)} fill={C.muted} fontSize={10} fontFamily={mono} textAnchor="middle" transform={`rotate(-90 12 ${py(0.5)})`}>
        APPROVAL RATE
      </text>
    </svg>
  );
}
