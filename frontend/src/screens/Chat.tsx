import { useEffect, useRef, useState } from "react";
import { ChatCitation, api } from "../api";
import { C, MEASURE, R, S, T, mono, sans } from "../theme";
import { Label, ScreenHeader } from "../ui";
import { Icon } from "../components/Icon";

interface Turn {
  role: "you" | "echolens";
  text: string;
  citations?: ChatCitation[];
  investigationId?: number;
}

const SUGGESTIONS = [
  "What's our biggest unresolved complaint?",
  "Tell me about battery drain",
  "Why did ratings dip last week?",
];

// Ask the verified knowledge anything. Answers cite the case they came from;
// an investigate-intent question launches a case that streams in the same thread.
export function Chat({ onOpenInvestigation, productName }: {
  onOpenInvestigation: (id: number) => void; productName: string | null;
}) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
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

  const send = async (msg?: string) => {
    const message = (msg ?? input).trim();
    if (!message || busy) return;
    setInput("");
    setTurns((t) => [...t, { role: "you", text: message }]);
    setBusy(true);
    try {
      const r = await api.chat(message);
      if (!alive.current) return;
      setTurns((t) => [...t, {
        role: "echolens", text: r.text, citations: r.citations,
        investigationId: r.type === "investigation" ? r.investigation_id : undefined
      }]);
    } catch (e) {
      const raw = String(e).replace("Error: ", "");
      const text = /404/.test(raw)
        ? "Chat isn't available on this server yet — the backend is still deploying the latest version. Try again in a minute."
        : raw;
      setTurns((t) => [...t, { role: "echolens", text }]);
    } finally {
      if (!alive.current) return;
      setBusy(false);
      requestAnimationFrame(() => {
        if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
      });
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <ScreenHeader title="Ask" product={productName} subtitle="Answers grounded in your own cases" />

      <div ref={scrollRef} style={{ flex: 1, overflow: "auto", padding: `${S[5]} ${S[6]}` }}>
        {turns.length === 0 && (
          <div style={{ maxWidth: 720 }}>
            <p style={{ fontSize: T.md, color: C.muted, lineHeight: "var(--el-lh-normal)" }}>
              Ask about a complaint, a cause, or what to fix next. Every answer cites the case it came from — and if I
              haven't looked into something, I'll say so (and offer to investigate).
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
            <Bubble key={i} turn={t} onOpenInvestigation={onOpenInvestigation} />
          ))}
          {busy && <div style={{ fontSize: T.base, color: C.dim, fontFamily: mono }}>EchoLens is thinking…</div>}
        </div>
      </div>

      <div style={{ flex: "none", borderTop: `1px solid ${C.border}`, padding: `${S[3]} ${S[6]}`, display: "flex", gap: S[2], maxWidth: MEASURE }}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
          aria-label="Ask a question about your feedback"
          placeholder="Ask about a complaint, cause, or what to fix next…"
          style={{ flex: 1, background: C.bgRaised, border: `1px solid ${C.border3}`, borderRadius: R.control, color: C.text, fontFamily: sans, fontSize: T.md, padding: `${S[3]} ${S[3]}` }}
        />
        <button onClick={() => send()} disabled={!input.trim() || busy} className="el-btn el-btn--primary"
          style={{ borderRadius: R.control, padding: `0 ${S[5]}`, fontWeight: 600, fontSize: T.md, cursor: input.trim() && !busy ? "pointer" : "not-allowed", opacity: input.trim() && !busy ? 1 : 0.5 }}>
          Ask
        </button>
      </div>
    </div>
  );
}

function Bubble({ turn, onOpenInvestigation }: { turn: Turn; onOpenInvestigation: (id: number) => void }) {
  const you = turn.role === "you";
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: you ? "flex-end" : "flex-start" }}>
      <div style={{ fontFamily: mono, fontSize: T.micro, letterSpacing: ".1em", color: C.faint, marginBottom: S[1] }}>
        {you ? "YOU" : "ECHOLENS"}
      </div>
      <div style={{ maxWidth: 560, padding: `${S[3]} ${S[4]}`, borderRadius: R.card, background: you ? C.accent : C.card, color: you ? C.onAccent : C.text2, border: you ? "none" : `1px solid ${C.border2}`, fontSize: T.md, lineHeight: "var(--el-lh-normal)" }}>
        {turn.text}
      </div>
      {turn.investigationId != null && (
        <button onClick={() => onOpenInvestigation(turn.investigationId!)}
          className="el-btn el-btn--ghost"
          style={{ marginTop: S[2] }}>
          <Icon name="play" size={12} /> Watch case #{turn.investigationId} stream
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
