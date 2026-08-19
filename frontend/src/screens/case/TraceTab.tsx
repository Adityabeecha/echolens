import { useEffect, useRef, useState } from "react";
import { Evidence, Hypothesis, Investigation, TraceStep, api, canReview } from "../../api";
import { withToast } from "../../components/Toast";
import { money } from "../../format";
import { useTrace } from "../../hooks";
import { C, R, S, T, KIND_COLOR, mono } from "../../theme";
import { Bar, Label } from "../../ui";
import { Icon } from "../../components/Icon";

interface Props {
  inv: Investigation;
  onOpenEvidence: (e: Evidence) => void;
  onReload: () => Promise<unknown> | void;
}

function parseFrac(v: string | undefined): [number, number] {
  const [a, b] = String(v ?? "0/0").split("/").map((x) => parseFloat(x));
  return [a || 0, b || 0];
}

/**
 * How EchoLens got there — the live reasoning trace, with replay.
 *
 * This is the machinery, so it is a tab rather than a screen: worth watching
 * while a case runs, worth auditing afterwards, not the thing you open a case
 * to read.
 */
export function TraceTab({ inv, onOpenEvidence, onReload }: Props) {
  const { steps } = useTrace(inv.id);
  const [selHyp, setSelHyp] = useState<string | null>(null);
  const [follow, setFollow] = useState(true);
  const traceRef = useRef<HTMLDivElement | null>(null);
  const [replayIdx, setReplayIdx] = useState<number | null>(null);
  const [speed, setSpeed] = useState(1);
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    if (follow && traceRef.current) traceRef.current.scrollTop = traceRef.current.scrollHeight;
  }, [steps, follow, replayIdx]);

  // replay clock: advance one step at 850ms / speed while playing
  useEffect(() => {
    if (!playing || replayIdx === null) return;
    if (replayIdx >= steps.length) { setPlaying(false); return; }
    const t = setTimeout(() => setReplayIdx((i) => (i === null ? null : i + 1)), 850 / speed);
    return () => clearTimeout(t);
  }, [playing, replayIdx, speed, steps.length]);

  const shownSteps = replayIdx === null ? steps : steps.slice(0, replayIdx);
  const running = inv.status === "running";
  const canReplay = !running && steps.length > 0;

  const [iter, iterMax] = parseFrac(inv.budget?.iterations);
  const [tok, tokMax] = parseFrac(inv.budget?.tokens);

  const sourcesTouched = new Map<string, number>();
  inv.evidence.forEach((e) => sourcesTouched.set(e.source, (sourcesTouched.get(e.source) ?? 0) + 1));

  const control = async (label: string, fn: () => Promise<unknown>, success: string) => {
    await withToast(fn, { success, failure: `Couldn't ${label} this case` });
    await onReload();
  };

  return (
    <div style={{ flex: 1, minWidth: 0, display: "grid",
                  gridTemplateColumns: "minmax(200px,296px) minmax(320px,1fr) minmax(180px,252px)",
                  overflowX: "auto" }}>
      {/* left: hypotheses */}
      <div style={{ borderRight: `1px solid ${C.border}`, overflow: "auto", padding: 16 }}>
        <Label style={{ marginBottom: S[3] }}>HYPOTHESES · {inv.hypotheses.length}</Label>
        <div style={{ display: "flex", flexDirection: "column", gap: S[2] }}>
          {inv.hypotheses.map((h) => (
            <HypothesisCard key={h.id} h={h} selected={selHyp === h.id}
              onPick={() => setSelHyp((s) => (s === h.id ? null : h.id))} />
          ))}
          {inv.hypotheses.length === 0 && (
            <div style={{ fontSize: T.sm, color: C.dim, lineHeight: "var(--el-lh-normal)" }}>
              No hypotheses yet — the first plan step proposes them.
            </div>
          )}
        </div>
      </div>

      {/* centre: reasoning trace */}
      <div ref={traceRef} style={{ overflow: "auto", padding: `${S[4]} ${S[6]}`, background: C.bg }}>
        <div style={{ display: "flex", alignItems: "center", gap: S[1], marginBottom: S[3],
                      maxWidth: 640 }}>
          <Label>REASONING TRACE</Label>
          <div style={{ flex: 1 }} />
          {/* Real <button>s, not <div onClick>. These carried .el-btn for the
              styling but none of the semantics: no role, no tabIndex, no key
              handler — so the whole replay transport was unreachable by
              keyboard and got no focus ring, because the focus rule matches
              button/a/[role=button]/[tabindex] and a bare div matches none. */}
          {canReplay && replayIdx === null && (
            <button onClick={() => { setReplayIdx(0); setPlaying(true); setFollow(true); }}
              className="el-btn" style={replayBtn(false)}>
              <Icon name="play" size={11} /> Replay
            </button>
          )}
          {replayIdx !== null && (
            <>
              <button onClick={() => setPlaying((p) => !p)} className="el-btn"
                aria-label={playing ? "Pause replay" : "Resume replay"}
                style={replayBtn(true)}>
                <Icon name={playing ? "pause" : "play"} size={11} /> {replayIdx}/{steps.length}
              </button>
              {[1, 2, 5].map((sp) => (
                <button key={sp} onClick={() => setSpeed(sp)} className="el-btn"
                  aria-pressed={speed === sp} aria-label={`Replay at ${sp}× speed`}
                  style={replayBtn(speed === sp)}>{sp}×</button>
              ))}
              <button onClick={() => { setReplayIdx(null); setPlaying(false); }} className="el-btn"
                style={replayBtn(false)} aria-label="Exit replay"><Icon name="close" size={11} /></button>
            </>
          )}
          {replayIdx === null && (
            <button onClick={() => setFollow((f) => !f)} className="el-btn"
              aria-pressed={follow} aria-label="Follow the newest step"
              style={{ fontFamily: mono, fontSize: T.micro, letterSpacing: ".06em", padding: `${S[1]} ${S[2]}`,
                       borderRadius: R.sm, color: follow ? C.accent : C.ghost }}>
              <Icon name={follow ? "dot" : "circle"} size={10} /> FOLLOW
            </button>
          )}
        </div>

        {selHyp && (
          <div style={{ maxWidth: 640, marginBottom: S[3], padding: `${S[2]} ${S[3]}`,
                        border: `1px solid ${C.accentLine}`, background: C.accentBg,
                        borderRadius: R.control, fontFamily: mono, fontSize: T.micro, color: C.accent }}>
            Highlighting steps for {selHyp} — click the hypothesis again to clear
          </div>
        )}

        <div style={{ display: "flex", flexDirection: "column", maxWidth: 640 }}>
          {shownSteps.map((s, i) => (
            <TraceRow key={s.seq} step={s} last={i === shownSteps.length - 1} selHyp={selHyp}
                      onOpenEvidence={onOpenEvidence} evidence={inv.evidence} />
          ))}
          {steps.length === 0 && (
            <div style={{ color: C.dim, fontSize: T.base }}>
              {running ? "Waiting for the first reasoning step…" : "No trace was recorded for this case."}
            </div>
          )}
        </div>
      </div>

      {/* right: budget + controls */}
      <div style={{ borderLeft: `1px solid ${C.border}`, overflow: "auto", padding: 16,
                    display: "flex", flexDirection: "column", gap: S[4] }}>
        <div>
          <Label style={{ marginBottom: S[2] }}>BUDGET</Label>
          <div style={{ display: "flex", flexDirection: "column", gap: S[3] }}>
            <Meter label="Iterations" value={`${iter} / ${iterMax}`}
                   pct={iterMax ? (iter / iterMax) * 100 : 0} color={C.accent} />
            <Meter label="Tokens" value={`${(tok / 1000).toFixed(1)}k / ${(tokMax / 1000).toFixed(0)}k`}
                   pct={tokMax ? (tok / tokMax) * 100 : 0} color={C.info} />
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: T.sm,
                          color: C.muted }}>
              <span>Cost so far</span>
              <span style={{ fontFamily: mono, color: C.text }}>
                {money(Number(inv.budget?.cost_usd ?? 0))}
              </span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: T.sm,
                          color: C.muted }}>
              <span>Tier</span>
              <span style={{ fontFamily: mono, color: C.text3 }}>{inv.budget_tier}</span>
            </div>
          </div>
        </div>

        <div style={{ height: 1, background: C.border }} />

        <div>
          <Label style={{ marginBottom: S[2] }}>SOURCES TOUCHED</Label>
          <div style={{ display: "flex", flexDirection: "column", gap: S[2], fontSize: T.sm }}>
            {["play_store", "github", "release_notes", "reddit"].map((src) => {
              const n = sourcesTouched.get(src) ?? 0;
              return (
                <div key={src} style={{ display: "flex", justifyContent: "space-between",
                                        color: n ? C.text3 : C.ghost }}>
                  <span>{src.replace("_", " ")}</span>
                  <span style={{ fontFamily: mono, color: n ? C.good : C.ghost }}>
                    {n ? `${n} ev` : "—"}
                  </span>
                </div>
              );
            })}
          </div>
        </div>

        {canReview() && running && (
          <>
            <div style={{ height: 1, background: C.border }} />
            <div style={{ display: "flex", gap: S[2] }}>
              {inv.paused ? (
                <SecondaryBtn onClick={() =>
                  control("resume", () => api.resume(inv.id), "Investigation resumed.")}>
                  <Icon name="play" size={12} /> Resume
                </SecondaryBtn>
              ) : (
                <SecondaryBtn onClick={() =>
                  control("pause", () => api.pause(inv.id), "Investigation paused.")}>
                  <Icon name="pause" size={12} /> Pause
                </SecondaryBtn>
              )}
              <SecondaryBtn
                active={inv.escalated}
                onClick={() => control("escalate", () => api.escalate(inv.id),
                  "Escalated — this case now runs on a bigger budget.")}>
                {inv.escalated ? <><Icon name="check" size={12} /> Escalated</> : "Escalate"}
              </SecondaryBtn>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function replayBtn(active: boolean): React.CSSProperties {
  return {
    fontFamily: mono, fontSize: T.micro, letterSpacing: ".04em", padding: `${S[1]} ${S[2]}`, borderRadius: R.sm,
    border: `1px solid ${active ? C.accent : C.border3}`,
    background: active ? C.accentBg : "transparent",
    color: active ? C.accent : C.muted
  };
}

function SecondaryBtn({ children, onClick, active }: {
  children: React.ReactNode; onClick: () => void; active?: boolean;
}) {
  return (
    <button onClick={onClick} className="el-btn"
      style={{ flex: 1, padding: `${S[2]} 0`, borderRadius: R.control,
               border: `1px solid ${active ? C.goodLine : C.border4}`,
               background: active ? C.goodBg : C.hover,
               color: active ? C.good : C.text, fontSize: T.sm, fontWeight: 500 }}>
      {children}
    </button>
  );
}

function Meter({ label, value, pct, color }: {
  label: string; value: string; pct: number; color: string;
}) {
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: T.sm,
                    color: C.muted, marginBottom: S[1] }}>
        <span>{label}</span>
        <span style={{ fontFamily: mono }}>{value}</span>
      </div>
      <Bar pct={pct} color={color} />
    </div>
  );
}

