import { useState } from "react";
import { CaseRow, Evidence, Investigation, api, canReview, errorMessage } from "../../api";
import { withToast } from "../../components/Toast";
import { ReleaseChart } from "../../components/casefile";
import { useAsync } from "../../hooks";
import { Button } from "../../ui";
import { ProductDecisionCard, RecommendationRow, ShareCard } from "./CaseActions";
import { EngineeringTab } from "./EngineeringTab";
import { DecisionCard, FollowupCard, WhyNotPanel } from "./FindingTab";

/**
 * Everything the problem page keeps below the fold: the short decision with its
 * numbers, recommended actions, how complaints moved around the release, what
 * the team decided, sharing, the ticket and fix watch in full (with reply
 * drafts), causes ruled out, follow-up questions, and merging a duplicate.
 */
export function MoreTab({ inv, onReload, onGoPatterns, onOpenEvidence, onMerged }: {
  inv: Investigation;
  onReload: () => Promise<unknown> | void;
  onGoPatterns: () => void;
  onOpenEvidence: (e: Evidence) => void;
  onMerged: (id: number) => void;
}) {
  const f = inv.finding;
  const reviewer = canReview();
  const challenged = f?.status === "challenged";
  return (
    <div className="cv-more__stack">
      {f?.decision && (
        <section aria-label="In short">
          <h3>In short</h3>
          <DecisionCard decision={f.decision} impact={f.impact} severity={f.severity} />
        </section>
      )}
      {inv.recommendations.length > 0 && (
        <section aria-label="Recommended actions">
          <h3>Recommended actions</h3>
          {inv.recommendations.map((r) => (
            <RecommendationRow key={r.rank} rec={r} findingId={challenged || !f ? null : f.id} onReload={onReload} />
          ))}
        </section>
      )}
      <CaseChart inv={inv} />
      {f && (
        <section aria-label="Decision and sharing">
          <h3>Decide and share</h3>
          <ProductDecisionCard inv={inv} onReload={onReload} />
          <ShareCard inv={inv} />
        </section>
      )}
      {f && (
        <section aria-label="The ticket and the fix">
          <h3>The ticket, the fix, and replies to reviewers</h3>
          <EngineeringTab inv={inv} onReload={onReload} onGoPatterns={onGoPatterns} />
        </section>
      )}
      <WhyNotPanel inv={inv} onOpenEvidence={onOpenEvidence} />
      {f && reviewer && !challenged && (
        <section aria-label="Ask a follow-up">
          <FollowupCard findingId={f.id} addenda={f.addenda} onAdded={onReload} />
        </section>
      )}
      {reviewer && ["needs_review", "needs_human", "resolved", "regressed"].includes(inv.case_status)
        && !inv.product_decision?.hidden && (
        <section aria-label="Merge a duplicate">
          <h3>Is this a duplicate?</h3>
          <MergeAction caseId={inv.id} onMerged={onMerged} />
        </section>
      )}
    </div>
  );
}

/** The case's complaints per day, with the releases pinned. */
function CaseChart({ inv }: { inv: Investigation }) {
  const t = useAsync(() => api.timeline(30, inv.id), [inv.id]);
  if (t.error || !t.data) return null;
  const series = t.data.theme?.series ?? t.data.series;
  const points = series.map((d) => ({ date: d.date, value: t.data!.theme ? d.negative : d.one_star }));
  if (!points.some((p) => p.value > 0)) return null;
  return (
    <section aria-label="How complaints moved">
      <h3>How complaints moved</h3>
      <ReleaseChart points={points} releases={t.data.releases} minimal={false} height={180}
        unit={t.data.theme ? "matching complaints" : "1★ reviews"}
        ariaLabel={t.data.theme ? "Complaints matching this problem per day" : "One-star reviews per day"}
        caption={t.data.theme ? `Complaints mentioning ${t.data.theme.terms.join(", ")}, last ${t.data.days} days`
          : `1★ reviews per day, last ${t.data.days} days`} />
    </section>
  );
}

function MergeAction({ caseId, onMerged }: { caseId: number; onMerged: (id: number) => void }) {
  const [candidates, setCandidates] = useState<CaseRow[] | null>(null);
  const [target, setTarget] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const load = async () => {
    setBusy(true); setError(null);
    try {
      const view = await api.cases();
      setCandidates(view.cases.filter((c) => c.id != null && c.id !== caseId &&
        ["needs_review", "needs_human", "resolved", "regressed"].includes(c.status) && !c.decision?.hidden));
    } catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  };
  const merge = async () => {
    if (!target) return;
    setBusy(true);
    const result = await withToast(() => api.mergeCase(caseId, Number(target)), {
      success: "Merged — this problem's proof is linked to the other one as related.",
      failure: "Couldn't merge them",
    });
    setBusy(false);
    if (result) onMerged(result.merged_into_id);
  };
  if (candidates === null) {
    return <div><Button variant="ghost" size="sm" loading={busy} onClick={load}>Merge into another problem…</Button>
      {error && <div role="alert" style={{ fontSize: 14, marginTop: 8 }}>{error}</div>}</div>;
  }
  return (
    <div className="cv-card">
      <label className="cv-field"><span>Merge problem #{caseId} into</span>
        <select className="cv-input" value={target} disabled={busy} onChange={(e) => setTarget(e.target.value)}>
          <option value="">{candidates.length ? "Choose a problem" : "No other open problems"}</option>
          {candidates.map((c) => <option key={c.id} value={c.id!}>#{c.id} · {c.title}</option>)}
        </select>
      </label>
      <div style={{ fontSize: 13, color: "var(--el-muted)" }}>
        This one leaves the open lists. Its proof stays linked as related, and its links open the other problem.
      </div>
      {error && <div role="alert" style={{ fontSize: 14 }}>{error}</div>}
      <div className="cv-row">
        <Button variant="primary" size="sm" loading={busy} disabled={!target} onClick={merge}>Merge</Button>
        <Button variant="quiet" size="sm" onClick={() => setCandidates(null)}>Cancel</Button>
      </div>
    </div>
  );
}
