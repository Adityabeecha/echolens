import { useEffect, useState } from "react";
import { BrainEdge, ChangeReview, api } from "../api";
import { useAsync } from "../hooks";
import { C, MEASURE, R, S, T, mono, sans } from "../theme";
import { Bar, Centered, EmptyState, ErrorState, Label, ScreenHeader } from "../ui";

const RISK: Record<string, { color: string; label: string }> = {
  high: { color: C.bad, label: "HIGH RISK" },
  elevated: { color: C.accent, label: "WORTH A CHECK" },
  clear: { color: C.good, label: "NO KNOWN HISTORY" },
};

interface Props {
  onOpenInvestigation: (id: number, status?: string) => void;
  onBack: () => void;
  backLabel: string;
  onGoCases: () => void;
}

/**
 * The product-knowledge brain — a learned map of how this product breaks, plus
 * the two things that map is FOR: reviewing a proposed change before it ships,
 * and answering a new PM's "what goes wrong here?" from real history.
 */
export function Brain({ onOpenInvestigation, onBack, backLabel, onGoCases }: Props) {
  const { data, loading, error, reload } = useAsync(() => api.brain(), []);

  if (loading && !data) return <Centered>Reading what this product has taught EchoLens…</Centered>;
  if (error || !data) {
    return (
      <div style={{ padding: 28 }}>
        <ErrorState title="Couldn't load this product's memory" onRetry={reload} />
      </div>
    );
  }

  const edges = data.edges;
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <ScreenHeader
        title="Product memory"
        product={data.product}
        subtitle="How this product breaks, learned from confirmed fixes"
        back={{ label: backLabel, onClick: onBack }}
        right={<span style={{ fontFamily: mono, fontSize: T.xs, color: C.muted }}>
          {edges.length} LEARNED PATTERN{edges.length === 1 ? "" : "S"}
        </span>}
      />
      <div style={{ flex: 1, overflow: "auto", padding: `${S[5]} ${S[6]}` }}>
        {edges.length === 0 ? (
          <EmptyState
            title={`EchoLens hasn't learned how ${data.product || "this product"} breaks yet`}
            body={'Each confirmed fix teaches it one rule — "changes to X tend to cause Y". Once a few fixes land, this becomes a map you can check a proposed change against before it ships.'}
            action="Go to Cases"
            onAction={onGoCases}
          />
        ) : (
          <>
            <ReviewBox />
            <Oracle />

            <Label style={{ margin: "28px 0 4px" }}>HOW THIS PRODUCT BREAKS</Label>
            <p style={{ fontSize: T.sm, color: C.dim, margin: "0 0 14px", lineHeight: "var(--el-lh-normal)" }}>
              Learned from confirmed fixes and graded against every resolved case. A pattern that
              stops predicting decays and retires itself — the map only shows what still holds.
            </p>
            <div style={{ display: "flex", flexDirection: "column", gap: S[2], maxWidth: MEASURE }}>
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
    <div className="el-card" style={{ padding: `${S[3]} ${S[4]}` }}>
      <div style={{ display: "flex", alignItems: "center", gap: S[3], flexWrap: "wrap" }}>
        <span style={{ fontFamily: mono, fontSize: T.xs, color: C.info }}>{edge.subsystem}</span>
        <span style={{ color: C.faint }}>→</span>
        <span style={{ fontSize: T.md, fontWeight: 600, color: C.text }}>
          {edge.symptom.replace(/-/g, " ")}
        </span>
        {edge.trend === "weakening" && (
          <span style={{ fontFamily: mono, fontSize: T.micro, padding: `0 ${S[2]}`, borderRadius: R.control,
                         background: `${C.accent}1a`, color: C.accent }}>WEAKENING</span>
        )}
        <span style={{ marginLeft: "auto", fontFamily: mono, fontSize: T.xs, color }}>
          {conf}% · verified {edge.verified_count}×
        </span>
      </div>
      <div style={{ marginTop: S[2], maxWidth: 320 }}>
        <Bar pct={conf} color={color} height={5} />
      </div>
      <div style={{ display: "flex", gap: S[3], marginTop: S[2], flexWrap: "wrap",
                    fontFamily: mono, fontSize: T.micro, color: C.faint }}>
        <span>{edge.supports} held · {edge.refutes} missed</span>
        {edge.case_ids.slice(0, 4).map((id) => (
          <button key={id} onClick={() => onOpen(id, "resolved")}
            className="el-btn el-btn--sm"
            style={{ color: C.accent, padding: `0 ${S[1]}` }}>
            #{id}
          </button>
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
    <div style={{ maxWidth: MEASURE, marginBottom: S[5], padding: `${S[4]} ${S[5]}`, background: C.card,
                  border: `1px solid ${C.border2}`, borderRadius: R.card }}>
      <Label style={{ marginBottom: S[1], color: C.accent }}>REVIEW A CHANGE BEFORE IT SHIPS</Label>
      <p style={{ fontSize: T.sm, color: C.dim, margin: "0 0 11px", lineHeight: "var(--el-lh-normal)" }}>
        Paste a spec or PR description. EchoLens checks it against what has bitten this product before.
      </p>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="e.g. Rework the background sync scheduler to batch uploads when the device is idle…"
        rows={3}
        style={{ width: "100%", background: C.bgRaised, border: `1px solid ${C.border3}`,
                 borderRadius: R.control, color: C.text, fontFamily: sans, fontSize: T.base,
                 padding: `${S[2]} ${S[3]}`, boxSizing: "border-box", resize: "vertical" }}
      />
      <div style={{ display: "flex", alignItems: "center", gap: S[3], marginTop: S[2] }}>
        <button onClick={run} disabled={!text.trim() || busy} className="el-btn el-btn--primary"
          style={{ borderRadius: R.control,
                   padding: `${S[2]} ${S[4]}`, fontWeight: 600, fontSize: T.base,
                   cursor: text.trim() && !busy ? "pointer" : "not-allowed",
                   opacity: text.trim() && !busy ? 1 : 0.5 }}>
          {busy ? "Reviewing…" : "Review change"}
        </button>
        {err && <span style={{ fontSize: T.sm, color: C.bad }}>{err}</span>}
      </div>

      {review && risk && (
        <div style={{ marginTop: S[3], paddingTop: 14, borderTop: `1px solid ${C.border}` }}>
          <div style={{ display: "flex", alignItems: "center", gap: S[2], marginBottom: S[2] }}>
            <span style={{ fontFamily: mono, fontSize: T.micro, letterSpacing: ".08em",
                           padding: `${S[1]} ${S[2]}`, borderRadius: R.pill, color: risk.color,
                           background: `${risk.color}1a`, border: `1px solid ${risk.color}55` }}>
              {risk.label}
            </span>
            <span style={{ fontSize: T.base, color: C.text2 }}>{review.summary}</span>
          </div>
          {review.flags.map((f) => (
            <div key={`${f.subsystem}-${f.symptom}`}
                 style={{ padding: `${S[3]} ${S[3]}`, background: C.card2, borderRadius: R.control,
                          border: `1px solid ${C.border2}`, marginBottom: S[2] }}>
              <div style={{ fontSize: T.base, color: C.text3, lineHeight: "var(--el-lh-normal)" }}>{f.why}</div>
              <div style={{ fontSize: T.sm, color: C.accent, marginTop: S[1] }}>
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
  const [askError, setAskError] = useState<string | null>(null);

  const ask = async (question: string) => {
    const text = question.trim();
    if (!text || busy) return;
    setBusy(true);
    setAskError(null);
    try {
      const r = await api.brainAsk(text);
      setAnswer(r.answer);
    } catch (e) {
      // An API error must NOT render in the answer panel styled exactly like a
      // grounded response — on a screen whose whole premise is "cited to real
      // history", "/brain/ask → 500" read as product knowledge.
      setAnswer(null);
      setAskError(String(e).replace("Error: ", ""));
    } finally {
      setBusy(false);
    }
  };

  const suggestions = ["What usually goes wrong with releases here?", "Any risk around sync?"];
  return (
    <div style={{ maxWidth: MEASURE, marginBottom: S[5], padding: `${S[4]} ${S[5]}`, background: C.card,
                  border: `1px solid ${C.border2}`, borderRadius: R.card }}>
      <Label style={{ marginBottom: S[1], color: C.info }}>ASK THE PRODUCT'S HISTORY</Label>
      <p style={{ fontSize: T.sm, color: C.dim, margin: "0 0 11px", lineHeight: "var(--el-lh-normal)" }}>
        New to this product? Ask what tends to break instead of reading old postmortems.
      </p>
      <div style={{ display: "flex", gap: S[2] }}>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && ask(q)}
          placeholder="Ask about the product's failure history…"
          style={{ flex: 1, background: C.bgRaised, border: `1px solid ${C.border3}`,
                   borderRadius: R.control, color: C.text, fontFamily: sans, fontSize: T.base,
                   padding: `${S[2]} ${S[3]}` }}
        />
        <button onClick={() => ask(q)} disabled={!q.trim() || busy} className="el-btn"
          style={{ background: "transparent", color: C.accent, border: `1px solid rgba(240,166,60,.4)`,
                   borderRadius: R.control, padding: `${S[2]} ${S[3]}`, fontSize: T.base,
                   cursor: q.trim() && !busy ? "pointer" : "not-allowed" }}>
          {busy ? "…" : "Ask"}
        </button>
      </div>
      <div style={{ display: "flex", gap: S[2], flexWrap: "wrap", marginTop: S[2] }}>
        {suggestions.map((sug) => (
          <button key={sug} onClick={() => { setQ(sug); ask(sug); }} className="el-btn"
            style={{ fontSize: T.xs, color: C.muted, padding: `${S[1]} ${S[3]}`,
                     borderRadius: R.pill, background: C.hover, border: `1px solid ${C.border3}` }}>
            {sug}
          </button>
        ))}
      </div>
      {askError && (
        <div style={{ marginTop: S[3], padding: `${S[3]} ${S[3]}`, background: `${C.bad}12`,
                      border: `1px solid ${C.bad}55`, borderRadius: R.control, fontSize: T.sm,
                      color: C.text3, display: "flex", alignItems: "center", gap: S[2] }}>
          <span style={{ color: C.bad }}>⚠</span>
          <span>Couldn't reach the product's history — {askError}</span>
        </div>
      )}
      {answer && (
        <div style={{ marginTop: S[3], padding: `${S[3]} ${S[4]}`, background: C.card2,
                      border: `1px solid ${C.border2}`, borderRadius: R.control, fontSize: T.base,
                      color: C.text3, lineHeight: "var(--el-lh-normal)", whiteSpace: "pre-wrap" }}>
          {answer}
        </div>
      )}
    </div>
  );
}
