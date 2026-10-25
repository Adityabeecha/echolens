import { Screen } from "../nav";
import { Icon } from "./Icon";
import { useMediaQuery } from "../hooks";

const ITEMS: { key: Screen; label: string }[] = [
  { key: "today", label: "Today" }, { key: "cases", label: "All problems" },
  { key: "plan", label: "Plan" }, { key: "intelligence", label: "What we've learned" },
];
/** Kept at the old import path for compatibility; this is a top/bottom nav, never a rail. */
export function Sidebar({ screen, go, onAsk, onMore, moreOpen = false }: {
  screen: Screen; go: (screen: Screen) => void; onAsk: () => void; onMore: () => void; moreOpen?: boolean;
}) {
  const current = screen === "case" ? "cases" : ["patterns", "memory"].includes(screen) ? "intelligence" : screen;
  const mobile = useMediaQuery("(max-width: 767px)");
  return <>
    {!mobile && <nav className="el-pill-nav" aria-label="Main navigation">{ITEMS.map((item) =>
      <button key={item.key} type="button" data-tour={item.key} aria-current={current === item.key ? "page" : undefined}
        className={current === item.key ? "is-active" : ""} onClick={() => go(item.key)}>{item.label}</button>)}</nav>}
    {mobile && <nav className="el-bottom-nav" aria-label="Phone navigation">
      {ITEMS.slice(0, 3).map((item, i) => <button key={item.key} type="button" onClick={() => go(item.key)}
        aria-current={current === item.key ? "page" : undefined} data-tour={item.key}>
        <Icon name={i === 0 ? "today" : i === 1 ? "cases" : "shipped"} size={18} />
        <span>{i === 1 ? "Problems" : item.label}</span></button>)}
      <button type="button" onClick={onAsk}><Icon name="ask" size={18} /><span>Ask</span></button>
      <button type="button" onClick={onMore} aria-expanded={moreOpen} aria-controls="el-workspace-menu">
        <Icon name="settings" size={18} /><span>More</span></button>
    </nav>}
  </>;
}
