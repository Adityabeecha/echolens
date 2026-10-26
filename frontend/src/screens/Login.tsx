import { FormEvent, ReactNode, useId, useState } from "react";
import { api, errorMessage, setGuest, setRole, startSession } from "../api";
import { useAsync, useDialog } from "../hooks";
import { Button } from "../ui";
import { SerifHeadline } from "../components/casefile";
import { LogoLockup } from "../components/Logo";
import { Icon } from "../components/Icon";
import { GoogleButton } from "../components/GoogleButton";
import "./landing/public.css";

/**
 * Sign in: a calm sheet over the landing page (right-hand panel on desktop,
 * bottom sheet on phones). One ink button, Google where the deployment has it,
 * and "Create the admin account" only while the server would accept one.
 *
 * `.el-login-form` is the sheet's scroll box and `.el-login-form-content` its
 * content: scripts/verify-login-overflow.mjs checks both at 390×320.
 */
export function Login({ onAuthed, onClose, onExplore }: {
  onAuthed: () => void;
  /** Back to the landing page underneath. Esc and the scrim do the same. */
  onClose: () => void;
  /** Into the read-only demo, when this deployment allows guests. */
  onExplore?: () => void;
}) {
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ref = useDialog(onClose);
  const titleId = useId();
  const errorId = useId();

  // What this deployment offers. If the call fails (backend asleep), the
  // email form still shows rather than a blank sheet.
  const cfg = useAsync(() => api.authConfig(), []);
  const googleId = cfg.data?.google_enabled ? cfg.data.google_client_id : "";
  // Older servers don't send signup_open; there it was open whenever auth
  // wasn't required (dev). The server still refuses a signup it won't allow.
  const signupOpen = cfg.data ? (cfg.data.signup_open ?? !cfg.data.auth_required) : false;
  const signup = mode === "signup" && signupOpen;

  const finish = (r: { role: string; csrf_token?: string }) => {
    setGuest(false);
    startSession(r.csrf_token);
    setRole(r.role);
    onAuthed();
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !password) {
      setError(!email.trim() ? "Enter your email address." : "Enter your password.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      finish(signup ? await api.signup(email.trim(), password) : await api.login(email.trim(), password));
    } catch (err) {
      setError(plainAuthError(err, signup));
    } finally {
      setBusy(false);
    }
  };

  const signInWithGoogle = async (credential: string) => {
    setBusy(true);
    setError(null);
    try {
      finish(await api.google(credential));
    } catch (err) {
      setError(plainAuthError(err, false, "Google sign-in didn't work. Try again, or use your email."));
    } finally {
      setBusy(false);
    }
  };

  const switchMode = () => {
    setMode(signup ? "login" : "signup");
    setError(null);
  };

  return (
    <>
      <div className="pub-scrim" onClick={onClose} aria-hidden="true" />
      <div ref={ref} role="dialog" aria-modal="true" aria-labelledby={titleId} className="pub-sheet el-login">
        <div className="el-login-form">
          <div className="el-login-form-content">
            <div className="pub-sheet__head">
              <LogoLockup size={26} />
            </div>

            <SerifHeadline as="h2" size="card" id={titleId}>
              {signup ? "Create the admin account" : "Sign in"}
            </SerifHeadline>
            <p className="pub-sheet__lede">
              {signup
                ? "The first account runs this workspace. You can invite reviewers once you're in."
                : "Pick up where your investigations left off."}
            </p>

            {googleId && !signup && (
              <>
                <div style={{ width: "100%" }}>
                  <GoogleButton clientId={googleId} onCredential={signInWithGoogle} disabled={busy} />
                </div>
                <div className="pub-divider">OR WITH EMAIL</div>
              </>
            )}

            <form className="pub-form" onSubmit={submit} noValidate>
              <Field label="Email">
                <input className="pub-input" type="email" name="email" autoComplete="email"
                  value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com"
                  aria-invalid={!!error && !email.trim()} aria-describedby={error ? errorId : undefined} />
              </Field>
              <Field label="Password" hint={signup ? "At least 10 characters." : undefined}>
                <input className="pub-input" type="password" name="password"
                  autoComplete={signup ? "new-password" : "current-password"}
                  value={password} onChange={(e) => setPassword(e.target.value)}
                  aria-invalid={!!error && !!email.trim() && !password}
                  aria-describedby={error ? errorId : undefined} />
              </Field>

              {error && <div id={errorId} role="alert" className="pub-error">{error}</div>}

              <Button type="submit" variant="primary" loading={busy} className="pub-btn pub-btn--lg pub-wide">
                {busy ? (signup ? "Creating your account…" : "Signing in…")
                  : signup ? "Create account and sign in" : "Sign in"}
              </Button>
            </form>

            {/* People asked what an account means before they sign in. */}
            {!signup && (
              <p className="pub-sheet__note" style={{ margin: 0, fontSize: 13, lineHeight: 1.5, color: "var(--el-muted)" }}>
                EchoLens is in beta. Accounts are set up by your workspace admin{googleId ? " or with an allowed Google account" : ""};
                no card is needed, and AI spend is capped each month in Settings. The demo needs no account at all.
              </p>
            )}

            {signupOpen && (
              <div className="pub-foot">
                {signup ? "Already have an account? " : "Setting up EchoLens for the first time? "}
                <button type="button" className="pub-text-btn" style={{ display: "inline" }} onClick={switchMode}>
                  {signup ? "Sign in instead" : "Create the admin account"}
                </button>
              </div>
            )}

            {onExplore && !signup && (
              <div className="pub-foot">
                No account?{" "}
                <button type="button" className="pub-text-btn" style={{ display: "inline" }} onClick={onExplore}>
                  Explore the live demo
                </button>
                {" "}— read-only, every screen.
              </div>
            )}
          </div>
        </div>
        {/* Last in the DOM so focus opens on the first field, not on Close. */}
        <button type="button" className="pub-close pub-sheet__close" onClick={onClose} aria-label="Close sign-in">
          <Icon name="close" size={16} />
        </button>
      </div>
    </>
  );
}

/** Server and network failures, in words a person can act on. */
function plainAuthError(err: unknown, signup: boolean, fallback?: string): string {
  const raw = errorMessage(err);
  if (/backend is unavailable|timed out/i.test(raw)) {
    return "We couldn't reach EchoLens. It may be waking up — wait a moment and try again.";
  }
  if (/→ 429|too many/i.test(raw)) return "Too many tries in a row. Wait a minute, then try again.";
  if (!signup && /invalid credentials|→ 401/i.test(raw)) {
    return "That email and password don't match. Check them and try again.";
  }
  if (/→ \d{3}$/.test(raw)) return fallback ?? (signup ? "We couldn't create the account. Try again." : "Sign-in didn't work. Try again.");
  const sentence = raw.charAt(0).toUpperCase() + raw.slice(1);
  return /[.!?]$/.test(sentence) ? sentence : `${sentence}.`;
}

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="pub-field">
      <span className="pub-field__label">{label}</span>
      {children}
      {hint && <span className="pub-field__hint">{hint}</span>}
    </label>
  );
}
