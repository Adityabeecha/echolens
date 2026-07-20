import { api } from "../api";
import { useAsync } from "../hooks";
import { C, mono } from "../theme";
import { Centered, Label, ScreenHeader } from "../ui";

// The validated pattern library: (trigger → cause → fix) proven by confirmed
// fixes. Earned, not asserted — each pattern is backed by fixes that worked.
export function Patterns() {
  const { data, loading, error } = useAsync(() => api.patterns(), []);
  if (loading) return <Centered>Loading patterns…</Centered>;
  if (error || !data) return <Centered>Backend unavailable.</Centered>;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <ScreenHeader title={`Pattern Library${data.product ? ` · ${data.product}` : ""}`} right={<span style={{ fontFamily: mono, fontSize: 11.5, color: C.muted }}>{data.patterns.length} VERIFIED</span>} />
      <div style={{ flex: 1, overflow: "auto", padding: "22px 28px" }}>
        <p style={{ fontSize: 13.5, color: C.muted, maxWidth: 720, lineHeight: 1.6, marginTop: 0 }}>
          Every pattern below is built from a fix that was <span style={{ color: C.good }}>verified to work</span>. The
          investigator uses a matching pattern as a proven starting prior, so a recurring problem shortcuts straight to
          the hypothesis that already worked.
        </p>

        {data.patterns.length === 0 ? (
          <div style={{ maxWidth: 720, marginTop: 12, padding: "28px 20px", border: `1px dashed ${C.border4}`, borderRadius: 12, textAlign: "center", color: C.dim, fontSize: 13.5 }}>
            No verified patterns for {data.product || "this product"} yet. A pattern is earned when a fix ships and
            EchoLens confirms the complaint went away — check back after your first confirmed fixes.
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 12, maxWidth: 820 }}>
            {data.patterns.map((p, i) => (
              <div key={i} style={{ padding: "16px 18px", background: C.card, border: `1px solid ${C.border2}`, borderRadius: 12 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
                  {p.terms.map((t) => (
                    <span key={t} style={{ fontFamily: mono, fontSize: 11, padding: "3px 9px", borderRadius: 20, background: C.hover, border: `1px solid ${C.border3}`, color: C.text3 }}>
                      {t}
                    </span>
                  ))}
                  <span style={{ fontFamily: mono, fontSize: 10.5, padding: "3px 9px", borderRadius: 20, background: `${C.good}1f`, border: `1px solid ${C.good}66`, color: C.good, marginLeft: "auto" }}>
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
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {steps.map(([k, v, color], i) => (
        <div key={k} style={{ display: "grid", gridTemplateColumns: "120px 1fr", gap: 12, alignItems: "baseline" }}>
          <div style={{ fontFamily: mono, fontSize: 10, letterSpacing: ".08em", color }}>
            {i > 0 ? "↓ " : ""}
            {k}
          </div>
          <div style={{ fontSize: 13.5, color: C.text2, lineHeight: 1.45 }}>{v || "—"}</div>
        </div>
      ))}
    </div>
  );
}
