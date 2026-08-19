import { useState } from "react";
import { DeletionPreview, ProductRow, api } from "../api";
import { useAsync, useDialog } from "../hooks";
import { C, R, S, T, mono, sans } from "../theme";

interface Props {
  product: ProductRow;
  onClose: () => void;
  onDeleted: (id: number) => void;
}

/**
 * Deleting a product destroys its whole history, so the dialog does two things
 * a generic "are you sure?" doesn't: it states the real counts fetched from the
 * server, and it requires the name typed exactly (which the backend enforces
 * too — the button being disabled is a courtesy, not the guard).
 */
export function DeleteProductModal({ product, onClose, onDeleted }: Props) {
  const { data: preview, loading } = useAsync<DeletionPreview>(
    () => api.deletionPreview(product.id), [product.id]);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Escape is ignored mid-delete: closing the dialog while the request is in
  // flight would hide an operation the user cannot then confirm finished.
  const ref = useDialog(onClose, true, !busy);

  const matches = typed.trim() === product.name;

  const remove = async () => {
    if (!matches || busy) return;
    setBusy(true);
    setError(null);
    try {
      await api.deleteProduct(product.id, product.name);
      onDeleted(product.id);
    } catch (e) {
      setError(String(e).replace("Error: ", ""));
      setBusy(false);
    }
  };

  const rows: [string, number][] = preview
    ? [
        ["Reviews & feedback", preview.reviews],
        ["Cases", preview.cases],
        ["Findings", preview.findings],
        ["Signals", preview.anomalies],
        ["Connected sources", preview.sources],
      ].filter(([, n]) => (n as number) > 0) as [string, number][]
    : [];

  return (
    <div
      className="el-overlay-scrim"
      onClick={() => !busy && onClose()}
      style={{ position: "fixed", inset: 0, background: "var(--el-scrim)", zIndex: 60,
               display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}
    >
      <div
        className="el-overlay-panel el-delete-product-modal"
        onClick={(e) => e.stopPropagation()}
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={`Delete ${product.name}`}
        style={{ width: "100%", maxWidth: 460, background: C.card,
                 border: `1px solid ${C.bad}55`, borderRadius: R.overlay, padding: `${S[5]} ${S[6]}`,
                 boxShadow: "var(--el-e4)" }}
      >
        <div style={{ fontFamily: mono, fontSize: T.micro, letterSpacing: ".12em", color: C.bad,
                      marginBottom: S[2] }}>
          PERMANENT
        </div>
        <div style={{ fontSize: T.lg, fontWeight: 600, color: C.text, marginBottom: S[2] }}>
          Delete {product.name}?
        </div>

        {loading ? (
          <div style={{ fontSize: T.base, color: C.dim, margin: "12px 0" }}>
            Checking what this would remove…
          </div>
        ) : (
          <>
            <p style={{ fontSize: T.base, color: C.muted, lineHeight: "var(--el-lh-normal)", margin: "0 0 14px" }}>
              This removes the product and everything EchoLens learned about it. It cannot be
              undone.
            </p>
            {rows.length > 0 ? (
              <div style={{ border: `1px solid ${C.border2}`, borderRadius: R.control, overflow: "hidden",
                            marginBottom: S[4] }}>
                {rows.map(([label, n]) => (
                  <div key={label}
                    style={{ display: "flex", justifyContent: "space-between", alignItems: "center",
                             padding: `${S[2]} ${S[3]}`, borderBottom: `1px solid ${C.border}`,
                             background: C.card2 }}>
                    <span style={{ fontSize: T.sm, color: C.text3 }}>{label}</span>
                    <span style={{ fontFamily: mono, fontSize: T.sm, color: C.bad,
                                   fontVariantNumeric: "tabular-nums" }}>
                      {n.toLocaleString()}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ fontSize: T.sm, color: C.dim, marginBottom: S[4] }}>
                Nothing has been collected for this product yet.
              </div>
            )}
          </>
        )}

        <label style={{ display: "block", fontSize: T.sm, color: C.text3, marginBottom: S[2] }}>
          Type <span style={{ fontFamily: mono, color: C.text }}>{product.name}</span> to confirm
        </label>
        <input
          aria-label="Type the product name to confirm deletion"
          autoFocus
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && remove()}
          placeholder={product.name}
          style={{ width: "100%", background: C.bgRaised, border: `1px solid ${matches ? C.bad : C.border3}`,
                   borderRadius: R.control, color: C.text, fontFamily: mono, fontSize: T.base,
                   padding: `${S[2]} ${S[3]}`, boxSizing: "border-box" }}
        />

        {error && (
          <div style={{ marginTop: S[3], padding: `${S[2]} ${S[3]}`, border: `1px solid ${C.bad}55`,
                        background: `${C.bad}14`, borderRadius: R.control, fontSize: T.sm, color: C.bad }}>
            {error}
          </div>
        )}

        <div style={{ display: "flex", gap: S[2], justifyContent: "flex-end", marginTop: S[4] }}>
          <button onClick={onClose} disabled={busy} className="el-btn"
            style={{ background: "transparent", color: C.muted, border: `1px solid ${C.border3}`,
                     borderRadius: R.control, padding: `${S[2]} ${S[4]}`, fontSize: T.base, fontFamily: sans }}>
            Keep it
          </button>
          <button onClick={remove} disabled={!matches || busy} className="el-btn"
            style={{ background: matches ? C.bad : C.hover, color: matches ? "#fff" : C.dim,
                     border: "none", borderRadius: R.control, padding: `${S[2]} ${S[4]}`, fontWeight: 600,
                     fontSize: T.base, fontFamily: sans,
                     cursor: matches && !busy ? "pointer" : "not-allowed" }}>
            {busy ? "Deleting…" : "Delete permanently"}
          </button>
        </div>
      </div>
    </div>
  );
}
