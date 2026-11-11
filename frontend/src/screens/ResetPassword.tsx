import { FormEvent, useId, useState } from "react";
import { api, errorMessage, setGuest, setRole, startSession } from "../api";
import { Button } from "../ui";
import { SerifHeadline } from "../components/casefile";
import { LogoLockup } from "../components/Logo";
import "./landing/public.css";

/**
 * Where a reset or invite link lands (/reset-password?token=…). One field,
 * then you're signed in. Rendered before the app, like a shared brief, so a
 * locked-out person never meets the sign-in wall first.
 */
export function ResetPassword({ token }: { token: string }) {
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const errorId = useId();

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (password.length < 10) return setError("Use at least 10 characters.");
    if (password !== confirm) return setError("The two passwords don't match.");
    setBusy(true);
    setError(null);
    try {
      const r = await api.confirmPasswordReset(token, password);
      setGuest(false);
      startSession(r.csrf_token);
      setRole(r.role);
      // A clean load of the app, signed in, with the token out of the address bar.
      window.location.replace("/");
    } catch (err) {
      const raw = errorMessage(err);
      setError(/→ 429|too many/i.test(raw) ? "Too many tries in a row. Wait a minute, then try again."
        : /→ \d{3}$/.test(raw) ? "That didn't work. Try again, or ask for a new link." : raw);
      setBusy(false);
    }
  };

  return (
    <div className="pub-page" style={{ minHeight: "100dvh", display: "grid", placeItems: "center", padding: 16 }}>
      <main className="pub-panel" style={{ width: "min(440px, 100%)", display: "flex", flexDirection: "column", gap: 16 }}>
        <LogoLockup size={26} />
        <SerifHeadline as="h1" size="card">Choose your password</SerifHeadline>
        <p style={{ margin: 0, fontSize: 15, lineHeight: 1.5, color: "var(--el-body)" }}>
          This also signs out any other device using your account.
        </p>
        {!token ? (
          <div role="alert" className="pub-error">This link is incomplete. Open it again from your email, or ask for a new one.</div>
        ) : (
          <form className="pub-form" onSubmit={submit} noValidate>
            <label className="pub-field">
              <span className="pub-field__label">New password</span>
              <input className="pub-input" type="password" autoComplete="new-password" autoFocus value={password}
                onChange={(e) => setPassword(e.target.value)} aria-describedby={error ? errorId : undefined} />
              <span className="pub-field__hint">At least 10 characters.</span>
            </label>
            <label className="pub-field">
              <span className="pub-field__label">Type it again</span>
              <input className="pub-input" type="password" autoComplete="new-password" value={confirm}
                onChange={(e) => setConfirm(e.target.value)} aria-describedby={error ? errorId : undefined} />
            </label>
            {error && <div id={errorId} role="alert" className="pub-error">{error}</div>}
            <Button type="submit" variant="primary" loading={busy} className="pub-btn pub-btn--lg pub-wide">
              {busy ? "Saving…" : "Save and sign in"}
            </Button>
          </form>
        )}
        <a href="/" className="pub-text-btn" style={{ alignSelf: "flex-start" }}>← Back to EchoLens</a>
      </main>
    </div>
  );
}
