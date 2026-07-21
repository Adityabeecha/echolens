import { useEffect, useState } from "react";
import { DeletionPreview, ProductRow, api } from "../api";
import { useAsync } from "../hooks";
import { C, mono, sans } from "../theme";

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

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, busy]);

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
      onClick={() => !busy && onClose()}
      style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.62)", zIndex: 60,
               display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={`Delete ${product.name}`}
        style={{ width: "100%", maxWidth: 460, background: C.card,
                 border: `1px solid ${C.bad}55`, borderRadius: 14, padding: "22px 24px",
                 boxShadow: "0 24px 60px rgba(0,0,0,.55)" }}
      >
        <div style={{ fontFamily: mono, fontSize: 10, letterSpacing: ".12em", color: C.bad,
                      marginBottom: 8 }}>
          PERMANENT
        </div>
        <div style={{ fontSize: 17, fontWeight: 600, color: C.text, marginBottom: 8 }}>
          Delete {product.name}?
        </div>

        {loading ? (
          <div style={{ fontSize: 13, color: C.dim, margin: "12px 0" }}>
            Checking what this would remove…
          </div>
        ) : (
          <>
            <p style={{ fontSize: 13, color: C.muted, lineHeight: 1.6, margin: "0 0 14px" }}>
              This removes the product and everything EchoLens learned about it. It cannot be
              undone.
            </p>
            {rows.length > 0 ? (
              <div style={{ border: `1px solid ${C.border2}`, borderRadius: 9, overflow: "hidden",
                            marginBottom: 16 }}>
                {rows.map(([label, n]) => (
                  <div key={label}
                    style={{ display: "flex", justifyContent: "space-between", alignItems: "center",
                             padding: "9px 13px", borderBottom: `1px solid ${C.border}`,
                             background: C.card2 }}>
                    <span style={{ fontSize: 12.5, color: C.text3 }}>{label}</span>
                    <span style={{ fontFamily: mono, fontSize: 12.5, color: C.bad,
                                   fontVariantNumeric: "tabular-nums" }}>
                      {n.toLocaleString()}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ fontSize: 12.5, color: C.dim, marginBottom: 16 }}>
                Nothing has been collected for this product yet.
              </div>
            )}
          </>
        )}

        <label style={{ display: "block", fontSize: 12.5, color: C.text3, marginBottom: 7 }}>
          Type <span style={{ fontFamily: mono, color: C.text }}>{product.name}</span> to confirm
        </label>
        <input
          autoFocus
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && remove()}
          placeholder={product.name}
          style={{ width: "100%", background: C.bgRaised, border: `1px solid ${matches ? C.bad : C.border3}`,
                   borderRadius: 8, color: C.text, fontFamily: mono, fontSize: 13.5,
                   padding: "10px 12px", boxSizing: "border-box" }}
        />

        {error && (
          <div style={{ marginTop: 12, padding: "9px 12px", border: `1px solid ${C.bad}55`,
                        background: `${C.bad}14`, borderRadius: 8, fontSize: 12.5, color: C.bad }}>
            {error}
          </div>
        )}

        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", marginTop: 18 }}>
          <button onClick={onClose} disabled={busy} className="el-btn"
            style={{ background: "transparent", color: C.muted, border: `1px solid ${C.border3}`,
                     borderRadius: 7, padding: "9px 16px", fontSize: 13, fontFamily: sans,
                     cursor: "pointer" }}>
            Keep it
          </button>
          <button onClick={remove} disabled={!matches || busy} className="el-btn"
            style={{ background: matches ? C.bad : C.hover, color: matches ? "#fff" : C.dim,
                     border: "none", borderRadius: 7, padding: "9px 16px", fontWeight: 600,
                     fontSize: 13, fontFamily: sans,
                     cursor: matches && !busy ? "pointer" : "not-allowed" }}>
            {busy ? "Deleting…" : "Delete permanently"}
          </button>
        </div>
      </div>
    </div>
  );
}
