import { useState } from "react";
import { api, canReview } from "../api";
import { useAsync } from "../hooks";
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

export function Sources({ onAddProduct, productName }: {
  onAddProduct?: () => void; productName: string | null;
}) {
  const { data, loading, error, reload } = useAsync(() => api.sources(), []);
  const [showConnect, setShowConnect] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const reviewer = canReview();

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
      setMsg(`Collected ${got} new items across ${r.results.length} source(s).`);
      reload();
    } catch (e) {
      setMsg(String(e).replace("Error: ", ""));
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
              <GhostButton onClick={() => setShowConnect((s) => !s)}>+ Connect source</GhostButton>
              <button onClick={() => setShowImport((s) => !s)} className="el-btn"
                style={{ background: "transparent", color: C.muted, border: `1px solid ${C.border3}`, borderRadius: R.control, padding: `${S[2]} ${S[3]}`, fontSize: T.base }}>
                Import CSV
              </button>
              {onAddProduct && (
                <button onClick={onAddProduct} className="el-btn el-btn--primary"
                  style={{ borderRadius: R.control, padding: `${S[2]} ${S[3]}`, fontSize: T.base, fontWeight: 600 }}>
                  Add a product
                </button>
              )}
            </div>
          ) : undefined
        }
      />
      <div style={{ flex: 1, overflow: "auto", padding: `${S[5]} ${S[6]}` }}>
        {showConnect && reviewer && <ConnectForm onDone={() => { setShowConnect(false); reload(); }} />}
        {showImport && reviewer && <ImportForm onDone={(m) => { setShowImport(false); setMsg(m); reload(); }} />}
        {msg && (
          <div style={{ maxWidth: MEASURE, marginBottom: S[3], padding: `${S[2]} ${S[3]}`, border: `1px solid ${C.border3}`, borderRadius: R.control, background: C.card, color: C.text3, fontSize: T.base }}>
            {msg}
          </div>
        )}

        <Label style={{ marginBottom: S[3] }}>CONNECTED</Label>
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
              <div key={`${i}-${s.name}-${s.detail}`} style={{ display: "grid", gridTemplateColumns: "minmax(180px,1.2fr) 120px minmax(140px,1fr) 120px", gap: S[3], alignItems: "center", padding: `${S[4]} ${S[4]}`, background: C.card, border: `1px solid ${C.border2}`, borderRadius: R.card }}>
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
                    {s.why || s.lastPull}
                  </div>
                  {s.lastSuccess && (
                    <div style={{ fontFamily: mono, fontSize: T.micro, color: C.faint, marginTop: 0 }}>
                      last success {new Date(s.lastSuccess).toLocaleString()}
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
                </div>
                <div style={{ fontFamily: mono, fontSize: T.xs, color: C.text3, textAlign: "right" }}>{s.volume}</div>
              </div>
            );
          })}
        </div>

        <Label style={{ margin: "28px 0 12px" }}>AVAILABLE SOON</Label>
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

function ConnectForm({ onDone }: { onDone: () => void }) {
  const [source, setSource] = useState("play_store");
  const [identifier, setIdentifier] = useState("");
  const [product, setProduct] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const hint =
    source === "play_store" ? "package name, e.g. com.spotify.music"
      : source === "app_store" ? "numeric App Store id, e.g. 324684580"
        : "owner/repo, e.g. signalapp/Signal-Android";

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
      <div style={{ display: "grid", gridTemplateColumns: "150px 1fr 1fr auto", gap: S[2], alignItems: "center" }}>
        <select value={source} onChange={(e) => setSource(e.target.value)} style={input}
          aria-label="Source type">
          <option value="play_store">Play Store</option>
          <option value="app_store">App Store</option>
          <option value="github">GitHub</option>
        </select>
        <input value={identifier} onChange={(e) => setIdentifier(e.target.value)} placeholder={hint}
          aria-label="Source identifier" style={input} />
        <input value={product} onChange={(e) => setProduct(e.target.value)} placeholder="product name (optional)"
          aria-label="Product name" style={input} />
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
  const [sourceLabel, setSourceLabel] = useState("csv");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.importReviews(file, product.trim() || undefined, sourceLabel);
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
      <div style={{ fontSize: T.md, fontWeight: 600, marginBottom: S[1] }}>Import reviews from a CSV</div>
      <div style={{ fontSize: T.sm, color: C.muted, marginBottom: S[3], lineHeight: "var(--el-lh-normal)" }}>
        Any export works — App Store, Zendesk, in-app feedback, a spreadsheet. Columns are matched loosely:
        a <span style={{ fontFamily: mono, color: C.text3 }}>text</span> column (or content/review/body),
        plus optional <span style={{ fontFamily: mono, color: C.text3 }}>rating</span>,{" "}
        <span style={{ fontFamily: mono, color: C.text3 }}>date</span>, <span style={{ fontFamily: mono, color: C.text3 }}>version</span>.
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr auto", gap: S[2], alignItems: "center" }}>
        <input type="file" accept=".csv,text/csv" aria-label="CSV file to import"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          style={{ ...input, padding: `${S[2]} ${S[2]}` }} />
        <input value={product} onChange={(e) => setProduct(e.target.value)} placeholder="product name (optional)" style={input} />
        <input value={sourceLabel} onChange={(e) => setSourceLabel(e.target.value)} placeholder="source label (e.g. app_store)"
          aria-label="Source label" style={input} />
        <button onClick={submit} disabled={!file || busy} className="el-btn el-btn--primary"
          style={{ borderRadius: R.control, padding: `${S[2]} ${S[4]}`, fontWeight: 600, fontSize: T.base, cursor: file ? "pointer" : "not-allowed", opacity: file ? 1 : 0.5 }}>
          {busy ? "Importing…" : "Import"}
        </button>
      </div>
      {error && <div style={{ color: C.bad, fontSize: T.sm, marginTop: S[2] }}>{error}</div>}
    </div>
  );
}
