// Typed client for the EchoLens FastAPI backend.
// Dev: Vite proxies "/api" → http://localhost:8000 (see vite.config.ts).
// Prod (split origins): set VITE_API_BASE to the backend URL at build time,
// e.g. VITE_API_BASE=https://echolens-api.code.run
const BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") || "/api";

// ── auth token (persisted) ──────────────────────────────────────────────
const TOKEN_KEY = "echolens_token";
let _token: string | null = localStorage.getItem(TOKEN_KEY);
let _onAuthError: (() => void) | null = null;

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

export function setToken(t: string | null): void {
  _token = t;
  if (t) localStorage.setItem(TOKEN_KEY, t);
  else localStorage.removeItem(TOKEN_KEY);
}
export function getToken(): string | null {
  return _token;
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
export function onAuthError(fn: () => void): void {
  _onAuthError = fn;
}
function authHeaders(): Record<string, string> {
  return _token ? { Authorization: `Bearer ${_token}` } : {};
}
function handle(status: number): void {
  if (status === 401) {
    setToken(null);
    _onAuthError?.(); // bounce back to login
  }
}

async function get<T>(path: string): Promise<T> {
  const r = await fetch(BASE + path, { headers: authHeaders() });
  if (!r.ok) {
    handle(r.status);
    throw new Error(`${path} → ${r.status}`);
  }
  return r.json();
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(BASE + path, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
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
  const r = await fetch(BASE + path, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...authHeaders() },
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
  const r = await fetch(BASE + path, { method: "DELETE", headers: authHeaders() });
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
  band: "high" | "medium" | "low";
}
export interface FixChartPoint {
  date: string;
  count: number;
}
export interface FixStatus {
  status: string; // issue_open | watching | confirmed | persists_reopened | regressed
  issue_number: number;
  issue_url: string;
  baseline_rate: number | null;
  post_rate: number | null;
  chart: {
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
  addenda?: { question: string; answer: string; dimension: string }[];
}
export interface Recommendation {
  rank: number;
  action: string;
  impact: string;
  effort: string;
  rationale: string;
}
export interface Investigation {
  id: number;
  anomaly_id: number | null;
  status: string;
  title: string;
  opened_by: string;
  budget_tier: string;
  budget: Record<string, string>;
  paused: boolean;
  escalated: boolean;
  reopens_investigation_id: number | null;
  data_notes: string[];
  hypotheses: Hypothesis[];
  evidence: Evidence[];
  finding: Finding | null;
  recommendations: Recommendation[];
}
export interface TraceStep {
  seq: number;
  kind: string;
  content: Record<string, unknown>;
  tokens: number;
  ms: number;
}
export interface FeedSummary {
  investigations_today: number;
  daily_limit: number;
  spent_today: number;
  product?: string | null;
}
export interface ArchiveRow {
  id: string;
  cause: string;
  status: string;
  conf: number;
  human: string;
  cost: string;
  time: string;
  summary: string;
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
  snapshot: Snapshot;
  anomalies: Anomaly[];
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
  label_source: "model" | "verbatim";
  first_seen?: string | null;
  /** Set when this theme is already queued or investigated. */
  existing: { reason: string; queue_id: number | null; investigation_id: number | null } | null;
}
export interface CandidatesResp {
  candidates: ThemeCandidate[];
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
  effort: { days: number; basis: string; known: boolean };
  value_per_day: number;
  projected: { stars: number; basis: string; confident: boolean };
  evidence_refs: string[];
  evidence_count: number;
  theme: string | null;
  defence: string;
}
export interface QuarterPlan {
  proposed: BacklogItem[];
  deferred: BacklogItem[];
  capacity_days: number;
  committed_days: number;
  remaining_days: number;
  projected_stars: number;
  owned: boolean;
  notes: Record<string, string>;
  resolution_rate: number;
  median_fix_days: number | null;
  unknown_effort: number;
  generated: string;
  product?: string | null;
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
  reasons: PortfolioReason[];
  headline: string;
  top_problem: { investigation_id: number; summary: string; band: string; sev_score: number } | null;
  open_problems: number;
  regressions: number;
  untriaged: number;
  negative_rate_pct: number;
  negative_rate_delta_pct: number;
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
export interface Overview {
  open_problems: { investigation_id: number; summary: string; impact_score: number; affected_pct: number }[];
  open_problem_count: number;
  in_verification: number;
  confirmed_fixes_total: number;
  confirmed_fixes_quarter: number;
  regressions: number;
  mean_days_to_confirmed_fix: number | null;
  product?: string | null;
  chronic_themes: ThemeLifecycle[];
}

// v7.0 chat, brief, themes
export interface ChatCitation {
  investigation_id: number;
  finding_id: number;
  summary: string;
  affected_pct?: number | null;
}
export interface ChatResponse {
  type: "answer" | "investigation";
  text: string;
  citations?: ChatCitation[];
  investigation_id?: number;
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
  id: number;
  email: string;
  role: string;
}

export const api = {
  health: () => get<{ db: boolean; llm_key_present: boolean; model: string }>("/health"),
  login: (email: string, password: string) =>
    post<{ token: string; role: string }>("/auth/login", { email, password }),
  signup: (email: string, password: string) =>
    post<{ id: number; email: string; role: string; token: string }>("/auth/signup", { email, password }),
  me: () => get<AuthUser>("/auth/me"),
  products: () => get<{ products: ProductRow[]; active_product_id: number | null }>("/products"),
  activateProduct: (id: number) =>
    post<{ active_product_id: number; name: string }>(`/products/${id}/activate`),
  deletionPreview: (id: number) => get<DeletionPreview>(`/products/${id}/deletion-preview`),
  deleteProduct: (id: number, confirmName: string) =>
    fetch(`${BASE}/products/${id}?confirm=${encodeURIComponent(confirmName)}`, {
      method: "DELETE",
      headers: authHeaders(),
    }).then(async (r) => {
      if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.detail || `delete → ${r.status}`);
      return r.json() as Promise<{ deleted: string }>;
    }),
  collect: () => post("/collect/run"),
  scan: () => post<{ detected: string[] }>(scoped("/anomalies/scan")),
  anomalies: () => get<{ anomalies: Anomaly[] }>(scoped("/anomalies")),
  triage: (run = false) =>
    post<{ summary?: string; skipped_already_triaged?: number }>(scoped(`/anomalies/triage?run=${run}`)),
  feedSummary: () => get<FeedSummary>(scoped("/feed/summary")),
  investigations: () =>
    get<{ investigations: { id: number; status: string; opened_by: string; anomaly_id: number | null }[] }>(
      scoped("/investigations")
    ),
  investigation: (id: number) => get<Investigation>(`/investigations/${id}`),
  trace: (id: number, after = 0) =>
    get<{ status: string; steps: TraceStep[] }>(`/investigations/${id}/trace?after=${after}`),
  startInvestigation: (body: { anomaly_slug?: string; description?: string; tier?: string }) =>
    post<{ status: string; investigation_id: number; anomaly_id: number }>("/investigations", {
      ...body,
      product_id: getActiveProduct(),
    }),
  review: (findingId: number, action: "approve" | "challenge", note = "", reason?: string) =>
    post<{ status: string; reopened_investigation_id?: number }>(`/findings/${findingId}/review`, {
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
    post<{ queued: unknown[]; already: unknown[]; queue: QueueView; summary: string }>(
      "/queue/themes", { slugs, statements, tier, product_id: getActiveProduct() }),
  queue: () => get<QueueView>(scoped("/queue")),
  cancelQueued: (queueId: number) => del<{ cancelled: number }>(`/queue/${queueId}`),
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
  saveBacklogPlan: (body: { included: number[]; excluded: number[]; capacity_days?: number }) =>
    put<QuarterPlan>("/backlog/plan", { ...body, product_id: getActiveProduct() }),
  portfolio: () => get<Portfolio>("/portfolio"),
  portfolioBrief: () => get<PortfolioBrief>("/portfolio/brief"),
  portfolioThemes: () =>
    get<{ themes: PortfolioTheme[]; products: string[]; days: number; note: string }>("/portfolio/themes"),
  overview: () => get<Overview>(scoped("/overview")),
  chat: (message: string) => post<ChatResponse>("/chat", { message, product_id: getActiveProduct() }),
  brief: () => get<WeeklyBrief>(scoped("/brief")),
  themes: () => get<{ themes: ThemeLifecycle[] }>(scoped("/themes")),
  findingFollowup: (findingId: number, question: string) =>
    post<{ question: string; answer: string; investigation_id: number }>(`/findings/${findingId}/followup`, { question }),
  pause: (id: number) => post(`/investigations/${id}/pause`),
  resume: (id: number) => post(`/investigations/${id}/resume`),
  escalate: (id: number) => post(`/investigations/${id}/escalate`),
  archive: () => get<{ rows: ArchiveRow[]; count: number; resolved_pct: number }>(scoped("/archive")),
  sources: () => get<SourcesResp>(scoped("/sources")),
  importReviews: (file: File, product?: string, source = "csv") => {
    const fd = new FormData();
    fd.append("file", file);
    const qs = new URLSearchParams({ source });
    if (product) qs.set("product", product);
    return fetch(`${BASE}/import/reviews?${qs.toString()}`, {
      method: "POST",
      headers: { ...(getToken() ? { Authorization: `Bearer ${getToken()}` } : {}) },
      body: fd,
    }).then(async (r) => {
      if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.detail || `import → ${r.status}`);
      return r.json() as Promise<{ imported: number; skipped: number; total: number }>;
    });
  },
  connectSource: (source: string, identifier: string, product?: string) =>
    post<{ connected: { source: string; identifier: string; product: string } }>("/sources/connect", {
      source,
      identifier,
      product,
    }),
  collectorsRetry: (source: string, identifier: string) =>
    post<{ inserted: number; error: string | null }>("/collectors/retry", { source, identifier }),
  collectorsRun: () => post<{ results: { source: string; identifier: string; fetched: number; inserted: number; error: string | null }[] }>("/collectors/run"),
  embed: () => post<{ embedded: Record<string, number> }>("/search/embed"),
  onboard: (body: { play_store: string; github?: string; product?: string }) =>
    post<{ status: string; product: string; product_id: number; play_store: string; github: string | null }>(
      "/onboard", body),
  onboardStatus: (product: string) =>
    get<OnboardStatus>(`/onboard/status?product=${encodeURIComponent(product)}`),
  snapshot: (product?: string) =>
    get<Snapshot>(product ? `/snapshot?product=${encodeURIComponent(product)}` : scoped("/snapshot")),
  findingIssue: (findingId: number) =>
    get<{ title: string; body: string; repo: string | null }>(`/findings/${findingId}/issue`),
  createGithubIssue: (findingId: number) =>
    post<{ repo: string; number: number; url: string }>(`/findings/${findingId}/github-issue`),
  notifyFinding: (findingId: number) => post<{ routed: string; sent?: string[] }>(`/findings/${findingId}/notify`),
  costsSummary: () => get<CostsSummary>(scoped("/costs/summary")),
  setLimits: (limits: { daily_investigations?: number; per_case_budget?: number; per_case_wall_min?: number }) =>
    fetch(`${BASE}/settings/limits`, {
      method: "PUT",
      headers: { "Content-Type": "application/json", ...(getToken() ? { Authorization: `Bearer ${getToken()}` } : {}) },
      body: JSON.stringify(limits),
    }).then((r) => r.json()),
  // SSE URL for the live trace (EventSource cannot go through fetch)
  traceStreamUrl: (id: number) => `${BASE}/investigations/${id}/trace/stream`,
};
