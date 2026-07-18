import { useState } from "react";
import { api, setToken } from "../api";
import { C, mono, sans } from "../theme";

// Login gate. In production the API requires a bearer token for any mutating
// action; this screen obtains one. The very first signup becomes the admin.
export function Login({ onAuthed }: { onAuthed: () => void }) {
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!email.trim() || !password) return;
    setBusy(true);
    setError(null);
    try {
      if (mode === "login") {
        const r = await api.login(email.trim(), password);
        setToken(r.token);
      } else {
        const r = await api.signup(email.trim(), password);
        setToken(r.token);
      }
      onAuthed();
    } catch (e) {
      setError(
        mode === "login"
          ? "Login failed — check your email/password."
          : String(e).replace("Error: ", "") || "Signup failed."
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      style={{
        display: "flex",
        height: "100vh",
        alignItems: "center",
        justifyContent: "center",
        background: C.bg,
        color: C.text,
        fontFamily: sans,
      }}
    >
      <div style={{ width: 340, padding: 28, background: C.card, border: `1px solid ${C.border2}`, borderRadius: 14 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 20 }}>
          <div style={{ width: 26, height: 26, borderRadius: "50%", border: `2px solid ${C.accent}`, position: "relative" }}>
            <div style={{ position: "absolute", inset: 5, borderRadius: "50%", background: "radial-gradient(circle at 35% 35%, #f7bd6a, #b06f1a)" }} />
          </div>
          <div>
            <div style={{ fontWeight: 700, fontSize: 16 }}>EchoLens</div>
            <div style={{ fontFamily: mono, fontSize: 9.5, color: C.faint, letterSpacing: ".08em" }}>FEEDBACK FORENSICS</div>
          </div>
        </div>

        <div style={{ fontSize: 13, color: C.muted, marginBottom: 14 }}>
          {mode === "login" ? "Sign in to continue." : "Create the first account (becomes admin)."}
        </div>

        <input
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="email"
          autoComplete="username"
          onKeyDown={(e) => e.key === "Enter" && submit()}
          style={inputStyle}
        />
        <input
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="password"
          type="password"
          autoComplete={mode === "login" ? "current-password" : "new-password"}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          style={{ ...inputStyle, marginTop: 10 }}
        />

        {error && <div style={{ color: C.bad, fontSize: 12, marginTop: 10 }}>{error}</div>}

        <button
          onClick={submit}
          disabled={busy || !email.trim() || !password}
          style={{
            width: "100%",
            marginTop: 16,
            padding: "11px 0",
            borderRadius: 8,
            border: "none",
            background: C.accent,
            color: C.onAccent,
            fontSize: 14,
            fontWeight: 600,
            cursor: email.trim() && password ? "pointer" : "not-allowed",
            opacity: email.trim() && password ? 1 : 0.5,
          }}
        >
          {busy ? "…" : mode === "login" ? "Sign in" : "Create account"}
        </button>

        <div
          onClick={() => {
            setMode(mode === "login" ? "signup" : "login");
            setError(null);
          }}
          style={{ marginTop: 14, fontSize: 12, color: C.dim, textAlign: "center", cursor: "pointer" }}
        >
          {mode === "login" ? "First time here? Create the admin account →" : "← Back to sign in"}
        </div>
      </div>
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  width: "100%",
  background: C.bgRaised,
  border: `1px solid ${C.border3}`,
  borderRadius: 7,
  color: C.text,
  fontFamily: "inherit",
  fontSize: 14,
  padding: "10px 12px",
};
