import { useState } from "react";
import { Anomaly, api, canReview } from "../api";
import { useAsync } from "../hooks";
import { C, mono, sans } from "../theme";
import { Chip, Label, Spark, sparkFor } from "../ui";

interface Props {
  onOpenInvestigation: (id: number, status?: string) => void;
  onNewCase: () => void;
  reloadKey: number;
  bumpReload: () => void;
}

function severity(z: number) {
  if (Math.abs(z) >= 3) return { label: "SEV1", color: C.bad };
  if (Math.abs(z) >= 2) return { label: "SEV2", color: C.accent };
  return { label: "SEV3", color: C.dim };
}

function chipFor(a: Anomaly): { label: string; color: string; bg: string; border: string; pulse?: boolean } {
  const t = a.triage?.decision;
  if (a.status === "investigating" || (t === "investigate" && a.investigation_id && a.status !== "closed"))
    return { label: "Investigating", color: C.accent, bg: "rgba(240,166,60,.1)", border: "rgba(240,166,60,.35)", pulse: true };
  if (a.status === "needs_human")
    return { label: "Needs your call", color: C.accent, bg: "rgba(240,166,60,.1)", border: "rgba(240,166,60,.35)" };
  if (t === "merge")
    return { label: "Merged", color: C.info, bg: "rgba(143,208,255,.08)", border: "rgba(143,208,255,.3)" };
  if (t === "ignore")
    return { label: "Ignored — noise", color: C.muted, bg: C.hover, border: C.border3 };
  if (a.status === "closed")
    return { label: "Resolved ✓", color: C.good, bg: "rgba(76,192,119,.1)", border: "rgba(76,192,119,.35)" };
  if (a.status === "insufficient_evidence" || a.status === "budget_exhausted")
    return { label: "No clear cause", color: C.muted, bg: C.hover, border: C.border3 };
  return { label: "Pending triage", color: C.text3, bg: C.hover, border: C.border4 };
}

// Which section a signal belongs to — so the feed reads as a pipeline, not a pile.
type Bucket = "attention" | "active" | "triage" | "resolved" | "dismissed";
function bucketOf(a: Anomaly): Bucket {
  const t = a.triage?.decision;
  if (a.status === "needs_human") return "attention";
  if (a.status === "investigating" || (t === "investigate" && a.investigation_id && a.status !== "closed")) return "active";
  if (a.status === "closed") return "resolved";
  if (a.status === "insufficient_evidence" || a.status === "budget_exhausted") return "resolved";
  if (t === "ignore" || t === "merge") return "dismissed";
  return "triage";
}

const SECTIONS: { key: Bucket; label: string; color: string }[] = [
  { key: "attention", label: "NEEDS YOUR CALL", color: C.accent },
  { key: "active", label: "ACTIVE INVESTIGATIONS", color: C.accent },
  { key: "triage", label: "AWAITING TRIAGE", color: C.text3 },
  { key: "resolved", label: "RESOLVED", color: C.good },
];

