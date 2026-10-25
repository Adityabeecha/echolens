import { useEffect, useRef, useState } from "react";
import { ProductRow, api, isAdmin, isGuest } from "../api";
import { plural } from "../format";
import { useAsync } from "../hooks";
import { Screen } from "../nav";
import { Icon, IconName } from "./Icon";
import { Logo } from "./Logo";
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
  /** The logo: the landing page for a guest, Today for a signed-in user. */
  onLogoClick?: () => void;
  /** Bumps when work starts or settles, so the live count refreshes. */
  liveKey?: number;
}

/**
 * The rail: what needs you, the work, what EchoLens has learned, then the
 * workspace. Every entry is always reachable — screens with nothing in them
 * yet explain themselves with an empty state rather than being locked away.
 */
interface NavItem { key: Screen; icon: IconName; label: string; hint: string }

const WORK: NavItem[] = [
  { key: "today", icon: "today", label: "Today", hint: "What needs you right now" },
  { key: "cases", icon: "cases", label: "Cases & Signals", hint: "Spikes, cases and what we found" },
  { key: "plan", icon: "shipped", label: "Quarter Plan", hint: "What to fix next, ranked by impact" },
  { key: "intelligence", icon: "patterns", label: "Intelligence", hint: "How this product breaks, and fixes proven to work" },
];

const WORKSPACE: NavItem[] = [
  { key: "portfolio", icon: "portfolio", label: "Portfolio", hint: "Every product you own, ranked" },
  { key: "sources", icon: "sources", label: "Sources", hint: "Where the feedback comes from" },
  { key: "settings", icon: "settings", label: "Settings", hint: "Budgets, limits, calibration and trackers" },
];

/** Screens reached from inside another; they light their parent. */
const PARENT: Partial<Record<Screen, Screen>> = {
  case: "cases", memory: "intelligence", patterns: "intelligence",
  calibration: "settings", costs: "settings",
};

/** Mobile bottom bar: four destinations and More. */
const MOBILE: NavItem[] = [
  WORK[0],
  { ...WORK[1], label: "Cases" },
  { ...WORK[2], label: "Plan" },
  { key: "ask", icon: "ask", label: "Ask", hint: "Ask about your feedback" },
];
const MORE: Screen[] = ["intelligence", "portfolio", "sources", "settings", "memory", "calibration", "costs"];

type Band = "healthy" | "watch" | "attention" | "on_fire";
const BAND_WORD: Record<Band, string> = {
  healthy: "healthy", watch: "worth watching", attention: "needs attention", on_fire: "needs you today",
};

