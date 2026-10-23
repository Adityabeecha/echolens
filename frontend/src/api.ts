// Typed client for the EchoLens FastAPI backend.
// Dev: Vite proxies "/api" → http://localhost:8000 (see vite.config.ts).
// Prod (split origins): set VITE_API_BASE to the backend URL at build time,
// e.g. VITE_API_BASE=https://echolens-api.code.run
const BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") || "/api";

// ── session (HttpOnly cookie) ───────────────────────────────────────────
// The JWT lives in an HttpOnly cookie set by /auth/login, /auth/signup and
// /auth/google, so no script on this page can read it. It used to sit in
// localStorage, where any XSS could lift it. What is persisted here is only a
// hint that a session cookie should exist, so a reload skips the login screen;
// the server stays the judge, and a 401 clears the hint.
const SESSION_KEY = "echolens_session";
const LEGACY_TOKEN_KEY = "echolens_token";
let _session = localStorage.getItem(SESSION_KEY) === "1";
// Drop any JWT an older build left behind; it must not linger in storage.
localStorage.removeItem(LEGACY_TOKEN_KEY);
let _onAuthError: (() => void) | null = null;

// Double-submit CSRF token: echoed in X-CSRF-Token on every write. Kept in
// memory only. The API's csrf cookie is on the API's origin, so a split-origin
// frontend cannot read it from document.cookie; the value arrives in the login
// response and, after a reload, from GET /auth/csrf.
let _csrf: string | null = null;

const ROLE_KEY = "echolens_role";
let _role: string = localStorage.getItem(ROLE_KEY) || "viewer";

// ── active product (v8.0) ───────────────────────────────────────────────
// The server is the source of truth (users.last_active_product_id); this is just
// the in-memory value appended to every scoped request.
let _productId: number | null = null;
export function setActiveProduct(id: number | null): void {
  _productId = id;
}
export function getActiveProduct(): number | null {
  return _productId;
}
/** Append the active product to a scoped path. */
function scoped(path: string): string {
  if (_productId == null) return path;
  return path + (path.includes("?") ? "&" : "?") + `product_id=${_productId}`;
}

/** Record a session the server just opened (its cookie is already set). */
export function startSession(csrf?: string | null): void {
  _session = true;
  _csrf = csrf ?? null;
  localStorage.setItem(SESSION_KEY, "1");
}
function forgetSession(): void {
  _session = false;
  _csrf = null;
  localStorage.removeItem(SESSION_KEY);
}
/** Sign out: drop local state and ask the server to clear the cookie. */
export function endSession(): void {
  forgetSession();
  // Always, not only when the hint said signed in: the hint can be lost (storage
  // cleared) while the cookie survives. Best effort; a failure leaves a cookie
  // the next 401 clears again.
  void fetch(BASE + "/auth/logout", { method: "POST", credentials: "include" }).catch(() => {});
}
export function setRole(r: string): void {
  _role = r;
  localStorage.setItem(ROLE_KEY, r);
}
export function getRole(): string {
  return _role;
}
const RANK: Record<string, number> = { viewer: 0, reviewer: 1, admin: 2 };
export function canReview(): boolean {
  return (RANK[_role] ?? 0) >= RANK.reviewer;
}
export function isAdmin(): boolean {
  return _role === "admin";
}

// ── guest mode ──────────────────────────────────────────────────────────
// A visitor with no token, on a deployment that allows guests. They see every
// screen with real data; the server refuses anything above `viewer`, so the UI
// disables those controls rather than letting them fail at the API.
const GUEST_KEY = "echolens_guest";
let _guest = localStorage.getItem(GUEST_KEY) === "1";

export function setGuest(on: boolean): void {
  _guest = on;
  if (on) localStorage.setItem(GUEST_KEY, "1");
  else localStorage.removeItem(GUEST_KEY);
}
/** Browsing without an account. */
export function isGuest(): boolean {
  return _guest && !_session;
}
/** True when the user is signed in properly. */
export function isAuthed(): boolean {
  return _session;
}
export function onAuthError(fn: () => void): void {
  _onAuthError = fn;
}

function readCookie(name: string): string | null {
  const hit = document.cookie.split("; ").find((c) => c.startsWith(name + "="));
  return hit ? decodeURIComponent(hit.slice(name.length + 1)) : null;
}

/** Headers for a state-changing request: the CSRF echo, fetched once if a
 * reload lost it. Reads go without it; the server only checks writes. */
async function writeHeaders(): Promise<Record<string, string>> {
  if (!_session) return {};
  if (!_csrf) _csrf = readCookie("echolens_csrf"); // same-origin deployments
  if (!_csrf) {
    try {
      const r = await fetch(BASE + "/auth/csrf", { credentials: "include" });
      if (r.ok) _csrf = (await r.json())?.csrf_token ?? null;
    } catch {
      /* the write itself will surface the failure */
    }
  }
  return _csrf ? { "X-CSRF-Token": _csrf } : {};
}

const CSRF_REJECTED = "missing or invalid CSRF token";

/** A state-changing request with the CSRF echo. If the server rejects the
 * token — another tab signed in again and rotated it — fetch the current one
 * and retry once, instead of failing every write until a reload. */
async function writeFetch(path: string, init: RequestInit & { headers?: Record<string, string> }): Promise<Response> {
  const send = async () => fetch(BASE + path, {
    ...init, credentials: "include", headers: { ...init.headers, ...(await writeHeaders()) },
  });
  let r = await send();
  if (r.status === 403 && _session) {
    const detail = await r.clone().json().then((j) => j?.detail, () => null);
    if (detail === CSRF_REJECTED) {
      _csrf = null;
      r = await send();
    }
  }
  return r;
}

function handle(status: number): void {
  if (status === 401) {
    // endSession also clears the stale cookie, so a guest-enabled deployment
    // does not keep rejecting every request for the expired session.
    endSession();
    _onAuthError?.(); // bounce back to login
  }
}

/** A stable, human-readable message for fetch and API failures. */
export function errorMessage(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  if (/failed to fetch/i.test(message) || /networkerror/i.test(message)) {
    return "The backend is unavailable. It may be restarting — wait a moment and retry.";
  }
  return message.replace(/^Error:\s*/i, "");
}

