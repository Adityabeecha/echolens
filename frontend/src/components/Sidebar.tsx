import { useEffect, useRef, useState } from "react";
import { ProductRow, api, isAdmin } from "../api";
import { plural } from "../format";
import { useAsync } from "../hooks";
import { Screen } from "../nav";
import { C, R, S, T, mono } from "../theme";
import { Icon, IconName } from "./Icon";

interface Props {
  screen: Screen;
  go: (s: Screen) => void;
  onLogout?: () => void;
  products?: ProductRow[];
  activeId?: number | null;
  onSwitchProduct?: (id: number) => void;
  onAddProduct?: () => void;
  onDeleteProduct?: (p: ProductRow) => void;
}

// v8.0: the active product scopes every screen, so it sits above the nav.
function ProductSwitcher({ products, activeId, onSwitch, onAdd, onDelete }: {
  products: ProductRow[]; activeId: number | null;
  onSwitch: (id: number) => void; onAdd?: () => void;
  onDelete?: (p: ProductRow) => void;
}) {
  const admin = isAdmin();
  const [open, setOpen] = useState(false);
  const active = products.find((p) => p.id === activeId) ?? products[0];
  const activeIndex = Math.max(0, products.findIndex((p) => p.id === activeId));
  const [focusIndex, setFocusIndex] = useState(activeIndex);
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

  const focusOption = (index: number) => {
    const next = Math.max(0, Math.min(products.length - 1, index));
    setFocusIndex(next);
    optionRefs.current[next]?.focus();
  };
  if (!active) return null;
  return (
    <div className="el-nav-wide" style={{ position: "relative", margin: `0 ${S[3]} ${S[3]}` }}>
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
          <span style={{ display: "block", fontFamily: mono, fontSize: T.micro, color: C.faint,
                         letterSpacing: "var(--el-ls-wide)" }}>
            {active.is_demo ? "DEMO PRODUCT" : "ACTIVE PRODUCT"}
          </span>
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
              <span className="el-truncate" style={{ flex: 1 }}>
                {p.name}{p.is_demo ? "  ·  demo" : ""}
              </span>
              {admin && onDelete && (
                <button
                  title={`Delete ${p.name}`}
                  aria-label={`Delete ${p.name}`}
                  onClick={(e) => { e.stopPropagation(); setOpen(false); onDelete(p); }}
                  className="el-btn el-btn--sm"
                  style={{ color: C.dim, padding: 2, flex: "none" }}>
                  <Icon name="close" size={13} />
                </button>
              )}
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
  { key: "ask", icon: "ask", label: "Ask", hint: "Ask about your feedback" },
];

const SYSTEM: NavItem[] = [
  { key: "sources", icon: "sources", label: "Sources", hint: "Where the feedback comes from" },
  { key: "patterns", icon: "patterns", label: "Patterns", hint: "Fixes proven to work" },
  { key: "calibration", icon: "calibration", label: "Calibration", hint: "How accurate EchoLens has been" },
  { key: "costs", icon: "costs", label: "Costs", hint: "What each case cost to run" },
  { key: "settings", icon: "settings", label: "Settings", hint: "Budgets, limits and this product" },
];

const SYSTEM_KEYS = SYSTEM.map((n) => n.key);
/** Screens reached from within another screen; they highlight their parent. */
const UNDER_CASES: Screen[] = ["cases", "case"];
const UNDER_TODAY: Screen[] = ["today", "plan"];
const UNDER_PATTERNS: Screen[] = ["patterns", "memory"];

export function Sidebar({
  screen, go, onLogout, products = [], activeId = null,
  onSwitchProduct, onAddProduct, onDeleteProduct
}: Props) {
  const admin = isAdmin();
  // The System group opens itself when you are inside it, so you are never on a
  // screen the nav claims you are not on.
  const [systemOpen, setSystemOpen] = useState(false);
  const inSystem = SYSTEM_KEYS.includes(screen) || screen === "memory";
  const showSystem = systemOpen || inSystem;

  // What is ACTUALLY running, asked of the server.
  // Deps are the PRODUCT only. `screen` in here meant clicking through the five
  // System nav items fired five identical /investigations requests in a second,
  // and the component is keyed on the product anyway.
  const { data: live } = useAsync(() => api.investigations(), [activeId]);
  const running = (live?.investigations ?? []).filter((i) => i.status === "running");

  const isActive = (key: Screen) => {
    if (key === "cases") return UNDER_CASES.includes(screen);
    if (key === "today") return UNDER_TODAY.includes(screen);
    if (key === "patterns") return UNDER_PATTERNS.includes(screen);
    return screen === key;
  };

  return (
    <nav aria-label="Main"
      style={{ width: "var(--el-sidebar-w)", flex: "none", display: "flex",
               flexDirection: "column", borderRight: `1px solid ${C.border}`,
               background: C.bgRaised }}>
      <div className="el-nav-brand"
           style={{ display: "flex", alignItems: "center", gap: S[3],
                    padding: `${S[5]} ${S[4]} ${S[4]}` }}>
        <span style={{ width: 26, height: 26, borderRadius: "50%",
                      border: `2px solid ${C.accent}`, position: "relative", flex: "none" }}>
          <span style={{ position: "absolute", inset: 5, borderRadius: "50%",
                        background: `radial-gradient(circle at 35% 35%, ${C.accentHi}, ${C.accentDeep})` }} />
        </span>
        <span>
          <span style={{ display: "block", fontWeight: 700, fontSize: T.md,
                         letterSpacing: "var(--el-ls-tight)", color: C.text }}>EchoLens</span>
          <span style={{ display: "block", fontFamily: mono, fontSize: T.micro, color: C.faint,
                         letterSpacing: "var(--el-ls-wide)" }}>
            FEEDBACK FORENSICS
          </span>
        </span>
      </div>

      {/* The portfolio spans every product, so it sits ABOVE the switcher — the
          switcher scopes what's below it, not this. */}
      {products.length > 1 && (
        <button
          onClick={() => go("portfolio")}
          className="el-btn"
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
                         onDelete={onDeleteProduct} />
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
        {PRIMARY.map((n) => (
          <NavRow key={n.key} item={n} active={isActive(n.key)} onClick={() => go(n.key)} />
        ))}
      </div>

      <div className="el-nav-spacer" style={{ flex: 1 }} />

      {running.length > 0 && (
        <button
          onClick={() => go("today")}
          className="el-btn el-nav-wide"
          style={{ margin: `${S[3]} ${S[3]} ${S[1]}`, padding: `${S[2]} ${S[3]}`,
                   border: `1px solid ${C.border2}`, borderRadius: R.control,
                   background: C.card, flexDirection: "column", alignItems: "flex-start",
                   gap: S[1] }}
        >
          <span style={{ display: "flex", alignItems: "center", gap: S[2] }}>
            <span style={{ width: 7, height: 7, borderRadius: "50%", background: C.accent,
                          animation: "elPulse 1.6s infinite", flex: "none" }} />
            <span style={{ fontSize: T.sm, color: C.text3 }}>
              {running.length} {plural(running.length, "investigation")} running
            </span>
          </span>
          <span className="el-mono el-truncate" style={{ fontSize: T.xs, color: C.accent,
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
          title="Sources, patterns, calibration, costs and settings"
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
        <div className="el-nav-system"
             style={{ display: showSystem ? "flex" : "none", flexDirection: "column", gap: 0 }}>
          {SYSTEM.map((n) => (
            <NavRow key={n.key} item={n} active={isActive(n.key)} small
                    onClick={() => go(n.key)} />
          ))}
        </div>
      </div>

      {onLogout && (
        <button
          onClick={onLogout}
          className="el-btn"
          title="Sign out"
          style={{ margin: `${S[1]} ${S[3]} ${S[3]}`, padding: `${S[2]} ${S[2]}`,
                   borderRadius: R.control, color: C.muted, fontSize: T.sm,
                   justifyContent: "flex-start", gap: S[3] }}
        >
          <Icon name="signout" size={15} style={{ color: C.dim }} />
          <span className="el-nav-label">Sign out</span>
        </button>
      )}
    </nav>
  );
}

function NavRow({ item, active, onClick, small }: {
  item: NavItem; active: boolean; onClick: () => void; small?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      className="el-btn"
      title={item.hint}
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
      <span className="el-nav-label">{item.label}</span>
    </button>
  );
}
