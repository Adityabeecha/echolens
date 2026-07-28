import { CSSProperties } from "react";

/**
 * The icon set — real SVG, drawn on one grid.
 *
 * Every icon in the app used to be a Unicode dingbat rendered in a monospace
 * font: nav was "◉ ▤ ✦ ⇄ ❖ ◑ ⚙", disclosure was "▸▾", close was "✕". That has
 * three concrete problems that no amount of styling fixes:
 *
 *   1. Font-dependent. "⚙" and "⚠" fall back to the OS emoji font on most
 *      Windows configurations and render as full-colour emoji at the wrong
 *      size, on a text baseline rather than the icon's optical centre.
 *   2. Unstylable. A glyph inherits fontSize and a baseline, so every usage
 *      site had to hand-set a width and a per-tier font size to stop it
 *      jittering next to its label.
 *   3. Not a family. "◉ ▤ ✦ ❖ ◑" come from four Unicode blocks with four
 *      different stroke weights and optical sizes.
 *
 * These are drawn on a 24× grid at a uniform 1.75 stroke, sized in one place,
 * and inherit `currentColor` so a parent's colour is the icon's colour.
 */

const P: Record<string, string> = {
  // ── navigation ──────────────────────────────────────────────────────────
  // Today: a viewfinder. What needs your attention right now.
  today: "M12 3v3M12 18v3M3 12h3M18 12h3M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z",
  // Cases: stacked records.
  cases: "M3 6h18M3 12h18M3 18h18",
  // Ask: a prompt caret.
  ask: "M4 7V5.5A1.5 1.5 0 0 1 5.5 4h13A1.5 1.5 0 0 1 20 5.5v9a1.5 1.5 0 0 1-1.5 1.5H12l-5 4v-4H5.5A1.5 1.5 0 0 1 4 14.5V7Z",
  // Sources: exchange between systems.
  sources: "M4 8h13l-3-3M20 16H7l3 3",
  // Patterns: a proven repeat.
  patterns: "M12 3 4.5 7.5v9L12 21l7.5-4.5v-9L12 3ZM12 3v18M4.5 7.5 12 12l7.5-4.5",
  // Calibration: half-filled dial.
  calibration: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM12 3v18",
  costs: "M12 2v20M17 6.5C17 4.6 14.8 3.5 12 3.5S7 4.6 7 6.5s2 2.8 5 3.5 5 1.6 5 3.5-2.2 3-5 3-5-1.1-5-3",
  settings:
    "M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-1.8-.3 1.6 1.6 0 0 0-1 1.5v.2a2 2 0 1 1-4 0v-.1a1.6 1.6 0 0 0-1-1.5 1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0 .3-1.8 1.6 1.6 0 0 0-1.5-1H2a2 2 0 1 1 0-4h.1a1.6 1.6 0 0 0 1.5-1 1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H8a1.6 1.6 0 0 0 1-1.5V2a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 1 1.5 1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V8a1.6 1.6 0 0 0 1.5 1h.2a2 2 0 1 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1Z",
  // Portfolio: every product at once.
  portfolio: "M4 4h7v7H4V4ZM13 4h7v7h-7V4ZM4 13h7v7H4v-7ZM13 13h7v7h-7v-7Z",
  signout: "M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9",

  // ── disclosure and direction ────────────────────────────────────────────
  chevronDown: "m6 9 6 6 6-6",
  chevronUp: "m18 15-6-6-6 6",
  chevronRight: "m9 18 6-6-6-6",
  chevronLeft: "m15 18-6-6 6-6",
  arrowUp: "M12 19V5M5 12l7-7 7 7",
  arrowDown: "M12 5v14M19 12l-7 7-7-7",
  arrowRight: "M5 12h14M12 5l7 7-7 7",
  reply: "M9 17 4 12l5-5M4 12h11a5 5 0 0 1 5 5v2",
  comment: "M21 11.5a8.4 8.4 0 0 1-9 8.4 8.4 8.4 0 0 1-3.8-.9L3 20l1.9-4.1A8.4 8.4 0 0 1 12 3a8.4 8.4 0 0 1 9 8.5Z",
  external: "M15 3h6v6M10 14 21 3M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5",
  upload: "M12 16V4M8 8l4-4 4 4M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2",

  // ── state ───────────────────────────────────────────────────────────────
  check: "m4 12 5 5L20 6",
  close: "M6 6l12 12M18 6 6 18",
  warning: "M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z",
  info: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM12 16v-4M12 8h.01",
  play: "m7 4 12 8-12 8V4Z",
  pause: "M9 4v16M15 4v16",
  retry: "M21 12a9 9 0 1 1-3-6.7M21 3v6h-6",
  dot: "M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z",
  circle: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z",
  diamond: "m12 3 9 9-9 9-9-9 9-9Z",
  search: "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16ZM21 21l-4.3-4.3",
  plus: "M12 5v14M5 12h14",
  // History kinds.
  shipped: "M12 19V5M5 12l7-7 7 7",
  keyboard: "M6 8h.01M10 8h.01M14 8h.01M18 8h.01M8 12h8M4 5h16a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1Z"
};

/** Icons drawn as solid shapes rather than strokes. */
const FILLED = new Set(["dot", "play", "diamond"]);

export type IconName = keyof typeof P;

export function Icon({
  name,
  size = 16,
  className,
  style,
  title
}: {
  name: IconName | string;
  size?: number;
  className?: string;
  style?: CSSProperties;
  /** Supply only when the icon is the sole label; otherwise it stays decorative. */
  title?: string;
}) {
  const d = P[name];
  if (!d) return null;
  const filled = FILLED.has(name);
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      className={className}
      // Decorative by default: an icon beside a text label must not be read
      // out twice by a screen reader.
      aria-hidden={title ? undefined : true}
      role={title ? "img" : undefined}
      focusable="false"
      style={{ flex: "none", display: "block", ...style }}
    >
      {title && <title>{title}</title>}
      <path
        d={d}
        fill={filled ? "currentColor" : "none"}
        stroke={filled ? "none" : "currentColor"}
        strokeWidth={1.75}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
