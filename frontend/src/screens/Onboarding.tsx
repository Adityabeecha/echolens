import { useEffect, useRef, useState } from "react";
import { OnboardStatus, Snapshot, api, canReview } from "../api";
import { C, mono, sans } from "../theme";
import { Dot, Label } from "../ui";

interface Props {
  onDone: () => void; // go to the populated Case Feed
  onOpenInvestigation: (id: number) => void;
  canSkip: boolean; // first run has nothing to skip to; later, "cancel" is allowed
  onCancel: () => void;
}

// The first-run wizard: two inputs → hands-off backfill → live health snapshot →
// a populated feed. The wait is never blank: the snapshot fills in as data lands.
export function Onboarding({ onDone, onOpenInvestigation, canSkip, onCancel }: Props) {
  const [phase, setPhase] = useState<"form" | "running">("form");
  const [product, setProduct] = useState("");

  return (
    <div style={{ height: "100%", overflow: "auto", background: C.bg }}>
      <div style={{ maxWidth: 760, margin: "0 auto", padding: "48px 28px 80px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 6 }}>
          <Logo />
          <div style={{ fontFamily: mono, fontSize: 10.5, letterSpacing: ".14em", color: C.faint }}>
            ADD YOUR PRODUCT
          </div>
        </div>
        <h1 style={{ fontSize: 27, fontWeight: 700, letterSpacing: "-.02em", margin: "10px 0 8px" }}>
          {phase === "form" ? "Point EchoLens at your app" : `Setting up ${product}`}
        </h1>
        <p style={{ fontSize: 14.5, color: C.muted, lineHeight: 1.6, margin: "0 0 28px", maxWidth: 620 }}>
          {phase === "form"
            ? "Give it a Play Store package and (optionally) a GitHub repo. EchoLens backfills 90 days of reviews, issues and releases, builds a baseline, and surfaces what needs your attention — hands-off from here."
            : "Backfilling your feedback. Here's what we've found so far — no need to wait for it to finish."}
        </p>

        {phase === "form" ? (
          <OnboardForm
            onStarted={(p) => {
              setProduct(p);
              setPhase("running");
            }}
            canSkip={canSkip}
            onCancel={onCancel}
          />
        ) : (
          <Backfilling product={product} onDone={onDone} onOpenInvestigation={onOpenInvestigation} />
        )}
      </div>
    </div>
  );
}

function Logo() {
  return (
    <div style={{ width: 24, height: 24, borderRadius: "50%", border: `2px solid ${C.accent}`, position: "relative", flex: "none" }}>
      <div style={{ position: "absolute", inset: 4, borderRadius: "50%", background: "radial-gradient(circle at 35% 35%, #f7bd6a, #b06f1a)" }} />
    </div>
  );
}

// ── step 1: the two inputs ──────────────────────────────────────────────

function OnboardForm({ onStarted, canSkip, onCancel }: { onStarted: (product: string) => void; canSkip: boolean; onCancel: () => void }) {
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
      onStarted(r.product);
    } catch (e) {
      setError(String(e).replace("Error: ", ""));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
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
        <div style={{ padding: "10px 14px", border: `1px solid ${C.bad}55`, background: `${C.bad}14`, borderRadius: 8, color: C.bad, fontSize: 13 }}>
          {error}
        </div>
      )}

      <div style={{ display: "flex", alignItems: "center", gap: 14, marginTop: 4 }}>
        <button onClick={submit} disabled={!pkg.trim() || busy} className="el-btn"
          style={{ background: C.accent, color: C.onAccent, border: "none", borderRadius: 8, padding: "12px 24px", fontWeight: 600, fontSize: 14, fontFamily: sans, cursor: pkg.trim() && !busy ? "pointer" : "not-allowed", opacity: pkg.trim() && !busy ? 1 : 0.5 }}>
          {busy ? "Starting backfill…" : "Start backfill"}
        </button>
        {canSkip && (
          <button onClick={onCancel} className="el-btn"
            style={{ background: "transparent", color: C.muted, border: "none", fontSize: 13, cursor: "pointer" }}>
            Cancel
          </button>
        )}
        <span style={{ fontSize: 12, color: C.faint }}>You need admin access to connect a product.</span>
      </div>
    </div>
  );
}

function Field({ label, hint, children }: { label: string; hint: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 7 }}>
        <span style={{ fontSize: 13.5, fontWeight: 600, color: C.text2 }}>{label}</span>
        <span style={{ fontSize: 12, color: C.faint }}>{hint}</span>
      </div>
      {children}
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  width: "100%",
  background: C.bgRaised,
  border: `1px solid ${C.border3}`,
  borderRadius: 9,
  color: C.text,
  fontFamily: mono,
  fontSize: 14,
  padding: "12px 14px",
};

