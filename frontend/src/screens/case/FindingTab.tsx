import { useState } from "react";
import { Decision, Evidence, Impact, Investigation, Severity, api, canReview } from "../../api";
import { withToast } from "../../components/Toast";
import { pct } from "../../format";
import { SEVERITY } from "../../status";
import { C, MEASURE, R, S, T, mono } from "../../theme";
import { EmptyState, Label } from "../../ui";
import { Icon } from "../../components/Icon";

interface Props {
  inv: Investigation;
  onOpenEvidence: (e: Evidence) => void;
  onOpenTrace: () => void;
  onOpenCase: (id: number, status?: string) => void;
  onReload: () => Promise<unknown> | void;
  onReviewed: () => void;
}

/** Render prose, turning [ev_00x] citations into clickable superscripts. */
function Prose({ text, evidence, onOpenEvidence }: {
  text: string; evidence: Evidence[]; onOpenEvidence: (e: Evidence) => void;
}) {
  return (
    <>
      {text.split(/(\[ev_\d+\])/g).map((p, i) => {
        const m = p.match(/^\[(ev_\d+)\]$/);
        if (!m) return <span key={i}>{p}</span>;
        const ev = evidence.find((e) => e.id === m[1]);
        return (
          <sup key={i} onClick={() => ev && onOpenEvidence(ev)}
            style={{ fontFamily: mono, fontSize: T.micro, color: C.accent,
                     padding: `0 ${S[1]}`, background: C.accentBg, borderRadius: R.sm,
                     marginLeft: 2 }}>
            {m[1]}
          </sup>
        );
      })}
    </>
  );
}

