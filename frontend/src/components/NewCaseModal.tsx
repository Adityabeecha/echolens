import { useState } from "react";
import { api } from "../api";
import { C, mono } from "../theme";

const TIERS: { key: string; name: string; detail: string }[] = [
  { key: "quick", name: "Quick look", detail: "5 iter · $0.25 · 15 min" },
  { key: "standard", name: "Standard", detail: "12 iter · $0.75 · 45 min" },
  { key: "deep", name: "Deep dive", detail: "30 iter · $2.00 · 2 h" },
];

export function NewCaseModal({ onClose, onStarted }: { onClose: () => void; onStarted: (investigationId: number) => void }) {
  const [desc, setDesc] = useState("");
  const [tier, setTier] = useState("standard");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!desc.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.startInvestigation({ description: desc, tier });
      onStarted(r.investigation_id);
    } catch (e) {
      // surface the reason instead of silently doing nothing
      const msg = String(e).replace("Error: ", "");
      setError(
        /403|401|token|admin|reviewer/i.test(msg)
          ? "You need reviewer or admin access to start an investigation."
          : msg || "Could not start the investigation. Is the backend awake?"
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(6,7,10,.6)", zIndex: 30 }} />
      <div
        style={{
          position: "fixed",
          top: "50%",
          left: "50%",
          transform: "translate(-50%,-50%)",
          width: 520,
          maxWidth: "92vw",
          background: C.card2,
          border: `1px solid ${C.border3}`,
          borderRadius: 14,
          zIndex: 31,
          padding: 24,
          boxShadow: "0 30px 80px rgba(0,0,0,.55)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
          <div style={{ fontSize: 16, fontWeight: 600 }}>Open a case</div>
          <button onClick={onClose} style={{ marginLeft: "auto", background: "none", border: "none", color: C.muted, fontSize: 16, cursor: "pointer" }}>
            ✕
          </button>
        </div>
        <div style={{ fontSize: 12.5, color: C.muted, marginBottom: 6 }}>What should the investigator look into?</div>
        <textarea
          value={desc}
          onChange={(e) => setDesc(e.target.value)}
          placeholder="e.g. Users report the share sheet freezing on Samsung devices since last week"
          style={{ width: "100%", height: 70, background: C.bgRaised, border: `1px solid ${C.border3}`, borderRadius: 7, color: C.text, fontFamily: "inherit", fontSize: 13, padding: 10, resize: "vertical" }}
        />
        <div style={{ fontSize: 12.5, color: C.muted, margin: "14px 0 6px" }}>Budget</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {TIERS.map((t) => (
            <div
              key={t.key}
              onClick={() => setTier(t.key)}
              style={{ padding: "7px 10px", border: `1px solid ${tier === t.key ? "rgba(240,166,60,.45)" : C.border3}`, borderRadius: 6, cursor: "pointer", background: tier === t.key ? "rgba(240,166,60,.06)" : "transparent" }}
            >
              <div style={{ fontSize: 12.5, fontWeight: 500, color: C.text2 }}>{t.name}</div>
              <div style={{ fontFamily: mono, fontSize: 10, color: C.faint, marginTop: 2 }}>{t.detail}</div>
            </div>
          ))}
        </div>
        {error && (
          <div style={{ marginTop: 14, padding: "9px 12px", borderRadius: 7, background: "rgba(224,88,79,.08)", border: "1px solid rgba(224,88,79,.35)", color: C.bad, fontSize: 12.5 }}>
            {error}
          </div>
        )}
        <button
          onClick={submit}
          disabled={!desc.trim() || busy}
          style={{ marginTop: 18, width: "100%", padding: "11px 0", borderRadius: 8, border: "none", background: C.accent, color: C.onAccent, fontSize: 14, fontWeight: 600, cursor: desc.trim() ? "pointer" : "not-allowed", opacity: desc.trim() ? 1 : 0.45 }}
        >
          {busy ? "Starting…" : "Start investigation"}
        </button>
        <div style={{ fontSize: 11, color: C.ghost, marginTop: 8, textAlign: "center" }}>
          Runs within your daily and per-case limits.
        </div>
      </div>
    </>
  );
}
