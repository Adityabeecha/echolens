import { useEffect, useState } from "react";
import { api, setToken } from "../api";
import { C, mono, sans } from "../theme";

// A branded split sign-in: the left panel is a taste of the product (the lens
// mark + a miniature reasoning trace), the right panel is the form. Collapses
// to a single column on narrow screens.
export function Login({ onAuthed }: { onAuthed: () => void }) {
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [narrow, setNarrow] = useState(typeof window !== "undefined" && window.innerWidth < 900);

  useEffect(() => {
    const onResize = () => setNarrow(window.innerWidth < 900);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const submit = async () => {
    if (!email.trim() || !password) return;
    setBusy(true);
    setError(null);
    try {
      const r = mode === "login"
        ? await api.login(email.trim(), password)
        : await api.signup(email.trim(), password);
      setToken(r.token);
      onAuthed();
    } catch (e) {
      setError(
        mode === "login"
          ? "That email and password didn't match. Check them and try again."
          : String(e).replace("Error: ", "") || "Couldn't create the account."
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ display: "flex", height: "100vh", background: C.bg, color: C.text, fontFamily: sans, overflow: "hidden" }}>
      {!narrow && <BrandPanel />}

      {/* form side */}
      <div
        style={{
          flex: narrow ? 1 : "0 0 460px",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          padding: narrow ? "0 24px" : "0 56px",
          borderLeft: narrow ? "none" : `1px solid ${C.border}`,
        }}
      >
        {narrow && <Wordmark />}

        <div style={{ fontSize: 22, fontWeight: 700, letterSpacing: "-0.01em", marginTop: narrow ? 28 : 0 }}>
          {mode === "login" ? "Sign in" : "Create your admin account"}
        </div>
        <div style={{ fontSize: 13.5, color: C.muted, marginTop: 8, lineHeight: 1.5, maxWidth: 360 }}>
          {mode === "login"
            ? "Pick up where the investigations left off."
            : "The first account becomes the workspace admin. You can add reviewers later."}
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 12, marginTop: 24, maxWidth: 360 }}>
          <Field label="Email">
            <input
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@company.com"
              autoComplete="username"
              onKeyDown={(e) => e.key === "Enter" && submit()}
              style={inputStyle}
            />
          </Field>
          <Field label="Password">
            <input
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              type="password"
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              onKeyDown={(e) => e.key === "Enter" && submit()}
              style={inputStyle}
            />
          </Field>

          {error && (
            <div style={{ fontSize: 12.5, color: C.bad, background: "rgba(224,88,79,.08)", border: "1px solid rgba(224,88,79,.35)", borderRadius: 7, padding: "8px 11px", lineHeight: 1.4 }}>
              {error}
            </div>
          )}

          <button
            onClick={submit}
            disabled={busy || !email.trim() || !password}
            style={{
              marginTop: 4,
              padding: "12px 0",
              borderRadius: 8,
              border: "none",
              background: C.accent,
              color: C.onAccent,
              fontSize: 14,
              fontWeight: 600,
              cursor: email.trim() && password ? "pointer" : "not-allowed",
              opacity: email.trim() && password ? 1 : 0.5,
              transition: "filter .15s",
            }}
          >
            {busy ? "…" : mode === "login" ? "Sign in" : "Create account & sign in"}
          </button>
        </div>

        <div style={{ marginTop: 22, fontSize: 12.5, color: C.dim, maxWidth: 360 }}>
          {mode === "login" ? "First time setting this up? " : "Already have an account? "}
          <span
            onClick={() => {
              setMode(mode === "login" ? "signup" : "login");
              setError(null);
            }}
            style={{ color: C.accent, cursor: "pointer", fontWeight: 500 }}
          >
            {mode === "login" ? "Create the admin account" : "Sign in instead"}
          </span>
        </div>
      </div>
    </div>
  );
}

// ── left brand panel: the product's world ──────────────────────────────

