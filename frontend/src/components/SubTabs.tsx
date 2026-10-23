import { KeyboardEvent, useRef } from "react";
import { C, S, T } from "../theme";

/**
 * Tabs inside one screen (Learned patterns, Settings). Same look as the case
 * tabs — an accent underline, not a pill — but a real tablist, so arrow keys
 * move between them and a screen reader announces "tab 2 of 2".
 */
export function SubTabs<K extends string>({ tabs, active, onChange, label }: {
  tabs: { key: K; label: string }[];
  active: K;
  onChange: (key: K) => void;
  /** Accessible name for the tablist. */
  label: string;
}) {
  const refs = useRef<Array<HTMLButtonElement | null>>([]);
  const onKey = (e: KeyboardEvent, i: number) => {
    const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const next = (i + step + tabs.length) % tabs.length;
    onChange(tabs[next].key);
    refs.current[next]?.focus();
  };
  return (
    <div role="tablist" aria-label={label}
      style={{ display: "flex", gap: S[1], padding: `0 var(--el-gutter)`, flex: "none",
               borderBottom: `1px solid ${C.border}`, overflowX: "auto" }}>
      {tabs.map((t, i) => {
        const on = t.key === active;
        return (
          <button
            key={t.key}
            ref={(el) => { refs.current[i] = el; }}
            role="tab"
            aria-selected={on}
            tabIndex={on ? 0 : -1}
            onClick={() => onChange(t.key)}
            onKeyDown={(e) => onKey(e, i)}
            className="el-btn"
            style={{
              background: "transparent", border: "none", whiteSpace: "nowrap",
              padding: `${S[2]} ${S[3]}`, fontSize: T.base, fontFamily: "inherit",
              color: on ? C.text : C.muted,
              borderBottom: `2px solid ${on ? C.accent : "transparent"}`,
            }}
          >
            {t.label}
          </button>
        );
      })}
    </div>
  );
}
