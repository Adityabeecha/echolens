import { useEffect, useState } from "react";
import { Evidence, api, getToken, isAdmin, onAuthError, setToken } from "./api";
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
import { Onboarding } from "./screens/Onboarding";
import { Calibration } from "./screens/Calibration";
import { Overview } from "./screens/Overview";
import { Patterns } from "./screens/Patterns";

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

  // First run: an admin with no real product connected lands on the wizard, not
  // an empty feed. (Demo rows report a "(demo)" name; those don't count.)
  useEffect(() => {
    if (!authed || !isAdmin()) return;
    let alive = true;
    api
      .sources()
      .then((s) => {
        const hasReal = s.connected.some((c) => !c.name.includes("(demo)"));
        if (alive && !hasReal) setScreen("onboarding");
      })
      .catch(() => {
        /* backend down — stay on feed, it shows its own error state */
      });
    return () => {
      alive = false;
    };
  }, [authed]);

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
          <CaseFeed
            onOpenInvestigation={openInvestigation}
            onNewCase={() => setNewCaseOpen(true)}
            reloadKey={reloadKey}
            bumpReload={() => setReloadKey((k) => k + 1)}
          />
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
        {screen === "onboarding" && (
          <Onboarding
            canSkip
            onCancel={() => setScreen("feed")}
            onDone={() => {
              setReloadKey((k) => k + 1);
              setScreen("feed");
            }}
            onOpenInvestigation={openInvestigation}
          />
        )}
        {screen === "archive" && <Archive onOpenInvestigation={openInvestigation} />}
        {screen === "overview" && <Overview onOpenInvestigation={openInvestigation} />}
        {screen === "patterns" && <Patterns />}
        {screen === "calibration" && <Calibration />}
        {screen === "sources" && <Sources onAddProduct={() => setScreen("onboarding")} />}
        {screen === "costs" && <Costs />}
      </div>

      <EvidenceSheet evidence={evidence} onClose={() => setEvidence(null)} />
      {newCaseOpen && (
        <NewCaseModal
          onClose={() => setNewCaseOpen(false)}
          onStarted={(investigationId) => {
            setNewCaseOpen(false);
            setReloadKey((k) => k + 1);
            openInvestigation(investigationId); // jump straight to the live trace
          }}
        />
      )}
    </div>
  );
}
