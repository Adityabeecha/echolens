import { useEffect, useRef, useState } from "react";
import { Evidence, Investigation, api, errorMessage } from "../api";
import { StatusChip } from "../components/CaseCard";
import { impactLine } from "../format";
import { CASE_TABS, CaseTab, CASE_TAB_LABEL } from "../nav";
import { SEVERITY } from "../status";
import { C, R, S, T, mono } from "../theme";
import { Centered, ErrorState, WorkflowRail } from "../ui";
import { EngineeringTab } from "./case/EngineeringTab";
import { EvidenceTab } from "./case/EvidenceTab";
import { FindingTab } from "./case/FindingTab";
import { DiscussionTab } from "./case/DiscussionTab";
import { HistoryTab } from "./case/HistoryTab";
import { TraceTab } from "./case/TraceTab";
import { Icon } from "../components/Icon";

interface Props {
  caseId: number;
  tab: CaseTab;
  productName: string | null;
  onTab: (tab: CaseTab) => void;
  onBack: () => void;
  backLabel: string;
  onOpenEvidence: (e: Evidence) => void;
  onOpenCase: (id: number, status?: string) => void;
  onReviewed: () => void;
  onGoCalibration: () => void;
  onGoPatterns: () => void;
}

/**
 * One case, one route, five tabs.
 *
 * A case used to be spread across two screens with their own URLs — the trace
 * at /case/{id} and the answer at /case/{id}/finding — so "send me that case"
 * meant sending one of two halves, and Back could return you to the other half
 * of the same thing. Everything about a case now lives here, with the tab in
 * the URL so a specific view is still linkable.
 */
