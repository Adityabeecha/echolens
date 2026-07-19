import { useEffect, useRef, useState } from "react";
import { Evidence, Hypothesis, TraceStep, api, canReview } from "../api";
import { useTrace } from "../hooks";
import { C, KIND_COLOR, mono, statusColor } from "../theme";
import { Bar, Label } from "../ui";

interface Props {
  investigationId: number;
  onBack: () => void;
  onDraftFinding: () => void;
  onOpenEvidence: (e: Evidence) => void;
}

function parseFrac(v: string | undefined): [number, number] {
  const [a, b] = String(v ?? "0/0").split("/").map((x) => parseFloat(x));
  return [a || 0, b || 0];
}

const STATE_LABEL: Record<string, string> = {
  running: "INVESTIGATING",
  resolved: "RESOLVED",
  insufficient_evidence: "INSUFFICIENT EVIDENCE",
  needs_human: "NEEDS HUMAN",
  budget_exhausted: "BUDGET EXHAUSTED",
};

export function Investigation({ investigationId, onBack, onDraftFinding, onOpenEvidence }: Props) {
  const { steps, status: liveStatus } = useTrace(investigationId);
  const [inv, setInv] = useState<Awaited<ReturnType<typeof api.investigation>> | null>(null);
  const [selHyp, setSelHyp] = useState<string | null>(null);
  const [follow, setFollow] = useState(true);
  const traceRef = useRef<HTMLDivElement | null>(null);
  // v5.0 replay: step the finished trace back for skeptics/audit (null = live/full)
  const [replayIdx, setReplayIdx] = useState<number | null>(null);
  const [speed, setSpeed] = useState(1);
  const [playing, setPlaying] = useState(false);

  // Poll investigation detail while running; refetch on status change.
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setInterval> | null = null;
    const load = () =>
      api.investigation(investigationId).then((d) => alive && setInv(d)).catch(() => {});
    load();
    timer = setInterval(() => {
      if (inv?.status && inv.status !== "running") {
        if (timer) clearInterval(timer);
        return;
      }
      load();
    }, 1500);
    return () => {
      alive = false;
      if (timer) clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [investigationId, liveStatus]);

  useEffect(() => {
    if (follow && traceRef.current) traceRef.current.scrollTop = traceRef.current.scrollHeight;
  }, [steps, follow, replayIdx]);

  // replay clock: advance one step at 850ms / speed while playing
  useEffect(() => {
    if (!playing || replayIdx === null) return;
    if (replayIdx >= steps.length) {
      setPlaying(false);
      return;
    }
    const t = setTimeout(() => setReplayIdx((i) => (i === null ? null : i + 1)), 850 / speed);
    return () => clearTimeout(t);
  }, [playing, replayIdx, speed, steps.length]);

  const shownSteps = replayIdx === null ? steps : steps.slice(0, replayIdx);
  const canReplay = (inv?.status ?? liveStatus) !== "running" && steps.length > 0;
  const startReplay = () => {
    setReplayIdx(0);
    setPlaying(true);
    setFollow(true);
  };
  const exitReplay = () => {
    setReplayIdx(null);
    setPlaying(false);
  };

  const status = inv?.status ?? liveStatus;
  const [iter, iterMax] = parseFrac(inv?.budget?.iterations);
  const [tok, tokMax] = parseFrac(inv?.budget?.tokens);
  const cost = inv?.budget?.cost_usd;
  const sc = statusColor(status);
  const running = status === "running";

  const sourcesTouched = new Map<string, number>();
  (inv?.evidence ?? []).forEach((e) => sourcesTouched.set(e.source, (sourcesTouched.get(e.source) ?? 0) + 1));

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 14,
          padding: "14px 24px",
          borderBottom: `1px solid ${C.border}`,
          flex: "none",
        }}
      >
        <span onClick={onBack} style={{ color: C.dim, cursor: "pointer", fontSize: 13 }}>
          ← Feed
        </span>
        <div style={{ width: 1, height: 18, background: C.border2 }} />
        <span style={{ fontFamily: mono, fontSize: 12, color: C.accent }}>CASE #{investigationId}</span>
        <div style={{ fontSize: 15, fontWeight: 600, maxWidth: 520, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {inv?.finding?.summary || inv?.title || "Investigation in progress"}
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            padding: "4px 10px",
            borderRadius: 20,
            background: `${sc}1a`,
            border: `1px solid ${sc}59`,
          }}
        >
          {running && (
            <div style={{ width: 6, height: 6, borderRadius: "50%", background: C.accent, animation: "elPulse 1.4s infinite" }} />
          )}
          <span style={{ fontSize: 11.5, fontWeight: 500, color: sc }}>{STATE_LABEL[status] ?? status}</span>
        </div>
        <div style={{ flex: 1 }} />
        <span style={{ fontFamily: mono, fontSize: 11.5, color: C.muted }}>{inv?.opened_by ?? ""}</span>
      </div>

      <div
        style={{
          flex: 1,
          display: "grid",
          gridTemplateColumns: "minmax(200px,296px) minmax(320px,1fr) minmax(180px,252px)",
          overflowX: "auto",
        }}
      >
        {/* left: hypotheses */}
        <div style={{ borderRight: `1px solid ${C.border}`, overflow: "auto", padding: 16 }}>
          <Label style={{ marginBottom: 12 }}>HYPOTHESES · {inv?.hypotheses.length ?? 0}</Label>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {(inv?.hypotheses ?? []).map((h) => (
              <HypothesisCard key={h.id} h={h} selected={selHyp === h.id} onPick={() => setSelHyp((s) => (s === h.id ? null : h.id))} />
            ))}
          </div>
        </div>

        {/* center: reasoning trace */}
        <div ref={traceRef} style={{ overflow: "auto", padding: "18px 26px", background: C.bg }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 14, maxWidth: 640 }}>
            <Label>REASONING TRACE</Label>
            <div style={{ flex: 1 }} />
            {canReplay && replayIdx === null && (
              <div onClick={startReplay} className="el-btn" style={replayBtn(false)}>
                ▸ Replay
              </div>
            )}
            {replayIdx !== null && (
              <>
                <div onClick={() => setPlaying((p) => !p)} className="el-btn" style={replayBtn(true)}>
                  {playing ? "⏸" : "▸"} {replayIdx}/{steps.length}
                </div>
                {[1, 2, 5].map((sp) => (
                  <div key={sp} onClick={() => setSpeed(sp)} className="el-btn" style={replayBtn(speed === sp)}>
                    {sp}×
                  </div>
                ))}
                <div onClick={exitReplay} className="el-btn" style={replayBtn(false)}>
                  ✕
                </div>
              </>
            )}
            {replayIdx === null && (
              <div
                onClick={() => setFollow((f) => !f)}
                style={{
                  fontFamily: mono,
                  fontSize: 9.5,
                  letterSpacing: ".06em",
                  padding: "3px 8px",
                  borderRadius: 4,
                  color: follow ? C.accent : C.ghost,
                  cursor: "pointer",
                }}
              >
                {follow ? "◉ FOLLOW" : "○ FOLLOW"}
              </div>
            )}
          </div>
          {selHyp && (
            <div
              style={{
                maxWidth: 640,
                marginBottom: 12,
                padding: "7px 12px",
                border: "1px solid rgba(240,166,60,.3)",
                background: "rgba(240,166,60,.05)",
                borderRadius: 6,
                fontFamily: mono,
                fontSize: 10.5,
                color: C.accent,
              }}
            >
              Highlighting steps for {selHyp} — click the hypothesis again to clear
            </div>
          )}
          <div style={{ display: "flex", flexDirection: "column", maxWidth: 640 }}>
            {shownSteps.map((s, i) => (
              <TraceRow key={s.seq} step={s} last={i === shownSteps.length - 1} selHyp={selHyp} onOpenEvidence={onOpenEvidence} evidence={inv?.evidence ?? []} />
            ))}
            {steps.length === 0 && (
              <div style={{ color: C.dim, fontSize: 13 }}>Waiting for the first reasoning step…</div>
            )}
          </div>
        </div>

        {/* right: case status */}
        <div style={{ borderLeft: `1px solid ${C.border}`, overflow: "auto", padding: 16, display: "flex", flexDirection: "column", gap: 16 }}>
          <div>
            <Label style={{ marginBottom: 10 }}>BUDGET</Label>
            <div style={{ display: "flex", flexDirection: "column", gap: 11 }}>
              <Meter label="Iterations" value={`${iter} / ${iterMax}`} pct={iterMax ? (iter / iterMax) * 100 : 0} color={C.accent} />
              <Meter label="Tokens" value={`${(tok / 1000).toFixed(1)}k / ${(tokMax / 1000).toFixed(0)}k`} pct={tokMax ? (tok / tokMax) * 100 : 0} color={C.info} />
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: C.muted }}>
                <span>Cost so far</span>
                <span style={{ fontFamily: mono, color: C.text }}>${Number(cost ?? 0).toFixed(4)}</span>
              </div>
            </div>
          </div>
          <div style={{ height: 1, background: C.border }} />
          <div>
            <Label style={{ marginBottom: 10 }}>SOURCES TOUCHED</Label>
            <div style={{ display: "flex", flexDirection: "column", gap: 7, fontSize: 12.5 }}>
              {["play_store", "github", "release_notes", "reddit"].map((src) => {
                const n = sourcesTouched.get(src) ?? 0;
                return (
                  <div key={src} style={{ display: "flex", justifyContent: "space-between", color: n ? C.text3 : C.ghost }}>
                    <span>{src.replace("_", " ")}</span>
                    <span style={{ fontFamily: mono, color: n ? C.good : C.ghost }}>{n ? `${n} ev` : "—"}</span>
                  </div>
                );
              })}
            </div>
          </div>
          <div style={{ height: 1, background: C.border }} />
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {canReview() && running && (
              <div style={{ display: "flex", gap: 8 }}>
                {inv?.paused ? (
                  <SecondaryBtn onClick={() => api.resume(investigationId)}>▸ Resume</SecondaryBtn>
                ) : (
                  <SecondaryBtn onClick={() => api.pause(investigationId)}>⏸ Pause</SecondaryBtn>
                )}
                <SecondaryBtn
                  onClick={() => api.escalate(investigationId)}
                  active={inv?.escalated}
                >
                  {inv?.escalated ? "✓ Escalated" : "Escalate"}
                </SecondaryBtn>
              </div>
            )}
            <button
              onClick={onDraftFinding}
              disabled={!inv?.finding}
              style={{
                width: "100%",
                padding: "9px 0",
                borderRadius: 7,
                border: "none",
                background: inv?.finding ? C.accent : C.hover,
                color: inv?.finding ? C.onAccent : C.dim,
                fontSize: 13,
                fontWeight: 600,
                cursor: inv?.finding ? "pointer" : "not-allowed",
              }}
            >
              {running ? "Investigating…" : "View finding →"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function replayBtn(active: boolean): React.CSSProperties {
  return {
    fontFamily: mono,
    fontSize: 9.5,
    letterSpacing: ".04em",
    padding: "3px 8px",
    borderRadius: 4,
    border: `1px solid ${active ? C.accent : C.border3}`,
    background: active ? "rgba(240,166,60,.12)" : "transparent",
    color: active ? C.accent : C.muted,
    cursor: "pointer",
  };
}

function SecondaryBtn({ children, onClick, active }: { children: React.ReactNode; onClick: () => void; active?: boolean }) {
  const [done, setDone] = useState(false);
  return (
    <button
      onClick={async () => {
        try {
          await onClick();
          setDone(true);
        } catch {
          /* ignore */
        }
      }}
      className="el-btn"
      style={{
        flex: 1,
        padding: "8px 0",
        borderRadius: 7,
        border: `1px solid ${active || done ? "rgba(76,192,119,.4)" : C.border4}`,
        background: active || done ? "rgba(76,192,119,.08)" : C.hover,
        color: active || done ? C.good : C.text,
        fontSize: 12.5,
        fontWeight: 500,
        cursor: "pointer",
      }}
    >
      {children}
    </button>
  );
}

function Meter({ label, value, pct, color }: { label: string; value: string; pct: number; color: string }) {
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: C.muted, marginBottom: 4 }}>
        <span>{label}</span>
        <span style={{ fontFamily: mono }}>{value}</span>
      </div>
      <Bar pct={pct} color={color} />
    </div>
  );
}

