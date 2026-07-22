import { useEffect, useState } from "react";
import { BrainEdge, ChangeReview, api } from "../api";
import { useAsync } from "../hooks";
import { C, mono, sans } from "../theme";
import { Bar, Centered, Label, ScreenHeader } from "../ui";

const RISK: Record<string, { color: string; label: string }> = {
  high: { color: C.bad, label: "HIGH RISK" },
  elevated: { color: C.accent, label: "WORTH A CHECK" },
  clear: { color: C.good, label: "NO KNOWN HISTORY" },
};

interface Props {
  onOpenInvestigation: (id: number, status?: string) => void;
}

/**
 * The product-knowledge brain — a learned map of how this product breaks, plus
 * the two things that map is FOR: reviewing a proposed change before it ships,
 * and answering a new PM's "what goes wrong here?" from real history.
 */
export function Brain({ onOpenInvestigation }: Props) {
  const { data, loading, error } = useAsync(() => api.brain(), []);

  if (loading) return <Centered>Reading what this product has taught EchoLens…</Centered>;
  if (error || !data) return <Centered>Backend unavailable.</Centered>;

  const edges = data.edges;
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <ScreenHeader
        title={`Product Memory${data.product ? ` · ${data.product}` : ""}`}
        right={<span style={{ fontFamily: mono, fontSize: 11.5, color: C.muted }}>
          {edges.length} LEARNED PATTERN{edges.length === 1 ? "" : "S"}
        </span>}
      />
      <div style={{ flex: 1, overflow: "auto", padding: "22px 28px" }}>
        {edges.length === 0 ? (
          <div style={{ maxWidth: 720, padding: "30px 22px", border: `1px dashed ${C.border4}`,
                        borderRadius: 12, textAlign: "center", color: C.dim, fontSize: 13.5,
                        lineHeight: 1.6 }}>
            EchoLens hasn't learned this product's failure patterns yet. Each confirmed fix teaches
            it one — "changes to X tend to cause Y". Come back after a few fixes land and this becomes
            a map you can check proposed changes against.
          </div>
        ) : (
          <>
            <ReviewBox />
            <Oracle />

            <Label style={{ margin: "28px 0 4px" }}>HOW THIS PRODUCT BREAKS</Label>
            <p style={{ fontSize: 12.5, color: C.dim, margin: "0 0 14px", lineHeight: 1.55 }}>
              Learned from confirmed fixes and graded against every resolved case. A pattern that
              stops predicting decays and retires itself — the map only shows what still holds.
            </p>
            <div style={{ display: "flex", flexDirection: "column", gap: 10, maxWidth: 980 }}>
              {edges.map((e) => (
                <EdgeCard key={`${e.subsystem}-${e.symptom}`} edge={e}
                          onOpen={onOpenInvestigation} />
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function EdgeCard({ edge, onOpen }: { edge: BrainEdge; onOpen: (id: number, s?: string) => void }) {
  const conf = Math.round(edge.confidence * 100);
  const color = edge.confidence >= 0.75 ? C.bad : edge.confidence >= 0.5 ? C.accent : C.dim;
  return (
    <div className="el-card" style={{ padding: "14px 17px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <span style={{ fontFamily: mono, fontSize: 11.5, color: C.info }}>{edge.subsystem}</span>
        <span style={{ color: C.faint }}>→</span>
        <span style={{ fontSize: 14, fontWeight: 600, color: C.text }}>
          {edge.symptom.replace(/-/g, " ")}
        </span>
        {edge.trend === "weakening" && (
          <span style={{ fontFamily: mono, fontSize: 9.5, padding: "2px 7px", borderRadius: 9,
                         background: `${C.accent}1a`, color: C.accent }}>WEAKENING</span>
        )}
        <span style={{ marginLeft: "auto", fontFamily: mono, fontSize: 11, color }}>
          {conf}% · verified {edge.verified_count}×
        </span>
      </div>
      <div style={{ marginTop: 9, maxWidth: 320 }}>
        <Bar pct={conf} color={color} height={5} />
      </div>
      <div style={{ display: "flex", gap: 12, marginTop: 9, flexWrap: "wrap",
                    fontFamily: mono, fontSize: 10.5, color: C.faint }}>
        <span>{edge.supports} held · {edge.refutes} missed</span>
        {edge.case_ids.slice(0, 4).map((id) => (
          <span key={id} onClick={() => onOpen(id, "resolved")} className="el-btn" role="button"
            tabIndex={0} onKeyDown={(ev) => { if (ev.key === "Enter") onOpen(id, "resolved"); }}
            style={{ color: C.accent, cursor: "pointer" }}>
            #{id}
          </span>
        ))}
      </div>
    </div>
  );
}

// Design-doc / PR review — prevention, not detection.
function ReviewBox() {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [review, setReview] = useState<ChangeReview | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const run = async () => {
    if (!text.trim() || busy) return;
    setBusy(true);
    setErr(null);
    try {
      setReview(await api.brainReview(text.trim()));
    } catch (e) {
      setErr(String(e).replace("Error: ", ""));
    } finally {
      setBusy(false);
    }
  };

  const risk = review ? RISK[review.risk] : null;
  return (
    <div style={{ maxWidth: 980, marginBottom: 20, padding: "16px 20px", background: C.card,
                  border: `1px solid ${C.border2}`, borderRadius: 12 }}>
      <Label style={{ marginBottom: 4, color: C.accent }}>REVIEW A CHANGE BEFORE IT SHIPS</Label>
      <p style={{ fontSize: 12.5, color: C.dim, margin: "0 0 11px", lineHeight: 1.55 }}>
        Paste a spec or PR description. EchoLens checks it against what has bitten this product before.
      </p>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="e.g. Rework the background sync scheduler to batch uploads when the device is idle…"
        rows={3}
        style={{ width: "100%", background: C.bgRaised, border: `1px solid ${C.border3}`,
                 borderRadius: 8, color: C.text, fontFamily: sans, fontSize: 13,
                 padding: "10px 12px", boxSizing: "border-box", resize: "vertical" }}
      />
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 10 }}>
        <button onClick={run} disabled={!text.trim() || busy} className="el-btn"
          style={{ background: C.accent, color: C.onAccent, border: "none", borderRadius: 7,
                   padding: "9px 16px", fontWeight: 600, fontSize: 13,
                   cursor: text.trim() && !busy ? "pointer" : "not-allowed",
                   opacity: text.trim() && !busy ? 1 : 0.5 }}>
          {busy ? "Reviewing…" : "Review change"}
        </button>
        {err && <span style={{ fontSize: 12.5, color: C.bad }}>{err}</span>}
      </div>

      {review && risk && (
        <div style={{ marginTop: 14, paddingTop: 14, borderTop: `1px solid ${C.border}` }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
            <span style={{ fontFamily: mono, fontSize: 10.5, letterSpacing: ".08em",
                           padding: "3px 10px", borderRadius: 20, color: risk.color,
                           background: `${risk.color}1a`, border: `1px solid ${risk.color}55` }}>
              {risk.label}
            </span>
            <span style={{ fontSize: 13.5, color: C.text2 }}>{review.summary}</span>
          </div>
          {review.flags.map((f) => (
            <div key={`${f.subsystem}-${f.symptom}`}
                 style={{ padding: "11px 14px", background: C.card2, borderRadius: 9,
                          border: `1px solid ${C.border2}`, marginBottom: 8 }}>
              <div style={{ fontSize: 13, color: C.text3, lineHeight: 1.5 }}>{f.why}</div>
              <div style={{ fontSize: 12.5, color: C.accent, marginTop: 6 }}>
                → {f.recommendation}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// The onboarding oracle.
function Oracle() {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [answer, setAnswer] = useState<string | null>(null);

  const ask = async (question: string) => {
    const text = question.trim();
    if (!text || busy) return;
    setBusy(true);
    try {
      const r = await api.brainAsk(text);
      setAnswer(r.answer);
    } catch (e) {
      setAnswer(String(e).replace("Error: ", ""));
    } finally {
      setBusy(false);
    }
  };

  const suggestions = ["What usually goes wrong with releases here?", "Any risk around sync?"];
  return (
    <div style={{ maxWidth: 980, marginBottom: 20, padding: "16px 20px", background: C.card,
                  border: `1px solid ${C.border2}`, borderRadius: 12 }}>
      <Label style={{ marginBottom: 4, color: C.info }}>ASK THE PRODUCT'S HISTORY</Label>
      <p style={{ fontSize: 12.5, color: C.dim, margin: "0 0 11px", lineHeight: 1.55 }}>
        New to this product? Ask what tends to break instead of reading old postmortems.
      </p>
      <div style={{ display: "flex", gap: 9 }}>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && ask(q)}
          placeholder="Ask about the product's failure history…"
          style={{ flex: 1, background: C.bgRaised, border: `1px solid ${C.border3}`,
                   borderRadius: 8, color: C.text, fontFamily: sans, fontSize: 13,
                   padding: "9px 12px" }}
        />
        <button onClick={() => ask(q)} disabled={!q.trim() || busy} className="el-btn"
          style={{ background: "transparent", color: C.accent, border: `1px solid rgba(240,166,60,.4)`,
                   borderRadius: 7, padding: "9px 14px", fontSize: 13,
                   cursor: q.trim() && !busy ? "pointer" : "not-allowed" }}>
          {busy ? "…" : "Ask"}
        </button>
      </div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 9 }}>
        {suggestions.map((sug) => (
          <span key={sug} onClick={() => { setQ(sug); ask(sug); }} className="el-btn" role="button"
            tabIndex={0} onKeyDown={(e) => { if (e.key === "Enter") { setQ(sug); ask(sug); } }}
            style={{ fontSize: 11.5, color: C.muted, cursor: "pointer", padding: "4px 10px",
                     borderRadius: 20, background: C.hover, border: `1px solid ${C.border3}` }}>
            {sug}
          </span>
        ))}
      </div>
      {answer && (
        <div style={{ marginTop: 13, padding: "13px 15px", background: C.card2,
                      border: `1px solid ${C.border2}`, borderRadius: 9, fontSize: 13,
                      color: C.text3, lineHeight: 1.6, whiteSpace: "pre-wrap" }}>
          {answer}
        </div>
      )}
    </div>
  );
}
