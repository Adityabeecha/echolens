import { PortfolioProduct, PortfolioTheme, TransferStats, api, isAdmin } from "../api";
import { useAsync } from "../hooks";
import { C, MEASURE, R, S, T, mono } from "../theme";
import { Bar, Centered, ErrorState, Label, ScreenHeader } from "../ui";
import { Icon } from "../components/Icon";

// Band → the colour that carries "how much does this need me". Semantic, kept
// separate from the amber accent so a burning product can't be confused with a
// primary action.
const BAND: Record<string, { color: string; label: string }> = {
  on_fire: { color: C.bad, label: "NEEDS YOU TODAY" },
  attention: { color: C.accent, label: "WORTH A LOOK" },
  watch: { color: C.info, label: "TRENDING" },
  healthy: { color: C.good, label: "HEALTHY" }
};

interface Props {
  onOpenProduct: (id: number) => void;
  onOpenInvestigation: (id: number) => void;
  onAddProduct?: () => void;
}

// v9.0 — the one screen a PM opens before they know which product to open.
// Attention is the scarce resource; this allocates it.
export function Portfolio({ onOpenProduct, onOpenInvestigation, onAddProduct }: Props) {
  const { data, loading, error, reload } = useAsync(() => api.portfolio(), []);
  const { data: themes } = useAsync(() => api.portfolioThemes(), []);
  const { data: brief } = useAsync(() => api.portfolioBrief(), []);

  if (loading && !data) return <Centered>Reading every product…</Centered>;
  if (error || !data) {
    return (
      <div style={{ padding: 28 }}>
        <ErrorState title="Couldn't load your portfolio" onRetry={reload} />
      </div>
    );
  }

  if (data.products.length === 0) {
    return (
      <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
        <ScreenHeader title="All products" />
        <Centered>
          <div style={{ textAlign: "center", maxWidth: 420 }}>
            <div style={{ fontSize: T.md, color: C.text3, marginBottom: S[2] }}>No products connected yet.</div>
            <div style={{ fontSize: T.base, color: C.dim, lineHeight: "var(--el-lh-normal)", marginBottom: S[4] }}>
              Connect an app and EchoLens starts watching its feedback. Add a second one and this screen
              starts ranking them for you.
            </div>
            {onAddProduct && isAdmin() && (
              <button onClick={onAddProduct} className="el-btn el-btn--primary"
                style={{ borderRadius: R.control,
                         padding: `${S[2]} ${S[4]}`, fontWeight: 600, fontSize: T.base }}>
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
        title="All products"
        subtitle="Ranked by what needs you"
        right={
          <span style={{ fontFamily: mono, fontSize: T.xs, color: C.muted }}>
            {data.total_products} PRODUCT{data.total_products === 1 ? "" : "S"} ·{" "}
            {data.needs_attention} NEED{data.needs_attention === 1 ? "S" : ""} ATTENTION
          </span>
        }
      />
      <div style={{ flex: 1, overflow: "auto", padding: `${S[5]} ${S[6]}` }}>
        {/* The one line to read first. */}
        <div style={{ maxWidth: MEASURE, padding: `${S[4]} ${S[5]}`, borderRadius: R.card,
                      background: C.card, border: `1px solid ${BAND[top.band].color}44`,
                      display: "flex", alignItems: "center", gap: S[3], flexWrap: "wrap" }}>
          <div style={{ width: 3, alignSelf: "stretch", minHeight: 34, borderRadius: R.sm,
                        background: BAND[top.band].color, flex: "none" }} />
          <div style={{ flex: 1, minWidth: 240 }}>
            <Label style={{ letterSpacing: ".12em", color: BAND[top.band].color, marginBottom: S[1] }}>
              WHERE TO START
            </Label>
            <div style={{ fontSize: T.lg, fontWeight: 600, color: C.text, letterSpacing: "-.01em", lineHeight: "var(--el-lh-snug)" }}>
              {data.verdict}
            </div>
          </div>
          <span style={{ fontFamily: mono, fontSize: T.micro, color: C.faint }}>{data.generated}</span>
        </div>

        <Label style={{ margin: "26px 0 12px" }}>RANKED BY WHAT NEEDS YOU</Label>
        <div style={{ display: "flex", flexDirection: "column", gap: S[2], maxWidth: MEASURE }}>
          {data.products.map((p) => (
            <ProductRow key={p.product_id} p={p} onOpen={onOpenProduct}
                        onOpenInvestigation={onOpenInvestigation} />
          ))}
        </div>

        {data.transfer && <TransferCard t={data.transfer} />}

        {themes && themes.themes.length > 0 && (
          <>
            <Label style={{ margin: "28px 0 6px" }}>THE SAME COMPLAINT, ACROSS PRODUCTS</Label>
            <p style={{ fontSize: T.sm, color: C.dim, maxWidth: 720, marginTop: 0, lineHeight: "var(--el-lh-normal)" }}>
              {themes.note} Comparing shares, not counts, is the only way a big app and a small one line up
              honestly.
            </p>
            <div style={{ display: "flex", flexDirection: "column", gap: S[3], maxWidth: MEASURE }}>
              {themes.themes.map((t) => <ThemeCompare key={t.theme_id} t={t} />)}
            </div>
          </>
        )}

        {brief && brief.lines.length > 0 && (
          <>
            <Label style={{ margin: "28px 0 12px" }}>THIS WEEK, EVERYTHING YOU OWN</Label>
            <div style={{ maxWidth: MEASURE, padding: `${S[4]} ${S[5]}`, background: C.card,
                          border: `1px solid ${C.border2}`, borderRadius: R.card,
                          display: "flex", flexDirection: "column", gap: S[2] }}>
              {brief.lines.map((ln, i) => (
                <div key={i} style={{ fontSize: T.base, color: i === 0 ? C.text2 : C.text3, lineHeight: "var(--el-lh-normal)" }}>
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
      style={{ display: "flex", gap: S[3], padding: `${S[4]} ${S[4]}`, background: C.card,
               border: `1px solid ${C.border2}`, borderRadius: R.card }}
      onClick={() => onOpen(p.product_id)}
      role="button" tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onOpen(p.product_id); }
      }}
    >
      {/* severity stripe — state as form, not just words */}
      <div style={{ width: 3, borderRadius: R.sm, background: band.color, flex: "none" }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: S[2], flexWrap: "wrap" }}>
          <span style={{ fontSize: T.md, fontWeight: 600, color: C.text }}>{p.product}</span>
          {p.is_demo && (
            <span style={{ fontFamily: mono, fontSize: T.micro, padding: `0 ${S[2]}`, borderRadius: R.card,
                           background: C.hover, color: C.faint, letterSpacing: ".06em" }}>DEMO</span>
          )}
          <span style={{ fontFamily: mono, fontSize: T.micro, letterSpacing: ".08em", color: band.color,
                         padding: `0 ${S[2]}`, borderRadius: R.card, background: `${band.color}1a`,
                         border: `1px solid ${band.color}55` }}>
            {band.label}
          </span>
          <span style={{ marginLeft: "auto", fontFamily: mono, fontSize: T.xs, color: C.faint }}>
            {p.has_data ? `${p.negative_rate_pct}% negative` : "no data yet"}
            {p.has_data && trend !== 0 && (
              <span style={{ color: trend > 0 ? C.bad : C.good, marginLeft: 6 }}>
                <Icon name={trend > 0 ? "arrowUp" : "arrowDown"} size={11} /> {Math.abs(trend)} pts
              </span>
            )}
          </span>
        </div>

        <div style={{ fontSize: T.base, color: C.text3, marginTop: S[1], lineHeight: "var(--el-lh-snug)" }}>{p.headline}</div>

        {/* why it is ranked here — a ranking a PM can't audit is one they won't trust */}
        {p.reasons.length > 1 && (
          <div style={{ display: "flex", gap: S[1], flexWrap: "wrap", marginTop: S[2] }}>
            {p.reasons.slice(1, 4).map((r) => (
              <span key={r.kind} style={{ fontFamily: mono, fontSize: T.micro, padding: `${S[1]} ${S[2]}`,
                                          borderRadius: R.pill, background: C.hover,
                                          border: `1px solid ${C.border3}`, color: C.muted }}>
                {r.text}
              </span>
            ))}
          </div>
        )}

        {p.top_problem && (
          <button className="el-btn"
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                e.stopPropagation();
                onOpenInvestigation(p.top_problem!.investigation_id);
              }
            }}
            onClick={(e) => { e.stopPropagation(); onOpenInvestigation(p.top_problem!.investigation_id); }}
            style={{ marginTop: S[2], fontSize: T.sm, color: C.muted, display: "flex", gap: S[2],
                     alignItems: "baseline" }}
          >
            <span style={{ fontFamily: mono, fontSize: T.xs, color: C.accent }}>
              #{p.top_problem.investigation_id}
            </span>
            <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {p.top_problem.summary}
            </span>
          </button>
        )}
      </div>
    </div>
  );
}

function TransferCard({ t }: { t: TransferStats }) {
  return (
    <>
      <Label style={{ margin: "28px 0 12px" }}>KNOWLEDGE THAT COMPOUNDED</Label>
      <div style={{ maxWidth: MEASURE, padding: `${S[4]} ${S[4]}`, background: C.card,
                    border: `1px solid ${C.border2}`, borderRadius: R.card }}>
        {t.seeded_cases === 0 ? (
          <div style={{ fontSize: T.base, color: C.dim, lineHeight: "var(--el-lh-normal)" }}>
            No cross-product transfers yet. Once a fix is <span style={{ color: C.good }}>verified</span> on
            one product, the next matching problem on another starts from that proven cause instead of from
            scratch.
          </div>
        ) : (
          <div style={{ display: "flex", gap: S[6], flexWrap: "wrap", alignItems: "flex-end" }}>
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
                <div style={{ fontSize: T.base, color: C.text3, lineHeight: "var(--el-lh-normal)" }}>
                  Reusing a verified fix cut{" "}
                  <span style={{ color: C.good, fontWeight: 600 }}>{t.iterations_saved_pct}%</span> of the
                  reasoning steps, measured against cases that started cold.
                </div>
              ) : (
                <div style={{ fontSize: T.sm, color: C.dim, lineHeight: "var(--el-lh-normal)" }}>
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
      <div style={{ fontFamily: mono, fontSize: T.micro, letterSpacing: ".1em", color: C.faint }}>{label}</div>
      <div style={{ fontSize: T.xl, fontWeight: 700, fontFamily: mono, color, marginTop: S[1] }}>{value}</div>
    </div>
  );
}

function ThemeCompare({ t }: { t: PortfolioTheme }) {
  const max = Math.max(1, ...t.products.map((p) => p.rate_pct));
  return (
    <div style={{ padding: `${S[3]} ${S[4]}`, background: C.card, border: `1px solid ${C.border2}`,
                  borderRadius: R.card }}>
      <div style={{ display: "flex", alignItems: "center", gap: S[2], marginBottom: S[3] }}>
        <span style={{ fontSize: T.base, fontWeight: 600, color: C.text2 }}>{t.label}</span>
        {!t.is_family && (
          <span style={{ fontFamily: mono, fontSize: T.micro, padding: `0 ${S[2]}`, borderRadius: R.card,
                         background: C.hover, color: C.faint, letterSpacing: ".06em" }}>
            EMERGENT
          </span>
        )}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: S[2] }}>
        {t.products.map((row) => (
          <div key={row.product ?? "—"}
               style={{ display: "grid", gridTemplateColumns: "minmax(90px,140px) 1fr 84px",
                        gap: S[3], alignItems: "center" }}>
            <span style={{ fontSize: T.sm, color: C.text3, overflow: "hidden",
                           textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{row.product}</span>
            <Bar pct={(row.rate_pct / max) * 100}
                 color={row.product === t.worst ? C.bad : C.info} height={6} />
            <span style={{ fontFamily: mono, fontSize: T.xs, color: C.muted, textAlign: "right",
                           fontVariantNumeric: "tabular-nums" }}>
              {row.rate_pct}% · {row.mentions}/{row.negatives}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
