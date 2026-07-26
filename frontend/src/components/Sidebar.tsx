import { useState } from "react";
import { ProductRow, api, isAdmin } from "../api";
import { plural } from "../format";
import { useAsync } from "../hooks";
import { Screen } from "../nav";
import { C, mono } from "../theme";

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
  if (!active) return null;
  return (
    <div style={{ position: "relative", margin: "0 10px 12px" }}>
      <div
        onClick={() => setOpen((o) => !o)}
        className="el-btn"
        role="button"
        tabIndex={0}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") setOpen((o) => !o); }}
        style={{ display: "flex", alignItems: "center", gap: 9, padding: "9px 11px",
                 borderRadius: 8, background: C.card, border: `1px solid ${C.border3}`,
                 cursor: "pointer" }}
      >
        <div style={{ width: 20, height: 20, borderRadius: 5, background: C.hover,
                      border: `1px solid ${C.border4}`, display: "flex", alignItems: "center",
                      justifyContent: "center", fontFamily: mono, fontSize: 10, color: C.accent,
                      flex: "none" }}>
          {active.name.slice(0, 1).toUpperCase()}
        </div>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontSize: 12.5, fontWeight: 600, color: C.text, overflow: "hidden",
                        textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{active.name}</div>
          <div style={{ fontFamily: mono, fontSize: 9, color: C.faint, letterSpacing: ".06em" }}>
            {active.is_demo ? "DEMO PRODUCT" : "ACTIVE PRODUCT"}
          </div>
        </div>
        <span style={{ color: C.faint, fontSize: 10 }}>{open ? "▲" : "▼"}</span>
      </div>
      {open && (
        <div style={{ position: "absolute", top: "100%", left: 0, right: 0, marginTop: 4,
                      zIndex: 20, background: C.card2, border: `1px solid ${C.border3}`,
                      borderRadius: 8, boxShadow: "0 16px 40px rgba(0,0,0,.5)",
                      overflow: "hidden" }}>
          {products.map((p) => (
            <div key={p.id}
              onClick={() => { setOpen(false); if (p.id !== activeId) onSwitch(p.id); }}
              className="el-row"
              style={{ display: "flex", alignItems: "center", gap: 8, padding: "9px 12px",
                       cursor: "pointer", fontSize: 12.5,
                       color: p.id === activeId ? C.accent : C.text2,
                       background: p.id === activeId ? C.hover : "transparent" }}>
              <span style={{ flex: 1, minWidth: 0, overflow: "hidden",
                             textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {p.name}{p.is_demo ? "  ·  demo" : ""}
              </span>
              {admin && onDelete && (
                <span
                  title={`Delete ${p.name}`}
                  aria-label={`Delete ${p.name}`}
                  role="button"
                  tabIndex={0}
                  onClick={(e) => { e.stopPropagation(); setOpen(false); onDelete(p); }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.stopPropagation(); setOpen(false); onDelete(p);
                    }
                  }}
                  className="el-btn"
                  style={{ fontFamily: mono, fontSize: 12, color: C.faint, cursor: "pointer",
                           padding: "0 3px", flex: "none" }}>
                  ×
                </span>
              )}
            </div>
          ))}
          {onAdd && (
            <div onClick={() => { setOpen(false); onAdd(); }} className="el-row"
              style={{ padding: "9px 12px", cursor: "pointer", fontSize: 12.5, color: C.muted,
                       borderTop: `1px solid ${C.border}` }}>
              + Add a product
            </div>
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
interface NavItem { key: Screen; icon: string; label: string; hint: string }

const PRIMARY: NavItem[] = [
  { key: "today", icon: "◉", label: "Today", hint: "What needs you right now" },
  { key: "cases", icon: "▤", label: "Cases", hint: "Every case, from queued to verified" },
  { key: "ask", icon: "✦", label: "Ask", hint: "Ask about your feedback" },
];

const SYSTEM: NavItem[] = [
  { key: "sources", icon: "⇄", label: "Sources", hint: "Where the feedback comes from" },
  { key: "patterns", icon: "❖", label: "Patterns", hint: "Fixes proven to work" },
  { key: "calibration", icon: "◑", label: "Calibration", hint: "How accurate EchoLens has been" },
  { key: "costs", icon: "$", label: "Costs", hint: "What each case cost to run" },
  { key: "settings", icon: "⚙", label: "Settings", hint: "Budgets, limits and this product" },
];

const SYSTEM_KEYS = SYSTEM.map((n) => n.key);
/** Screens reached from within another screen; they highlight their parent. */
const UNDER_CASES: Screen[] = ["cases", "case"];
const UNDER_TODAY: Screen[] = ["today", "plan"];
const UNDER_PATTERNS: Screen[] = ["patterns", "memory"];

export function Sidebar({
  screen, go, onLogout, products = [], activeId = null,
  onSwitchProduct, onAddProduct, onDeleteProduct,
}: Props) {
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
    <div style={{ width: 216, flex: "none", display: "flex", flexDirection: "column",
                  borderRight: `1px solid ${C.border}`, background: C.bgRaised }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "18px 18px 16px" }}>
        <div style={{ width: 26, height: 26, borderRadius: "50%", border: `2px solid ${C.accent}`,
                      position: "relative", flex: "none" }}>
          <div style={{ position: "absolute", inset: 5, borderRadius: "50%",
                        background: "radial-gradient(circle at 35% 35%, #f7bd6a, #b06f1a)" }} />
        </div>
        <div>
          <div style={{ fontWeight: 700, fontSize: 15, letterSpacing: ".02em" }}>EchoLens</div>
          <div style={{ fontFamily: mono, fontSize: 9.5, color: C.faint, letterSpacing: ".08em" }}>
            FEEDBACK FORENSICS
          </div>
        </div>
      </div>

      {/* The portfolio spans every product, so it sits ABOVE the switcher — the
          switcher scopes what's below it, not this. */}
      {products.length > 1 && (
        <div
          onClick={() => go("portfolio")}
          className="el-btn"
          role="button"
          tabIndex={0}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") go("portfolio"); }}
          style={{ display: "flex", alignItems: "center", gap: 10, margin: "0 10px 8px",
                   padding: "8px 11px", borderRadius: 8, cursor: "pointer",
                   background: screen === "portfolio" ? C.active : "transparent",
                   border: `1px solid ${screen === "portfolio" ? C.border3 : "transparent"}`,
                   color: screen === "portfolio" ? C.text : C.muted }}
        >
          <span style={{ fontFamily: mono, fontSize: 10, width: 16, color: C.accent }}>▦</span>
          <span style={{ fontSize: 13 }}>All products</span>
          <span style={{ marginLeft: "auto", fontFamily: mono, fontSize: 9, color: C.faint,
                         letterSpacing: ".06em" }}>
            {products.length}
          </span>
        </div>
      )}

      {products.length > 0 && onSwitchProduct && (
        <ProductSwitcher products={products} activeId={activeId}
                         onSwitch={onSwitchProduct} onAdd={onAddProduct}
                         onDelete={onDeleteProduct} />
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 2, padding: "0 10px",
                    overflow: "auto" }}>
        {PRIMARY.map((n) => (
          <NavRow key={n.key} item={n} active={isActive(n.key)} onClick={() => go(n.key)} />
        ))}
      </div>

      <div style={{ flex: 1 }} />

      {running.length > 0 && (
        <div
          onClick={() => go("today")}
          className="el-btn"
          role="button"
          tabIndex={0}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") go("today"); }}
          style={{ margin: "10px 10px 4px", padding: "10px 12px",
                   border: `1px solid ${C.border2}`, borderRadius: 8, background: C.card2,
                   cursor: "pointer" }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div style={{ width: 7, height: 7, borderRadius: "50%", background: C.accent,
                          animation: "elPulse 1.6s infinite", flex: "none" }} />
            <div style={{ fontSize: 12, color: C.text3 }}>
              {running.length} {plural(running.length, "investigation")} running
            </div>
          </div>
          <div style={{ fontFamily: mono, fontSize: 11, color: C.accent, marginTop: 4,
                        marginLeft: 15 }}>
            {running.slice(0, 2).map((i) => `case #${i.id}`).join(", ")}
            {running.length > 2 ? ` +${running.length - 2}` : ""}
          </div>
        </div>
      )}

      {/* System: how EchoLens itself is running. Collapsed, small, findable. */}
      <div style={{ padding: "6px 10px 4px" }}>
        <div
          onClick={() => setSystemOpen((o) => !o)}
          className="el-btn"
          role="button"
          tabIndex={0}
          aria-expanded={showSystem}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") setSystemOpen((o) => !o); }}
          style={{ display: "flex", alignItems: "center", gap: 7, padding: "5px 10px",
                   cursor: "pointer", fontFamily: mono, fontSize: 9,
                   letterSpacing: ".11em", color: C.ghost }}
        >
          <span>{showSystem ? "▾" : "▸"}</span>
          SYSTEM
        </div>
        {showSystem && (
          <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
            {SYSTEM.map((n) => (
              <NavRow key={n.key} item={n} active={isActive(n.key)} small
                      onClick={() => go(n.key)} />
            ))}
          </div>
        )}
      </div>

      {onLogout && (
        <div
          onClick={onLogout}
          className="el-btn"
          role="button"
          tabIndex={0}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onLogout(); }}
          style={{ margin: "2px 10px 12px", padding: "8px 10px", borderRadius: 6,
                   cursor: "pointer", color: C.muted, fontSize: 12.5, display: "flex",
                   alignItems: "center", gap: 10 }}
        >
          <span style={{ fontFamily: mono, fontSize: 10, width: 16, color: C.faint }}>⎋</span>
          Sign out
        </div>
      )}
    </div>
  );
}

function NavRow({ item, active, onClick, small }: {
  item: NavItem; active: boolean; onClick: () => void; small?: boolean;
}) {
  return (
    <div
      onClick={onClick}
      className="el-btn"
      role="button"
      tabIndex={0}
      title={item.hint}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onClick(); }}
      style={{
        display: "flex", alignItems: "center", gap: 10,
        padding: small ? "6px 10px" : "8px 10px",
        borderRadius: 6, cursor: "pointer",
        background: active ? C.active : "transparent",
        color: active ? C.text : C.muted,
        fontSize: small ? 12.5 : 13.5,
      }}
    >
      <span style={{ fontFamily: mono, fontSize: small ? 9 : 10, width: 16,
                     color: active ? C.accent : C.faint }}>
        {item.icon}
      </span>
      {item.label}
    </div>
  );
}
