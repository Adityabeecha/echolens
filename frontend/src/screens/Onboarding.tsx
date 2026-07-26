import { useEffect, useRef, useState } from "react";
import { OnboardStatus, Snapshot, api } from "../api";
import { plural } from "../format";
import { C, MEASURE, R, S, T, mono, sans } from "../theme";
import { Dot, Label } from "../ui";
import { Icon } from "../components/Icon";

interface Props {
  onDone: () => void; // land on Today for the new product
  /** Hand off to Cases → Signals, where triage actually happens. */
  onReviewSignals: () => void;
  canSkip: boolean; // first run has nothing to skip to; later, "cancel" is allowed
  onCancel: () => void;
  /** Called the moment the product exists, so it becomes the active scope
   *  immediately. Without this, anything started from this wizard was filed
   *  against the PREVIOUS product. */
  onProductCreated: (id: number, name: string) => void;
}

// The first-run wizard: two inputs → hands-off backfill → live health snapshot →
// a populated feed. The wait is never blank: the snapshot fills in as data lands.
export function Onboarding({ onDone, onReviewSignals, canSkip, onCancel, onProductCreated }: Props) {
  const [phase, setPhase] = useState<"form" | "running">("form");
  const [product, setProduct] = useState("");

  return (
    <div style={{ height: "100%", overflow: "auto", background: C.bg }}>
      <div style={{ maxWidth: MEASURE, margin: "0 auto", padding: `${S[12]} ${S[6]} ${S[12]}` }}>
        <div style={{ display: "flex", alignItems: "center", gap: S[3], marginBottom: S[1] }}>
          <Logo />
          <div style={{ fontFamily: mono, fontSize: T.micro, letterSpacing: ".14em", color: C.faint }}>
            ADD YOUR PRODUCT
          </div>
        </div>
        <h1 style={{ fontSize: T.display, fontWeight: 700, letterSpacing: "-.02em", margin: "10px 0 8px" }}>
          {phase === "form" ? "Point EchoLens at your app" : `Setting up ${product}`}
        </h1>
        <p style={{ fontSize: T.md, color: C.muted, lineHeight: "var(--el-lh-normal)", margin: "0 0 28px", maxWidth: 620 }}>
          {phase === "form"
            ? "Give it a Play Store package and (optionally) a GitHub repo. EchoLens backfills 90 days of reviews, issues and releases, builds a baseline, and surfaces what needs your attention — hands-off from here."
            : "Backfilling your feedback. Here's what we've found so far — no need to wait for it to finish."}
        </p>

        {phase === "form" ? (
          <OnboardForm
            onStarted={(p, id) => {
              // Switch scope FIRST: everything started from here belongs to the
              // product being onboarded, not the one that happened to be active.
              onProductCreated(id, p);
              setProduct(p);
              setPhase("running");
            }}
            canSkip={canSkip}
            onCancel={onCancel}
          />
        ) : (
          <Backfilling product={product} onDone={onDone} onReviewSignals={onReviewSignals} />
        )}
      </div>
    </div>
  );
}

function Logo() {
  return (
    <div style={{ width: 24, height: 24, borderRadius: "50%", border: `2px solid ${C.accent}`, position: "relative", flex: "none" }}>
      <div style={{ position: "absolute", inset: 4, borderRadius: "50%", background: `radial-gradient(circle at 35% 35%, ${C.accentHi}, ${C.accentDeep})` }} />
    </div>
  );
}

// ── step 1: the two inputs ──────────────────────────────────────────────

