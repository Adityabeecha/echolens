import { Anomaly, api } from "../api";
import { useAsync } from "../hooks";
import { C, mono } from "../theme";
import { Centered, Chip, Label, PrimaryButton, Spark, sparkFor } from "../ui";

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
        <div style={{ fontSize: 17, fontWeight: 600 }}>Case Feed</div>
        <div style={{ flex: 1 }} />
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ display: "flex", gap: 3 }}>
            {Array.from({ length: limit }).map((_, i) => (
              <div
                key={i}
                style={{ width: 18, height: 6, borderRadius: 2, background: i < used ? C.accent : "#2a2d38" }}
              />
            ))}
          </div>
          <div style={{ fontFamily: mono, fontSize: 11.5, color: C.muted }}>
            {used}/{limit} investigations today · ${(summary.data?.spent_today ?? 0).toFixed(2)} spent
          </div>
        </div>
        <PrimaryButton onClick={onNewCase}>New case</PrimaryButton>
      </div>

      <div style={{ flex: 1, overflow: "auto", padding: "22px 28px" }}>
        <Label style={{ marginBottom: 12 }}>DETECTED ANOMALIES · LUMO · LAST 7 DAYS</Label>

        {anomalies.loading && <Centered>Loading anomalies…</Centered>}
        {anomalies.error && (
          <Centered>
            Backend unavailable — start it with <code style={{ margin: "0 6px", color: C.accent }}>echolens serve</code>{" "}
            then run <code style={{ marginLeft: 6, color: C.accent }}>scan</code>.
          </Centered>
        )}
        {anomalies.data && anomalies.data.anomalies.length === 0 && (
          <div
            style={{
              maxWidth: 880,
              padding: "46px 20px",
              border: `1px dashed ${C.border4}`,
              borderRadius: 12,
              textAlign: "center",
            }}
          >
            <div style={{ fontSize: 15, fontWeight: 600, color: C.text3 }}>All quiet</div>
            <div style={{ fontSize: 13, color: C.dim, marginTop: 6 }}>
              No anomalies detected. Run the detector: <code style={{ color: C.accent }}>echolens scan</code>.
            </div>
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
            return (
              <div
                key={a.slug}
                onClick={() => clickable && onOpenInvestigation(a.investigation_id!)}
                style={{
                  display: "grid",
                  gridTemplateColumns: "70px 1fr auto",
                  gap: 16,
                  alignItems: "center",
                  padding: "16px 18px",
                  background: C.card,
                  border: `1px solid ${C.border2}`,
                  borderRadius: 10,
                  cursor: clickable ? "pointer" : "default",
                  opacity: clickable ? 1 : 0.72,
                }}
              >
                <div>
                  <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <div style={{ width: 8, height: 8, borderRadius: 2, background: isManual ? C.info : sev.color, flex: "none" }} />
                    <div style={{ fontFamily: mono, fontSize: 11, color: isManual ? C.info : sev.color }}>
                      {isManual ? "MANUAL" : sev.label}
                    </div>
                  </div>
                  <div style={{ fontFamily: mono, fontSize: 10, color: C.faint, marginTop: 5 }}>
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
            );
          })}
        </div>
      </div>
    </div>
  );
}
