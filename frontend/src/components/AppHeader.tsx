import { useState } from "react";
import { ProductRow, api, isAdmin } from "../api";
import { useAsync, useDialog } from "../hooks";
import { Screen } from "../nav";
import { ThemeMode } from "../themeMode";
import { Icon } from "./Icon";
import { LogoLockup } from "./Logo";
import { Sidebar } from "./Sidebar";
import { ThemeToggle } from "./ThemeToggle";

export interface Crumb { label: string; onClick?: () => void; mono?: boolean }
export interface AppHeaderProps {
  screen: Screen; go: (screen: Screen) => void; products: ProductRow[]; productId: number | null;
  onSwitchProduct: (id: number) => void; onLogo: () => void; onAsk: () => void; askShortcut: string;
  theme: ThemeMode; onThemeChange: (theme: ThemeMode) => void; onLogout: () => void;
  onAddProduct?: () => void; onRunInvestigation?: () => void; onImportCsv?: () => void;
  liveKey?: number; guest?: boolean;
}
/** The approved top bar; every secondary destination stays in its quiet menu. */
export function AppHeader({ screen, go, products, productId, onSwitchProduct, onLogo, onAsk, askShortcut,
  theme, onThemeChange, onLogout, onAddProduct, onRunInvestigation, onImportCsv, liveKey = 0, guest = false }: AppHeaderProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useDialog(() => setMenuOpen(false), menuOpen);
  const { data: board } = useAsync(() => api.portfolio(), [products.length, productId, liveKey]);
  const active = products.find((p) => p.id === productId);
  const health = board?.products.find((p) => p.product_id === productId);
  const open = (next: Screen) => { setMenuOpen(false); go(next); };
  const act = (fn?: () => void) => { setMenuOpen(false); fn?.(); };
  return <header className="el-topbar">
    <div className="el-topbar__inner">
      <button className="el-topbar__brand" type="button" onClick={onLogo} aria-label={guest ? "EchoLens home page" : "EchoLens Today"}>
        <LogoLockup size={28} /></button>
      {products.length > 0 && <div className="el-product-picker">
        <span className={`el-health-dot el-health-dot--${health?.band ?? "unknown"}`} role="img"
          aria-label={health ? `Health ${health.health}/100 — higher is healthier` : "Health not available yet"}
          title={health ? `Health ${health.health}/100 — higher is healthier` : "Health not available yet"} />
        <select aria-label="Product" value={productId ?? ""} onChange={(event) => onSwitchProduct(Number(event.target.value))}>
          {!active && <option value="" disabled>Choose product</option>}
          {products.map((p) => <option key={p.id} value={p.id}>{p.is_demo ? p.name.replace(/\s*\(demo\)$/i, "") : p.name}</option>)}
        </select><span aria-hidden>▾</span>{active?.is_demo && <span className="el-product-picker__demo">Demo</span>}
      </div>}
      <Sidebar screen={screen} go={open} onAsk={onAsk} onMore={() => setMenuOpen(true)} moreOpen={menuOpen} />
      <div className="el-topbar__spacer" />
      <button type="button" className="el-ask-field" onClick={onAsk} aria-haspopup="dialog" data-tour="ask"
        aria-label="Ask about your reviews" aria-keyshortcuts={askShortcut.startsWith("⌘") ? "Meta+K" : "Control+K"}>
        <Icon name="search" size={16} /><span>Ask about your reviews…</span><kbd>{askShortcut}</kbd></button>
      {onRunInvestigation && <button type="button" className="el-topbar__new el-btn" onClick={() => setMenuOpen(true)}><Icon name="plus" size={14} /> New</button>}
      <button type="button" className="el-topbar__more" onClick={() => setMenuOpen((v) => !v)}
        aria-label="Workspace menu" aria-expanded={menuOpen} aria-controls="el-workspace-menu"><Icon name="settings" size={18} /></button>
    </div>
    {menuOpen && <>
      <div className="el-menu-scrim" onClick={() => setMenuOpen(false)} aria-hidden />
      <div ref={menuRef} id="el-workspace-menu" className="el-workspace-menu" role="dialog" aria-modal="true" aria-label="Workspace menu" tabIndex={-1}>
        <div className="el-workspace-menu__head"><strong>Workspace</strong><button type="button" className="el-btn el-btn--sm" onClick={() => setMenuOpen(false)} aria-label="Close workspace menu">×</button></div>
        {onRunInvestigation && <button type="button" onClick={() => act(onRunInvestigation)}>Run investigation</button>}
        {onImportCsv && <button type="button" onClick={() => act(onImportCsv)}>Import CSV</button>}
        <button type="button" onClick={() => open("intelligence")}>What we've learned</button>
        <button type="button" onClick={() => open("sources")}>Sources</button>
        <button type="button" onClick={() => open("settings")}>Settings</button>
        <button type="button" onClick={() => open("portfolio")}>All products</button>
        {onAddProduct && isAdmin() && <button type="button" onClick={() => act(onAddProduct)}>Add a product</button>}
        <ThemeToggle mode={theme} onChange={onThemeChange} />
        <button type="button" onClick={() => act(onLogout)}>{guest ? "Sign in" : "Sign out"}</button>
      </div>
    </>}
  </header>;
}
