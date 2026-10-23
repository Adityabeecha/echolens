import { useEffect, useRef, useState } from "react";
import { Evidence, Hypothesis, Investigation, api, canReview } from "../../api";
import { withToast } from "../../components/Toast";
import { sourceLabel } from "../../format";
import { useTrace } from "../../hooks";
import { C, R, S, T, mono } from "../../theme";
import { Button, Label } from "../../ui";
import { Icon } from "../../components/Icon";
import { TraceRow } from "./TraceTab";

export type InspectorMode = "evidence" | "trace";

/** A ref that is a real address gets a link; anything else stays text. */
function refHref(e: Evidence, repo?: string | null): string | null {
  if (/^https?:\/\//i.test(e.ref)) return e.ref;
  const gh = e.ref.match(/^([\w.-]+\/[\w.-]+)#(\d+)$/);
  if (gh) return `https://github.com/${gh[1]}/issues/${gh[2]}`;
  if (repo && /^#\d+$/.test(e.ref)) return `https://github.com/${repo}/issues/${e.ref.slice(1)}`;
  return null;
}

/**
 * One citation, in full: the verbatim quote, where it came from, and which
 * possible causes it bears on. Shared by the wide-screen Inspector and the
 * narrow-screen sheet so a claim is checked the same way on both.
 */
export function EvidenceDetail({ evidence, inv, onReload }: {
  evidence: Evidence;
  inv: Investigation;
  onReload?: () => Promise<unknown> | void;
}) {
  const [rejecting, setRejecting] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [verdict, setVerdict] = useState<string | null>(null);
  useEffect(() => { setRejecting(false); setNote(""); setVerdict(null); }, [evidence.id]);

  const byId = new Map(inv.hypotheses.map((h) => [h.id, h]));
  const supports = evidence.supports.map((id) => byId.get(id)).filter((h): h is Hypothesis => !!h);
  const contradicts = evidence.contradicts.map((id) => byId.get(id)).filter((h): h is Hypothesis => !!h);
  const href = refHref(evidence);
  const f = inv.finding;
  const rejected = !!evidence.rejected;
  const canReject = canReview() && !!f && f.status !== "challenged" && !rejected && !!onReload;

  const reject = async () => {
    if (!f) return;
    setBusy(true);
    const r = await withToast(() => api.rejectEvidence(f.id, evidence.id, note.trim()), {
      success: "Evidence rejected — the two-source rule was re-checked.",
      failure: "Couldn't reject that evidence"
    });
    setBusy(false);
    if (!r) return;
    setVerdict(r.message);
    setRejecting(false);
    await onReload?.();
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: S[3] }}>
      <div style={{ display: "flex", alignItems: "center", gap: S[2], flexWrap: "wrap" }}>
        <span style={{ fontFamily: mono, fontSize: T.base, color: rejected ? C.faint : C.accent }}>
          {evidence.id}
        </span>
        <span style={{ fontFamily: mono, fontSize: T.micro, padding: `0 ${S[2]}`,
                       border: `1px solid ${C.border3}`, borderRadius: R.sm, color: C.muted }}>
          {sourceLabel(evidence.source)}
        </span>
        {rejected && (
          <span style={{ fontFamily: mono, fontSize: T.micro, padding: `0 ${S[2]}`, borderRadius: R.sm,
                         background: C.badBg, border: `1px solid ${C.badLine}`, color: C.bad }}>
            rejected by reviewer
          </span>
        )}
      </div>

      <blockquote style={{ margin: 0, padding: 16, background: C.bgRaised, border: `1px solid ${C.border}`,
                           borderRadius: R.control, fontSize: T.base, lineHeight: "var(--el-lh-normal)",
                           color: rejected ? C.dim : C.text2, overflowWrap: "anywhere",
                           textDecoration: rejected ? "line-through" : undefined,
                           textDecorationColor: C.ghost }}>
        “{evidence.snippet}”
      </blockquote>

      <div style={{ fontSize: T.sm, color: C.muted, lineHeight: "var(--el-lh-normal)",
                    display: "flex", flexDirection: "column", gap: S[1] }}>
        <div style={{ overflowWrap: "anywhere" }}>
          <span style={{ color: C.faint }}>Source</span> —{" "}
          {href ? (
            <a href={href} target="_blank" rel="noreferrer noopener"
               style={{ color: C.accent, fontFamily: mono }}>
              {evidence.ref} <Icon name="external" size={11} style={{ display: "inline" }} />
            </a>
          ) : <span style={{ fontFamily: mono }}>{evidence.ref}</span>}
        </div>
        <div style={{ overflowWrap: "anywhere" }}>
          <span style={{ color: C.faint }}>Found by</span> —{" "}
          <span style={{ fontFamily: mono }}>{evidence.retrieved_by}</span>
        </div>
      </div>

      <div>
        <Label style={{ marginBottom: S[2] }}>BEARS ON</Label>
        {supports.length === 0 && contradicts.length === 0 && (
          <div style={{ fontSize: T.sm, color: C.dim }}>Not linked to any possible cause.</div>
        )}
        <div style={{ display: "flex", flexDirection: "column", gap: S[2] }}>
          {supports.map((h) => <HypLine key={`s-${h.id}`} h={h} stance="supports" />)}
          {contradicts.map((h) => <HypLine key={`c-${h.id}`} h={h} stance="contradicts" />)}
        </div>
      </div>

      {rejected && evidence.rejected?.note && (
        <div style={{ fontSize: T.sm, color: C.text3, fontStyle: "italic" }}>
          Reviewer's note: “{evidence.rejected.note}”
        </div>
      )}
      {verdict && (
        <div role="status" style={{ fontSize: T.sm, color: C.text2, padding: `${S[2]} ${S[3]}`,
                                    background: C.card, border: `1px solid ${C.border3}`,
                                    borderRadius: R.control, lineHeight: "var(--el-lh-normal)" }}>
          {verdict}
        </div>
      )}

      {canReject && !rejecting && (
        <Button variant="ghost" size="sm" icon="close" onClick={() => setRejecting(true)}
                style={{ alignSelf: "flex-start" }}>
          This quote doesn't support it
        </Button>
      )}
      {canReject && rejecting && (
        <div style={{ display: "flex", flexDirection: "column", gap: S[2], padding: S[3],
                      background: C.card, border: `1px solid ${C.border2}`, borderRadius: R.control }}>
          <div style={{ fontSize: T.sm, color: C.muted, lineHeight: "var(--el-lh-normal)" }}>
            Strike this item from the finding. EchoLens re-checks whether two independent sources
            still agree without it — the case is not re-opened.
          </div>
          <textarea value={note} onChange={(e) => setNote(e.target.value)}
            aria-label="Why this quote doesn't support the finding"
            placeholder="Optional: why it doesn't support it (e.g. it's about charging, not drain)"
            style={{ width: "100%", height: 60, background: C.bgRaised, border: `1px solid ${C.border3}`,
                     borderRadius: R.control, color: C.text, fontFamily: "inherit", fontSize: T.sm,
                     padding: S[2], resize: "vertical", boxSizing: "border-box" }} />
          <div style={{ display: "flex", gap: S[2] }}>
            <Button variant="danger" size="sm" loading={busy} onClick={reject}>
              {busy ? "Rejecting…" : "Reject evidence"}
            </Button>
            <Button variant="quiet" size="sm" onClick={() => setRejecting(false)}>Cancel</Button>
          </div>
        </div>
      )}

      <div style={{ fontSize: T.xs, color: C.faint, fontStyle: "italic" }}>
        Raw source preserved verbatim. EchoLens never paraphrases evidence into the record.
      </div>
    </div>
  );
}

function HypLine({ h, stance }: { h: Hypothesis; stance: "supports" | "contradicts" }) {
  const color = stance === "supports" ? C.good : C.bad;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: S[2], alignItems: "baseline",
                  fontSize: T.sm, lineHeight: "var(--el-lh-snug)" }}>
      <span style={{ fontFamily: mono, fontSize: T.micro, padding: `0 ${S[1]}`, borderRadius: R.sm,
                     color, border: `1px solid ${stance === "supports" ? C.goodLine : C.badLine}` }}>
        {stance} {h.id}
      </span>
      <span style={{ color: h.status === "rejected" ? C.dim : C.text3,
                     textDecoration: h.status === "rejected" ? "line-through" : undefined }}>
        {h.statement}
        {h.status === "supported" && <span style={{ color: C.good }}> · proven cause</span>}
        {h.status === "rejected" && <span style={{ color: C.dim }}> · ruled out</span>}
      </span>
    </div>
  );
}

