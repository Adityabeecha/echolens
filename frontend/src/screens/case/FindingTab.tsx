import { useState } from "react";
import { Decision, Evidence, Impact, Investigation, Severity, api, canReview } from "../../api";
import { withToast } from "../../components/Toast";
import { pct } from "../../format";
import { SEVERITY } from "../../status";
import { C, mono } from "../../theme";
import { EmptyState, Label } from "../../ui";

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
            style={{ fontFamily: mono, fontSize: 10, color: C.accent, cursor: "pointer",
                     padding: "1px 4px", background: "rgba(240,166,60,.1)", borderRadius: 3,
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
  inv, onOpenEvidence, onOpenTrace, onOpenCase, onReload, onReviewed,
}: Props) {
  const [challengeOpen, setChallengeOpen] = useState(false);
  const [note, setNote] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  const f = inv.finding;
  if (!f) {
    return (
      <div style={{ flex: 1, overflow: "auto", padding: "26px 28px" }}>
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
      failure: "Couldn't approve that finding",
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
      <div style={{ maxWidth: 820, padding: "24px 28px 60px" }}>
        {challenged && (
          <Banner color={C.accent}>
            You challenged this finding. A fresh case is addressing it — see History for the link.
          </Banner>
        )}

        {inv.data_notes && inv.data_notes.length > 0 && (
          <div style={{ marginBottom: 18, padding: "12px 16px", border: `1px solid ${C.bad}44`,
                        background: `${C.bad}12`, borderRadius: 8 }}>
            <Label style={{ color: C.bad, marginBottom: 6 }}>DATA AVAILABILITY</Label>
            {inv.data_notes.map((n, i) => (
              <div key={i} style={{ fontSize: 12.5, color: C.text3, lineHeight: 1.55 }}>{n}</div>
            ))}
          </div>
        )}

        {f.decision && (
          <DecisionCard decision={f.decision} impact={f.impact} severity={f.severity} />
        )}

        <div style={{ padding: "22px 24px", background: C.card, border: `1px solid ${C.border2}`,
                      borderRadius: 12 }}>
          <Label style={{ letterSpacing: ".12em", marginBottom: 12 }}>FINDING</Label>
          <div style={{ fontSize: 20, fontWeight: 700, lineHeight: 1.35,
                        letterSpacing: "-.01em" }}>
            {f.summary}
          </div>
          <div style={{ fontSize: 14, lineHeight: 1.75, color: C.text3, marginTop: 14 }}>
            <Prose text={f.prose} evidence={inv.evidence} onOpenEvidence={onOpenEvidence} />
          </div>
          {inv.status !== "resolved" && f.what_would_settle_it && (
            <div style={{ marginTop: 14, fontSize: 12.5, color: C.muted, lineHeight: 1.6 }}>
              <span style={{ color: C.text3 }}>What would settle it:</span> {f.what_would_settle_it}
            </div>
          )}
          <div onClick={onOpenTrace} className="el-btn" role="button" tabIndex={0}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onOpenTrace(); }}
            style={{ marginTop: 16, fontSize: 12.5, color: C.dim, cursor: "pointer" }}>
            See how we got here →
          </div>
        </div>

        {inv.recommendations.length > 0 && (
          <>
            <Label style={{ margin: "26px 0 10px" }}>RECOMMENDED ACTIONS</Label>
            <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
              {inv.recommendations.map((ac) => (
                <div key={ac.rank} style={{ display: "flex", alignItems: "center", gap: 14,
                                            padding: "14px 16px", background: C.card,
                                            border: `1px solid ${C.border2}`, borderRadius: 9 }}>
                  <div style={{ width: 26, height: 26, borderRadius: 6, background: C.hover,
                                border: `1px solid ${C.border3}`, display: "flex",
                                alignItems: "center", justifyContent: "center", fontFamily: mono,
                                fontSize: 12, color: C.accent, flex: "none" }}>
                    {ac.rank}
                  </div>
                  <div style={{ flex: 1, fontSize: 13.5, fontWeight: 500 }}>{ac.action}</div>
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
          <Banner color={C.good} style={{ marginTop: 26, marginBottom: 0 }}>
            ✓ You approved this finding. It stays under Resolved until a fix is verified.
          </Banner>
        )}

        {!approved && !challenged && !reviewer && (
          <div style={{ marginTop: 26, fontSize: 12.5, color: C.faint }}>
            You have viewer access — approving or challenging findings needs a reviewer role.
          </div>
        )}

        {!approved && !challenged && reviewer && (
          <div style={{ display: "flex", gap: 12, marginTop: 26, alignItems: "flex-start" }}>
            <button onClick={approve} disabled={busy} className="el-btn"
              style={{ padding: "12px 26px", borderRadius: 8, border: "none", background: C.accent,
                       color: C.onAccent, fontSize: 14, fontWeight: 600,
                       cursor: busy ? "wait" : "pointer" }}>
              {busy ? "Saving…" : "Approve finding"}
            </button>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <button onClick={() => setChallengeOpen((o) => !o)} className="el-btn"
                style={{ padding: "12px 26px", borderRadius: 8, border: `1px solid ${C.border4}`,
                         background: "transparent", color: C.text, fontSize: 14, fontWeight: 500,
                         cursor: "pointer" }}>
                Challenge
              </button>
              <span style={{ fontSize: 11, color: C.faint }}>
                challenging re-opens the investigation with your note
              </span>
            </div>
          </div>
        )}

        {challengeOpen && (
          <div style={{ marginTop: 14, padding: 16, background: C.card,
                        border: `1px solid ${C.border2}`, borderRadius: 10, maxWidth: 560 }}>
            <div style={{ fontSize: 12.5, color: C.muted, marginBottom: 8 }}>
              What's wrong with this finding? Your reason rolls up into Calibration and steers
              future investigations.
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 7, marginBottom: 10 }}>
              {[
                ["wrong_cause", "Wrong root cause"],
                ["weak_evidence", "Evidence too weak"],
                ["wrong_severity", "Severity/impact off"],
                ["already_knew", "Already knew this"],
              ].map(([val, label]) => (
                <button key={val} onClick={() => setReason((r) => (r === val ? "" : val))}
                  className="el-btn"
                  style={{ fontSize: 12, padding: "6px 11px", borderRadius: 20, cursor: "pointer",
                           border: `1px solid ${reason === val ? C.accent : C.border3}`,
                           background: reason === val ? "rgba(240,166,60,.12)" : "transparent",
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
                       border: `1px solid ${C.border3}`, borderRadius: 7, color: C.text,
                       fontFamily: "inherit", fontSize: 13, padding: 10, resize: "vertical",
                       boxSizing: "border-box" }}
            />
            <button onClick={submitChallenge} disabled={!note.trim() || busy} className="el-btn"
              style={{ marginTop: 10, padding: "8px 18px", borderRadius: 7, border: "none",
                       background: C.accent, color: C.onAccent, fontSize: 13, fontWeight: 600,
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
    <div style={{ marginBottom: 18, padding: "20px 22px", background: C.card,
                  border: `1px solid ${C.border3}`, borderRadius: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
        <Label style={{ letterSpacing: ".12em", color: C.accent }}>DECISION</Label>
        {severity && (
          <span style={{ fontFamily: mono, fontSize: 10.5, padding: "3px 9px", borderRadius: 4,
                         background: `${sevColor}1f`, border: `1px solid ${sevColor}66`,
                         color: sevColor, textTransform: "uppercase" }}>
            {severity.band} severity · {severity.score.toFixed(2)}
          </span>
        )}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 11 }}>
        {rows.map(([q, a]) => (
          <div key={q} style={{ display: "grid", gridTemplateColumns: "108px 1fr", gap: 14,
                                alignItems: "baseline" }}>
            <div style={{ fontFamily: mono, fontSize: 11, color: C.faint,
                          textTransform: "uppercase", letterSpacing: ".06em" }}>{q}</div>
            <div style={{ fontSize: 14, color: C.text2, lineHeight: 1.5 }}>{a || "—"}</div>
          </div>
        ))}
      </div>
      {impact && (impact.affected_volume > 0 || impact.rating_impact > 0) && (
        <div style={{ display: "flex", gap: 9, flexWrap: "wrap", marginTop: 16 }}>
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
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {rejected.map((h) => {
          const killers = h.evidence_against.map((id) => byId.get(id))
            .filter((e): e is Evidence => !!e);
          return (
            <div key={h.id} style={{ padding: "14px 16px", background: C.card,
                                     border: `1px solid ${C.border2}`, borderRadius: 10 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8,
                            flexWrap: "wrap" }}>
                <span style={{ fontFamily: mono, fontSize: 11, color: C.bad }}>{h.id}</span>
                <span style={{ fontFamily: mono, fontSize: 9.5, padding: "2px 7px",
                               borderRadius: 4, background: `${C.bad}1f`, color: C.bad,
                               textTransform: "uppercase" }}>
                  ruled out
                </span>
                <span style={{ fontSize: 13.5, color: C.text3, textDecoration: "line-through",
                               textDecorationColor: C.ghost }}>
                  {h.statement}
                </span>
              </div>
              {killers.length > 0 ? (
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {killers.map((e) => (
                    <div key={e.id} onClick={() => onOpenEvidence(e)}
                      style={{ fontSize: 12.5, color: C.text3, lineHeight: 1.45,
                               borderLeft: `2px solid ${C.bad}66`, paddingLeft: 10,
                               cursor: "pointer" }}>
                      <span style={{ fontFamily: mono, fontSize: 10.5, color: C.bad,
                                     marginRight: 6 }}>{e.id}</span>“{e.snippet}”
                    </div>
                  ))}
                </div>
              ) : (
                <div style={{ fontSize: 12, color: C.faint }}>
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
      failure: "Couldn't answer that follow-up",
    });
    setBusy(false);
    if (ok) { setQ(""); await onAdded(); }
  };
  return (
    <div style={{ marginTop: 26 }}>
      <Label style={{ marginBottom: 10 }}>FOLLOW-UP</Label>
      {addenda && addenda.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 9, marginBottom: 12 }}>
          {addenda.map((a, i) => (
            <div key={i} style={{ padding: "12px 15px", background: C.card,
                                  border: `1px solid ${C.border2}`, borderRadius: 10 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: C.text2 }}>{a.question}</div>
              <div style={{ fontSize: 13, color: C.text3, marginTop: 6, lineHeight: 1.5 }}>
                {a.answer}
              </div>
            </div>
          ))}
        </div>
      )}
      <div style={{ display: "flex", gap: 9, maxWidth: 560 }}>
        <input value={q} onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && ask()}
          placeholder="Does this affect iOS too? Which version?"
          style={{ flex: 1, background: C.bgRaised, border: `1px solid ${C.border3}`,
                   borderRadius: 8, color: C.text, fontFamily: "inherit", fontSize: 13,
                   padding: "9px 12px" }} />
        <button onClick={ask} disabled={!q.trim() || busy} className="el-btn"
          style={{ background: "transparent", color: C.accent, border: `1px solid ${C.accent}66`,
                   borderRadius: 8, padding: "0 16px", fontSize: 13,
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
    <div style={{ flex: 1, minWidth: 150, padding: "11px 14px", background: C.card2,
                  border: `1px solid ${C.border2}`, borderRadius: 9 }}>
      <div style={{ fontFamily: mono, fontSize: 9.5, letterSpacing: ".1em", color: C.faint }}>
        {label}
      </div>
      <div style={{ fontFamily: mono, fontSize: 18, fontWeight: 700, color: color ?? C.text,
                    marginTop: 5 }}>
        {value}
      </div>
      <div style={{ fontSize: 11, color: C.dim, marginTop: 2 }}>{sub}</div>
    </div>
  );
}

function Tag({ children, color }: { children: React.ReactNode; color: string }) {
  return (
    <span style={{ fontFamily: mono, fontSize: 10, padding: "3px 8px", borderRadius: 4,
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
    <div style={{ marginBottom: 18, padding: "12px 16px", border: `1px solid ${color}66`,
                  background: `${color}12`, borderRadius: 8, fontSize: 13, color,
                  lineHeight: 1.55, maxWidth: 620, ...style }}>
      {children}
    </div>
  );
}
