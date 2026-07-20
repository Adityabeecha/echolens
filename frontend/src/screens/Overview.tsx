import { api } from "../api";
import { useAsync } from "../hooks";
import { C, mono } from "../theme";
import { Centered, Label, ScreenHeader } from "../ui";

// Split "…case #12…" into clickable case links.
function Cited({ text, onOpen }: { text: string; onOpen: (id: number) => void }) {
  const parts = text.split(/(case #\d+)/g);
  return (
    <>
      {parts.map((p, i) => {
        const m = p.match(/^case #(\d+)$/);
        if (!m) return <span key={i}>{p}</span>;
        return (
          <span key={i} onClick={() => onOpen(parseInt(m[1], 10))} style={{ color: C.accent, cursor: "pointer", fontFamily: mono, fontSize: 12.5 }}>
            {p}
          </span>
        );
      })}
    </>
  );
}

// The PM's monthly review, auto-written: outcomes, not alerts.
export function Overview({ onOpenInvestigation }: { onOpenInvestigation: (id: number) => void }) {
  const { data, loading, error } = useAsync(() => api.overview(), []);
  const { data: brief } = useAsync(() => api.brief(), []);
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
      <ScreenHeader title={`Product Health${data.product ? ` · ${data.product}` : ""}`} right={<span style={{ fontFamily: mono, fontSize: 11.5, color: C.muted }}>OUTCOMES, NOT ALERTS</span>} />
      <div style={{ flex: 1, overflow: "auto", padding: "22px 28px" }}>
        {brief && brief.lines.length > 0 && (
          <div style={{ maxWidth: 980, marginBottom: 20, padding: "16px 20px", background: C.card, border: `1px solid ${C.border2}`, borderRadius: 12 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
              <Label style={{ letterSpacing: ".12em", color: C.accent }}>THIS WEEK</Label>
              <span style={{ fontFamily: mono, fontSize: 10.5, color: C.faint }}>{brief.generated}</span>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {brief.lines.map((ln, i) => (
                <div key={i} style={{ fontSize: 13.5, color: i === 0 ? C.text2 : C.text3, lineHeight: 1.5 }}>
                  <Cited text={ln} onOpen={onOpenInvestigation} />
                </div>
              ))}
            </div>
          </div>
        )}

        {data.chronic_themes && data.chronic_themes.length > 0 && (
          <div style={{ maxWidth: 980, marginBottom: 20 }}>
            <Label style={{ marginBottom: 10, color: C.bad }}>⚠ CHRONIC THEMES · UNRESOLVED &gt; 60 DAYS</Label>
            <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
              {data.chronic_themes.map((t) => (
                <div key={t.theme} onClick={() => t.cases[0] && onOpenInvestigation(t.cases[0])}
                  className="el-row"
                  style={{ display: "flex", alignItems: "center", gap: 12, padding: "13px 16px", background: C.card, border: `1px solid ${C.bad}44`, borderRadius: 10, cursor: "pointer" }}>
                  <span style={{ fontFamily: mono, fontSize: 11, padding: "3px 9px", borderRadius: 20, background: `${C.bad}1f`, color: C.bad }}>{t.age_days}d</span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13.5, color: C.text2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.label}</div>
                    <div style={{ fontFamily: mono, fontSize: 10.5, color: C.faint, marginTop: 2 }}>
                      {t.theme} · first seen {t.first_seen} · {t.open_cases} open
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

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
                {/* an impact score of 0 means the inputs aren't in yet — say so
                    rather than showing a fake 0% bar */}
                {p.impact_score > 0 ? (
                  <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                    <div style={{ flex: 1, height: 5, borderRadius: 3, background: C.track, overflow: "hidden" }}>
                      <div style={{ height: "100%", width: `${Math.max(4, Math.round(p.impact_score * 100))}%`, background: C.accent }} />
                    </div>
                  </div>
                ) : (
                  <span style={{ fontFamily: mono, fontSize: 10, color: C.faint }}>collecting data</span>
                )}
                <span style={{ fontFamily: mono, fontSize: 11.5, color: C.muted, textAlign: "right" }}>
                  {p.impact_score > 0 ? `${p.affected_pct}%` : "—"}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
