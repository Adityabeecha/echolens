"""Central configuration: budgets, tiers, model, pricing.

Budgets are enforced in deterministic code (investigator.guards / the check
node), never in prompts.
"""
from __future__ import annotations

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class BudgetTier(BaseModel):
    name: str
    max_iterations: int
    max_tool_calls: int
    max_tokens: int
    max_wall_clock_s: int
    max_cost_usd: float


BUDGET_TIERS: dict[str, BudgetTier] = {
    "quick": BudgetTier(
        name="quick", max_iterations=5, max_tool_calls=8,
        max_tokens=50_000, max_wall_clock_s=15 * 60, max_cost_usd=0.25,
    ),
    "standard": BudgetTier(
        name="standard", max_iterations=12, max_tool_calls=20,
        max_tokens=120_000, max_wall_clock_s=45 * 60, max_cost_usd=0.75,
    ),
    "deep": BudgetTier(
        name="deep", max_iterations=30, max_tool_calls=50,
        max_tokens=300_000, max_wall_clock_s=120 * 60, max_cost_usd=2.00,
    ),
}

# USD per 1M tokens (input, output) — used to compute llm_calls.cost.
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
}

# Hypothesis / evidence rules (PRD §5.2, §5.6)
MAX_ACTIVE_HYPOTHESES = 4
SUPPORT_CONFIDENCE = 0.80          # resolved requires >= this AND two-source rule
INSUFFICIENT_CONFIDENCE = 0.50     # below this at budget end -> insufficient_evidence
MIN_INDEPENDENT_EVIDENCE = 2       # two-source rule: >=2 items ...
MIN_DISTINCT_SOURCES = 2           # ... from >=2 distinct sources

# v2.0 budget extension: if the agent is THIS close at budget end, grant one
# extra allowance rather than giving up (capped, logged, once).
EXTENSION_CONFIDENCE = 0.65        # best hypothesis must be at least this promising
EXTENSION_FACTOR = 1.5             # one-time cap multiplier

# Tool output discipline (PRD §5.4): truncation lives in the tool layer.
TOOL_RESULT_MAX_ITEMS = 8
TOOL_SNIPPET_MAX_CHARS = 240

# Orchestrator daily caps (PRD §5.7). LLM proposes, code enforces.
ORCHESTRATOR_DAILY_INVESTIGATIONS = 5
ORCHESTRATOR_DAILY_COST_USD = 10.0


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = ""
    echolens_model: str = "gpt-4o-mini"
    echolens_db_url: str = "sqlite:///echolens.db"

    # deployment mode: dev (no auth) | staging | production
    echolens_env: str = "dev"

    # collector credentials (all optional; collectors are injectable/offline-testable)
    # NOTE: Reddit was removed as a live source (Reddit ended free API access in 2026).
    github_token: str = ""

    # collector schedule (cron-ish): hours between runs
    collector_interval_hours: int = 6

    # auth
    jwt_secret: str = "dev-insecure-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24

    # CORS: comma-separated allowed origins for the browser frontend.
    # e.g. "https://echolens.vercel.app"
    cors_origins: str = ""

    # Free-tier bootstrap (no shell needed): on startup, if the DB has no users
    # and these are set, create the first admin. Seed demo data if requested.
    bootstrap_admin_email: str = ""
    bootstrap_admin_password: str = ""
    seed_on_start: bool = False

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    _INSECURE_SECRETS = {"dev-insecure-change-me", "change-me-in-prod", ""}

    def check_production_ready(self) -> list[str]:
        """Return a list of misconfigurations that must be fixed before prod."""
        problems: list[str] = []
        if self.echolens_env == "production":
            if self.jwt_secret in self._INSECURE_SECRETS:
                problems.append("JWT_SECRET is unset or the insecure default — set a strong random value")
            if not self.openai_api_key:
                problems.append("OPENAI_API_KEY is not set")
            if not self.cors_list:
                problems.append("CORS_ORIGINS is empty — set your frontend origin(s)")
            if self.echolens_db_url.startswith("sqlite"):
                problems.append("ECHOLENS_DB_URL is SQLite — use Postgres in production")
        return problems

    # semantic search embedding backend: hash (zero-dep) | sentence-transformers
    embedding_backend: str = "hash"
    embedding_dim: int = 256

    # extra complaint themes to watch, comma-separated (adds to the built-in list)
    detector_extra_terms: str = ""

    # ── v4.0 delivery & actionability ───────────────────────────────────
    # Public base URL of the frontend, for deep links in alerts/tickets.
    app_base_url: str = ""
    alerts_enabled: bool = True
    # A finding at or above this severity is pinged instantly; below → digest.
    alert_instant_min_severity: float = 0.5
    # Slack incoming-webhook URL for finding/anomaly alerts (optional).
    slack_webhook_url: str = ""
    # Shared secret guarding the reply-to-act endpoint (Slack → review).
    slack_action_token: str = ""
    # On a Slack "approve", also open a GitHub issue automatically.
    auto_create_issue_on_approve: bool = False
    # Fallback repo for issue creation when a product has no GitHub source.
    github_default_repo: str = ""
    # Optional secret to verify GitHub webhook signatures (X-Hub-Signature-256).
    github_webhook_secret: str = ""
    # Email (optional). If smtp_host is unset, email delivery is skipped.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    alert_email_from: str = ""
    alert_email_to: str = ""

    @property
    def extra_theme_terms(self) -> list[str]:
        return [t.strip() for t in self.detector_extra_terms.split(",") if t.strip()]

    @property
    def auth_required(self) -> bool:
        return self.echolens_env != "dev"


settings = Settings()
