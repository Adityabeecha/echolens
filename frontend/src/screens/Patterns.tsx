import { api } from "../api";
import { useAsync } from "../hooks";
import { C, MEASURE, R, S, T, mono } from "../theme";
import { Centered, EmptyState, ErrorState, Label, ScreenHeader } from "../ui";

interface Props {
  onGoMemory: () => void;
  onGoCases: () => void;
}

// The validated pattern library: (trigger → cause → fix) proven by confirmed
// fixes. Earned, not asserted — each pattern is backed by fixes that worked.
export function Patterns({ onGoMemory, onGoCases }: Props) {
  const { data, loading, error, reload } = useAsync(() => api.patterns(), []);
  if (loading && !data) return <Centered>Loading patterns…</Centered>;
  if (error || !data) {
    return (
      <div style={{ padding: 28 }}>
        <ErrorState title="Couldn't load the pattern library" onRetry={reload} />
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <ScreenHeader
        title="Patterns"
        product={data.product}
        subtitle="FIXES THAT WERE PROVEN TO WORK"
        right={
          <span onClick={onGoMemory} className="el-btn" role="button" tabIndex={0}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onGoMemory(); }}
            style={{ fontSize: T.sm, color: C.dim, cursor: "pointer" }}>
            What else this product has taught EchoLens →
          </span>
        }
      />
      <div style={{ flex: 1, overflow: "auto", padding: `${S[5]} ${S[6]}` }}>
        <p style={{ fontSize: T.base, color: C.muted, maxWidth: 720, lineHeight: "var(--el-lh-normal)", marginTop: 0 }}>
          Every pattern below is built from a fix that was <span style={{ color: C.good }}>verified to work</span>. The
          investigator uses a matching pattern as a proven starting prior, so a recurring problem shortcuts straight to
          the hypothesis that already worked.
        </p>

        {data.patterns.length === 0 ? (
          <EmptyState
            title={`No proven patterns for ${data.product || "this product"} yet`}
            body="A pattern is earned, not assumed: it appears once a fix ships and EchoLens confirms the complaints actually stopped. Resolve a case and file the fix, and the first one lands here."
            action="Go to Cases"
            onAction={onGoCases}
          />
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: S[3], maxWidth: MEASURE }}>
            {data.patterns.map((p, i) => (
              <div key={i} style={{ padding: `${S[4]} ${S[4]}`, background: C.card, border: `1px solid ${C.border2}`, borderRadius: R.card }}>
                <div style={{ display: "flex", alignItems: "center", gap: S[2], marginBottom: S[3], flexWrap: "wrap" }}>
                  {p.terms.map((t) => (
                    <span key={t} style={{ fontFamily: mono, fontSize: T.xs, padding: `${S[1]} ${S[2]}`, borderRadius: R.pill, background: C.hover, border: `1px solid ${C.border3}`, color: C.text3 }}>
                      {t}
                    </span>
                  ))}
                  {p.cross_product && p.from_product && (
                    <span style={{ fontFamily: mono, fontSize: T.micro, padding: `${S[1]} ${S[2]}`, borderRadius: R.pill, background: `${C.info}1f`, border: `1px solid ${C.info}66`, color: C.info }}>
                      proven on {p.from_product}
                    </span>
                  )}
                  <span style={{ fontFamily: mono, fontSize: T.micro, padding: `${S[1]} ${S[2]}`, borderRadius: R.pill, background: `${C.good}1f`, border: `1px solid ${C.good}66`, color: C.good, marginLeft: "auto" }}>
                    verified {p.verified_count}×
                  </span>
                </div>
                <Flow trigger={p.trigger} cause={p.cause} fix={p.fix} />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function Flow({ trigger, cause, fix }: { trigger: string; cause: string; fix: string }) {
  const steps: [string, string, string][] = [
    ["TRIGGER", trigger.replace(/_/g, " "), C.info],
    ["CAUSE", cause, C.accent],
    ["FIX THAT WORKED", fix, C.good],
  ];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: S[2] }}>
      {steps.map(([k, v, color], i) => (
        <div key={k} style={{ display: "grid", gridTemplateColumns: "120px 1fr", gap: S[3], alignItems: "baseline" }}>
          <div style={{ fontFamily: mono, fontSize: T.micro, letterSpacing: ".08em", color }}>
            {i > 0 ? "↓ " : ""}
            {k}
          </div>
          <div style={{ fontSize: T.base, color: C.text2, lineHeight: "var(--el-lh-snug)" }}>{v || "—"}</div>
        </div>
      ))}
    </div>
  );
}
