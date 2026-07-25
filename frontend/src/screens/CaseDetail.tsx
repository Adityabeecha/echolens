import { useEffect, useState } from "react";
import { Evidence, Investigation, api } from "../api";
import { StatusChip } from "../components/CaseCard";
import { impactLine } from "../format";
import { CASE_TABS, CaseTab, CASE_TAB_LABEL } from "../nav";
import { SEVERITY } from "../status";
import { C, mono } from "../theme";
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

  // Poll while the case is live; stop the moment it settles.
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setInterval> | null = null;
    const tick = () =>
      api.investigation(caseId)
        .then((d) => {
          if (!alive) return;
          setInv(d);
          setError(null);
          if (d.status !== "running" && timer) { clearInterval(timer); timer = null; }
        })
        .catch((e) => alive && setError(String(e).replace("Error: ", "")));
    tick();
    timer = setInterval(tick, 1500);
    return () => { alive = false; if (timer) clearInterval(timer); };
  }, [caseId]);

  if (error && !inv) {
    return (
      <div style={{ padding: "28px" }}>
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
      <div style={{ flex: "none", borderBottom: `1px solid ${C.border}`, padding: "13px 28px 0" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
          <span onClick={onBack} className="el-btn" role="button" tabIndex={0}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onBack(); }}
            style={{ color: C.dim, cursor: "pointer", fontSize: 13, whiteSpace: "nowrap" }}>
            ← Back to {backLabel}
          </span>
          <div style={{ width: 1, height: 16, background: C.border2 }} />
          <span style={{ fontFamily: mono, fontSize: 12, color: C.accent }}>CASE #{caseId}</span>
          <span style={{ fontFamily: mono, fontSize: 11, color: C.faint }}>
            {productName ? `· ${productName}` : ""}
          </span>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 9,
                      flexWrap: "wrap" }}>
          <div style={{ fontSize: 17, fontWeight: 600, letterSpacing: "-.01em",
                        maxWidth: 660, lineHeight: 1.35 }}>
            {inv.title}
          </div>
          <StatusChip status={inv.case_status} />
          {sev && (
            <span style={{ fontFamily: mono, fontSize: 10, letterSpacing: ".04em",
                           padding: "3px 8px", borderRadius: 4, color: sev.color,
                           border: `1px solid ${sev.color}55`, textTransform: "uppercase" }}>
              {sev.label} severity
            </span>
          )}
          {impact && <span style={{ fontSize: 12.5, color: C.muted }}>{impact}</span>}
          {finding?.confidence != null && (
            <span
              onClick={onGoCalibration}
              className="el-btn"
              role="button"
              tabIndex={0}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onGoCalibration(); }}
              title="How well EchoLens's stated confidence has matched your verdicts"
              style={{ fontFamily: mono, fontSize: 11, color: C.dim, cursor: "pointer",
                       textDecoration: "underline dotted", textUnderlineOffset: 3 }}
            >
              confidence {finding.confidence.toFixed(2)}
            </span>
          )}
        </div>

        {inv.case_why && (
          <div style={{ fontSize: 12.5, color: C.dim, marginTop: 6 }}>{inv.case_why}</div>
        )}

        <div style={{ display: "flex", gap: 3, marginTop: 12 }}>
          {CASE_TABS.map((t) => {
            const active = t === tab;
            return (
              <button
                key={t}
                onClick={() => onTab(t)}
                className="el-btn"
                style={{
                  background: "transparent", border: "none", cursor: "pointer",
                  padding: "8px 12px", fontSize: 13, fontFamily: "inherit",
                  color: active ? C.text : C.muted,
                  borderBottom: `2px solid ${active ? C.accent : "transparent"}`,
                }}
              >
                {CASE_TAB_LABEL[t]}
                {counts[t] != null && counts[t]! > 0 && (
                  <span style={{ fontFamily: mono, fontSize: 10, color: C.faint, marginLeft: 6 }}>
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