/** The live (or replayable) reasoning trace, compact enough for the side pane. */
function InspectorTrace({ inv, onPick }: { inv: Investigation; onPick: (e: Evidence) => void }) {
  const { steps } = useTrace(inv.id);
  const [replayIdx, setReplayIdx] = useState<number | null>(null);
  const ref = useRef<HTMLDivElement | null>(null);
  const running = inv.status === "running";

  useEffect(() => {
    if (replayIdx === null || replayIdx >= steps.length) return;
    const t = setTimeout(() => setReplayIdx((i) => (i === null ? null : i + 1)), 600);
    return () => clearTimeout(t);
  }, [replayIdx, steps.length]);
  useEffect(() => {
    if ((running || replayIdx !== null) && ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [steps, running, replayIdx]);

  const shown = replayIdx === null ? steps : steps.slice(0, replayIdx);
  return (
    <div style={{ display: "flex", flexDirection: "column", minHeight: 0, flex: 1 }}>
      <div style={{ display: "flex", alignItems: "center", gap: S[2], marginBottom: S[3] }}>
        <Label>{running ? "LIVE TRACE" : "TRACE"} · {steps.length} {steps.length === 1 ? "STEP" : "STEPS"}</Label>
        <div style={{ flex: 1 }} />
        {!running && steps.length > 0 && (
          replayIdx === null
            ? <Button variant="ghost" size="sm" icon="play" onClick={() => setReplayIdx(0)}>Replay</Button>
            : <Button variant="quiet" size="sm" icon="close" onClick={() => setReplayIdx(null)}>
                Stop replay {replayIdx}/{steps.length}
              </Button>
        )}
      </div>
      <div ref={ref} style={{ flex: 1, minHeight: 0, overflow: "auto", paddingRight: S[1] }}>
        {shown.map((s, i) => (
          <TraceRow key={s.seq} step={s} last={i === shown.length - 1} selHyp={null}
                    onOpenEvidence={onPick} evidence={inv.evidence} />
        ))}
        {steps.length === 0 && (
          <div style={{ color: C.dim, fontSize: T.sm }}>
            {running ? "Waiting for the first reasoning step…" : "No trace was recorded for this case."}
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * The right-hand pane on wide screens. Checking a claim used to mean leaving
 * the finding for another tab; now the brief stays put and the thing you
 * clicked — a citation, or the reasoning that produced it — opens beside it.
 */
export function Inspector({ inv, mode, onMode, evidence, onPick, onReload }: {
  inv: Investigation;
  mode: InspectorMode;
  onMode: (m: InspectorMode) => void;
  evidence: Evidence | null;
  onPick: (e: Evidence) => void;
  onReload: () => Promise<unknown> | void;
}) {
  const running = inv.status === "running";
  return (
    <aside aria-label="Inspector" className="el-case-inspector"
      style={{ display: "flex", flexDirection: "column", minHeight: 0, minWidth: 0,
               borderLeft: `1px solid ${C.border}`, background: C.bg }}>
      <div role="tablist" aria-label="Inspector view"
        style={{ flex: "none", display: "flex", gap: S[1], padding: `${S[2]} ${S[4]}`,
                 borderBottom: `1px solid ${C.border}` }}>
        {(["evidence", "trace"] as const).map((m) => (
          <button key={m} role="tab" aria-selected={mode === m} onClick={() => onMode(m)}
            className="el-btn el-btn--sm"
            style={{ padding: `${S[1]} ${S[3]}`, borderRadius: R.pill, fontSize: T.sm,
                     border: `1px solid ${mode === m ? C.accentLine : "transparent"}`,
                     background: mode === m ? C.accentBg : "transparent",
                     color: mode === m ? C.accent : C.muted }}>
            {m === "evidence" ? "Evidence" : "Investigation trace"}
            {m === "trace" && running && (
              <span aria-hidden style={{ width: 6, height: 6, borderRadius: "50%", background: C.accent,
                                         display: "inline-block", marginLeft: 6,
                                         animation: "elPulse 1.4s infinite" }} />
            )}
          </button>
        ))}
      </div>
      <div style={{ flex: 1, minHeight: 0, overflow: mode === "trace" ? "hidden" : "auto",
                    padding: S[4], display: "flex", flexDirection: "column" }}>
        {mode === "trace" ? (
          <InspectorTrace inv={inv} onPick={onPick} />
        ) : evidence ? (
          <EvidenceDetail evidence={evidence} inv={inv} onReload={onReload} />
        ) : (
          <EvidenceIndex inv={inv} onPick={onPick} />
        )}
      </div>
    </aside>
  );
}

/** Nothing picked yet: list what can be picked, rather than an empty pane. */
function EvidenceIndex({ inv, onPick }: { inv: Investigation; onPick: (e: Evidence) => void }) {
  if (inv.evidence.length === 0) {
    return (
      <div style={{ fontSize: T.sm, color: C.dim, lineHeight: "var(--el-lh-normal)" }}>
        {inv.status === "running"
          ? "No evidence yet — citations appear here as the investigation retrieves them."
          : "This case reached its verdict without citable evidence. Switch to the trace to see what was tried."}
      </div>
    );
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: S[2] }}>
      <div style={{ fontSize: T.sm, color: C.dim, marginBottom: S[1] }}>
        Click a citation in the finding, or pick one here.
      </div>
      {inv.evidence.map((e) => (
        <button key={e.id} onClick={() => onPick(e)} className="el-btn el-btn--block"
          style={{ textAlign: "left", padding: `${S[2]} ${S[3]}`, background: C.card,
                   border: `1px solid ${C.border2}`, borderRadius: R.control,
                   opacity: e.rejected ? 0.55 : 1 }}>
          <span style={{ fontFamily: mono, fontSize: T.micro, color: C.accent, marginRight: S[2] }}>{e.id}</span>
          <span style={{ fontFamily: mono, fontSize: T.micro, color: C.faint }}>{sourceLabel(e.source)}</span>
          <div style={{ fontSize: T.sm, color: C.text3, marginTop: S[1], lineHeight: "var(--el-lh-snug)",
                        overflowWrap: "anywhere" }}>
            “{e.snippet.length > 160 ? `${e.snippet.slice(0, 160)}…` : e.snippet}”
          </div>
        </button>
      ))}
    </div>
  );
}
