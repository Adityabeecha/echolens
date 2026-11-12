import { MouseEvent, useState } from "react";
import { api, endSession, setGuest, setRole } from "../api";
import { useAsync } from "../hooks";
import { Button } from "../ui";
import { SerifHeadline } from "../components/casefile";
import { LogoLockup } from "../components/Logo";
import { Login } from "./Login";
import { ExampleCase } from "./landing/ExampleCase";
import { HowItWorks } from "./landing/HowItWorks";
import { HonestyChecks } from "./landing/HonestyChecks";
import "./landing/public.css";

/**
 * The public front door (design/approved/landing.html): what EchoLens does,
 * the loop in five steps, the honesty checks it cannot skip, and a one-click
 * way into the live demo. Sign-in opens as a sheet over this page.
 *
 * `?signin` opens the sign-in sheet directly (bookmarks, "Sign in" from the
 * demo banner, the login QA script).
 */
export function Landing({ onAuthed }: { onAuthed: () => void }) {
  const [signingIn, setSigningIn] = useState(
    () => typeof window !== "undefined" && new URLSearchParams(window.location.search).has("signin"));
  // The demo is offered unless the server says guests are off. If the call
  // fails (a free-tier backend asleep), the button stays: the page should not
  // hide its main door because of one slow request.
  const cfg = useAsync(() => api.authConfig(), []);
  const demoOn = cfg.data?.allow_guest !== false;

  const explore = () => {
    setGuest(true);
    endSession();
    // Explicitly viewer: a stale "admin" from an old session must not unlock
    // UI the server will refuse. Boot re-confirms this against /auth/me.
    setRole("viewer");
    onAuthed();
  };
  const openSignIn = () => setSigningIn(true);
  const closeSignIn = () => {
    setSigningIn(false);
    if (new URLSearchParams(window.location.search).has("signin")) {
      window.history.replaceState(null, "", window.location.pathname);
    }
  };
  // In-page links: the router owns hashes, so scroll (and move focus) by hand.
  const jump = (id: string) => (event: MouseEvent<HTMLAnchorElement>) => {
    event.preventDefault();
    const target = document.getElementById(id);
    target?.scrollIntoView();
    target?.focus({ preventScroll: true });
  };

  return (
    <div className="pub-page el-landing">
      <header className="pub-wrap pub-top">
        <LogoLockup size={30} />
        <nav aria-label="Page" className="pub-top__nav">
          <a href="#how" onClick={jump("how")}>How it works</a>
          <a href="#honest" onClick={jump("honest")}>Why you can trust it</a>
        </nav>
        <span className="pub-top__spacer" />
        <a className="pub-top__github" href={GITHUB_URL} target="_blank" rel="noreferrer"
          aria-label="EchoLens on GitHub (opens in a new tab)">
          <GitHubMark />
          <span className="pub-top__github-label" aria-hidden="true">GitHub</span>
        </a>
        {demoOn ? (
          <>
            <button type="button" className="pub-top__signin" onClick={openSignIn}>Sign in</button>
            <Button variant="primary" className="pub-btn pub-top__demo" onClick={explore}>
              <span>Explore <span className="pub-top__demo-long">the live </span>demo</span>
            </Button>
          </>
        ) : (
          <Button variant="primary" className="pub-btn" onClick={openSignIn}>Sign in</Button>
        )}
      </header>

      <main>
        <section className="pub-wrap pub-hero" aria-labelledby="pub-hero-title">
          <div className="pub-hero__copy">
            <div className="pub-kicker">FEEDBACK FORENSICS FOR APP MAKERS</div>
            <SerifHeadline as="h1" size="hero" id="pub-hero-title">
              Find the root cause before the reviews pile up.
            </SerifHeadline>
            <p className="pub-lede">
              EchoLens reads your app-store reviews and GitHub issues, notices when something breaks,
              and finds out why — with proof you can click. Then it tells you if your fix worked.
            </p>
            <div className="pub-actions">
              {demoOn && (
                <Button variant="primary" className="pub-btn pub-btn--lg" onClick={explore}>
                  Explore the live demo
                </Button>
              )}
              <Button variant={demoOn ? "ghost" : "primary"} className="pub-btn pub-btn--lg" onClick={openSignIn}>
                Connect your app
              </Button>
            </div>
            <div className="pub-note">
              {demoOn ? "No sign-up for the demo · " : ""}works with Google Play, App Store, GitHub and CSV exports
            </div>
          </div>
          <ExampleCase />
        </section>

        <section id="how" tabIndex={-1} className="pub-band" aria-labelledby="pub-how-title">
          <div className="pub-wrap pub-stack">
            <h2 id="pub-how-title" className="pub-h2">From a pile of reviews to one clear answer.</h2>
            <HowItWorks />
          </div>
        </section>

        <section id="honest" tabIndex={-1} className="pub-wrap pub-honest pub-stack" aria-labelledby="pub-honest-title">
          <div className="pub-honest__intro">
            <h2 id="pub-honest-title" className="pub-h2">We'd rather say “not sure” than guess.</h2>
            <p>Every answer passes the same honesty checks, written in code — not in a prompt.
              When the proof isn't there, EchoLens says so.</p>
          </div>
          <HonestyChecks />
        </section>

        <section className="pub-wrap pub-cta-wrap" aria-label="Get started">
          <div className="pub-cta">
            {demoOn ? (
              <>
                <h2>See it solve a real problem. No sign-up.</h2>
                <Button variant="primary" className="pub-btn" onClick={explore}>Explore the live demo</Button>
              </>
            ) : (
              <>
                <h2>Point EchoLens at your app.</h2>
                <Button variant="primary" className="pub-btn" onClick={openSignIn}>Sign in</Button>
              </>
            )}
          </div>
        </section>
      </main>

      {signingIn && (
        <Login onAuthed={onAuthed} onClose={closeSignIn} onExplore={demoOn ? explore : undefined} />
      )}
    </div>
  );
}

const GITHUB_URL = "https://github.com/Adityabeecha/echolens";

/** GitHub's mark, inline so it needs no request and follows the text colour. */
function GitHubMark() {
  return (
    <svg width="20" height="20" viewBox="0 0 16 16" aria-hidden="true" focusable="false" fill="currentColor">
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
    </svg>
  );
}
