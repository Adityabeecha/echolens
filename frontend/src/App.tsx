import { useCallback, useEffect, useState } from "react";
import { Evidence, ProductRow, api, getToken, onAuthError, setActiveProduct, setToken } from "./api";
import { GLOBAL_SCREENS, Screen, caseScreenFor } from "./nav";
import { useRouter } from "./router";
import { C, sans } from "./theme";
import { Sidebar } from "./components/Sidebar";
import { EvidenceSheet } from "./components/EvidenceSheet";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { NewCaseModal } from "./components/NewCaseModal";
import { DeleteProductModal } from "./components/DeleteProductModal";
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
import { Backlog } from "./screens/Backlog";
import { Brain } from "./screens/Brain";

export default function App() {
  const { route, navigate, back, backTarget } = useRouter({ screen: "feed", productId: null });
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const [newCaseOpen, setNewCaseOpen] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [authed, setAuthed] = useState<boolean>(!!getToken());
  const [products, setProducts] = useState<ProductRow[]>([]);
  const [booted, setBooted] = useState(false);
  const [deleting, setDeleting] = useState<ProductRow | null>(null);

  // The active product comes from the URL, so a refresh or a shared link lands
  // on the product you were actually looking at.
  const activeId = route.productId ?? null;

  // A 401 anywhere (expired/absent token) bounces back to the login screen.
  useEffect(() => {
    onAuthError(() => setAuthed(false));
  }, []);

  // Keep the api client's scope in step with the URL, before any screen fetches.
  useEffect(() => {
    setActiveProduct(activeId);
  }, [activeId]);

  // Boot: the server decides which products exist and which was last active.
  // The URL wins when it already names one, so a deep link isn't overridden.
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
          navigate({ screen: "onboarding", productId: null }, { replace: true });
          return;
        }

        const known = new Set(r.products.map((p) => p.id));
        const fromUrl = route.productId != null && known.has(route.productId) ? route.productId : null;
        const active = fromUrl ?? r.active_product_id ?? r.products[0].id;
        setActiveProduct(active);

        if (GLOBAL_SCREENS.includes(route.screen)) return; // portfolio/onboarding carry no product
        if (fromUrl == null) {
          // No usable product in the URL (fresh load, or it named a deleted one)
          // — put the real one there rather than leaving the address bar lying.
          navigate({ ...route, productId: active }, { replace: true });
        }
        if (fromUrl != null && fromUrl !== r.active_product_id) {
          // Deep link into another product: make the server agree, so the next
          // plain load comes back here too.
          api.activateProduct(fromUrl).catch(() => {});
        }
      })
      .catch(() => {
        if (alive) setBooted(true); // backend down — screens show their own error
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authed]);

  const switchProduct = useCallback(
    (id: number) => {
      setActiveProduct(id);
      navigate({ screen: "feed", productId: id });
      api.activateProduct(id).catch(() => {
        /* best-effort persistence; the in-memory scope already switched */
      });
    },
    [navigate],
  );

  const go = useCallback(
    (s: Screen) => {
      navigate(GLOBAL_SCREENS.includes(s) ? { screen: s, productId: null } : { screen: s, productId: activeId });
    },
    [navigate, activeId],
  );

  // Finished cases open their finding (the answer); running ones open the live
  // trace. Callers that only ever surface resolved work pass "resolved".
  const openInvestigation = useCallback(
    (id: number, status?: string) =>
      navigate({ screen: caseScreenFor(status), id, productId: activeId }),
    [navigate, activeId],
  );

  const logout = () => {
    setToken(null);
    setAuthed(false);
  };

  if (!authed) return <Login onAuthed={() => setAuthed(true)} />;

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

  const { screen } = route;
  const caseId = route.id ?? null;
  // Onboarding owns the whole window: a half-connected product has nothing to
  // navigate to, and leaving the nav live invited exactly the mis-scoped cases
  // that filed work under the previous product.
  const fullscreen = screen === "onboarding";

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
      {!fullscreen && (
        <Sidebar
          screen={screen}
          go={go}
          onOpenCase={() => setNewCaseOpen(true)}
          onLogout={logout}
          products={products}
          activeId={activeId}
          onSwitchProduct={switchProduct}
          onAddProduct={() => navigate({ screen: "onboarding", productId: null })}
          onDeleteProduct={setDeleting}
        />
      )}

      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        <ErrorBoundary resetKey={`${screen}:${caseId}:${activeId}`} onGoHome={() => go("feed")}>
          {/* Product-scoped screens remount per product so they re-fetch; the
              case/finding pair is keyed by case id for the same reason. */}
          {screen === "feed" && (
            <CaseFeed
              key={activeId ?? "none"}
              onOpenInvestigation={openInvestigation}
              onNewCase={() => setNewCaseOpen(true)}
              reloadKey={reloadKey}
              bumpReload={() => setReloadKey((k) => k + 1)}
            />
          )}
          {screen === "case" && caseId != null && (
            <Investigation
              key={caseId}
              investigationId={caseId}
              onBack={back}
              backLabel={backTarget?.label ?? "the Case Feed"}
              onDraftFinding={() => navigate({ screen: "finding", id: caseId, productId: activeId })}
              onOpenEvidence={setEvidence}
            />
          )}
          {screen === "finding" && caseId != null && (
            <FindingReview
              key={caseId}
              investigationId={caseId}
              onBack={back}
              backLabel={backTarget?.label ?? "the investigation"}
              onOpenTrace={() => navigate({ screen: "case", id: caseId, productId: activeId })}
              onOpenEvidence={setEvidence}
              onReviewed={() => setReloadKey((k) => k + 1)}
            />
          )}
          {screen === "onboarding" && (
            <Onboarding
              canSkip={products.length > 0}
              onProductCreated={(id) => {
                // Scope everything to the new product straight away — including
                // anything the wizard itself starts.
                setActiveProduct(id);
                api.products().then((r) => setProducts(r.products)).catch(() => {});
                api.activateProduct(id).catch(() => {});
              }}
              onCancel={() => navigate({ screen: "feed", productId: activeId }, { replace: true })}
              onDone={() => {
                api.products().then((r) => {
                  setProducts(r.products);
                  const newest = r.products[r.products.length - 1];
                  if (newest) {
                    setActiveProduct(newest.id);
                    api.activateProduct(newest.id).catch(() => {});
                    setReloadKey((k) => k + 1);
                    navigate({ screen: "feed", productId: newest.id }, { replace: true });
                  }
                });
              }}
              onOpenInvestigation={openInvestigation}
            />
          )}
          {screen === "portfolio" && (
            <Portfolio
              onOpenProduct={switchProduct}
              onOpenInvestigation={(id) => openInvestigation(id, "resolved")}
              onAddProduct={() => navigate({ screen: "onboarding", productId: null })}
            />
          )}
          {screen === "backlog" && (
            <Backlog key={activeId ?? "none"} onOpenInvestigation={openInvestigation} />
          )}
          {screen === "archive" && <Archive key={activeId ?? "none"} onOpenInvestigation={(id) => openInvestigation(id, "resolved")} />}
          {screen === "chat" && <Chat key={activeId ?? "none"} onOpenInvestigation={(id) => openInvestigation(id, "resolved")} />}
          {screen === "overview" && <Overview key={activeId ?? "none"} onOpenInvestigation={(id) => openInvestigation(id, "resolved")} />}
          {screen === "patterns" && <Patterns key={activeId ?? "none"} />}
          {screen === "brain" && (
            <Brain key={activeId ?? "none"} onOpenInvestigation={openInvestigation} />
          )}
          {screen === "calibration" && <Calibration key={activeId ?? "none"} />}
          {screen === "sources" && (
            <Sources key={activeId ?? "none"} onAddProduct={() => navigate({ screen: "onboarding", productId: null })} />
          )}
          {screen === "costs" && <Costs key={activeId ?? "none"} />}
        </ErrorBoundary>
      </div>

      {deleting && (
        <DeleteProductModal
          product={deleting}
          onClose={() => setDeleting(null)}
          onDeleted={(id) => {
            setDeleting(null);
            const left = products.filter((p) => p.id !== id);
            setProducts(left);
            if (left.length === 0) {
              // Nothing left to look at — the wizard is the only sensible screen.
              setActiveProduct(null);
              navigate({ screen: "onboarding", productId: null }, { replace: true });
              return;
            }
            // Deleting the product you were viewing must not strand you on a
            // dead URL, so move to a surviving one and tell the server.
            if (id === activeId) {
              switchProduct(left[0].id);
            } else {
              setReloadKey((k) => k + 1);
            }
          }}
        />
      )}

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