async function get<T>(path: string): Promise<T> {
  // credentials: "include" sends the session cookie to a split-origin API.
  const r = await fetch(BASE + path, { credentials: "include" });
  if (!r.ok) {
    handle(r.status);
    throw new Error(`${path} → ${r.status}`);
  }
  return r.json();
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const r = await writeFetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) {
    handle(r.status);
    let detail = "";
    try {
      detail = (await r.json())?.detail ?? "";
    } catch {
      /* ignore */
    }
    throw new Error(detail || `${path} → ${r.status}`);
  }
  return r.json();
}

async function put<T>(path: string, body?: unknown): Promise<T> {
  const r = await writeFetch(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) {
    handle(r.status);
    let detail = "";
    try {
      detail = (await r.json())?.detail ?? "";
    } catch {
      /* ignore */
    }
    throw new Error(detail || `${path} → ${r.status}`);
  }
  return r.json();
}

async function patch<T>(path: string, body?: unknown): Promise<T> {
  const r = await writeFetch(path, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) {
    handle(r.status);
    let detail = "";
    try {
      detail = (await r.json())?.detail ?? "";
    } catch {
      /* ignore */
    }
    throw new Error(detail || `${path} → ${r.status}`);
  }
  return r.json();
}

async function del<T>(path: string): Promise<T> {
  const r = await writeFetch(path, { method: "DELETE" });
  if (!r.ok) {
    handle(r.status);
    let detail = "";
    try {
      detail = (await r.json())?.detail ?? "";
    } catch {
      /* ignore */
    }
    throw new Error(detail || `${path} → ${r.status}`);
  }
  return r.json();
}

// ── types ────────────────────────────────────────────────────────────

export interface Triage {
  decision: "investigate" | "ignore" | "merge";
  reason: string;
  budget_tier: string | null;
  merge_into_anomaly_id: number | null;
}
export interface Anomaly {
  slug: string;
  type: string;
  metric: string;
  delta: number;
  z: number;
  window: string;
  description: string;
  status: string;
  headline?: string;
  product_id?: number | null;
  triage: Triage | null;
  investigation_id: number | null;
}
export interface Hypothesis {
  id: string;
  statement: string;
  confidence: number;
  status: "active" | "supported" | "rejected";
  evidence_for: string[];
  evidence_against: string[];
  next_test?: string;
}
export interface Evidence {
  id: string;
  source: string;
  ref: string;
  snippet: string;
  retrieved_by: string;
  supports: string[];
  contradicts: string[];
  /** v15: set when a reviewer struck this item as not supporting the finding. */
  rejected?: { at: string; user_id: number | null; note: string } | null;
}
export interface Impact {
  terms: string[];
  affected_pct: number;
  affected_volume: number;
  recent_negatives: number;
  rating_now: number | null;
  rating_baseline: number | null;
  rating_impact: number;
  blast_radius: { dimension: string; top_cohort: string | null; ratio: number | null; exclusive: boolean };
  impact_score: number;
  as_of: string;
}
export interface Decision {
  whats_broken: string;
  how_bad: string;
  what_to_do: string;
}
export interface Severity {
  score: number;
  /** "unknown" means impact could not be measured — not that it is small. */
  band: "high" | "medium" | "low" | "unknown";
}
export interface FixChartPoint {
  date: string;
  count: number;
}
export interface ReleaseState {
  fixed_in_version: string | null;
  state: "none" | "not_seen" | "rolling_out" | "live";
  first_seen: string | null;
  review_count: number;
  needed_reviews: number;
  needed_days: number;
}
export interface ReplyDraft {
  review_id: number;
  ext_id: string;
  rating: number;
  version: string | null;
  created_at: string | null;
  excerpt: string;
  language: "en" | "non_english";
  draft: string | null;
  note: string | null;
}
export interface ReplyDrafts {
  finding_id: number;
  mode: "fixed" | "shipped" | "investigating";
  fixed_in_version: string | null;
  fix_confirmed: boolean;
  topic: string;
  total: number;
  shown: number;
  skipped_on_fixed_version: number;
  drafts: ReplyDraft[];
  translation_note: string;
  draft_only: true;
  store: "play_store" | "app_store" | null;
  console_name: string | null;
  console_url: string | null;
  listing_url?: string;
}
export interface FollowupQuestions {
  finding_id: number;
  case_status: string | null;
  questions: { question: string; source: string; why: string }[];
}
export interface FixStatus {
  status: string; // issue_open | waiting_for_release | watching | confirmed | persists_reopened | regressed
  issue_number: number;
  issue_url: string;
  baseline_rate: number | null;
  post_rate: number | null;
  /** The app version carrying the fix; the watch window opens when it reaches users. */
  fixed_in_version?: string | null;
  /** True while no version is set, so the UI can suggest setting one. */
  version_hint?: boolean;
  release?: ReleaseState;
  chart: {
    fixed_in_version?: string | null;
    window_start?: "first_review_on_fixed_version" | "issue_closed";
    fix_date: string;
    window_days: number;
    before: FixChartPoint[];
    after: FixChartPoint[];
    before_rate: number | null;
    after_rate: number | null;
    metric: string;
    terms: string[];
  } | null;
}
export interface Finding {
  id: number;
  status: string;
  summary: string;
  prose: string;
  confidence: number;
  supported_hypothesis: string | null;
  checked: string[];
  what_would_settle_it: string;
  impact?: Impact;
  decision?: Decision;
  severity?: Severity;
  fix?: FixStatus | null;
  /** How much to trust this finding, from its own evidence rows. */
  trust?: TrustSummary | null;
  addenda?: { question: string; answer: string; dimension: string }[];
  /** Set when the claim-grounding guard rejected the drafted prose. */
  grounding_violations?: string[];
  /** The rejected text, kept for audit — never presented as the conclusion. */
  rejected_draft?: string;
  /** v15: evidence a reviewer struck, and the flag raised when that broke the two-source rule. */
  rejected_evidence?: { eid: string; user_id: number | null; at: string; note: string }[];
  needs_review?: { reason: string; at: string; eid: string } | null;
}
export interface Recommendation {
  rank: number;
  action: string;
  impact: string;
  effort: string;
  rationale: string;
}
/** v15: what the team decided to DO about a finding (separate from whether it is true). */
export type ProductDecisionKind = "fix_now" | "park" | "wont_fix";
export interface ProductDecision {
  decision: ProductDecisionKind;
  revisit_by: string | null;
  reason: string;
  user_id: number | null;
  at: string | null;
  /** True while the decision keeps it out of the open-problem lists. */
  hidden: boolean;
}
/** v15: whether a dead-end case can be continued with more budget. */
export interface ExtensionOffer {
  eligible: boolean;
  reason: string;
  steps: number;
  estimate_usd: number;
  spent_usd: number;
  used: number;
  remaining: number;
}
export interface ShareState {
  active: boolean;
  token: string | null;
  created_at: string | null;
  url: string | null;
}
export interface ShareBrief {
  headline: string;
  impact: string;
  why: string;
  quotes: { text: string; source: string }[];
  actions: { action: string; impact: string; effort: string }[];
  markdown: string;
  product?: string | null;
  shared_at?: string | null;
}
export interface HistoryEvent {
  at: string | null;
  kind: string;
  text: string;
  case_id: number | null;
  note: string;
  /** Who made it, for human decisions (email), when known. */
  by?: string | null;
}
export interface Investigation {
  id: number;
  anomaly_id: number | null;
  /** The raw engine state. Prefer case_status for anything user-facing. */
  status: string;
  /** The canonical status, derived server-side so lists and detail agree. */
  case_status: string;
  case_why: string;
  title: string;
  opened_by: string;
  budget_tier: string;
  budget: Record<string, string>;
  paused: boolean;
  escalated: boolean;
  reopens_investigation_id: number | null;
  data_notes: string[];
  history: HistoryEvent[];
  hypotheses: Hypothesis[];
  evidence: Evidence[];
  finding: Finding | null;
  recommendations: Recommendation[];
  product_decision?: ProductDecision | null;
  extension?: ExtensionOffer | null;
}

