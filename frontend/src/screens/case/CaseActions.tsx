import { useEffect, useState } from "react";
import {
  Investigation, ProductDecision, ProductDecisionKind, Recommendation, ShareState, api,
  canReview, errorMessage, getActiveProduct
} from "../../api";
import { toast, withToast } from "../../components/Toast";
import { money, when } from "../../format";
import { C, R, S, T, mono } from "../../theme";
import { Button, Label, Rich } from "../../ui";

// v15: the single-case PM workflow — what the team decides to do about a
// finding, small corrections that don't throw the case away, more budget for a
// case that ran dry, and getting the answer in front of people who don't use
// EchoLens.

const DECISION_META: Record<ProductDecisionKind, { label: string; color: string; bg: string; line: string }> = {
  fix_now: { label: "Fix now", color: C.good, bg: C.goodBg, line: C.goodLine },
  park: { label: "Parked", color: C.info, bg: C.infoBg, line: C.infoLine },
  wont_fix: { label: "Won't fix", color: C.muted, bg: C.hover, line: C.border3 },
};

export function decisionLabel(d: ProductDecision): string {
  if (d.decision === "park") return d.revisit_by ? `Parked until ${d.revisit_by}` : "Parked";
  if (d.decision === "wont_fix") return d.reason ? `Won't fix — ${d.reason}` : "Won't fix";
  return DECISION_META[d.decision].label;
}

/** The product decision as a chip, for the case header. */
export function DecisionChip({ decision }: { decision: ProductDecision | null | undefined }) {
  if (!decision) return null;
  const m = DECISION_META[decision.decision];
  return (
    <span title={`Product decision${decision.at ? ` · set ${when(decision.at)}` : ""}${decision.reason ? ` — ${decision.reason}` : ""}`} style={{
      display: "inline-flex", alignItems: "center", gap: S[1], padding: `3px ${S[3]}`,
      borderRadius: R.pill, background: m.bg, border: `1px solid ${m.line}`, color: m.color,
      fontSize: T.sm, fontWeight: 500, maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis",
      whiteSpace: "nowrap" }}>
      {decisionLabel(decision)}
    </span>
  );
}

