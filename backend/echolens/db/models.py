"""Storage schema (PRD §7) plus UI-driven fields (pause/escalate/manual cases).

SQLite in dev, Postgres (Supabase) later — everything here is portable.
`embedding` columns are nullable JSON placeholders reserving the pgvector
upgrade path; M1 search is keyword-based.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# ── corpus ──────────────────────────────────────────────────────────────


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32), default="play_store", index=True)
    ext_id: Mapped[str] = mapped_column(String(64), unique=True)
    rating: Mapped[int] = mapped_column(Integer, index=True)
    text: Mapped[str] = mapped_column(Text)
    version: Mapped[str | None] = mapped_column(String(32), index=True)
    os_version: Mapped[str | None] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(index=True)
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # v1.0: which tracked product/app this row belongs to (package name)
    product: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)


class Issue(Base):
    __tablename__ = "issues"

    id: Mapped[int] = mapped_column(primary_key=True)
    ext_id: Mapped[str] = mapped_column(String(64), unique=True)  # e.g. "#2841"
    title: Mapped[str] = mapped_column(Text)
    body_snippet: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(16), default="open")
    reactions: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(index=True)
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)
    labels: Mapped[list | None] = mapped_column(JSON, nullable=True)  # v1.0 GitHub labels
    product: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32), default="reddit")
    ext_id: Mapped[str] = mapped_column(String(64), unique=True)
    subreddit: Mapped[str | None] = mapped_column(String(64))
    text_snippet: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(index=True)
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)
    product: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)


class Release(Base):
    __tablename__ = "releases"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[str] = mapped_column(String(32), unique=True)
    notes: Mapped[str] = mapped_column(Text)
    released_at: Mapped[datetime] = mapped_column(index=True)
    product: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)


# ── v1.0 operational tables ─────────────────────────────────────────────


class Product(Base):
    """v8.0: the tenant of everything. Each product owns its own sources, corpus
    slice, anomalies, cases, patterns and budgets — nothing is global anymore."""
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    package_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    github_repo: Mapped[str | None] = mapped_column(String(256), nullable=True)
    is_demo: Mapped[bool] = mapped_column(default=False)
    # per-product budget overrides; falls back to the global defaults
    limits_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class CollectorState(Base):
    """One row per configured collector — its incremental watermark and health
    (PRD/roadmap v1.0). Lets ingestion be idempotent and observable."""
    __tablename__ = "collector_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32), index=True)      # play_store|github|reddit
    identifier: Mapped[str] = mapped_column(String(256))            # package / repo / subreddit
    product: Mapped[str | None] = mapped_column(String(128), nullable=True)
    watermark: Mapped[str | None] = mapped_column(String(64), nullable=True)  # ISO ts or ext_id cursor
    status: Mapped[str] = mapped_column(String(16), default="idle")  # idle|running|healthy|error
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(nullable=True)
    items_last_run: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(default=True)
    product_id: Mapped[int | None] = mapped_column(nullable=True, index=True)


class Setting(Base):
    """Workspace-level key/value settings (e.g. adjustable budget limits)."""
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)


class User(Base):
    """Auth principal with an RBAC role (v1.0). Passwords are bcrypt-hashed."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(16), default="viewer")  # admin|reviewer|viewer
    # v8.0: which product this user was last looking at (server-side, so a refresh
    # lands them back on it instead of re-showing the wizard)
    last_active_product_id: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


# ── investigation state ────────────────────────────────────────────────


