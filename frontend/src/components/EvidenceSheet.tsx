import { useEffect } from "react";
import { Evidence } from "../api";
import { C, mono } from "../theme";

export function EvidenceSheet({ evidence, onClose }: { evidence: Evidence | null; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (!evidence) return null;

  return (
    <>
      <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(6,7,10,.55)", zIndex: 20 }} />
      <div
        style={{
          position: "fixed",
          top: 0,
          right: 0,
          bottom: 0,
          width: 400,
          background: C.card2,
          borderLeft: `1px solid ${C.border3}`,
          zIndex: 21,
          padding: 22,
          display: "flex",
          flexDirection: "column",
          gap: 14,
          boxShadow: "-20px 0 50px rgba(0,0,0,.45)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontFamily: mono, fontSize: 13, color: C.accent }}>{evidence.id}</span>
          <span style={{ fontFamily: mono, fontSize: 10, padding: "2px 8px", border: `1px solid ${C.border3}`, borderRadius: 4, color: C.muted, textTransform: "uppercase" }}>
            {evidence.source}
          </span>
          <button onClick={onClose} style={{ marginLeft: "auto", background: "none", border: "none", color: C.muted, fontSize: 16, cursor: "pointer" }}>
            ✕
          </button>
        </div>
        <div style={{ padding: 16, background: C.bgRaised, border: `1px solid ${C.border}`, borderRadius: 9, fontSize: 13.5, lineHeight: 1.65, color: C.text2 }}>
          “{evidence.snippet}”
        </div>
        <div style={{ fontSize: 12, color: C.muted, lineHeight: 1.7 }}>
          <div>
            <span style={{ color: C.faint }}>Ref</span> — {evidence.ref}
          </div>
          <div>
            <span style={{ color: C.faint }}>Retrieved by</span> — <span style={{ fontFamily: mono }}>{evidence.retrieved_by}</span>
          </div>
          <div>
            <span style={{ color: C.faint }}>Supports</span> — <span style={{ color: C.good }}>{evidence.supports.join(", ") || "—"}</span>
          </div>
          {evidence.contradicts.length > 0 && (
            <div>
              <span style={{ color: C.faint }}>Contradicts</span> — <span style={{ color: C.bad }}>{evidence.contradicts.join(", ")}</span>
            </div>
          )}
        </div>
        <div style={{ fontSize: 11.5, color: C.faint, fontStyle: "italic" }}>
          Raw source preserved verbatim. EchoLens never paraphrases evidence into the record. Press Esc to close.
        </div>
      </div>
    </>
  );
}
