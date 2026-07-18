// Typed client for the EchoLens FastAPI backend.
// Dev: Vite proxies "/api" → http://localhost:8000 (see vite.config.ts).
// Prod (split origins): set VITE_API_BASE to the backend URL at build time,
// e.g. VITE_API_BASE=https://echolens-api.onrender.com
const BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") || "/api";

// ── auth token (persisted) ──────────────────────────────────────────────
const TOKEN_KEY = "echolens_token";
let _token: string | null = localStorage.getItem(TOKEN_KEY);
let _onAuthError: (() => void) | null = null;

export function setToken(t: string | null): void {
  _token = t;
  if (t) localStorage.setItem(TOKEN_KEY, t);
  else localStorage.removeItem(TOKEN_KEY);
}
export function getToken(): string | null {
  return _token;
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
export interface Finding {
  id: number;
  status: string;
  summary: string;
  prose: string;
  confidence: number;
  supported_hypothesis: string | null;
  checked: string[];
  what_would_settle_it: string;
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
    lastPull: string;
    volume: string;
  }[];
  available: string[];
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
  review: (findingId: number, action: "approve" | "challenge", note = "") =>
    post<{ status: string; reopened_investigation_id?: number }>(`/findings/${findingId}/review`, {
      action,
      note,
    }),
  archive: () => get<{ rows: ArchiveRow[]; count: number; resolved_pct: number }>("/archive"),
  sources: () => get<SourcesResp>("/sources"),
  costsSummary: () => get<CostsSummary>("/costs/summary"),
  // SSE URL for the live trace (EventSource cannot go through fetch)
  traceStreamUrl: (id: number) => `${BASE}/investigations/${id}/trace/stream`,
};
