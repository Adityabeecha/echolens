import { ReactNode, Suspense, lazy, useCallback, useEffect, useRef, useState } from "react";
import { ProductRow, api, canReview, endSession, isAdmin, isAuthed, isGuest, onAuthError, setActiveProduct,
         setGuest, setRole } from "./api";
import { CaseTab, GLOBAL_SCREENS, LEARNED_VIEWS, LearnedView, SETTINGS_SECTIONS, Screen,
         SettingsSection, caseTabFor } from "./nav";
import { useRouter } from "./router";
import { clearAsyncCache, useWorkWatcher } from "./hooks";
import { C, T, sans } from "./theme";
import { AppHeader } from "./components/AppHeader";
import { Logo } from "./components/Logo";
import { Icon } from "./components/Icon";
import { AskDrawer, isAskShortcut } from "./components/AskDrawer";
import { Chat } from "./screens/Chat";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { NewCaseModal } from "./components/NewCaseModal";
import { DeleteProductModal } from "./components/DeleteProductModal";
import { Toasts, clearToasts, toast } from "./components/Toast";
import { Today } from "./screens/Today";
import { Cases } from "./screens/Cases";
import { CaseDetail } from "./screens/CaseDetail";
import { Landing } from "./screens/Landing";
import { Centered } from "./ui";
import { ThemeToggle } from "./components/ThemeToggle";
import { FirstRunTour } from "./components/FirstRunTour";
import { markTourSeen, tourSeen } from "./tourState";
import { ThemeMode, applyTheme, persistTheme, resolveTheme } from "./themeMode";

// Route-level code splitting. Today, Cases and the case detail are where
// nearly every visit starts and stays, so they ship in the main bundle; the
// rest load on first visit. A chunk that fails to load (a redeploy replaced
// it) throws inside the ErrorBoundary below, which offers a way back.
const Sources = lazy(() => import("./screens/Sources").then((m) => ({ default: m.Sources })));
const Settings = lazy(() => import("./screens/Settings").then((m) => ({ default: m.Settings })));
const Onboarding = lazy(() => import("./screens/Onboarding").then((m) => ({ default: m.Onboarding })));
const Portfolio = lazy(() => import("./screens/Portfolio").then((m) => ({ default: m.Portfolio })));
const Backlog = lazy(() => import("./screens/Backlog").then((m) => ({ default: m.Backlog })));
const LearnedPatterns = lazy(() => import("./screens/LearnedPatterns").then((m) => ({ default: m.LearnedPatterns })));
const DesignGallery = import.meta.env.DEV ? lazy(() => import("./components/casefile/DesignGallery")) : null;

/** The wait while a lazily loaded screen's chunk arrives. */
function ScreenChunk({ children, fallback = <Centered>Loading…</Centered> }: {
  children: ReactNode; fallback?: ReactNode;
}) {
  return <Suspense fallback={fallback}>{children}</Suspense>;
}

export default function App() {
  if (DesignGallery && window.location.pathname === "/design") {
    return <Suspense fallback={<Centered>Loading the design library…</Centered>}><DesignGallery /></Suspense>;
  }
  return <WorkspaceApp />;
}

