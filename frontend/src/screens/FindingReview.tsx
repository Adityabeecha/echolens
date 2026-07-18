import { useState } from "react";
import { Evidence, Investigation, api, canReview } from "../api";
import { useAsync } from "../hooks";
import { C, mono, statusColor } from "../theme";
import { Centered, Label } from "../ui";

interface Props {
  investigationId: number;
  onBack: () => void;
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

export function FindingReview({ investigationId, onBack, onOpenEvidence, onReviewed }: Props) {
  const { data: inv, loading, reload } = useAsync<Investigation>(() => api.investigation(investigationId), [investigationId]);
  const [challengeOpen, setChallengeOpen] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  if (loading) return <Centered>Loading finding…</Centered>;
  if (!inv?.finding) return <Centered>No finding drafted yet for case #{investigationId}.</Centered>;

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
    const r = await api.review(f.id, "challenge", note);
    setBusy(false);
    setChallengeOpen(false);
    setNote("");
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
        <span onClick={onBack} style={{ color: C.dim, cursor: "pointer", fontSize: 13 }}>
          ← Investigation
        </span>
        <div style={{ width: 1, height: 18, background: C.border2 }} />
        <span style={{ fontFamily: mono, fontSize: 12, color: C.accent }}>CASE #{investigationId}</span>
        <div style={{ fontSize: 15, fontWeight: 600 }}>Finding Review</div>
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
              What does this finding get wrong, or what should the agent check?
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
