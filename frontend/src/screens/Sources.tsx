import { api } from "../api";
import { useAsync } from "../hooks";
import { C, mono } from "../theme";
import { Centered, GhostButton, Label, ScreenHeader } from "../ui";

const STATUS_COLOR: Record<string, string> = {
  Healthy: C.good,
  "Rate-limited": C.accent,
  Disconnected: C.bad,
  "Syncing…": C.accent,
};

export function Sources() {
  const { data, loading, error } = useAsync(() => api.sources(), []);
  if (loading) return <Centered>Loading sources…</Centered>;
  if (error) return <Centered>Backend unavailable.</Centered>;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <ScreenHeader title="Sources" right={<GhostButton>+ Connect source</GhostButton>} />
      <div style={{ flex: 1, overflow: "auto", padding: "22px 28px" }}>
        <Label style={{ marginBottom: 12 }}>CONNECTED · MONITORED EVERY 6H</Label>
        <div style={{ display: "flex", flexDirection: "column", gap: 10, maxWidth: 880 }}>
          {data?.connected.map((s) => {
            const col = STATUS_COLOR[s.status] ?? C.muted;
            return (
              <div
                key={s.name}
                style={{ display: "grid", gridTemplateColumns: "minmax(180px,1.2fr) 120px minmax(140px,1fr) 120px", gap: 14, alignItems: "center", padding: "15px 18px", background: C.card, border: `1px solid ${C.border2}`, borderRadius: 10 }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 11, minWidth: 0 }}>
                  <div style={{ width: 30, height: 30, borderRadius: 7, background: C.hover, border: `1px solid ${C.border3}`, display: "flex", alignItems: "center", justifyContent: "center", fontFamily: mono, fontSize: 12, color: C.accent, flex: "none" }}>
                    {s.icon}
                  </div>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: 14, fontWeight: 600 }}>{s.name}</div>
                    <div style={{ fontFamily: mono, fontSize: 10, color: C.faint, marginTop: 2 }}>{s.detail}</div>
                  </div>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                  <div style={{ width: 7, height: 7, borderRadius: "50%", background: col, flex: "none", animation: s.status === "Rate-limited" ? "elPulse 1.6s infinite" : "none" }} />
                  <span style={{ fontSize: 12, color: col }}>{s.status}</span>
                </div>
                <div style={{ fontSize: 12, color: C.muted }}>{s.lastPull}</div>
                <div style={{ fontFamily: mono, fontSize: 11.5, color: C.text3, textAlign: "right" }}>{s.volume}</div>
              </div>
            );
          })}
        </div>
        <Label style={{ margin: "28px 0 12px" }}>AVAILABLE</Label>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", maxWidth: 880 }}>
          {data?.available.map((a) => (
            <div key={a} style={{ display: "flex", alignItems: "center", gap: 9, padding: "10px 16px", border: `1px dashed ${C.border4}`, borderRadius: 9, color: C.muted, fontSize: 13 }}>
              {a}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
