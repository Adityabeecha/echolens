import { useEffect, useState } from "react";
import { Evidence, Investigation, api } from "../api";
import { StatusChip } from "../components/CaseCard";
import { impactLine } from "../format";
import { CASE_TABS, CaseTab, CASE_TAB_LABEL } from "../nav";
import { SEVERITY } from "../status";
import { C, R, S, T, mono } from "../theme";
import { Centered, ErrorState } from "../ui";
import { EngineeringTab } from "./case/EngineeringTab";
import { EvidenceTab } from "./case/EvidenceTab";
import { FindingTab } from "./case/FindingTab";
import { HistoryTab } from "./case/HistoryTab";
import { TraceTab } from "./case/TraceTab";

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
  onReviewed, onGoCalibration, onGoPatterns,
}: Props) {
  const [inv, setInv] = useState<Investigation | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () =>
    api.investigation(caseId)
      .then((d) => { setInv(d); setError(null); })
      .catch((e) => setError(String(e).replace("Error: ", "")));

  // Poll while the case is LIVE — which includes queued work that has not
  // started yet. The interval used to be torn down on the first non-running
  // tick and never re-established, so opening a queued case froze the screen:
  // when the queue promoted it to running seconds later the UI never noticed,
  // and pause/resume left the detail stale until a manual reload.
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setInterval> | null = null;
    const settled = (d: Investigation) =>
      d.status !== "running" && d.case_status !== "queued";
    const tick = () =>
      api.investigation(caseId)
        .then((d) => {
          if (!alive) return;
          setInv(d);
          setError(null);
          if (settled(d) && timer) { clearInterval(timer); timer = null; }
        })
        .catch((e) => alive && setError(String(e).replace("Error: ", "")));
    void tick();
    timer = setInterval(tick, 1500);
    return () => { alive = false; if (timer) clearInterval(timer); };
  }, [caseId]);

  if (error && !inv) {
    return (
      <div style={{ padding: `${S[6]}` }}>
        <ErrorState title={`Couldn't load case #${caseId}`} detail={error} onRetry={load} />
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
    history: inv.history?.length ?? 0,
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      {/* persistent header — the same facts whichever tab you're on */}
      <div style={{ flex: "none", borderBottom: `1px solid ${C.border}`, padding: `${S[3]} ${S[6]} 0` }}>
        <div style={{ display: "flex", alignItems: "center", gap: S[3], flexWrap: "wrap" }}>
          <span onClick={onBack} className="el-btn" role="button" tabIndex={0}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onBack(); }}
            style={{ color: C.dim, cursor: "pointer", fontSize: T.base, whiteSpace: "nowrap" }}>
            ← Back to {backLabel}
          </span>
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
            <span
              onClick={onGoCalibration}
              className="el-btn"
              role="button"
              tabIndex={0}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onGoCalibration(); }}
              title="How well EchoLens's stated confidence has matched your verdicts"
              style={{ fontFamily: mono, fontSize: T.xs, color: C.dim, cursor: "pointer",
                       textDecoration: "underline dotted", textUnderlineOffset: 3 }}
            >
              confidence {finding.confidence.toFixed(2)}
            </span>
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
                  background: "transparent", border: "none", cursor: "pointer",
                  padding: `${S[2]} ${S[3]}`, fontSize: T.base, fontFamily: "inherit",
                  color: active ? C.text : C.muted,
                  borderBottom: `2px solid ${active ? C.accent : "transparent"}`,
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
      {error && (
        <div style={{ flex: "none", margin: "10px 28px 0", padding: `${S[2]} ${S[3]}`,
                      border: `1px solid ${C.bad}55`, background: `${C.bad}12`,
                      borderRadius: R.control, fontSize: T.sm, color: C.text3,
                      display: "flex", alignItems: "center", gap: S[2] }}>
          <span style={{ color: C.bad }}>⚠</span>
          <span style={{ flex: 1 }}>Couldn't refresh this case — {error}</span>
          <span onClick={load} className="el-btn" role="button" tabIndex={0}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") load(); }}
            style={{ color: C.accent, cursor: "pointer" }}>Retry</span>
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
        {tab === "history" && <HistoryTab inv={inv} onOpenCase={onOpenCase} />}
      </div>
    </div>
  );
}
