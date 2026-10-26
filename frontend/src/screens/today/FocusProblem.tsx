import { CaseRow, ComplaintTimeline, TodayFocus } from "../../api";
import { FocusCard, HighlightQuote, ReleaseChart, SerifHeadline, Stamp, StatTile, stampFor } from "../../components/casefile";
import { Button, Skeleton } from "../../ui";
import { plainWords } from "./model";

export function FocusProblem({ row, metrics, timeline, loading, onOpen, onTicket }: {
  row: CaseRow; metrics: TodayFocus | null; timeline: ComplaintTimeline | null; loading: boolean;
  onOpen: () => void; onTicket?: () => void;
}) {
  const verdict = stampFor(row);
  const share = metrics?.one_star_share;
  const release = metrics?.release;
  const drag = metrics?.rating_drag;
  const sources = row.trust?.distinct_sources ?? 0;
  const sourceLine = verdict === "hunch" ? "needs a second source"
    : verdict === "reopened" ? "the fix didn't hold"
    : sources >= 2 ? `${sources} sources agree` : "proof ready for your review";
  const points = (timeline?.series ?? []).map(p => ({ date:p.date, value:p.one_star }));
  const pins = release ? [{ version:release.version, date:release.date, kind:"release" as const }] : [];
  return <FocusCard className="today-focus" aria-label={`First problem: ${plainWords(row.title)}`}
    stamp={<Stamp variant={verdict} />} aside={<>
      <StatTile value={drag != null ? `${drag > 0 ? "−" : ""}${drag.toFixed(2)}★` : "—"} tone={drag && verdict !== "hunch" ? "problem" : "neutral"}
        caption={drag != null ? "estimated loss: last 7 days vs prior 28" : "Rating impact needs more reviews"} />
      <StatTile value={share?.pct != null ? `${share.pct}%` : "—"}
        caption={share?.pct != null ? `of ${share.total} one-star reviews in 30 days mention it` : "Too few one-star reviews to compare"} />
      {release ? <StatTile value={release.days_after === 0 ? "Same day" : `${release.days_after} ${release.days_after === 1 ? "day" : "days"}`}
        caption={release.days_after === 0 ? "the release and first complaint" : "after the update, the first complaint"} />
        : <StatTile value={share ? `${share.matching} ${share.matching === 1 ? "review" : "reviews"}` : "—"}
          caption={share ? `match it out of ${share.total} one-star reviews in 30 days` : "Review counts are not available yet"} />}
      {timeline ? <ReleaseChart points={points} releases={pins} unit="one-star reviews" ariaLabel="One-star reviews per day, last 30 days"
        caption={`1★ reviews per day, ${timeline.start} to ${timeline.end}`} />
        : <div className="today-chart-note" role="status">{loading ? <Skeleton rows={2} height={36} />
          : <p>Review history is unavailable. Open the proof for the stored reviews.</p>}</div>}
    </>}>
    <div className="today-focus__meta">Problem #{row.id} · {sourceLine}</div>
    <SerifHeadline as="h2" size="card">{plainWords(row.title)}</SerifHeadline>
    <p>{verdict === "hunch" ? "This is a hunch, with more proof needed. " : ""}
      {metrics?.quote ? <>One reviewer put it simply: <HighlightQuote>“{metrics.quote.text}”</HighlightQuote></>
        : "Open the proof to see what the sources say and decide what happens next."}</p>
    <div className="today-actions"><Button variant="primary" onClick={onOpen}>See the proof</Button>
      {onTicket && <Button onClick={onTicket}>Send to GitHub</Button>}</div>
  </FocusCard>;
}