function HypothesisCard({ h, selected, onPick }: {
  h: Hypothesis; selected: boolean; onPick: () => void;
}) {
  const color = h.status === "supported" ? C.good : h.status === "rejected" ? C.bad : C.accent;
  return (
    // `el-btn` is for inline controls: it centres its content and sets
    // white-space: nowrap, which clipped these multi-line statements at BOTH
    // ends. A card whose content is block text needs the layout reset.
    <button className="el-btn el-btn--block" onClick={onPick}
      aria-pressed={selected}
      style={{ padding: `${S[3]} ${S[3]}`, background: C.card,
               border: `1px solid ${selected ? C.accent : h.status === "active" ? C.accentLine : C.border2}`,
               borderRadius: R.control, opacity: selected || h.status !== "rejected" ? 1 : 0.62 }}>
      <div style={{ display: "flex", alignItems: "center", gap: S[2], marginBottom: S[2] }}>
        <span style={{ fontFamily: mono, fontSize: T.xs, color }}>{h.id}</span>
        <span style={{ fontFamily: mono, fontSize: T.micro, letterSpacing: ".06em", padding: `0 ${S[1]}`,
                       borderRadius: R.sm, background: `${color}1f`, color }}>
          {h.status.toUpperCase()}
        </span>
      </div>
      <div style={{ fontSize: T.base, lineHeight: "var(--el-lh-snug)", color: C.text2 }}>{h.statement}</div>
      <div style={{ display: "flex", alignItems: "center", gap: S[2], marginTop: S[3] }}>
        <div style={{ flex: 1 }}><Bar pct={h.confidence * 100} color={color} /></div>
        <span style={{ fontFamily: mono, fontSize: T.xs, color, width: 32, textAlign: "right" }}>
          {h.confidence.toFixed(2)}
        </span>
      </div>
      <div style={{ fontFamily: mono, fontSize: T.micro, color: C.dim, marginTop: S[2] }}>
        evidence +{h.evidence_for.length} for · −{h.evidence_against.length} against
      </div>
    </button>
  );
}

