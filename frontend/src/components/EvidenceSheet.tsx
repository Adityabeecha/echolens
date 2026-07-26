import { Evidence } from "../api";
import { useDialog } from "../hooks";
import { C, R, S, T, mono } from "../theme";
import { Icon } from "./Icon";

export function EvidenceSheet({ evidence, onClose }: { evidence: Evidence | null; onClose: () => void }) {
  // Escape, focus-in on open, focus-return on close, and a Tab cycle that
  // stays inside the sheet.
  const ref = useDialog(onClose, !!evidence);

  if (!evidence) return null;

  return (
    <>
      <div onClick={onClose} aria-hidden="true"
           style={{ position: "fixed", inset: 0, background: "rgba(6,7,10,.55)", zIndex: 20 }} />
      <div
        // Announced as a dialog. Without a role a screen reader treated this as
        // ordinary page content, so focus stayed on the obscured page behind it
        // and Tab cycled through the case detail rather than the sheet.
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label="Evidence detail"
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
          gap: S[3],
          boxShadow: "-20px 0 50px rgba(0,0,0,.45)"
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: S[2] }}>
          <span style={{ fontFamily: mono, fontSize: T.base, color: C.accent }}>{evidence.id}</span>
          <span style={{ fontFamily: mono, fontSize: T.micro, padding: `0 ${S[2]}`, border: `1px solid ${C.border3}`, borderRadius: R.sm, color: C.muted, textTransform: "uppercase" }}>
            {evidence.source}
          </span>
          <button onClick={onClose} style={{ marginLeft: "auto", background: "none", border: "none", color: C.muted, fontSize: T.lg }}>
            <Icon name="close" size={15} />
          </button>
        </div>
        <div style={{ padding: 16, background: C.bgRaised, border: `1px solid ${C.border}`, borderRadius: R.control, fontSize: T.base, lineHeight: "var(--el-lh-normal)", color: C.text2 }}>
          “{evidence.snippet}”
        </div>
        <div style={{ fontSize: T.sm, color: C.muted, lineHeight: "var(--el-lh-normal)" }}>
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
        <div style={{ fontSize: T.xs, color: C.faint, fontStyle: "italic" }}>
          Raw source preserved verbatim. EchoLens never paraphrases evidence into the record. Press Esc to close.
        </div>
      </div>
    </>
  );
}