export function CaseDetail({
  caseId, tab, productName, onTab, onBack, backLabel, onOpenEvidence, onOpenCase,
  onReviewed, onGoCalibration, onGoPatterns
}: Props) {
  const [inv, setInv] = useState<Investigation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pollGeneration, setPollGeneration] = useState(0);

  // Monotonic sequence guard, matching the polling effect below. Retry calls
  // this, and a slow response used to be able to land AFTER a newer poll tick
  // and overwrite it — the one path in this file without the guard the rest of
  // it applies.
  const loadSeq = useRef(0);
  const load = () => {
    const mine = ++loadSeq.current;
    return api.investigation(caseId)
      .then((d) => { if (mine === loadSeq.current) { setInv(d); setError(null); } })
      .catch((e) => { if (mine === loadSeq.current) setError(errorMessage(e)); });
  };

  // Restart the polling effect, not just one request. The old Retry called
  // load() once after the poller had stopped at MAX_FAILURES, so a backend that
  // was still waking on that exact request left the button permanently stuck.
  const retry = () => {
    setError(null);
    setPollGeneration((n) => n + 1);
  };

  // Poll while the case is LIVE — which includes queued work that has not
  // started yet. The interval used to be torn down on the first non-running
  // tick and never re-established, so opening a queued case froze the screen:
  // when the queue promoted it to running seconds later the UI never noticed,
  // and pause/resume left the detail stale until a manual reload.
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const settled = (d: Investigation) =>
      d.status !== "running" && d.case_status !== "queued";
    // Consecutive failures before giving up. The catch used to set `error` and
    // keep polling: a deleted case, a case in another product, or a down
    // backend was hit every 1500ms forever, because the check that stops the
    // interval only ran on the success path.
    const MAX_FAILURES = 4;
    let failures = 0;
    let finished = false;
    const stop = () => {
      finished = true;
      if (timer) { clearTimeout(timer); timer = null; }
    };
    const schedule = () => {
      if (alive && !finished) timer = setTimeout(() => { void tick(); }, 1500);
    };
    const tick = async () => {
      const mine = ++loadSeq.current;
      try {
        const d = await api.investigation(caseId);
        if (!alive || mine !== loadSeq.current) return;
        failures = 0;
        setInv(d);
        setError(null);
        if (settled(d)) stop();
      } catch (e) {
        if (!alive || mine !== loadSeq.current) return;
        setError(errorMessage(e));
        if (++failures >= MAX_FAILURES) stop();   // Retry restarts it
      } finally {
        // Schedule only AFTER this request finishes. setInterval allowed slow
        // case responses to overlap; every new request advanced loadSeq before
        // the previous one landed, so no response was ever accepted and the UI
        // stayed on "Loading case" while hammering the backend toward a 503.
        if (alive && !finished) schedule();
      }
    };
    void tick();
    return () => { alive = false; stop(); };
  }, [caseId, pollGeneration]);

  if (error && !inv) {
    return (
      <div style={{ padding: `${S[6]}` }}>
        <ErrorState title={`Couldn't load case #${caseId}`} detail={error} onRetry={retry} />
      </div>
    );
  }
  if (!inv) return <Centered>Loading case #{caseId}…</Centered>;

  const finding = inv.finding;
  const sev = finding?.severity ? SEVERITY[finding.severity.band] : null;
  const impact = impactLine(finding?.impact ?? null);
  const running = inv.status === "running";

  // Which tabs are worth offering. A tab that opens onto "nothing yet" is a
  // dead end; the ones that would be empty say so in the label instead.
  const counts: Partial<Record<CaseTab, number>> = {
    evidence: inv.evidence.length,
    history: inv.history?.length ?? 0
  };

  return (
    <div className="el-case-detail" style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      {/* persistent header — the same facts whichever tab you're on */}
      <div className="el-case-dossier-header" style={{ flex: "none", borderBottom: `1px solid ${C.border}`, padding: `${S[3]} ${S[6]} 0` }}>
        <div style={{ display: "flex", alignItems: "center", gap: S[3], flexWrap: "wrap" }}>
          <button onClick={onBack} className="el-btn"
            style={{ color: C.dim, fontSize: T.base, whiteSpace: "nowrap" }}>
            <Icon name="chevronLeft" size={15} /> Back to {backLabel}
          </button>
          <div style={{ width: 1, height: 16, background: C.border2 }} />
          <span style={{ fontFamily: mono, fontSize: T.sm, color: C.accent }}>CASE #{caseId}</span>
          <span style={{ fontFamily: mono, fontSize: T.xs, color: C.faint }}>
            {productName ? `· ${productName}` : ""}
          </span>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: S[3], marginTop: S[2],
                      flexWrap: "wrap" }}>
          <div style={{ fontSize: T.lg, fontWeight: 600, letterSpacing: "-.01em",
                        maxWidth: 660, lineHeight: "var(--el-lh-snug)" }}>
            {inv.title}
          </div>
          <StatusChip status={inv.case_status} />
          {sev && (
            <span style={{ fontFamily: mono, fontSize: T.micro, letterSpacing: ".04em",
                           padding: `${S[1]} ${S[2]}`, borderRadius: R.sm, color: sev.color,
                           border: `1px solid ${sev.color}55`, textTransform: "uppercase" }}>
              {sev.label} severity
            </span>
          )}
          {impact && <span style={{ fontSize: T.sm, color: C.muted }}>{impact}</span>}
          {finding?.confidence != null && (
            <button
              onClick={onGoCalibration}
              className="el-btn"
              title="How well EchoLens's stated confidence has matched your verdicts"
              style={{ fontFamily: mono, fontSize: T.xs, color: C.dim,
                       textDecoration: "underline dotted", textUnderlineOffset: 3 }}
            >
              confidence {finding.confidence.toFixed(2)}
            </button>
          )}
        </div>

        {inv.case_why && (
          <div style={{ fontSize: T.sm, color: C.dim, marginTop: S[1] }}>{inv.case_why}</div>
        )}

        <div style={{ display: "flex", gap: S[1], marginTop: S[3] }}>
          {CASE_TABS.map((t) => {
            const active = t === tab;
            return (
              <button
                key={t}
                onClick={() => onTab(t)}
                className="el-btn"
                style={{
                  background: "transparent", border: "none",
                  padding: `${S[2]} ${S[3]}`, fontSize: T.base, fontFamily: "inherit",
                  color: active ? C.text : C.muted,
                  borderBottom: `2px solid ${active ? C.accent : "transparent"}`
                }}
              >
                {CASE_TAB_LABEL[t]}
                {counts[t] != null && counts[t]! > 0 && (
                  <span style={{ fontFamily: mono, fontSize: T.micro, color: C.faint, marginLeft: 6 }}>
                    {counts[t]}
                  </span>
                )}
                {t === "trace" && running && (
                  <span style={{ width: 6, height: 6, borderRadius: "50%", background: C.accent,
                                 display: "inline-block", marginLeft: 7,
                                 animation: "elPulse 1.4s infinite" }} />
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* An error AFTER the first successful load used to be stored and never
          rendered, so a failed refresh left stale data on screen while a toast
          said the action had succeeded — the UI contradicting itself. */}
      <WorkflowRail active={running ? "investigation" : finding ? "finding" : "signal"} />

      {error && (
        <div style={{ flex: "none", margin: "10px 28px 0", padding: `${S[2]} ${S[3]}`,
                      border: `1px solid ${C.bad}55`, background: `${C.bad}12`,
                      borderRadius: R.control, fontSize: T.sm, color: C.text3,
                      display: "flex", alignItems: "center", gap: S[2] }}>
          <Icon name="warning" size={14} style={{ color: C.bad }} />
          <span style={{ flex: 1 }}>Couldn't refresh this case — {error}</span>
          <button onClick={retry} className="el-btn"
            style={{ color: C.accent }}>Retry</button>
        </div>
      )}

      <div style={{ flex: 1, minHeight: 0, overflow: "hidden", display: "flex" }}>
        {tab === "finding" && (
          <FindingTab inv={inv} onOpenEvidence={onOpenEvidence} onReload={load}
                      onReviewed={onReviewed} onOpenTrace={() => onTab("trace")}
                      onOpenCase={onOpenCase} />
        )}
        {tab === "trace" && (
          <TraceTab inv={inv} onOpenEvidence={onOpenEvidence} onReload={load} />
        )}
        {tab === "evidence" && <EvidenceTab inv={inv} onOpenEvidence={onOpenEvidence} />}
        {tab === "engineering" && (
          <EngineeringTab inv={inv} onReload={load} onGoPatterns={onGoPatterns} />
        )}
        {tab === "discussion" && <DiscussionTab caseId={caseId} />}
        {tab === "history" && <HistoryTab inv={inv} onOpenCase={onOpenCase} />}
      </div>
    </div>
  );
}