export function Sidebar({
  screen, go, onLogout, products = [], activeId = null, onSwitchProduct, onAddProduct,
  theme, onThemeChange, collapsed, onCollapsedChange, onAsk, askShortcut = "Ctrl K",
  onLogoClick, liveKey = 0,
}: Props) {
  const guest = isGuest();
  const current = PARENT[screen] ?? screen;

  // What is ACTUALLY running, asked of the server; refreshed when the
  // workspace's work watcher sees something start or finish.
  const { data: live } = useAsync(() => api.investigations(), [activeId, liveKey]);
  const running = (live?.investigations ?? []).filter((i) => i.status === "running");

  // Health per product for the switcher's dots — the stored portfolio rows,
  // which the board already keeps fresh. A failure just means no dots.
  const { data: board } = useAsync(
    () => (products.length > 1 ? api.portfolio() : Promise.resolve(null)), [products.length, liveKey]);
  const health = new Map((board?.products ?? []).map((r) => [r.product_id, r]));

  const open = (key: Screen) => (key === "ask" && onAsk ? onAsk() : go(key));
  const askKeys = askShortcut.startsWith("⌘") ? "Meta+K" : "Control+K";

  return (
    <nav id="el-sidebar-navigation" aria-label="Main navigation"
      className={`el-sidebar el-rail${collapsed ? " is-collapsed" : ""}`}>
      <div className="el-rail__brand">
        <button type="button" className="el-rail__logo" onClick={onLogoClick}
                title={guest ? "EchoLens — back to the start page" : "EchoLens — Today"}
                aria-label={guest ? "EchoLens home page" : "Today"}>
          <Logo size={26} live={running.length > 0} decorative />
          <span className="el-rail__wordmark el-rail__label">EchoLens</span>
        </button>
        <button
          type="button"
          className="el-rail__collapse"
          onClick={() => onCollapsedChange(!collapsed)}
          aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
          title={collapsed ? "Expand navigation" : "Collapse navigation"}
          aria-expanded={!collapsed}
          aria-controls="el-sidebar-navigation"
        >
          <Icon name={collapsed ? "chevronRight" : "chevronLeft"} size={13} />
        </button>
      </div>

      {products.length > 0 && onSwitchProduct ? (
        <ProductSwitcher products={products} activeId={activeId} onSwitch={onSwitchProduct}
                         onAdd={onAddProduct} screen={screen} health={health} />
      ) : (
        /* No products: the only way in is to add one, so it is offered here
           (admins only — anyone else would be offered a button that 403s). */
        onAddProduct && isAdmin() ? (
          <button type="button" onClick={onAddProduct} className="el-rail__add">
            <Icon name="plus" size={14} />
            <span className="el-rail__label">Add a product</span>
          </button>
        ) : null
      )}

      <div className="el-rail__groups">
        <ul className="el-rail__list" aria-label="Work">
          {WORK.map((n) => (
            <li key={n.key}>
              <NavRow item={n} active={current === n.key} onClick={() => open(n.key)} />
            </li>
          ))}
        </ul>
        <div className="el-rail__rule" aria-hidden />
        <ul className="el-rail__list" aria-label="Workspace">
          {WORKSPACE.map((n) => (
            <li key={n.key}>
              <NavRow item={n} active={current === n.key} onClick={() => open(n.key)}
                      badge={n.key === "portfolio" && products.length > 1 ? String(products.length) : undefined} />
            </li>
          ))}
        </ul>
      </div>

      <div className="el-rail__spacer" />

      {running.length > 0 && (
        <button type="button" onClick={() => go("cases")} className="el-rail__live"
                title={`${running.length} ${plural(running.length, "investigation")} running — open Cases`}>
          <span className="el-rail__live-dot" aria-hidden />
          <span className="el-rail__label">
            <span className="el-rail__live-count">
              {running.length} {plural(running.length, "investigation")} running
            </span>
            <span className="el-rail__live-ids">
              {running.slice(0, 2).map((i) => `#${i.id}`).join(", ")}
              {running.length > 2 ? ` +${running.length - 2}` : ""}
            </span>
          </span>
        </button>
      )}

      <div className="el-rail__foot">
        <ThemeToggle mode={theme} onChange={onThemeChange} compact />
        {onLogout && (
          <button type="button" onClick={onLogout} className="el-rail__item el-rail__item--quiet"
                  title={guest ? "Sign in" : "Sign out"} aria-label={guest ? "Sign in" : "Sign out"}>
            <Icon name={guest ? "arrowRight" : "signout"} size={15} />
            <span className="el-rail__label">{guest ? "Sign in" : "Sign out"}</span>
          </button>
        )}
      </div>

      <div className="el-mobile-task-nav" aria-label="Primary navigation">
        {MOBILE.map((item) => {
          const active = current === item.key;
          return (
            <button
              key={`mobile-${item.key}`}
              type="button"
              data-tour={item.key}
              onClick={() => open(item.key)}
              className={active ? "is-active" : ""}
              aria-current={active ? "page" : undefined}
              aria-keyshortcuts={item.key === "ask" && onAsk ? askKeys : undefined}
            >
              <Icon name={item.icon} size={19} />
              <span>{item.label}</span>
            </button>
          );
        })}
        <button
          type="button"
          onClick={() => go("intelligence")}
          className={MORE.includes(screen) ? "is-active" : ""}
          aria-current={MORE.includes(screen) ? "page" : undefined}
          aria-label="More: intelligence, portfolio, sources and settings"
        >
          <Icon name="settings" size={19} />
          <span>More</span>
        </button>
      </div>
    </nav>
  );
}