class AnomalyEvent(Base):
    __tablename__ = "anomaly_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str | None] = mapped_column(String(64), unique=True)  # "demo1"
    type: Mapped[str] = mapped_column(String(64))  # negative_review_spike, ...
    metric: Mapped[str] = mapped_column(String(128))
    delta: Mapped[float] = mapped_column(Float)
    z: Mapped[float] = mapped_column(Float)
    window: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending|triaged|investigating|closed
    # v6.0: for a regression anomaly, the original resolved case it re-opens.
    parent_case_id: Mapped[int | None] = mapped_column(nullable=True)
    product_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    # v8.0 dedupe key: one anomaly per (product, metric, type, window)
    window_start: Mapped[datetime | None] = mapped_column(nullable=True)
    window_end: Mapped[datetime | None] = mapped_column(nullable=True)
    # when this row was superseded/merged into another anomaly
    merged_into_id: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class FixWatch(Base):
    """v6.0 closed-loop verification: links a finding's GitHub issue to the metric
    it should fix, then watches whether the fix actually worked.

    Lifecycle: issue_open → (issue closes) watching → confirmed | persists_reopened,
    and later possibly → regressed if the fixed theme re-spikes."""
    __tablename__ = "fix_watches"

    id: Mapped[int] = mapped_column(primary_key=True)
    finding_id: Mapped[int] = mapped_column(ForeignKey("findings.id"), index=True)
    investigation_id: Mapped[int] = mapped_column(ForeignKey("investigations.id"), index=True)
    repo: Mapped[str] = mapped_column(String(256))
    issue_number: Mapped[int] = mapped_column(Integer, index=True)
    issue_url: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(24), default="issue_open")
    terms: Mapped[list] = mapped_column(JSON, default=list)   # theme keywords being watched
    metric: Mapped[str] = mapped_column(String(160), default="")
    window_days: Mapped[int] = mapped_column(Integer, default=14)
    fix_date: Mapped[datetime | None] = mapped_column(nullable=True)      # when the issue closed
    baseline_rate: Mapped[float | None] = mapped_column(Float, nullable=True)  # pre-fix complaint rate
    post_rate: Mapped[float | None] = mapped_column(Float, nullable=True)      # post-fix complaint rate
    confirmed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    chart_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # before/after series
    product_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class TriageDecision(Base):
    """One orchestrator ruling on one anomaly (PRD §4.1): investigate / ignore /
    merge. First-class so the Case Feed can show *why* something was not pursued."""
    __tablename__ = "triage_decisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    anomaly_id: Mapped[int] = mapped_column(ForeignKey("anomaly_events.id"), index=True)
    decision: Mapped[str] = mapped_column(String(16))  # investigate|ignore|merge
    reason: Mapped[str] = mapped_column(Text, default="")
    budget_tier: Mapped[str | None] = mapped_column(String(16), nullable=True)
    merge_into_anomaly_id: Mapped[int | None] = mapped_column(
        ForeignKey("anomaly_events.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Investigation(Base):
    __tablename__ = "investigations"

    id: Mapped[int] = mapped_column(primary_key=True)
    anomaly_id: Mapped[int | None] = mapped_column(ForeignKey("anomaly_events.id"))
    status: Mapped[str] = mapped_column(String(32), default="running")
    # running|resolved|insufficient_evidence|needs_human|budget_exhausted
    opened_by: Mapped[str] = mapped_column(String(16), default="anomaly")  # anomaly|manual
    budget_tier: Mapped[str] = mapped_column(String(16), default="standard")
    budget_json: Mapped[dict] = mapped_column(JSON, default=dict)
    paused: Mapped[bool] = mapped_column(default=False)
    escalated: Mapped[bool] = mapped_column(default=False)
    # set when this case was re-opened by a human challenge (PRD §4.1)
    reopens_investigation_id: Mapped[int | None] = mapped_column(nullable=True)
    # v1.0 recovery: serialized loop state, refreshed each iteration
    checkpoint_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # v3.0: data-availability caveats captured at start (e.g. a stale source), so
    # the finding can disclose what was unavailable during the investigation.
    data_notes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    product_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(nullable=True)


class HypothesisRow(Base):
    __tablename__ = "hypotheses"

    id: Mapped[int] = mapped_column(primary_key=True)
    investigation_id: Mapped[int] = mapped_column(ForeignKey("investigations.id"), index=True)
    hid: Mapped[str] = mapped_column(String(8))  # "H1"
    statement: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active|supported|rejected
    json: Mapped[dict] = mapped_column(JSON, default=dict)  # evidence_for/against, next_test


class EvidenceRow(Base):
    __tablename__ = "evidence"

    id: Mapped[int] = mapped_column(primary_key=True)
    investigation_id: Mapped[int] = mapped_column(ForeignKey("investigations.id"), index=True)
    eid: Mapped[str] = mapped_column(String(12))  # "ev_007"
    source: Mapped[str] = mapped_column(String(32))
    ref: Mapped[str] = mapped_column(String(128))  # re-retrievable pointer
    snippet: Mapped[str] = mapped_column(Text)
    retrieved_by: Mapped[str] = mapped_column(Text)
    json: Mapped[dict] = mapped_column(JSON, default=dict)  # supports/contradicts


class TraceStep(Base):
    __tablename__ = "trace_steps"

    id: Mapped[int] = mapped_column(primary_key=True)
    investigation_id: Mapped[int] = mapped_column(ForeignKey("investigations.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(8))  # THINK|TOOL|EVID|UPDT|FAIL|CHECK
    content_json: Mapped[dict] = mapped_column(JSON, default=dict)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[int] = mapped_column(primary_key=True)
    investigation_id: Mapped[int] = mapped_column(ForeignKey("investigations.id"), index=True)
    summary: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft|approved|challenged
    json: Mapped[dict] = mapped_column(JSON, default=dict)  # prose, claim->evidence map, what_would_settle_it
    product_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(primary_key=True)
    finding_id: Mapped[int] = mapped_column(ForeignKey("findings.id"), index=True)
    action: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text, default="")
    effort: Mapped[str] = mapped_column(String(8), default="MED")
    impact: Mapped[str] = mapped_column(String(8), default="MED")
    rank: Mapped[int] = mapped_column(Integer, default=1)


class ReviewFeedback(Base):
    __tablename__ = "review_feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    finding_id: Mapped[int] = mapped_column(ForeignKey("findings.id"), index=True)
    action: Mapped[str] = mapped_column(String(16))  # approve|challenge
    note: Mapped[str] = mapped_column(Text, default="")
    user_id: Mapped[int | None] = mapped_column(nullable=True)  # v1.0 audit: who acted
    # v5.0 challenge autopsy: structured reason category (wrong_cause|weak_evidence|
    # wrong_severity|already_knew) so failure modes roll up into visible weak spots.
    reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class LLMCall(Base):
    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    investigation_id: Mapped[int | None] = mapped_column(ForeignKey("investigations.id"), index=True)
    agent: Mapped[str] = mapped_column(String(32))  # investigator.plan, orchestrator, ...
    model: Mapped[str] = mapped_column(String(64), default="")
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
