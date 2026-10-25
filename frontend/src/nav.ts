// Routing. The URL is the single source of truth for "where am I" — not React
// state — so refresh restores your place, the browser back button works, and a
// case (or a filtered view of the case list) can be linked to a colleague.
//
// Clean history paths. vercel.json (and the Vite dev server) serve index.html
// for any path that is not a file, so a deep link or a refresh lands here.
//
//   /p/12/today                  product 12's home
//   /p/12/cases?tab=running      the case list, filtered — shareable
//   /p/12/cases/34               case 34 (finding tab by default)
//   /p/12/cases/34/trace         case 34's investigation trace
//   /p/12/intelligence?view=fixes  what EchoLens has learned (patterns, proven fixes)
//   /p/12/settings?section=costs
//   /portfolio                   cross-product, deliberately unscoped
//   /onboarding                  the add-product wizard
//   /share/<token>               a public brief (outside the app; see main.tsx)
//
// Older builds used hash routes (/#/p/12/today, /#/share/<token>). Those links
// live on in notifications, Slack and bookmarks, so they still parse, and
// main.tsx rewrites them to the clean path on load.

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
  | "intelligence"
  | "portfolio"
  | "onboarding";

/** The tabs of a single case. One route, one page, six views. */
export const CASE_TABS = ["finding", "trace", "evidence", "engineering", "discussion", "history"] as const;
export type CaseTab = (typeof CASE_TABS)[number];

export const CASE_TAB_LABEL: Record<CaseTab, string> = {
  finding: "Finding",
  trace: "Investigation trace",
  evidence: "Evidence",
  engineering: "Engineering",
  discussion: "Discussion",
  history: "History",
};

/** Screens that live above a single product and must never carry one. */
export const GLOBAL_SCREENS: Screen[] = ["portfolio", "onboarding"];

/** Screens scoped to one product. */
const PRODUCT_SCREENS: Screen[] = [
  "today", "cases", "ask", "sources", "patterns", "calibration", "costs",
  "settings", "plan", "memory", "intelligence",
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
  cases: "All problems",
  case: "Problem",
  ask: "Ask",
  sources: "Sources",
  patterns: "What we've learned",
  calibration: "Settings",
  costs: "Costs",
  settings: "Settings",
  plan: "Plan",
  memory: "What we've learned",
  intelligence: "What we've learned",
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

/**
 * What EchoLens has learned lives under "Intelligence" (`intelligence`): the
 * learned-patterns map and proven fixes as two views, with calibration one
 * click away in Settings. `memory` (the old "Learned patterns") and `patterns`
 * stay in the union so existing `go("memory")` / `go("patterns")` callers and
 * old links keep working; they are rewritten here, in one place. Calibration
 * and Costs are sections of Settings.
 */
export const LEARNED_VIEWS = ["map", "fixes"] as const;
export type LearnedView = (typeof LEARNED_VIEWS)[number];
export const SETTINGS_SECTIONS = ["general", "costs", "sensitivity", "honesty", "integrations", "calibration"] as const;
export type SettingsSection = (typeof SETTINGS_SECTIONS)[number];

export function canonicalRoute(r: Route): Route {
  if (r.screen === "patterns") {
    return { ...r, screen: "intelligence", params: { ...r.params, view: "fixes" } };
  }
  if (r.screen === "memory") {
    return { ...r, screen: "intelligence" };
  }
  if (r.screen === "calibration") {
    return { ...r, screen: "settings", params: { ...r.params, section: "calibration" } };
  }
  if (r.screen === "costs") {
    return { ...r, screen: "settings", params: { ...r.params, section: "costs" } };
  }
  return r;
}

export function formatRoute(route: Route): string {
  const r = canonicalRoute(route);
  if (GLOBAL_SCREENS.includes(r.screen)) return `/${r.screen}${qs(r.params)}`;
  const p = r.productId != null ? `/p/${r.productId}` : "";
  if (r.screen === "case") {
    const tab = r.tab && r.tab !== "finding" ? `/${r.tab}` : "";
    return `${p}/cases/${r.id}${tab}${qs(r.params)}`;
  }
  return `${p}/${r.screen}${qs(r.params)}`;
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

/**
 * A route from a clean path ("/p/12/cases?tab=running") or a legacy hash
 * ("#/p/12/cases?tab=running", "#case/34"). Null when it names no screen.
 */
export function parseRoute(location: string): Route | null {
  const [rawPath, rawQuery] = location.replace(/^#?\/?/, "").split("?");
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
    // A product id is a positive integer. parseInt("-5") is -5, not NaN, so
    // "#/p/-5/today" produced scoped requests with product_id=-5 on first paint,
    // before the boot check could reject it.
    if (!Number.isFinite(productId) || productId <= 0) productId = null;
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
    return canonicalRoute({ screen: head as Screen, productId, params });
  }
  // Retired screens keep working rather than dead-ending: their content moved,
  // so send people where it moved to.
  const RETIRED: Record<string, Screen> = {
    feed: "cases", archive: "cases", overview: "today", backlog: "plan",
    brain: "intelligence", chat: "ask",
  };
  if (RETIRED[head]) return { screen: RETIRED[head], productId, params };
  return null;
}

/**
 * The token of a public, read-only share link (/share/<token>, or the legacy
 * #/share/<token>), or null.
 *
 * Deliberately outside `Route`: a shared brief is not a place in the app. It is
 * rendered before login and without a product, so it must never reach the
 * router, the boot sequence, or any authenticated request.
 */
export function shareToken(location: string): string | null {
  const m = location.match(/^#?\/?share\/([A-Za-z0-9_-]{16,64})\/?$/);
  return m ? m[1] : null;
}

/** Kept for callers that only ever had the hash. */
export const shareTokenFromHash = shareToken;

/** Where the app is now: the path and query (the hash is legacy-only). */
export function currentLocation(): string {
  return window.location.pathname + window.location.search;
}

/**
 * The clean path an old hash URL stands for ("/#/p/2/today" -> "/p/2/today",
 * "/#/share/<t>" -> "/share/<t>"), or null when the hash is not a route. Used
 * once on load so bookmarks and links from older builds keep working.
 */
export function legacyHashTarget(hash: string): string | null {
  if (!hash || hash === "#" || hash === "#/") return null;
  const token = shareToken(hash);
  if (token) return `/share/${token}`;
  const route = parseRoute(hash);
  return route ? formatRoute(route) : null;
}