/** The answer: what's broken, how bad, what to do — and your verdict on it. */
export function FindingTab({
  inv, onOpenEvidence, onOpenTrace, onOpenCase, onReload, onReviewed
}: Props) {
  const [challengeOpen, setChallengeOpen] = useState(false);
  const [note, setNote] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  const f = inv.finding;
  if (!f) {
    return (
      <div style={{ flex: 1, overflow: "auto", padding: `${S[6]} ${S[6]}` }}>
        <EmptyState
          title={`No answer yet for case #${inv.id}`}
          body={
            inv.status === "running"
              ? "It's still investigating — the reasoning is streaming live on the Investigation trace tab."
              : "This case ended without a drafted finding. The trace shows exactly what was checked and where it stopped."
          }
          action="See the investigation trace"
          onAction={onOpenTrace}
        />
      </div>
    );
  }

  const approved = f.status === "approved";
  const challenged = f.status === "challenged";
  const reviewer = canReview();

  const approve = async () => {
    setBusy(true);
    const ok = await withToast(() => api.review(f.id, "approve"), {
      success: "Finding approved — the case is now Resolved.",
      failure: "Couldn't approve that finding"
    });
    setBusy(false);
    if (ok) { await onReload(); onReviewed(); }
  };

  const submitChallenge = async () => {
    if (!note.trim()) return;
    setBusy(true);
    const r = await withToast(
      () => api.review(f.id, "challenge", note, reason || undefined),
      { success: "Challenge recorded — a fresh case is re-investigating with your note.",
        failure: "Couldn't submit that challenge" });
    setBusy(false);
    if (!r) return;
    setChallengeOpen(false);
    setNote("");
    setReason("");
    onReviewed();
    await onReload();
    if (r.reopened_investigation_id) onOpenCase(r.reopened_investigation_id, "running");
  };

  return (
    <div style={{ flex: 1, overflow: "auto" }}>
      <div style={{ maxWidth: MEASURE, padding: `${S[6]} ${S[6]} ${S[12]}` }}>
        {challenged && (
          <Banner color={C.accent}>
            You challenged this finding. A fresh case is addressing it — see History for the link.
          </Banner>
        )}

        {f.grounding_violations && f.grounding_violations.length > 0 && (
          <div style={{ marginBottom: S[4], padding: `${S[3]} ${S[4]}`,
                        border: `1px solid ${C.bad}66`, background: `${C.bad}12`,
                        borderRadius: R.control, maxWidth: 720 }}>
            <Label style={{ color: C.bad, marginBottom: S[2] }}>
              CLAIM-GROUNDING GUARD BLOCKED THIS DRAFT
            </Label>
            <div style={{ fontSize: T.base, color: C.text3, lineHeight: "var(--el-lh-normal)" }}>
              EchoLens drafted a cause but could not tie{" "}
              {f.grounding_violations.length === 1 ? "one sentence" : "some sentences"} to specific
              evidence, so the draft is not being shown as a conclusion. This is the honesty rule
              working, not a failure — treat the evidence below as what was actually established.
            </div>
            {f.rejected_draft && (
              <details style={{ marginTop: S[2] }}>
                <summary style={{ fontSize: T.sm, color: C.muted }}>
                  Show the rejected draft (for audit — not a finding)
                </summary>
                <div style={{ fontSize: T.sm, color: C.dim, marginTop: S[2], lineHeight: "var(--el-lh-normal)",
                              fontStyle: "italic", paddingLeft: 10,
                              borderLeft: `2px solid ${C.bad}44` }}>
                  {f.rejected_draft}
                </div>
              </details>
            )}
          </div>
        )}

        {inv.data_notes && inv.data_notes.length > 0 && (
          <div style={{ marginBottom: S[4], padding: `${S[3]} ${S[4]}`, border: `1px solid ${C.bad}44`,
                        background: `${C.bad}12`, borderRadius: R.control }}>
            <Label style={{ color: C.bad, marginBottom: S[1] }}>DATA AVAILABILITY</Label>
            {inv.data_notes.map((n, i) => (
              <div key={i} style={{ fontSize: T.sm, color: C.text3, lineHeight: "var(--el-lh-normal)" }}>{n}</div>
            ))}
          </div>
        )}

        {f.decision && (
          <DecisionCard decision={f.decision} impact={f.impact} severity={f.severity} />
        )}

        <div style={{ padding: `${S[5]} ${S[6]}`, background: C.card, border: `1px solid ${C.border2}`,
                      borderRadius: R.card }}>
          <Label style={{ letterSpacing: ".12em", marginBottom: S[3] }}>FINDING</Label>
          <div style={{ fontSize: T.xl, fontWeight: 700, lineHeight: "var(--el-lh-snug)",
                        letterSpacing: "-.01em" }}>
            {f.summary}
          </div>
          <div style={{ fontSize: T.md, lineHeight: "var(--el-lh-normal)", color: C.text3, marginTop: S[3] }}>
            <Prose text={f.prose} evidence={inv.evidence} onOpenEvidence={onOpenEvidence} />
          </div>
          {inv.status !== "resolved" && f.what_would_settle_it && (
            <div style={{ marginTop: S[3], fontSize: T.sm, color: C.muted, lineHeight: "var(--el-lh-normal)" }}>
              <span style={{ color: C.text3 }}>What would settle it:</span> {f.what_would_settle_it}
            </div>
          )}
          <button onClick={onOpenTrace} className="el-btn"
            style={{ marginTop: S[4], fontSize: T.sm, color: C.dim }}>
            See how we got here →
          </button>
        </div>

        {inv.recommendations.length > 0 && (
          <>
            <Label style={{ margin: "26px 0 10px" }}>RECOMMENDED ACTIONS</Label>
            <div style={{ display: "flex", flexDirection: "column", gap: S[2] }}>
              {inv.recommendations.map((ac) => (
                <div key={ac.rank} style={{ display: "flex", alignItems: "center", gap: S[3],
                                            padding: `${S[3]} ${S[4]}`, background: C.card,
                                            border: `1px solid ${C.border2}`, borderRadius: R.control }}>
                  <div style={{ width: 26, height: 26, borderRadius: R.control, background: C.hover,
                                border: `1px solid ${C.border3}`, display: "flex",
                                alignItems: "center", justifyContent: "center", fontFamily: mono,
                                fontSize: T.sm, color: C.accent, flex: "none" }}>
                    {ac.rank}
                  </div>
                  <div style={{ flex: 1, fontSize: T.base, fontWeight: 500 }}>{ac.action}</div>
                  <Tag color={C.good}>{ac.impact} impact</Tag>
                  <Tag color={C.muted}>{ac.effort} effort</Tag>
                </div>
              ))}
            </div>
          </>
        )}

        <WhyNotPanel inv={inv} onOpenEvidence={onOpenEvidence} />

        {reviewer && <FollowupCard findingId={f.id} addenda={f.addenda} onAdded={onReload} />}

        {approved && (
          <Banner color={C.good} style={{ marginTop: S[6], marginBottom: 0 }}>
            <Icon name="check" size={14} style={{ display: "inline", verticalAlign: "-2px" }} /> You approved this finding. It stays under Resolved until a fix is verified.
          </Banner>
        )}

        {!approved && !challenged && !reviewer && (
          <div style={{ marginTop: S[6], fontSize: T.sm, color: C.faint }}>
            You have viewer access — approving or challenging findings needs a reviewer role.
          </div>
        )}

        {!approved && !challenged && reviewer && (
          <div style={{ display: "flex", gap: S[3], marginTop: S[6], alignItems: "flex-start" }}>
            <button onClick={approve} disabled={busy} className="el-btn el-btn--primary"
              style={{ padding: `${S[3]} ${S[6]}`, borderRadius: R.control, border: "none", background: C.accent,
                       color: C.onAccent, fontSize: T.md, fontWeight: 600,
                       cursor: busy ? "wait" : "pointer" }}>
              {busy ? "Saving…" : "Approve finding"}
            </button>
            <div style={{ display: "flex", flexDirection: "column", gap: S[1] }}>
              <button onClick={() => setChallengeOpen((o) => !o)} className="el-btn"
                style={{ padding: `${S[3]} ${S[6]}`, borderRadius: R.control, border: `1px solid ${C.border4}`,
                         background: "transparent", color: C.text, fontSize: T.md, fontWeight: 500 }}>
                Challenge
              </button>
              <span style={{ fontSize: T.xs, color: C.faint }}>
                challenging re-opens the investigation with your note
              </span>
            </div>
          </div>
        )}

        {challengeOpen && (
          <div style={{ marginTop: S[3], padding: 16, background: C.card,
                        border: `1px solid ${C.border2}`, borderRadius: R.card, maxWidth: 560 }}>
            <div style={{ fontSize: T.sm, color: C.muted, marginBottom: S[2] }}>
              What's wrong with this finding? Your reason rolls up into Calibration and steers
              future investigations.
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: S[2], marginBottom: S[2] }}>
              {[
                ["wrong_cause", "Wrong root cause"],
                ["weak_evidence", "Evidence too weak"],
                ["wrong_severity", "Severity/impact off"],
                ["already_knew", "Already knew this"],
              ].map(([val, label]) => (
                <button key={val} onClick={() => setReason((r) => (r === val ? "" : val))}
                  className="el-btn"
                  style={{ fontSize: T.sm, padding: `${S[1]} ${S[3]}`, borderRadius: R.pill,
                           border: `1px solid ${reason === val ? C.accent : C.border3}`,
                           background: reason === val ? C.accentBg : "transparent",
                           color: reason === val ? C.accent : C.muted }}>
                  {label}
                </button>
              ))}
            </div>
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="e.g. Battery complaints also mention charging speed — check charger-related reviews before pinning this on sync."
              style={{ width: "100%", height: 76, background: C.bgRaised,
                       border: `1px solid ${C.border3}`, borderRadius: R.control, color: C.text,
                       fontFamily: "inherit", fontSize: T.base, padding: 10, resize: "vertical",
                       boxSizing: "border-box" }}
            />
            <button onClick={submitChallenge} disabled={!note.trim() || busy} className="el-btn el-btn--primary"
              style={{ marginTop: S[2], padding: `${S[2]} ${S[4]}`, borderRadius: R.control, border: "none",
                       background: C.accent, color: C.onAccent, fontSize: T.base, fontWeight: 600,
                       cursor: note.trim() && !busy ? "pointer" : "not-allowed",
                       opacity: note.trim() ? 1 : 0.45 }}>
              Submit &amp; re-open investigation
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

/** The three questions a PM asks, answered above the fold. */
function DecisionCard({ decision, impact, severity }: {
  decision: Decision; impact?: Impact; severity?: Severity;
}) {
  const sevColor = severity ? SEVERITY[severity.band]?.color ?? C.muted : C.muted;
  const rows: [string, string][] = [
    ["What's broken", decision.whats_broken],
    ["How bad", decision.how_bad],
    ["What to do", decision.what_to_do],
  ];
  return (
    <div style={{ marginBottom: S[4], padding: `${S[5]} ${S[5]}`, background: C.card,
                  border: `1px solid ${C.border3}`, borderRadius: R.card }}>
      <div style={{ display: "flex", alignItems: "center", gap: S[2], marginBottom: S[3] }}>
        <Label style={{ letterSpacing: ".12em", color: C.accent }}>DECISION</Label>
        {severity && (
          <span style={{ fontFamily: mono, fontSize: T.micro, padding: `${S[1]} ${S[2]}`, borderRadius: R.sm,
                         background: `${sevColor}1f`, border: `1px solid ${sevColor}66`,
                         color: sevColor, textTransform: "uppercase" }}>
            {severity.band} severity · {severity.score.toFixed(2)}
          </span>
        )}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: S[3] }}>
        {rows.map(([q, a]) => (
          <div key={q} style={{ display: "grid", gridTemplateColumns: "108px 1fr", gap: S[3],
                                alignItems: "baseline" }}>
            <div style={{ fontFamily: mono, fontSize: T.xs, color: C.faint,
                          textTransform: "uppercase", letterSpacing: ".06em" }}>{q}</div>
            <div style={{ fontSize: T.md, color: C.text2, lineHeight: "var(--el-lh-normal)" }}>{a || "—"}</div>
          </div>
        ))}
      </div>
      {impact && (impact.affected_volume > 0 || impact.rating_impact > 0) && (
        <div style={{ display: "flex", gap: S[2], flexWrap: "wrap", marginTop: S[4] }}>
          <ImpactStat label="AFFECTED" value={pct(impact.affected_pct)}
                      sub={`${impact.affected_volume} reviews / 7d`} />
          <ImpactStat label="RATING IMPACT" value={`${impact.rating_impact.toFixed(2)}★`}
                      sub="est. lost vs baseline"
                      color={impact.rating_impact > 0 ? C.bad : C.muted} />
          {impact.blast_radius.top_cohort && impact.blast_radius.top_cohort !== "unknown" && (
            <ImpactStat
              label="BLAST RADIUS"
              value={impact.blast_radius.top_cohort}
              sub={impact.blast_radius.exclusive ? "exclusive to cohort"
                : impact.blast_radius.ratio ? `${impact.blast_radius.ratio}× next version`
                  : "top cohort"} />
          )}
        </div>
      )}
    </div>
  );
}

