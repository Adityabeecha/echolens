import { useState } from "react";
import { ProductRow, api, isAdmin } from "../api";
import { useAsync } from "../hooks";
import { C, mono } from "../theme";
import { Screen } from "../nav";

interface Props {
  screen: Screen;
  go: (s: Screen) => void;
  onOpenCase: () => void;
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
    <div style={{ position: "relative", margin: "0 10px 10px" }}>
      <div
        onClick={() => setOpen((o) => !o)}
        className="el-btn"
        style={{ display: "flex", alignItems: "center", gap: 9, padding: "9px 11px", borderRadius: 8,
                 background: C.card, border: `1px solid ${C.border3}`, cursor: "pointer" }}
      >
        <div style={{ width: 20, height: 20, borderRadius: 5, background: C.hover, border: `1px solid ${C.border4}`,
                      display: "flex", alignItems: "center", justifyContent: "center",
                      fontFamily: mono, fontSize: 10, color: C.accent, flex: "none" }}>
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
        <div style={{ position: "absolute", top: "100%", left: 0, right: 0, marginTop: 4, zIndex: 20,
                      background: C.card2, border: `1px solid ${C.border3}`, borderRadius: 8,
                      boxShadow: "0 16px 40px rgba(0,0,0,.5)", overflow: "hidden" }}>
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

// Grouped by the PM's job, not by EchoLens's internals. Nine flat items forced
// you to know which machine stage a screen belonged to; these three questions
// are the ones people actually arrive with.
interface NavItem { key: Screen; icon: string; label: string; iconColor?: string }
const NAV_GROUPS: { title: string; items: NavItem[] }[] = [
  {
    title: "WHAT NEEDS ME",
    items: [
      { key: "feed", icon: "◉", label: "Cases", iconColor: C.accent },
      { key: "backlog", icon: "▦", label: "Quality Backlog", iconColor: C.accent },
      { key: "chat", icon: "✦", label: "Ask EchoLens", iconColor: C.accent },
    ],
  },
  {
    title: "WHAT WE LEARNED",
    items: [
      { key: "overview", icon: "◈", label: "Product Health" },
      { key: "archive", icon: "▤", label: "Past Cases" },
      { key: "patterns", icon: "❖", label: "Patterns" },
      { key: "brain", icon: "◧", label: "Product Memory", iconColor: C.info },
    ],
  },
  {
    title: "HOW IT'S RUNNING",
    items: [
      { key: "sources", icon: "⇄", label: "Sources" },
      { key: "costs", icon: "$", label: "Costs" },
      { key: "calibration", icon: "◑", label: "Accuracy" },
    ],
  },
];

// The feed / case / finding screens all keep "Case Feed" highlighted.
const FEED_GROUP: Screen[] = ["feed", "case", "finding"];

export function Sidebar({ screen, go, onOpenCase, onLogout, products = [], activeId = null,
                          onSwitchProduct, onAddProduct, onDeleteProduct }: Props) {
  // What is ACTUALLY running, asked of the server — this used to show whatever
  // case you last opened, pulsing as "live" long after it had finished.
  const { data: live } = useAsync(() => api.investigations(), [screen, activeId]);
  const running = (live?.investigations ?? []).filter((i) => i.status === "running");
  return (
    <div
      style={{
        width: 216,
        flex: "none",
        display: "flex",
        flexDirection: "column",
        borderRight: `1px solid ${C.border}`,
        background: C.bgRaised,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "18px 18px 16px" }}>
        <div
          style={{
            width: 26,
            height: 26,
            borderRadius: "50%",
            border: `2px solid ${C.accent}`,
            position: "relative",
            flex: "none",
          }}
        >
          <div
            style={{
              position: "absolute",
              inset: 5,
              borderRadius: "50%",
              background: "radial-gradient(circle at 35% 35%, #f7bd6a, #b06f1a)",
            }}
          />
        </div>
        <div>
          <div style={{ fontWeight: 700, fontSize: 15, letterSpacing: ".02em" }}>EchoLens</div>
          <div style={{ fontFamily: mono, fontSize: 9.5, color: C.faint, letterSpacing: ".08em" }}>
            FEEDBACK FORENSICS
          </div>
        </div>
      </div>

      {/* v9.0: the portfolio spans every product, so it sits ABOVE the switcher —
          the switcher scopes what's below it, not this. */}
      {products.length > 1 && (
        <div
          onClick={() => go("portfolio")}
          className="el-btn"
          style={{ display: "flex", alignItems: "center", gap: 10, margin: "0 10px 8px",
                   padding: "8px 11px", borderRadius: 8, cursor: "pointer",
                   background: screen === "portfolio" ? C.active : "transparent",
                   border: `1px solid ${screen === "portfolio" ? C.border3 : "transparent"}`,
                   color: screen === "portfolio" ? C.text : C.muted }}
        >
          <span style={{ fontFamily: mono, fontSize: 10, width: 16, color: C.accent }}>▦</span>
          <span style={{ fontSize: 13 }}>Portfolio</span>
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

      <div style={{ display: "flex", flexDirection: "column", gap: 14, padding: "8px 10px", overflow: "auto" }}>
        {NAV_GROUPS.map((group) => (
          <div key={group.title} style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            <div style={{ fontFamily: mono, fontSize: 9, letterSpacing: ".11em", color: C.ghost,
                          padding: "0 10px 5px" }}>
              {group.title}
            </div>
            {group.items.map((n) => {
              const active = n.key === "feed" ? FEED_GROUP.includes(screen) : screen === n.key;
              return (
                <div
                  key={n.key}
                  onClick={() => go(n.key)}
                  className="el-btn"
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") go(n.key); }}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                    padding: "7px 10px",
                    borderRadius: 6,
                    cursor: "pointer",
                    background: active ? C.active : "transparent",
                    color: active ? C.text : C.muted,
                  }}
                >
                  <span style={{ fontFamily: mono, fontSize: 10, width: 16, color: n.iconColor ?? C.faint }}>
                    {n.icon}
                  </span>
                  {n.label}
                </div>
              );
            })}
          </div>
        ))}
      </div>

      <div style={{ flex: 1 }} />

      {running.length > 0 && (
        <div
          onClick={() => go("feed")}
          className="el-btn"
          style={{
            margin: 10,
            padding: "10px 12px",
            border: `1px solid ${C.border2}`,
            borderRadius: 8,
            background: C.card2,
            cursor: "pointer",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div
              style={{
                width: 7,
                height: 7,
                borderRadius: "50%",
                background: C.accent,
                animation: "elPulse 1.6s infinite",
                flex: "none",
              }}
            />
            <div style={{ fontSize: 12, color: C.text3 }}>
              {running.length === 1 ? "Investigation running" : `${running.length} investigations running`}
            </div>
          </div>
          <div style={{ fontFamily: mono, fontSize: 11, color: C.accent, marginTop: 4, marginLeft: 15 }}>
            {running.slice(0, 2).map((i) => `case #${i.id}`).join(", ")}
            {running.length > 2 ? ` +${running.length - 2}` : ""}
          </div>
        </div>
      )}

      {onLogout && (
        <div
          onClick={onLogout}
          style={{
            margin: "4px 10px 12px",
            padding: "8px 10px",
            borderRadius: 6,
            cursor: "pointer",
            color: C.muted,
            fontSize: 12.5,
            display: "flex",
            alignItems: "center",
            gap: 10,
          }}
        >
          <span style={{ fontFamily: mono, fontSize: 10, width: 16, color: C.faint }}>⎋</span>
          Sign out
        </div>
      )}
    </div>
  );
}
