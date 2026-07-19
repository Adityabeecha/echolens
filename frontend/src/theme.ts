// Design tokens from echolens-ui-build/project/EchoLens.dc.html.
export const C = {
  bg: "#0e0f13",
  bgRaised: "#101117",
  card: "#15161c",
  card2: "#14151c",
  hover: "#1b1d26",
  active: "#1e202b",
  border: "#22242e",
  border2: "#262933",
  border3: "#2e3140",
  border4: "#3a3e4d",
  text: "#e9eaee",
  text2: "#d7d9e0",
  text3: "#c6c8d1",
  muted: "#9a9daa",
  dim: "#7c7f8c",
  faint: "#6b6e7b",
  ghost: "#565968",
  accent: "#f0a63c",
  accentHi: "#f7bd6a",
  accentDeep: "#b06f1a",
  onAccent: "#17130a",
  good: "#4cc077",
  bad: "#e0584f",
  info: "#8fd0ff",
  track: "#23252f",
} as const;

export const mono = "'IBM Plex Mono', monospace";
export const sans = "'IBM Plex Sans', sans-serif";

// Map a terminal-trace kind to its accent color (matches the design).
export const KIND_COLOR: Record<string, string> = {
  THINK: C.muted,
  TOOL: C.info,
  EVID: C.accent,
  UPDT: C.good,
  FAIL: C.bad,
  CHECK: C.faint,
  SPEC: C.accentHi, // v2.0 specialist delegation
  REFUTE: C.info, // v5.0 counter-evidence duty (attempted refutation)
};

export function statusColor(status: string): string {
  return (
    {
      resolved: C.good,
      insufficient_evidence: C.text3,
      needs_human: C.accent,
      budget_exhausted: C.bad,
      running: C.accent,
    }[status] ?? C.muted
  );
}

export function confColor(conf: number): string {
  return conf >= 0.7 ? C.good : conf >= 0.5 ? C.accent : C.muted;
}
