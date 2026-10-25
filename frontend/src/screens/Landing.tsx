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
