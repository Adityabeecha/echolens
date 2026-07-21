import { useState } from "react";
import { Anomaly, QueueItem, ThemeCandidate, api, canReview } from "../api";
import { useAsync } from "../hooks";
import { C, mono, sans } from "../theme";
import { Chip, Dot, Label, Spark, sparkFor } from "../ui";

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
  const queue = useAsync(() => api.queue(), [reloadKey]);
  const [busy, setBusy] = useState<string | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [queueError, setQueueError] = useState<string | null>(null);
  const [showDismissed, setShowDismissed] = useState(false);
  const reviewer = canReview();

  const used = summary.data?.investigations_today ?? 0;
  const limit = summary.data?.daily_limit ?? 5;

  // Only themes not already queued or investigated can be picked.
  const selectable = (candidates.data?.candidates ?? []).filter((c) => !c.existing);
  const allSelected = selectable.length > 0 && selected.length === selectable.length;
  const toggle = (slug: string) =>
    setSelected((s) => (s.includes(slug) ? s.filter((x) => x !== slug) : [...s, slug]));
  const toggleAll = () =>
    setSelected(allSelected ? [] : selectable.map((c) => c.slug));

  const refreshAll = () => {
    setSelected([]);
    bumpReload();
  };

  // Rough, and labelled as rough: a quick-tier case is a handful of LLM calls.
  const estCost = (selected.length * 0.008).toFixed(3);
  const remaining = queue.data?.remaining_today ?? Math.max(0, limit - used);
  const willDefer = Math.max(0, selected.length - remaining);

  const queueSelected = async () => {
    if (selected.length === 0) return;
    setBusy("queue");
    setQueueError(null);
    try {
      const statements: Record<string, string> = {};
      for (const c of candidates.data?.candidates ?? []) {
        if (selected.includes(c.slug)) statements[c.slug] = c.statement;
      }
      await api.queueThemes(selected, statements);
      refreshAll();
    } catch (e) {
      setQueueError(String(e).replace("Error: ", ""));
    } finally {
      setBusy(null);
    }
  };

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
            <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 4 }}>
              <Label style={{ color: C.info }}>
                INVESTIGATE FROM YOUR FEEDBACK · {candidates.data.candidates.length}
              </Label>
              {selectable.length > 0 && (
                <span onClick={toggleAll} className="el-btn" role="button" tabIndex={0}
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") toggleAll(); }}
                  style={{ fontFamily: mono, fontSize: 10, color: C.dim, cursor: "pointer" }}>
                  {allSelected ? "CLEAR" : "SELECT ALL"}
                </span>
              )}
            </div>
            <p style={{ fontSize: 12.5, color: C.dim, margin: "0 0 12px", lineHeight: 1.55 }}>
              Complaints grouped by what they're actually about. These aren't spikes — no baseline
              shift is needed to look into them. Pick any number; they run one at a time.
            </p>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {candidates.data.candidates.map((c) => (
                <ThemeCard
                  key={c.slug}
                  theme={c}
                  selected={selected.includes(c.slug)}
                  onToggle={() => toggle(c.slug)}
                  onOpen={onOpenInvestigation}
                />
              ))}
            </div>
          </div>
        )}

        {queue.data && (queue.data.running.length > 0 || queue.data.queued.length > 0) && (
          <div style={{ maxWidth: 880, marginBottom: 26 }}>
            <Label style={{ marginBottom: 12, color: C.accent }}>
              ACTIVE &amp; QUEUED · {queue.data.running.length + queue.data.queued.length}
            </Label>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {queue.data.running.map((r) => (
                <div key={`run-${r.queue_id}`} className="el-card"
                  onClick={() => r.investigation_id && onOpenInvestigation(r.investigation_id)}
                  style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 16px",
                           cursor: r.investigation_id ? "pointer" : "default" }}>
                  <Dot color={C.accent} pulse />
                  <span style={{ fontSize: 13.5, color: C.text2, flex: 1, minWidth: 0,
                                 overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {r.title}
                  </span>
                  <span style={{ fontFamily: mono, fontSize: 10.5, color: C.accent }}>RUNNING</span>
                </div>
              ))}
              {queue.data.queued.map((q) => (
                <QueuedRow key={q.queue_id} item={q} onCancelled={refreshAll} />
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

      {/* One commit for any number of selections — the per-card buttons used to
          fight the daily budget one click at a time. */}
      {reviewer && selected.length > 0 && (
        <div style={{ flex: "none", borderTop: `1px solid ${C.border2}`, background: C.bgRaised,
                      padding: "12px 28px", display: "flex", alignItems: "center", gap: 16,
                      flexWrap: "wrap" }}>
          <span style={{ fontSize: 13.5, color: C.text2 }}>
            <strong>{selected.length}</strong> theme{selected.length === 1 ? "" : "s"} selected
          </span>
          <span style={{ fontFamily: mono, fontSize: 11.5, color: C.faint }}>
            ~${estCost} · runs one at a time
          </span>
          {willDefer > 0 && (
            <span style={{ fontFamily: mono, fontSize: 11.5, color: C.accent }}>
              {willDefer} past today's limit — queued for tomorrow
            </span>
          )}
          {queueError && (
            <span style={{ fontSize: 12.5, color: C.bad }}>{queueError}</span>
          )}
          <div style={{ flex: 1 }} />
          <button onClick={() => setSelected([])} className="el-btn"
            style={{ background: "transparent", color: C.muted, border: `1px solid ${C.border3}`,
                     borderRadius: 7, padding: "9px 14px", fontSize: 13, cursor: "pointer" }}>
            Clear
          </button>
          <button onClick={queueSelected} disabled={busy === "queue"} className="el-btn"
            style={{ background: C.accent, color: C.onAccent, border: "none", borderRadius: 7,
                     padding: "9px 18px", fontWeight: 600, fontSize: 13,
                     cursor: busy === "queue" ? "wait" : "pointer" }}>
            {busy === "queue" ? "Queueing…" : `Investigate selected (${selected.length})`}
          </button>
        </div>
      )}
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

// A clustered complaint. Selecting is separate from committing: you tick what
// matters, then commit once from the action bar.
function ThemeCard({ theme, selected, onToggle, onOpen }: {
  theme: ThemeCandidate;
  selected: boolean;
  onToggle: () => void;
  onOpen: (id: number, status?: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const taken = theme.existing;
  const trend = theme.trend === "up" ? { s: "▲", c: C.bad } : theme.trend === "down" ? { s: "▼", c: C.good } : null;

  return (
    <div className="el-card" style={{ padding: "13px 16px", opacity: taken ? 0.72 : 1 }}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
        {taken ? (
          <span style={{ width: 16, flex: "none", fontFamily: mono, fontSize: 11, color: C.good,
                         lineHeight: "20px", textAlign: "center" }}>✓</span>
        ) : (
          <input
            type="checkbox"
            checked={selected}
            onChange={onToggle}
            aria-label={`Select: ${theme.statement}`}
            style={{ width: 15, height: 15, marginTop: 3, flex: "none",
                     accentColor: C.accent, cursor: "pointer" }}
          />
        )}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13.5, color: C.text2, lineHeight: 1.45 }}>{theme.statement}</div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 5, flexWrap: "wrap" }}>
            <span style={{ fontFamily: mono, fontSize: 10.5, color: C.faint }}>
              {theme.count} review{theme.count === 1 ? "" : "s"}
            </span>
            {trend && (
              <span style={{ fontFamily: mono, fontSize: 10.5, color: trend.c }}>
                {trend.s} {theme.trend}
              </span>
            )}
            {theme.label_source === "verbatim" && (
              <span title="Shown in a customer's own words — the generated label wasn't confident enough."
                style={{ fontFamily: mono, fontSize: 9.5, padding: "1px 6px", borderRadius: 9,
                         background: C.hover, color: C.faint }}>
                VERBATIM
              </span>
            )}
            {theme.verbatims.length > 1 && (
              <span onClick={() => setOpen((o) => !o)} className="el-btn" role="button" tabIndex={0}
                onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") setOpen((o) => !o); }}
                style={{ fontFamily: mono, fontSize: 10.5, color: C.dim, cursor: "pointer" }}>
                {open ? "▾ hide reviews" : `▸ ${theme.verbatims.length} reviews`}
              </span>
            )}
          </div>
          {open && (
            <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 9,
                          paddingLeft: 10, borderLeft: `2px solid ${C.border3}` }}>
              {theme.verbatims.map((v, i) => (
                <div key={i} style={{ fontSize: 12.5, color: C.dim, lineHeight: 1.5 }}>“{v}”</div>
              ))}
            </div>
          )}
        </div>
        {taken && (
          <span
            onClick={() => taken.investigation_id && onOpen(taken.investigation_id)}
            className={taken.investigation_id ? "el-btn" : undefined}
            style={{ fontSize: 12, color: taken.investigation_id ? C.accent : C.dim,
                     cursor: taken.investigation_id ? "pointer" : "default",
                     whiteSpace: "nowrap", flex: "none" }}>
            {taken.reason === "queued" ? "already queued"
              : taken.investigation_id ? "view case →" : "already investigated"}
          </span>
        )}
      </div>
    </div>
  );
}

function QueuedRow({ item, onCancelled }: { item: QueueItem; onCancelled: () => void }) {
  const [busy, setBusy] = useState(false);
  const deferred = item.status === "deferred";
  const cancel = async () => {
    setBusy(true);
    try {
      await api.cancelQueued(item.queue_id);
      onCancelled();
    } catch {
      setBusy(false);
    }
  };
  return (
    <div className="el-card" style={{ display: "flex", alignItems: "center", gap: 12,
                                      padding: "12px 16px" }}>
      <span style={{ fontFamily: mono, fontSize: 10.5, color: deferred ? C.dim : C.text3,
                     width: 62, flex: "none" }}>
        {deferred ? "WAITING" : `QUEUED #${item.position}`}
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, color: C.text3, overflow: "hidden",
                      textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{item.title}</div>
        {item.note && (
          <div style={{ fontFamily: mono, fontSize: 10, color: C.accent, marginTop: 3 }}>
            {item.note}
          </div>
        )}
      </div>
      <button onClick={cancel} disabled={busy} className="el-btn"
        style={{ background: "transparent", color: C.dim, border: `1px solid ${C.border3}`,
                 borderRadius: 6, padding: "5px 11px", fontSize: 12, fontFamily: sans,
                 cursor: "pointer", flex: "none" }}>
        {busy ? "…" : "Cancel"}
      </button>
    </div>
  );
}
