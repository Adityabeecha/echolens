import { Anomaly, api } from "../api";
import { useAsync } from "../hooks";
import { C, mono } from "../theme";
import { Chip, Label, Spark, sparkFor } from "../ui";

interface Props {
  onOpenInvestigation: (id: number) => void;
  onNewCase: () => void;
  reloadKey: number;
}

function severity(z: number) {
  if (Math.abs(z) >= 3) return { label: "SEV1", color: C.bad };
  if (Math.abs(z) >= 2) return { label: "SEV2", color: C.accent };
  return { label: "SEV3", color: C.dim };
}

function chipFor(a: Anomaly): { label: string; color: string; bg: string; border: string; pulse?: boolean } {
  const t = a.triage?.decision;
  if (a.status === "investigating" || (t === "investigate" && a.investigation_id))
    return { label: "Investigating", color: C.accent, bg: "rgba(240,166,60,.1)", border: "rgba(240,166,60,.35)", pulse: true };
  if (t === "merge")
    return { label: "Merged", color: C.info, bg: "rgba(143,208,255,.08)", border: "rgba(143,208,255,.3)" };
  if (t === "ignore")
    return { label: "Ignored — noise", color: C.muted, bg: C.hover, border: C.border3 };
  if (a.status === "closed")
    return { label: "Resolved ✓", color: C.good, bg: "rgba(76,192,119,.1)", border: "rgba(76,192,119,.35)" };
  return { label: "Pending triage", color: C.text3, bg: C.hover, border: C.border4 };
}

