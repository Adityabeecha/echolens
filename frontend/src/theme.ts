// The token bridge.
//
// Every value here is a `var()` pointing at tokens.css, which is the single
// source of truth. Previously this file hardcoded the same 27 hexes that
// tokens.css also declared, so the CSS variables styled almost nothing and
// changing a colour meant changing it in two places.
//
// The shape of `C` is unchanged on purpose: it is imported by ~30 files, and
// keeping the keys stable means the token layer lands without touching them.
// Prefer the `el-*` classes in tokens.css for anything with a hover, focus,
// active or disabled state — an inline style cannot express a pseudo-class.

const v = (name: string) => `var(--el-${name})`;

export const C = {
  ink: v("ink"), paper: v("paper"), soft: v("soft"), line: v("line"), lineStrong: v("line-strong"),
  body: v("body"), stampRed: v("stamp-red"), amber: v("amber"), pencil: v("pencil-blue"),
  green: v("green"), greenBg: v("green-bg"), greenDeep: v("green-deep"),
  highlighter: v("highlighter"), highlighterSoft: v("highlighter-soft"),
  focus: v("focus"), focusText: v("focus-text"), focusMuted: v("focus-muted"), focusBody: v("focus-body"),
  // surface
  bg: v("bg"),
  bgRaised: v("bg-raised"),
  card: v("bg-card"),
  /** Alias of `card`. The two used to differ by 1/255 on one channel. */
  card2: v("bg-card"),
  hover: v("bg-hover"),
  active: v("bg-active"),

  // border
  border: v("border"),
  border2: v("border-2"),
  border3: v("border-3"),
  border4: v("border-4"),

  // text — all of these now pass WCAG AA on every surface
  text: v("text"),
  text2: v("text-2"),
  text3: v("text-3"),
  muted: v("text-muted"),
  dim: v("text-dim"),
  faint: v("text-faint"),
  ghost: v("text-ghost"),

  // accent
  accent: v("accent"),
  accentHi: v("accent-hover"),
  accentDeep: v("accent-deep"),
  onAccent: v("on-accent"),
  accentBg: v("accent-bg"),
  accentLine: v("accent-line"),

  // semantic
  good: v("good"),
  goodBg: v("good-bg"),
  goodLine: v("good-line"),
  bad: v("bad"),
  badBg: v("bad-bg"),
  badLine: v("bad-line"),
  info: v("info"),
  infoBg: v("info-bg"),
  infoLine: v("info-line"),

  // Compatibility names: green fixes, red confirmed problems, blue pencil.
  live: v("live"),
  liveBg: v("live-bg"),
  liveLine: v("live-line"),
  cite: v("cite"),
  citeBg: v("cite-bg"),
  citeLine: v("cite-line"),
  verified: v("verified"),
  verifiedBg: v("verified-bg"),
  verifiedLine: v("verified-line"),
  lead: v("lead"),
  leadBg: v("lead-bg"),
  leadLine: v("lead-line"),
  /** Legacy alias for the approved confirmed-problem red. */
  regress: v("regress"),
  regressBg: v("regress-bg"),
  regressLine: v("regress-line"),

  overlay: v("bg-overlay"),
  inset: v("bg-inset"),
  track: v("track"),
} as const;

export const mono = "var(--el-mono)";
export const sans = "var(--el-font)";
export const serif = "var(--el-serif)";

/** Approved headline and UI scales. */
export const T = {
  hero: "var(--el-fs-hero)", page: "var(--el-fs-page)", case: "var(--el-fs-case)",
  card: "var(--el-fs-card)", section: "var(--el-fs-section)", story: "var(--el-fs-story)", stat: "var(--el-fs-stat)",
  micro: "var(--el-fs-micro)",
  xs: "var(--el-fs-xs)",
  sm: "var(--el-fs-sm)",
  base: "var(--el-fs-base)",
  md: "var(--el-fs-md)",
  lg: "var(--el-fs-lg)",
  xl: "var(--el-fs-xl)",
  display: "var(--el-fs-display)",
} as const;

/** Spacing scale — 4px base. Use as numbers-in-strings, e.g. padding: S[3]. */
export const S = {
  1: "var(--el-s1)",
  2: "var(--el-s2)",
  3: "var(--el-s3)",
  4: "var(--el-s4)",
  5: "var(--el-s5)",
  6: "var(--el-s6)",
  8: "var(--el-s8)",
  10: "var(--el-s10)",
  12: "var(--el-s12)",
} as const;

/** Approved controls, cards, overlays and case-file radii. */
export const R = {
  focus: "var(--el-r-focus)", exhibit: "var(--el-r-exhibit)", good: "var(--el-r-good)",
  sm: "var(--el-r-sm)",
  control: "var(--el-r-control)",
  card: "var(--el-r-card)",
  overlay: "var(--el-r-overlay)",
  pill: "var(--el-r-pill)",
} as const;

/** Elevation scale, tinted toward the background rather than pure black. */
export const E = {
  1: "var(--el-e1)",
  2: "var(--el-e2)",
  3: "var(--el-e3)",
  4: "var(--el-e4)",
} as const;

/**
 * App content is centered at 1200px, including its side gutters.
 */
export const MEASURE = "var(--el-measure)";
/** Public pages use the approved 1280px measure. */
export const PUBLIC_MAX = "var(--el-public-max)";

// Map a terminal-trace kind to its accent color (matches the design).
export const KIND_COLOR: Record<string, string> = {
  THINK: C.muted,
  TOOL: C.live,
  EVID: C.cite,
  UPDT: C.verified,
  // A refused step is an honesty check doing its job, not a regression, so it
  // stays neutral (red is reserved for confirmed problems).
  FAIL: C.text3,
  CHECK: C.faint,
  SPEC: C.accentHi, // v2.0 specialist delegation
  REFUTE: C.live, // v5.0 counter-evidence duty (attempted refutation)
};

export function statusColor(status: string): string {
  return (
    {
      resolved: C.verified,
      insufficient_evidence: C.text3,
      needs_human: C.lead,
      budget_exhausted: C.muted,
      running: C.live,
      queued: C.live,
    }[status] ?? C.muted
  );
}

export function confColor(conf: number): string {
  return conf >= 0.7 ? C.verified : conf >= 0.5 ? C.lead : C.muted;
}
