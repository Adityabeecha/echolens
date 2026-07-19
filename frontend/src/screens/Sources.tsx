import { useState } from "react";
import { api, canReview } from "../api";
import { useAsync } from "../hooks";
import { C, mono } from "../theme";
import { Centered, GhostButton, Label, ScreenHeader } from "../ui";

const STATUS_COLOR: Record<string, string> = {
  Healthy: C.good,
  "Rate-limited": C.accent,
  Disconnected: C.bad,
  Error: C.bad,
  Stale: C.accent,
  "Syncing…": C.accent,
  Idle: C.muted,
};

export function Sources({ onAddProduct }: { onAddProduct?: () => void }) {
  const { data, loading, error, reload } = useAsync(() => api.sources(), []);
  const [showConnect, setShowConnect] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const reviewer = canReview();

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

  if (loading) return <Centered>Loading sources…</Centered>;
  if (error) return <Centered>Backend unavailable.</Centered>;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <ScreenHeader
        title="Sources"
        right={
          reviewer ? (
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", justifyContent: "flex-end" }}>
              <button onClick={collect} disabled={!!busy} className="el-btn"
                style={{ background: "transparent", color: C.muted, border: `1px solid ${C.border3}`, borderRadius: 6, padding: "8px 14px", fontSize: 13, cursor: "pointer" }}>
                {busy === "collect" ? "Collecting…" : "Collect now"}
              </button>
              <GhostButton onClick={() => setShowConnect((s) => !s)}>+ Connect source</GhostButton>
              <button onClick={() => setShowImport((s) => !s)} className="el-btn"
                style={{ background: "transparent", color: C.muted, border: `1px solid ${C.border3}`, borderRadius: 6, padding: "8px 14px", fontSize: 13, cursor: "pointer" }}>
                ⇪ Import CSV
              </button>
              {onAddProduct && (
                <button onClick={onAddProduct} className="el-btn"
                  style={{ background: C.accent, color: C.onAccent, border: "none", borderRadius: 6, padding: "8px 14px", fontSize: 13, fontWeight: 600, cursor: "pointer" }}>
                  Add a product
                </button>
              )}
            </div>
          ) : undefined
        }
      />
      <div style={{ flex: 1, overflow: "auto", padding: "22px 28px" }}>
        {showConnect && reviewer && <ConnectForm onDone={() => { setShowConnect(false); reload(); }} />}
        {showImport && reviewer && <ImportForm onDone={(m) => { setShowImport(false); setMsg(m); reload(); }} />}
        {msg && (
          <div style={{ maxWidth: 880, marginBottom: 14, padding: "10px 14px", border: `1px solid ${C.border3}`, borderRadius: 8, background: C.card, color: C.text3, fontSize: 13 }}>
            {msg}
          </div>
        )}

        <Label style={{ marginBottom: 12 }}>CONNECTED</Label>
        {data && data.connected.length === 0 && (
          <div style={{ maxWidth: 880, padding: "40px 24px", border: `1px dashed ${C.border4}`, borderRadius: 12, textAlign: "center" }}>
            <div style={{ fontSize: 15, fontWeight: 600, color: C.text3 }}>No sources connected</div>
            <div style={{ fontSize: 13, color: C.dim, marginTop: 6 }}>
              Connect a Play Store app or a GitHub repo to start monitoring real feedback.
            </div>
          </div>
        )}
        <div style={{ display: "flex", flexDirection: "column", gap: 10, maxWidth: 880 }}>
          {data?.connected.map((s) => {
            const col = STATUS_COLOR[s.status] ?? C.muted;
            return (
              <div key={s.name + s.detail} style={{ display: "grid", gridTemplateColumns: "minmax(180px,1.2fr) 120px minmax(140px,1fr) 120px", gap: 14, alignItems: "center", padding: "15px 18px", background: C.card, border: `1px solid ${C.border2}`, borderRadius: 10 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 11, minWidth: 0 }}>
                  <div style={{ width: 30, height: 30, borderRadius: 7, background: C.hover, border: `1px solid ${C.border3}`, display: "flex", alignItems: "center", justifyContent: "center", fontFamily: mono, fontSize: 12, color: C.accent, flex: "none" }}>
                    {s.icon}
                  </div>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: 14, fontWeight: 600 }}>{s.name}</div>
                    <div style={{ fontFamily: mono, fontSize: 10, color: C.faint, marginTop: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.detail}</div>
                  </div>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                  <div style={{ width: 7, height: 7, borderRadius: "50%", background: col, flex: "none" }} />
                  <span style={{ fontSize: 12, color: col }}>{s.status}</span>
                </div>
                <div style={{ fontSize: 12, color: s.error ? C.bad : s.stale ? C.accent : C.muted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {s.error || (s.stale && s.staleSince ? `stale since ${s.staleSince}` : s.lastPull)}
                </div>
                <div style={{ fontFamily: mono, fontSize: 11.5, color: C.text3, textAlign: "right" }}>{s.volume}</div>
              </div>
            );
          })}
        </div>

        <Label style={{ margin: "28px 0 12px" }}>AVAILABLE SOON</Label>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", maxWidth: 880 }}>
          {data?.available.map((a) => (
            <div key={a} style={{ display: "flex", alignItems: "center", gap: 9, padding: "10px 16px", border: `1px dashed ${C.border4}`, borderRadius: 9, color: C.muted, fontSize: 13 }}>
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

  const input: React.CSSProperties = { background: C.bgRaised, border: `1px solid ${C.border3}`, borderRadius: 7, color: C.text, fontFamily: "inherit", fontSize: 13, padding: "9px 11px" };

  return (
    <div style={{ maxWidth: 880, marginBottom: 18, padding: 18, background: C.card, border: `1px solid ${C.border2}`, borderRadius: 12 }}>
      <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>Connect a data source</div>
      <div style={{ display: "grid", gridTemplateColumns: "150px 1fr 1fr auto", gap: 10, alignItems: "center" }}>
        <select value={source} onChange={(e) => setSource(e.target.value)} style={input}>
          <option value="play_store">Play Store</option>
          <option value="app_store">App Store</option>
          <option value="github">GitHub</option>
        </select>
        <input value={identifier} onChange={(e) => setIdentifier(e.target.value)} placeholder={hint} style={input} />
        <input value={product} onChange={(e) => setProduct(e.target.value)} placeholder="product name (optional)" style={input} />
        <button onClick={submit} disabled={!identifier.trim() || busy} className="el-btn"
          style={{ background: C.accent, color: C.onAccent, border: "none", borderRadius: 7, padding: "9px 16px", fontWeight: 600, fontSize: 13, cursor: identifier.trim() ? "pointer" : "not-allowed", opacity: identifier.trim() ? 1 : 0.5 }}>
          {busy ? "…" : "Connect"}
        </button>
      </div>
      {error && <div style={{ color: C.bad, fontSize: 12.5, marginTop: 10 }}>{error}</div>}
      <div style={{ fontSize: 11.5, color: C.faint, marginTop: 10 }}>
        After connecting, click <span style={{ color: C.text3 }}>Collect now</span> to pull data, then <span style={{ color: C.text3 }}>Scan now</span> on the Case Feed.
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
      onDone(`Imported ${r.imported} reviews (${r.skipped} skipped) from ${file.name}. Run a scan on the Case Feed.`);
    } catch (e) {
      setError(String(e).replace("Error: ", ""));
    } finally {
      setBusy(false);
    }
  };

  const input: React.CSSProperties = { background: C.bgRaised, border: `1px solid ${C.border3}`, borderRadius: 7, color: C.text, fontFamily: "inherit", fontSize: 13, padding: "9px 11px" };

  return (
    <div style={{ maxWidth: 880, marginBottom: 18, padding: 18, background: C.card, border: `1px solid ${C.border2}`, borderRadius: 12 }}>
      <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 6 }}>Import reviews from a CSV</div>
      <div style={{ fontSize: 12, color: C.muted, marginBottom: 12, lineHeight: 1.5 }}>
        Any export works — App Store, Zendesk, in-app feedback, a spreadsheet. Columns are matched loosely:
        a <span style={{ fontFamily: mono, color: C.text3 }}>text</span> column (or content/review/body),
        plus optional <span style={{ fontFamily: mono, color: C.text3 }}>rating</span>,{" "}
        <span style={{ fontFamily: mono, color: C.text3 }}>date</span>, <span style={{ fontFamily: mono, color: C.text3 }}>version</span>.
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr auto", gap: 10, alignItems: "center" }}>
        <input type="file" accept=".csv,text/csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          style={{ ...input, padding: "7px 9px" }} />
        <input value={product} onChange={(e) => setProduct(e.target.value)} placeholder="product name (optional)" style={input} />
        <input value={sourceLabel} onChange={(e) => setSourceLabel(e.target.value)} placeholder="source label (e.g. app_store)" style={input} />
        <button onClick={submit} disabled={!file || busy} className="el-btn"
          style={{ background: C.accent, color: C.onAccent, border: "none", borderRadius: 7, padding: "9px 16px", fontWeight: 600, fontSize: 13, cursor: file ? "pointer" : "not-allowed", opacity: file ? 1 : 0.5 }}>
          {busy ? "Importing…" : "Import"}
        </button>
      </div>
      {error && <div style={{ color: C.bad, fontSize: 12.5, marginTop: 10 }}>{error}</div>}
    </div>
  );
}
