import { DragEvent, useEffect, useRef, useState } from "react";
import { ImportField, ImportMapping, ImportPreview, api, errorMessage } from "../../api";
import { Button } from "../../ui";

const FIELDS: { id: ImportField; label: string; hint: string }[] = [
  { id: "text", label: "Review text", hint: "Required" },
  { id: "rating", label: "Rating", hint: "1–5 stars; rows without one are skipped" },
  { id: "version", label: "Version", hint: "Optional" },
  { id: "date", label: "Date", hint: "Optional; undated rows stay out of spike checks" },
  { id: "source", label: "Source", hint: "Optional, e.g. App Store or Google Play" },
  { id: "author", label: "Author", hint: "Optional; used in the preview only — not stored" },
];

const ACCEPT = ".csv,.xlsx,.xlsm,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

/**
 * Import reviews from a CSV or Excel export: drop or browse, see the first
 * rows, match the columns (guessed, changeable), see which rows would be
 * skipped and why, then import. Nothing is written until "Import".
 */
export function ImportPanel({ onDone, onCancel }: { onDone: (message: string) => void; onCancel: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [over, setOver] = useState(false);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [mapping, setMapping] = useState<ImportMapping | null>(null);
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState<"preview" | "import" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement | null>(null);
  const seq = useRef(0);

  // Re-check the rows whenever the file or the column matching changes.
  useEffect(() => {
    if (!file) return;
    const mine = ++seq.current;
    setBusy("preview");
    setError(null);
    api.previewImport(file, mapping, label.trim() || "CSV import")
      .then((p) => { if (mine === seq.current) { setPreview(p); if (!mapping && p.mapping) setMapping(p.mapping); } })
      .catch((e) => { if (mine === seq.current) setError(errorMessage(e)); })
      .finally(() => { if (mine === seq.current) setBusy(null); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [file, JSON.stringify(mapping)]);

  const pick = (f: File | null | undefined) => {
    if (!f) return;
    setFile(f); setPreview(null); setMapping(null); setError(null);
  };
  const onDrop = (e: DragEvent) => {
    e.preventDefault(); setOver(false);
    pick(e.dataTransfer.files?.[0]);
  };
  const run = async () => {
    if (!file || !mapping?.text) return;
    setBusy("import");
    setError(null);
    try {
      const r = await api.importReviews(file, undefined, label.trim() || "CSV import", mapping);
      const why = Object.entries(r.reasons ?? {}).map(([k, n]) => `${n.toLocaleString()} ${k}`).join(", ");
      onDone(`Imported ${r.imported.toLocaleString()} · skipped ${r.skipped.toLocaleString()}${why ? ` (${why})` : ""} from ${file.name}.`);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  const columns = preview?.columns ?? [];
  const shown = columns.slice(0, 8);
  return (
    <div className="ps-panel" role="region" aria-label="Import reviews from a file">
      <div className="ps-row" style={{ justifyContent: "space-between" }}>
        <h3 className="ps-h2" style={{ fontSize: 22 }}>Import reviews from a file</h3>
        <Button variant="quiet" size="sm" onClick={onCancel}>Close</Button>
      </div>
      <div className={`ps-drop${over ? " is-over" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)} onDrop={onDrop}>
        <strong>{file ? file.name : "Drop a CSV or Excel file here"}</strong>
        <span className="ps-muted">Any export works — App Store, Zendesk, Intercom, in-app feedback, a spreadsheet.</span>
        <Button variant="ghost" size="sm" onClick={() => input.current?.click()}>{file ? "Choose another file" : "Browse…"}</Button>
        <input ref={input} type="file" accept={ACCEPT} hidden aria-label="CSV or Excel file to import"
          onChange={(e) => pick(e.target.files?.[0])} />
      </div>

      {busy === "preview" && <div className="ps-banner" role="status">Reading the file…</div>}
      {error && <div className="ps-banner" role="alert">{error}</div>}
      {preview?.error && <div className="ps-banner" role="alert">{preview.error}</div>}

      {preview && columns.length > 0 && (
        <>
          <div>
            <div className="ps-muted" style={{ marginBottom: 8 }}>The first rows, as the file has them</div>
            <div className="ps-table-wrap">
              <table className="ps-table">
                <thead><tr>{shown.map((c) => <th key={c} scope="col">{c}</th>)}</tr></thead>
                <tbody>{preview.rows.map((r, i) => (
                  <tr key={i}>{shown.map((c) => <td key={c} title={r[c]}>{r[c]}</td>)}</tr>
                ))}</tbody>
              </table>
            </div>
            {columns.length > shown.length && <div className="ps-muted" style={{ marginTop: 6 }}>
              +{columns.length - shown.length} more columns</div>}
          </div>

          <fieldset className="ps-map" style={{ border: 0, padding: 0, margin: 0 }}>
            <legend className="ps-muted" style={{ marginBottom: 8, padding: 0 }}>Which column is which?</legend>
            {FIELDS.map((f) => (
              <label key={f.id} className="ps-field" title={f.hint}>
                <span>{f.label}{f.id === "text" ? " *" : ""}</span>
                <select className="ps-select" value={mapping?.[f.id] ?? ""}
                  onChange={(e) => setMapping({ ...(mapping ?? {}), [f.id]: e.target.value || null })}>
                  <option value="">{f.id === "text" ? "Choose a column" : "Not in this file"}</option>
                  {columns.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </label>
            ))}
          </fieldset>

          {!preview.error && preview.total != null && (
            <div className="ps-card">
              <strong style={{ fontWeight: 500 }}>
                {preview.would_import.toLocaleString()} of {preview.total.toLocaleString()} rows will be imported
                {preview.skipped ? ` · ${preview.skipped.toLocaleString()} skipped` : ""}
              </strong>
              {Object.keys(preview.reasons).length > 0 && (
                <ul className="ps-problems">
                  {Object.entries(preview.reasons).map(([why, n]) => <li key={why}>{n.toLocaleString()} — {why}</li>)}
                </ul>
              )}
              {preview.problems.length > 0 && (
                <span className="ps-muted">Rows to check: {preview.problems.slice(0, 12).map((p) => p.row).join(", ")}
                  {preview.problems.length > 12 ? "…" : ""}</span>
              )}
              {preview.undated > 0 && <span className="ps-muted">{preview.undated.toLocaleString()} rows have no date —
                they are kept for search but never counted as a new spike.</span>}
            </div>
          )}

          <div className="ps-row" style={{ alignItems: "flex-end" }}>
            <label className="ps-field" style={{ flex: "1 1 220px" }}>
              <span>Call this source (optional)</span>
              <input className="ps-input" value={label} onChange={(e) => setLabel(e.target.value)}
                placeholder="e.g. App Store reviews" />
            </label>
            <Button variant="primary" loading={busy === "import"}
              disabled={!mapping?.text || !!busy || !!preview.error || preview.would_import === 0} onClick={run}>
              Import {preview.would_import ? preview.would_import.toLocaleString() : ""} rows
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