function OnboardForm({ onStarted, canSkip, onCancel }: { onStarted: (product: string, productId: number) => void; canSkip: boolean; onCancel: () => void }) {
  const [pkg, setPkg] = useState("");
  const [repo, setRepo] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!pkg.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.onboard({ play_store: pkg.trim(), github: repo.trim() || undefined, product: name.trim() || undefined });
      onStarted(r.product, r.product_id);
    } catch (e) {
      setError(String(e).replace("Error: ", ""));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: S[4] }}>
      <Field label="Play Store package" hint="Required — copy it from the store URL (id=…)">
        <input autoFocus value={pkg} onChange={(e) => setPkg(e.target.value)} placeholder="com.spotify.music"
          onKeyDown={(e) => e.key === "Enter" && submit()} style={inputStyle} />
      </Field>
      <Field label="GitHub repo" hint="Optional — issues and releases sharpen the investigation">
        <input value={repo} onChange={(e) => setRepo(e.target.value)} placeholder="signalapp/Signal-Android"
          onKeyDown={(e) => e.key === "Enter" && submit()} style={inputStyle} />
      </Field>
      <Field label="Display name" hint="Optional — defaults to the package name">
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Spotify"
          onKeyDown={(e) => e.key === "Enter" && submit()} style={inputStyle} />
      </Field>

      {error && (
        <div style={{ padding: `${S[2]} ${S[3]}`, border: `1px solid ${C.bad}55`, background: `${C.bad}14`, borderRadius: R.control, color: C.bad, fontSize: T.base }}>
          {error}
        </div>
      )}

      <div style={{ display: "flex", alignItems: "center", gap: S[3], marginTop: S[1] }}>
        <button onClick={submit} disabled={!pkg.trim() || busy} className="el-btn el-btn--primary"
          style={{ borderRadius: R.control, padding: `${S[3]} ${S[6]}`, fontWeight: 600, fontSize: T.md, fontFamily: sans, cursor: pkg.trim() && !busy ? "pointer" : "not-allowed", opacity: pkg.trim() && !busy ? 1 : 0.5 }}>
          {busy ? "Starting backfill…" : "Start backfill"}
        </button>
        {canSkip && (
          <button onClick={onCancel} className="el-btn"
            style={{ background: "transparent", color: C.muted, border: "none", fontSize: T.base }}>
            Cancel
          </button>
        )}
        <span style={{ fontSize: T.sm, color: C.faint }}>You need admin access to connect a product.</span>
      </div>
    </div>
  );
}

