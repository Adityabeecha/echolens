import React, { Suspense, lazy, useEffect, useState } from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { currentLocation, legacyHashTarget, shareToken } from "./nav";
import { Centered } from "./ui";
import "./tokens.css";

// Public share links are rare and never need the signed-in app, so their page
// is its own chunk rather than weight on every normal visit.
const SharedBrief = lazy(() => import("./screens/SharedBrief").then((m) => ({ default: m.SharedBrief })));

// Links from older builds are hash routes (/#/p/2/today, /#/share/<token>):
// bookmarks, Slack and email notifications, shared briefs. Rewrite them to the
// clean path BEFORE anything reads the location, so the router, the boot
// sequence and the share page only ever see one URL format.
const legacy = legacyHashTarget(window.location.hash);
if (legacy) window.history.replaceState(null, "", legacy);

/** A public share link renders on its own, never mounting the signed-in app. */
function Root() {
  const [share, setShare] = useState(() => shareToken(currentLocation()));
  useEffect(() => {
    const on = () => setShare(shareToken(currentLocation()) ?? shareToken(window.location.hash));
    window.addEventListener("popstate", on);
    window.addEventListener("hashchange", on);
    return () => {
      window.removeEventListener("popstate", on);
      window.removeEventListener("hashchange", on);
    };
  }, []);
  return share
    ? <Suspense fallback={<Centered>Loading the shared brief…</Centered>}><SharedBrief token={share} /></Suspense>
    : <App />;
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>
);