// ── step 2: live backfill + snapshot ────────────────────────────────────

function Backfilling({ product, onDone, onOpenInvestigation }: { product: string; onDone: () => void; onOpenInvestigation: (id: number) => void }) {
  const [status, setStatus] = useState<OnboardStatus | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    let alive = true;
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
        if (alive) setErr(String(e).replace("Error: ", ""));
      }
    };
    poll();
    timer.current = window.setInterval(poll, 2500);
    return () => {
      alive = false;
      if (timer.current) window.clearInterval(timer.current);
    };
  }, [product]);

  if (err && !status) return <div style={{ color: C.bad, fontSize: 13 }}>{err}</div>;
  if (!status) return <div style={{ color: C.dim, fontSize: 14 }}>Connecting…</div>;

  const snap = status.snapshot;
  const anomalies = status.anomalies.filter((a) => a.status === "pending");
  const ready = snap.reviews > 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 22 }}>
      {/* source health */}
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {status.sources.map((s) => {
          const color = s.status === "error" ? C.bad : s.status === "healthy" ? C.good : C.accent;
          const label =
            s.status === "error" ? (s.last_error || "failed") :
            s.status === "healthy" ? `${s.items_last_run.toLocaleString()} items pulled` :
            s.never_collected ? "backfilling…" : "syncing…";
          return (
            <div key={s.source + s.identifier} style={{ display: "flex", alignItems: "center", gap: 11, padding: "11px 15px", background: C.card, border: `1px solid ${C.border2}`, borderRadius: 10 }}>
              <Dot color={color} pulse={status.backfilling && s.status !== "error" && s.status !== "healthy"} />
              <span style={{ fontSize: 13.5, fontWeight: 500 }}>{s.source === "play_store" ? "Play Store" : "GitHub"}</span>
              <span style={{ fontFamily: mono, fontSize: 11.5, color: C.faint }}>{s.identifier}</span>
              <div style={{ flex: 1 }} />
              <span style={{ fontSize: 12.5, color: s.status === "error" ? C.bad : C.muted }}>{label}</span>
            </div>
          );
        })}
      </div>

      {ready ? (
        <SnapshotView snap={snap} />
      ) : (
        <div style={{ padding: "28px 20px", border: `1px dashed ${C.border4}`, borderRadius: 12, textAlign: "center", color: C.dim, fontSize: 13.5 }}>
          {status.backfilling ? "Pulling your first reviews…" : "No reviews came back yet. Check the package name is exactly as it appears in the Play Store URL."}
        </div>
      )}

      {/* signals found */}
      {anomalies.length > 0 && (
        <div style={{ padding: "16px 18px", border: `1px solid ${C.accent}55`, background: `${C.accent}12`, borderRadius: 12 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
            <Dot color={C.accent} pulse />
            <span style={{ fontSize: 14, fontWeight: 600, color: C.accentHi }}>
              {anomalies.length} signal{anomalies.length > 1 ? "s" : ""} already surfaced
            </span>
          </div>
          <div style={{ fontSize: 13, color: C.text3, marginTop: 8, lineHeight: 1.55 }}>
            {anomalies[0].description}
          </div>
        </div>
      )}

      {/* themes → investigate now */}
      {ready && snap.top_themes.length > 0 && (
        <div>
          <Label style={{ marginBottom: 10 }}>TOP NEGATIVE THEMES — INVESTIGATE ANY NOW</Label>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 9 }}>
            {snap.top_themes.map((t) => (
              <ThemeChip key={t.label} theme={t.label} count={t.count} onOpenInvestigation={onOpenInvestigation} />
            ))}
          </div>
        </div>
      )}

      {/* data-quality disclosures */}
      {(snap.data_quality.note || snap.data_quality.non_english_note) && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {snap.data_quality.note && <Notice text={snap.data_quality.note} />}
          {snap.data_quality.non_english_note && <Notice text={snap.data_quality.non_english_note} />}
        </div>
      )}

      {/* CTA */}
      <div style={{ display: "flex", alignItems: "center", gap: 14, marginTop: 6 }}>
        <button onClick={onDone} disabled={!ready} className="el-btn"
          style={{ background: ready ? C.accent : C.hover, color: ready ? C.onAccent : C.dim, border: "none", borderRadius: 8, padding: "12px 24px", fontWeight: 600, fontSize: 14, cursor: ready ? "pointer" : "not-allowed" }}>
          Go to Case Feed
        </button>
        {status.backfilling && <span style={{ fontSize: 12.5, color: C.faint }}>Still backfilling — the feed keeps filling in.</span>}
      </div>
    </div>
  );
}

