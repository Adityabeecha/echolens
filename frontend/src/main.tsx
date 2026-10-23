import React, { useEffect, useState } from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { shareTokenFromHash } from "./nav";
import { SharedBrief } from "./screens/SharedBrief";
import "./tokens.css";

/** A public share link renders on its own, never mounting the signed-in app. */
function Root() {
  const [share, setShare] = useState(() => shareTokenFromHash(window.location.hash));
  useEffect(() => {
    const on = () => setShare(shareTokenFromHash(window.location.hash));
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return share ? <SharedBrief token={share} /> : <App />;
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>
);
