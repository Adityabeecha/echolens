import { api } from "../api";
import { useAsync } from "../hooks";
import { C, mono } from "../theme";
import { Centered, Label, ScreenHeader } from "../ui";

// The PM's monthly review, auto-written: outcomes, not alerts.
export function Overview({ onOpenInvestigation }: { onOpenInvestigation: (id: number) => void }) {
  const { data, loading, error } = useAsync(() => api.overview(), []);
  if (loading) return <Centered>Loading product health…</Centered>;
  if (error || !data) return <Centered>Backend unavailable.</Centered>;

  const tiles = [
    { label: "OPEN PROBLEMS", value: String(data.open_problem_count), color: C.accent, sub: "resolved, not yet fixed" },
    { label: "IN VERIFICATION", value: String(data.in_verification), color: C.info, sub: "fixes being watched" },
    { label: "CONFIRMED THIS QUARTER", value: String(data.confirmed_fixes_quarter), color: C.good, sub: `${data.confirmed_fixes_total} all-time` },
    {
      label: "MEAN TIME TO FIX",
      value: data.mean_days_to_confirmed_fix == null ? "—" : `${data.mean_days_to_confirmed_fix}d`,
      color: C.text,
      sub: "anomaly → confirmed",
    },
    { label: "REGRESSIONS", value: String(data.regressions), color: data.regressions ? C.bad : C.muted, sub: "fixes that came back" },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <ScreenHeader title="Product Health" right={<span style={{ fontFamily: mono, fontSize: 11.5, color: C.muted }}>OUTCOMES, NOT ALERTS</span>} />
      <div style={{ flex: 1, overflow: "auto", padding: "22px 28px" }}>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", maxWidth: 980 }}>
          {tiles.map((t) => (
            <div key={t.label} style={{ flex: 1, minWidth: 160, padding: "16px 18px", background: C.card, border: `1px solid ${C.border2}`, borderRadius: 11 }}>
              <div style={{ fontFamily: mono, fontSize: 9.5, letterSpacing: ".1em", color: C.faint }}>{t.label}</div>
              <div style={{ fontSize: 26, fontWeight: 700, fontFamily: mono, color: t.color, marginTop: 7 }}>{t.value}</div>
              <div style={{ fontSize: 11.5, color: C.dim, marginTop: 3 }}>{t.sub}</div>
            </div>
          ))}
        </div>

        <Label style={{ margin: "28px 0 12px" }}>OPEN PROBLEMS BY IMPACT</Label>
        {data.open_problems.length === 0 ? (
          <div style={{ maxWidth: 980, padding: "28px 20px", border: `1px dashed ${C.border4}`, borderRadius: 12, textAlign: "center", color: C.dim, fontSize: 13.5 }}>
            No open problems — every resolved case is either fixed or in verification. Nice.
          </div>
        ) : (
          <div style={{ border: `1px solid ${C.border2}`, borderRadius: 10, overflow: "hidden", maxWidth: 980 }}>
            {data.open_problems.map((p) => (
              <div
                key={p.investigation_id}
                onClick={() => onOpenInvestigation(p.investigation_id)}
                className="el-row"
                style={{ display: "grid", gridTemplateColumns: "64px 1fr 120px 90px", gap: 12, padding: "13px 16px", borderBottom: `1px solid ${C.border}`, alignItems: "center", cursor: "pointer", background: C.card }}
              >
                <span style={{ fontFamily: mono, fontSize: 11.5, color: C.accent }}>#{p.investigation_id}</span>
                <span style={{ fontSize: 13.5, color: C.text2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.summary}</span>
                <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                  <div style={{ flex: 1, height: 5, borderRadius: 3, background: C.track, overflow: "hidden" }}>
                    <div style={{ height: "100%", width: `${Math.round(p.impact_score * 100)}%`, background: C.accent }} />
                  </div>
                </div>
                <span style={{ fontFamily: mono, fontSize: 11.5, color: C.muted, textAlign: "right" }}>{p.affected_pct}%</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