// v13: the unified case list. One lifecycle, one status vocabulary, one card —
// this is what Today, Cases and every "open problems" list read from.
export interface CaseRow {
  /** Null for queued work: it has no investigation yet. */
  id: number | null;
  queue_id: number | null;
  title: string;
  status: string;
  why: string;
  severity: "high" | "medium" | "low" | "unknown" | null;
  severity_score: number | null;
  confidence: number | null;
  impact: { affected_pct: number; affected_volume: number } | null;
  opened_at: string | null;
  age_days: number | null;
  source: string;
  opened_by: string;
  iterations: { done: number; max: number } | null;
  paused: boolean;
  finding_id: number | null;
  issue_url: string | null;
  issue_number: number | null;
  reopens_investigation_id: number | null;
  /** v15: the product decision in force, if any. */
  decision?: ProductDecision | null;
  position?: number;
  /** Weekly complaint volume, or null when there is nothing real to draw. */
  spark: number[] | null;
  /** Queued past today's daily cap; `why` says so. */
  deferred?: boolean;
  budget_tier?: string | null;
  /** What running it now would likely cost — always an estimate. */
  estimate?: CostEstimate | null;
  /** The trust badge, for cases with a finding. */
  trust?: TrustSummary | null;
}
/**
 * Computed from a case's evidence rows. `label` is the badge sentence; it says
 * "verified" only when `verified` (approved + confirmed fix) is true.
 */
export interface TrustSummary {
  label: string;
  sources: { source: string; count: number }[];
  distinct_sources: number;
  /** guards.two_source_rule on the supported hypothesis. */
  two_source_ok: boolean;
  confidence: "high" | "medium" | "low";
  evidence_count: number;
  verified: boolean;
}
export interface CostEstimate {
  usd: number;
  /** "median" of past cases at this tier, or the tier's "tier_cap". */
  basis: "median" | "tier_cap";
  samples: number;
  tier: string;
  is_estimate: true;
}
/** Review counts by what the review is FOR. Every key is always present. */
export type IntentCounts = Record<"bug" | "feature_request" | "ux_confusion" | "praise" | "other", number>;
/** Related signals for one product and window, investigated as one. */
export interface Incident {
  key: string;
  /** The strongest member: investigating the incident investigates this. */
  lead: string;
  title: string;
  members: string[];
  z: number;
  window_start: string;
  window_end: string;
  intents: IntentCounts | null;
}
export interface SignalRow {
  id?: number;
  slug: string;
  title: string;
  type: string;
  metric: string;
  z: number;
  window: string;
  age_days: number | null;
  dismissed: boolean;
  dismissed_reason: string | null;
  window_start?: string | null;
  window_end?: string | null;
  /** Null when no reviews sit behind the signal (e.g. a GitHub issue burst). */
  intents?: IntentCounts | null;
}
export interface CaseView {
  product: string | null;
  product_id: number | null;
  cases: CaseRow[];
  signals: SignalRow[];
  incidents?: Incident[];
  intents?: { product: string | null; days: number; total: number; counts: IntentCounts };
  daily_limit?: number;
  counts: Record<string, number>;
}
export interface TraceStep {
  seq: number;
  kind: string;
  content: Record<string, unknown>;
  tokens: number;
  ms: number;
}
export interface SourcesResp {
  connected: {
    icon: string;
    name: string;
    detail: string;
    status: string;
    stale?: boolean;
    staleSince?: string | null;
    why?: string | null;
    lastSuccess?: string | null;
    source?: string;
    identifier?: string;
    lastPull: string;
    volume: string;
    error?: string | null;
  }[];
  available: string[];
  product?: string | null;
  last_synced?: Freshness;
}