export function CaseFeed({ onOpenInvestigation, onNewCase, reloadKey, bumpReload }: Props) {
  const anomalies = useAsync(() => api.anomalies(), [reloadKey]);
  const summary = useAsync(() => api.feedSummary(), [reloadKey]);
  const sources = useAsync(() => api.sources(), [reloadKey]);
  // Themes worth investigating that aren't anomalies yet. The onboarding wizard
  // offers these; without the same list here they'd vanish on the way to the feed.
  const candidates = useAsync(() => api.feedCandidates(), [reloadKey]);
  const [busy, setBusy] = useState<string | null>(null);
  const [showDismissed, setShowDismissed] = useState(false);
  const reviewer = canReview();

  const used = summary.data?.investigations_today ?? 0;
  const limit = summary.data?.daily_limit ?? 5;

  const run = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label);
    try {
      await fn();
      bumpReload();
    } catch {
      /* errors surface via the reloaded views */
    } finally {
      setBusy(null);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 20,
          padding: "16px 28px",
          borderBottom: `1px solid ${C.border}`,
          flex: "none",
        }}
      >
        <div>
          <div style={{ fontSize: 17, fontWeight: 600, letterSpacing: "-0.01em" }}>
            Case Feed{summary.data?.product ? ` · ${summary.data.product}` : ""}
          </div>
          <div style={{ fontFamily: mono, fontSize: 10.5, color: C.faint, letterSpacing: ".04em", marginTop: 2 }}>
            SIGNALS WORTH A LOOK · LAST 7 DAYS
          </div>
        </div>
        <div style={{ flex: 1 }} />
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 5 }}>
          <div style={{ display: "flex", gap: 3 }}>
            {Array.from({ length: limit }).map((_, i) => (
              <div
                key={i}
                style={{ width: 20, height: 5, borderRadius: 2, background: i < used ? C.accent : C.track }}
              />
            ))}
          </div>
          <div style={{ fontFamily: mono, fontSize: 11, color: C.muted, fontVariantNumeric: "tabular-nums" }}>
            {used}/{limit} today · ${(summary.data?.spent_today ?? 0).toFixed(2)} spent
          </div>
        </div>
        {reviewer && (
          <>
            <button onClick={() => run("scan", () => api.scan())} disabled={!!busy} className="el-btn"
              style={{ background: "transparent", color: C.muted, border: `1px solid ${C.border3}`, borderRadius: 7, padding: "9px 14px", fontSize: 13, cursor: "pointer" }}>
              {busy === "scan" ? "Scanning…" : "Scan now"}
            </button>
            <button onClick={() => run("triage", () => api.triage(true))} disabled={!!busy} className="el-btn"
              style={{ background: "transparent", color: C.muted, border: `1px solid ${C.border3}`, borderRadius: 7, padding: "9px 14px", fontSize: 13, cursor: "pointer" }}>
              {busy === "triage" ? "Triaging…" : "Run triage"}
            </button>
          </>
        )}
        {reviewer && (
          <button onClick={onNewCase} className="el-btn" style={{ background: C.accent, color: C.onAccent, border: "none", borderRadius: 7, padding: "9px 16px", fontWeight: 600, fontSize: 13, cursor: "pointer" }}>
            + New case
          </button>
        )}
      </div>

      <div style={{ flex: 1, overflow: "auto", padding: "22px 28px" }}>
        {(() => {
          const stale = (sources.data?.connected ?? []).filter((s) => s.stale);
          if (stale.length === 0) return null;
          return (
            <div style={{ maxWidth: 880, marginBottom: 18, padding: "11px 15px", borderRadius: 9,
                          border: `1px solid ${C.accent}55`, background: `${C.accent}12`,
                          fontSize: 12.5, color: C.text3, lineHeight: 1.5 }}>
              ⚠ {stale.length} source{stale.length > 1 ? "s are" : " is"} stale
              {stale[0].staleSince ? ` (since ${stale[0].staleSince})` : ""} — findings below may be based on old data.
              Fix it on the Sources screen.
            </div>
          );
        })()}
        {anomalies.loading && (
          <div style={{ display: "flex", flexDirection: "column", gap: 10, maxWidth: 880 }}>
            {[0, 1, 2].map((i) => (
              <div key={i} style={{ height: 74, borderRadius: 10, background: C.card, border: `1px solid ${C.border2}`, animation: "elSkeleton 1.4s infinite", animationDelay: `${i * 0.15}s` }} />
            ))}
          </div>
        )}
        {anomalies.error && (
          <div style={{ maxWidth: 880, padding: "30px 22px", border: `1px solid ${C.border3}`, borderRadius: 12, background: C.card }}>
            <div style={{ fontSize: 14.5, fontWeight: 600, color: C.text3 }}>Can't reach the investigator</div>
            <div style={{ fontSize: 13, color: C.dim, marginTop: 6, lineHeight: 1.5 }}>
              The backend may be waking up (free tier sleeps after a while). Give it ~30 seconds, then retry.
            </div>
            <button onClick={anomalies.reload} className="el-btn" style={{ marginTop: 14, background: "transparent", color: C.accent, border: `1px solid rgba(240,166,60,.4)`, borderRadius: 7, padding: "8px 16px", fontSize: 13, fontWeight: 500, cursor: "pointer" }}>
              Retry
            </button>
          </div>
        )}
        {anomalies.data && anomalies.data.anomalies.length === 0 && (
          <div style={{ maxWidth: 880, padding: "40px 26px", border: `1px dashed ${C.border4}`, borderRadius: 12 }}>
            <div style={{ fontSize: 15.5, fontWeight: 600, color: C.text3, textAlign: "center" }}>No cases yet</div>
            <div style={{ fontSize: 13, color: C.dim, marginTop: 6, lineHeight: 1.55, maxWidth: 460, margin: "6px auto 14px", textAlign: "center" }}>
              Cases appear two ways. Open one yourself, or let EchoLens find them:
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8, maxWidth: 520, margin: "0 auto", fontSize: 12.5, color: C.muted }}>
              <div><span style={{ fontFamily: mono, color: C.accent }}>1 · Scan now</span> — the detector reads your reviews/issues and flags statistical anomalies.</div>
              <div><span style={{ fontFamily: mono, color: C.accent }}>2 · Run triage</span> — the orchestrator decides which anomalies are worth investigating (and merges duplicates, ignores noise).</div>
              <div><span style={{ fontFamily: mono, color: C.accent }}>3 · Investigate</span> — worthwhile ones become cases here, each with a cited finding.</div>
            </div>
            <div style={{ textAlign: "center" }}>
              <button onClick={onNewCase} className="el-btn" style={{ marginTop: 18, background: "transparent", color: C.accent, border: `1px solid rgba(240,166,60,.4)`, borderRadius: 7, padding: "9px 18px", fontSize: 13, fontWeight: 500, cursor: "pointer" }}>
                + Open a case now
              </button>
            </div>
          </div>
        )}

        {candidates.data && candidates.data.candidates.length > 0 && (
          <div style={{ maxWidth: 880, marginBottom: 26 }}>
            <Label style={{ marginBottom: 4, color: C.info }}>
              INVESTIGATE FROM YOUR FEEDBACK · {candidates.data.candidates.length}
            </Label>
            <p style={{ fontSize: 12.5, color: C.dim, margin: "0 0 12px", lineHeight: 1.55 }}>
              What people complain about most, right now. These aren't spikes — no baseline shift is
              needed to look into them.
            </p>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {candidates.data.candidates.map((c) => (
                <CandidateRow key={c.label} label={c.label} count={c.count}
                              description={c.description} onOpen={onOpenInvestigation}
                              onStarted={bumpReload} />
              ))}
            </div>
          </div>
        )}

        {anomalies.data && anomalies.data.anomalies.length > 0 && (() => {
          const groups: Record<Bucket, typeof anomalies.data.anomalies> = {
            attention: [], active: [], triage: [], resolved: [], dismissed: [],
          };
          for (const a of anomalies.data.anomalies) groups[bucketOf(a)].push(a);
          return (
            <div style={{ maxWidth: 880 }}>
              {SECTIONS.filter((s) => groups[s.key].length > 0).map((s) => (
                <div key={s.key} style={{ marginBottom: 26 }}>
                  <Label style={{ marginBottom: 12, color: s.color }}>
                    {s.label} · {groups[s.key].length}
                  </Label>
                  <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                    {groups[s.key].map((a) => (
                      <AnomalyCard key={a.slug} a={a} onOpen={onOpenInvestigation} />
                    ))}
                  </div>
                </div>
              ))}

              {groups.dismissed.length > 0 && (
                <div style={{ marginBottom: 26 }}>
                  <div onClick={() => setShowDismissed((v) => !v)} style={{ cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 8 }}>
                    <Label style={{ color: C.faint }}>
                      {showDismissed ? "▾" : "▸"} DISMISSED — NOISE · {groups.dismissed.length}
                    </Label>
                  </div>
                  {showDismissed && (
                    <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 12 }}>
                      {groups.dismissed.map((a) => (
                        <AnomalyCard key={a.slug} a={a} onOpen={onOpenInvestigation} />
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })()}
      </div>
    </div>
  );
}

function AnomalyCard({ a, onOpen }: { a: Anomaly; onOpen: (id: number, status?: string) => void }) {
  const sev = severity(a.z);
  const chip = chipFor(a);
  const clickable = a.investigation_id != null;
  const isManual = a.type === "manual";
  // Lead with a problem statement a PM understands; the metric is metadata.
  const title = a.headline || (isManual ? a.description : a.metric);
  const stripe = isManual ? C.info : sev.color;
  return (
    <div
      onClick={() => clickable && onOpen(a.investigation_id!, a.status)}
      className={clickable ? "el-card el-card--click" : "el-card"}
      style={{ display: "flex", alignItems: "stretch", overflow: "hidden", opacity: clickable ? 1 : 0.72 }}
    >
      <div style={{ width: 3, flex: "none", background: stripe }} />
      <div style={{ display: "grid", gridTemplateColumns: "66px 1fr auto", gap: 16, alignItems: "center", padding: "16px 18px", flex: 1, minWidth: 0 }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <div style={{ width: 7, height: 7, borderRadius: "50%", background: stripe, flex: "none", animation: a.status === "investigating" ? "elPulse 1.4s infinite" : "none" }} />
            <div style={{ fontFamily: mono, fontSize: 10.5, letterSpacing: ".03em", color: stripe }}>
              {isManual ? "MANUAL" : sev.label}
            </div>
          </div>
          <div style={{ fontFamily: mono, fontSize: 10, color: C.faint, marginTop: 5, fontVariantNumeric: "tabular-nums" }}>
            {isManual ? "you opened" : `z=${a.z}`}
          </div>
        </div>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 14.5, fontWeight: 600, color: C.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {title}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 7, flexWrap: "wrap" }}>
            <span style={{ fontFamily: mono, fontSize: 10, padding: "2px 7px", border: `1px solid ${C.border3}`, borderRadius: 4, color: C.muted, textTransform: "uppercase" }}>
              {isManual ? "manual case" : a.type.replace(/_/g, " ")}
            </span>
            {!isManual && a.metric && (
              <span style={{ fontFamily: mono, fontSize: 10, color: C.faint, overflow: "hidden",
                             textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 260 }}>
                {a.metric}
              </span>
            )}
            {!isManual && <Spark points={sparkFor(a.z)} color={sev.color} />}
            {a.triage?.reason && <span style={{ fontSize: 12, color: C.dim, fontStyle: "italic" }}>{a.triage.reason}</span>}
          </div>
        </div>
        <Chip {...chip} />
      </div>
    </div>
  );
}

// A complaint theme you can turn into a case. Selecting is separate from
// committing: the row explains itself; only the button starts an investigation.
function CandidateRow({ label, count, description, onOpen, onStarted }: {
  label: string;
  count: number;
  description: string;
  onOpen: (id: number, status?: string) => void;
  onStarted: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const reviewer = canReview();

  const investigate = async () => {
    if (!reviewer || busy) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await api.startInvestigation({ description, tier: "quick" });
      onStarted();
      onOpen(r.investigation_id);
    } catch (e) {
      setErr(String(e).replace("Error: ", ""));
      setBusy(false);
    }
  };

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 15px",
                  background: C.card, border: `1px solid ${C.border2}`, borderRadius: 10 }}>
      <div style={{ width: 3, alignSelf: "stretch", minHeight: 26, borderRadius: 2,
                    background: C.info, flex: "none" }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13.5, color: C.text2 }}>{label}</div>
        <div style={{ fontFamily: mono, fontSize: 10.5, color: C.faint, marginTop: 3 }}>
          {count} negative review{count === 1 ? "" : "s"} mention this
        </div>
        {err && <div style={{ fontSize: 12, color: C.bad, marginTop: 6 }}>{err}</div>}
      </div>
      <button onClick={investigate} disabled={!reviewer || busy} className="el-btn"
        title={reviewer ? "Start a case for this theme" : "You need reviewer access to start an investigation."}
        style={{ background: "transparent", color: reviewer ? C.accent : C.dim,
                 border: `1px solid ${reviewer ? "rgba(240,166,60,.4)" : C.border3}`,
                 borderRadius: 6, padding: "7px 13px", fontSize: 12.5, fontFamily: sans,
                 cursor: reviewer && !busy ? "pointer" : "not-allowed", flex: "none" }}>
        {busy ? "Starting…" : "Investigate"}
      </button>
    </div>
  );
}
