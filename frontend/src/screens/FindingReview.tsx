import { useState } from "react";
import { Decision, Evidence, FixStatus, Impact, Investigation, Severity, api, canReview } from "../api";
import { useAsync } from "../hooks";
import { C, mono, statusColor } from "../theme";
import { Centered, Label } from "../ui";

const SEV_COLOR: Record<string, string> = { high: C.bad, medium: C.accent, low: C.muted };

interface Props {
  investigationId: number;
  onBack: () => void;
  backLabel?: string;
  /** Jump to the reasoning trace for this case. */
  onOpenTrace?: () => void;
  onOpenEvidence: (e: Evidence) => void;
  onReviewed: () => void;
}

// Render prose, turning [ev_00x] citations into clickable superscripts.
function Prose({ text, evidence, onOpenEvidence }: { text: string; evidence: Evidence[]; onOpenEvidence: (e: Evidence) => void }) {
  const parts = text.split(/(\[ev_\d+\])/g);
  return (
    <>
      {parts.map((p, i) => {
        const m = p.match(/^\[(ev_\d+)\]$/);
        if (!m) return <span key={i}>{p}</span>;
        const ev = evidence.find((e) => e.id === m[1]);
        return (
          <sup
            key={i}
            onClick={() => ev && onOpenEvidence(ev)}
            style={{
              fontFamily: mono,
              fontSize: 10,
              color: C.accent,
              cursor: "pointer",
              padding: "1px 4px",
              background: "rgba(240,166,60,.1)",
              borderRadius: 3,
              marginLeft: 2,
            }}
          >
            {m[1]}
          </sup>
        );
      })}
    </>
  );
}

