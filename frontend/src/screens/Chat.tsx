import { useRef, useState } from "react";
import { ChatCitation, api } from "../api";
import { C, mono, sans } from "../theme";
import { Label, ScreenHeader } from "../ui";

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
export function Chat({ onOpenInvestigation }: { onOpenInvestigation: (id: number) => void }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  const send = async (msg?: string) => {
    const message = (msg ?? input).trim();
    if (!message || busy) return;
    setInput("");
    setTurns((t) => [...t, { role: "you", text: message }]);
    setBusy(true);
    try {
      const r = await api.chat(message);
      setTurns((t) => [...t, {
        role: "echolens", text: r.text, citations: r.citations,
        investigationId: r.type === "investigation" ? r.investigation_id : undefined,
      }]);
    } catch (e) {
      setTurns((t) => [...t, { role: "echolens", text: String(e).replace("Error: ", "") }]);
    } finally {
      setBusy(false);
      requestAnimationFrame(() => {
        if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
      });
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <ScreenHeader title="Ask EchoLens" right={<span style={{ fontFamily: mono, fontSize: 11.5, color: C.muted }}>GROUNDED IN YOUR CASES</span>} />

      <div ref={scrollRef} style={{ flex: 1, overflow: "auto", padding: "22px 28px" }}>
        {turns.length === 0 && (
          <div style={{ maxWidth: 720 }}>
            <p style={{ fontSize: 14, color: C.muted, lineHeight: 1.6 }}>
              Ask about a complaint, a cause, or what to fix next. Every answer cites the case it came from — and if I
              haven't looked into something, I'll say so (and offer to investigate).
            </p>
            <Label style={{ margin: "18px 0 10px" }}>TRY</Label>
            <div style={{ display: "flex", flexDirection: "column", gap: 8, alignItems: "flex-start" }}>
              {SUGGESTIONS.map((s) => (
                <button key={s} onClick={() => send(s)} className="el-btn"
                  style={{ background: C.card, border: `1px solid ${C.border3}`, borderRadius: 20, padding: "8px 14px", color: C.text3, fontSize: 13, cursor: "pointer", fontFamily: sans }}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        <div style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: 720 }}>
          {turns.map((t, i) => (
            <Bubble key={i} turn={t} onOpenInvestigation={onOpenInvestigation} />
          ))}
          {busy && <div style={{ fontSize: 13, color: C.dim, fontFamily: mono }}>EchoLens is thinking…</div>}
        </div>
      </div>

      <div style={{ flex: "none", borderTop: `1px solid ${C.border}`, padding: "14px 28px", display: "flex", gap: 10, maxWidth: 900 }}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
          placeholder="Ask about a complaint, cause, or what to fix next…"
          style={{ flex: 1, background: C.bgRaised, border: `1px solid ${C.border3}`, borderRadius: 9, color: C.text, fontFamily: sans, fontSize: 14, padding: "11px 14px" }}
        />
        <button onClick={() => send()} disabled={!input.trim() || busy} className="el-btn"
          style={{ background: C.accent, color: C.onAccent, border: "none", borderRadius: 9, padding: "0 20px", fontWeight: 600, fontSize: 14, cursor: input.trim() && !busy ? "pointer" : "not-allowed", opacity: input.trim() && !busy ? 1 : 0.5 }}>
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
      <div style={{ fontFamily: mono, fontSize: 9.5, letterSpacing: ".1em", color: C.faint, marginBottom: 5 }}>
        {you ? "YOU" : "ECHOLENS"}
      </div>
      <div style={{ maxWidth: 560, padding: "12px 16px", borderRadius: 12, background: you ? C.accent : C.card, color: you ? C.onAccent : C.text2, border: you ? "none" : `1px solid ${C.border2}`, fontSize: 14, lineHeight: 1.5 }}>
        {turn.text}
      </div>
      {turn.investigationId != null && (
        <button onClick={() => onOpenInvestigation(turn.investigationId!)} className="el-btn"
          style={{ marginTop: 8, background: "transparent", border: `1px solid ${C.accent}66`, color: C.accent, borderRadius: 8, padding: "7px 13px", fontSize: 13, cursor: "pointer" }}>
          ▸ Watch case #{turn.investigationId} stream
        </button>
      )}
      {turn.citations && turn.citations.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 7, marginTop: 8 }}>
          {turn.citations.map((c) => (
            <button key={c.investigation_id} onClick={() => onOpenInvestigation(c.investigation_id)} className="el-btn"
              title={c.summary}
              style={{ display: "flex", alignItems: "center", gap: 6, background: C.card2, border: `1px solid ${C.border3}`, borderRadius: 8, padding: "5px 10px", cursor: "pointer" }}>
              <span style={{ fontFamily: mono, fontSize: 10.5, color: C.accent }}>case #{c.investigation_id}</span>
              <span style={{ fontSize: 12, color: C.muted, maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.summary}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