export function CaseFeed({ onOpenInvestigation, onNewCase, reloadKey }: Props) {
  const anomalies = useAsync(() => api.anomalies(), [reloadKey]);
  const summary = useAsync(() => api.feedSummary(), [reloadKey]);

  const used = summary.data?.investigations_today ?? 0;
  const limit = summary.data?.daily_limit ?? 5;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 20,
          padding: "16px 28px",
          borderBottom: `1px solid ${C.border}`,
          flex: "none",
        }}
      >
        <div>
          <div style={{ fontSize: 17, fontWeight: 600, letterSpacing: "-0.01em" }}>Case Feed</div>
          <div style={{ fontFamily: mono, fontSize: 10.5, color: C.faint, letterSpacing: ".04em", marginTop: 2 }}>
            SIGNALS WORTH A LOOK · LAST 7 DAYS
          </div>
        </div>
        <div style={{ flex: 1 }} />
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 5 }}>
          <div style={{ display: "flex", gap: 3 }}>
            {Array.from({ length: limit }).map((_, i) => (
              <div
                key={i}
                style={{ width: 20, height: 5, borderRadius: 2, background: i < used ? C.accent : C.track }}
              />
            ))}
          </div>
          <div style={{ fontFamily: mono, fontSize: 11, color: C.muted, fontVariantNumeric: "tabular-nums" }}>
            {used}/{limit} today · ${(summary.data?.spent_today ?? 0).toFixed(2)} spent
          </div>
        </div>
        <button onClick={onNewCase} className="el-btn" style={{ background: C.accent, color: C.onAccent, border: "none", borderRadius: 7, padding: "9px 16px", fontWeight: 600, fontSize: 13, cursor: "pointer" }}>
          + New case
        </button>
      </div>

      <div style={{ flex: 1, overflow: "auto", padding: "22px 28px" }}>
        <Label style={{ marginBottom: 12 }}>
          {anomalies.data ? `${anomalies.data.anomalies.length} SIGNALS` : "SIGNALS"} · SEVERITY FIRST
        </Label>

        {anomalies.loading && (
          <div style={{ display: "flex", flexDirection: "column", gap: 10, maxWidth: 880 }}>
            {[0, 1, 2].map((i) => (
              <div key={i} style={{ height: 74, borderRadius: 10, background: C.card, border: `1px solid ${C.border2}`, animation: "elSkeleton 1.4s infinite", animationDelay: `${i * 0.15}s` }} />
            ))}
          </div>
        )}
        {anomalies.error && (
          <div style={{ maxWidth: 880, padding: "30px 22px", border: `1px solid ${C.border3}`, borderRadius: 12, background: C.card }}>
            <div style={{ fontSize: 14.5, fontWeight: 600, color: C.text3 }}>Can't reach the investigator</div>
            <div style={{ fontSize: 13, color: C.dim, marginTop: 6, lineHeight: 1.5 }}>
              The backend may be waking up (free tier sleeps after a while). Give it ~30 seconds, then retry.
            </div>
            <button onClick={anomalies.reload} className="el-btn" style={{ marginTop: 14, background: "transparent", color: C.accent, border: `1px solid rgba(240,166,60,.4)`, borderRadius: 7, padding: "8px 16px", fontSize: 13, fontWeight: 500, cursor: "pointer" }}>
              Retry
            </button>
          </div>
        )}
        {anomalies.data && anomalies.data.anomalies.length === 0 && (
          <div style={{ maxWidth: 880, padding: "48px 24px", border: `1px dashed ${C.border4}`, borderRadius: 12, textAlign: "center" }}>
            <div style={{ fontSize: 15.5, fontWeight: 600, color: C.text3 }}>Nothing needs investigating</div>
            <div style={{ fontSize: 13, color: C.dim, marginTop: 6, lineHeight: 1.55, maxWidth: 420, margin: "6px auto 0" }}>
              No anomalies in the last 7 days. Open a case yourself, or connect a source and run a scan.
            </div>
            <button onClick={onNewCase} className="el-btn" style={{ marginTop: 18, background: "transparent", color: C.accent, border: `1px solid rgba(240,166,60,.4)`, borderRadius: 7, padding: "9px 18px", fontSize: 13, fontWeight: 500, cursor: "pointer" }}>
              + Open a case
            </button>
          </div>
        )}

        <div style={{ display: "flex", flexDirection: "column", gap: 10, maxWidth: 880 }}>
          {anomalies.data?.anomalies.map((a) => {
            const sev = severity(a.z);
            const chip = chipFor(a);
            const clickable = a.investigation_id != null;
            const isManual = a.type === "manual";
            // Manual cases carry their real name in `description`; detected
            // anomalies describe themselves via `metric`.
            const title = isManual ? a.description : a.metric;
            const stripe = isManual ? C.info : sev.color;
            return (
              <div
                key={a.slug}
                onClick={() => clickable && onOpenInvestigation(a.investigation_id!)}
                className={clickable ? "el-card el-card--click" : "el-card"}
                style={{
                  display: "flex",
                  alignItems: "stretch",
                  overflow: "hidden",
                  opacity: clickable ? 1 : 0.68,
                }}
              >
                {/* signature: severity stripe — encodes state in form, reads like a case tag */}
                <div style={{ width: 3, flex: "none", background: stripe }} />
                <div style={{ display: "grid", gridTemplateColumns: "66px 1fr auto", gap: 16, alignItems: "center", padding: "16px 18px", flex: 1, minWidth: 0 }}>
                <div>
                  <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <div style={{ width: 7, height: 7, borderRadius: "50%", background: stripe, flex: "none", animation: a.status === "investigating" ? "elPulse 1.4s infinite" : "none" }} />
                    <div style={{ fontFamily: mono, fontSize: 10.5, letterSpacing: ".03em", color: stripe }}>
                      {isManual ? "MANUAL" : sev.label}
                    </div>
                  </div>
                  <div style={{ fontFamily: mono, fontSize: 10, color: C.faint, marginTop: 5, fontVariantNumeric: "tabular-nums" }}>
                    {isManual ? "you opened" : `z=${a.z}`}
                  </div>
                </div>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 14.5, fontWeight: 600, color: C.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {title}
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 7, flexWrap: "wrap" }}>
                    <span
                      style={{
                        fontFamily: mono,
                        fontSize: 10,
                        padding: "2px 7px",
                        border: `1px solid ${C.border3}`,
                        borderRadius: 4,
                        color: C.muted,
                        textTransform: "uppercase",
                      }}
                    >
                      {isManual ? "manual case" : a.type.replace(/_/g, " ")}
                    </span>
                    {!isManual && <Spark points={sparkFor(a.z)} color={sev.color} />}
                    {a.triage?.reason && (
                      <span style={{ fontSize: 12, color: C.dim, fontStyle: "italic" }}>{a.triage.reason}</span>
                    )}
                  </div>
                </div>
                <Chip {...chip} />
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