// Today overview: the context drawn around the score.
export interface Freshness {
  last_synced_at: string | null;
  age_minutes: number | null;
  sources: number;
  stale_after_hours: number;
  stale: boolean;
}
export interface ReleaseMarker {
  version: string;
  released_at: string;
  label: string;
}
export interface RatingPart {
  theme_id: string;
  label: string;
  contribution: number;
  recent_share_pct: number | null;
  recent_reviews: number | null;
  case_id: number | null;
}
export interface RatingBreakdown {
  estimate: boolean;
  method: string;
  window: { recent_days: number; prior_days: number };
  recent_reviews: number;
  prior_reviews: number;
  rating_now: number | null;
  rating_prior: number | null;
  delta: number | null;
  dropped: boolean;
  parts: RatingPart[];
  summary: string | null;
  reason: string | null;
}
export interface Overview {
  product: string | null;
  product_id: number | null;
  releases: ReleaseMarker[];
  rating_breakdown: RatingBreakdown;
  freshness: Freshness;
  /** Fixes confirmed in the last 14 days that you have not dismissed (max 3). */
  confirmed_fixes?: ConfirmedFix[];
}
export interface ConfirmedFix {
  watch_id: number;
  finding_id: number;
  investigation_id: number;
  headline: string;
  metric: string;
  drop_pct: number | null;
  fixed_in_version: string | null;
  confirmed_at: string;
  chart: FixStatus["chart"];
  /** Affected reviewers the reply panel would draft for. */
  reply_count: number;
}

// Issue trackers a finding can be filed to.
export type TrackerId = "github" | "linear" | "jira";
export interface TrackerInfo { id: TrackerId; label: string; configured: boolean }
export interface TicketResult {
  tracker: TrackerId; repo: string | null;
  /** GitHub issue number, Linear identifier ("ENG-12") or Jira key ("APP-3"). */
  number: number | string | null;
  url: string | null;
}

/** The onboarding preview of one source. `ok: false` is a normal answer. */
export interface SourcePreview {
  ok: boolean;
  kind?: "invalid" | "not_found" | "timeout" | "unavailable";
  reason?: string;
  source?: "play_store" | "github";
  identifier?: string;
  title?: string;
  developer?: string | null;
  ratings?: number | null;
  reviews?: number | null;
  score?: number | null;
  installs?: string | null;
  description?: string | null;
  open_issues?: number | null;
  stars?: number | null;
}

// v3.0 onboarding + health snapshot
export interface SnapshotTheme {
  label: string;
  count: number;
}
export interface Snapshot {
  product: string | null;
  reviews: number;
  window_days: number;
  date_from: string;
  date_to: string;
  avg_per_day: number;
  negatives: number;
  rating_now: number | null;
  rating_prev: number | null;
  rating_delta: number | null;
  weekly: { week_start: string; count: number; avg_rating: number | null }[];
  top_themes: SnapshotTheme[];
  non_english: number;
  data_quality: { low_volume: boolean; note: string | null; non_english_note: string | null };
}
export interface SourceHealth {
  source: string;
  identifier: string;
  product: string | null;
  status: string;
  items_last_run: number;
  last_run_at: string | null;
  last_error: string | null;
  stale: boolean;
  stale_since: string | null;
  never_collected: boolean;
}
export interface OnboardStatus {
  product: string;
  backfilling: boolean;
  sources: SourceHealth[];
  progress?: {
    checked_sources: number;
    failed_sources: number;
    timed_out_sources: number;
    total_sources: number;
    expected_seconds: number;
    timeout_seconds: number;
    started_at: string | null;
  };
  snapshot: Snapshot;
  anomalies: Anomaly[];
}
export interface FixWatchRow {
  id: number;
  finding_id: number;
  investigation_id: number;
  repo: string;
  issue_number: number;
  issue_url: string;
  status: string;
  metric: string;
  baseline_rate: number | null;
  post_rate: number | null;
  // Only present on a terminal status — the server sends null while watching.
  chart: FixStatus["chart"];
  fix_date: string | null;
}
export interface FixWatchResp {
  watches: FixWatchRow[];
}
export interface CommentNode {
  id: number;
  author: string;
  author_id: number | null;
  body: string | null;
  deleted: boolean;
  created_at: string | null;
  edited: boolean;
  replies: CommentNode[];
}
export interface CommentsResp {
  investigation_id: number;
  comments: CommentNode[];
}
export interface TeamView {
  awaiting_review: {
    id: number; investigation_id: number; requested_by: string;
    requested_of: string; note: string; created_at: string | null;
  }[];
  recent_comments: {
    id: number; investigation_id: number; author: string;
    excerpt: string; created_at: string | null;
  }[];
  contributors: { user: string; comments: number }[];
  open_request_count: number;
  product: string | null;
}
export interface AvailableSource {
  source: string;
  label: string;
  hint: string;
}
export interface AvailableSourcesResp {
  sources: AvailableSource[];
}
export interface CostsSummary {
  stats: {
    spent_today: number;
    avg_per_resolved: number;
    dead_end_spend: number;
    analyst_hours_saved: number;
    resolved_count: number;
  };
  month_to_date: number;
  budget: number;
  product?: string | null;
  limits: {
    daily_investigations: number;
    per_case_budget: number;
    per_case_wall_min: number;
  };
  rows: {
    id: string;
    outcome: string;
    status: string;
    tokens: string;
    queries: number;
    time: string;
    cost: string;
  }[];
}

// v5.0 calibration + weak spots
export interface CalibrationPoint {
  range: string;
  midpoint: number;
  count: number;
  approval_rate: number | null;
}
export interface WeakSpot {
  reason: string;
  label: string;
  count: number;
  guidance: string;
}
export interface Calibration {
  n_reviewed: number;
  sufficient: boolean;
  points: CalibrationPoint[];
  overall_approval_rate: number | null;
  mean_stated_confidence: number | null;
  overconfidence_gap: number | null;
  overconfident: boolean;
  headline: string | null;
  product?: string | null;
  weak_spots: { total_challenges: number; spots: WeakSpot[] };
}

