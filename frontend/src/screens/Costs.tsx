import { api } from "../api";
import { useAsync } from "../hooks";
import { C, mono } from "../theme";
import { Centered, Label } from "../ui";

const ROW_STATUS_COLOR: Record<string, string> = {
  resolved: C.good,
  running: C.accent,
  needs_human: C.accent,
  insufficient_evidence: C.muted,
  budget_exhausted: C.bad,
};

const COLS = "64px 1.5fr 90px 90px 90px 100px";

export function Costs() {
  const { data, loading, error } = useAsync(() => api.costsSummary(), []);
  if (loading) return <Centered>Loading costs…</Centered>;
  if (error || !data) return <Centered>Backend unavailable.</Centered>;

  const st = data.stats;
  const pct = data.budget ? (data.month_to_date / data.budget) * 100 : 0;
  const tiles = [
    { label: "SPENT TODAY", value: `$${st.spent_today.toFixed(2)}`, color: C.text },
    { label: "AVG PER RESOLVED CASE", value: `$${st.avg_per_resolved.toFixed(2)}`, color: C.good },
    { label: "SPENT ON DEAD ENDS", value: `$${st.dead_end_spend.toFixed(2)}`, color: C.accent },
    { label: "EST. ANALYST HOURS SAVED", value: `${st.analyst_hours_saved}h`, color: C.info },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16, padding: "16px 28px", borderBottom: `1px solid ${C.border}`, flex: "none" }}>
        <div style={{ fontSize: 17, fontWeight: 600 }}>Costs</div>
        <div style={{ flex: 1 }} />
        <div style={{ fontFamily: mono, fontSize: 11.5, color: C.muted }}>JULY 2026 · BUDGET ${data.budget.toFixed(2)}</div>
      </div>
      <div style={{ flex: 1, overflow: "auto", padding: "22px 28px" }}>
        <div style={{ display: "flex", gap: 12, maxWidth: 880, flexWrap: "wrap" }}>
          {tiles.map((t) => (
            <div key={t.label} style={{ flex: 1, minWidth: 170, padding: "16px 18px", background: C.card, border: `1px solid ${C.border2}`, borderRadius: 10 }}>
              <div style={{ fontFamily: mono, fontSize: 10, letterSpacing: ".1em", color: C.faint }}>{t.label}</div>
              <div style={{ fontSize: 24, fontWeight: 700, marginTop: 8, fontFamily: mono, color: t.color }}>{t.value}</div>
            </div>
          ))}
        </div>

        <div style={{ maxWidth: 880, marginTop: 22, padding: "18px 20px", background: C.card, border: `1px solid ${C.border2}`, borderRadius: 10 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 12 }}>
            <Label>MONTH-TO-DATE SPEND</Label>
            <span style={{ fontFamily: mono, fontSize: 12, color: C.text }}>
              ${data.month_to_date.toFixed(2)} / ${data.budget.toFixed(2)}
            </span>
          </div>
          <div style={{ height: 8, borderRadius: 4, background: C.track, overflow: "hidden" }}>
            <div style={{ height: "100%", width: `${Math.min(100, pct)}%`, borderRadius: 4, background: "linear-gradient(90deg,#b06f1a,#f0a63c)" }} />
          </div>
        </div>

        <Label style={{ margin: "26px 0 10px" }}>LIMITS</Label>
        <div style={{ display: "flex", gap: 12, maxWidth: 880, flexWrap: "wrap" }}>
          {[
            { name: "Daily investigations", value: `${data.limits.daily_investigations} / day` },
            { name: "Per-case budget", value: `$${data.limits.per_case_budget.toFixed(2)}` },
            { name: "Per-case wall-clock", value: `${data.limits.per_case_wall_min} min` },
          ].map((l) => (
            <div key={l.name} style={{ flex: 1, minWidth: 200, padding: "13px 16px", background: C.card, border: `1px solid ${C.border2}`, borderRadius: 10 }}>
              <div style={{ fontSize: 12.5, color: C.text3 }}>{l.name}</div>
              <div style={{ fontFamily: mono, fontSize: 15, color: C.text, marginTop: 3 }}>{l.value}</div>
            </div>
          ))}
        </div>

        <Label style={{ margin: "26px 0 10px" }}>COST PER CASE</Label>
        <div style={{ border: `1px solid ${C.border2}`, borderRadius: 10, overflowX: "auto", maxWidth: 880 }}>
          <div style={{ minWidth: 700 }}>
            <div style={{ display: "grid", gridTemplateColumns: COLS, gap: 12, padding: "10px 16px", background: C.card2, fontFamily: mono, fontSize: 10, letterSpacing: ".08em", color: C.faint, borderBottom: `1px solid ${C.border}` }}>
              <span>CASE</span>
              <span>OUTCOME</span>
              <span>TOKENS</span>
              <span>QUERIES</span>
              <span>TIME</span>
              <span style={{ textAlign: "right" }}>COST</span>
            </div>
            {data.rows.map((r) => (
              <div key={r.id} style={{ display: "grid", gridTemplateColumns: COLS, gap: 12, padding: "12px 16px", borderBottom: `1px solid #1c1e27`, alignItems: "center", background: C.card }}>
                <span style={{ fontFamily: mono, fontSize: 11.5, color: C.accent }}>{r.id}</span>
                <span style={{ fontSize: 12.5, color: ROW_STATUS_COLOR[r.status] ?? C.muted }}>{r.outcome}</span>
                <span style={{ fontFamily: mono, fontSize: 11.5, color: C.muted }}>{r.tokens}</span>
                <span style={{ fontFamily: mono, fontSize: 11.5, color: C.muted }}>{r.queries}</span>
                <span style={{ fontFamily: mono, fontSize: 11.5, color: C.muted }}>{r.time}</span>
                <span style={{ fontFamily: mono, fontSize: 11.5, color: C.text, textAlign: "right" }}>{r.cost}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