function Field({ label, hint, children }: { label: string; hint: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={{ display: "flex", alignItems: "baseline", gap: S[2], marginBottom: S[2] }}>
        <span style={{ fontSize: T.base, fontWeight: 600, color: C.text2 }}>{label}</span>
        <span style={{ fontSize: T.sm, color: C.faint }}>{hint}</span>
      </div>
      {children}
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  width: "100%",
  background: C.bgRaised,
  border: `1px solid ${C.border3}`,
  borderRadius: R.control,
  color: C.text,
  fontFamily: mono,
  fontSize: T.md,
  padding: `${S[3]} ${S[3]}`
};

// ── step 2: live backfill + snapshot ────────────────────────────────────

function Backfilling({ product, onDone, onReviewSignals }: {
  product: string; onDone: () => void; onReviewSignals: () => void;
}) {
  const [status, setStatus] = useState<OnboardStatus | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    let alive = true;
    let failures = 0;
    const poll = async () => {
      try {
        const s = await api.onboardStatus(product);
        if (!alive) return;
        setStatus(s);
        setErr(null);
        if (!s.backfilling && timer.current) {
          window.clearInterval(timer.current);
          timer.current = null;
        }
      } catch (e) {
        if (!alive) return;
        setErr(String(e).replace("Error: ", ""));
        // Stop after repeated failures instead of polling a dead backend
        // forever behind a frozen snapshot that still looks like progress.
        failures += 1;
        if (failures >= 5 && timer.current) {
          window.clearInterval(timer.current);
          timer.current = null;
        }
      }
    };
    poll();
    timer.current = window.setInterval(poll, 2500);
    return () => {
      alive = false;
      if (timer.current) window.clearInterval(timer.current);
    };
  }, [product]);

  if (err && !status) return <div style={{ color: C.bad, fontSize: T.base }}>{err}</div>;
  if (!status) return <div style={{ color: C.dim, fontSize: T.md }}>Connecting…</div>;

  const snap = status.snapshot;
  const anomalies = status.anomalies.filter((a) => a.status === "pending");
  const ready = snap.reviews > 0;
  const found = anomalies.length + snap.top_themes.length;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: S[5] }}>
      {err && status && (
        <div style={{ padding: `${S[2]} ${S[3]}`, border: `1px solid ${C.bad}55`,
                      background: `${C.bad}12`, borderRadius: R.control, color: C.text3,
                      fontSize: T.sm, lineHeight: "var(--el-lh-normal)" }}>
          <Icon name="warning" size={14} style={{ display: "inline", verticalAlign: "-2px" }} /> Lost contact while backfilling — {err}. The snapshot below may be
          out of date.
        </div>
      )}
      {/* source health */}
      <div style={{ display: "flex", flexDirection: "column", gap: S[2] }}>
        {status.sources.map((s) => {
          const color = s.status === "error" ? C.bad : s.status === "healthy" ? C.good : C.accent;
          const label =
            s.status === "error" ? (s.last_error || "failed") :
            s.status === "healthy" ? `${s.items_last_run.toLocaleString()} items pulled` :
            s.never_collected ? "backfilling…" : "syncing…";
          return (
            <div key={s.source + s.identifier} style={{ display: "flex", alignItems: "center", gap: S[3], padding: `${S[3]} ${S[4]}`, background: C.card, border: `1px solid ${C.border2}`, borderRadius: R.card }}>
              <Dot color={color} pulse={status.backfilling && s.status !== "error" && s.status !== "healthy"} />
              <span style={{ fontSize: T.base, fontWeight: 500 }}>{s.source === "play_store" ? "Play Store" : "GitHub"}</span>
              <span style={{ fontFamily: mono, fontSize: T.xs, color: C.faint }}>{s.identifier}</span>
              <div style={{ flex: 1 }} />
              <span style={{ fontSize: T.sm, color: s.status === "error" ? C.bad : C.muted }}>{label}</span>
            </div>
          );
        })}
      </div>

      {ready ? (
        <SnapshotView snap={snap} />
      ) : (
        <div style={{ padding: `${S[6]} ${S[5]}`, border: `1px dashed ${C.border4}`, borderRadius: R.card, textAlign: "center", color: C.dim, fontSize: T.base }}>
          {status.backfilling ? "Pulling your first reviews…" : "No reviews came back yet. Check the package name is exactly as it appears in the Play Store URL."}
        </div>
      )}

      {/* What we found — a summary and a handoff, not a third place to triage.
          This list used to be its own format, so the same themes appeared here,
          on the feed, and nowhere else the same way. Triage happens in one
          place: Cases → Signals. */}
      {ready && found > 0 && (
        <div style={{ padding: `${S[4]} ${S[5]}`, background: C.card, border: `1px solid ${C.border2}`,
                      borderRadius: R.card }}>
          <Label style={{ marginBottom: S[1], color: C.info }}>WHAT WE FOUND</Label>
          <div style={{ fontSize: T.md, color: C.text2, lineHeight: "var(--el-lh-normal)" }}>
            {found} {plural(found, "signal")} worth a look in {product}'s feedback
            {anomalies.length > 0 && snap.top_themes.length > 0
              ? ` — ${anomalies.length} detected ${plural(anomalies.length, "spike")} and ${snap.top_themes.length} recurring ${plural(snap.top_themes.length, "complaint")}.`
              : "."}
          </div>
          <div style={{ fontSize: T.sm, color: C.dim, marginTop: S[2], lineHeight: "var(--el-lh-normal)" }}>
            They're waiting under Signals at the bottom of Cases. Tick the ones worth
            investigating and they queue together — nothing is lost by not choosing now.
          </div>
        </div>
      )}

      {/* data-quality disclosures */}
      {(snap.data_quality.note || snap.data_quality.non_english_note) && (
        <div style={{ display: "flex", flexDirection: "column", gap: S[2] }}>
          {snap.data_quality.note && <Notice text={snap.data_quality.note} />}
          {snap.data_quality.non_english_note && <Notice text={snap.data_quality.non_english_note} />}
        </div>
      )}

      {/* CTA */}
      <div style={{ display: "flex", alignItems: "center", gap: S[3], marginTop: S[1],
                    flexWrap: "wrap" }}>
        <button onClick={onDone} disabled={!ready} className="el-btn"
          style={{ background: ready ? C.accent : C.hover, color: ready ? C.onAccent : C.dim,
                   border: "none", borderRadius: R.control, padding: `${S[3]} ${S[6]}`, fontWeight: 600,
                   fontSize: T.md, cursor: ready ? "pointer" : "not-allowed" }}>
          Go to Today
        </button>
        {ready && found > 0 && (
          <button onClick={onReviewSignals} className="el-btn"
            style={{ background: "transparent", color: C.accent,
                     border: `1px solid rgba(240,166,60,.4)`, borderRadius: R.control, padding: `${S[3]} ${S[5]}`,
                     fontWeight: 500, fontSize: T.md, fontFamily: sans }}>
            Review {found} {plural(found, "signal")} in Cases
          </button>
        )}
        {status.backfilling && (
          <span style={{ fontSize: T.sm, color: C.faint }}>
            Still backfilling — Today keeps filling in.
          </span>
        )}
      </div>
    </div>
  );
}

