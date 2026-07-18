import { useEffect, useState } from "react";
import { Evidence, getToken, onAuthError, setToken } from "./api";
import { Screen } from "./nav";
import { C, sans } from "./theme";
import { Sidebar } from "./components/Sidebar";
import { EvidenceSheet } from "./components/EvidenceSheet";
import { NewCaseModal } from "./components/NewCaseModal";
import { CaseFeed } from "./screens/CaseFeed";
import { Investigation } from "./screens/Investigation";
import { FindingReview } from "./screens/FindingReview";
import { Archive } from "./screens/Archive";
import { Sources } from "./screens/Sources";
import { Costs } from "./screens/Costs";
import { Login } from "./screens/Login";

export default function App() {
  const [screen, setScreen] = useState<Screen>("feed");
  const [currentInv, setCurrentInv] = useState<number | null>(null);
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const [newCaseOpen, setNewCaseOpen] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [authed, setAuthed] = useState<boolean>(!!getToken());

  // A 401 anywhere (expired/absent token) bounces back to the login screen.
  useEffect(() => {
    onAuthError(() => setAuthed(false));
  }, []);

  // Deep-link support: #case/123 (used by the challenge-reopen redirect).
  useEffect(() => {
    const apply = () => {
      const m = window.location.hash.match(/#case\/(\d+)/);
      if (m) {
        setCurrentInv(parseInt(m[1], 10));
        setScreen("case");
        window.location.hash = "";
      }
    };
    apply();
    window.addEventListener("hashchange", apply);
    return () => window.removeEventListener("hashchange", apply);
  }, []);

  const openInvestigation = (id: number) => {
    setCurrentInv(id);
    setScreen("case");
  };

  const go = (s: Screen) => setScreen(s);

  const logout = () => {
    setToken(null);
    setAuthed(false);
  };

  // Not signed in → show the login gate. (In dev mode the backend still lets
  // reads through, but production needs a token, so we always gate.)
  if (!authed) {
    return <Login onAuthed={() => setAuthed(true)} />;
  }

  const running =
    currentInv != null
      ? {
          label: "Active investigation",
          detail: `case #${currentInv}`,
          color: C.accent,
          dot: C.accent,
          pulse: screen === "case",
        }
      : null;

  return (
    <div
      style={{
        display: "flex",
        height: "100vh",
        background: C.bg,
        color: C.text,
        fontFamily: sans,
        fontSize: 14,
        overflow: "hidden",
      }}
    >
      <Sidebar screen={screen} go={go} running={running} onOpenCase={() => setNewCaseOpen(true)} onLogout={logout} />

      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {screen === "feed" && (
          <CaseFeed onOpenInvestigation={openInvestigation} onNewCase={() => setNewCaseOpen(true)} reloadKey={reloadKey} />
        )}
        {screen === "case" && currentInv != null && (
          <Investigation
            investigationId={currentInv}
            onBack={() => setScreen("feed")}
            onDraftFinding={() => setScreen("finding")}
            onOpenEvidence={setEvidence}
          />
        )}
        {screen === "finding" && currentInv != null && (
          <FindingReview
            investigationId={currentInv}
            onBack={() => setScreen("case")}
            onOpenEvidence={setEvidence}
            onReviewed={() => setReloadKey((k) => k + 1)}
          />
        )}
        {screen === "archive" && <Archive onOpenInvestigation={openInvestigation} />}
        {screen === "sources" && <Sources />}
        {screen === "costs" && <Costs />}
      </div>

      <EvidenceSheet evidence={evidence} onClose={() => setEvidence(null)} />
      {newCaseOpen && (
        <NewCaseModal
          onClose={() => setNewCaseOpen(false)}
          onStarted={() => {
            setNewCaseOpen(false);
            setReloadKey((k) => k + 1);
            setScreen("feed");
          }}
        />
      )}
    </div>
  );
}