// v6.0 patterns + product-health overview
// v10: themes are clustered problem statements, not n-gram counts.
export interface ThemeCandidate {
  slug: string;
  statement: string;
  count: number;
  verbatims: string[];
  trend: "up" | "down" | "flat";
  label_source: "model" | "verbatim" | "phrase";
  first_seen?: string | null;
  /** Set when this theme is already queued or investigated. */
  existing: { reason: string; queue_id: number | null; investigation_id: number | null } | null;
  intents?: IntentCounts | null;
  /** Set when someone renamed it; the generated name is kept here. */
  renamed?: boolean;
  original_statement?: string;
  merged_from?: string[];
  avg_rating?: number | null;
}
export interface ThemeOverride {
  slug: string;
  label: string | null;
  merged_into: string | null;
  muted: boolean;
  updated_by: string | null;
  updated_at: string | null;
}
export interface CandidatesResp {
  candidates: ThemeCandidate[];
  /** Feature requests / improvements from 3-5 star reviews. */
  requests?: ThemeCandidate[];
  muted?: number;
  product: string | null;
  engine?: string;
  cached?: boolean;
  reviews_considered?: number;
  other?: number;
}
export interface QueueItem {
  queue_id: number;
  position: number;
  title: string;
  source: string;
  budget_tier: string;
  anomaly_id: number | null;
  investigation_id: number | null;
  status: "queued" | "deferred";
  note: string | null;
}
export interface QueueSelection {
  status: "queued" | "already";
  slug: string;
  queue_id: number | null;
  investigation_id: number | null;
}
export interface QueueView {
  running: { queue_id: number; title: string; investigation_id: number | null }[];
  queued: QueueItem[];
  used_today: number;
  daily_limit: number;
  remaining_today: number;
}

// v12: the product-knowledge brain
export interface BrainEdge {
  subsystem: string;
  symptom: string;
  statement: string;
  confidence: number;
  verified_count: number;
  supports: number;
  refutes: number;
  status: "active" | "retired";
  case_ids: number[];
  trend: "holding" | "weakening";
}
export interface ReviewFlag {
  subsystem: string;
  symptom: string;
  confidence: number;
  verified_count: number;
  case_ids: number[];
  recommendation: string;
  why: string;
}
export interface ChangeReview {
  risk: "clear" | "elevated" | "high";
  subsystems_touched: string[];
  flags: ReviewFlag[];
  summary: string;
  product?: string | null;
}

// v11: the quality backlog
export interface BacklogItem {
  rank: number;
  investigation_id: number;
  finding_id: number;
  summary: string;
  confidence: number;
  severity: { score: number; band: "high" | "medium" | "low" };
  score: number;
  volume: number;
  persistence_days: number;
  effort: {
    days: number; basis: string; known: boolean;
    /** True when a reviewer set the number; `estimated` is what EchoLens guessed. */
    overridden?: boolean;
    estimated?: { days: number; basis: string; known: boolean };
  };
  /** Impact on a 1–5 scale; `default` comes from the severity band. */
  impact?: { level: number; default: number; overridden: boolean; factor: number };
  /** A manual priority segment set by a reviewer, or null. */
  segment?: PlanSegment | null;
  value_per_day: number;
  projected: { stars: number; basis: string; confident: boolean };
  evidence_refs: string[];
  evidence_count: number;
  theme: string | null;
  defence: string;
}
export interface QuarterPlan {
  included?: number[];
  excluded?: number[];
  proposed: BacklogItem[];
  deferred: BacklogItem[];
  capacity_days: number;
  committed_days: number;
  remaining_days: number;
  projected_stars: number;
  owned: boolean;
  notes: Record<string, string>;
  /** Reviewer overrides keyed by investigation id. */
  overrides?: Record<string, PlanOverride>;
  /** The priority segments a reviewer can pick, with their documented factors. */
  segments?: PlanSegment[];
  /** Impact level → value multiplier ("1".."5"). */
  impact_scale?: Record<string, number>;
  resolution_rate: number;
  median_fix_days: number | null;
  unknown_effort: number;
  generated: string;
  product?: string | null;
}

export interface PlanSegment {
  key: string;
  label: string;
  factor: number;
  why: string;
}
export interface PlanOverride {
  effort_days?: number | null;
  impact?: number | null;
  segment?: string | null;
}

export interface Pattern {
  terms: string[];
  trigger: string;
  cause: string;
  fix: string;
  verified_count: number;
  cases: number[];
  cross_product?: boolean;
  from_product?: string | null;
}

// ── v9.0 portfolio ──────────────────────────────────────────────────────
export interface PortfolioReason {
  kind: string;
  weight: number;
  text: string;
}
export interface PortfolioProduct {
  product_id: number;
  product: string;
  is_demo: boolean;
  score: number;
  band: "on_fire" | "attention" | "watch" | "healthy";
  band_label: string;
  /** 100 − score: what users see. Higher is healthier; `score` still ranks. */
  health: number;
  health_label: string;
  reasons: PortfolioReason[];
  headline: string;
  top_problem: { investigation_id: number; summary: string; band: string; sev_score: number } | null;
  open_problems: number;
  regressions: number;
  untriaged: number;
  negative_rate_pct: number;
  negative_rate_delta_pct: number | null;
  confirmed_fixes: number;
  has_data: boolean;
}
export interface TransferStats {
  seeded_cases: number;
  cold_cases: number;
  median_iterations_seeded: number | null;
  median_iterations_cold: number | null;
  iterations_saved_pct: number | null;
  sufficient: boolean;
}
export interface Portfolio {
  generated: string;
  products: PortfolioProduct[];
  total_products: number;
  needs_attention: number;
  verdict: string;
  transfer: TransferStats;
}
export interface PortfolioBrief {
  generated: string;
  verdict: string;
  lines: string[];
  problems: { investigation_id: number; summary: string; product: string; impact_score: number }[];
  transfers: {
    investigation_id: number;
    product: string | null;
    from_product: string | null;
    cause: string | null;
    verified_count: number | null;
    status: string;
  }[];
}
export interface PortfolioTheme {
  theme_id: string;
  label: string;
  is_family: boolean;
  worst: string | null;
  products: { product: string | null; rate_pct: number; mentions: number; negatives: number }[];
}

