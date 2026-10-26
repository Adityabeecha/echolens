import { CaseRow, Freshness, Overview, PortfolioProduct, Snapshot, WeeklyBrief } from "../../api";
import { ago, plural } from "../../format";
import { Button, RatingTrend } from "../../ui";
import { plainWords } from "./model";

export function WeeklyUpdate({ brief, error, onRetry, onOpen, spikes = 0 }: {
  brief: WeeklyBrief | null; error: string | null; onRetry: () => void; onOpen: (id: number) => void;
  /** Spikes waiting: the brief covers proven problems only, so "quiet week"
   *  under "EchoLens found two spikes" contradicted the page. */
  spikes?: number;
}) {
  const quiet = spikes > 0
    ? `no problems proven yet — ${spikes} ${plural(spikes, "spike")} waiting above`
    : "quiet week — nothing new";
  return <details className="today-details"><summary>This week · {error ? "couldn't load the update"
    : brief?.quiet ? quiet : brief?.new_problems.length ? `${brief.new_problems.length} new ${plural(brief.new_problems.length, "problem")}` : "your weekly brief"}</summary>
    {error ? <p className="today-muted">The weekly update couldn't be loaded. <Button variant="quiet" onClick={onRetry}>Try again</Button></p>
      : !brief ? <p className="today-muted">Reading this week's update…</p>
      : brief.quiet ? <p className="today-muted">{spikes > 0
          ? "Nothing has been investigated and proven this week yet. Pick a spike above and EchoLens will look into it."
          : "Quiet week — nothing new. EchoLens is still checking connected sources for new complaints and fixes."}</p>
      : brief.lines.length > 0 ? <div className="today-brief">
        <p className="today-muted">Updated {new Date(brief.generated).toLocaleDateString(undefined, { month:"long", day:"numeric" })}</p>
        {brief.lines.map((line, i) => <p key={i}>{line.split(/(case #\d+)/gi).map((part, j) => {
          const match = /^case #(\d+)$/i.exec(part);
          return match ? <Button key={j} variant="quiet" onClick={() => onOpen(Number(match[1]))}>problem #{match[1]}</Button>
            : <span key={j}>{plainWords(part)}</span>;
        })}</p>)}</div>
      : <p className="today-muted">No weekly update yet. Your new problems and checked fixes will appear here.</p>}
  </details>;
}

export function HealthDetails({ product, snapshot, overview, onOpen }: {
  product: PortfolioProduct | null; snapshot: Snapshot | null; overview: Overview | null; onOpen: (id: number) => void;
}) {
  const breakdown = overview?.rating_breakdown;
  return <details className="today-details"><summary>Why health is {product?.has_data ? `${product.health}/100` : "waiting for reviews"} · higher is healthier</summary>
    <div className="today-health">
      {!product ? <p className="today-muted">Health isn't available yet. Check your sources and try again.</p>
        : !product.has_data ? <p className="today-muted">Connect feedback so EchoLens can measure how your product is doing.</p>
        : <><p className="today-muted">{product.reasons.length ? product.reasons.slice(0, 3).map(r => plainWords(r.text)).join("; ") : "No unfixed high-severity problems or new review spikes are pushing health down."}</p>
          {product.top_problem && <Button variant="quiet" onClick={() => onOpen(product.top_problem!.investigation_id)}>
            Top problem in health: {plainWords(product.top_problem.summary)}</Button>}
          {snapshot && snapshot.weekly.length > 0 && <div><RatingTrend weekly={snapshot.weekly}
            releases={overview?.releases ?? []} color="var(--el-ink)" width={240} height={48}
            title={`Average rating over ${snapshot.weekly.length} weeks; higher is better`} /><span className="today-muted">Average rating over {snapshot.weekly.length} weeks · higher is better</span></div>}
          {breakdown && <>
            <p className="today-muted">{breakdown.delta != null ? `Rating ${breakdown.delta >= 0 ? "rose" : "fell"} ${Math.abs(breakdown.delta).toFixed(2)} stars: ${breakdown.rating_prior?.toFixed(2)} → ${breakdown.rating_now?.toFixed(2)}, last ${breakdown.window.recent_days} days vs prior ${breakdown.window.prior_days}.` : breakdown.reason ?? "More reviews are needed for a rating comparison."}</p>
            {breakdown.parts.map((p, i) => <div className="today-health__part" key={`${p.theme_id}-${i}`}>
              {p.case_id != null ? <Button variant="quiet" onClick={() => onOpen(p.case_id!)}>{plainWords(p.label)} · problem #{p.case_id}</Button> : <strong>{plainWords(p.label)}</strong>}
              <span>{p.contribution > 0 ? "+" : ""}{p.contribution.toFixed(2)}★ {p.contribution < 0 ? "worse" : "better"}</span>
            </div>)}
            {breakdown.parts.length > 0 && <p className="today-muted">Estimated contributions to the rating change. Reviews can describe more than one problem; these grouped parts add up to the overall change.</p>}
          </>}
        </>}
    </div>
  </details>;
}

export function CollectionNote({ freshness, staleCount, collecting, onCollect, onSources }: {
  freshness?: Freshness; staleCount: number; collecting: boolean; onCollect?: () => void; onSources: () => void;
}) {
  if (!freshness?.sources && !staleCount) return null;
  return <div className="today-context-line"><span>
    {freshness?.last_synced_at ? `Last collected ${ago(freshness.age_minutes)}` : "No collection has finished yet."}
    {staleCount > 0 && ` · ${staleCount} feedback ${plural(staleCount, "source")} ${staleCount === 1 ? "needs" : "need"} attention`}
  </span>
    {(freshness?.stale || staleCount > 0) && <>
      <Button variant="quiet" onClick={onSources}>Review sources</Button>
      {onCollect && <Button loading={collecting} onClick={onCollect}>Collect now</Button>}
    </>}
  </div>;
}

export function QueuedWork({ rows, busy, onCancel, onCases }: {
  rows: CaseRow[]; busy: number | null; onCancel?: (row: CaseRow) => void; onCases: () => void;
}) {
  if (!rows.length) return null;
  return <details className="today-details"><summary>{rows.length} {plural(rows.length, "investigation")} waiting to start</summary>
    {rows.map(row => <div className="today-queued" key={row.queue_id}>
      <span>{plainWords(row.title)}{row.position ? ` · position ${row.position}` : ""}
        {row.deferred && " · waiting for daily capacity"}</span>
      {onCancel && row.queue_id != null && <Button variant="quiet" loading={busy === row.queue_id} onClick={() => onCancel(row)}>Cancel</Button>}
    </div>)}<Button variant="quiet" onClick={onCases}>See the full queue</Button>
  </details>;
}
