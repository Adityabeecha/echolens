import { useState } from "react";
import { api, canReview, isAdmin } from "../api";
import { count, duration, plural, relativeWhen, when } from "../format";
import { useAsync, useDialog } from "../hooks";
import { C, MEASURE, R, S, T, mono } from "../theme";
import { Centered, EmptyState, ErrorState, GhostButton, Label, ScreenHeader } from "../ui";

const STATUS_COLOR: Record<string, string> = {
  Healthy: C.good,
  "Rate-limited": C.accent,
  Disconnected: C.bad,
  Error: C.bad,
  Stale: C.accent,
  "Syncing…": C.accent,
  Idle: C.muted
};

export function Sources({ onAddProduct, productName, openImport = false }: {
  onAddProduct?: () => void; productName: string | null;
  /** Arrive with the import form open (the header's "Import CSV"). */
  openImport?: boolean;
}) {
  const { data, loading, error, reload } = useAsync(() => api.sources(), []);
  const [showConnect, setShowConnect] = useState(false);
  const [showImport, setShowImport] = useState(openImport);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [resetTarget, setResetTarget] = useState<{ source: string; identifier: string } | null>(null);
  const resetDialog = useDialog(() => setResetTarget(null), !!resetTarget, !busy);
  const reviewer = canReview();
  const admin = isAdmin();

  const resetSource = async () => {
    if (!resetTarget || busy || !isAdmin()) return;
    const { source, identifier } = resetTarget;
    setBusy(`reset-${source}-${identifier}`);
    setMsg(null);
    try {
      const r = await api.collectorsReset(source, identifier);
      setMsg(r.error ? `Re-sync failed: ${r.error}` :
        `Re-synced ${identifier}: ${count(r.inserted)} new ${plural(r.inserted, "item")}, ${count(r.skipped_duplicate)} ${plural(r.skipped_duplicate, "duplicate")} skipped from ${count(r.fetched)} fetched in ${duration(r.duration_seconds)}.`);
      reload();
    } catch (e) {
      setMsg(String(e).replace("Error: ", ""));
    } finally {
      setBusy(null);
      setResetTarget(null);
    }
  };

  const retry = async (source: string, identifier: string) => {
    setBusy(`retry-${identifier}`);
    setMsg(null);
    try {
      const r = await api.collectorsRetry(source, identifier);
      setMsg(r.error ? `Retry failed: ${r.error}` : `Retried ${identifier} — ${r.inserted} new items.`);
      reload();
    } catch (e) {
      setMsg(String(e).replace("Error: ", ""));
    } finally {
      setBusy(null);
    }
  };

  const collect = async () => {
    setBusy("collect");
    setMsg(null);
    try {
      const r = await api.collectorsRun();
      const got = r.results.reduce((n, x) => n + x.inserted, 0);
      const failed = r.results.filter((x) => x.error).length;
      setMsg(`Collected ${got} new items across ${r.results.length} source(s) in ${r.duration_seconds.toFixed(1)}s${
        failed ? ` â€” ${failed} source(s) need attention.` : "."
      }`);
      reload();
    } catch (e) {
      setMsg(String(e).replace("Error: ", ""));
    } finally {
      setBusy(null);
    }
  };

  const translate = async () => {
    if (!reviewer || busy) return;
    setBusy("translate");
    setMsg(null);
    try {
      const r = await api.translateReviews();
      const { toast } = await import("../components/Toast");
      const result = `Translated ${count(r.translated)} ${plural(r.translated, "review")}, ${count(r.pending)} pending${
        r.stopped ? ` — stopped: ${r.stopped}` : ""
      }.${r.note ? ` ${r.note}` : ""}`;
      if (r.stopped) toast.info(result);
      else toast.ok(result);
      reload();
    } catch (e) {
      setMsg(`Couldn't translate reviews: ${String(e).replace("Error: ", "")}`);
    } finally {
      setBusy(null);
    }
  };

  if (loading && !data) return <Centered>Loading sources…</Centered>;
  if (error && !data) {
    return (
      <div style={{ padding: 28 }}>
        <ErrorState title="Couldn't load your sources" onRetry={reload} />
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <ScreenHeader
        title="Sources"
        product={productName ?? data?.product}
        subtitle="Where this product's feedback comes from"
        right={
          reviewer ? (
            <div style={{ display: "flex", gap: S[2], flexWrap: "wrap", justifyContent: "flex-end" }}>
              <button onClick={collect} disabled={!!busy} className="el-btn"
                style={{ background: "transparent", color: C.muted, border: `1px solid ${C.border3}`, borderRadius: R.control, padding: `${S[2]} ${S[3]}`, fontSize: T.base }}>
                {busy === "collect" ? "Collecting…" : "Collect now"}
              </button>
              <button onClick={translate} disabled={!!busy} className="el-btn"
                style={{ background: "transparent", color: C.muted, border: `1px solid ${C.border3}`, borderRadius: R.control, padding: `${S[2]} ${S[3]}`, fontSize: T.base }}>
                {busy === "translate" ? "Translating…" : "Translate non-English reviews"}
              </button>
              <GhostButton onClick={() => setShowConnect((s) => !s)}>+ Connect source</GhostButton>
              <button onClick={() => setShowImport((s) => !s)} className="el-btn"
                style={{ background: "transparent", color: C.muted, border: `1px solid ${C.border3}`, borderRadius: R.control, padding: `${S[2]} ${S[3]}`, fontSize: T.base }}>
                Import CSV
              </button>
              {onAddProduct && isAdmin() && (
                <button onClick={onAddProduct} className="el-btn el-btn--primary"
                  style={{ borderRadius: R.control, padding: `${S[2]} ${S[3]}`, fontSize: T.base, fontWeight: 600 }}>
                  Add a product
                </button>
              )}
            </div>
          ) : undefined
        }
      />
      {resetTarget && admin && (
        <div className="el-overlay-scrim" onClick={() => !busy && setResetTarget(null)}
          style={{ position: "fixed", inset: 0, background: "var(--el-scrim)", zIndex: 60,
            display: "flex", alignItems: "center", justifyContent: "center", padding: S[5] }}>
          <div ref={resetDialog} className="el-overlay-panel" role="dialog" aria-modal="true"
            aria-labelledby="source-reset-title" aria-describedby="source-reset-description"
            onClick={(e) => e.stopPropagation()}
            style={{ width: "100%", maxWidth: 480, background: C.card, border: `1px solid ${C.border3}`,
              borderRadius: R.overlay, padding: `${S[5]} ${S[6]}`, boxShadow: "var(--el-e4)" }}>
            <h2 id="source-reset-title" style={{ margin: `0 0 ${S[3]}`, fontSize: T.lg }}>
              Re-sync from scratch?
            </h2>
            <div style={{ fontFamily: mono, fontSize: T.sm, color: C.text3, overflowWrap: "anywhere" }}>
              {resetTarget.identifier}
            </div>
            <p id="source-reset-description" style={{ fontSize: T.base, color: C.muted, lineHeight: "var(--el-lh-normal)" }}>
              This clears this source's collection watermark and replays its normal backfill.
              Existing feedback is kept. Previously collected items are deduplicated, so the replay adds no duplicates.
            </p>
            {busy && <div role="status" style={{ color: C.accent, fontSize: T.sm }}>Re-syncing this source…</div>}
            <div style={{ display: "flex", gap: S[2], justifyContent: "flex-end", marginTop: S[4] }}>
              <button onClick={() => setResetTarget(null)} disabled={!!busy} className="el-btn"
                style={{ background: "transparent", color: C.muted, border: `1px solid ${C.border3}`,
                  borderRadius: R.control, padding: `${S[2]} ${S[3]}`, fontSize: T.base }}>Cancel</button>
              <button onClick={resetSource} disabled={!!busy} className="el-btn el-btn--primary"
                style={{ borderRadius: R.control, padding: `${S[2]} ${S[3]}`, fontSize: T.base }}>
                {busy ? "Re-syncing…" : "Re-sync from scratch"}
              </button>
            </div>
          </div>
        </div>
      )}
      <div style={{ flex: 1, overflow: "auto", padding: `${S[5]} ${S[6]}` }}>
        {showConnect && reviewer && <ConnectForm onDone={() => { setShowConnect(false); reload(); }} />}
        {showImport && reviewer && <ImportForm onDone={(m) => { setShowImport(false); setMsg(m); reload(); }} />}
        {msg && (
          <div role="status" aria-live="polite" style={{ maxWidth: MEASURE, marginBottom: S[3], padding: `${S[2]} ${S[3]}`, border: `1px solid ${C.border3}`, borderRadius: R.control, background: C.card, color: C.text3, fontSize: T.base }}>
            {msg}
          </div>
        )}

        <div style={{ display: "flex", alignItems: "baseline", gap: S[3], marginBottom: S[3],
                      maxWidth: MEASURE }}>
          <Label>CONNECTED</Label>
          {data?.last_synced && data.last_synced.sources > 0 && (
            <span
              style={{ marginLeft: "auto", fontFamily: mono, fontSize: T.xs,
                       color: data.last_synced.stale ? C.accent : C.faint }}>
              {data.last_synced.last_synced_at
                ? <>Last synced <RelativeDate iso={data.last_synced.last_synced_at} /></>
                : "Not synced yet"}
            </span>
          )}
        </div>
        {data && data.connected.length === 0 && (
          <div style={{ maxWidth: MEASURE, padding: `${S[10]} ${S[6]}`, border: `1px dashed ${C.border4}`, borderRadius: R.card, textAlign: "center" }}>
            <div style={{ fontSize: T.md, fontWeight: 600, color: C.text3 }}>
              No sources connected for {data?.product || "this product"}
            </div>
            <div style={{ fontSize: T.base, color: C.dim, marginTop: S[1], lineHeight: "var(--el-lh-normal)" }}>
              EchoLens has nothing to read yet. Connect a Play Store app or a GitHub repo — or
              import a CSV of reviews you already have — and collection starts immediately.
            </div>
          </div>
        )}
        <div style={{ display: "flex", flexDirection: "column", gap: S[2], maxWidth: MEASURE }}>
          {data?.connected.map((s, i) => {
            const col = STATUS_COLOR[s.status] ?? C.muted;
            return (
              <div key={`${i}-${s.name}-${s.detail}`} className="el-ui-forms-source-card" style={{ display: "grid", gap: S[3], alignItems: "center", padding: `${S[4]} ${S[4]}`, background: C.card, border: `1px solid ${C.border2}`, borderRadius: R.card }}>
                <div style={{ display: "flex", alignItems: "center", gap: S[3], minWidth: 0 }}>
                  <div style={{ width: 30, height: 30, borderRadius: R.control, background: C.hover, border: `1px solid ${C.border3}`, display: "flex", alignItems: "center", justifyContent: "center", fontFamily: mono, fontSize: T.sm, color: C.accent, flex: "none" }}>
                    {s.icon}
                  </div>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: T.md, fontWeight: 600 }}>{s.name}</div>
                    <div style={{ fontFamily: mono, fontSize: T.micro, color: C.faint, marginTop: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.detail}</div>
                  </div>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: S[2] }}>
                  <div style={{ width: 7, height: 7, borderRadius: "50%", background: col, flex: "none" }} />
                  <span style={{ fontSize: T.sm, color: col }}>{s.status}</span>
                </div>
                <div title={s.why || undefined} style={{ minWidth: 0 }}>
                  <div style={{ fontSize: T.sm, color: s.error ? C.bad : s.stale ? C.accent : C.muted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {s.why ? <SourceActivity text={s.why} lastPull={s.lastPull} /> : s.lastSuccess
                      ? <>Last success <RelativeDate iso={s.lastSuccess} /></>
                      : <SourceActivity text={s.lastPull} />}
                  </div>
                  {s.why && s.lastSuccess && (
                    <div style={{ fontFamily: mono, fontSize: T.micro, color: C.faint, marginTop: 0 }}>
                      Last success <RelativeDate iso={s.lastSuccess} />
                    </div>
                  )}
                  {(s.stale || s.error) && reviewer && s.source && s.identifier && (
                    <button
                      onClick={(e) => { e.stopPropagation(); retry(s.source!, s.identifier!); }}
                      disabled={busy === `retry-${s.identifier}`}
                      className="el-btn"
                      style={{ marginTop: S[1], background: "transparent", color: C.accent, border: `1px solid ${C.accent}55`, borderRadius: R.control, padding: `${S[1]} ${S[2]}`, fontSize: T.xs }}>
                      {busy === `retry-${s.identifier}` ? "Retrying…" : "Retry now"}
                    </button>
                  )}
                  {admin && s.source && s.identifier && (
                    <button onClick={() => setResetTarget({ source: s.source!, identifier: s.identifier! })}
                      disabled={!!busy || s.status === "Syncing…"} className="el-btn"
                      style={{ marginTop: S[1], marginLeft: S[1], background: "transparent", color: C.muted,
                        border: `1px solid ${C.border3}`, borderRadius: R.control,
                        padding: `${S[1]} ${S[2]}`, fontSize: T.xs }}>
                      Re-sync from scratch
                    </button>
                  )}
                </div>
                <div style={{ fontFamily: mono, fontSize: T.xs, color: C.text3, textAlign: "right" }}>{s.volume}</div>
              </div>
            );
          })}
        </div>

        <Label style={{ margin: "28px 0 4px" }}>Not yet supported</Label>
        <p style={{ fontSize: T.sm, color: C.dim, margin: `0 0 ${S[3]}`, maxWidth: MEASURE }}>
          These can't be connected directly today. Import their data as a CSV instead.
        </p>
        <div style={{ display: "flex", gap: S[2], flexWrap: "wrap", maxWidth: MEASURE }}>
          {data?.available.map((a) => (
            <div key={a} style={{ display: "flex", alignItems: "center", gap: S[2], padding: `${S[2]} ${S[4]}`, border: `1px dashed ${C.border4}`, borderRadius: R.control, color: C.muted, fontSize: T.base }}>
              {a}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function RelativeDate({ iso }: { iso: string }) {
  const date = new Date(iso);
  const valid = Number.isFinite(date.getTime());
  return (
    <time dateTime={valid ? date.toISOString() : undefined}
      title={valid ? `${when(iso)} · ${date.toLocaleTimeString()} (${iso})` : undefined}>
      {relativeWhen(iso)}
    </time>
  );
}

function SourceActivity({ text, lastPull }: { text: string; lastPull?: string }) {
  // Collector error times are UTC; lastPull supplies the date of the same run.
  const day = lastPull?.match(/\d{4}-\d{2}-\d{2}/)?.[0];
  const activity = day
    ? text.replace(/^collector failed at (\d{2}:\d{2}):/, `Collector failed ${day}T$1:00Z:`)
    : text;
  return <>{activity.split(/(\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)?)/).map((part, i) =>
    /^\d{4}-\d{2}-\d{2}/.test(part) ? <RelativeDate key={i} iso={part} /> : part)}</>;
}

function ConnectForm({ onDone }: { onDone: () => void }) {
  const [source, setSource] = useState("play_store");
  const [identifier, setIdentifier] = useState("");
  const [product, setProduct] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Served from the collector registry so the form can never offer a source
  // that has no collector behind it.
  const { data: available } = useAsync(() => api.availableSources(), []);

  const options = available?.sources ?? [];
  const hint = options.find((o) => o.source === source)?.hint ?? "";

  const submit = async () => {
    if (!identifier.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await api.connectSource(source, identifier.trim(), product.trim() || undefined);
      onDone();
    } catch (e) {
      setError(String(e).replace("Error: ", ""));
    } finally {
      setBusy(false);
    }
  };

  const input: React.CSSProperties = { background: C.bgRaised, border: `1px solid ${C.border3}`, borderRadius: R.control, color: C.text, fontFamily: "inherit", fontSize: T.base, padding: `${S[2]} ${S[3]}` };

  return (
    <div style={{ maxWidth: MEASURE, marginBottom: S[4], padding: 18, background: C.card, border: `1px solid ${C.border2}`, borderRadius: R.card }}>
      <div style={{ fontSize: T.md, fontWeight: 600, marginBottom: S[3] }}>Connect a data source</div>
      <div className="el-ui-forms-source-fields">
        <label className="el-ui-forms-source-field">
          <span>Source type</span>
          <select value={source} onChange={(e) => setSource(e.target.value)} style={input}
            aria-label="Source type">
            {options.length === 0
              ? <option value="play_store">Play Store</option>
              : options.map((o) => (
                <option key={o.source} value={o.source}>{o.label}</option>
              ))}
          </select>
        </label>
        <label className="el-ui-forms-source-field">
          <span>Source identifier</span>
          <input value={identifier} onChange={(e) => setIdentifier(e.target.value)} placeholder={hint}
            aria-label="Source identifier" style={input} />
        </label>
        <label className="el-ui-forms-source-field">
          <span>Product name (optional)</span>
          <input value={product} onChange={(e) => setProduct(e.target.value)}
            aria-label="Product name (optional)" placeholder="product name (optional)"
            style={input} />
        </label>
        <button onClick={submit} disabled={!identifier.trim() || busy} className="el-btn el-btn--primary"
          style={{ borderRadius: R.control, padding: `${S[2]} ${S[4]}`, fontWeight: 600, fontSize: T.base, cursor: identifier.trim() ? "pointer" : "not-allowed", opacity: identifier.trim() ? 1 : 0.5 }}>
          {busy ? "…" : "Connect"}
        </button>
      </div>
      {error && <div style={{ color: C.bad, fontSize: T.sm, marginTop: S[2] }}>{error}</div>}
      <div style={{ fontSize: T.xs, color: C.faint, marginTop: S[2] }}>
        After connecting, click <span style={{ color: C.text3 }}>Collect now</span> to pull data, then <span style={{ color: C.text3 }}>Scan now</span> under Signals at the bottom of Cases.
      </div>
    </div>
  );
}

function ImportForm({ onDone }: { onDone: (msg: string) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [product, setProduct] = useState("");
  const [sourceLabel, setSourceLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.importReviews(file, product.trim() || undefined, sourceLabel.trim() || "CSV import");
      onDone(`Imported ${r.imported} reviews (${r.skipped} skipped) from ${file.name}. Run a scan under Signals in Cases to look for new problems.`);
    } catch (e) {
      setError(String(e).replace("Error: ", ""));
    } finally {
      setBusy(false);
    }
  };

  const input: React.CSSProperties = { background: C.bgRaised, border: `1px solid ${C.border3}`, borderRadius: R.control, color: C.text, fontFamily: "inherit", fontSize: T.base, padding: `${S[2]} ${S[3]}` };

  return (
    <div style={{ maxWidth: MEASURE, marginBottom: S[4], padding: 18, background: C.card, border: `1px solid ${C.border2}`, borderRadius: R.card }}>
      <div style={{ fontSize: T.md, fontWeight: 600, marginBottom: S[1] }}>Import reviews from a CSV or Excel file</div>
      <div style={{ fontSize: T.sm, color: C.muted, marginBottom: S[3], lineHeight: "var(--el-lh-normal)" }}>
        Any export works — App Store, Zendesk, in-app feedback, a spreadsheet. Columns are matched loosely:
        a <span style={{ fontFamily: mono, color: C.text3 }}>text</span> column (or content/review/body),
        plus optional <span style={{ fontFamily: mono, color: C.text3 }}>rating</span>,{" "}
        <span style={{ fontFamily: mono, color: C.text3 }}>date</span>, <span style={{ fontFamily: mono, color: C.text3 }}>version</span>.
      </div>
      <div className="el-ui-forms-source-fields">
        <label className="el-ui-forms-source-field">
          <span>CSV or Excel file</span>
          <input type="file"
            accept=".csv,.xlsx,.xlsm,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            aria-label="CSV or Excel file to import"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            style={{ ...input, padding: `${S[2]} ${S[2]}` }} />
        </label>
        <label className="el-ui-forms-source-field">
          <span>Product name (optional)</span>
          <input value={product} onChange={(e) => setProduct(e.target.value)}
            aria-label="Product name (optional)"
            placeholder="product name (optional)" style={input} />
        </label>
        <label className="el-ui-forms-source-field">
          <span>Source label (optional)</span>
          <input value={sourceLabel} onChange={(e) => setSourceLabel(e.target.value)} placeholder="e.g. App Store reviews"
            aria-label="Source label" style={input} />
        </label>
        <button onClick={submit} disabled={!file || busy} className="el-btn el-btn--primary"
          style={{ borderRadius: R.control, padding: `${S[2]} ${S[4]}`, fontWeight: 600, fontSize: T.base, cursor: file ? "pointer" : "not-allowed", opacity: file ? 1 : 0.5 }}>
          {busy ? "Importing…" : "Import"}
        </button>
      </div>
      {error && <div style={{ color: C.bad, fontSize: T.sm, marginTop: S[2] }}>{error}</div>}
    </div>
  );
}
