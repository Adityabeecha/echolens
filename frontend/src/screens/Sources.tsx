import { useState } from "react";
import { api, canReview, isAdmin } from "../api";
import { count, duration, plural, relativeWhen, when } from "../format";
import { useAsync, useDialog } from "../hooks";
import { Button, Centered, ErrorState } from "../ui";
import { SerifHeadline } from "../components/casefile";
import { ImportPanel } from "./sources/ImportPanel";
import "./settings/ps.css";

/** The collector's status, as one of four plain states. */
type State = "healthy" | "late" | "broken" | "reading" | "waiting";
function stateOf(status: string): State {
  if (status === "Healthy") return "healthy";
  if (status === "Error" || status === "Disconnected") return "broken";
  if (status === "Syncing…") return "reading";
  if (status === "Stale" || status === "Rate-limited") return "late";
  return "waiting";
}
const STATE_WORDS: Record<State, string> = {
  healthy: "Healthy", late: "Late", broken: "Broken", reading: "Reading now", waiting: "Not read yet",
};

/**
 * Sources: one row per connected source — healthy, late or broken, when it was
 * last read and how much — with "Read now" and "Start over". Tools EchoLens
 * can't read directly are listed honestly, with the file import as the way in.
 */
export function Sources({ onAddProduct, productName, openImport = false }: {
  onAddProduct?: () => void; productName: string | null;
  /** Arrive with the import panel open (the header's "Import CSV"). */
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
      setMsg(r.error ? `Starting over didn't work: ${r.error}` :
        `Started ${identifier} over: ${count(r.inserted)} new ${plural(r.inserted, "item")}, ${count(r.skipped_duplicate)} ${plural(r.skipped_duplicate, "duplicate")} skipped from ${count(r.fetched)} fetched in ${duration(r.duration_seconds)}.`);
      reload();
    } catch (e) {
      setMsg(String(e).replace("Error: ", ""));
    } finally {
      setBusy(null);
      setResetTarget(null);
    }
  };

  const readNow = async (source: string, identifier: string) => {
    setBusy(`read-${source}-${identifier}`);
    setMsg(null);
    try {
      const r = await api.collectorsRetry(source, identifier);
      setMsg(r.error ? `Reading ${identifier} didn't work: ${r.error}` : `Read ${identifier} — ${count(r.inserted)} new ${plural(r.inserted, "item")}.`);
      reload();
    } catch (e) {
      setMsg(String(e).replace("Error: ", ""));
    } finally {
      setBusy(null);
    }
  };

  const readAll = async () => {
    setBusy("collect");
    setMsg(null);
    try {
      const r = await api.collectorsRun();
      const got = r.results.reduce((n, x) => n + x.inserted, 0);
      const failed = r.results.filter((x) => x.error).length;
      setMsg(`Read ${count(got)} new ${plural(got, "item")} across ${r.results.length} ${plural(r.results.length, "source")} in ${r.duration_seconds.toFixed(1)}s${
        failed ? ` — ${failed} ${plural(failed, "source needs", "sources need")} a look.` : "."}`);
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
      setMsg(`Translated ${count(r.translated)} ${plural(r.translated, "review")}, ${count(r.pending)} still to do${
        r.stopped ? ` — stopped: ${r.stopped}` : ""}.${r.note ? ` ${r.note}` : ""}`);
      reload();
    } catch (e) {
      setMsg(`Couldn't translate reviews: ${String(e).replace("Error: ", "")}`);
    } finally {
      setBusy(null);
    }
  };

  if (loading && !data) return <Centered>Loading sources…</Centered>;
  if (error && !data) {
    return <div style={{ padding: 28 }}><ErrorState title="Couldn't load your sources" onRetry={reload} /></div>;
  }

  const connected = data?.connected ?? [];
  const states = connected.map((s) => stateOf(s.status));
  const needLook = states.filter((s) => s === "broken" || s === "late").length;
  const answer = connected.length === 0 ? "Nothing connected yet."
    : needLook === 0 ? `${connected.length === 1 ? "Your source is" : `All ${connected.length} sources are`} reading normally.`
    : `${needLook} of ${connected.length} ${plural(connected.length, "source")} ${needLook === 1 ? "needs" : "need"} a look.`;

  return (
    <div className="ps-screen">
      {resetTarget && admin && (
        <div className="el-overlay-scrim" onClick={() => !busy && setResetTarget(null)}
          style={{ position: "fixed", inset: 0, background: "var(--el-scrim)", zIndex: 60,
            display: "flex", alignItems: "center", justifyContent: "center", padding: 20 }}>
          <div ref={resetDialog} className="el-overlay-panel" role="dialog" aria-modal="true"
            aria-labelledby="source-reset-title" aria-describedby="source-reset-description"
            onClick={(e) => e.stopPropagation()}
            style={{ width: "100%", maxWidth: 480, background: "var(--el-paper)", border: "1px solid var(--el-line)",
              borderRadius: 24, padding: 28, boxShadow: "var(--el-e4)", color: "var(--el-ink)" }}>
            <h2 id="source-reset-title" className="ps-h2" style={{ fontSize: 26, marginBottom: 12 }}>
              Start this source over?
            </h2>
            <div style={{ fontFamily: "var(--el-mono)", fontSize: 13, color: "var(--el-muted)", overflowWrap: "anywhere" }}>
              {resetTarget.identifier}
            </div>
            <p id="source-reset-description" className="ps-note">
              EchoLens forgets where it stopped reading (the collection watermark) and reads again with the normal backfill.
              Existing feedback is kept. Anything it has already read is recognised as a duplicate, so nothing is counted twice.
            </p>
            {busy && <div role="status" className="ps-banner">Re-syncing this source…</div>}
            <div className="ps-row" style={{ justifyContent: "flex-end", marginTop: 16 }}>
              <button type="button" onClick={() => setResetTarget(null)} disabled={!!busy} className="el-btn el-btn--ghost">Cancel</button>
              <button type="button" onClick={resetSource} disabled={!!busy} className="el-btn el-btn--primary">
                {busy ? "Re-syncing…" : "Start over"}
              </button>
            </div>
          </div>
        </div>
      )}

      <main className="ps-main">
        <header className="ps-head">
          <div className="ps-head__meta">
            <span>{productName ?? data?.product ?? "This product"}
              {data?.last_synced && data.last_synced.sources > 0 && (
                <> · {data.last_synced.last_synced_at ? <>last read <RelativeDate iso={data.last_synced.last_synced_at} /></> : "not read yet"}</>
              )}</span>
            <span className="ps-spacer" />
            {reviewer && (
              <>
                <Button variant="ghost" size="sm" loading={busy === "collect"} disabled={!!busy} onClick={readAll}>Read every source now</Button>
                <Button variant="ghost" size="sm" loading={busy === "translate"} disabled={!!busy} onClick={translate}
                  title="Adds English beside reviews written in other languages">Translate other languages</Button>
              </>
            )}
            {onAddProduct && admin && <Button variant="ghost" size="sm" icon="plus" onClick={onAddProduct}>Add a product</Button>}
          </div>
          <SerifHeadline as="h1" size="page">{answer}</SerifHeadline>
        </header>

        {msg && <div role="status" aria-live="polite" className="ps-banner">{msg}</div>}

        <section className="ps-section" aria-labelledby="ps-connected">
          <div className="ps-row" style={{ justifyContent: "space-between" }}>
            <h2 id="ps-connected" className="ps-h2">Connected</h2>
            {reviewer && (
              <div className="ps-row">
                <Button variant="primary" size="sm" aria-expanded={showConnect} onClick={() => setShowConnect((s) => !s)}>
                  Connect a source</Button>
                <Button variant="ghost" size="sm" aria-expanded={showImport} onClick={() => setShowImport((s) => !s)}>
                  Import a file</Button>
              </div>
            )}
          </div>
          {showConnect && reviewer && <ConnectForm onDone={() => { setShowConnect(false); reload(); }} />}
          {showImport && reviewer && (
            <ImportPanel onCancel={() => setShowImport(false)} onDone={(m) => { setShowImport(false); setMsg(m); reload(); }} />
          )}
          {connected.length === 0 ? (
            <div className="ps-panel">
              <p className="ps-note">EchoLens has nothing to read for {data?.product || "this product"} yet. Connect a store
                listing or a GitHub repo — or import a file of reviews you already have — and reading starts at once.</p>
            </div>
          ) : (
            <div className="ps-sources">
              {connected.map((s, i) => {
                const st = states[i];
                const key = `${s.source}-${s.identifier}`;
                const real = !!(s.source && s.identifier);
                return (
                  <div key={`${i}-${s.name}-${s.detail}`} className="ps-source">
                    <div className="ps-source__name">
                      <strong>{s.name}</strong>
                      <span title={s.detail}>{s.detail}</span>
                    </div>
                    <span className={`ps-state is-${st === "waiting" ? "late" : st}`}>
                      <i className="ps-dot" aria-hidden />{STATE_WORDS[st]}
                    </span>
                    <div className="ps-source__when" title={s.why || undefined}>
                      <span>{s.lastSuccess ? <>Read <RelativeDate iso={s.lastSuccess} /></> : <SourceActivity text={s.lastPull} />} · {s.volume}</span>
                      {s.why && <span><SourceActivity text={s.why} lastPull={s.lastPull} /></span>}
                    </div>
                    <div className="ps-source__actions">
                      {reviewer && real && (
                        <button type="button" onClick={() => readNow(s.source!, s.identifier!)}
                          disabled={!!busy || st === "reading"}>
                          {busy === `read-${key}` ? "Reading…" : "Read now"}
                        </button>
                      )}
                      {admin && real && (
                        <button type="button" onClick={() => setResetTarget({ source: s.source!, identifier: s.identifier! })}
                          disabled={!!busy || s.status === "Syncing…"}
                          title="Read this source again from the start; nothing is counted twice">
                          Start over
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        <section className="ps-section" aria-labelledby="ps-unsupported">
          <h2 id="ps-unsupported" className="ps-h2">Not supported yet</h2>
          <p className="ps-note">EchoLens can't read these directly. Export them and import the tickets as a CSV — use
            “Import a file” above.</p>
          <div className="ps-unsupported">
            {(data?.available ?? []).map((a) => (
              <div key={a}><b>{a}</b>Not supported yet — import tickets as a CSV</div>
            ))}
          </div>
        </section>
      </main>
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
    ? text.replace(/^collector failed at (\d{2}:\d{2}):/, `Reading failed ${day}T$1:00Z:`)
    : text.replace(/^pulled /, "read ");
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

  return (
    <div className="ps-panel" role="region" aria-label="Connect a source">
      <div className="ps-row" style={{ alignItems: "flex-end" }}>
        <label className="ps-field" style={{ flex: "1 1 180px" }}>
          <span>What to read</span>
          <select className="ps-select" value={source} onChange={(e) => setSource(e.target.value)} aria-label="Source type">
            {options.length === 0 ? <option value="play_store">Google Play</option>
              : options.map((o) => <option key={o.source} value={o.source}>{o.label}</option>)}
          </select>
        </label>
        <label className="ps-field" style={{ flex: "2 1 240px" }}>
          <span>Which one</span>
          <input className="ps-input" value={identifier} onChange={(e) => setIdentifier(e.target.value)} placeholder={hint}
            aria-label="Source identifier" />
        </label>
        <label className="ps-field" style={{ flex: "1 1 180px" }}>
          <span>Product name (optional)</span>
          <input className="ps-input" value={product} onChange={(e) => setProduct(e.target.value)} aria-label="Product name (optional)" />
        </label>
        <Button variant="primary" loading={busy} disabled={!identifier.trim()} onClick={submit}>Connect</Button>
      </div>
      {error && <div role="alert" className="ps-banner">{error}</div>}
      <span className="ps-muted">After connecting, use “Read now” to pull its feedback.</span>
    </div>
  );
}
