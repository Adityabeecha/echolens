// Routing. The URL is the single source of truth for "where am I" — not React
// state — so refresh restores your place, the browser back button works, and a
// case (or a filtered view of the case list) can be linked to a colleague.
//
// Hash-based on purpose: it needs no server rewrite rules, so the same build
// works on Vercel, a static bucket, or file://.
//
//   #/p/12/today                 product 12's home
//   #/p/12/cases?tab=running     the case list, filtered — shareable
//   #/p/12/cases/34              case 34 (finding tab by default)
//   #/p/12/cases/34/trace        case 34's investigation trace
//   #/portfolio                  cross-product, deliberately unscoped
//   #/onboarding                 the add-product wizard

export type Screen =
  | "today"
  | "cases"
  | "case"
  | "ask"
  | "sources"
  | "patterns"
  | "calibration"
  | "costs"
  | "settings"
  | "plan"
  | "memory"
  | "portfolio"
  | "onboarding";

/** The tabs of a single case. One route, one page, five views. */
export const CASE_TABS = ["finding", "trace", "evidence", "engineering", "history"] as const;
export type CaseTab = (typeof CASE_TABS)[number];

export const CASE_TAB_LABEL: Record<CaseTab, string> = {
  finding: "Finding",
  trace: "Investigation trace",
  evidence: "Evidence",
  engineering: "Engineering",
  history: "History",
};

/** Screens that live above a single product and must never carry one. */
export const GLOBAL_SCREENS: Screen[] = ["portfolio", "onboarding"];

/** Screens scoped to one product. */
const PRODUCT_SCREENS: Screen[] = [
  "today", "cases", "ask", "sources", "patterns", "calibration", "costs",
  "settings", "plan", "memory",
];

export interface Route {
  screen: Screen;
  /** Case id, for the "case" screen. */
  id?: number;
  /** Which tab of the case detail. */
  tab?: CaseTab;
  /** The product this view is scoped to. Null on global screens. */
  productId?: number | null;
  /** List state (filter tab, severity, search…) — in the URL so views are shareable. */
  params?: Record<string, string>;
}

/** The name each screen answers to, used in "Screen · Product" headers. */
export const SCREEN_LABEL: Record<Screen, string> = {
  today: "Today",
  cases: "Cases",
  case: "Case",
  ask: "Ask",
  sources: "Sources",
  patterns: "Patterns",
  calibration: "Calibration",
  costs: "Costs",
  settings: "Settings",
  plan: "Plan",
  memory: "Product memory",
  portfolio: "All products",
  onboarding: "Add a product",
};

/**
 * Which tab of a case to open.
 *
 * A case still running has no answer yet, so it opens the live trace — the most
 * useful thing to watch. A finished case opens its FINDING: a PM wants the
 * conclusion, with "how we got here" one click away, not a reasoning dump.
 */
export function caseTabFor(status?: string | null): CaseTab {
  return status === "running" || status === "queued" ? "trace" : "finding";
}

function qs(params?: Record<string, string>): string {
  if (!params) return "";
  const pairs = Object.entries(params).filter(([, v]) => v !== "" && v != null);
  if (pairs.length === 0) return "";
  return "?" + pairs.map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&");
}

export function formatRoute(r: Route): string {
  if (GLOBAL_SCREENS.includes(r.screen)) return `#/${r.screen}${qs(r.params)}`;
  const p = r.productId != null ? `/p/${r.productId}` : "";
  if (r.screen === "case") {
    const tab = r.tab && r.tab !== "finding" ? `/${r.tab}` : "";
    return `#${p}/cases/${r.id}${tab}${qs(r.params)}`;
  }
  return `#${p}/${r.screen}${qs(r.params)}`;
}

function parseQuery(raw: string): Record<string, string> | undefined {
  if (!raw) return undefined;
  const out: Record<string, string> = {};
  for (const pair of raw.split("&")) {
    if (!pair) continue;
    const [k, v = ""] = pair.split("=");
    if (k) out[decodeURIComponent(k)] = decodeURIComponent(v);
  }
  return Object.keys(out).length ? out : undefined;
}

export function parseRoute(hash: string): Route | null {
  const [rawPath, rawQuery] = hash.replace(/^#\/?/, "").split("?");
  const path = rawPath.replace(/\/$/, "");
  const params = parseQuery(rawQuery ?? "");
  if (!path) return null;
  const parts = path.split("/");

  // Legacy deep links from older builds and from notification/Slack payloads:
  // #case/123 and #/p/1/case/123. They must not 404 a colleague's link.
  if (parts[0] === "case" && parts[1]) {
    const id = parseInt(parts[1], 10);
    if (!Number.isNaN(id)) return { screen: "case", id, productId: null, tab: "finding" };
  }

  let productId: number | null = null;
  let rest = parts;
  if (parts[0] === "p" && parts[1]) {
    productId = parseInt(parts[1], 10);
    if (Number.isNaN(productId)) productId = null;
    rest = parts.slice(2);
  }

  const head = rest[0];
  if (!head) return null;

  if ((head === "cases" || head === "case") && rest[1] && /^\d+$/.test(rest[1])) {
    const id = parseInt(rest[1], 10);
    let tab = (rest[2] ?? "finding") as CaseTab;
    // Old #/p/1/case/34/finding links land on the finding tab, as they should.
    if (!CASE_TABS.includes(tab)) tab = "finding";
    return { screen: "case", id, tab, productId, params };
  }
  if (GLOBAL_SCREENS.includes(head as Screen)) {
    return { screen: head as Screen, productId: null, params };
  }
  if (PRODUCT_SCREENS.includes(head as Screen)) {
    return { screen: head as Screen, productId, params };
  }
  // Retired screens keep working rather than dead-ending: their content moved,
  // so send people where it moved to.
  const RETIRED: Record<string, Screen> = {
    feed: "cases", archive: "cases", overview: "today", backlog: "plan",
    brain: "memory", chat: "ask",
  };
  if (RETIRED[head]) return { screen: RETIRED[head], productId, params };
  return null;
}