function BrandPanel() {
  const steps: { tag: string; color: string; text: string; mono?: boolean }[] = [
    { tag: "THINK", color: C.muted, text: "1-star reviews jumped 23% — three days after v3.2 shipped." },
    { tag: "TOOL", color: C.info, text: 'search_reviews("battery drain", since="v3.2")', mono: true },
    { tag: "EVID", color: C.accent, text: "“Phone dies by 2pm since the update.”  ev_003" },
    { tag: "FOUND", color: C.good, text: "Background sync holds a wakelock — confidence 0.85." },
  ];
  return (
    <div
      style={{
        flex: 1,
        minWidth: 0,
        position: "relative",
        background: C.bgRaised,
        padding: "56px 56px",
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
        overflow: "hidden",
      }}
    >
      {/* soft amber lens glow, top-left */}
      <div
        style={{
          position: "absolute",
          top: -120,
          left: -120,
          width: 360,
          height: 360,
          borderRadius: "50%",
          background: "radial-gradient(circle, rgba(240,166,60,.14), transparent 70%)",
          pointerEvents: "none",
        }}
      />
      <div style={{ position: "relative", maxWidth: 460 }}>
        <Wordmark large />
        <div style={{ fontSize: 30, fontWeight: 700, lineHeight: 1.2, letterSpacing: "-0.02em", marginTop: 34, textWrap: "balance" as const }}>
          Find the root cause<br />before the reviews pile up.
        </div>
        <div style={{ fontSize: 14, color: C.muted, marginTop: 14, lineHeight: 1.6, maxWidth: 400 }}>
          EchoLens watches your feedback, notices what's off, and investigates it
          the way an analyst would — every conclusion backed by evidence you can click.
        </div>

        {/* miniature reasoning trace */}
        <div style={{ marginTop: 34, display: "flex", flexDirection: "column", gap: 8 }}>
          {steps.map((s, i) => (
            <div key={i} style={{ display: "grid", gridTemplateColumns: "56px 1fr", columnGap: 12, alignItems: "start" }}>
              <div
                style={{
                  fontFamily: mono,
                  fontSize: 9,
                  letterSpacing: ".05em",
                  textAlign: "center",
                  padding: "3px 0",
                  borderRadius: 4,
                  border: `1px solid ${s.color}`,
                  color: s.color,
                  background: C.bg,
                }}
              >
                {s.tag}
              </div>
              <div
                style={{
                  fontSize: 12.5,
                  lineHeight: 1.45,
                  color: s.tag === "TOOL" ? C.info : C.text3,
                  fontFamily: s.mono ? mono : sans,
                  paddingTop: 2,
                }}
              >
                {s.text}
              </div>
            </div>
          ))}
          <div style={{ display: "flex", alignItems: "center", gap: 7, marginTop: 4, marginLeft: 68 }}>
            <div style={{ width: 6, height: 6, borderRadius: "50%", background: C.accent, animation: "elPulse 1.4s infinite" }} />
            <span style={{ fontFamily: mono, fontSize: 9.5, letterSpacing: ".1em", color: C.accent }}>LIVE · EVERY STEP VISIBLE</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function Wordmark({ large }: { large?: boolean }) {
  const d = large ? 34 : 26;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
      <div style={{ width: d, height: d, borderRadius: "50%", border: `2px solid ${C.accent}`, position: "relative", flex: "none" }}>
        <div style={{ position: "absolute", inset: large ? 6 : 5, borderRadius: "50%", background: "radial-gradient(circle at 35% 35%, #f7bd6a, #b06f1a)" }} />
      </div>
      <div>
        <div style={{ fontWeight: 700, fontSize: large ? 19 : 16, letterSpacing: "0.01em" }}>EchoLens</div>
        <div style={{ fontFamily: mono, fontSize: large ? 10 : 9.5, color: C.faint, letterSpacing: ".1em" }}>FEEDBACK FORENSICS</div>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <span style={{ fontFamily: mono, fontSize: 10, letterSpacing: ".1em", color: C.faint }}>{label.toUpperCase()}</span>
      {children}
    </label>
  );
}

const inputStyle: React.CSSProperties = {
  width: "100%",
  background: C.bgRaised,
  border: `1px solid ${C.border3}`,
  borderRadius: 8,
  color: C.text,
  fontFamily: "inherit",
  fontSize: 14,
  padding: "11px 13px",
};
