import { useState } from "react";
import { ConfirmedFix, FixWatchRow, api, canReview, getActiveProduct, isGuest } from "../../api";
import { GoodNewsCard, ListRow } from "../../components/casefile";
import { withToast } from "../../components/Toast";
import { formatRoute } from "../../nav";
import { BeforeAfterChart, Button } from "../../ui";
import { fixSentence, fixTitle, fixTopic, watchProgress } from "./model";

export function openEngineering(id: number, replies = false) {
  window.location.hash = formatRoute({ screen:"case", id, productId:getActiveProduct(), tab:"engineering",
    params:replies ? { replies:"1" } : undefined });
}

export function GoodNews({ fixes, watches, onOpen, onReload }: {
  fixes: ConfirmedFix[]; watches: FixWatchRow[]; onOpen: (id: number, status?: string) => void; onReload: () => void;
}) {
  const recent = new Set(fixes.map(f => f.watch_id));
  const older = watches.filter(w => w.status === "confirmed" && !w.dismissed_today && !recent.has(w.id));
  const active = watches.filter(w => ["issue_open", "watching", "waiting_for_release", "inconclusive"].includes(w.status));
  return <div className="today-stack">
    {fixes.map(f => <ConfirmedCard key={f.watch_id} fix={f} onOpen={onOpen} onReload={onReload} />)}
    {active.map(w => <div key={w.id} className="today-watch">
      <Button variant="quiet" onClick={() => onOpen(w.investigation_id, "resolved")}>
        Checking your {fixTopic(w.metric)} fix</Button><span> · {w.status === "inconclusive" ? "the result needs your review" : watchProgress(w)}</span>
    </div>)}
    {older.length > 0 && <details className="today-details"><summary>{older.length} earlier {older.length === 1 ? "fix that worked" : "fixes that worked"}</summary>
      {older.map(w => <ListRow key={w.id} variant="fixWorked" title={fixTopic(w.metric)} detail={fixSentence(w)}
        onClick={() => onOpen(w.investigation_id, "verified_fixed")} />)}</details>}
    {fixes.length + active.length + older.length === 0 && <p className="today-muted">
      No fixes being checked yet. When a fix ships, mark it on the problem and EchoLens will watch the reviews.</p>}
  </div>;
}

function ConfirmedCard({ fix, onOpen, onReload }: {
  fix: ConfirmedFix; onOpen: (id: number, status?: string) => void; onReload: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [hidden, setHidden] = useState(false);
  const dismiss = async () => {
    setBusy(true);
    const result = await withToast(() => api.dismissFix(fix.watch_id), {
      success:"Hidden from your Today. The fix stays in What we've learned.", failure:"Couldn't hide this fix",
    });
    setBusy(false);
    if (result) { setHidden(true); onReload(); }
  };
  if (hidden) return null;
  return <GoodNewsCard title={fixTitle(fix.metric)} action={<div className="today-actions">
    {fix.reply_count > 0 && <Button variant="primary" onClick={() => openEngineering(fix.investigation_id, true)}>
      Write to the {fix.reply_count} {fix.reply_count === 1 ? "reviewer" : "reviewers"}</Button>}
    <Button variant="quiet" onClick={() => onOpen(fix.investigation_id, "verified_fixed")}>See the proof</Button>
    {canReview() && !isGuest() && <Button variant="quiet" loading={busy} onClick={dismiss}>Dismiss</Button>}
  </div>}>
    <p className="today-fix-sentence">{fixSentence(fix)}</p>
    {fix.chart && <details className="today-fix-chart"><summary>Compare complaints before and after</summary>
      <BeforeAfterChart chart={fix.chart} compact /></details>}
  </GoodNewsCard>;
}
