import { useCallback, useEffect, useState } from "react";
import { Evidence, ProductRow, api, getToken, onAuthError, setActiveProduct, setToken } from "./api";
import { CaseTab, GLOBAL_SCREENS, Screen, caseTabFor } from "./nav";
import { useRouter } from "./router";
import { C, T, sans } from "./theme";
import { Sidebar } from "./components/Sidebar";
import { EvidenceSheet } from "./components/EvidenceSheet";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { NewCaseModal } from "./components/NewCaseModal";
import { DeleteProductModal } from "./components/DeleteProductModal";
import { Toasts, clearToasts, toast } from "./components/Toast";
import { Today } from "./screens/Today";
import { Cases } from "./screens/Cases";
import { CaseDetail } from "./screens/CaseDetail";
import { Sources } from "./screens/Sources";
import { Costs } from "./screens/Costs";
import { Settings } from "./screens/Settings";
import { Login } from "./screens/Login";
import { Onboarding } from "./screens/Onboarding";
import { Calibration } from "./screens/Calibration";
import { Patterns } from "./screens/Patterns";
import { Portfolio } from "./screens/Portfolio";
import { Chat } from "./screens/Chat";
import { Backlog } from "./screens/Backlog";
import { Brain } from "./screens/Brain";

export default function App() {
  // Today is home: the first thing you see is what needs you, not a list of
  // everything the detector has ever noticed.
  const { route, navigate, back, backTarget, setParams } =
    useRouter({ screen: "today", productId: null });
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
  const activeProduct = products.find((p) => p.id === activeId) ?? null;
  const productName = activeProduct?.name ?? null;

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

        if (GLOBAL_SCREENS.includes(route.screen)) return; // carry no product
        if (fromUrl == null) {
          // No usable product in the URL (fresh load, or a deep link like
          // /cases/34 that names a case but not its product) — restore the
          // product context rather than leaving the address bar lying.
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

  // Switching product re-scopes everything and lands on Today, because the
  // answer to "how is this one doing" is never the screen you happened to be on.
  const switchProduct = useCallback(
    (id: number) => {
      setActiveProduct(id);
      navigate({ screen: "today", productId: id });
      api.activateProduct(id).catch(() => {
        /* best-effort persistence; the in-memory scope already switched */
      });
    },
    [navigate],
  );

  const go = useCallback(
    (s: Screen, params?: Record<string, string>) => {
      navigate(GLOBAL_SCREENS.includes(s)
        ? { screen: s, productId: null }
        : { screen: s, productId: activeId, params });
    },
    [navigate, activeId],
  );

  const openCase = useCallback(
    (id: number, status?: string) =>
      navigate({ screen: "case", id, tab: caseTabFor(status), productId: activeId }),
    [navigate, activeId],
  );

  const setCaseTab = useCallback(
    (tab: CaseTab) => navigate({ ...route, tab }, { replace: true }),
    [navigate, route],
  );

  const bumpReload = useCallback(() => setReloadKey((k) => k + 1), []);

  const logout = () => {
    setToken(null);
    setAuthed(false);
    clearToasts();  // a previous session's failures must not greet the next user
  };

  if (!authed) return <Login onAuthed={() => setAuthed(true)} />;

  // Wait for the server to tell us which products exist before choosing a screen —
  // otherwise the wizard flashes on every refresh.
  if (!booted) {
    return (
      <div style={{ height: "100vh", background: C.bg, color: C.dim, fontFamily: sans,
                    display: "flex", alignItems: "center", justifyContent: "center", fontSize: T.md }}>
        Loading your workspace…
      </div>
    );
  }

  const { screen } = route;
  const caseId = route.id ?? null;
  const params = route.params ?? {};
  // Onboarding owns the whole window: a half-connected product has nothing to
  // navigate to, and leaving the nav live invited exactly the mis-scoped cases
  // that filed work under the previous product.
  const fullscreen = screen === "onboarding";
  const key = activeId ?? "none";

  return (
    <div
      className="el-shell"
      style={{
        display: "flex",
        // dvh, not vh: on mobile browsers `100vh` measures the viewport WITHOUT
        // the address bar, so the bottom of the app sat permanently under it.
        height: "100dvh",
        background: C.bg,
        color: C.text,
        fontFamily: sans,
        fontSize: T.base,
        overflow: "hidden"
      }}
    >
      {!fullscreen && (
        <Sidebar
          // Keyed on the product for the same reason every screen is: child
          // effects flush BEFORE parent effects, so on a product switch the
          // sidebar's own fetch fired while api.ts still held the previous
          // _productId — showing the old product's running cases under the new
          // product's name. Remounting makes the scope change unmissable.
          key={activeId ?? "none"}
          screen={screen}
          go={go}
          onLogout={logout}
          products={products}
          activeId={activeId}
          onSwitchProduct={switchProduct}
          onAddProduct={() => navigate({ screen: "onboarding", productId: null })}
          onDeleteProduct={setDeleting}
        />
      )}

      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column",
                    overflow: "hidden" }}>
        <ErrorBoundary // The tab is part of the key: a TraceTab that threw stayed broken when
          // you switched to Finding, because nothing in the key had changed.
          resetKey={`${screen}:${caseId}:${route.tab ?? ""}:${activeId}`} onGoHome={() => go("today")}>
          {/* Product-scoped screens remount per product so they re-fetch; the
              case detail is keyed by case id for the same reason. */}
          {screen === "today" && (
            <Today
              key={key}
              productName={productName}
              onOpenCase={openCase}
              onGoCases={(tab) => go("cases", tab && tab !== "all" ? { tab } : undefined)}
              onGoSources={() => go("sources")}
              onGoPlan={() => go("plan")}
              reloadKey={reloadKey}
              bumpReload={bumpReload}
            />
          )}

          {screen === "cases" && (
            <Cases
              key={key}
              productName={productName}
              params={params}
              setParams={setParams}
              onOpenCase={openCase}
              onNewCase={() => setNewCaseOpen(true)}
              reloadKey={reloadKey}
              bumpReload={bumpReload}
            />
          )}

          {screen === "case" && caseId != null && (
            <CaseDetail
              key={caseId}
              caseId={caseId}
              tab={route.tab ?? "finding"}
              productName={productName}
              onTab={setCaseTab}
              onBack={back}
              backLabel={backTarget?.label ?? "Cases"}
              onOpenEvidence={setEvidence}
              onOpenCase={openCase}
              onReviewed={bumpReload}
              onGoCalibration={() => go("calibration")}
              onGoPatterns={() => go("patterns")}
            />
          )}

          {screen === "ask" && (
            <Chat key={key} productName={productName}
                  onOpenInvestigation={(id) => openCase(id, "resolved")} />
          )}

          {screen === "sources" && (
            <Sources key={key} productName={productName}
                     onAddProduct={() => navigate({ screen: "onboarding", productId: null })} />
          )}

          {screen === "patterns" && (
            <Patterns key={key} onGoMemory={() => go("memory")}
                      onGoCases={() => go("cases")} />
          )}

          {screen === "calibration" && (
            <Calibration key={key} onGoCases={() => go("cases", { tab: "needs-review" })} />
          )}

          {screen === "costs" && <Costs key={key} onGoSettings={() => go("settings")} />}

          {screen === "settings" && (
            <Settings
              key={key}
              product={activeProduct}
              onGoCosts={() => go("costs")}
              onGoSources={() => go("sources")}
              onAddProduct={() => navigate({ screen: "onboarding", productId: null })}
              onDeleteProduct={setDeleting}
            />
          )}

          {/* Reached from within another screen rather than from the nav, so
              they carry a named Back instead of a nav highlight. */}
          {screen === "plan" && (
            <Backlog key={key} onOpenInvestigation={openCase} onBack={back}
                     onGoCases={() => go("cases")}
                     backLabel={backTarget?.label ?? "Today"} />
          )}
          {screen === "memory" && (
            <Brain key={key} onOpenInvestigation={openCase} onBack={back}
                   onGoCases={() => go("cases")}
                   backLabel={backTarget?.label ?? "Patterns"} />
          )}

          {screen === "portfolio" && (
            <Portfolio
              onOpenProduct={switchProduct}
              onOpenInvestigation={(id) => openCase(id, "resolved")}
              onAddProduct={() => navigate({ screen: "onboarding", productId: null })}
            />
          )}

          {screen === "onboarding" && (
            <Onboarding
              canSkip={products.length > 0}
              onProductCreated={(id) => {
                // Scope everything to the new product straight away.
                setActiveProduct(id);
                api.products().then((r) => setProducts(r.products)).catch(() => {});
                api.activateProduct(id).catch(() => {});
              }}
              onCancel={() => navigate({ screen: "today", productId: activeId }, { replace: true })}
              onDone={() => finishOnboarding("today")}
              onReviewSignals={() => finishOnboarding("cases", { signals: "1" })}
            />
          )}
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
            if (id === activeId) switchProduct(left[0].id);
            else bumpReload();
          }}
        />
      )}

      <EvidenceSheet evidence={evidence} onClose={() => setEvidence(null)} />
      {newCaseOpen && (
        <NewCaseModal
          onClose={() => setNewCaseOpen(false)}
          onStarted={(investigationId) => {
            setNewCaseOpen(false);
            bumpReload();
            openCase(investigationId, "running"); // jump straight to the live trace
          }}
        />
      )}
      <Toasts />
    </div>
  );

  /** Leaving the wizard: adopt the new product, then land where asked. */
  function finishOnboarding(target: Screen, extra?: Record<string, string>) {
    api.products().then((r) => {
      setProducts(r.products);
      // By created_at (then id), not array position. GET /products carries no
      // ordering guarantee, so "the last element" could be any product — you
      // could finish adding "Acme" and land on Today for a different app.
      const newest = [...r.products].sort((a, b) =>
        String(b.created_at ?? "").localeCompare(String(a.created_at ?? "")) || b.id - a.id)[0];
      if (!newest) return;
      setActiveProduct(newest.id);
      api.activateProduct(newest.id).catch(() => {});
      bumpReload();
      navigate({ screen: target, productId: newest.id, params: extra }, { replace: true });
    }).catch(() => {
      // Without this the wizard sat on its completed state forever with no
      // feedback if the refresh failed.
      toast.fail("Couldn't load your new product — reload the page to continue.");
    });
  }
}
