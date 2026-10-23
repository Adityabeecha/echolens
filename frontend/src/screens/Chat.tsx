import { useEffect, useRef, useState } from "react";
import {
  ChatBasis, ChatCitation, ChatNextStep, ChatResponse, ChatStep, ChatToolCall, api, canReview
} from "../api";
import { C, MEASURE, R, S, T, mono, sans } from "../theme";
import { Dot, Label, ScreenHeader } from "../ui";
import { Icon } from "../components/Icon";

interface Turn {
  role: "you" | "echolens";
  text: string;
  citations?: ChatCitation[];
  investigationId?: number;
  toolCalls?: ChatToolCall[];
  confident?: boolean;
  canInvestigate?: boolean;
  question?: string;
  error?: boolean;
  basis?: ChatBasis;
  nextStep?: ChatNextStep | null;
  /** Set on an answer whose "Start an investigation" card was used. */
  launchedId?: number;
  queued?: boolean;
  launchError?: string;
}

const SUGGESTIONS = [
  "What's our biggest unresolved complaint?",
  "Tell me about battery drain",
  "Why did ratings dip last week?",
];

// Ask the verified knowledge anything. Answers say where they came from (a
// verified case, a raw feedback search, or a waiting signal); an
// investigate-intent question launches a case that streams in the same thread.
interface AskProps {
  onOpenInvestigation: (id: number) => void;
  productName: string | null;
  productId?: number | null;
}

export function Chat(props: AskProps) {
  return <AskConversation {...props} showHeader />;
}