function WorkspaceApp() {
  const [theme, setTheme] = useState<ThemeMode>(() => resolveTheme());
  // Today is home: the first thing you see is what needs you, not a list of
  // everything the detector has ever noticed.
  const { route, navigate, back, backTarget, setParams } =
    useRouter({ screen: "today", productId: null });
  const [askOpen, setAskOpen] = useState(false);
  const askReturnFocus = useRef<HTMLElement | null>(null);
  const closeAsk = useCallback(() => setAskOpen(false), []);
  const openAsk = useCallback(() => {
    if (askOpen) return;
    // Capture before making the background inert, which may blur the opener.
    askReturnFocus.current = document.activeElement as HTMLElement | null;
    setAskOpen(true);
  }, [askOpen]);
  const [newCaseOpen, setNewCaseOpen] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  // "In the app" is either a real session or an accepted guest visit. A guest
  // has no token, so `authed` alone would bounce them straight back to Login.
  // A guest arriving at "/" sees the landing page (with "Explore the demo"),
  // not a silent redirect back into the demo they may have meant to leave.
  const [authed, setAuthed] = useState<boolean>(
    () => isAuthed() || (isGuest() && window.location.pathname !== "/"));
  const [products, setProducts] = useState<ProductRow[]>([]);
  const [booted, setBooted] = useState(false);
  const [deleting, setDeleting] = useState<ProductRow | null>(null);
  // The first-run tour opens once, when the first product is added.
  const [tourOpen, setTourOpen] = useState(false);
  const closeTour = useCallback(() => { markTourSeen(); setTourOpen(false); }, []);

  useEffect(() => {
    applyTheme(theme);
    persistTheme(theme);
  }, [theme]);


  // The active product comes from the URL, so a refresh or a shared link lands
  // on the product you were actually looking at.
  // "Add a product" is an overlay with a product-less URL. Keep showing the
  // product behind it: dropping it blanked the switcher ("Choose product") and
  // Today's health ("—") while the dialog was open.
  const lastProductRef = useRef<number | null>(null);
  const createdProductRef = useRef<number | null>(null);
  if (route.productId != null) lastProductRef.current = route.productId;
  const activeId = route.productId ?? (route.screen === "onboarding" ? lastProductRef.current : null);
  const activeProduct = products.find((p) => p.id === activeId) ?? null;
  const productName = activeProduct?.name ?? null;

  // Cached reads belong to one product. Cleared during render, BEFORE the
  // screens for the new product mount and read the cache — an effect would
  // run after them and let one product's numbers flash under another's name.
  const cacheScope = useRef<number | null | undefined>(undefined);
  if (cacheScope.current !== activeId) {
    if (cacheScope.current !== undefined) clearAsyncCache();
    cacheScope.current = activeId;
  }

  // A 401 anywhere (expired/absent token) bounces back to the login screen.
  useEffect(() => {
    // A 401 ends the session — but a guest browsing a guest-enabled deployment
    // has no session to end, and bouncing them to Login on one unlucky request
    // would look like the demo breaking.
    onAuthError(() => { if (!isGuest()) setAuthed(false); });
  }, []);

  // "Import CSV" arrives as ?import=1 so Sources opens with its form showing.
  // Consumed once: a refresh or a later visit must not reopen it.
  useEffect(() => {
    if (route.screen === "sources" && route.params?.import) setParams({ import: null });
  }, [route.screen, route.params?.import, setParams]);

  // Keep the api client's scope in step with the URL, before any screen fetches.
  useEffect(() => {
    setActiveProduct(activeId);
  }, [activeId]);

  useEffect(() => {
    if (!authed) { setAskOpen(false); return; }
    const onKey = (event: KeyboardEvent) => {
      if (!isAskShortcut(event)) return;
      event.preventDefault();
      openAsk();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [authed, openAsk]);

  // Boot: the server decides which products exist and which was last active.
  // The URL wins when it already names one, so a deep link isn't overridden.
  useEffect(() => {
    if (!authed) return;
    let alive = true;
    // Ask the server who we are BEFORE deciding anything on role.
    //
    // The role was read from localStorage, which is stale after any change of
    // deployment mode and editable by anyone with devtools. A browser left
    // holding `echolens_role: "admin"` from an earlier dev-mode session was
    // treated as an admin and pushed into the product wizard, where every
    // action then 403'd. The server is the only authority on this; the local
    // copy is now just a cache to avoid a flash of the wrong UI.
    api
      .me()
      .then((me) => { if (alive && me?.role) setRole(me.role); })
      .catch(() => {
        // Fail CLOSED. Falling back to the cached role restored exactly what
        // the comment above says was removed: a browser holding a planted or
        // stale `echolens_role: "admin"` rendered the full admin UI whenever
        // /auth/me failed, and a cold backend is enough to trigger that. The
        // server still refuses the actions, so this was never an escalation —
        // but it offered controls that could only 403, on the one failure path
        // the fix was written for. `viewer` is the least privilege, so an
        // unverifiable session shows the least.
        if (alive) setRole("viewer");
      })
      .then(() => api.products())
      .then((r) => {
        if (!alive || !r) return;
        setProducts(r.products);
        setBooted(true);

        if (r.products.length === 0) {
          setActiveProduct(null);
          // Only an admin can actually complete this wizard. A guest browsing
          // an empty demo used to be redirected into a form where every button
          // 403s, with the nav hidden — a dead end. Everyone else lands on
          // Today, whose empty states explain the situation and stay navigable.
          if (isAdmin()) {
            navigate({ screen: "onboarding", productId: null }, { replace: true });
          }
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

  /** Dismiss the onboarding overlay and return to the app behind it. */
  const closeOnboarding = useCallback(
    () => navigate({ screen: "today", productId: activeId }, { replace: true }),
    [navigate, activeId],
  );

  // While anything is queued or running, watch for it to finish and refresh
  // every list when it does. Without this a queued case sat at "Queued" until
  // the user reloaded the page by hand — the work had actually completed, but
  // nothing on screen said so. Keyed on reloadKey so queueing something (which
  // bumps it) also wakes the watcher; it stops polling once nothing is in
  // flight, so an idle workspace issues no requests.
  // A queued case has no investigation id, so its card is not clickable and
  // there is no way to open it and watch it think. By the time it becomes
  // clickable it is usually finished — which is why the reasoning only ever
  // appeared after the fact. Offer the live view the instant the id exists.
  const announceStarted = useCallback((id: number) => {
    // Already watching it: no toast, and no navigation that would reset the
    // trace scroll under someone who is reading it.
    if (route.screen === "case" && route.id === id) return;
    toast.action(`Case #${id} is running now.`, "Watch live",
                 () => openCase(id, "running"));
  }, [route.screen, route.id, openCase]);

  useWorkWatcher(activeId, reloadKey, bumpReload, 4000, announceStarted);

  const logout = () => {
    closeAsk();
    clearAsyncCache();
    endSession();
    // Drop the cached role too. Leaving "admin" behind is what let a stale
    // value from an earlier session decide the next one's UI.
    setRole("viewer");
    // Clear guest too: "Sign out" must return to the door, not silently drop
    // the user into a read-only session they did not ask for.
    setGuest(false);
    setAuthed(false);
    clearToasts();  // a previous session's failures must not greet the next user
  };

  /** Leave the demo for the public landing page (or its sign-in form). */
  const leaveDemo = (signIn: boolean) => {
    logout();
    window.history.replaceState(null, "", signIn ? "/?signin" : "/");
  };
  // The logo: a guest goes to the landing page (their demo is one click
  // back), a signed-in user goes to Today.
  const onLogo = () => {
    if (isGuest()) {
      closeAsk();
      window.history.pushState(null, "", "/");
      setAuthed(false);
    } else {
      go("today");
    }
  };

  if (!authed) return (
    <>
      <Landing onAuthed={() => setAuthed(true)} />
      <div className="el-login-theme-toggle">
        <ThemeToggle mode={theme} onChange={setTheme} compact />
      </div>
    </>
  );

  // Wait for the server to tell us which products exist before choosing a screen —
  // otherwise the wizard flashes on every refresh.
  if (!booted) {
    return (
      <div role="status" style={{ height: "100dvh", background: C.bg, color: C.dim, fontFamily: sans,
                    display: "flex", alignItems: "center", justifyContent: "center", fontSize: T.md,
                    gap: 12 }}>
        <Logo size={28} live decorative />
        Loading your workspace…
      </div>
    );
  }

  const { screen } = route;
  const caseId = route.id ?? null;
  const params = route.params ?? {};
  // Onboarding is an overlay, not a takeover. It used to replace the whole
  // window with the nav hidden, so arriving there with nothing to add — an
  // empty workspace, or no permission to create a product — was a dead end
  // with no way back. It now sits above the running app and can be dismissed.
  const onboarding = screen === "onboarding";
  const key = activeId ?? "none";
  const guest = isGuest();
  // Starting a case and importing reviews need reviewer access; a guest or a
  // viewer is not offered buttons the server would refuse.
  const canAct = canReview() && !guest && activeId != null;
  const askShortcut = /Mac|iPhone|iPad|iPod/.test(navigator.platform) ? "\u2318 K" : "Ctrl K";

  return (
    <>
    <div
      inert={askOpen ? true : undefined}
      className="el-shell"
      style={{
        display: "flex", flexDirection: "column",
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
      <AppHeader key={activeId ?? "none"} screen={screen} go={go} products={products} productId={activeId}
        onSwitchProduct={switchProduct} onLogo={onLogo} onAsk={openAsk} askShortcut={askShortcut}
        theme={theme} onThemeChange={setTheme} onLogout={guest ? () => leaveDemo(true) : logout}
        onAddProduct={() => navigate({ screen: "onboarding", productId: activeId })} liveKey={reloadKey} guest={guest}
        onRunInvestigation={canAct ? () => setNewCaseOpen(true) : undefined}
        onImportCsv={canAct ? () => go("sources", { import: "1" }) : undefined} />
      {guest && <div className="el-demo-banner" role="region" aria-label="Demo">
        <span>You're exploring the demo</span><span aria-hidden>·</span>
        <button type="button" onClick={() => leaveDemo(true)}>Sign in</button><span aria-hidden>·</span>
        <button type="button" onClick={() => leaveDemo(false)}>Exit demo</button>
      </div>}
      <main id="main-content" className="el-workspace">
        <ErrorBoundary // The tab is part of the key: a TraceTab that threw stayed broken when
          // you switched to Finding, because nothing in the key had changed.
          resetKey={`${screen}:${caseId}:${route.tab ?? ""}:${activeId}`} onGoHome={() => go("today")}>
          {/* Product-scoped screens remount per product so they re-fetch; the
              case detail is keyed by case id for the same reason. */}
          {/* `onboarding` renders Today underneath: the wizard is a layer over
              the running app now, so there has to be an app behind it. */}
          {(screen === "today" || onboarding) && (
            <Today
              key={key}
              productName={productName}
              onOpenCase={openCase}
              onGoCases={(tab) => go("cases", tab && tab !== "all" ? { tab } : undefined)}
              onGoSources={() => go("sources")}
              onGoPlan={() => go("plan")}
              onAddProduct={() => navigate({ screen: "onboarding", productId: activeId })}
              // A guest signing in is a sign-OUT of the guest visit: it clears
              // the guest flag and returns to the door.
              onSignIn={logout}
              reloadKey={reloadKey}
              bumpReload={bumpReload}
            />
          )}

          {screen === "cases" && (
            <Cases
              key={key}
              productName={productName}
              productId={activeId}
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
              onOpenCase={openCase}
              onReviewed={bumpReload}
              onGoCalibration={() => go("calibration")}
              onGoPatterns={() => go("patterns")}
            />
          )}

          {screen === "ask" && (
            <ScreenChunk>
              <Chat key={key} productName={productName} productId={activeId}
                    onOpenInvestigation={(id) => openCase(id, "resolved")} />
            </ScreenChunk>
          )}

          {screen === "sources" && (
            <ScreenChunk>
              <Sources key={key} productName={productName} openImport={params.import === "1"}
                       onAddProduct={() => navigate({ screen: "onboarding", productId: activeId })} />
            </ScreenChunk>
          )}

          {screen === "settings" && (
            <ScreenChunk>
              <Settings
                key={key}
                product={activeProduct}
                onGoCosts={() => setParams({ section: "costs" })}
                onGoSources={() => go("sources")}
                onAddProduct={() => navigate({ screen: "onboarding", productId: activeId })}
                onDeleteProduct={setDeleting}
                section={SETTINGS_SECTIONS.includes(params.section as SettingsSection)
                  ? params.section as SettingsSection : "general"}
                onSection={(section) => setParams({ section: section === "general" ? null : section })}
                onGoReview={() => go("cases", { tab: "needs-review" })}
              />
            </ScreenChunk>
          )}

          {/* Reached from within another screen rather than from the nav, so
              they carry a named Back instead of a nav highlight. */}
          {screen === "plan" && (
            <ScreenChunk>
              <Backlog key={key} onOpenInvestigation={openCase} onBack={back}
                       onGoCases={() => go("cases")}
                       backLabel={backTarget?.label ?? "Cases"} />
            </ScreenChunk>
          )}
          {/* Intelligence: the learned-patterns map and proven fixes, with
              calibration one click away. (The full hub replaces this.) */}
          {(screen === "intelligence" || screen === "memory") && (
            <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
              <div className="el-intel-link">
                <span>How often is EchoLens right when it says it is sure?</span>
                <button type="button" onClick={() => go("settings", { section: "calibration" })}>
                  See calibration in Settings <Icon name="arrowRight" size={13} />
                </button>
              </div>
              <ScreenChunk>
                <LearnedPatterns
                  key={key}
                  productName={productName}
                  view={LEARNED_VIEWS.includes(params.view as LearnedView) ? params.view as LearnedView : "map"}
                  onView={(view) => setParams({ view: view === "map" ? null : view })}
                  onOpenInvestigation={openCase}
                  onGoCases={() => go("cases")}
                />
              </ScreenChunk>
            </div>
          )}

          {screen === "portfolio" && (
            <ScreenChunk>
              <Portfolio
                onOpenProduct={switchProduct}
                onOpenInvestigation={(id) => openCase(id, "resolved")}
                onAddProduct={() => navigate({ screen: "onboarding", productId: activeId })}
              />
            </ScreenChunk>
          )}

          {onboarding && (
            <ScreenChunk fallback={null}>
              <Onboarding
                // Always dismissible. "Can I skip this?" is not the same question
                // as "does a product exist yet?" — the answer is always yes.
                canSkip
                onClose={closeOnboarding}
                onProductCreated={(id) => {
                  // Scope everything to the new product straight away.
                  createdProductRef.current = id;
                  setActiveProduct(id);
                  api.products().then((r) => setProducts(r.products)).catch(() => {});
                  api.activateProduct(id).catch(() => {});
                }}
                onCancel={() => {
                  closeOnboarding();
                }}
                onDone={() => finishOnboarding("today")}
                onReviewSignals={() => finishOnboarding("cases", { signals: "1" })}
                onManageSources={() => finishOnboarding("sources")}
              />
            </ScreenChunk>
          )}
        </ErrorBoundary>
      </main>

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
      {tourOpen && !onboarding && <FirstRunTour onClose={closeTour} />}
    </div>
    {askOpen && <AskDrawer productId={activeId} productName={productName} onClose={closeAsk}
      returnFocus={askReturnFocus.current}
      onOpenInvestigation={(id) => { closeAsk(); openCase(id); }} />}
    </>
  );

  /** Leaving the wizard: adopt the new product, then land where asked. */
  function finishOnboarding(target: Screen, extra?: Record<string, string>) {
    // Leave the wizard at once when the new product's id is known. Waiting for
    // the product list first meant the click did nothing visible for seconds on
    // a busy server (it is still saving the backfill), so people clicked again.
    const created = createdProductRef.current;
    if (created != null) {
      setActiveProduct(created);
      api.activateProduct(created).catch(() => {});
      bumpReload();
      navigate({ screen: target, productId: created, params: extra }, { replace: true });
      api.products().then((r) => {
        setProducts(r.products);
        if (r.products.length === 1 && !tourSeen()) setTourOpen(true);
      }).catch(() => {});
      return;
    }
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
      if (r.products.length === 1 && !tourSeen()) setTourOpen(true);
    }).catch(() => {
      // Without this the wizard sat on its completed state forever with no
      // feedback if the refresh failed.
      toast.fail("Couldn't load your new product — reload the page to continue.");
    });
  }
}
