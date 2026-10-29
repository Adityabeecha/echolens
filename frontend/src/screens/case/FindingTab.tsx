import { useState } from "react";
import { Decision, Evidence, Impact, Investigation, Severity, api } from "../../api";
import { withToast } from "../../components/Toast";
import { pct } from "../../format";
import { SEVERITY } from "../../status";
import { C, R, S, T, mono } from "../../theme";
import { Label, Rich } from "../../ui";

// Parts of the old Finding tab that live on under "More" on the problem page:
// the decision summary with its impact numbers, the causes ruled out, and
// follow-up questions. The story, reasons and verdict moved to CaseDetail.

/** The three questions a PM asks, answered above the fold. */
export function DecisionCard({ decision, impact, severity }: {
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
            <div style={{ fontSize: T.md, color: C.text2, lineHeight: "var(--el-lh-normal)",
                          overflowWrap: "anywhere", minWidth: 0 }}>{a ? <Rich text={a} /> : "—"}</div>
          </div>
        ))}
      </div>
      {impact && (impact.affected_volume > 0 || impact.rating_impact > 0) && (
        <div style={{ display: "flex", gap: S[2], flexWrap: "wrap", marginTop: S[4] }}>
          <ImpactStat label="AFFECTED" value={pct(impact.affected_pct)}
                      sub={`of recent negative reviews · ${impact.affected_volume} reviews / 7d`}
                      hint="Share of recent negative reviews that match this problem. It is a share of reviews, not of users." />
          <ImpactStat label="APP RATING CHANGE" value={`−${impact.rating_impact.toFixed(2)}★`}
                      sub="whole app, last 7 days vs before"
                      hint="How far the whole app's rating fell while this problem was investigated. Other problems can contribute too; this problem's own share is shown at the top of the page."
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
export function WhyNotPanel({ inv, onOpenEvidence }: {
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
export function FollowupCard({ findingId, addenda, onAdded }: {
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
          aria-label="Ask a follow-up question about this finding"
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

function ImpactStat({ label, value, sub, color, hint }: {
  label: string; value: string; sub: string; color?: string; hint?: string;
}) {
  return (
    <div title={hint} style={{ flex: 1, minWidth: 150, padding: `${S[3]} ${S[3]}`, background: C.card2,
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


