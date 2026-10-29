import { Portfolio as PortfolioData, PortfolioProduct, PortfolioTheme, TransferStats, api, isAdmin } from "../api";
import { pct } from "../format";
import { useAsync } from "../hooks";
import { C } from "../theme";
import { Bar, Button, Centered, ErrorState, Spark } from "../ui";
import { EmptyState, SerifHeadline, Stamp, stampFor } from "../components/casefile";
import "./settings/ps.css";

interface Props {
  onOpenProduct: (id: number) => void;
  onOpenInvestigation: (id: number) => void;
  onAddProduct?: () => void;
}

/** What each health band means, in words. */
const BAND_WORDS: Record<string, string> = {
  on_fire: "Needs you today", attention: "Needs attention", watch: "Worth watching", healthy: "Healthy",
};

/**
 * All products: the one screen opened before knowing which product to open.
 * It answers first (where to start, and why), then one row per app — health,
 * the rating over 12 weeks, the negative share, the top problem with its
 * verdict, and what people complain about.
 */
export function Portfolio({ onOpenProduct, onOpenInvestigation, onAddProduct }: Props) {
  const { data, loading, error, reload } = useAsync(() => api.portfolio(), []);
  // A FAILED fetch and a genuinely empty section must not look the same:
  // "no cross-product themes" is a claim, so a failure says it is missing.
  const { data: themes, error: themesError } = useAsync(() => api.portfolioThemes(), []);
  const { data: brief, error: briefError } = useAsync(() => api.portfolioBrief(), []);

  if (loading && !data) return <Centered>Reading every product…</Centered>;
  if (error || !data) {
    return <div style={{ padding: 28 }}><ErrorState title="Couldn't load your products" onRetry={reload} /></div>;
  }

  if (data.products.length === 0) {
    return (
      <div className="ps-screen"><main className="ps-main">
        <SerifHeadline as="h1" size="page">No products yet.</SerifHeadline>
        <EmptyState title="Connect your first app."
          action={onAddProduct && isAdmin() ? <Button variant="primary" onClick={onAddProduct}>Add your first product</Button> : undefined}>
          Connect an app and EchoLens starts reading its feedback. Add a second one and this page tells you which needs you first.
        </EmptyState>
      </main></div>
    );
  }

  return (
    <div className="ps-screen">
      <main className="ps-main">
        <header className="ps-head">
          <div className="ps-head__meta">
            <span><b>{data.total_products}</b> {data.total_products === 1 ? "product" : "products"} · {data.needs_attention} need
              {data.needs_attention === 1 ? "s" : ""} attention · as of {data.generated}</span>
            <span className="ps-spacer" />
            {onAddProduct && isAdmin() && <Button variant="ghost" size="sm" icon="plus" onClick={onAddProduct}>Add a product</Button>}
          </div>
          <SerifHeadline as="h1" size="page">{headline(data)}</SerifHeadline>
        </header>

        <section className="ps-section" aria-label="Every product, ranked by what needs you">
          <div className="ps-products">
            {data.products.map((p) => (
              <ProductRow key={p.product_id} p={p} onOpen={onOpenProduct} onOpenInvestigation={onOpenInvestigation} />
            ))}
          </div>
        </section>

        {themesError && <ErrorState title="Couldn't load the shared complaints" detail="This section is missing, not empty." />}
        {themes && themes.themes.length > 0 && (
          <section className="ps-section" aria-labelledby="ps-same">
            <h2 id="ps-same">The same complaint, across products</h2>
            <p className="ps-note">{themes.note} Shares, not counts, so a big app and a small one compare honestly.</p>
            <div className="ps-panel">{themes.themes.map((t) => <ThemeCompare key={t.theme_id} t={t} />)}</div>
          </section>
        )}

        {briefError && <ErrorState title="Couldn't load this week's summary" detail="This section is missing, not empty." />}
        {brief && brief.lines.length > 0 && (
          <section className="ps-section" aria-labelledby="ps-week">
            <h2 id="ps-week">This week, everything you own</h2>
            <div className="ps-panel">
              {brief.lines.map((ln, i) => (
                <p key={i} className="ps-note" style={{ color: i === 0 ? "var(--el-ink)" : undefined }}>{ln}</p>
              ))}
            </div>
          </section>
        )}

        {data.transfer && <TransferCard t={data.transfer} />}
      </main>
    </div>
  );
}

/** "Start with Lumo — one confirmed problem is waiting for a fix." The star
 *  figure here was the whole app's rating fall, not this problem's cost, so it
 *  is no longer quoted; the problem page shows the problem's own number. */
function headline(data: PortfolioData): string {
  const top = data.products[0];
  const tp = top?.top_problem;
  const proven = tp && stampFor({ status: tp.status, support_level: tp.support_level, needs_review: tp.needs_review,
    fix: tp.fix_status ? { status: tp.fix_status } : null }) === "confirmed";
  const n = top?.confirmed_open ?? 0;
  if (top && top.band !== "healthy" && proven && n > 0) {
    return n === 1
      ? `Start with ${top.product} — one confirmed problem is waiting for a fix.`
      : `Start with ${top.product} — ${n} confirmed problems are waiting for a fix.`;
  }
  return data.verdict;
}