function SnapshotView({ snap }: { snap: Snapshot }) {
  const delta = snap.rating_delta;
  const deltaColor = delta == null ? C.muted : delta >= 0 ? C.good : C.bad;
  const deltaArrow = delta == null ? null : delta >= 0 ? "arrowUp" : "arrowDown";
  const max = Math.max(1, ...snap.weekly.map((w) => w.count));

  const tiles = [
    { label: "REVIEWS (90D)", value: snap.reviews.toLocaleString(), color: C.text },
    {
      label: "RATING NOW",
      value: snap.rating_now != null ? `${snap.rating_now.toFixed(1)}★` : "—",
      color: C.text,
      sub: delta != null ? (
        <>
          {deltaArrow && <Icon name={deltaArrow} size={10} style={{ display: "inline" }} />}
          {" "}{Math.abs(delta).toFixed(2)} vs last wk
        </>
      ) : undefined,
      subColor: deltaColor
    },
    { label: "REVIEWS / DAY", value: String(snap.avg_per_day), color: C.text },
    { label: "NEGATIVE", value: snap.negatives.toLocaleString(), color: C.accent },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: S[4] }}>
      <div style={{ display: "flex", gap: S[2], flexWrap: "wrap" }}>
        {tiles.map((t) => (
          <div key={t.label} style={{ flex: 1, minWidth: 130, padding: `${S[3]} ${S[4]}`, background: C.card, border: `1px solid ${C.border2}`, borderRadius: R.card }}>
            <div style={{ fontFamily: mono, fontSize: T.micro, letterSpacing: ".1em", color: C.faint }}>{t.label}</div>
            <div style={{ fontSize: T.xl, fontWeight: 700, fontFamily: mono, color: t.color, marginTop: S[2] }}>{t.value}</div>
            {t.sub && <div style={{ fontFamily: mono, fontSize: T.micro, color: t.subColor, marginTop: S[1] }}>{t.sub}</div>}
          </div>
        ))}
      </div>

      {/* weekly volume bars */}
      <div style={{ padding: `${S[4]} ${S[4]}`, background: C.card, border: `1px solid ${C.border2}`, borderRadius: R.card }}>
        <Label style={{ marginBottom: S[3] }}>REVIEW VOLUME · LAST 12 WEEKS</Label>
        <div style={{ display: "flex", alignItems: "flex-end", gap: S[1], height: 56 }}>
          {snap.weekly.map((w) => (
            <div key={w.week_start} title={`${w.week_start}: ${w.count}`}
              style={{ flex: 1, height: `${Math.max(4, (w.count / max) * 100)}%`, borderRadius: "3px 3px 0 0", background: `linear-gradient(180deg,${C.accent},${C.accentDeep})`, opacity: 0.9 }} />
          ))}
        </div>
      </div>
    </div>
  );
}

function Notice({ text }: { text: string }) {
  return (
    <div style={{ display: "flex", gap: S[2], padding: `${S[2]} ${S[3]}`, border: `1px solid ${C.border3}`, background: C.card2, borderRadius: R.control, color: C.muted, fontSize: T.sm, lineHeight: "var(--el-lh-normal)" }}>
      <Icon name="info" size={14} style={{ color: C.info, flex: "none" }} />
      {text}
    </div>
  );
}