/** Shared by the full Ask screen and the global drawer. */
export function AskConversation({ onOpenInvestigation, productName, productId, showHeader = false }: AskProps & {
  showHeader?: boolean;
}) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  // Live progress for the in-flight question, from POST /chat/stream.
  const [steps, setSteps] = useState<ChatStep[]>([]);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  // Chat is keyed on the product, so switching products unmounts it mid-flight.
  // The reply belonged to the OLD product's scope, so applying it after the
  // switch would attribute one product's answer to another.
  const alive = useRef(true);
  useEffect(() => {
    // Set on MOUNT as well as cleared on unmount. Only the cleanup existed, so
    // under StrictMode's dev-only mount → unmount → remount the simulated
    // unmount set this false and nothing ever set it back — every chat reply
    // was silently discarded in `npm run dev`. Production was unaffected (a
    // real remount gets a fresh useRef), which is exactly why it would survive
    // review: it only breaks where you develop.
    alive.current = true;
    return () => { alive.current = false; };
  }, []);

  const scrollDown = () => requestAnimationFrame(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  });

  // Stream first; fall back to the blocking POST /chat when the stream is
  // unavailable (older backend, a proxy that buffers SSE, a network blip). A
  // forced launch only falls back if the stream failed before any step arrived,
  // so a mid-stream failure can never open the same investigation twice.
  const ask = async (message: string, force: boolean): Promise<ChatResponse> => {
    let seen = 0;
    try {
      return await api.chatStream(message, (s) => {
        seen += 1;
        if (!alive.current) return;
        setSteps((prev) => [...prev, s]);
        scrollDown();
      }, force, productId);
    } catch (e) {
      if (force && seen > 0) throw e;
      return api.chat(message, force, productId);
    }
  };

  const send = async (msg?: string, force = false, fromTurn?: number) => {
    const message = (msg ?? input).trim();
    if (!message || busy) return;
    if (!force) {
      setInput("");
      setTurns((t) => [...t, { role: "you", text: message }]);
    }
    setBusy(true);
    setSteps([]);
    scrollDown();
    try {
      const r = await ask(message, force);
      if (!alive.current) return;
      const launched = r.type === "investigation" ? r.investigation_id : undefined;
      setTurns((t) => {
        const next = fromTurn != null && launched != null
          ? t.map((x, i) => (i === fromTurn ? { ...x, launchedId: launched } : x))
          : t;
        return [...next, {
          role: "echolens", text: r.text, citations: r.citations,
          investigationId: launched,
          toolCalls: r.tool_calls, confident: r.confident,
          canInvestigate: r.can_investigate, question: message,
          basis: r.basis, nextStep: r.next_step
        }];
      });
    } catch (e) {
      if (!alive.current) return;
      const raw = String(e).replace("Error: ", "");
      if (force && fromTurn != null) {
        // Keep the failure on the card the user pressed, with the reason.
        const reason = /403/.test(raw)
          ? "You need reviewer access to start an investigation."
          : "Couldn't start the investigation. Please try again.";
        setTurns((t) => t.map((x, i) => (i === fromTurn ? { ...x, launchError: reason } : x)));
        return;
      }
      const text = /404/.test(raw)
        ? "Chat isn't available on this server yet — the backend is still deploying the latest version. Try again in a minute."
        : "I couldn't reach EchoLens just now. Please try your question again.";
      setTurns((t) => [...t, { role: "echolens", text, error: true,
                              question: message }]);
    } finally {
      if (!alive.current) return;
      setBusy(false);
      setSteps([]);
      scrollDown();
    }
  };

  const startInvestigation = async (question: string, slug: string | undefined, fromTurn: number) => {
    if (!slug) return send(question, true, fromTurn);
    if (busy) return;
    setBusy(true);
    try {
      const result = await api.queueThemes([slug], { [slug]: question }, "quick", productId);
      if (!alive.current) return;
      const item = result.queued[0] ?? result.already[0];
      if (!item) throw new Error("No queue entry returned");
      setTurns((t) => t.map((x, i) => i === fromTurn
        ? { ...x, queued: true, launchedId: item.investigation_id ?? undefined, launchError: undefined } : x));
    } catch {
      if (alive.current) setTurns((t) => t.map((x, i) => i === fromTurn
        ? { ...x, launchError: "Couldn't queue the investigation. Please try again." } : x));
    } finally {
      if (alive.current) setBusy(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      {showHeader && <ScreenHeader title="Ask" product={productName} subtitle="Answers grounded in your own cases" />}

      <div ref={scrollRef} style={{ flex: 1, overflow: "auto", padding: `${S[5]} ${S[6]}` }}>
        {turns.length === 0 && (
          <div style={{ maxWidth: 720 }}>
            <p style={{ fontSize: T.md, color: C.muted, lineHeight: "var(--el-lh-normal)" }}>
              Ask about a complaint, a cause, or what to fix next. Every answer says where it came from — a verified
              case, a raw feedback search, or a signal nobody has investigated yet — and if I haven't looked into
              something, you can start an investigation from the answer.
            </p>
            <Label style={{ margin: "18px 0 10px" }}>TRY</Label>
            <div style={{ display: "flex", flexDirection: "column", gap: S[2], alignItems: "flex-start" }}>
              {SUGGESTIONS.map((s) => (
                <button key={s} onClick={() => send(s)} className="el-btn"
                  style={{ background: C.card, border: `1px solid ${C.border3}`, borderRadius: R.pill, padding: `${S[2]} ${S[3]}`, color: C.text3, fontSize: T.base, fontFamily: sans }}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        <div style={{ display: "flex", flexDirection: "column", gap: S[4], maxWidth: 720 }}>
          {turns.map((t, i) => (
            <Bubble key={i} turn={t} onOpenInvestigation={onOpenInvestigation}
              onInvestigate={(q, slug) => startInvestigation(q, slug, i)} onRetry={(q) => send(q)} busy={busy} />
          ))}
          {busy && <Progress steps={steps} />}
        </div>
      </div>

      <div style={{ flex: "none", borderTop: `1px solid ${C.border}`, padding: `${S[3]} ${S[6]}`, display: "flex", gap: S[2], maxWidth: MEASURE, minWidth: 0 }}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
          aria-label="Ask a question about your feedback"
          placeholder="Ask about a complaint, cause, or what to fix next…"
          style={{ flex: 1, minWidth: 0, background: C.bgRaised, border: `1px solid ${C.border3}`, borderRadius: R.control, color: C.text, fontFamily: sans, fontSize: T.md, padding: `${S[3]} ${S[3]}` }}
        />
        <button onClick={() => send()} disabled={!input.trim() || busy} className="el-btn el-btn--primary"
          style={{ borderRadius: R.control, padding: `0 ${S[5]}`, fontWeight: 600, fontSize: T.md, cursor: input.trim() && !busy ? "pointer" : "not-allowed", opacity: input.trim() && !busy ? 1 : 0.5 }}>
          Ask
        </button>
      </div>
    </div>
  );
}

/** What Ask is doing right now — one line per step, the newest one pulsing. */
function Progress({ steps }: { steps: ChatStep[] }) {
  if (steps.length === 0) {
    return <div style={{ fontSize: T.base, color: C.dim, fontFamily: mono }}>EchoLens is thinking…</div>;
  }
  return (
    <div role="status" aria-live="polite"
      style={{ display: "flex", flexDirection: "column", gap: S[1], paddingLeft: S[3],
               borderLeft: `2px solid ${C.border3}` }}>
      {steps.map((s, i) => {
        const live = i === steps.length - 1;
        return (
          <div key={i} style={{ display: "flex", alignItems: "baseline", gap: S[2],
                                fontSize: T.sm, color: live ? C.text3 : C.faint }}>
            <Dot color={live ? C.accent : C.border4} pulse={live} />
            <span>
              {s.text}
              {s.tool && (
                <span style={{ fontFamily: mono, fontSize: T.micro, color: C.dim, marginLeft: S[2] }}>
                  {s.tool}
                </span>
              )}
              {s.why && (
                <span style={{ display: "block", fontSize: T.xs, color: C.dim }}>why: {s.why}</span>
              )}
            </span>
          </div>
        );
      })}
    </div>
  );
}

const BASIS_TONE: Record<ChatBasis["kind"], { color: string; bg: string; line: string }> = {
  investigation: { color: C.good, bg: C.goodBg, line: C.goodLine },
  investigation_started: { color: C.info, bg: C.infoBg, line: C.infoLine },
  raw_search: { color: C.info, bg: C.infoBg, line: C.infoLine },
  signals: { color: C.accent, bg: C.accentBg, line: C.accentLine },
  none: { color: C.dim, bg: C.bgRaised, line: C.border3 },
};

/** Where this answer came from, as a pill (and a link when it names a case). */
function BasisBadge({ basis, onOpen }: { basis: ChatBasis; onOpen: (id: number) => void }) {
  const tone = BASIS_TONE[basis.kind] ?? BASIS_TONE.none;
  const style = {
    display: "inline-flex", alignItems: "center", gap: S[1],
    fontFamily: mono, fontSize: T.micro, letterSpacing: ".04em",
    color: tone.color, background: tone.bg, border: `1px solid ${tone.line}`,
    borderRadius: R.pill, padding: `2px ${S[2]}`,
  } as const;
  const icon = basis.kind === "investigation" ? "check" : basis.kind === "none" ? "info" : "search";
  if (basis.case_id != null) {
    return (
      <button className="el-btn" onClick={() => onOpen(basis.case_id!)} style={style}
        title={`Open case #${basis.case_id}`}>
        <Icon name={icon} size={10} /> {basis.label}
      </button>
    );
  }
  return <span style={style}><Icon name={icon} size={10} /> {basis.label}</span>;
}

/** The next step for an answer no case backs: start one, or see why you can't. */
function InvestigateCard({ step, launchedId, queued, launchError, busy, onStart, onOpen }: {
  step: ChatNextStep;
  launchedId?: number;
  queued?: boolean;
  launchError?: string;
  busy: boolean;
  onStart: () => void;
  onOpen: (id: number) => void;
}) {
  return (
    <div style={{ marginTop: S[2], maxWidth: 560, padding: `${S[3]} ${S[4]}`, borderRadius: R.card,
                  background: C.card, border: `1px dashed ${C.border4}`,
                  display: "flex", flexDirection: "column", gap: S[2] }}>
      <div style={{ fontSize: T.sm, color: C.text3, lineHeight: "var(--el-lh-normal)" }}>
        Start an investigation into “{step.question}”
      </div>
      {launchedId != null ? (
        <button onClick={() => onOpen(launchedId)} className="el-btn el-btn--ghost"
          style={{ alignSelf: "flex-start", fontSize: T.sm }}>
          <Icon name="play" size={12} /> Case #{launchedId} is running — watch it live
        </button>
      ) : queued ? (
        <div role="status" style={{ fontSize: T.sm, color: C.muted }}>Queued for investigation. Track it in Cases.</div>
      ) : step.allowed ? (
        <button onClick={onStart} disabled={busy} className="el-btn el-btn--primary"
          style={{ alignSelf: "flex-start", borderRadius: R.control, padding: `${S[2]} ${S[3]}`,
                   fontSize: T.sm, fontWeight: 600, cursor: busy ? "wait" : "pointer" }}>
          <Icon name="search" size={12} /> {busy ? "Starting…" : "Start investigation"}
        </button>
      ) : (
        <div style={{ display: "flex", gap: S[2], alignItems: "baseline", fontSize: T.sm, color: C.muted }}>
          <Icon name="info" size={12} /> {step.reason ?? "You can't start investigations from this account."}
        </div>
      )}
      {launchError && (
        <div role="alert" style={{ fontSize: T.sm, color: C.bad }}>{launchError}</div>
      )}
    </div>
  );
}

function Bubble({ turn, onOpenInvestigation, onInvestigate, onRetry, busy }: {
  turn: Turn;
  onOpenInvestigation: (id: number) => void;
  onInvestigate?: (question: string, slug?: string) => void;
  onRetry: (question: string) => void;
  busy: boolean;
}) {
  const you = turn.role === "you";
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: you ? "flex-end" : "flex-start" }}>
      <div style={{ fontFamily: mono, fontSize: T.micro, letterSpacing: ".1em", color: C.faint, marginBottom: S[1] }}>
        {you ? "YOU" : "ECHOLENS"}
      </div>
      <div style={{ maxWidth: 560, padding: `${S[3]} ${S[4]}`, borderRadius: R.card, background: you ? C.accent : C.card, color: you ? C.onAccent : C.text2, border: you ? "none" : `1px solid ${C.border2}`, fontSize: T.md, lineHeight: "var(--el-lh-normal)" }}>
        {turn.text}
      </div>
      {!you && turn.basis && (
        <div style={{ marginTop: S[2], display: "flex", flexDirection: "column", gap: S[1], maxWidth: 560 }}>
          <div><BasisBadge basis={turn.basis} onOpen={onOpenInvestigation} /></div>
          {turn.basis.caution && (
            <div style={{ display: "flex", gap: S[1], alignItems: "baseline", fontSize: T.sm,
                          color: C.muted, lineHeight: "var(--el-lh-normal)" }}>
              <Icon name="warning" size={11} /> {turn.basis.caution}
            </div>
          )}
        </div>
      )}
      {turn.toolCalls && turn.toolCalls.length > 0 && (
        <div style={{ marginTop: S[2], fontSize: T.sm, color: C.faint,
                      display: "flex", flexWrap: "wrap", gap: S[2], alignItems: "center" }}>
          <span style={{ fontFamily: mono, fontSize: T.micro }}>CHECKED</span>
          {turn.toolCalls.map((tc, i) => (
            <span key={i} title={tc.why || undefined}
              style={{ fontFamily: mono, fontSize: T.micro, color: C.dim,
                       background: C.bgRaised, border: `1px solid ${C.border3}`,
                       borderRadius: R.pill, padding: `2px ${S[2]}` }}>
              {tc.name}
            </span>
          ))}
        </div>
      )}
      {turn.investigationId != null && (
        <button onClick={() => onOpenInvestigation(turn.investigationId!)}
          className="el-btn el-btn--ghost"
          style={{ marginTop: S[2] }}>
          <Icon name="play" size={12} /> Watch case #{turn.investigationId} stream
        </button>
      )}
      {!you && turn.nextStep && turn.question && onInvestigate && (
        <InvestigateCard step={turn.nextStep} launchedId={turn.launchedId} queued={turn.queued}
          launchError={turn.launchError} busy={busy}
          onStart={() => onInvestigate(turn.nextStep!.question, turn.nextStep!.slug)} onOpen={onOpenInvestigation} />
      )}
      {!you && turn.nextStep === undefined && turn.canInvestigate && canReview() && turn.question && onInvestigate && (
        turn.launchedId != null ? (
          <button onClick={() => onOpenInvestigation(turn.launchedId!)} className="el-btn el-btn--ghost"
            style={{ marginTop: S[2], fontSize: T.sm }}>
            <Icon name="play" size={12} /> Case #{turn.launchedId} is running — watch it live
          </button>
        ) : (
          <button onClick={() => onInvestigate(turn.question!)} disabled={busy}
            className="el-btn el-btn--ghost"
            style={{ marginTop: S[2], fontSize: T.sm }}>
            <Icon name="search" size={12} /> Investigate again anyway
          </button>
        )
      )}
      {!you && turn.error && turn.question && (
        <button onClick={() => onRetry(turn.question!)} disabled={busy}
          className="el-btn el-btn--ghost"
          style={{ marginTop: S[2], fontSize: T.sm }}>
          <Icon name="retry" size={12} /> {busy ? "Retrying…" : "Try again"}
        </button>
      )}
      {turn.citations && turn.citations.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: S[2], marginTop: S[2] }}>
          {turn.citations.map((c) => (
            <button key={c.investigation_id} onClick={() => onOpenInvestigation(c.investigation_id)} className="el-btn"
              title={c.summary}
              style={{ display: "flex", alignItems: "center", gap: S[1], background: C.card2, border: `1px solid ${C.border3}`, borderRadius: R.control, padding: `${S[1]} ${S[2]}` }}>
              <span style={{ fontFamily: mono, fontSize: T.micro, color: C.accent }}>case #{c.investigation_id}</span>
              <span style={{ fontSize: T.sm, color: C.muted, maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.summary}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
