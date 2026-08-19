import { useState } from "react";
import { api } from "../api";
import { useDialog } from "../hooks";
import { toast } from "./Toast";
import { C, R, S, T, mono } from "../theme";
import { Icon } from "./Icon";

const TIERS: { key: string; name: string; detail: string }[] = [
  { key: "quick", name: "Quick look", detail: "5 iter · $0.25 · shallow — may only skim a few reviews" },
  { key: "standard", name: "Standard", detail: "12 iter · $0.75 · gathers evidence across sources (recommended)" },
  { key: "deep", name: "Deep dive", detail: "30 iter · $2.00 · widest search, strongest corroboration" },
];

export function NewCaseModal({ onClose, onStarted }: { onClose: () => void; onStarted: (investigationId: number) => void }) {
  const [desc, setDesc] = useState("");
  const [tier, setTier] = useState("standard");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // This dialog had no Escape handler, no dialog role and no focus management
  // at all: opening it left the keyboard on the page behind it.
  const ref = useDialog(onClose, true, !busy);

  const submit = async () => {
    if (!desc.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.startInvestigation({ description: desc, tier });
      toast.ok(`Case #${r.investigation_id} opened — it’s streaming now.`);
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
      <div className="el-overlay-scrim" onClick={onClose} aria-hidden="true"
           style={{ position: "fixed", inset: 0, background: "var(--el-scrim)", zIndex: 30 }} />
      <div
        className="el-overlay-panel el-new-case-modal"
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label="Open a case"
        style={{
          position: "fixed",
          top: "50%",
          left: "50%",
          transform: "translate(-50%,-50%)",
          width: 520,
          // 520px overflowed a 375px phone by 145px. maxWidth was already set
          // to 92vw below, but `width` wins over it for the BOX unless the
          // ceiling is also absolute — keep both.
          maxWidth: "min(520px, 92vw)",
          background: C.card,
          border: `1px solid ${C.border3}`,
          borderRadius: R.overlay,
          zIndex: 31,
          padding: S[6],
          boxShadow: "var(--el-e4)"
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: S[2], marginBottom: S[4] }}>
          <div style={{ fontSize: T.lg, fontWeight: 600 }}>Open a case</div>
          <button onClick={onClose} aria-label="Close"
                  className="el-btn el-btn--sm"
                  style={{ marginLeft: "auto", color: C.muted }}>
            <Icon name="close" size={15} />
          </button>
        </div>
        <div style={{ fontSize: T.sm, color: C.muted, marginBottom: S[1] }}>What should the investigator look into?</div>
        <textarea
          aria-label="What should the investigator look into?"
          value={desc}
          onChange={(e) => setDesc(e.target.value)}
          placeholder="e.g. Users report the share sheet freezing on Samsung devices since last week"
          style={{ width: "100%", height: 70, background: C.bgRaised, border: `1px solid ${C.border3}`, borderRadius: R.control, color: C.text, fontFamily: "inherit", fontSize: T.base, padding: 10, resize: "vertical" }}
        />
        <div style={{ fontSize: T.sm, color: C.muted, margin: "14px 0 6px" }}>Budget</div>
        <div style={{ display: "flex", flexDirection: "column", gap: S[1] }}>
          {TIERS.map((t) => (
            // A radio group, and now actually operable as one. With no role,
            // tabIndex or key handler a keyboard-only user could reach the
            // textarea and the submit button but COULD NOT change the budget
            // tier at all — it was permanently locked to the default.
            <div
              key={t.key}
              role="radio"
              aria-checked={tier === t.key}
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setTier(t.key); }
              }}
              onClick={() => setTier(t.key)}
              style={{ padding: `${S[2]} ${S[2]}`, border: `1px solid ${tier === t.key ? "var(--el-accent-line)" : C.border3}`, borderRadius: R.control, background: tier === t.key ? "var(--el-accent-bg)" : "transparent" }}
            >
              <div style={{ fontSize: T.sm, fontWeight: 500, color: C.text2 }}>{t.name}</div>
              <div style={{ fontFamily: mono, fontSize: T.micro, color: C.faint, marginTop: 0 }}>{t.detail}</div>
            </div>
          ))}
        </div>
        {error && (
          <div style={{ marginTop: S[3], padding: `${S[2]} ${S[3]}`, borderRadius: R.control, background: "var(--el-bad-bg)", border: "1px solid var(--el-bad-line)", color: C.bad, fontSize: T.sm }}>
            {error}
          </div>
        )}
        <button
          onClick={submit}
          disabled={!desc.trim() || busy}
          style={{ marginTop: S[4], width: "100%", padding: `${S[3]} 0`, borderRadius: R.control, border: "none", background: C.accent, color: C.onAccent, fontSize: T.md, fontWeight: 600, cursor: desc.trim() ? "pointer" : "not-allowed", opacity: desc.trim() ? 1 : 0.45 }}
        >
          {busy ? "Starting…" : "Start investigation"}
        </button>
        <div style={{ fontSize: T.xs, color: C.ghost, marginTop: S[2], textAlign: "center" }}>
          Runs within your daily and per-case limits.
        </div>
      </div>
    </>
  );
}