export function FindingReview({ investigationId, onBack, backLabel = "the investigation", onOpenEvidence, onReviewed, onOpenTrace }: Props) {
  const { data: inv, loading, reload } = useAsync<Investigation>(() => api.investigation(investigationId), [investigationId]);
  const [challengeOpen, setChallengeOpen] = useState(false);
  const [note, setNote] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  if (loading) return <Centered>Loading finding…</Centered>;
  if (!inv?.finding)
    return (
      <Centered>
        <div style={{ textAlign: "center", maxWidth: 380 }}>
          <div style={{ fontSize: 14.5, color: C.text3, marginBottom: 8 }}>
            No answer yet for case #{investigationId}
          </div>
          <div style={{ fontSize: 13, color: C.dim, lineHeight: 1.6, marginBottom: 14 }}>
            {inv?.status === "running"
              ? "It's still investigating — the reasoning is streaming live."
              : "This case ended without a drafted finding. The trace shows what was checked."}
          </div>
          <div style={{ display: "flex", gap: 10, justifyContent: "center" }}>
            {onOpenTrace && (
              <button onClick={onOpenTrace} className="el-btn"
                style={{ background: "transparent", color: C.accent, border: `1px solid rgba(240,166,60,.4)`,
                         borderRadius: 7, padding: "9px 16px", fontSize: 13, cursor: "pointer" }}>
                See the investigation
              </button>
            )}
            <button onClick={onBack} className="el-btn"
              style={{ background: "transparent", color: C.muted, border: `1px solid ${C.border3}`,
                       borderRadius: 7, padding: "9px 16px", fontSize: 13, cursor: "pointer" }}>
              Back to {backLabel}
            </button>
          </div>
        </div>
      </Centered>
    );

  const f = inv.finding;
  const conf = f.confidence ?? 0;
  const approved = f.status === "approved";
  const challenged = f.status === "challenged";
  const sc = statusColor(inv.status);

  const approve = async () => {
    setBusy(true);
    await api.review(f.id, "approve");
    await reload();
    onReviewed();
    setBusy(false);
  };
  const submitChallenge = async () => {
    if (!note.trim()) return;
    setBusy(true);
    const r = await api.review(f.id, "challenge", note, reason || undefined);
    setBusy(false);
    setChallengeOpen(false);
    setNote("");
    setReason("");
    onReviewed();
    if (r.reopened_investigation_id) window.location.hash = `#case/${r.reopened_investigation_id}`;
    await reload();
  };

  return (
    <div style={{ height: "100%", overflow: "auto" }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 14,
          padding: "14px 28px",
          borderBottom: `1px solid ${C.border}`,
          position: "sticky",
          top: 0,
          background: C.bg,
          zIndex: 5,
        }}
      >
        <span onClick={onBack} className="el-btn" role="button" tabIndex={0}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onBack(); }}
          style={{ color: C.dim, cursor: "pointer", fontSize: 13, whiteSpace: "nowrap" }}>
          ← Back to {backLabel}
        </span>
        <div style={{ width: 1, height: 18, background: C.border2 }} />
        <span style={{ fontFamily: mono, fontSize: 12, color: C.accent }}>CASE #{investigationId}</span>
        <div style={{ fontSize: 15, fontWeight: 600 }}>Finding Review</div>
        {onOpenTrace && (
          <span onClick={onOpenTrace} className="el-btn" role="button" tabIndex={0}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onOpenTrace(); }}
            style={{ fontSize: 12.5, color: C.dim, cursor: "pointer", whiteSpace: "nowrap" }}>
            See how we got here →
          </span>
        )}
        <div style={{ flex: 1 }} />
        <span style={{ fontFamily: mono, fontSize: 10.5, color: C.ghost }}>{inv.budget?.tier} tier</span>
      </div>

      <div style={{ maxWidth: 820, padding: "26px 28px 60px" }}>
        {challenged && (
          <div
            style={{
              marginBottom: 18,
              padding: "12px 16px",
              border: "1px solid rgba(240,166,60,.4)",
              background: "rgba(240,166,60,.07)",
              borderRadius: 8,
              fontSize: 13,
              color: C.accent,
            }}
          >
            Investigation re-opened with your note. A fresh case is addressing it.
          </div>
        )}

        {inv.data_notes && inv.data_notes.length > 0 && (
          <div style={{ marginBottom: 18, padding: "12px 16px", border: `1px solid ${C.bad}44`, background: `${C.bad}12`, borderRadius: 8 }}>
            <div style={{ fontFamily: mono, fontSize: 10.5, letterSpacing: ".1em", color: C.bad, marginBottom: 6 }}>
              DATA AVAILABILITY
            </div>
            {inv.data_notes.map((n, i) => (
              <div key={i} style={{ fontSize: 12.5, color: C.text3, lineHeight: 1.55 }}>{n}</div>
            ))}
          </div>
        )}

        {f.decision && (
          <DecisionCard decision={f.decision} impact={f.impact} severity={f.severity} findingId={f.id} canCreate={canReview() && inv.status === "resolved"} />
        )}

        {f.fix && <FixCard fix={f.fix} />}

        {canReview() && <FollowupCard findingId={f.id} addenda={f.addenda} onAdded={reload} />}

        <div style={{ padding: "22px 24px", background: C.card, border: `1px solid ${C.border2}`, borderRadius: 12 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
            <Label style={{ letterSpacing: ".12em" }}>FINDING</Label>
            <span
              style={{
                fontFamily: mono,
                fontSize: 10.5,
                padding: "3px 9px",
                borderRadius: 4,
                background: `${sc}1f`,
                border: `1px solid ${sc}66`,
                color: sc,
                textTransform: "uppercase",
              }}
            >
              {inv.status.replace(/_/g, " ")} · {conf.toFixed(2)}
            </span>
          </div>
          <div style={{ fontSize: 20, fontWeight: 700, lineHeight: 1.35, letterSpacing: "-.01em" }}>{f.summary}</div>
          <div style={{ fontSize: 14, lineHeight: 1.75, color: C.text3, marginTop: 14 }}>
            <Prose text={f.prose} evidence={inv.evidence} onOpenEvidence={onOpenEvidence} />
          </div>
          {inv.status !== "resolved" && f.what_would_settle_it && (
            <div style={{ marginTop: 14, fontSize: 12.5, color: C.muted, lineHeight: 1.6 }}>
              <span style={{ color: C.text3 }}>What would settle it:</span> {f.what_would_settle_it}
            </div>
          )}
        </div>

        <Label style={{ margin: "26px 0 10px" }}>EVIDENCE · {inv.evidence.length} ITEMS</Label>
        <div style={{ border: `1px solid ${C.border2}`, borderRadius: 10, overflow: "hidden" }}>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "76px 120px 1fr 140px",
              gap: 12,
              padding: "9px 16px",
              background: C.card2,
              fontFamily: mono,
              fontSize: 10,
              letterSpacing: ".08em",
              color: C.faint,
              borderBottom: `1px solid ${C.border}`,
            }}
          >
            <span>ID</span>
            <span>SOURCE</span>
            <span>SNIPPET</span>
            <span>SUPPORTS</span>
          </div>
          {inv.evidence.map((e) => (
            <div
              key={e.id}
              onClick={() => onOpenEvidence(e)}
              style={{
                display: "grid",
                gridTemplateColumns: "76px 120px 1fr 140px",
                gap: 12,
                padding: "12px 16px",
                borderBottom: `1px solid #1c1e27`,
                cursor: "pointer",
                background: C.card,
              }}
            >
              <span style={{ fontFamily: mono, fontSize: 11.5, color: C.accent }}>{e.id}</span>
              <span style={{ fontFamily: mono, fontSize: 11, color: C.muted, textTransform: "uppercase" }}>{e.source}</span>
              <span style={{ fontSize: 12.5, color: C.text3, lineHeight: 1.45 }}>“{e.snippet}”</span>
              <span style={{ fontSize: 12, color: C.good }}>{e.supports.join(", ")}</span>
            </div>
          ))}
        </div>

        {inv.recommendations.length > 0 && (
          <>
            <Label style={{ margin: "26px 0 10px" }}>RECOMMENDED ACTIONS</Label>
            <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
              {inv.recommendations.map((ac) => (
                <div
                  key={ac.rank}
                  style={{ display: "flex", alignItems: "center", gap: 14, padding: "14px 16px", background: C.card, border: `1px solid ${C.border2}`, borderRadius: 9 }}
                >
                  <div
                    style={{
                      width: 26,
                      height: 26,
                      borderRadius: 6,
                      background: C.hover,
                      border: `1px solid ${C.border3}`,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontFamily: mono,
                      fontSize: 12,
                      color: C.accent,
                      flex: "none",
                    }}
                  >
                    {ac.rank}
                  </div>
                  <div style={{ flex: 1, fontSize: 13.5, fontWeight: 500 }}>{ac.action}</div>
                  <span style={{ fontFamily: mono, fontSize: 10, padding: "3px 8px", borderRadius: 4, background: "rgba(76,192,119,.1)", color: C.good, border: "1px solid rgba(76,192,119,.3)" }}>
                    {ac.impact} impact
                  </span>
                  <span style={{ fontFamily: mono, fontSize: 10, padding: "3px 8px", borderRadius: 4, background: C.hover, color: C.muted, border: `1px solid ${C.border3}` }}>
                    {ac.effort} effort
                  </span>
                </div>
              ))}
            </div>
          </>
        )}

        <WhyNotPanel inv={inv} onOpenEvidence={onOpenEvidence} />

        {approved && (
          <div
            style={{
              marginTop: 26,
              padding: "14px 18px",
              border: "1px solid rgba(76,192,119,.4)",
              background: "rgba(76,192,119,.07)",
              borderRadius: 9,
              fontSize: 13,
              color: C.good,
              lineHeight: 1.6,
              maxWidth: 560,
            }}
          >
            ✓ Finding approved · case moved to archive as RESOLVED.
          </div>
        )}

        {!approved && !challenged && !canReview() && (
          <div style={{ marginTop: 26, fontSize: 12.5, color: C.faint }}>
            You have viewer access — approving or challenging findings needs a reviewer role.
          </div>
        )}
        {!approved && !challenged && canReview() && (
          <div style={{ display: "flex", gap: 12, marginTop: 26, alignItems: "flex-start" }}>
            <button
              onClick={approve}
              disabled={busy}
              style={{ padding: "12px 26px", borderRadius: 8, border: "none", background: C.accent, color: C.onAccent, fontSize: 14, fontWeight: 600, cursor: "pointer" }}
            >
              Approve finding
            </button>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <button
                onClick={() => setChallengeOpen((o) => !o)}
                style={{ padding: "12px 26px", borderRadius: 8, border: `1px solid ${C.border4}`, background: "transparent", color: C.text, fontSize: 14, fontWeight: 500, cursor: "pointer" }}
              >
                Challenge
              </button>
              <span style={{ fontSize: 11, color: C.faint }}>challenging re-opens the investigation with your note</span>
            </div>
          </div>
        )}

        {challengeOpen && (
          <div style={{ marginTop: 14, padding: 16, background: C.card, border: `1px solid ${C.border2}`, borderRadius: 10, maxWidth: 560 }}>
            <div style={{ fontSize: 12.5, color: C.muted, marginBottom: 8 }}>
              What's wrong with this finding? Your reason feeds the Calibration page and steers future investigations.
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 7, marginBottom: 10 }}>
              {[
                ["wrong_cause", "Wrong root cause"],
                ["weak_evidence", "Evidence too weak"],
                ["wrong_severity", "Severity/impact off"],
                ["already_knew", "Already knew this"],
              ].map(([val, label]) => (
                <button
                  key={val}
                  onClick={() => setReason((r) => (r === val ? "" : val))}
                  className="el-btn"
                  style={{
                    fontSize: 12,
                    padding: "6px 11px",
                    borderRadius: 20,
                    cursor: "pointer",
                    border: `1px solid ${reason === val ? C.accent : C.border3}`,
                    background: reason === val ? "rgba(240,166,60,.12)" : "transparent",
                    color: reason === val ? C.accent : C.muted,
                  }}
                >
                  {label}
                </button>
              ))}
            </div>
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="e.g. Battery complaints also mention charging speed — check charger-related reviews before pinning this on sync."
              style={{
                width: "100%",
                height: 76,
                background: C.bgRaised,
                border: `1px solid ${C.border3}`,
                borderRadius: 7,
                color: C.text,
                fontFamily: "inherit",
                fontSize: 13,
                padding: 10,
                resize: "vertical",
              }}
            />
            <button
              onClick={submitChallenge}
              disabled={!note.trim() || busy}
              style={{
                marginTop: 10,
                padding: "8px 18px",
                borderRadius: 7,
                border: "none",
                background: C.accent,
                color: C.onAccent,
                fontSize: 13,
                fontWeight: 600,
                cursor: note.trim() ? "pointer" : "not-allowed",
                opacity: note.trim() ? 1 : 0.45,
              }}
            >
              Submit &amp; re-open investigation
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// The decision document: the three questions a PM asks, above the fold, with
// impact numbers and one-click ticketing. Evidence detail stays below.
function DecisionCard({
  decision,
  impact,
  severity,
  findingId,
  canCreate,
}: {
  decision: Decision;
  impact?: Impact;
  severity?: Severity;
  findingId: number;
  canCreate: boolean;
}) {
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const sevColor = severity ? SEV_COLOR[severity.band] ?? C.muted : C.muted;

  const copyIssue = async () => {
    setBusy("copy");
    setMsg(null);
    try {
      const t = await api.findingIssue(findingId);
      await navigator.clipboard.writeText(`# ${t.title}\n\n${t.body}`);
      setMsg("Copied ticket markdown to clipboard.");
    } catch (e) {
      setMsg(String(e).replace("Error: ", ""));
    } finally {
      setBusy(null);
    }
  };
  const createIssue = async () => {
    setBusy("create");
    setMsg(null);
    try {
      const r = await api.createGithubIssue(findingId);
      setMsg(`Opened GitHub issue #${r.number} in ${r.repo}.`);
    } catch (e) {
      setMsg(String(e).replace("Error: ", ""));
    } finally {
      setBusy(null);
    }
  };

  const rows: [string, string][] = [
    ["What's broken", decision.whats_broken],
    ["How bad", decision.how_bad],
    ["What to do", decision.what_to_do],
  ];

  return (
    <div style={{ marginBottom: 18, padding: "20px 22px", background: C.card, border: `1px solid ${C.border3}`, borderRadius: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
        <Label style={{ letterSpacing: ".12em", color: C.accent }}>DECISION</Label>
        {severity && (
          <span style={{ fontFamily: mono, fontSize: 10.5, padding: "3px 9px", borderRadius: 4, background: `${sevColor}1f`, border: `1px solid ${sevColor}66`, color: sevColor, textTransform: "uppercase" }}>
            {severity.band} severity · {severity.score.toFixed(2)}
          </span>
        )}
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 11 }}>
        {rows.map(([q, a]) => (
          <div key={q} style={{ display: "grid", gridTemplateColumns: "108px 1fr", gap: 14, alignItems: "baseline" }}>
            <div style={{ fontFamily: mono, fontSize: 11, color: C.faint, textTransform: "uppercase", letterSpacing: ".06em" }}>{q}</div>
            <div style={{ fontSize: 14, color: C.text2, lineHeight: 1.5 }}>{a || "—"}</div>
          </div>
        ))}
      </div>

      {impact && (impact.affected_volume > 0 || impact.rating_impact > 0) && (
        <div style={{ display: "flex", gap: 9, flexWrap: "wrap", marginTop: 16 }}>
          <ImpactStat label="AFFECTED" value={`${impact.affected_pct}%`} sub={`${impact.affected_volume} reviews / 7d`} />
          <ImpactStat label="RATING IMPACT" value={`${impact.rating_impact.toFixed(2)}★`} sub="est. lost vs baseline" color={impact.rating_impact > 0 ? C.bad : C.muted} />
          {impact.blast_radius.top_cohort && impact.blast_radius.top_cohort !== "unknown" && (
            <ImpactStat
              label="BLAST RADIUS"
              value={impact.blast_radius.top_cohort}
              sub={impact.blast_radius.exclusive ? "exclusive to cohort" : impact.blast_radius.ratio ? `${impact.blast_radius.ratio}× next version` : "top cohort"}
            />
          )}
        </div>
      )}

      <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 16, flexWrap: "wrap" }}>
        <button onClick={copyIssue} disabled={!!busy} className="el-btn"
          style={{ background: "transparent", color: C.text2, border: `1px solid ${C.border3}`, borderRadius: 7, padding: "8px 14px", fontSize: 13, cursor: "pointer" }}>
          {busy === "copy" ? "Copying…" : "Copy as issue"}
        </button>
        {canCreate && (
          <button onClick={createIssue} disabled={!!busy} className="el-btn"
            style={{ background: C.accent, color: C.onAccent, border: "none", borderRadius: 7, padding: "8px 14px", fontSize: 13, fontWeight: 600, cursor: "pointer" }}>
            {busy === "create" ? "Creating…" : "Create GitHub issue"}
          </button>
        )}
        {msg && <span style={{ fontSize: 12.5, color: C.muted }}>{msg}</span>}
      </div>
    </div>
  );
}