function NavRow({ item, active, onClick, badge }: {
  item: NavItem; active: boolean; onClick: () => void; badge?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      data-tour={item.key}
      className={`el-rail__item${active ? " is-active" : ""}`}
      // The name leads the tooltip: in the icon-only rail it is the only place
      // the name is visible at all.
      title={`${item.label} — ${item.hint}`}
      aria-label={item.label}
      aria-current={active ? "page" : undefined}
    >
      <Icon name={item.icon} size={16} />
      <span className="el-rail__label">{item.label}</span>
      {badge && <span className="el-rail__badge el-rail__label">{badge}</span>}
    </button>
  );
}

// The active product scopes every screen, so it sits above the nav. Switching
// only: deleting lives in Settings → This product, behind its confirmation.
function ProductSwitcher({ products, activeId, onSwitch, onAdd, screen, health }: {
  products: ProductRow[]; activeId: number | null;
  onSwitch: (id: number) => void; onAdd?: () => void;
  screen: Screen;
  health: Map<number, { health: number; band: string }>;
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

  // Outside click and Escape close it wherever focus is.
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
  const dot = (id: number) => {
    const h = health.get(id);
    if (!h) return null;
    const band = (h.band in BAND_WORD ? h.band : "watch") as Band;
    return (
      <span className={`el-health-dot el-health-dot--${band}`}
            title={`Health ${Math.round(h.health)} of 100 — ${BAND_WORD[band]}`}>
        <span className="el-sr-only">Health {Math.round(h.health)} of 100, {BAND_WORD[band]}</span>
      </span>
    );
  };
  return (
    <div ref={rootRef} className="el-rail__switcher">
      <button
        ref={triggerRef}
        type="button"
        onClick={() => { openFocus.current = activeIndex; setOpen((o) => !o); }}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown" || e.key === "ArrowUp") {
            e.preventDefault();
            openFocus.current = e.key === "ArrowDown" ? activeIndex : products.length - 1;
            setOpen(true);
          }
        }}
        className="el-rail__product"
        aria-expanded={open}
        aria-haspopup="listbox"
        title={`Product: ${active.name}`}
      >
        <span className="el-rail__monogram" aria-hidden>
          {active.name.slice(0, 1).toUpperCase()}
          {dot(active.id)}
        </span>
        <span className="el-rail__label el-rail__product-text">
          <span className="el-truncate el-rail__product-name">{active.name}</span>
          <span className="el-rail__product-meta">{active.is_demo ? "Demo product" : "Product"}</span>
        </span>
        <Icon name={open ? "chevronUp" : "chevronDown"} size={14} className="el-rail__label" />
      </button>
      {open && (
        <div role="listbox" aria-label="Products" className="el-rail__menu"
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
          }}>
          {products.map((p, index) => (
            <div key={p.id}
              ref={(node) => { optionRefs.current[index] = node; }}
              role="option"
              aria-selected={p.id === activeId}
              tabIndex={index === focusIndex ? 0 : -1}
              className={`el-rail__option${p.id === activeId ? " is-active" : ""}`}
              onFocus={() => setFocusIndex(index)}
              onClick={() => { setOpen(false); if (p.id !== activeId) onSwitch(p.id); }}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault(); setOpen(false);
                  if (p.id !== activeId) onSwitch(p.id);
                }
              }}>
              {dot(p.id) ?? <span className="el-health-dot el-health-dot--none" aria-hidden />}
              <span className="el-truncate" style={{ flex: 1 }}>{p.name}</span>
              {health.get(p.id) && (
                <span className="el-num el-rail__option-health">{Math.round(health.get(p.id)!.health)}</span>
              )}
              {p.is_demo && <span className="el-product-tag">Demo</span>}
            </div>
          ))}
          {/* Admin-only: creating a product is an admin route. */}
          {onAdd && admin && (
            <button type="button" onClick={() => { setOpen(false); onAdd(); }} className="el-rail__option el-rail__option--add">
              <Icon name="plus" size={13} /> Add a product
            </button>
          )}
        </div>
      )}
    </div>
  );
}