// v7.0 chat, brief, themes
export interface ChatCitation {
  investigation_id: number;
  finding_id: number;
  summary: string;
  affected_pct?: number | null;
}
export interface ChatToolCall {
  name: string;
  args: Record<string, unknown>;
  why?: string;
}
/** Where an Ask answer came from. */
export interface ChatBasis {
  kind: "investigation" | "raw_search" | "signals" | "none" | "investigation_started";
  label: string;
  case_id: number | null;
  /** Shown under answers that are not a verified cause. */
  caution: string | null;
}
/** The inline "Start an investigation into …" card. */
export interface ChatNextStep {
  kind: "investigate";
  question: string;
  /** Queue this existing incident lead through the Cases path. */
  slug?: string;
  allowed: boolean;
  reason: string | null;
}
/** One live progress line while Ask works ("Searching reviews for 'paywall'…"). */
export interface ChatStep {
  kind: string;
  text: string;
  tool?: string;
  why?: string;
}
export interface ChatResponse {
  type: "answer" | "investigation";
  text: string;
  citations?: ChatCitation[];
  investigation_id?: number;
  tool_calls?: ChatToolCall[];
  confident?: boolean;
  can_investigate?: boolean;
  basis?: ChatBasis;
  next_step?: ChatNextStep | null;
}
export interface WeeklyBrief {
  generated: string;
  resolution_rate: number;
  new_problems: { investigation_id: number; summary: string; impact_score: number }[];
  fixes_verified: { investigation_id: number; metric: string }[];
  regressions: { slug: string; parent_case_id: number | null }[];
  chronic_themes: ThemeLifecycle[];
  fix_next: { investigation_id: number; summary: string; score: number } | null;
  lines: string[];
}
export interface ThemeLifecycle {
  theme: string;
  label: string;
  status: "chronic" | "active" | "resolved";
  age_days: number;
  cases: number[];
  open_cases: number;
  first_seen: string;
  last_seen: string;
}

// v8.0 products
export interface DeletionPreview {
  id: number;
  name: string;
  is_demo: boolean;
  reviews: number;
  cases: number;
  findings: number;
  anomalies: number;
  sources: number;
}
export interface ProductRow {
  id: number;
  name: string;
  package_name: string | null;
  github_repo: string | null;
  is_demo: boolean;
  created_at: string | null;
}

// ── endpoints ────────────────────────────────────────────────────────

export interface AuthUser {
  id: number | null;
  email: string | null;
  role: string;
  /** True when the server admitted this request with no token at all. */
  guest?: boolean;
}

