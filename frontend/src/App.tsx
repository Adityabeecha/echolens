import { useEffect, useState } from "react";
import { Evidence, ProductRow, api, getToken, onAuthError, setActiveProduct, setToken } from "./api";
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
import { Portfolio } from "./screens/Portfolio";
import { Chat } from "./screens/Chat";

export default function App() {
  const [screen, setScreen] = useState<Screen>("feed");
  const [currentInv, setCurrentInv] = useState<number | null>(null);
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const [newCaseOpen, setNewCaseOpen] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [authed, setAuthed] = useState<boolean>(!!getToken());
  const [products, setProducts] = useState<ProductRow[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [booted, setBooted] = useState(false);

  // A 401 anywhere (expired/absent token) bounces back to the login screen.
  useEffect(() => {
    onAuthError(() => setAuthed(false));
  }, []);

  // v8.0 boot routing — SERVER-DERIVED, no localStorage flags. If any product
  // exists we land on the last-active product's Case Feed; only a truly empty
  // workspace (0 products) shows the add-product wizard.
  useEffect(() => {
    if (!authed) return;
    let alive = true;
    api
      .products()
      .then((r) => {
        if (!alive) return;
        setProducts(r.products);
        setBooted(true);
        if (r.products.length === 0) {
          setActiveProduct(null);
          setScreen("onboarding");
          return;
        }
        const active = r.active_product_id ?? r.products[0].id;
        setActiveProduct(active);
        setActiveId(active);
        setScreen("feed");
      })
      .catch(() => {
        if (alive) setBooted(true); // backend down — screens show their own error
      });
    return () => {
      alive = false;
    };
  }, [authed]);

  const switchProduct = (id: number) => {
    setActiveProduct(id);
    setActiveId(id);
    setCurrentInv(null);
    setScreen("feed");
    api.activateProduct(id).catch(() => {
      /* best-effort persistence; the in-memory scope already switched */
    });
  };

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

  // Wait for the server to tell us which products exist before choosing a screen —
  // otherwise the wizard flashes on every refresh.
  if (!booted) {
    return (
      <div style={{ height: "100vh", background: C.bg, color: C.dim, fontFamily: sans,
                    display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14 }}>
        Loading your workspace…
      </div>
    );
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
      <Sidebar
        screen={screen}
        go={go}
        running={running}
        onOpenCase={() => setNewCaseOpen(true)}
        onLogout={logout}
        products={products}
        activeId={activeId}
        onSwitchProduct={switchProduct}
        onAddProduct={() => setScreen("onboarding")}
      />

      {/* keyed by product: switching remounts every screen so it re-scopes */}
      <div key={activeId ?? "none"} style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}>
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
            canSkip={products.length > 0}
            onProductCreated={(id) => {
              // scope everything to the new product straight away — including
              // anything the wizard itself starts
              setActiveProduct(id);
              setActiveId(id);
              api.products().then((r) => setProducts(r.products)).catch(() => {});
              api.activateProduct(id).catch(() => {});
            }}
            onCancel={() => setScreen("feed")}
            onDone={() => {
              // re-read products from the server and land on the new one's feed
              api.products().then((r) => {
                setProducts(r.products);
                const newest = r.products[r.products.length - 1];
                if (newest) {
                  setActiveProduct(newest.id);
                  setActiveId(newest.id);
                  // persist it, or the next refresh snaps back to the old product
                  api.activateProduct(newest.id).catch(() => {});
                }
                setReloadKey((k) => k + 1);
                setScreen("feed");
              });
            }}
            onOpenInvestigation={openInvestigation}
          />
        )}
        {screen === "portfolio" && (
          <Portfolio
            // picking a product here IS switching to it — take the PM to the thing
            onOpenProduct={switchProduct}
            onOpenInvestigation={openInvestigation}
            onAddProduct={() => setScreen("onboarding")}
          />
        )}
        {screen === "archive" && <Archive onOpenInvestigation={openInvestigation} />}
        {screen === "chat" && <Chat onOpenInvestigation={openInvestigation} />}
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
