import { api } from "../api";
import { money } from "../format";
import { useAsync } from "../hooks";
import { C, MEASURE, R, S, T, mono } from "../theme";
import { Centered, EmptyState, ErrorState, Label, ScreenHeader } from "../ui";

const ROW_STATUS_COLOR: Record<string, string> = {
  resolved: C.good,
  running: C.accent,
  needs_human: C.accent,
  insufficient_evidence: C.muted,
  budget_exhausted: C.bad
};

const COLS = "64px 1.5fr 90px 90px 90px 100px";

/**
 * Costs — the accounting, and nothing else.
 *
 * This screen used to carry the budget limits too, which meant a PM adjusting
 * how much EchoLens may spend had to work inside a token-level cost table. The
 * levers moved to Settings; what is left is the per-case ledger, which is a
 * developer's view and is now labelled as one.
 */
export function Costs({ onGoSettings }: { onGoSettings: () => void }) {
  const { data, loading, error, reload } = useAsync(() => api.costsSummary(), []);
  if (loading && !data) return <Centered>Loading costs…</Centered>;
  if (error || !data) {
    return (
      <div style={{ padding: 28 }}>
        <ErrorState title="Couldn't load costs" onRetry={reload} />
      </div>
    );
  }

  const st = data.stats;
  const tiles = [
    { label: "SPENT TODAY", value: money(st.spent_today), color: C.text },
    { label: "AVG PER RESOLVED CASE", value: money(st.avg_per_resolved), color: C.good },
    { label: "SPENT ON DEAD ENDS", value: money(st.dead_end_spend), color: C.accent },
    { label: "EST. ANALYST HOURS SAVED", value: `${st.analyst_hours_saved}h`, color: C.info },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <ScreenHeader
        title="Costs"
        product={data.product}
        subtitle="What every case cost to run"
        right={
          <button onClick={onGoSettings} className="el-btn"
            style={{ fontSize: T.sm, color: C.dim }}>
            Budgets and limits are in Settings →
          </button>
        }
      />

      <div style={{ flex: 1, overflow: "auto", padding: `${S[5]} ${S[6]} ${S[12]}` }}>
        <div style={{ display: "flex", gap: S[3], maxWidth: MEASURE, flexWrap: "wrap" }}>
          {tiles.map((t) => (
            <div key={t.label} style={{ flex: 1, minWidth: 170, padding: `${S[4]} ${S[4]}`,
                                        background: C.card, border: `1px solid ${C.border2}`,
                                        borderRadius: R.card }}>
              <div style={{ fontFamily: mono, fontSize: T.micro, letterSpacing: ".1em",
                            color: C.faint }}>{t.label}</div>
              <div style={{ fontSize: T.xl, fontWeight: 700, marginTop: S[2], fontFamily: mono,
                            color: t.color }}>{t.value}</div>
            </div>
          ))}
        </div>

        <Label style={{ margin: "26px 0 10px" }}>COST PER CASE</Label>
        {data.rows.length === 0 ? (
          <EmptyState
            title={`No cases have run yet for ${data.product ?? "this product"}`}
            body="Every investigation records its tokens, tool calls, wall-clock time and dollar cost here as it runs."
          />
        ) : (
          <div style={{ border: `1px solid ${C.border2}`, borderRadius: R.card, overflowX: "auto",
                        maxWidth: MEASURE }}>
            <div style={{ minWidth: 700 }}>
              <div style={{ display: "grid", gridTemplateColumns: COLS, gap: S[3],
                            padding: `${S[2]} ${S[4]}`, background: C.card2, fontFamily: mono,
                            fontSize: T.micro, letterSpacing: ".08em", color: C.faint,
                            borderBottom: `1px solid ${C.border}` }}>
                <span>CASE</span>
                <span>OUTCOME</span>
                <span>TOKENS</span>
                <span>QUERIES</span>
                <span>TIME</span>
                <span style={{ textAlign: "right" }}>COST</span>
              </div>
              {data.rows.map((r) => (
                <div key={r.id} style={{ display: "grid", gridTemplateColumns: COLS, gap: S[3],
                                         padding: `${S[3]} ${S[4]}`, borderBottom: `1px solid #1c1e27`,
                                         alignItems: "center", background: C.card }}>
                  <span style={{ fontFamily: mono, fontSize: T.xs, color: C.accent }}>{r.id}</span>
                  <span style={{ fontSize: T.sm, color: ROW_STATUS_COLOR[r.status] ?? C.muted }}>
                    {r.outcome}
                  </span>
                  <span style={{ fontFamily: mono, fontSize: T.xs, color: C.muted }}>{r.tokens}</span>
                  <span style={{ fontFamily: mono, fontSize: T.xs, color: C.muted }}>{r.queries}</span>
                  <span style={{ fontFamily: mono, fontSize: T.xs, color: C.muted }}>{r.time}</span>
                  {/* Through money() like the tiles above. Rendering the
                      server's pre-formatted string here put "$0.00" beside a
                      tile reading "$0.0031" — the same quantity, two formats,
                      which is exactly what format.ts exists to prevent. */}
                  <span style={{ fontFamily: mono, fontSize: T.xs, color: C.text,
                                 textAlign: "right" }}>
                    {money(Number(String(r.cost).replace(/[^0-9.]/g, "")))}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
