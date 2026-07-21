// Routing. The URL is the single source of truth for "where am I" — not React
// state — so refresh restores your place, the browser back button works, and a
// case can be linked to a colleague.
//
// Hash-based on purpose: it needs no server rewrite rules, so the same build
// works on Vercel, a static bucket, or file://.
//
//   #/p/12/feed            product 12's Case Feed
//   #/p/12/case/34         case 34 (which belongs to product 12)
//   #/p/12/case/34/finding the finding for case 34
//   #/portfolio            cross-product, deliberately unscoped
//   #/onboarding           the add-product wizard

export type Screen =
  | "portfolio"
  | "feed"
  | "backlog"
  | "case"
  | "finding"
  | "archive"
  | "sources"
  | "costs"
  | "onboarding"
  | "calibration"
  | "overview"
  | "patterns"
  | "chat";

/** Screens that live above a single product and must never carry one. */
export const GLOBAL_SCREENS: Screen[] = ["portfolio", "onboarding"];

/** Screens scoped to one product, reachable from the sidebar. */
const PRODUCT_SCREENS: Screen[] = [
  "feed", "backlog", "archive", "sources", "costs", "calibration", "overview", "patterns", "chat",
];

export interface Route {
  screen: Screen;
  /** Case id, for "case" and "finding". */
  id?: number;
  /** The product this view is scoped to. Null on global screens. */
  productId?: number | null;
}

export const SCREEN_LABEL: Record<Screen, string> = {
  portfolio: "Portfolio",
  feed: "Case Feed",
  backlog: "Quality Backlog",
  case: "the investigation",
  finding: "the finding",
  archive: "Archive",
  sources: "Sources",
  costs: "Costs",
  onboarding: "Add a product",
  calibration: "Calibration",
  overview: "Product Health",
  patterns: "Patterns",
  chat: "Ask EchoLens",
};

/** Case states where the work is over and an answer exists to read. */
const SETTLED = ["closed", "resolved", "needs_human", "insufficient_evidence", "budget_exhausted"];

/**
 * Where clicking a case should land you.
 *
 * A finished case opens its FINDING — the answer — not the reasoning trace.
 * The trace is EchoLens's machinery; a PM wants the conclusion, with "how we
 * got here" one click away. A case still running has no answer yet, so it opens
 * the live trace, which is genuinely the most useful thing to watch.
 */
export function caseScreenFor(status?: string | null): "case" | "finding" {
  return status && SETTLED.includes(status) ? "finding" : "case";
}

export function formatRoute(r: Route): string {
  if (GLOBAL_SCREENS.includes(r.screen)) return `#/${r.screen}`;
  const p = r.productId != null ? `/p/${r.productId}` : "";
  if (r.screen === "case") return `#${p}/case/${r.id}`;
  if (r.screen === "finding") return `#${p}/case/${r.id}/finding`;
  return `#${p}/${r.screen}`;
}

export function parseRoute(hash: string): Route | null {
  const path = hash.replace(/^#\/?/, "").replace(/\/$/, "");
  if (!path) return null;
  const parts = path.split("/");

  // Legacy deep link from the challenge-reopen redirect: #case/123
  if (parts[0] === "case" && parts[1]) {
    return { screen: "case", id: parseInt(parts[1], 10), productId: null };
  }

  let productId: number | null = null;
  let rest = parts;
  if (parts[0] === "p" && parts[1]) {
    productId = parseInt(parts[1], 10);
    if (Number.isNaN(productId)) productId = null;
    rest = parts.slice(2);
  }

  const head = rest[0] as Screen | undefined;
  if (!head) return null;

  if (head === "case" && rest[1]) {
    const id = parseInt(rest[1], 10);
    if (Number.isNaN(id)) return null;
    return rest[2] === "finding"
      ? { screen: "finding", id, productId }
      : { screen: "case", id, productId };
  }
  if (GLOBAL_SCREENS.includes(head)) return { screen: head, productId: null };
  if (PRODUCT_SCREENS.includes(head)) return { screen: head, productId };
  return null;
}