function HypothesisCard({ h, selected, onPick }: { h: Hypothesis; selected: boolean; onPick: () => void }) {
  const color = h.status === "supported" ? C.good : h.status === "rejected" ? C.bad : C.accent;
  const tag = h.status.toUpperCase();
  return (
    <div
      onClick={onPick}
      style={{
        padding: "13px 14px",
        background: C.card,
        border: `1px solid ${selected ? C.accent : h.status === "active" ? "rgba(240,166,60,.45)" : C.border2}`,
        borderRadius: 9,
        opacity: selected || h.status !== "rejected" ? 1 : 0.62,
        cursor: "pointer",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 7 }}>
        <span style={{ fontFamily: mono, fontSize: 11, color }}>{h.id}</span>
        <span style={{ fontFamily: mono, fontSize: 9.5, letterSpacing: ".06em", padding: "2px 6px", borderRadius: 3, background: `${color}1f`, color }}>
          {tag}
        </span>
      </div>
      <div style={{ fontSize: 13, lineHeight: 1.45, color: C.text2 }}>{h.statement}</div>
      <div style={{ display: "flex", alignItems: "center", gap: 9, marginTop: 11 }}>
        <div style={{ flex: 1 }}>
          <Bar pct={h.confidence * 100} color={color} />
        </div>
        <span style={{ fontFamily: mono, fontSize: 11.5, color, width: 32, textAlign: "right" }}>{h.confidence.toFixed(2)}</span>
      </div>
      <div style={{ fontFamily: mono, fontSize: 10.5, color: C.dim, marginTop: 7 }}>
        evidence +{h.evidence_for.length} for · −{h.evidence_against.length} against
      </div>
    </div>
  );
}

