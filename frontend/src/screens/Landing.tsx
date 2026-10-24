import { useEffect, useState } from "react";
import { api, endSession, setGuest, setRole } from "../api";
import { useAsync } from "../hooks";
import { C, MEASURE, R, S, T, mono, sans } from "../theme";
import { Login, TracePreview, Wordmark } from "./Login";

// The whole loop, in the order the product walks it. Short on purpose: this is
// the picture a visitor should leave with, not documentation.
const LOOP: { step: string; detail: string; color: string }[] = [
  { step: "Detect", detail: "A spike or a new complaint theme in your reviews", color: C.muted },
  { step: "Investigate", detail: "An agent tests competing causes, step by step", color: C.info },
  { step: "Evidence", detail: "Every claim cites a quote you can open", color: C.accent },
  { step: "Decide & plan", detail: "Approve, park or won't-fix — ranked by impact", color: C.text2 },
  { step: "File the issue", detail: "GitHub, Linear or Jira, evidence attached", color: C.text2 },
  { step: "Verify the fix", detail: "Complaints are watched after it ships", color: C.good },
  { step: "Learn", detail: "Confirmed fixes become patterns for next time", color: C.good },
];

/**
 * The public front door. A visitor used to land on a sign-in form for a product
 * they had never seen; now they see what it does, how the loop works, and — on
 * a deployment that allows it — a one-click way into the live demo. Sign-in is
 * one step away, and the demo is never hidden behind an account link.
 *
 * `?signin` opens the sign-in view directly (bookmarks, the login QA script).
 */
export function Landing({ onAuthed }: { onAuthed: () => void }) {
  const [signingIn, setSigningIn] = useState(
    () => typeof window !== "undefined" && new URLSearchParams(window.location.search).has("signin"));
  const [narrow, setNarrow] = useState(typeof window !== "undefined" && window.innerWidth < 900);
  // If the call fails (backend asleep), the page still renders; only the demo
  // button waits for the deployment to say guests are allowed.
  const cfg = useAsync(() => api.authConfig(), []);
  const guestAllowed = !!cfg.data?.allow_guest;

  useEffect(() => {
    const onResize = () => setNarrow(window.innerWidth < 900);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const explore = () => {
    setGuest(true);
    endSession();
    // Explicitly viewer, as on the sign-in view: a stale "admin" from an old
    // session must not unlock UI the server will refuse.
    setRole("viewer");
    onAuthed();
  };

  if (signingIn) return <Login onAuthed={onAuthed} onBack={() => setSigningIn(false)} />;

  return (
    <div className="el-landing"
      style={{ height: "100dvh", overflowY: "auto", overflowX: "hidden", background: C.bg,
               color: C.text, fontFamily: sans }}>
      <div style={{ maxWidth: 1080, margin: "0 auto",
                    padding: narrow ? `${S[6]} ${S[5]} ${S[10]}` : `${S[8]} ${S[8]} ${S[12]}` }}>
        {/* Right padding: App pins the theme toggle to this corner. */}
        <header style={{ display: "flex", alignItems: "center", gap: S[3], paddingRight: 56 }}>
          <Wordmark />
          <span style={{ flex: 1 }} />
          <button onClick={() => setSigningIn(true)} className="el-btn el-btn--sm"
            style={{ color: C.text2, fontWeight: 500 }}>
            Sign in
          </button>
        </header>

        <section style={{ display: "grid", gap: narrow ? S[8] : S[10], alignItems: "center",
                          gridTemplateColumns: narrow ? "1fr" : "minmax(0, 1.1fr) minmax(0, 1fr)",
                          marginTop: narrow ? S[8] : S[12] }}>
          <div>
            <h1 style={{ margin: 0, fontSize: T.display, fontWeight: 700, letterSpacing: "-0.02em",
                         lineHeight: "var(--el-lh-tight)", textWrap: "balance" as const }}>
              Find the root cause before the reviews pile up.
            </h1>
            <p style={{ fontSize: T.md, color: C.muted, marginTop: S[4], maxWidth: MEASURE,
                        lineHeight: "var(--el-lh-normal)" }}>
              EchoLens watches your app-store reviews and feedback, notices what changed,
              and investigates it the way an analyst would — then follows the fix through
              to the reviews that prove it worked. Every conclusion is backed by evidence
              you can click.
            </p>
            <div style={{ display: "flex", gap: S[3], marginTop: S[6], flexWrap: "wrap",
                          alignItems: "center" }}>
              {guestAllowed && (
                <button onClick={explore} className="el-btn el-btn--primary"
                  style={{ padding: `${S[3]} ${S[6]}`, fontSize: T.md }}>
                  Explore the live demo
                </button>
              )}
              <button onClick={() => setSigningIn(true)}
                className={`el-btn ${guestAllowed ? "el-btn--ghost" : "el-btn--primary"}`}
                style={{ padding: `${S[3]} ${S[6]}`, fontSize: T.md }}>
                Sign in
              </button>
            </div>
            {guestAllowed && (
              <div style={{ fontSize: T.sm, color: C.dim, marginTop: S[2] }}>
                No account needed: a real product's data, read-only.
              </div>
            )}
          </div>

          <div style={{ padding: narrow ? S[5] : S[6], background: C.bgRaised,
                        border: `1px solid ${C.border2}`, borderRadius: R.card }}>
            <div style={{ fontFamily: mono, fontSize: T.micro, letterSpacing: ".1em", color: C.faint }}>
              ONE INVESTIGATION, AS IT HAPPENS
            </div>
            <TracePreview />
          </div>
        </section>

        <section aria-labelledby="el-loop-title" style={{ marginTop: narrow ? S[10] : S[12] }}>
          <h2 id="el-loop-title" style={{ margin: 0, fontFamily: mono, fontSize: T.micro,
                                          letterSpacing: ".1em", color: C.faint, fontWeight: 500 }}>
            THE WHOLE LOOP
          </h2>
          <ol style={{ listStyle: "none", margin: `${S[4]} 0 0`, padding: 0, display: "grid", gap: S[3],
                       gridTemplateColumns: narrow ? "1fr" : "repeat(7, minmax(0, 1fr))" }}>
            {LOOP.map((l, i) => (
              <li key={l.step} style={{ display: "flex", flexDirection: narrow ? "row" : "column",
                                        gap: S[2], alignItems: narrow ? "baseline" : "stretch" }}>
                <div style={{ display: "flex", alignItems: "center", gap: S[2] }}>
                  <span style={{ fontFamily: mono, fontSize: T.xs, color: C.faint, minWidth: 18 }}>
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <span style={{ height: 2, flex: narrow ? "none" : 1, width: narrow ? 12 : undefined,
                                 background: l.color, borderRadius: R.sm, opacity: 0.8 }} />
                </div>
                <div>
                  <div style={{ fontSize: T.base, fontWeight: 600, color: C.text }}>{l.step}</div>
                  <div style={{ fontSize: T.sm, color: C.muted, marginTop: S[1],
                                lineHeight: "var(--el-lh-snug)" }}>
                    {l.detail}
                  </div>
                </div>
              </li>
            ))}
          </ol>
        </section>
      </div>
    </div>
  );
}