// "Why not X?": the hypotheses that were ruled out, with the evidence that
// killed them. Half of trust is seeing what was considered and rejected.
function WhyNotPanel({ inv, onOpenEvidence }: { inv: Investigation; onOpenEvidence: (e: Evidence) => void }) {
  const rejected = inv.hypotheses.filter((h) => h.status === "rejected");
  if (rejected.length === 0) return null;
  const byId = new Map(inv.evidence.map((e) => [e.id, e]));

  return (
    <>
      <Label style={{ margin: "26px 0 10px" }}>WHY NOT? · {rejected.length} RULED OUT</Label>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {rejected.map((h) => {
          const killers = h.evidence_against.map((id) => byId.get(id)).filter((e): e is Evidence => !!e);
          return (
            <div key={h.id} style={{ padding: "14px 16px", background: C.card, border: `1px solid ${C.border2}`, borderRadius: 10 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                <span style={{ fontFamily: mono, fontSize: 11, color: C.bad }}>{h.id}</span>
                <span style={{ fontFamily: mono, fontSize: 9.5, padding: "2px 7px", borderRadius: 4, background: `${C.bad}1f`, color: C.bad, textTransform: "uppercase" }}>
                  ruled out
                </span>
                <span style={{ fontSize: 13.5, color: C.text3, textDecoration: "line-through", textDecorationColor: C.ghost }}>
                  {h.statement}
                </span>
              </div>
              {killers.length > 0 ? (
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {killers.map((e) => (
                    <div
                      key={e.id}
                      onClick={() => onOpenEvidence(e)}
                      style={{ fontSize: 12.5, color: C.text3, lineHeight: 1.45, borderLeft: `2px solid ${C.bad}66`, paddingLeft: 10, cursor: "pointer" }}
                    >
                      <span style={{ fontFamily: mono, fontSize: 10.5, color: C.bad, marginRight: 6 }}>{e.id}</span>“{e.snippet}”
                    </div>
                  ))}
                </div>
              ) : (
                <div style={{ fontSize: 12, color: C.faint }}>Rejected as the leading cause was corroborated instead.</div>
              )}
            </div>
          );
        })}
      </div>
    </>
  );
}

// v6.0: did the fix work? Verification badge + before/after complaint chart.
const FIX_META: Record<string, { label: string; color: string }> = {
  issue_open: { label: "Fix issue open — awaiting close", color: C.info },
  watching: { label: "In verification — 14-day watch", color: C.accent },
  confirmed: { label: "✓ Confirmed fix", color: C.good },
  persists_reopened: { label: "Fix didn't hold — re-opened", color: C.bad },
  regressed: { label: "⚠ Regressed — re-spiked after fix", color: C.bad },
};

function FixCard({ fix }: { fix: FixStatus }) {
  const meta = FIX_META[fix.status] ?? { label: fix.status, color: C.muted };
  return (
    <div style={{ marginBottom: 18, padding: "16px 18px", background: C.card, border: `1px solid ${meta.color}55`, borderRadius: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <Label style={{ letterSpacing: ".12em" }}>FIX STATUS</Label>
        <span style={{ fontFamily: mono, fontSize: 11, padding: "3px 10px", borderRadius: 20, background: `${meta.color}1f`, border: `1px solid ${meta.color}66`, color: meta.color }}>
          {meta.label}
        </span>
        {fix.issue_url && (
          <a href={fix.issue_url} target="_blank" rel="noreferrer" style={{ fontFamily: mono, fontSize: 11.5, color: C.info, marginLeft: "auto", textDecoration: "none" }}>
            issue #{fix.issue_number} ↗
          </a>
        )}
      </div>
      {fix.chart && (fix.chart.before.length > 0 || fix.chart.after.length > 0) && (
        <BeforeAfterChart chart={fix.chart} />
      )}
    </div>
  );
}

function BeforeAfterChart({ chart }: { chart: NonNullable<FixStatus["chart"]> }) {
  const max = Math.max(1, ...chart.before.map((p) => p.count), ...chart.after.map((p) => p.count));
  const Bars = ({ points, color }: { points: { date: string; count: number }[]; color: string }) => (
    <div style={{ flex: 1, minWidth: 0 }}>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 2, height: 60 }}>
        {points.map((p) => (
          <div key={p.date} title={`${p.date}: ${p.count}`} style={{ flex: 1, height: `${Math.max(2, (p.count / max) * 100)}%`, background: color, borderRadius: "2px 2px 0 0", opacity: 0.85 }} />
        ))}
      </div>
    </div>
  );
  const rate = (r: number | null) => (r == null ? "—" : `${r.toFixed(1)}/day`);
  return (
    <div style={{ marginTop: 14 }}>
      <div style={{ fontSize: 12.5, color: C.muted, marginBottom: 10 }}>
        Complaint volume for “{chart.terms.join(", ")}” around the fix ({chart.fix_date}).
      </div>
      <div style={{ display: "flex", gap: 16, alignItems: "stretch" }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontFamily: mono, fontSize: 10, color: C.faint, marginBottom: 6 }}>
            BEFORE · {rate(chart.before_rate)}
          </div>
          <Bars points={chart.before} color={C.bad} />
        </div>
        <div style={{ width: 1, background: C.border3, alignSelf: "stretch" }} />
        <div style={{ flex: 1 }}>
          <div style={{ fontFamily: mono, fontSize: 10, color: C.faint, marginBottom: 6 }}>
            AFTER · {rate(chart.after_rate)}
          </div>
          <Bars points={chart.after} color={C.good} />
        </div>
      </div>
    </div>
  );
}

// v7.0: ask a targeted follow-up ("does this affect iOS too?") → cohort answer
// appended as an addendum, no full re-investigation.
function FollowupCard({ findingId, addenda, onAdded }: { findingId: number; addenda?: { question: string; answer: string; dimension: string }[]; onAdded: () => void }) {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const ask = async () => {
    if (!q.trim() || busy) return;
    setBusy(true);
    try {
      await api.findingFollowup(findingId, q.trim());
      setQ("");
      onAdded();
    } finally {
      setBusy(false);
    }
  };
  return (
    <div style={{ marginTop: 26 }}>
      <Label style={{ marginBottom: 10 }}>FOLLOW-UP</Label>
      {addenda && addenda.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 9, marginBottom: 12 }}>
          {addenda.map((a, i) => (
            <div key={i} style={{ padding: "12px 15px", background: C.card, border: `1px solid ${C.border2}`, borderRadius: 10 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: C.text2 }}>{a.question}</div>
              <div style={{ fontSize: 13, color: C.text3, marginTop: 6, lineHeight: 1.5 }}>{a.answer}</div>
            </div>
          ))}
        </div>
      )}
      <div style={{ display: "flex", gap: 9, maxWidth: 560 }}>
        <input value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && ask()}
          placeholder="Does this affect iOS too? Which version?"
          style={{ flex: 1, background: C.bgRaised, border: `1px solid ${C.border3}`, borderRadius: 8, color: C.text, fontFamily: "inherit", fontSize: 13, padding: "9px 12px" }} />
        <button onClick={ask} disabled={!q.trim() || busy} className="el-btn"
          style={{ background: "transparent", color: C.accent, border: `1px solid ${C.accent}66`, borderRadius: 8, padding: "0 16px", fontSize: 13, cursor: q.trim() && !busy ? "pointer" : "not-allowed", opacity: q.trim() && !busy ? 1 : 0.5 }}>
          {busy ? "…" : "Ask"}
        </button>
      </div>
    </div>
  );
}

function ImpactStat({ label, value, sub, color }: { label: string; value: string; sub: string; color?: string }) {
  return (
    <div style={{ flex: 1, minWidth: 150, padding: "11px 14px", background: C.card2, border: `1px solid ${C.border2}`, borderRadius: 9 }}>
      <div style={{ fontFamily: mono, fontSize: 9.5, letterSpacing: ".1em", color: C.faint }}>{label}</div>
      <div style={{ fontFamily: mono, fontSize: 18, fontWeight: 700, color: color ?? C.text, marginTop: 5 }}>{value}</div>
      <div style={{ fontSize: 11, color: C.dim, marginTop: 2 }}>{sub}</div>
    </div>
  );
}
