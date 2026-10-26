import { useState } from "react";
import { ProductRow, api, isAdmin } from "../api";
import { useAsync, useDialog } from "../hooks";
import { Screen } from "../nav";
import { ThemeMode } from "../themeMode";
import { Icon } from "./Icon";
import { Dropdown } from "./casefile";
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
function dotColor(band?: string | null): string {
  if (band === "healthy") return "var(--el-green)";
  if (band === "attention" || band === "on_fire") return "var(--el-amber)";
  return "var(--el-muted)";
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
  const newActions = [
    onRunInvestigation && { value: "problem", label: "New problem", hint: "Ask EchoLens to look into something", run: onRunInvestigation },
    onImportCsv && { value: "import", label: "Import reviews or tickets", hint: "From a CSV or spreadsheet", run: onImportCsv },
    onAddProduct && isAdmin() && { value: "product", label: "Add a product", hint: "Connect another app", run: onAddProduct },
  ].filter(Boolean) as { value: string; label: string; hint: string; run: () => void }[];
  const act = (fn?: () => void) => { setMenuOpen(false); fn?.(); };
  return <header className="el-topbar">
    <div className="el-topbar__inner">
      <button className="el-topbar__brand" type="button" onClick={onLogo} aria-label={guest ? "EchoLens home page" : "EchoLens Today"}>
        <LogoLockup size={28} /></button>
      {products.length > 0 && <div className="el-product-picker">
        <Dropdown label="Product" value={productId != null ? String(productId) : null} placeholder="Choose product"
          buttonClassName="el-product-picker__button"
          options={products.map((p) => {
            const h = board?.products.find((b) => b.product_id === p.id);
            return { value: String(p.id), label: p.is_demo ? p.name.replace(/\s*\(demo\)$/i, "") : p.name,
              dot: dotColor(h?.band), hint: [p.is_demo ? "Demo" : null, h?.has_data ? `health ${h.health}/100` : null].filter(Boolean).join(" · ") || undefined };
          })}
          onChange={(v) => onSwitchProduct(Number(v))}
          renderButton={(chosen) => <>
            <span className="cf-dropdown__dot" style={{ background: dotColor(health?.band) }} role="img"
              aria-label={health ? `Health ${health.health}/100 — higher is healthier` : "Health not available yet"} />
            <span className="cf-dropdown__value">{chosen?.label ?? "Choose product"}</span>
            {active?.is_demo && <span className="el-product-picker__demo">Demo</span>}
          </>}
          footer={onAddProduct && isAdmin() ? (close) => <button type="button" onClick={() => { close(); onAddProduct(); }}>+ Add a product</button> : undefined} />
      </div>}
      <Sidebar screen={screen} go={open} onAsk={onAsk} onMore={() => setMenuOpen(true)} moreOpen={menuOpen} />
      <div className="el-topbar__spacer" />
      <button type="button" className="el-ask-field" onClick={onAsk} aria-haspopup="dialog" data-tour="ask"
        aria-label="Ask about your reviews" aria-keyshortcuts={askShortcut.startsWith("⌘") ? "Meta+K" : "Control+K"}>
        <Icon name="search" size={16} /><span>Ask about your reviews…</span><kbd>{askShortcut}</kbd></button>
      {/* "+ New" makes things; the gear holds where-to-go and settings. It used
          to open the same workspace menu as the gear. */}
      {newActions.length > 0 && <Dropdown menu label="Create something new" align="end" className="el-topbar__new"
        buttonClassName="el-topbar__new-button" options={newActions.map(({ value, label, hint }) => ({ value, label, hint }))}
        onChange={(v) => newActions.find((a) => a.value === v)?.run()}
        renderButton={() => <><Icon name="plus" size={14} /> New</>} />}
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