/** The hypotheses ruled out, with the evidence that killed them. */
function WhyNotPanel({ inv, onOpenEvidence }: {
  inv: Investigation; onOpenEvidence: (e: Evidence) => void;
}) {
  const rejected = inv.hypotheses.filter((h) => h.status === "rejected");
  if (rejected.length === 0) return null;
  const byId = new Map(inv.evidence.map((e) => [e.id, e]));
  return (
    <>
      <Label style={{ margin: "26px 0 10px" }}>WHY NOT? · {rejected.length} RULED OUT</Label>
      <div style={{ display: "flex", flexDirection: "column", gap: S[2] }}>
        {rejected.map((h) => {
          const killers = h.evidence_against.map((id) => byId.get(id))
            .filter((e): e is Evidence => !!e);
          return (
            <div key={h.id} style={{ padding: `${S[3]} ${S[4]}`, background: C.card,
                                     border: `1px solid ${C.border2}`, borderRadius: R.card }}>
              <div style={{ display: "flex", alignItems: "center", gap: S[2], marginBottom: S[2],
                            flexWrap: "wrap" }}>
                <span style={{ fontFamily: mono, fontSize: T.xs, color: C.bad }}>{h.id}</span>
                <span style={{ fontFamily: mono, fontSize: T.micro, padding: `0 ${S[2]}`,
                               borderRadius: R.sm, background: `${C.bad}1f`, color: C.bad,
                               textTransform: "uppercase" }}>
                  ruled out
                </span>
                <span style={{ fontSize: T.base, color: C.text3, textDecoration: "line-through",
                               textDecorationColor: C.ghost }}>
                  {h.statement}
                </span>
              </div>
              {killers.length > 0 ? (
                <div style={{ display: "flex", flexDirection: "column", gap: S[1] }}>
                  {killers.map((e) => (
                    <div key={e.id} onClick={() => onOpenEvidence(e)}
                      style={{ fontSize: T.sm, color: C.text3, lineHeight: "var(--el-lh-snug)",
                               borderLeft: `2px solid ${C.bad}66`, paddingLeft: 10 }}>
                      <span style={{ fontFamily: mono, fontSize: T.micro, color: C.bad,
                                     marginRight: 6 }}>{e.id}</span>“{e.snippet}”
                    </div>
                  ))}
                </div>
              ) : (
                <div style={{ fontSize: T.sm, color: C.faint }}>
                  Rejected as the leading cause was corroborated instead.
                </div>
              )}
            </div>
          );
        })}
      </div>
    </>
  );
}