function TraceRow({
  step,
  last,
  selHyp,
  onOpenEvidence,
  evidence,
}: {
  step: TraceStep;
  last: boolean;
  selHyp: string | null;
  onOpenEvidence: (e: Evidence) => void;
  evidence: Evidence[];
}) {
  const c = step.content as Record<string, any>;
  const color = KIND_COLOR[step.kind] ?? C.muted;
  const stepHyp: string | null =
    (Array.isArray(c.supports) && c.supports[0]) ||
    (typeof c.code === "string" && /^H\d/.test(c.code) ? c.code.slice(0, 2) : null) ||
    null;
  const dim = !selHyp ? 1 : stepHyp === selHyp ? 1 : stepHyp ? 0.3 : 0.55;

  return (
    <div style={{ display: "grid", gridTemplateColumns: "52px 1fr", columnGap: 14, opacity: dim, transition: "opacity .25s" }}>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
        <div
          style={{
            fontFamily: mono,
            fontSize: 9,
            letterSpacing: ".05em",
            padding: "3px 0",
            width: 44,
            textAlign: "center",
            borderRadius: 4,
            border: `1px solid ${color}`,
            color,
            background: C.bgRaised,
            flex: "none",
          }}
        >
          {step.kind}
        </div>
        <div style={{ width: 1, flex: 1, background: last ? "transparent" : C.border2, minHeight: 14 }} />
      </div>
      <div style={{ paddingBottom: 16, minWidth: 0 }}>
        <div style={{ padding: "11px 14px", background: C.card, border: `1px solid ${C.border2}`, borderRadius: 8 }}>
          {step.kind === "THINK" && <div style={{ fontSize: 13, lineHeight: 1.5, color: C.text3 }}>{c.text}</div>}
          {step.kind === "TOOL" && (
            <>
              <div style={{ fontFamily: mono, fontSize: 12, color: C.info, wordBreak: "break-all" }}>{c.code}</div>
              <div style={{ fontFamily: mono, fontSize: 11, color: C.muted, marginTop: 8 }}>→ {c.preview}</div>
            </>
          )}
          {step.kind === "EVID" && (
            <>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 7 }}>
                <span style={{ fontFamily: mono, fontSize: 11, color: C.accent }}>{c.id}</span>
                <span style={{ fontFamily: mono, fontSize: 9.5, padding: "2px 7px", border: `1px solid ${C.border3}`, borderRadius: 4, color: C.muted }}>
                  {c.source}
                </span>
                <span style={{ fontFamily: mono, fontSize: 10, color: C.good, marginLeft: "auto" }}>
                  supports {(c.supports ?? []).join(", ")}
                </span>
              </div>
              <div
                onClick={() => {
                  const ev = evidence.find((e) => e.id === c.id);
                  if (ev) onOpenEvidence(ev);
                }}
                style={{ fontSize: 13, lineHeight: 1.5, color: C.text2, borderLeft: `2px solid ${C.border4}`, paddingLeft: 10, cursor: "pointer" }}
              >
                “{c.text}”
              </div>
            </>
          )}
          {step.kind === "UPDT" && (
            <>
              <div style={{ fontFamily: mono, fontSize: 12.5, color: c.good === false ? C.bad : C.good }}>{c.code}</div>
              <div style={{ fontSize: 12.5, color: C.muted, marginTop: 5 }}>{c.text}</div>
            </>
          )}
          {step.kind === "FAIL" && (
            <>
              <div style={{ fontFamily: mono, fontSize: 12, color: C.info, wordBreak: "break-all" }}>{c.code}</div>
              <div style={{ marginTop: 8, padding: "8px 11px", background: "rgba(224,88,79,.07)", border: "1px solid rgba(224,88,79,.35)", borderRadius: 6, fontFamily: mono, fontSize: 11, color: C.bad }}>
                ✕ {c.error}
              </div>
              <div style={{ fontSize: 12, color: C.muted, marginTop: 6 }}>{c.text}</div>
            </>
          )}
          {step.kind === "SPEC" && (
            <>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                <span style={{ fontFamily: mono, fontSize: 11, color: C.accentHi }}>
                  {String(c.specialist ?? "specialist").replace(/_/g, " ")}
                </span>
                {c.focus ? <span style={{ fontFamily: mono, fontSize: 10, color: C.faint }}>· {String(c.focus)}</span> : null}
              </div>
              <div style={{ fontSize: 13, lineHeight: 1.5, color: C.text3 }}>{c.text}</div>
            </>
          )}
          {step.kind === "REFUTE" && (
            <>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                <span style={{ fontFamily: mono, fontSize: 11, color: C.info }}>
                  attempted refutation{c.hypothesis ? ` · ${c.hypothesis}` : ""}
                </span>
                <span style={{ fontFamily: mono, fontSize: 9.5, padding: "2px 7px", borderRadius: 4, marginLeft: "auto", background: c.contradicted ? `${C.bad}1f` : `${C.good}1f`, color: c.contradicted ? C.bad : C.good }}>
                  {c.contradicted ? "counter-evidence found" : "hypothesis survived"}
                </span>
              </div>
              <div style={{ fontSize: 13, lineHeight: 1.5, color: C.text3 }}>{c.text}</div>
            </>
          )}
          {step.kind === "CHECK" && <div style={{ fontFamily: mono, fontSize: 11.5, color: C.faint }}>{c.text}</div>}
        </div>
      </div>
    </div>
  );
}
