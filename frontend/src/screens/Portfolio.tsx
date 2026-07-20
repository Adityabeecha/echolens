import { PortfolioProduct, PortfolioTheme, TransferStats, api } from "../api";
import { useAsync } from "../hooks";
import { C, mono } from "../theme";
import { Bar, Centered, Label, ScreenHeader } from "../ui";

// Band → the colour that carries "how much does this need me". Semantic, kept
// separate from the amber accent so a burning product can't be confused with a
// primary action.
const BAND: Record<string, { color: string; label: string }> = {
  on_fire: { color: C.bad, label: "NEEDS YOU TODAY" },
  attention: { color: C.accent, label: "WORTH A LOOK" },
  watch: { color: C.info, label: "TRENDING" },
  healthy: { color: C.good, label: "HEALTHY" },
};

interface Props {
  onOpenProduct: (id: number) => void;
  onOpenInvestigation: (id: number) => void;
  onAddProduct?: () => void;
}

// v9.0 — the one screen a PM opens before they know which product to open.
// Attention is the scarce resource; this allocates it.
export function Portfolio({ onOpenProduct, onOpenInvestigation, onAddProduct }: Props) {
  const { data, loading, error } = useAsync(() => api.portfolio(), []);
  const { data: themes } = useAsync(() => api.portfolioThemes(), []);
  const { data: brief } = useAsync(() => api.portfolioBrief(), []);

  if (loading) return <Centered>Reading every product…</Centered>;
  if (error || !data) return <Centered>Backend unavailable — the portfolio couldn't be loaded.</Centered>;

  if (data.products.length === 0) {
    return (
      <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
        <ScreenHeader title="Portfolio" />
        <Centered>
          <div style={{ textAlign: "center", maxWidth: 420 }}>
            <div style={{ fontSize: 15, color: C.text3, marginBottom: 8 }}>No products connected yet.</div>
            <div style={{ fontSize: 13, color: C.dim, lineHeight: 1.6, marginBottom: 16 }}>
              Connect an app and EchoLens starts watching its feedback. Add a second one and this screen
              starts ranking them for you.
            </div>
            {onAddProduct && (
              <button onClick={onAddProduct} className="el-btn"
                style={{ background: C.accent, color: C.onAccent, border: "none", borderRadius: 6,
                         padding: "9px 16px", fontWeight: 600, fontSize: 13, cursor: "pointer" }}>
                Add your first product
              </button>
            )}
          </div>
        </Centered>
      </div>
    );
  }

  const top = data.products[0];
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <ScreenHeader
        title="Portfolio"
        right={
          <span style={{ fontFamily: mono, fontSize: 11.5, color: C.muted }}>
            {data.total_products} PRODUCT{data.total_products === 1 ? "" : "S"} ·{" "}
            {data.needs_attention} NEED{data.needs_attention === 1 ? "S" : ""} ATTENTION
          </span>
        }
      />
      <div style={{ flex: 1, overflow: "auto", padding: "22px 28px" }}>
        {/* The one line to read first. */}
        <div style={{ maxWidth: 980, padding: "16px 20px", borderRadius: 12,
                      background: C.card, border: `1px solid ${BAND[top.band].color}44`,
                      display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
          <div style={{ width: 3, alignSelf: "stretch", minHeight: 34, borderRadius: 2,
                        background: BAND[top.band].color, flex: "none" }} />
          <div style={{ flex: 1, minWidth: 240 }}>
            <Label style={{ letterSpacing: ".12em", color: BAND[top.band].color, marginBottom: 6 }}>
              WHERE TO START
            </Label>
            <div style={{ fontSize: 16, fontWeight: 600, color: C.text, letterSpacing: "-.01em", lineHeight: 1.4 }}>
              {data.verdict}
            </div>
          </div>
          <span style={{ fontFamily: mono, fontSize: 10.5, color: C.faint }}>{data.generated}</span>
        </div>

        <Label style={{ margin: "26px 0 12px" }}>RANKED BY WHAT NEEDS YOU</Label>
        <div style={{ display: "flex", flexDirection: "column", gap: 10, maxWidth: 980 }}>
          {data.products.map((p) => (
            <ProductRow key={p.product_id} p={p} onOpen={onOpenProduct}
                        onOpenInvestigation={onOpenInvestigation} />
          ))}
        </div>

        {data.transfer && <TransferCard t={data.transfer} />}

        {themes && themes.themes.length > 0 && (
          <>
            <Label style={{ margin: "28px 0 6px" }}>THE SAME COMPLAINT, ACROSS PRODUCTS</Label>
            <p style={{ fontSize: 12.5, color: C.dim, maxWidth: 720, marginTop: 0, lineHeight: 1.55 }}>
              {themes.note} Comparing shares, not counts, is the only way a big app and a small one line up
              honestly.
            </p>
            <div style={{ display: "flex", flexDirection: "column", gap: 12, maxWidth: 980 }}>
              {themes.themes.map((t) => <ThemeCompare key={t.theme_id} t={t} />)}
            </div>
          </>
        )}

        {brief && brief.lines.length > 0 && (
          <>
            <Label style={{ margin: "28px 0 12px" }}>THIS WEEK, EVERYTHING YOU OWN</Label>
            <div style={{ maxWidth: 980, padding: "16px 20px", background: C.card,
                          border: `1px solid ${C.border2}`, borderRadius: 12,
                          display: "flex", flexDirection: "column", gap: 7 }}>
              {brief.lines.map((ln, i) => (
                <div key={i} style={{ fontSize: 13.5, color: i === 0 ? C.text2 : C.text3, lineHeight: 1.5 }}>
                  {ln}
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function ProductRow({ p, onOpen, onOpenInvestigation }: {
  p: PortfolioProduct;
  onOpen: (id: number) => void;
  onOpenInvestigation: (id: number) => void;
}) {
  const band = BAND[p.band];
  const trend = p.negative_rate_delta_pct;
  return (
    <div className="el-row"
      style={{ display: "flex", gap: 14, padding: "15px 18px", background: C.card,
               border: `1px solid ${C.border2}`, borderRadius: 12, cursor: "pointer" }}
      onClick={() => onOpen(p.product_id)}
      role="button" tabIndex={0}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onOpen(p.product_id); }}
    >
      {/* severity stripe — state as form, not just words */}
      <div style={{ width: 3, borderRadius: 2, background: band.color, flex: "none" }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <span style={{ fontSize: 14.5, fontWeight: 600, color: C.text }}>{p.product}</span>
          {p.is_demo && (
            <span style={{ fontFamily: mono, fontSize: 9.5, padding: "2px 7px", borderRadius: 10,
                           background: C.hover, color: C.faint, letterSpacing: ".06em" }}>DEMO</span>
          )}
          <span style={{ fontFamily: mono, fontSize: 9.5, letterSpacing: ".08em", color: band.color,
                         padding: "2px 8px", borderRadius: 10, background: `${band.color}1a`,
                         border: `1px solid ${band.color}55` }}>
            {band.label}
          </span>
          <span style={{ marginLeft: "auto", fontFamily: mono, fontSize: 11, color: C.faint }}>
            {p.has_data ? `${p.negative_rate_pct}% negative` : "no data yet"}
            {p.has_data && trend !== 0 && (
              <span style={{ color: trend > 0 ? C.bad : C.good, marginLeft: 6 }}>
                {trend > 0 ? "▲" : "▼"} {Math.abs(trend)} pts
              </span>
            )}
          </span>
        </div>

        <div style={{ fontSize: 13, color: C.text3, marginTop: 6, lineHeight: 1.45 }}>{p.headline}</div>

        {/* why it is ranked here — a ranking a PM can't audit is one they won't trust */}
        {p.reasons.length > 1 && (
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 9 }}>
            {p.reasons.slice(1, 4).map((r) => (
              <span key={r.kind} style={{ fontFamily: mono, fontSize: 10.5, padding: "3px 9px",
                                          borderRadius: 20, background: C.hover,
                                          border: `1px solid ${C.border3}`, color: C.muted }}>
                {r.text}
              </span>
            ))}
          </div>
        )}

        {p.top_problem && (
          <div
            onClick={(e) => { e.stopPropagation(); onOpenInvestigation(p.top_problem!.investigation_id); }}
            style={{ marginTop: 10, fontSize: 12.5, color: C.muted, display: "flex", gap: 8,
                     alignItems: "baseline" }}
          >
            <span style={{ fontFamily: mono, fontSize: 11, color: C.accent }}>
              #{p.top_problem.investigation_id}
            </span>
            <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {p.top_problem.summary}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

function TransferCard({ t }: { t: TransferStats }) {
  return (
    <>
      <Label style={{ margin: "28px 0 12px" }}>KNOWLEDGE THAT COMPOUNDED</Label>
      <div style={{ maxWidth: 980, padding: "15px 18px", background: C.card,
                    border: `1px solid ${C.border2}`, borderRadius: 12 }}>
        {t.seeded_cases === 0 ? (
          <div style={{ fontSize: 13, color: C.dim, lineHeight: 1.55 }}>
            No cross-product transfers yet. Once a fix is <span style={{ color: C.good }}>verified</span> on
            one product, the next matching problem on another starts from that proven cause instead of from
            scratch.
          </div>
        ) : (
          <div style={{ display: "flex", gap: 26, flexWrap: "wrap", alignItems: "flex-end" }}>
            <Stat label="CASES THAT REUSED A PROVEN FIX" value={String(t.seeded_cases)} color={C.good} />
            <Stat label="MEDIAN STEPS · REUSED"
                  value={t.median_iterations_seeded == null ? "—" : String(t.median_iterations_seeded)}
                  color={C.text} />
            <Stat label="MEDIAN STEPS · FROM SCRATCH"
                  value={t.median_iterations_cold == null ? "—" : String(t.median_iterations_cold)}
                  color={C.muted} />
            <div style={{ flex: 1, minWidth: 220 }}>
              {/* Never claim a speedup the sample can't support. */}
              {t.sufficient && t.iterations_saved_pct != null && t.iterations_saved_pct > 0 ? (
                <div style={{ fontSize: 13, color: C.text3, lineHeight: 1.5 }}>
                  Reusing a verified fix cut{" "}
                  <span style={{ color: C.good, fontWeight: 600 }}>{t.iterations_saved_pct}%</span> of the
                  reasoning steps, measured against cases that started cold.
                </div>
              ) : (
                <div style={{ fontSize: 12.5, color: C.dim, lineHeight: 1.5 }}>
                  Not enough cases yet to measure whether this saves time — shown once there are enough of
                  both kinds to compare.
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </>
  );
}

function Stat({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div>
      <div style={{ fontFamily: mono, fontSize: 9, letterSpacing: ".1em", color: C.faint }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, fontFamily: mono, color, marginTop: 5 }}>{value}</div>
    </div>
  );
}

function ThemeCompare({ t }: { t: PortfolioTheme }) {
  const max = Math.max(1, ...t.products.map((p) => p.rate_pct));
  return (
    <div style={{ padding: "14px 18px", background: C.card, border: `1px solid ${C.border2}`,
                  borderRadius: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 9, marginBottom: 11 }}>
        <span style={{ fontSize: 13.5, fontWeight: 600, color: C.text2 }}>{t.label}</span>
        {!t.is_family && (
          <span style={{ fontFamily: mono, fontSize: 9.5, padding: "2px 7px", borderRadius: 10,
                         background: C.hover, color: C.faint, letterSpacing: ".06em" }}>
            EMERGENT
          </span>
        )}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {t.products.map((row) => (
          <div key={row.product ?? "—"}
               style={{ display: "grid", gridTemplateColumns: "minmax(90px,140px) 1fr 84px",
                        gap: 12, alignItems: "center" }}>
            <span style={{ fontSize: 12.5, color: C.text3, overflow: "hidden",
                           textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{row.product}</span>
            <Bar pct={(row.rate_pct / max) * 100}
                 color={row.product === t.worst ? C.bad : C.info} height={6} />
            <span style={{ fontFamily: mono, fontSize: 11, color: C.muted, textAlign: "right",
                           fontVariantNumeric: "tabular-nums" }}>
              {row.rate_pct}% · {row.mentions}/{row.negatives}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