function todayPlus(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

/** Fix now / park / won't fix — what happens next, separate from "is it true?". */
export function ProductDecisionCard({ inv, onReload }: {
  inv: Investigation; onReload: () => Promise<unknown> | void;
}) {
  const f = inv.finding;
  const current = inv.product_decision ?? null;
  const [open, setOpen] = useState<ProductDecisionKind | null>(null);
  const [revisit, setRevisit] = useState(todayPlus(30));
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  if (!f || f.status === "challenged") return null;
  const reviewer = canReview();

  const save = async (decision: ProductDecisionKind | "cleared") => {
    if (decision === "wont_fix" && !reason.trim()) return;
    setBusy(true);
    const ok = await withToast(
      () => api.decideFinding(f.id, decision, decision === "park" ? revisit : null, reason.trim()),
      {
        success: decision === "fix_now" ? "Marked fix now — it goes into the plan first."
          : decision === "park" ? `Parked until ${revisit} — it leaves Top open problems until then.`
          : decision === "wont_fix" ? "Marked won't fix — it leaves the open lists."
          : "Decision cleared.",
        failure: "Couldn't save that decision"
      });
    setBusy(false);
    if (!ok) return;
    setOpen(null);
    setReason("");
    await onReload();
  };

  return (
    <div style={{ marginTop: S[6], padding: `${S[4]} ${S[5]}`, background: C.card,
                  border: `1px solid ${C.border2}`, borderRadius: R.card }}>
      <div style={{ display: "flex", alignItems: "center", gap: S[2], flexWrap: "wrap", marginBottom: S[2] }}>
        <Label>PRODUCT DECISION</Label>
        <DecisionChip decision={current} />
        {current?.at && <span style={{ fontFamily: mono, fontSize: T.micro, color: C.faint }}>{when(current.at)}</span>}
      </div>
      <div style={{ fontSize: T.sm, color: C.dim, lineHeight: "var(--el-lh-normal)", marginBottom: S[3] }}>
        Approve and Challenge say whether the finding is right. This says what the team will do
        about it — and keeps parked or won't-fix work out of Today and the Plan.
      </div>
      {!reviewer ? (
        <div style={{ fontSize: T.sm, color: C.faint }}>Recording a decision needs a reviewer role.</div>
      ) : (
        <>
          <div style={{ display: "flex", gap: S[2], flexWrap: "wrap" }}>
            <Button variant={current?.decision === "fix_now" ? "primary" : "ghost"} size="sm"
                    loading={busy && open === null} onClick={() => save("fix_now")}>
              Fix now
            </Button>
            <Button variant={open === "park" || current?.decision === "park" ? "primary" : "ghost"} size="sm"
                    aria-expanded={open === "park"} onClick={() => setOpen(open === "park" ? null : "park")}>
              Park…
            </Button>
            <Button variant={open === "wont_fix" || current?.decision === "wont_fix" ? "primary" : "ghost"} size="sm"
                    aria-expanded={open === "wont_fix"} onClick={() => setOpen(open === "wont_fix" ? null : "wont_fix")}>
              Won't fix…
            </Button>
            {current && (
              <Button variant="quiet" size="sm" onClick={() => save("cleared")}>Clear decision</Button>
            )}
          </div>
          {open === "park" && (
            <div style={{ display: "flex", gap: S[2], alignItems: "center", flexWrap: "wrap", marginTop: S[3] }}>
              <label style={{ fontSize: T.sm, color: C.muted }} htmlFor={`revisit-${f.id}`}>Revisit by</label>
              <input id={`revisit-${f.id}`} type="date" value={revisit} min={todayPlus(1)}
                onChange={(e) => setRevisit(e.target.value)}
                style={inputStyle} />
              <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Optional note"
                aria-label="Why it's parked" style={{ ...inputStyle, flex: 1, minWidth: 160 }} />
              <Button variant="primary" size="sm" loading={busy} onClick={() => save("park")}>Park it</Button>
            </div>
          )}
          {open === "wont_fix" && (
            <div style={{ display: "flex", gap: S[2], alignItems: "center", flexWrap: "wrap", marginTop: S[3] }}>
              <input value={reason} onChange={(e) => setReason(e.target.value)}
                placeholder="Reason (required) — e.g. by design, not worth the cost"
                aria-label="Why it won't be fixed" style={{ ...inputStyle, flex: 1, minWidth: 220 }} />
              <Button variant="primary" size="sm" loading={busy} disabled={!reason.trim()}
                      onClick={() => save("wont_fix")}>Mark won't fix</Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  background: C.bgRaised, border: `1px solid ${C.border3}`, borderRadius: R.control, color: C.text,
  fontFamily: "inherit", fontSize: T.sm, padding: `${S[1]} ${S[2]}`, minHeight: 30,
};

/** "Continue with more budget (+5 steps, ~$X)" on a case that ran dry. */
export function ExtendCard({ inv, onReload }: { inv: Investigation; onReload: () => Promise<unknown> | void }) {
  const [busy, setBusy] = useState(false);
  const x = inv.extension;
  if (!x || inv.status === "running") return null;
  if (!x.eligible && x.used === 0) return null;      // not a dead end — nothing to offer
  const reviewer = canReview();
  const go = async () => {
    setBusy(true);
    const ok = await withToast(() => api.extend(inv.id), {
      success: `Continuing with ${x.steps} more steps — follow it in the trace.`,
      failure: "Couldn't continue this case"
    });
    setBusy(false);
    if (ok) await onReload();
  };
  return (
    <div style={{ marginTop: S[4], padding: `${S[3]} ${S[4]}`, background: C.card,
                  border: `1px solid ${C.accentLine}`, borderRadius: R.card,
                  display: "flex", alignItems: "center", gap: S[3], flexWrap: "wrap" }}>
      <div style={{ flex: 1, minWidth: 220, fontSize: T.sm, color: C.text3, lineHeight: "var(--el-lh-normal)" }}>
        {x.eligible
          ? <>This case stopped before a cause cleared the evidence bar. It can pick up where it left
              off, with everything it already found. <span style={{ color: C.faint }}>
              {x.remaining} of 2 continuations left · {money(x.spent_usd)} spent so far.</span></>
          : x.reason}
      </div>
      {x.eligible && (reviewer ? (
        <Button variant="primary" size="sm" icon="play" loading={busy} onClick={go}>
          Continue with more budget (+{x.steps} steps, ~{money(x.estimate_usd)})
        </Button>
      ) : (
        <span style={{ fontSize: T.sm, color: C.faint }}>Continuing needs a reviewer role.</span>
      ))}
    </div>
  );
}

const LEVELS = ["LOW", "MED", "HIGH"] as const;

/** One recommended action, with reviewer-correctable impact/effort. */
export function RecommendationRow({ rec, findingId, onReload }: {
  rec: Recommendation; findingId: number | null; onReload: () => Promise<unknown> | void;
}) {
  const [editing, setEditing] = useState(false);
  const [impact, setImpact] = useState(rec.impact);
  const [effort, setEffort] = useState(rec.effort);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setImpact(rec.impact); setEffort(rec.effort); }, [rec.impact, rec.effort]);
  const can = canReview() && findingId != null;

  const save = async () => {
    if (findingId == null) return;
    const body: { impact?: string; effort?: string } = {};
    if (impact !== rec.impact) body.impact = impact;
    if (effort !== rec.effort) body.effort = effort;
    if (!body.impact && !body.effort) { setEditing(false); return; }
    setBusy(true);
    const ok = await withToast(() => api.editRecommendation(findingId, rec.rank, body), {
      success: "Estimate corrected — recorded for Calibration; the finding stands.",
      failure: "Couldn't save that correction"
    });
    setBusy(false);
    if (ok) { setEditing(false); await onReload(); }
  };

  return (
    <div style={{ display: "flex", alignItems: "center", gap: S[3], flexWrap: "wrap",
                  padding: `${S[3]} ${S[4]}`, background: C.card,
                  border: `1px solid ${C.border2}`, borderRadius: R.control }}>
      <div style={{ width: 26, height: 26, borderRadius: R.control, background: C.hover,
                    border: `1px solid ${C.border3}`, display: "flex", alignItems: "center",
                    justifyContent: "center", fontFamily: mono, fontSize: T.sm, color: C.accent, flex: "none" }}>
        {rec.rank}
      </div>
      <div style={{ flex: 1, fontSize: T.base, fontWeight: 500, minWidth: 160 }}><Rich text={rec.action} /></div>
      {editing ? (
        <span style={{ display: "inline-flex", gap: S[2], alignItems: "center", flexWrap: "wrap" }}>
          <LevelSelect label="Impact" value={impact} onChange={setImpact} />
          <LevelSelect label="Effort" value={effort} onChange={setEffort} />
          <Button variant="primary" size="sm" loading={busy} onClick={save}>Save</Button>
          <Button variant="quiet" size="sm" onClick={() => { setEditing(false); setImpact(rec.impact); setEffort(rec.effort); }}>
            Cancel
          </Button>
        </span>
      ) : (
        <>
          <Tag color={C.good}>{rec.impact} impact</Tag>
          <Tag color={C.muted}>{rec.effort} effort</Tag>
          {can && (
            <Button variant="quiet" size="sm" onClick={() => setEditing(true)}
                    aria-label={`Correct impact or effort for action ${rec.rank}`}>
              Correct
            </Button>
          )}
        </>
      )}
    </div>
  );
}

function LevelSelect({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <label style={{ display: "inline-flex", alignItems: "center", gap: S[1], fontSize: T.xs, color: C.muted }}>
      {label}
      <select value={value} onChange={(e) => onChange(e.target.value)} style={inputStyle}>
        {LEVELS.map((l) => <option key={l} value={l}>{l}</option>)}
      </select>
    </label>
  );
}

function Tag({ children, color }: { children: React.ReactNode; color: string }) {
  return (
    <span style={{ fontFamily: mono, fontSize: T.micro, padding: `${S[1]} ${S[2]}`, borderRadius: R.sm,
                   background: `${color}1a`, color, border: `1px solid ${color}4d`,
                   whiteSpace: "nowrap" }}>
      {children}
    </span>
  );
}

/** The app URL for a hash route, from wherever the app is being served. */
function appUrl(hash: string): string {
  // From the site root: the app uses clean paths now, and main.tsx turns a
  // root hash link into the matching path.
  return `${window.location.origin}/${hash}`;
}

export function shareUrl(s: ShareState): string | null {
  if (!s.active || !s.token) return null;
  return s.url ?? appUrl(`#/share/${s.token}`);
}

async function copy(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

/** Copy a Slack/Notion-ready brief; mint or revoke a read-only public link. */
export function ShareCard({ inv }: { inv: Investigation }) {
  const f = inv.finding;
  const reviewer = canReview();
  const [share, setShare] = useState<ShareState | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [shareError, setShareError] = useState<string | null>(null);

  useEffect(() => {
    if (!f || !reviewer) return;
    let alive = true;
    api.shareState(f.id).then((s) => alive && setShare(s))
      .catch((e) => alive && setShareError(errorMessage(e)));
    return () => { alive = false; };
  }, [f?.id, reviewer]);

  if (!f || f.status === "challenged") return null;
  const link = share ? shareUrl(share) : null;

  const copyBrief = async () => {
    setBusy("brief");
    try {
      const pid = getActiveProduct();
      const back = link ?? appUrl(`#${pid != null ? `/p/${pid}` : ""}/cases/${inv.id}`);
      const brief = await api.findingBrief(f.id, back);
      if (await copy(brief.markdown)) toast.ok("Brief copied — paste it into Slack or Notion.");
      else toast.fail("Your browser blocked the clipboard. Try again from this tab.");
    } catch (e) {
      toast.fail(`Couldn't build the brief — ${errorMessage(e)}`);
    }
    setBusy(null);
  };

  const create = async () => {
    setBusy("create");
    const s = await withToast(() => api.createShare(f.id), {
      success: "Read-only link created. Anyone with it can read this brief — nothing else.",
      failure: "Couldn't create a link"
    });
    setBusy(null);
    if (!s) return;
    setShare(s);
    const url = shareUrl(s);
    if (url) await copy(url);
  };

  const revoke = async () => {
    setBusy("revoke");
    const s = await withToast(() => api.revokeShare(f.id), {
      success: "Link revoked — it no longer opens.",
      failure: "Couldn't revoke the link"
    });
    setBusy(null);
    if (s) setShare(s);
  };

  return (
    <div style={{ marginTop: S[4], padding: `${S[4]} ${S[5]}`, background: C.card,
                  border: `1px solid ${C.border2}`, borderRadius: R.card }}>
      <Label style={{ marginBottom: S[2] }}>SHARE</Label>
      <div style={{ display: "flex", gap: S[2], flexWrap: "wrap", alignItems: "center" }}>
        <Button variant="ghost" size="sm" loading={busy === "brief"} onClick={copyBrief}>
          Copy brief
        </Button>
        {reviewer && !link && (
          <Button variant="ghost" size="sm" loading={busy === "create"} onClick={create}
                  disabled={share === null && !shareError}>
            Create read-only link
          </Button>
        )}
        {reviewer && link && (
          <>
            <Button variant="ghost" size="sm" onClick={async () => {
              if (await copy(link)) toast.ok("Link copied.");
            }}>Copy link</Button>
            <Button variant="danger" size="sm" loading={busy === "revoke"} onClick={revoke}>Revoke link</Button>
          </>
        )}
      </div>
      {link && (
        <div style={{ marginTop: S[2], fontFamily: mono, fontSize: T.xs, color: C.dim, overflowWrap: "anywhere" }}>
          {link}
        </div>
      )}
      <div style={{ marginTop: S[2], fontSize: T.xs, color: C.faint, lineHeight: "var(--el-lh-normal)" }}>
        The brief has the headline, impact, a few user quotes and the actions — no internal ids.
        {reviewer ? " A link shows only that brief, needs no login, and stops working when revoked." : ""}
        {shareError ? ` (${shareError})` : ""}
      </div>
    </div>
  );
}
