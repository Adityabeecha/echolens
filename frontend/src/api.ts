// Typed client for the EchoLens FastAPI backend.
// Dev: Vite proxies "/api" → http://localhost:8000 (see vite.config.ts).
// Prod (split origins): set VITE_API_BASE to the backend URL at build time,
// e.g. VITE_API_BASE=https://echolens-api.onrender.com
const BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") || "/api";

// ── auth token (persisted) ──────────────────────────────────────────────
const TOKEN_KEY = "echolens_token";
let _token: string | null = localStorage.getItem(TOKEN_KEY);
let _onAuthError: (() => void) | null = null;

const ROLE_KEY = "echolens_role";
let _role: string = localStorage.getItem(ROLE_KEY) || "viewer";

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
    lastPull: string;
    volume: string;
    error?: string | null;
  }[];
  available: string[];
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
  weak_spots: { total_challenges: number; spots: WeakSpot[] };
}

// v6.0 patterns + product-health overview
export interface Pattern {
  terms: string[];
  trigger: string;
  cause: string;
  fix: string;
  verified_count: number;
  cases: number[];
}
export interface Overview {
  open_problems: { investigation_id: number; summary: string; impact_score: number; affected_pct: number }[];
  open_problem_count: number;
  in_verification: number;
  confirmed_fixes_total: number;
  confirmed_fixes_quarter: number;
  regressions: number;
  mean_days_to_confirmed_fix: number | null;
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
  collect: () => post("/collect/run"),
  scan: () => post<{ detected: string[] }>("/anomalies/scan"),
  anomalies: () => get<{ anomalies: Anomaly[] }>("/anomalies"),
  triage: (run = false) => post(`/anomalies/triage?run=${run}`),
  feedSummary: () => get<FeedSummary>("/feed/summary"),
  investigations: () =>
    get<{ investigations: { id: number; status: string; opened_by: string; anomaly_id: number | null }[] }>(
      "/investigations"
    ),
  investigation: (id: number) => get<Investigation>(`/investigations/${id}`),
  trace: (id: number, after = 0) =>
    get<{ status: string; steps: TraceStep[] }>(`/investigations/${id}/trace?after=${after}`),
  startInvestigation: (body: { anomaly_slug?: string; description?: string; tier?: string }) =>
    post<{ status: string; investigation_id: number; anomaly_id: number }>("/investigations", body),
  review: (findingId: number, action: "approve" | "challenge", note = "", reason?: string) =>
    post<{ status: string; reopened_investigation_id?: number }>(`/findings/${findingId}/review`, {
      action,
      note,
      reason,
    }),
  calibration: () => get<Calibration>("/calibration"),
  patterns: () => get<{ patterns: Pattern[] }>("/patterns"),
  overview: () => get<Overview>("/overview"),
  chat: (message: string) => post<ChatResponse>("/chat", { message }),
  brief: () => get<WeeklyBrief>("/brief"),
  themes: () => get<{ themes: ThemeLifecycle[] }>("/themes"),
  findingFollowup: (findingId: number, question: string) =>
    post<{ question: string; answer: string; investigation_id: number }>(`/findings/${findingId}/followup`, { question }),
  pause: (id: number) => post(`/investigations/${id}/pause`),
  resume: (id: number) => post(`/investigations/${id}/resume`),
  escalate: (id: number) => post(`/investigations/${id}/escalate`),
  archive: () => get<{ rows: ArchiveRow[]; count: number; resolved_pct: number }>("/archive"),
  sources: () => get<SourcesResp>("/sources"),
  connectSource: (source: string, identifier: string, product?: string) =>
    post<{ connected: { source: string; identifier: string; product: string } }>("/sources/connect", {
      source,
      identifier,
      product,
    }),
  collectorsRun: () => post<{ results: { source: string; identifier: string; fetched: number; inserted: number; error: string | null }[] }>("/collectors/run"),
  embed: () => post<{ embedded: Record<string, number> }>("/search/embed"),
  onboard: (body: { play_store: string; github?: string; product?: string }) =>
    post<{ status: string; product: string; play_store: string; github: string | null }>("/onboard", body),
  onboardStatus: (product: string) =>
    get<OnboardStatus>(`/onboard/status?product=${encodeURIComponent(product)}`),
  snapshot: (product?: string) =>
    get<Snapshot>(`/snapshot${product ? `?product=${encodeURIComponent(product)}` : ""}`),
  findingIssue: (findingId: number) =>
    get<{ title: string; body: string; repo: string | null }>(`/findings/${findingId}/issue`),
  createGithubIssue: (findingId: number) =>
    post<{ repo: string; number: number; url: string }>(`/findings/${findingId}/github-issue`),
  notifyFinding: (findingId: number) => post<{ routed: string; sent?: string[] }>(`/findings/${findingId}/notify`),
  costsSummary: () => get<CostsSummary>("/costs/summary"),
  setLimits: (limits: { daily_investigations?: number; per_case_budget?: number; per_case_wall_min?: number }) =>
    fetch(`${BASE}/settings/limits`, {
      method: "PUT",
      headers: { "Content-Type": "application/json", ...(getToken() ? { Authorization: `Bearer ${getToken()}` } : {}) },
      body: JSON.stringify(limits),
    }).then((r) => r.json()),
  // SSE URL for the live trace (EventSource cannot go through fetch)
  traceStreamUrl: (id: number) => `${BASE}/investigations/${id}/trace/stream`,
};