export const api = {
  health: () => get<{ db: boolean; llm_key_present: boolean; model: string }>("/health"),
  login: (email: string, password: string) =>
    post<{ token: string; role: string; csrf_token?: string }>("/auth/login", { email, password }),
  signup: (email: string, password: string) =>
    post<{ id: number; email: string; role: string; token: string; csrf_token?: string }>("/auth/signup", { email, password }),
  /** Exchange a Google ID token for an EchoLens token. */
  google: (credential: string) =>
    post<{ token: string; role: string; email: string; csrf_token?: string }>("/auth/google", { credential }),
  /** Which sign-in options this deployment offers. Safe without a token. */
  authConfig: () =>
    get<{
      google_client_id: string;
      google_enabled: boolean;
      allow_guest: boolean;
      auth_required: boolean;
    }>("/auth/config"),
  me: () => get<AuthUser>("/auth/me"),
  products: () => get<{ products: ProductRow[]; active_product_id: number | null }>("/products"),
  activateProduct: (id: number) =>
    post<{ active_product_id: number; name: string }>(`/products/${id}/activate`),
  deletionPreview: (id: number) => get<DeletionPreview>(`/products/${id}/deletion-preview`),
  // Goes through del() like everything else: a raw fetch() skipped handle(),
  // so a 401 here left you on a dead screen instead of bouncing to login.
  deleteProduct: (id: number, confirmName: string) =>
    del<{ deleted: string }>(`/products/${id}?confirm=${encodeURIComponent(confirmName)}`),
  collect: () => post("/collect/run"),
  scan: () => post<{ detected: string[] }>(scoped("/anomalies/scan")),
  cases: () => get<CaseView>(scoped("/cases")),
  triage: (run = false) =>
    post<{ summary?: string; skipped_already_triaged?: number }>(scoped(`/anomalies/triage?run=${run}`)),
  // `id` is null for rows still in the queue — they have no Investigation yet.
  // They are included so the work-watcher can see queued work at all.
  investigations: () =>
    get<{ investigations: { id: number | null; queue_id?: number; status: string;
                            opened_by: string; anomaly_id: number | null }[] }>(
      scoped("/investigations")
    ),
  // scoped(): without the active product the server falls back to the FIRST
  // product, and the ownership check then 404s any case belonging to another
  // one — which is every case in a product you added second.
  investigation: (id: number) => get<Investigation>(scoped(`/investigations/${id}`)),
  trace: (id: number, after = 0) =>
    get<{ status: string; steps: TraceStep[] }>(scoped(`/investigations/${id}/trace?after=${after}`)),
  startInvestigation: (body: { anomaly_slug?: string; description?: string; tier?: string }) =>
    post<{ status: string; investigation_id: number; anomaly_id: number }>("/investigations", {
      ...body,
      product_id: getActiveProduct(),
    }),
  review: (findingId: number, action: "approve" | "challenge", note = "", reason?: string) =>
    post<{ status: string; reopened_investigation_id?: number }>(scoped(`/findings/${findingId}/review`), {
      action,
      note,
      reason,
    }),
  calibration: () => get<Calibration>(scoped("/calibration")),
  patterns: () => get<{ patterns: Pattern[]; product?: string | null }>(scoped("/patterns")),
  // v9.0 — deliberately NOT scoped: this is the screen you open before you know
  // which product to open.
  feedCandidates: (refresh = false) =>
    get<CandidatesResp>(scoped(`/feed/candidates${refresh ? "?refresh=true" : ""}`)),
  queueThemes: (slugs: string[], statements: Record<string, string>, tier = "quick") =>
    post<{ queued: QueueSelection[]; already: QueueSelection[]; queue: QueueView; summary: string }>(
      "/queue/themes", { slugs, statements, tier, product_id: getActiveProduct() }),
  queue: () => get<QueueView>(scoped("/queue")),
  cancelQueued: (queueId: number) => del<{ cancelled: number }>(scoped(`/queue/${queueId}`)),
  /** Bypass today's cap for ONE deferred item. Recorded on the queue row. */
  runQueuedNow: (queueId: number) =>
    post<{ status: string; investigation_id: number; estimate: CostEstimate }>(
      scoped(`/queue/${queueId}/run-now`)),
  themeOverrides: () => get<{ overrides: ThemeOverride[] }>(scoped("/themes/overrides")),
  setThemeOverride: (body: { slug: string; action: "rename" | "merge" | "mute" | "unmute" | "reset";
                             label?: string; into?: string }) =>
    post<{ overrides: ThemeOverride[] }>("/themes/overrides",
      { ...body, product_id: getActiveProduct() }),
  brain: (includeRetired = false) =>
    get<{ edges: BrainEdge[]; product: string | null }>(
      scoped(`/brain${includeRetired ? "?include_retired=true" : ""}`)),
  brainReview: (text: string) =>
    post<ChangeReview>("/brain/review", { text, product_id: getActiveProduct() }),
  brainAsk: (question: string) =>
    post<{ answer: string; edges: BrainEdge[]; grounded: boolean }>(
      "/brain/ask", { question, product_id: getActiveProduct() }),
  backlogPlan: (capacityDays?: number) =>
    get<QuarterPlan>(scoped(`/backlog/plan${capacityDays ? `?capacity_days=${capacityDays}` : ""}`)),
  // `overrides` omitted keeps the saved ones (a Drop/Add never wipes estimates);
  // send the whole map to change them.
  saveBacklogPlan: (body: {
    included: number[]; excluded: number[]; capacity_days?: number;
    overrides?: Record<string, PlanOverride>;
  }) =>
    put<QuarterPlan>("/backlog/plan", { ...body, product_id: getActiveProduct() }),
  portfolio: () => get<Portfolio>("/portfolio"),
  portfolioBrief: () => get<PortfolioBrief>("/portfolio/brief"),
  portfolioThemes: () =>
    get<{ themes: PortfolioTheme[]; products: string[]; days: number; note: string }>("/portfolio/themes"),
  /**
   * POST /chat/stream: the same answer as `chat`, but `onStep` is called with
   * each progress line as it happens. Read with fetch (not EventSource) so it
   * is a normal cookie-authenticated POST with the CSRF header, never a token
   * in the URL. Rejects on any failure — the caller falls back to `chat`.
   */
  chatStream: async (message: string, onStep: (s: ChatStep) => void,
                     forceInvestigate = false): Promise<ChatResponse> => {
    const r = await writeFetch("/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ message, product_id: getActiveProduct(), force_investigate: forceInvestigate }),
    });
    if (!r.ok || !r.body) {
      handle(r.status);
      throw new Error(`/chat/stream → ${r.status}`);
    }
    const reader = r.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
      let cut: number;
      while ((cut = buf.indexOf("\n\n")) >= 0) {
        const block = buf.slice(0, cut);
        buf = buf.slice(cut + 2);
        let event = "message";
        let data = "";
        for (const line of block.split("\n")) {
          if (line.startsWith("event:")) event = line.slice(6).trim();
          else if (line.startsWith("data:")) data += line.slice(5).trim();
        }
        if (!data) continue;
        const payload = JSON.parse(data);
        if (event === "step") onStep(payload as ChatStep);
        else if (event === "answer") {
          reader.cancel().catch(() => undefined);
          return payload as ChatResponse;
        } else if (event === "error") {
          reader.cancel().catch(() => undefined);
          throw new Error(payload?.error || "Ask failed");
        }
      }
    }
    throw new Error("The answer stream ended early");
  },
  chat: (message: string, forceInvestigate = false) =>
    post<ChatResponse>("/chat", {
      message, product_id: getActiveProduct(), force_investigate: forceInvestigate
    }),
  brief: () => get<WeeklyBrief>(scoped("/brief")),
  findingFollowup: (findingId: number, question: string) =>
    post<{ question: string; answer: string; investigation_id: number }>(
      scoped(`/findings/${findingId}/followup`), { question }),
  pause: (id: number) => post(scoped(`/investigations/${id}/pause`)),
  // v15 — single-case PM workflow
  extend: (id: number) =>
    post<ExtensionOffer & { status: string }>(scoped(`/investigations/${id}/extend`)),
  decideFinding: (findingId: number, decision: ProductDecisionKind | "cleared",
                  revisitBy?: string | null, reason = "") =>
    post<{ product_decision: ProductDecision | null }>(scoped(`/findings/${findingId}/decision`), {
      decision, revisit_by: revisitBy || null, reason
    }),
  rejectEvidence: (findingId: number, eid: string, note = "") =>
    post<{ eid: string; two_source_ok: boolean | null; needs_review: boolean; message: string }>(
      scoped(`/findings/${findingId}/evidence/${encodeURIComponent(eid)}/reject`), { note }),
  editRecommendation: (findingId: number, rank: number, body: { effort?: string; impact?: string }) =>
    patch<Recommendation>(scoped(`/findings/${findingId}/recommendations/${rank}`), body),
  findingBrief: (findingId: number, link?: string) =>
    get<ShareBrief>(scoped(`/findings/${findingId}/brief${link ? `?link=${encodeURIComponent(link)}` : ""}`)),
  shareState: (findingId: number) => get<ShareState>(scoped(`/findings/${findingId}/share`)),
  createShare: (findingId: number) => post<ShareState>(scoped(`/findings/${findingId}/share`)),
  revokeShare: (findingId: number) => del<ShareState>(scoped(`/findings/${findingId}/share`)),
  /** Public, unauthenticated: never sends the session token. */
  publicShare: async (token: string): Promise<ShareBrief> => {
    const r = await fetch(`${BASE}/share/${encodeURIComponent(token)}`);
    if (!r.ok) {
      let detail = "";
      try { detail = (await r.json())?.detail ?? ""; } catch { /* ignore */ }
      throw new Error(detail || `This link is not valid (${r.status}).`);
    }
    return r.json();
  },
  resume: (id: number) => post(scoped(`/investigations/${id}/resume`)),
  escalate: (id: number) => post(scoped(`/investigations/${id}/escalate`)),
  sources: () => get<SourcesResp>(scoped("/sources")),
  overview: () => get<Overview>(scoped("/today/overview")),
  // Not scoped: which source types exist is global, not per-product.
  availableSources: () => get<AvailableSourcesResp>("/sources/available"),
  fixwatch: () => get<FixWatchResp>(scoped("/fixwatch")),
  /** Hide a "Fix confirmed" card from your own Today, for good. */
  dismissFix: (watchId: number) =>
    post<{ dismissed: number }>(scoped(`/fixwatch/${watchId}/dismiss`)),
  comments: (invId: number) =>
    get<CommentsResp>(scoped(`/investigations/${invId}/comments`)),
  postComment: (invId: number, body: string, parentId?: number) =>
    post<CommentsResp & { posted: number }>(
      scoped(`/investigations/${invId}/comments`),
      { body, parent_id: parentId ?? null }),
  deleteComment: (commentId: number) =>
    del<{ deleted: number }>(scoped(`/comments/${commentId}`)),
  team: () => get<TeamView>(scoped("/team")),
  requestReview: (invId: number, note: string) =>
    post<{ request_id: number; status: string }>(
      scoped(`/investigations/${invId}/review-request`), { note }),
  importReviews: (file: File, product?: string, source = "csv") => {
    const fd = new FormData();
    fd.append("file", file);
    const qs = new URLSearchParams({ source });
    if (product) qs.set("product", product);
    // Without a product the importer writes Review(product=None): the rows land
    // attached to NO product and are invisible to every scoped screen.
    const pid = getActiveProduct();
    if (pid != null) qs.set("product_id", String(pid));
    return writeFetch(`/import/reviews?${qs.toString()}`, {
      method: "POST",
      body: fd,
    }).then(async (r) => {
      if (!r.ok) {
        // handle() bounces a 401 to the login screen. This raw fetch skipped it,
        // so an expired session here failed silently instead.
        handle(r.status);
        throw new Error((await r.json().catch(() => ({})))?.detail || `import → ${r.status}`);
      }
      return r.json() as Promise<{ imported: number; skipped: number; total: number }>;
    });
  },
  // product_id, not just the free-text name. With a blank product the server
  // falls back to `product or identifier`, so the source attached to a product
  // named after the raw PACKAGE — not the one whose Sources screen you were on.
  connectSource: (source: string, identifier: string, product?: string) =>
    post<{ connected: { source: string; identifier: string; product: string } }>("/sources/connect", {
      source,
      identifier,
      product,
      product_id: getActiveProduct(),
    }),
  collectorsRetry: (source: string, identifier: string) =>
    post<{ inserted: number; error: string | null }>("/collectors/retry", {
      source, identifier, product_id: getActiveProduct()
    }),
  collectorsRun: () => post<{
    duration_seconds: number;
    results: { source: string; identifier: string; fetched: number; inserted: number;
               error: string | null; duration_seconds: number }[];
  }>(scoped("/collectors/run")),
  embed: () => post<{ embedded: Record<string, number> }>(scoped("/search/embed")),
  onboard: (body: {
    play_store: string; github?: string; github_sources?: string[]; product?: string;
    app_store?: string; chrome_web_store?: string; hacker_news?: string; stack_overflow?: string;
  }) =>
    post<{ status: string; product: string; product_id: number; play_store: string;
           github: string | null; github_sources: string[]; additional_sources: string[] }>(
      "/onboard", body),
  onboardStatus: (product: string) =>
    get<OnboardStatus>(`/onboard/status?product=${encodeURIComponent(product)}`),
  snapshot: (product?: string) =>
    get<Snapshot>(product ? `/snapshot?product=${encodeURIComponent(product)}` : scoped("/snapshot")),
  findingIssue: (findingId: number) =>
    get<{ title: string; body: string; repo: string | null }>(scoped(`/findings/${findingId}/issue`)),
  createGithubIssue: (findingId: number) =>
    post<{ repo: string; number: number; url: string }>(scoped(`/findings/${findingId}/github-issue`)),
  setFixedVersion: (findingId: number, version: string | null) =>
    put<{ status: string; fixed_in_version: string | null; release: ReleaseState }>(
      scoped(`/findings/${findingId}/fixed-version`), { version }),
  replyDrafts: (findingId: number) =>
    get<ReplyDrafts>(scoped(`/findings/${findingId}/reply-drafts`)),
  followupQuestions: (findingId: number) =>
    get<FollowupQuestions>(scoped(`/findings/${findingId}/followup-questions`)),
  /** Which issue trackers this deployment can file to (booleans, no secrets). */
  trackers: () => get<{ trackers: TrackerInfo[] }>("/integrations/trackers"),
  /** File a finding to GitHub, Linear or Jira — same ticket body everywhere. */
  createTicket: (findingId: number, tracker: TrackerId) =>
    post<TicketResult>(scoped(`/findings/${findingId}/ticket?tracker=${tracker}`)),
  /** Instant look-up of what the wizard is about to connect. Never throws on a
   *  slow store — the server answers `ok: false` with a reason instead. */
  onboardPreview: (q: { play_store?: string; github?: string }) => {
    const qs = Object.entries(q).filter(([, v]) => v && v.trim())
      .map(([k, v]) => `${k}=${encodeURIComponent(v!.trim())}`).join("&");
    return get<{ play_store?: SourcePreview; github?: SourcePreview }>(`/onboard/preview?${qs}`);
  },
  notifyFinding: (findingId: number) =>
    post<{ routed: string; sent?: string[] }>(scoped(`/findings/${findingId}/notify`)),
  costsSummary: () => get<CostsSummary>(scoped("/costs/summary")),
  // Goes through put(): the raw fetch() never checked r.ok, so a rejected save
  // (401, 403, 500) resolved as success and Settings reported "Limit saved."
  // scoped(): the READ comes from costsSummary(), which is product-scoped and
  // layers this product's override on top. An unscoped write landed in the
  // workspace row that the read ignores, so the save appeared to succeed and
  // the number silently reverted.
  setLimits: (limits: { daily_investigations?: number; per_case_budget?: number; per_case_wall_min?: number }) =>
    put<Record<string, number>>(scoped("/settings/limits"), limits),
  // SSE URL for the live trace. No token in it: a JWT in a URL ends up in
  // proxy logs and history. The session cookie authenticates the stream, sent
  // because useTrace opens the EventSource with withCredentials.
  traceStreamUrl: (id: number) => {
    const qs = new URLSearchParams();
    if (_productId != null) qs.set("product_id", String(_productId));
    const q = qs.toString();
    return `${BASE}/investigations/${id}/trace/stream${q ? `?${q}` : ""}`;
  },
};