function TraceRow({ step, last, selHyp, onOpenEvidence, evidence }: {
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
    <div style={{ display: "grid", gridTemplateColumns: "52px 1fr", columnGap: S[3], opacity: dim,
                  transition: "opacity .25s" }}>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
        <div style={{ fontFamily: mono, fontSize: T.micro, letterSpacing: ".05em", padding: `${S[1]} 0`,
                      width: 44, textAlign: "center", borderRadius: R.sm, border: `1px solid ${color}`,
                      color, background: C.bgRaised, flex: "none" }}>
          {step.kind}
        </div>
        <div style={{ width: 1, flex: 1, background: last ? "transparent" : C.border2,
                      minHeight: 14 }} />
      </div>
      <div style={{ paddingBottom: 16, minWidth: 0 }}>
        <div style={{ padding: `${S[3]} ${S[3]}`, background: C.card, border: `1px solid ${C.border2}`,
                      borderRadius: R.control }}>
          {step.kind === "THINK" && (
            <div style={{ fontSize: T.base, lineHeight: "var(--el-lh-normal)", color: C.text3 }}>{c.text}</div>
          )}
          {step.kind === "TOOL" && (
            <>
              <div style={{ fontFamily: mono, fontSize: T.sm, color: C.info,
                            wordBreak: "break-all" }}>{c.code}</div>
              <div style={{ fontFamily: mono, fontSize: T.xs, color: C.muted, marginTop: S[2] }}>
                → {c.preview}
              </div>
            </>
          )}
          {step.kind === "EVID" && (
            <>
              <div style={{ display: "flex", alignItems: "center", gap: S[2], marginBottom: S[2] }}>
                <span style={{ fontFamily: mono, fontSize: T.xs, color: C.accent }}>{c.id}</span>
                <span style={{ fontFamily: mono, fontSize: T.micro, padding: `0 ${S[2]}`,
                               border: `1px solid ${C.border3}`, borderRadius: R.sm, color: C.muted }}>
                  {c.source}
                </span>
                <span style={{ fontFamily: mono, fontSize: T.micro, color: C.good, marginLeft: "auto" }}>
                  supports {(c.supports ?? []).join(", ")}
                </span>
              </div>
              <button className="el-btn"
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    const ev = evidence.find((x) => x.id === c.id);
                    if (ev) onOpenEvidence(ev);
                  }
                }}
                onClick={() => {
                  const ev = evidence.find((e) => e.id === c.id);
                  if (ev) onOpenEvidence(ev);
                }}
                style={{ fontSize: T.base, lineHeight: "var(--el-lh-normal)", color: C.text2,
                         borderLeft: `2px solid ${C.border4}`, paddingLeft: 10 }}>
                “{c.text}”
              </button>
            </>
          )}
          {step.kind === "UPDT" && (
            <>
              <div style={{ fontFamily: mono, fontSize: T.sm,
                            color: c.good === false ? C.bad : C.good }}>{c.code}</div>
              <div style={{ fontSize: T.sm, color: C.muted, marginTop: S[1] }}>{c.text}</div>
            </>
          )}
          {step.kind === "FAIL" && (
            <>
              <div style={{ fontFamily: mono, fontSize: T.sm, color: C.info,
                            wordBreak: "break-all" }}>{c.code}</div>
              <div style={{ marginTop: S[2], padding: `${S[2]} ${S[3]}`, background: "rgba(224,88,79,.07)",
                            border: `1px solid ${C.badLine}`, borderRadius: R.control,
                            fontFamily: mono, fontSize: T.xs, color: C.bad }}>
                <Icon name="close" size={11} style={{ display: "inline" }} /> {c.error}
              </div>
              <div style={{ fontSize: T.sm, color: C.muted, marginTop: S[1] }}>{c.text}</div>
            </>
          )}
          {step.kind === "SPEC" && (
            <>
              <div style={{ display: "flex", alignItems: "center", gap: S[2], marginBottom: S[1] }}>
                <span style={{ fontFamily: mono, fontSize: T.xs, color: C.accentHi }}>
                  {String(c.specialist ?? "specialist").replace(/_/g, " ")}
                </span>
                {c.focus ? (
                  <span style={{ fontFamily: mono, fontSize: T.micro, color: C.faint }}>
                    · {String(c.focus)}
                  </span>
                ) : null}
              </div>
              <div style={{ fontSize: T.base, lineHeight: "var(--el-lh-normal)", color: C.text3 }}>{c.text}</div>
            </>
          )}
          {step.kind === "REFUTE" && (
            <>
              <div style={{ display: "flex", alignItems: "center", gap: S[2], marginBottom: S[1] }}>
                <span style={{ fontFamily: mono, fontSize: T.xs, color: C.info }}>
                  attempted refutation{c.hypothesis ? ` · ${c.hypothesis}` : ""}
                </span>
                <span style={{ fontFamily: mono, fontSize: T.micro, padding: `0 ${S[2]}`, borderRadius: R.sm,
                               marginLeft: "auto",
                               background: c.contradicted ? `${C.bad}1f` : `${C.good}1f`,
                               color: c.contradicted ? C.bad : C.good }}>
                  {c.contradicted ? "counter-evidence found" : "hypothesis survived"}
                </span>
              </div>
              <div style={{ fontSize: T.base, lineHeight: "var(--el-lh-normal)", color: C.text3 }}>{c.text}</div>
            </>
          )}
          {step.kind === "CHECK" && (
            <div style={{ fontFamily: mono, fontSize: T.xs, color: C.faint }}>{c.text}</div>
          )}
        </div>
      </div>
    </div>
  );
}