/** Ask a targeted follow-up; the answer is appended as an addendum. */
function FollowupCard({ findingId, addenda, onAdded }: {
  findingId: number;
  addenda?: { question: string; answer: string; dimension: string }[];
  onAdded: () => Promise<unknown> | void;
}) {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const ask = async () => {
    if (!q.trim() || busy) return;
    setBusy(true);
    const ok = await withToast(() => api.findingFollowup(findingId, q.trim()), {
      success: "Answered — added below as an addendum.",
      failure: "Couldn't answer that follow-up"
    });
    setBusy(false);
    if (ok) { setQ(""); await onAdded(); }
  };
  return (
    <div style={{ marginTop: S[6] }}>
      <Label style={{ marginBottom: S[2] }}>FOLLOW-UP</Label>
      {addenda && addenda.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: S[2], marginBottom: S[3] }}>
          {addenda.map((a, i) => (
            <div key={i} style={{ padding: `${S[3]} ${S[4]}`, background: C.card,
                                  border: `1px solid ${C.border2}`, borderRadius: R.card }}>
              <div style={{ fontSize: T.base, fontWeight: 600, color: C.text2 }}>{a.question}</div>
              <div style={{ fontSize: T.base, color: C.text3, marginTop: S[1], lineHeight: "var(--el-lh-normal)" }}>
                {a.answer}
              </div>
            </div>
          ))}
        </div>
      )}
      <div style={{ display: "flex", gap: S[2], maxWidth: 560 }}>
        <input value={q} onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && ask()}
          placeholder="Does this affect iOS too? Which version?"
          style={{ flex: 1, background: C.bgRaised, border: `1px solid ${C.border3}`,
                   borderRadius: R.control, color: C.text, fontFamily: "inherit", fontSize: T.base,
                   padding: `${S[2]} ${S[3]}` }} />
        <button onClick={ask} disabled={!q.trim() || busy} className="el-btn"
          style={{ background: "transparent", color: C.accent, border: `1px solid ${C.accent}66`,
                   borderRadius: R.control, padding: `0 ${S[4]}`, fontSize: T.base,
                   cursor: q.trim() && !busy ? "pointer" : "not-allowed",
                   opacity: q.trim() && !busy ? 1 : 0.5 }}>
          {busy ? "…" : "Ask"}
        </button>
      </div>
    </div>
  );
}

function ImpactStat({ label, value, sub, color }: {
  label: string; value: string; sub: string; color?: string;
}) {
  return (
    <div style={{ flex: 1, minWidth: 150, padding: `${S[3]} ${S[3]}`, background: C.card2,
                  border: `1px solid ${C.border2}`, borderRadius: R.control }}>
      <div style={{ fontFamily: mono, fontSize: T.micro, letterSpacing: ".1em", color: C.faint }}>
        {label}
      </div>
      <div style={{ fontFamily: mono, fontSize: T.lg, fontWeight: 700, color: color ?? C.text,
                    marginTop: S[1] }}>
        {value}
      </div>
      <div style={{ fontSize: T.xs, color: C.dim, marginTop: 0 }}>{sub}</div>
    </div>
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

function Banner({ children, color, style }: {
  children: React.ReactNode; color: string; style?: React.CSSProperties;
}) {
  return (
    <div style={{ marginBottom: S[4], padding: `${S[3]} ${S[4]}`, border: `1px solid ${color}66`,
                  background: `${color}12`, borderRadius: R.control, fontSize: T.base, color,
                  lineHeight: "var(--el-lh-normal)", maxWidth: 620, ...style }}>
      {children}
    </div>
  );
}
