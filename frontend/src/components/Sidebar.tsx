import { useEffect, useRef, useState } from "react";
import { ProductRow, api, isAdmin, isGuest } from "../api";
import { plural } from "../format";
import { useAsync } from "../hooks";
import { Screen } from "../nav";
import { C, R, S, T, mono } from "../theme";
import { Icon, IconName } from "./Icon";
import { ThemeMode } from "../themeMode";
import { ThemeToggle } from "./ThemeToggle";

interface Props {
  screen: Screen;
  go: (s: Screen) => void;
  onLogout?: () => void;
  onAsk?: () => void;
  askShortcut?: string;
  products?: ProductRow[];
  activeId?: number | null;
  onSwitchProduct?: (id: number) => void;
  onAddProduct?: () => void;
  /** Unused: deleting a product lives in Settings → This product, behind its
   *  confirmation. Kept so callers that still pass it compile. */
  onDeleteProduct?: (p: ProductRow) => void;
  theme: ThemeMode;
  onThemeChange: (theme: ThemeMode) => void;
  collapsed: boolean;
  onCollapsedChange: (collapsed: boolean) => void;
}

// v8.0: the active product scopes every screen, so it sits above the nav.
//
// Switching only. It used to carry an inline × per product, one slip from the
// destructive action sitting next to the most-used one; deleting now lives in
// Settings → This product, behind its confirmation.
function ProductSwitcher({ products, activeId, onSwitch, onAdd, screen }: {
  products: ProductRow[]; activeId: number | null;
  onSwitch: (id: number) => void; onAdd?: () => void;
  screen: Screen;
}) {
  const admin = isAdmin();
  const [open, setOpen] = useState(false);
  const active = products.find((p) => p.id === activeId) ?? products[0];
  const activeIndex = Math.max(0, products.findIndex((p) => p.id === activeId));
  const [focusIndex, setFocusIndex] = useState(activeIndex);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const optionRefs = useRef<Array<HTMLDivElement | null>>([]);
  const openFocus = useRef(activeIndex);

  useEffect(() => {
    if (!open) return;
    const index = openFocus.current;
    setFocusIndex(index);
    const frame = requestAnimationFrame(() => optionRefs.current[index]?.focus());
    return () => cancelAnimationFrame(frame);
  }, [open, activeIndex]);

  // A menu left open across navigation floated over the next screen.
  useEffect(() => { setOpen(false); }, [screen]);

  // Outside click and Escape close it wherever focus is, not only from inside
  // the list (a mouse user's focus is usually still on the page).
  useEffect(() => {
    if (!open) return;
    const onPointer = (e: PointerEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.preventDefault();
      setOpen(false);
      triggerRef.current?.focus();
    };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const focusOption = (index: number) => {
    const next = Math.max(0, Math.min(products.length - 1, index));
    setFocusIndex(next);
    optionRefs.current[next]?.focus();
  };
  if (!active) return null;
  return (
    <div ref={rootRef} className="el-nav-wide el-product-switcher" style={{ position: "relative", margin: `0 ${S[3]} ${S[3]}` }}>
      <button
        ref={triggerRef}
        onClick={() => { openFocus.current = activeIndex; setOpen((o) => !o); }}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown" || e.key === "ArrowUp") {
            e.preventDefault();
            openFocus.current = e.key === "ArrowDown" ? activeIndex : products.length - 1;
            setOpen(true);
          }
        }}
        className="el-btn"
        aria-expanded={open}
        aria-haspopup="listbox"
        style={{ display: "flex", alignItems: "center", gap: S[2], padding: S[2],
                 width: "100%", borderRadius: R.control, background: C.card,
                 border: `1px solid ${C.border3}`, textAlign: "left" }}
      >
        <span style={{ width: 22, height: 22, borderRadius: R.sm, background: C.bgRaised,
                      border: `1px solid ${C.border4}`, display: "grid", placeItems: "center",
                      fontFamily: mono, fontSize: T.micro, fontWeight: 600, color: C.accent,
                      flex: "none" }}>
          {active.name.slice(0, 1).toUpperCase()}
        </span>
        <span style={{ minWidth: 0, flex: 1 }}>
          <span className="el-truncate" style={{ display: "block", fontSize: T.sm,
                        fontWeight: 600, color: C.text }}>{active.name}</span>
          {active.is_demo ? (
            <span className="el-product-tag">Demo product</span>
          ) : (
            <span style={{ display: "block", fontFamily: mono, fontSize: T.micro, color: C.faint,
                           letterSpacing: "var(--el-ls-wide)" }}>
              ACTIVE PRODUCT
            </span>
          )}
        </span>
        <Icon name={open ? "chevronUp" : "chevronDown"} size={14} style={{ color: C.dim }} />
      </button>
      {open && (
        <div role="listbox" aria-label="Products"
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.preventDefault(); setOpen(false); triggerRef.current?.focus();
            } else if (e.key === "ArrowDown") {
              e.preventDefault(); focusOption((focusIndex + 1) % products.length);
            } else if (e.key === "ArrowUp") {
              e.preventDefault(); focusOption((focusIndex - 1 + products.length) % products.length);
            } else if (e.key === "Home") {
              e.preventDefault(); focusOption(0);
            } else if (e.key === "End") {
              e.preventDefault(); focusOption(products.length - 1);
            }
          }}
          style={{ position: "absolute", top: "100%", left: 0, right: 0,
                      marginTop: S[1], zIndex: 20, background: C.card,
                      border: `1px solid ${C.border3}`, borderRadius: R.control,
                      boxShadow: "var(--el-e3)", overflow: "hidden" }}>
          {products.map((p, index) => (
            <div key={p.id} className="el-row el-row--click"
              ref={(node) => { optionRefs.current[index] = node; }}
              role="option"
              aria-selected={p.id === activeId}
              tabIndex={index === focusIndex ? 0 : -1}
              onFocus={() => setFocusIndex(index)}
              onClick={() => { setOpen(false); if (p.id !== activeId) onSwitch(p.id); }}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault(); setOpen(false);
                  if (p.id !== activeId) onSwitch(p.id);
                }
              }}
              style={{ display: "flex", alignItems: "center", gap: S[2],
                       padding: `${S[2]} ${S[3]}`, fontSize: T.sm,
                       color: p.id === activeId ? C.accent : C.text2,
                       background: p.id === activeId ? C.hover : "transparent" }}>
              <span className="el-truncate" style={{ flex: 1 }}>{p.name}</span>
              {p.is_demo && <span className="el-product-tag">Demo product</span>}
            </div>
          ))}
          {/* Admin-only: creating a product is an admin route, so offering it
              to a guest or viewer is offering a button the server refuses. */}
          {onAdd && admin && (
            <button onClick={() => { setOpen(false); onAdd(); }}
              className="el-btn"
              style={{ padding: `${S[2]} ${S[3]}`, fontSize: T.sm, color: C.muted,
                       width: "100%", justifyContent: "flex-start",
                       borderRadius: 0, borderTop: `1px solid ${C.border}` }}>
              <Icon name="plus" size={13} /> Add a product
            </button>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * Three questions, then the machine room.
 *
 * Nine flat nav items made you learn EchoLens's pipeline before you could find
 * anything, and several of them opened onto screens that were empty until the
 * system had earned their content. What is left in the primary group is what a
 * PM actually arrives wanting: what needs me, show me the work, let me ask.
 * Everything about how EchoLens itself is running lives in a collapsed System
 * group where it can be found without competing for attention.
 */
interface NavItem { key: Screen; icon: IconName; label: string; hint: string }

const PRIMARY: NavItem[] = [
  { key: "today", icon: "today", label: "Today", hint: "What needs you right now" },
  { key: "cases", icon: "cases", label: "Cases", hint: "Every case, from queued to verified" },
  { key: "plan", icon: "shipped", label: "Plan", hint: "What to fix next, ranked by impact" },
  { key: "ask", icon: "ask", label: "Ask", hint: "Ask about your feedback" },
];

// Four, not six. Patterns and Product memory were two halves of one answer —
// "what has EchoLens learned?" — so they are tabs of Learned patterns now, and
// Calibration ("is it right as often as it claims?") is a section of Settings.
// Old links to either are rewritten in nav.ts, so nothing 404s.
const SYSTEM: NavItem[] = [
  { key: "sources", icon: "sources", label: "Sources", hint: "Where the feedback comes from" },
  { key: "memory", icon: "patterns", label: "Learned patterns", hint: "How this product breaks, and fixes proven to work" },
  { key: "costs", icon: "costs", label: "Costs", hint: "What each case cost to run" },
  { key: "settings", icon: "settings", label: "Settings", hint: "Budgets, limits, calibration and trackers" },
];

const SYSTEM_KEYS = SYSTEM.map((n) => n.key);
/** Screens reached from within another screen; they highlight their parent. */
const UNDER_CASES: Screen[] = ["cases", "case"];

/** Screens that are empty until EchoLens has resolved something. */
type Lockable = "memory" | "plan";
const UNLOCK_HINT = "Unlocks after your first resolved case";

/**
 * Whether each learning screen has anything to show yet, from the endpoints
 * those screens already read. Fails OPEN: a request that errors, or a server
 * too old to answer, leaves the entry in the nav — a hiccup must never hide a
 * screen that has content.
 */
async function learningUnlocks(): Promise<Record<Lockable, boolean>> {
  const has = <R,>(p: Promise<R>, pick: (r: R) => boolean) => p.then(pick, () => true);
  const [patterns, brain, plan] = await Promise.all([
    has(api.patterns(), (r) => (r.patterns ?? []).length > 0),
    has(api.brain(), (r) => (r.edges ?? []).length > 0),
    // Open problems and feature requests together: the plan ranks both.
    has(api.backlogPlan(undefined, "all"), (r) => r.counts
      ? r.counts.bugs + r.counts.requests > 0
      : r.proposed.length + r.deferred.length > 0),
  ]);
  return { memory: patterns || brain, plan };
}

export function Sidebar({
  screen, go, onLogout, products = [], activeId = null,
  onSwitchProduct, onAddProduct, theme, onThemeChange,
  collapsed, onCollapsedChange, onAsk, askShortcut = "Ctrl K"
}: Props) {
  const admin = isAdmin();
  // The System group opens itself when you are inside it, so you are never on a
  // screen the nav claims you are not on.
  const [systemOpen, setSystemOpen] = useState(false);
  const inSystem = SYSTEM_KEYS.includes(screen);
  const guest = isGuest();
  const showSystem = systemOpen || inSystem;

  // What is ACTUALLY running, asked of the server.
  // Deps are the PRODUCT only. `screen` in here meant clicking through the five
  // System nav items fired five identical /investigations requests in a second,
  // and the component is keyed on the product anyway.
  const { data: live } = useAsync(() => api.investigations(), [activeId]);
  const running = (live?.investigations ?? []).filter((i) => i.status === "running");

  // Day one: Learned patterns and Plan have nothing in them yet. Without a
  // product there is nothing to ask about, so everything stays as it is.
  const { data: unlocks } = useAsync(
    () => (activeId == null ? Promise.resolve(null) : learningUnlocks()), [activeId]);
  // Never lock the screen you are on: the nav must not deny where you are.
  const locked = (key: Screen) =>
    (key === "memory" || key === "plan") && unlocks != null && !unlocks[key] && screen !== key;

  const isActive = (key: Screen) => {
    if (key === "cases") return UNDER_CASES.includes(screen);
    return screen === key;
  };
  // "Ask" opens the drawer over whatever you are reading; the full page is
  // still at its URL and one click away inside the drawer.
  const open = (key: Screen) => (key === "ask" && onAsk ? onAsk() : go(key));
  const askKeys = askShortcut.startsWith("⌘") ? "Meta+K" : "Control+K";

  return (
    <nav id="el-sidebar-navigation" aria-label="Main"
      className={`el-sidebar${collapsed ? " is-user-collapsed" : ""}`}
      style={{ width: "var(--el-sidebar-w)", flex: "none", display: "flex",
               flexDirection: "column", borderRight: `1px solid ${C.border}`,
               background: C.bgRaised }}>
      <div className="el-nav-brand"
           style={{ display: "flex", alignItems: "center", gap: S[3],
                    padding: `${S[5]} ${S[4]} ${S[4]}` }}>
        <span className="el-brand-mark" aria-hidden>
          <span />
        </span>
        <span>
          <span className="el-brand-name" style={{ display: "block", fontWeight: 700, fontSize: T.md,
                         letterSpacing: "var(--el-ls-tight)", color: C.text }}>EchoLens</span>
          <span style={{ display: "block", fontFamily: mono, fontSize: T.micro, color: C.faint,
                         letterSpacing: "var(--el-ls-wide)" }}>
            FEEDBACK FORENSICS
          </span>
        </span>
        <button
          type="button"
          className="el-sidebar-collapse"
          onClick={() => onCollapsedChange(!collapsed)}
          aria-label={collapsed ? "Open navigation panel" : "Close navigation panel"}
          title={collapsed ? "Open navigation panel" : "Close navigation panel"}
          aria-expanded={!collapsed}
          aria-controls="el-sidebar-navigation"
        >
          <Icon name={collapsed ? "chevronRight" : "chevronLeft"} size={13} />
        </button>
      </div>

      {/* The portfolio spans every product, so it sits ABOVE the switcher — the
          switcher scopes what's below it, not this. */}
      {products.length > 0 && (
        <button
          onClick={() => go("portfolio")}
          className="el-btn el-nav-wide"
          title="Every product you own, ranked"
          aria-current={screen === "portfolio" ? "page" : undefined}
          style={{ display: "flex", alignItems: "center", gap: S[3],
                   margin: `0 ${S[3]} ${S[2]}`, padding: `${S[2]} ${S[2]}`,
                   borderRadius: R.control, justifyContent: "flex-start",
                   background: screen === "portfolio" ? C.active : "transparent",
                   color: screen === "portfolio" ? C.text : C.muted }}
        >
          <Icon name="portfolio" size={15}
                style={{ color: screen === "portfolio" ? C.accent : C.dim }} />
          <span className="el-nav-label" style={{ fontSize: T.base }}>All products</span>
          <span className="el-num" style={{ marginLeft: "auto", fontSize: T.micro,
                         color: C.faint }}>
            {products.length}
          </span>
        </button>
      )}

      {products.length > 0 && onSwitchProduct ? (
        <ProductSwitcher products={products} activeId={activeId}
                         onSwitch={onSwitchProduct} onAdd={onAddProduct}
                         screen={screen} />
      ) : (
        /* With no products the switcher has nothing to switch between, so it
           used to render nothing at all — taking the only "Add a product"
           button in the app with it. An admin who dismissed onboarding was
           then left with an empty app and no way back into it. */
        onAddProduct && admin ? (
          <button
            onClick={onAddProduct}
            className="el-btn el-btn--ghost el-nav-wide"
            style={{ margin: `0 ${S[3]} ${S[3]}`, width: `calc(100% - 2 * ${S[3]})` }}
          >
            <Icon name="plus" size={14} />
            Add a product
          </button>
        ) : null
      )}

      <div className="el-nav-primary"
           style={{ display: "flex", flexDirection: "column", gap: 2,
                    padding: `0 ${S[3]}`, overflow: "auto" }}>
        {PRIMARY.map((n) => locked(n.key) ? (
          <LockedRow key={n.key} item={n} />
        ) : (
          <NavRow key={n.key} item={n} active={isActive(n.key)} onClick={() => open(n.key)}
                  shortcut={n.key === "ask" && onAsk ? { label: askShortcut, keys: askKeys } : undefined} />
        ))}
      </div>

      <div className="el-nav-spacer" style={{ flex: 1 }} />

      {running.length > 0 && (
        <button
          onClick={() => go("today")}
          className="el-btn el-nav-wide el-nav-live"
          style={{ margin: `${S[3]} ${S[3]} ${S[1]}`, padding: `${S[2]} ${S[3]}`,
                   border: `1px solid ${C.border2}`, borderRadius: R.control,
                   background: C.card, flexDirection: "column", alignItems: "flex-start",
                   gap: S[1] }}
        >
          <span style={{ display: "flex", alignItems: "center", gap: S[2] }}>
            <span className="el-nav-live__dot" style={{ width: 7, height: 7, borderRadius: "50%",
                          animation: "elPulse 1.6s infinite", flex: "none" }} />
            <span className="el-nav-live__count" style={{ fontSize: T.sm, fontWeight: 500 }}>
              {running.length} {plural(running.length, "investigation")} running
            </span>
          </span>
          <span className="el-mono el-truncate el-nav-live__ids" style={{ fontSize: T.xs,
                        marginLeft: 15, maxWidth: "100%" }}>
            {running.slice(0, 2).map((i) => `case #${i.id}`).join(", ")}
            {running.length > 2 ? ` +${running.length - 2}` : ""}
          </span>
        </button>
      )}

      {/* System: how EchoLens itself is running. Collapsed, small, findable. */}
      <div className="el-nav-system-group" style={{ padding: `${S[2]} ${S[3]} ${S[1]}` }}>
        <button
          onClick={() => setSystemOpen((o) => !o)}
          className="el-btn el-btn--sm el-nav-system-toggle"
          title="System: sources, learned patterns, costs and settings"
          aria-label="System"
          aria-expanded={showSystem}
          style={{ display: "flex", alignItems: "center", gap: S[2],
                   padding: `${S[1]} ${S[2]}`, width: "100%", justifyContent: "flex-start",
                   fontFamily: mono, fontSize: T.micro,
                   letterSpacing: "var(--el-ls-wide)", color: C.ghost }}
        >
          <Icon name={showSystem ? "chevronDown" : "chevronRight"} size={12} />
          <span className="el-nav-label">SYSTEM</span>
        </button>
        {/* Always rendered; the disclosure is CSS. On a phone the nav is a
            scrolling icon bar where a collapsed group would simply hide five
            screens, so `.el-nav-system` is shown there and the toggle hidden. */}
        <div className={`el-nav-system${showSystem ? " is-open" : ""}`}
             style={{ display: showSystem ? "flex" : "none", flexDirection: "column", gap: 0 }}>
          {SYSTEM.map((n) => locked(n.key) ? (
            <LockedRow key={n.key} item={n} small />
          ) : (
            <NavRow key={n.key} item={n} active={isActive(n.key)} small
                    onClick={() => go(n.key)} />
          ))}
        </div>
      </div>

      <ThemeToggle mode={theme} onChange={onThemeChange} />

      {onLogout && (
        <button
          onClick={onLogout}
          className="el-btn"
          title={guest ? "Sign in" : "Sign out"}
          aria-label={guest ? "Sign in" : "Sign out"}
          style={{ margin: `${S[1]} ${S[3]} ${S[3]}`, padding: `${S[2]} ${S[2]}`,
                   borderRadius: R.control, color: C.muted, fontSize: T.sm,
                   justifyContent: "flex-start", gap: S[3] }}
        >
          <Icon name={guest ? "arrowRight" : "signout"} size={15} style={{ color: C.dim }} />
          <span className="el-nav-label">{guest ? "Sign in" : "Sign out"}</span>
        </button>
      )}

      <div className="el-mobile-task-nav" aria-label="Primary navigation">
        {PRIMARY.map((item) => (
          <button
            key={`mobile-${item.key}`}
            type="button"
            data-tour={item.key}
            onClick={() => open(item.key)}
            className={isActive(item.key) ? "is-active" : ""}
            aria-current={isActive(item.key) ? "page" : undefined}
            aria-keyshortcuts={item.key === "ask" && onAsk ? askKeys : undefined}
          >
            <Icon name={item.icon} size={19} />
            <span>{item.label}</span>
          </button>
        ))}
        <button
          type="button"
          onClick={() => go("sources")}
          className={inSystem ? "is-active" : ""}
          aria-label="More: sources and system settings"
        >
          <Icon name="settings" size={19} />
          <span>More</span>
        </button>
      </div>
    </nav>
  );
}

function NavRow({ item, active, onClick, small, shortcut }: {
  item: NavItem; active: boolean; onClick: () => void; small?: boolean;
  /** Shown beside the label, e.g. "Ctrl K"; `keys` is the aria-keyshortcuts value. */
  shortcut?: { label: string; keys: string };
}) {
  return (
    <button
      onClick={onClick}
      data-tour={item.key}
      className={`el-btn el-nav-item${small ? " el-nav-item--small" : ""}${active ? " el-nav-item--active" : ""}`}
      // The name leads the tooltip: in the icon-only rail (collapsed, or under
      // 1200px) it is the only place the name is visible at all.
      title={`${item.label}${shortcut ? ` (${shortcut.label})` : ""} — ${item.hint}`}
      aria-label={item.label}
      aria-keyshortcuts={shortcut?.keys}
      aria-current={active ? "page" : undefined}
      style={{
        display: "flex", alignItems: "center", gap: S[3],
        padding: small ? `${S[1]} ${S[2]}` : `${S[2]} ${S[2]}`,
        borderRadius: R.control, justifyContent: "flex-start",
        background: active ? C.active : "transparent",
        color: active ? C.text : C.muted,
        fontSize: small ? T.sm : T.base,
        fontWeight: active ? 500 : 400,
        position: "relative"
      }}
    >
      {/* The active marker is a rail, not just a colour — colour alone is not a
          reliable state indicator. */}
      {active && (
        <span aria-hidden style={{ position: "absolute", left: 0, top: 6, bottom: 6,
                     width: 2, borderRadius: R.pill, background: C.accent }} />
      )}
      <Icon name={item.icon} size={small ? 14 : 16}
            style={{ color: active ? C.accent : C.dim }} />
      {/* Wrapped, not a bare text node, so the collapsed-sidebar breakpoint can
          hide the label without also blanking the icon or the accessible name. */}
      <span className="el-nav-label">
        {item.label}
        {shortcut && <kbd className="el-nav-kbd">{shortcut.label}</kbd>}
      </span>
    </button>
  );
}

/** A learning screen that has nothing yet: named, quiet, not clickable. */
function LockedRow({ item, small }: { item: NavItem; small?: boolean }) {
  return (
    <div className="el-nav-locked" data-tour={item.key}
         title={`${item.label} — ${UNLOCK_HINT.toLowerCase()}`}
         aria-label={`${item.label}: ${UNLOCK_HINT.toLowerCase()}`} role="note">
      <Icon name={item.icon} size={small ? 14 : 16} />
      <span className="el-nav-label">
        {item.label}
        <small>{UNLOCK_HINT}</small>
      </span>
    </div>
  );
}