function ProductRow({ p, onOpen, onOpenInvestigation }: {
  p: PortfolioProduct; onOpen: (id: number) => void; onOpenInvestigation: (id: number) => void;
}) {
  const weeks = (p.rating_weekly ?? []).filter((v): v is number => v != null);
  const now = weeks.at(-1);
  const tp = p.top_problem;
  const verdict = tp ? stampFor({ status: tp.status ?? "resolved", support_level: tp.support_level,
    needs_review: tp.needs_review, fix: tp.fix_status ? { status: tp.fix_status } : null }) : null;
  const trend = p.negative_rate_delta_pct;
  return (
    <article className="ps-product" aria-label={p.product}>
      <div className="ps-health" title={`Health ${Math.round(p.health)} of 100 — higher is better. Ranked by what needs you.`}>
        <span className="ps-health__n">{Math.round(p.health)}<small>/100</small></span>
        <span className="ps-health__label"><i className={`ps-dot is-${p.band}`} aria-hidden />{BAND_WORDS[p.band] ?? p.band_label}</span>
      </div>
      <div className="ps-product__name">
        <button type="button" onClick={() => onOpen(p.product_id)}>{p.product}{p.is_demo && !/demo/i.test(p.product) ? " · demo" : ""}</button>
        <span>{p.headline.charAt(0).toUpperCase() + p.headline.slice(1)}</span>
        {(p.top_topics?.length ?? 0) > 0 && (
          <div className="ps-topics" aria-label="What people complain about">
            {p.top_topics!.map((t) => <span key={t}>{t}</span>)}
          </div>
        )}
      </div>
      <div className="ps-trend">
        {weeks.length >= 2 ? (
          <>
            <Spark points={weeks} color={C.ink} width={140} height={30}
              title={`Average rating per week over 12 weeks: ${weeks.map((w) => w.toFixed(1)).join(", ")}`} />
            <span><b>{now!.toFixed(1)}★</b> this week</span>
          </>
        ) : <span>No rating trend yet</span>}
        <span title={p.negative_rate_pct == null ? p.negative_rate_reason ?? undefined : "Share of the last 7 days' reviews rated 1–2★"}>
          {!p.has_data ? "No feedback collected yet"
            : p.negative_rate_pct == null ? <>— negative · {p.negative_rate_reason ?? "too few recent reviews"}</>
            : <><b>{pct(p.negative_rate_pct, 1)}</b> negative{trend ? ` · ${trend > 0 ? "up" : "down"} ${Math.abs(trend)} pts` : ""}</>}
        </span>
      </div>
      <div className="ps-problem">
        {tp && verdict && verdict !== "live" ? (
          <button type="button" onClick={() => onOpenInvestigation(tp.investigation_id)}>
            <Stamp variant={verdict} compact rotation={-3} />
            <span>{tp.summary}</span>
          </button>
        ) : <span className="ps-muted">No open problem</span>}
        {p.open_problems > 1 && <span className="ps-muted">{p.open_problems} open problems in all</span>}
      </div>
    </article>
  );
}

function TransferCard({ t }: { t: TransferStats }) {
  return (
    <section className="ps-section" aria-labelledby="ps-transfer">
      <h2 id="ps-transfer">What one product taught another</h2>
      <div className="ps-panel">
        {t.seeded_cases === 0 ? (
          <p className="ps-note">Nothing yet. Once a fix is confirmed on one product, the next matching problem on another
            starts from that proven cause instead of from scratch.</p>
        ) : (
          <>
            <p className="ps-note">
              {t.seeded_cases} {t.seeded_cases === 1 ? "problem" : "problems"} started from a fix already proven elsewhere.{" "}
              {t.sufficient && t.iterations_saved_pct != null && t.iterations_saved_pct > 0
                ? <>That cut <b>{t.iterations_saved_pct}%</b> of the steps, against problems that started from scratch.</>
                : "Not enough of both kinds yet to say whether it saves time."}
            </p>
            <span className="ps-muted" title="Median reasoning steps per problem">
              Median steps: {t.median_iterations_seeded ?? "—"} reusing a fix · {t.median_iterations_cold ?? "—"} from scratch
            </span>
          </>
        )}
      </div>
    </section>
  );
}

function ThemeCompare({ t }: { t: PortfolioTheme }) {
  const max = Math.max(1, ...t.products.map((p) => p.rate_pct));
  return (
    <div className="ps-card">
      <strong style={{ fontWeight: 500 }} title={t.is_family ? undefined : "Found across products without a known family name"}>{t.label}</strong>
      <div className="ps-breakdown">
        {t.products.map((row) => (
          <div key={row.product ?? "—"}>
            <span>{row.product}</span>
            <Bar pct={(row.rate_pct / max) * 100} color={row.product === t.worst ? C.stampRed : C.ink} height={6} />
            <span title={`${row.mentions} of ${row.negatives} negative reviews`}>{row.rate_pct}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}