function SnapshotView({ snap }: { snap: Snapshot }) {
  const delta = snap.rating_delta;
  const deltaColor = delta == null ? C.muted : delta >= 0 ? C.good : C.bad;
  const deltaArrow = delta == null ? "" : delta >= 0 ? "▲" : "▼";
  const max = Math.max(1, ...snap.weekly.map((w) => w.count));

  const tiles = [
    { label: "REVIEWS (90D)", value: snap.reviews.toLocaleString(), color: C.text },
    {
      label: "RATING NOW",
      value: snap.rating_now != null ? `${snap.rating_now.toFixed(1)}★` : "—",
      color: C.text,
      sub: delta != null ? `${deltaArrow} ${Math.abs(delta).toFixed(2)} vs last wk` : undefined,
      subColor: deltaColor,
    },
    { label: "REVIEWS / DAY", value: String(snap.avg_per_day), color: C.text },
    { label: "NEGATIVE", value: snap.negatives.toLocaleString(), color: C.accent },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        {tiles.map((t) => (
          <div key={t.label} style={{ flex: 1, minWidth: 130, padding: "14px 16px", background: C.card, border: `1px solid ${C.border2}`, borderRadius: 11 }}>
            <div style={{ fontFamily: mono, fontSize: 9.5, letterSpacing: ".1em", color: C.faint }}>{t.label}</div>
            <div style={{ fontSize: 23, fontWeight: 700, fontFamily: mono, color: t.color, marginTop: 7 }}>{t.value}</div>
            {t.sub && <div style={{ fontFamily: mono, fontSize: 10.5, color: t.subColor, marginTop: 3 }}>{t.sub}</div>}
          </div>
        ))}
      </div>

      {/* weekly volume bars */}
      <div style={{ padding: "16px 18px", background: C.card, border: `1px solid ${C.border2}`, borderRadius: 11 }}>
        <Label style={{ marginBottom: 12 }}>REVIEW VOLUME · LAST 12 WEEKS</Label>
        <div style={{ display: "flex", alignItems: "flex-end", gap: 5, height: 56 }}>
          {snap.weekly.map((w) => (
            <div key={w.week_start} title={`${w.week_start}: ${w.count}`}
              style={{ flex: 1, height: `${Math.max(4, (w.count / max) * 100)}%`, borderRadius: "3px 3px 0 0", background: "linear-gradient(180deg,#f0a63c,#b06f1a)", opacity: 0.9 }} />
          ))}
        </div>
      </div>
    </div>
  );
}

function ThemeChip({ theme, count, onOpenInvestigation }: { theme: string; count: number; onOpenInvestigation: (id: number) => void }) {
  const [busy, setBusy] = useState(false);
  const reviewer = canReview();

  const investigate = async () => {
    if (!reviewer || busy) return;
    setBusy(true);
    try {
      const r = await api.startInvestigation({
        description: `Rising negative feedback about "${theme}" — investigate the cause.`,
        tier: "quick",
      });
      onOpenInvestigation(r.investigation_id);
    } catch {
      setBusy(false);
    }
  };

  return (
    <button
      onClick={investigate}
      disabled={!reviewer || busy}
      className="el-btn"
      title={reviewer ? "Investigate this theme now" : "Reviewer access needed to investigate"}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 9,
        padding: "8px 13px",
        background: C.card,
        border: `1px solid ${C.border3}`,
        borderRadius: 20,
        color: C.text2,
        fontSize: 13,
        fontFamily: sans,
        cursor: reviewer ? "pointer" : "default",
      }}
    >
      <span>{theme}</span>
      <span style={{ fontFamily: mono, fontSize: 10.5, color: C.faint }}>{count}</span>
      {reviewer && <span style={{ fontSize: 11, color: C.accent }}>{busy ? "…" : "Investigate →"}</span>}
    </button>
  );
}

function Notice({ text }: { text: string }) {
  return (
    <div style={{ display: "flex", gap: 9, padding: "10px 14px", border: `1px solid ${C.border3}`, background: C.card2, borderRadius: 9, color: C.muted, fontSize: 12.5, lineHeight: 1.5 }}>
      <span style={{ color: C.info, flex: "none" }}>ⓘ</span>
      {text}
    </div>
  );
}
