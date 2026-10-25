import { Fragment } from "react";
import { api } from "../api";
import { money } from "../format";
import { useAsync } from "../hooks";
import { Icon } from "./Icon";

// The bar above every app screen: where you are, what the AI is costing, and
// the three things you can do from anywhere — ask, run an investigation,
// import reviews. Actions a viewer or guest cannot use are not offered.

export interface Crumb {
  label: string;
  /** Omit on the last crumb (the current page). */
  onClick?: () => void;
  /** Ids and versions ("Case #34") read as data. */
  mono?: boolean;
}

export function AppHeader({
  crumbs, productId, liveKey = 0, onAsk, askShortcut, onRunInvestigation, onImportCsv, onOpenCosts,
}: {
  crumbs: Crumb[];
  productId: number | null;
  /** Bumps when work starts or settles, so this month's spend refreshes. */
  liveKey?: number;
  onAsk: () => void;
  askShortcut: string;
  /** Present only when the user may start a case. */
  onRunInvestigation?: () => void;
  /** Present only when the user may import. */
  onImportCsv?: () => void;
  onOpenCosts?: () => void;
}) {
  return (
    <header className="el-app-header">
      <nav aria-label="Breadcrumb" className="el-crumbs">
        <ol>
          {crumbs.map((c, i) => {
            const last = i === crumbs.length - 1;
            return (
              <Fragment key={`${c.label}-${i}`}>
                {i > 0 && <li aria-hidden className="el-crumbs__sep">/</li>}
                <li className={`el-crumbs__item${last ? " is-current" : ""}${c.mono ? " el-mono" : ""}`}>
                  {c.onClick && !last ? (
                    <button type="button" onClick={c.onClick}>{c.label}</button>
                  ) : (
                    <span aria-current={last ? "page" : undefined}>{c.label}</span>
                  )}
                </li>
              </Fragment>
            );
          })}
        </ol>
      </nav>

      <div className="el-app-header__spacer" />

      <CostPill productId={productId} liveKey={liveKey} onOpen={onOpenCosts} />

      <button type="button" className="el-ask-btn" onClick={onAsk} data-tour="ask"
              aria-keyshortcuts={askShortcut.startsWith("⌘") ? "Meta+K" : "Control+K"}
              title="Ask anything about your feedback">
        <Icon name="search" size={14} />
        <span className="el-ask-btn__text">Ask</span>
        <kbd>{askShortcut}</kbd>
      </button>

      {onImportCsv && (
        <button type="button" className="el-btn el-btn--quiet el-btn--sm el-app-header__action"
                onClick={onImportCsv} title="Import reviews from a CSV or Excel file">
          <Icon name="upload" size={14} />
          <span className="el-app-header__action-text">Import CSV</span>
        </button>
      )}
      {onRunInvestigation && (
        <button type="button" className="el-btn el-btn--primary el-btn--sm el-app-header__action"
                onClick={onRunInvestigation} title="Describe a problem and investigate it">
          <Icon name="play" size={13} />
          <span className="el-app-header__action-text">Run investigation</span>
        </button>
      )}
    </header>
  );
}

/**
 * This month's AI spend against its cap, the average per resolved case, and
 * the model doing the work — from /costs/summary and /health. Hidden when
 * either is unavailable rather than showing a guess.
 */
function CostPill({ productId, liveKey, onOpen }: {
  productId: number | null; liveKey: number; onOpen?: () => void;
}) {
  const { data: costs } = useAsync(() => api.costsSummary(), [productId, liveKey]);
  const { data: health } = useAsync(() => api.health(), []);
  if (!costs) return null;
  const spent = Number(costs.month_to_date ?? 0);
  const cap = Number(costs.budget ?? 0);
  const pct = cap > 0 ? Math.min(100, (spent / cap) * 100) : null;
  const perCase = Number(costs.stats?.avg_per_resolved ?? 0);
  const model = health?.model || null;
  const near = pct != null && pct >= 80;
  const title = [
    `AI spend this month: ${money(spent)}${cap > 0 ? ` of a ${money(cap)} cap (${Math.round(pct!)}%)` : ""}`,
    perCase > 0 ? `Average ${money(perCase)} per resolved case` : null,
    model ? `Model: ${model}` : null,
  ].filter(Boolean).join(". ") + ".";
  return (
    <button type="button" className={`el-cost-pill${near ? " is-near" : ""}`} onClick={onOpen}
            title={title} aria-label={title} disabled={!onOpen}>
      <span className="el-cost-pill__spend el-num">
        {money(spent)}{cap > 0 && <span className="el-cost-pill__cap"> / {money(cap)}</span>}
      </span>
      {pct != null && (
        <span className="el-cost-pill__meter" aria-hidden>
          <span style={{ width: `${pct}%` }} />
        </span>
      )}
      {perCase > 0 && <span className="el-cost-pill__per el-num">{money(perCase)}/case</span>}
      {model && <span className="el-cost-pill__model el-mono">{model}</span>}
    </button>
  );
}
