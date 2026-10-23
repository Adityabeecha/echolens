import React, { Suspense, lazy, useEffect, useState } from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { shareTokenFromHash } from "./nav";
import { Centered } from "./ui";
import "./tokens.css";

// Public share links are rare and never need the signed-in app, so their page
// is its own chunk rather than weight on every normal visit.
const SharedBrief = lazy(() => import("./screens/SharedBrief").then((m) => ({ default: m.SharedBrief })));

/** A public share link renders on its own, never mounting the signed-in app. */
function Root() {
  const [share, setShare] = useState(() => shareTokenFromHash(window.location.hash));
  useEffect(() => {
    const on = () => setShare(shareTokenFromHash(window.location.hash));
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
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
