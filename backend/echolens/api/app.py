"""FastAPI surface (PRD §8) + M2 additions (triage, recommend).

Investigations run in a background thread with their own DB session so the
trace endpoints can tail progress live (poll or SSE) — this is what the
Milestone-3 Investigation screen consumes.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any

from contextlib import asynccontextmanager
from datetime import date, datetime, timezone

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import func, select

from echolens.config import (
    BUDGET_TIERS,
    EXTENSION_FACTOR,
    ORCHESTRATOR_DAILY_INVESTIGATIONS,
    settings,
)
from echolens.db.models import (
    AnomalyEvent,
    EvidenceRow,
    Finding,
    HypothesisRow,
    Investigation,
    Issue,
    LLMCall,
    Recommendation,
    Release,
    Review,
    ReviewFeedback,
    Setting,
    TraceStep,
    TriageDecision,
)
from echolens.db.session import init_db, session_scope
from echolens.logging import get_logger
from echolens.timeutil import aware_utc

@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Fail fast on an insecure production config (v1.0).
    problems = settings.check_production_ready()
    if problems:
        raise RuntimeError("refusing to start in production: " + "; ".join(problems))
    init_db()
    _bootstrap()  # free-tier: seed + first admin from env, no shell needed
    # v1.0: resume any investigation interrupted by the last shutdown.
    try:
        from echolens.investigator.recover import resume_running
        with session_scope() as s:
            recovered = resume_running(s)
        if recovered:
            log.info("startup_recovery", investigations=recovered)
    except Exception as err:  # never block startup on recovery
        log.error("startup_recovery_failed", error=str(err))
    yield


def _bootstrap() -> None:
    """Seed demo data and/or create the first admin from env vars, so a shell-
    less free-tier deploy is self-sufficient. Both steps are idempotent."""
    from echolens.auth import create_user
    from echolens.db.models import Review, User

    try:
        with session_scope() as s:
            if settings.seed_on_start and s.scalar(select(Review).limit(1)) is None:
                from echolens.synthetic.generate import generate
                generate(s)
                log.info("bootstrap_seeded")
            if settings.bootstrap_admin_email and settings.bootstrap_admin_password:
                if s.scalar(select(User).limit(1)) is None:
                    create_user(s, settings.bootstrap_admin_email,
                                settings.bootstrap_admin_password, "admin")
                    log.info("bootstrap_admin_created", email=settings.bootstrap_admin_email)
    except Exception as err:
        log.error("bootstrap_failed", error=str(err))


limiter = Limiter(key_func=get_remote_address, default_limits=["240/minute"])
app = FastAPI(title="EchoLens API", version="1.0.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
log = get_logger("api")

# CORS: explicit allowlist in prod; permissive in dev for localhost tooling.
_cors_origins = settings.cors_list or (["*"] if settings.echolens_env == "dev" else [])
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,  # auth is via Authorization bearer header, not cookies
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── serializers ────────────────────────────────────────────────────────

def _anomaly_headline(session, a: AnomalyEvent) -> str:
    """A PM-readable problem statement, not a metric name. The metric + z stay as
    secondary metadata on the card."""
    metric = (a.metric or "").strip()
    if a.type == "manual":
        return (a.description or "Manual case").strip()
    if a.type == "regression":
        return f"Regression — “{metric}” came back after being fixed"
    if a.type == "fix_regression":
        return f"Fix didn't hold — “{metric}” complaints continue"
    if a.type == "theme_volume_surge":
        label = metric.split(" share of")[0].split(" on ")[0].strip() or "complaints"
        return f"{label[:1].upper()}{label[1:]} rising"
    if a.type == "issue_velocity_surge":
        label = metric.split(" per week")[0].strip() or "issue reports"
        return f"{label[:1].upper()}{label[1:]} piling up on GitHub"
    if a.type == "rating_drop":
        return "Average rating falling"
    if a.type == "negative_review_spike":
        # name the theme driving it when a matching theme surge was detected
        stmt = select(AnomalyEvent).where(AnomalyEvent.type == "theme_volume_surge")
        if a.product_id is not None:
            stmt = stmt.where(AnomalyEvent.product_id == a.product_id)
        theme = session.scalars(stmt.order_by(AnomalyEvent.z.desc())).first()
        if theme is not None:
            label = (theme.metric or "").split(" share of")[0].strip()
            if label:
                return f"1-star reviews spiking — {label} driving it"
        return "1-star reviews spiking"
    return metric or "Signal detected"


def _anomaly_dict(session, a: AnomalyEvent) -> dict:
    td = session.scalars(
        select(TriageDecision).where(TriageDecision.anomaly_id == a.id)
        .order_by(TriageDecision.id.desc())
    ).first()
    inv = session.scalars(
        select(Investigation).where(Investigation.anomaly_id == a.id)
        .order_by(Investigation.id.desc())
    ).first()
    return {
        "slug": a.slug, "type": a.type, "metric": a.metric, "delta": a.delta,
        "z": a.z, "window": a.window, "description": a.description, "status": a.status,
        "headline": _anomaly_headline(session, a), "product_id": a.product_id,
        "triage": None if td is None else {
            "decision": td.decision, "reason": td.reason, "budget_tier": td.budget_tier,
            "merge_into_anomaly_id": td.merge_into_anomaly_id,
        },
        "investigation_id": inv.id if inv else None,
    }


def _investigation_dict(session, inv: Investigation) -> dict:
    hyps = session.scalars(select(HypothesisRow).where(
        HypothesisRow.investigation_id == inv.id)).all()
    evs = session.scalars(select(EvidenceRow).where(
        EvidenceRow.investigation_id == inv.id)).all()
    finding = session.scalars(select(Finding).where(
        Finding.investigation_id == inv.id).order_by(Finding.id.desc())).first()
    recs = []
    if finding is not None:
        recs = session.scalars(select(Recommendation).where(
            Recommendation.finding_id == finding.id).order_by(Recommendation.rank)).all()
    anomaly = session.get(AnomalyEvent, inv.anomaly_id) if inv.anomaly_id else None
    title = "Investigation"
    if anomaly is not None:
        title = anomaly.description if anomaly.type == "manual" else anomaly.metric
    return {
        "id": inv.id, "anomaly_id": inv.anomaly_id, "status": inv.status,
        "title": title,
        "opened_by": inv.opened_by, "budget_tier": inv.budget_tier,
        "budget": inv.budget_json, "paused": inv.paused, "escalated": inv.escalated,
        "reopens_investigation_id": inv.reopens_investigation_id,
        "data_notes": inv.data_notes or [],
        "hypotheses": [{"id": h.hid, "statement": h.statement, "confidence": h.confidence,
                        "status": h.status, **h.json} for h in hyps],
        "evidence": [{"id": e.eid, "source": e.source, "ref": e.ref, "snippet": e.snippet,
                      "retrieved_by": e.retrieved_by, **e.json} for e in evs],
        "finding": None if finding is None else {
            "id": finding.id, "status": finding.status, **finding.json,
            **_finding_extras(session, finding, recs, inv.status)},
        "recommendations": [{"rank": r.rank, "action": r.action, "impact": r.impact,
                             "effort": r.effort, "rationale": r.rationale} for r in recs],
    }


def _finding_extras(session, finding, recs, status: str) -> dict:
    """The decision doc + severity (v4.0) plus the fix-verification status (v6.0),
    so the UI can show What's broken / How bad / What to do and — once a fix
    ships — a confirmed-fix badge with a before/after chart."""
    from echolens.db.models import FixWatch
    from echolens.impact import decision_doc, severity
    fj = finding.json or {}
    impact = fj.get("impact", {})
    watch = session.scalars(select(FixWatch).where(
        FixWatch.finding_id == finding.id).order_by(FixWatch.id.desc())).first()
    fix = None
    if watch is not None:
        fix = {"status": watch.status, "issue_number": watch.issue_number,
               "issue_url": watch.issue_url, "chart": watch.chart_json,
               "baseline_rate": watch.baseline_rate, "post_rate": watch.post_rate}
    return {
        "decision": decision_doc(fj, list(recs), impact, status),
        "severity": severity(float(fj.get("confidence", 0.0)), impact),
        "fix": fix,
    }


def _trace_dict(t: TraceStep) -> dict:
    return {"seq": t.seq, "kind": t.kind, "content": t.content_json,
            "tokens": t.tokens, "ms": t.ms}


# ── background investigation runner ────────────────────────────────────

def _try_notify(session, finding) -> None:
    """Auto-deliver a concluded finding by severity (v4.0). Never let a delivery
    failure affect the investigation result."""
    try:
        from echolens.notify import notify_finding
        result = notify_finding(session, finding)
        log.info("finding_notified", finding_id=finding.id, routed=result.get("routed"))
    except Exception as err:
        log.error("notify_failed", finding_id=finding.id, error=str(err))


def _run_investigation_bg(investigation_id: int, tier: str) -> None:
    """Run the loop on an investigation row that was already created (so the
    POST could return its id immediately for the UI to jump to)."""
    from echolens.investigator.graph import Investigator
    from echolens.recommender.recommend import recommend

    with session_scope() as session:
        inv_row = session.get(Investigation, investigation_id)
        anomaly = session.get(AnomalyEvent, inv_row.anomaly_id)
        anomaly.status = "investigating"
        inv = Investigator(session, anomaly, tier=tier,
                           existing_investigation=inv_row).run()
        finding = session.scalars(select(Finding).where(
            Finding.investigation_id == inv.id).order_by(Finding.id.desc())).first()
        if finding is not None:
            recommend(session, finding)
            _try_notify(session, finding)


# ── endpoints ──────────────────────────────────────────────────────────

from echolens.auth import authenticate, create_token, create_user, current_user, require_role


class SignupBody(BaseModel):
    email: str
    password: str
    role: str = "viewer"


class LoginBody(BaseModel):
    email: str
    password: str


@app.post("/auth/signup")
def auth_signup(body: SignupBody, request: Request) -> dict:
    """User creation. In production the FIRST admin must come from the
    BOOTSTRAP_ADMIN_* env (not open self-service) — otherwise a stranger could
    claim admin by being first to hit this endpoint. After an admin exists, only
    an admin may create users. In dev, the first signup bootstraps an admin."""
    from echolens.db.models import User
    with session_scope() as session:
        first_user = session.scalar(select(User).limit(1)) is None
        if first_user:
            if settings.echolens_env == "production":
                raise HTTPException(
                    403,
                    "Open signup is disabled in production. Create the first admin via the "
                    "BOOTSTRAP_ADMIN_EMAIL / BOOTSTRAP_ADMIN_PASSWORD environment variables.",
                )
            role = "admin"  # dev bootstrap
        else:
            caller = current_user(request)  # 401 without a token in prod
            if caller["role"] != "admin":
                raise HTTPException(403, "only an admin can create users")
            role = body.role
        try:
            user = create_user(session, body.email, body.password, role)
        except ValueError as err:
            raise HTTPException(422, str(err))
        return {"id": user.id, "email": user.email, "role": user.role,
                "token": create_token(user)}


@app.post("/auth/login")
def auth_login(body: LoginBody) -> dict:
    with session_scope() as session:
        user = authenticate(session, body.email, body.password)
        if user is None:
            raise HTTPException(401, "invalid credentials")
        return {"token": create_token(user), "role": user.role}


@app.get("/auth/me")
def auth_me(user: dict = Depends(current_user)) -> dict:
    return user


# ── v8.0: products are the scope of everything ──────────────────────────

def _scope(session, product_id: int | None):
    """The product this request is scoped to: the explicit id, else the first
    product. Returns None only when no products exist at all."""
    from echolens.db.models import Product
    if product_id is not None:
        p = session.get(Product, product_id)
        if p is not None:
            return p
    return session.scalars(select(Product).order_by(Product.id)).first()


def _product_dict(p) -> dict:
    return {"id": p.id, "name": p.name, "package_name": p.package_name,
            "github_repo": p.github_repo, "is_demo": p.is_demo,
            "created_at": p.created_at.isoformat() if p.created_at else None}


@app.get("/products")
def list_products(user: dict = Depends(current_user)) -> dict:
    """Every product + the caller's last-active one. The client uses this on boot
    to decide between the Case Feed and the add-product wizard (server-derived)."""
    from echolens.db.models import Product, User
    with session_scope() as session:
        rows = session.scalars(select(Product).order_by(Product.id)).all()
        active = None
        uid = user.get("id")
        if uid:
            u = session.get(User, uid)
            if u and u.last_active_product_id:
                active = u.last_active_product_id
        if active not in {p.id for p in rows}:
            active = rows[0].id if rows else None
        return {"products": [_product_dict(p) for p in rows], "active_product_id": active}


class ProductBody(BaseModel):
    name: str
    package_name: str | None = None
    github_repo: str | None = None


@app.post("/products")
def create_product(body: ProductBody, user: dict = Depends(require_role("admin"))) -> dict:
    from echolens.db.models import Product
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "a product needs a name")
    with session_scope() as session:
        if session.scalars(select(Product).where(Product.name == name)).first():
            raise HTTPException(409, f"a product named '{name}' already exists")
        p = Product(name=name, package_name=body.package_name, github_repo=body.github_repo)
        session.add(p)
        session.flush()
        return _product_dict(p)


@app.post("/products/{product_id}/activate")
def activate_product(product_id: int, user: dict = Depends(current_user)) -> dict:
    """Persist the caller's active product server-side so a refresh returns here."""
    from echolens.db.models import Product, User
    with session_scope() as session:
        p = session.get(Product, product_id)
        if p is None:
            raise HTTPException(404, "no such product")
        uid = user.get("id")
        if uid:
            u = session.get(User, uid)
            if u is not None:
                u.last_active_product_id = product_id
        return {"active_product_id": product_id, "name": p.name}


@app.delete("/products/{product_id}")
def delete_product(product_id: int, confirm: str = "",
                   user: dict = Depends(require_role("admin"))) -> dict:
    """Delete a product and cascade its data. Requires ?confirm=<exact name>."""
    from echolens.db.models import (
        AnomalyEvent, CollectorState, EvidenceRow, Finding, FixWatch, HypothesisRow,
        Investigation, Issue, LLMCall, Post, Product, Recommendation, Release,
        Review, ReviewFeedback, TraceStep, TriageDecision, User)
    with session_scope() as session:
        p = session.get(Product, product_id)
        if p is None:
            raise HTTPException(404, "no such product")
        if confirm.strip() != p.name:
            raise HTTPException(422, f"type the product name exactly to confirm deletion ('{p.name}')")
        name = p.name
        inv_ids = [i.id for i in session.scalars(select(Investigation).where(
            Investigation.product_id == product_id)).all()]
        find_ids = [f.id for f in session.scalars(select(Finding).where(
            Finding.product_id == product_id)).all()]
        anom_ids = [a.id for a in session.scalars(select(AnomalyEvent).where(
            AnomalyEvent.product_id == product_id)).all()]

        def _purge(model, col, ids):
            if ids:
                for row in session.scalars(select(model).where(col.in_(ids))).all():
                    session.delete(row)

        _purge(ReviewFeedback, ReviewFeedback.finding_id, find_ids)
        _purge(Recommendation, Recommendation.finding_id, find_ids)
        _purge(TraceStep, TraceStep.investigation_id, inv_ids)
        _purge(HypothesisRow, HypothesisRow.investigation_id, inv_ids)
        _purge(EvidenceRow, EvidenceRow.investigation_id, inv_ids)
        _purge(LLMCall, LLMCall.investigation_id, inv_ids)
        _purge(TriageDecision, TriageDecision.anomaly_id, anom_ids)
        for model in (FixWatch, Finding, Investigation, AnomalyEvent, CollectorState):
            for row in session.scalars(select(model).where(model.product_id == product_id)).all():
                session.delete(row)
        for model in (Review, Issue, Post, Release):
            for row in session.scalars(select(model).where(model.product == name)).all():
                session.delete(row)
        for u in session.scalars(select(User).where(User.last_active_product_id == product_id)).all():
            u.last_active_product_id = None
        session.delete(p)
        return {"deleted": name}


@app.get("/health")
def health() -> dict:
    ok = True
    try:
        with session_scope() as s:
            s.execute(select(AnomalyEvent).limit(1))
    except Exception:
        ok = False
    return {"db": ok, "llm_key_present": bool(settings.openai_api_key),
            "model": settings.echolens_model}


@app.post("/collect/run")
def collect_run() -> dict:
    """Dev convenience: seed the synthetic corpus if empty (real collectors are M3)."""
    from echolens.db.models import Review
    from echolens.synthetic.generate import generate
    with session_scope() as session:
        if session.scalar(select(Review).limit(1)) is not None:
            return {"status": "already_populated"}
        counts = generate(session)
    return {"status": "seeded", "counts": counts}


class ConnectSource(BaseModel):
    source: str            # play_store | github
    identifier: str        # package name / repo
    product: str | None = None


@app.post("/sources/connect")
def connect_source(body: ConnectSource, user: dict = Depends(require_role("admin"))) -> dict:
    """Register a real data source (v1.0). Collection happens on the schedule
    or via POST /collectors/run."""
    from echolens.collectors.registry import add_source
    with session_scope() as session:
        try:
            st = add_source(session, body.source, body.identifier, body.product)
        except ValueError as err:
            raise HTTPException(422, str(err))
        return {"connected": {"source": st.source, "identifier": st.identifier, "product": st.product}}


@app.post("/collectors/run")
def collectors_run(user: dict = Depends(require_role("reviewer"))) -> dict:
    """Run every configured collector once (deterministic, no LLM)."""
    from echolens.collectors.registry import run_all
    with session_scope() as session:
        results = run_all(session)
        return {"results": [
            {"source": r.source, "identifier": r.identifier, "fetched": r.fetched,
             "inserted": r.inserted, "error": r.error} for r in results]}


class RetryBody(BaseModel):
    source: str
    identifier: str


@app.post("/collectors/retry")
def collectors_retry(body: RetryBody, user: dict = Depends(require_role("reviewer"))) -> dict:
    """Retry ONE source now (the 'Retry now' action on a stale/failed source)."""
    from echolens.collectors.registry import SourceConfig
    with session_scope() as session:
        from echolens.db.models import CollectorState
        st = session.scalars(select(CollectorState).where(
            CollectorState.source == body.source,
            CollectorState.identifier == body.identifier)).first()
        if st is None:
            raise HTTPException(404, "no such source")
        res = SourceConfig(st.source, st.identifier, st.product).build().run(session)
        return {"source": res.source, "identifier": res.identifier,
                "inserted": res.inserted, "error": res.error}


@app.get("/collectors")
def collectors_health() -> dict:
    from echolens.db.models import CollectorState
    with session_scope() as session:
        rows = session.scalars(select(CollectorState)).all()
        return {"collectors": [
            {"source": c.source, "identifier": c.identifier, "product": c.product,
             "status": c.status, "watermark": c.watermark, "items_last_run": c.items_last_run,
             "last_error": c.last_error,
             "last_run_at": c.last_run_at.isoformat() if c.last_run_at else None,
             "enabled": c.enabled} for c in rows]}


def _data_notes(session) -> list[str]:
    """Disclosure strings for any source that is stale RIGHT NOW, captured when an
    investigation starts so its finding can say what was unavailable."""
    from echolens.collectors.registry import source_health
    notes = []
    for h in source_health(session):
        if h["stale"]:
            label = _SOURCE_META.get(h["source"], {}).get("label", h["source"])
            when = f" since {h['stale_since']}" if h.get("stale_since") else ""
            notes.append(f"{label} ({h['identifier']}) was unavailable{when} during this "
                         f"investigation — conclusions may be incomplete.")
    return notes


def _onboard_bg(product: str, product_id: int | None = None) -> None:
    """Hands-off backfill: pull every configured source once, then scan. Runs in
    a thread so POST /onboard returns immediately and the wizard can poll."""
    from echolens.collectors.registry import run_all
    from echolens.detector.detect import scan
    try:
        with session_scope() as session:
            run_all(session, limit=300)  # 90-day-ish backfill for a first run
        with session_scope() as session:
            scan(session, product=product, product_id=product_id)
        log.info("onboard_backfill_done", product=product)
    except Exception as err:  # never crash the worker; the source shows its error
        log.error("onboard_backfill_failed", product=product, error=str(err))


class OnboardBody(BaseModel):
    play_store: str
    github: str | None = None
    product: str | None = None


@app.post("/onboard")
def onboard(body: OnboardBody, user: dict = Depends(require_role("admin"))) -> dict:
    """Add a real product in one shot: validate the inputs, register the sources,
    and kick off a hands-off backfill. The wizard then polls /onboard/status."""
    from echolens.collectors.registry import add_source
    from echolens.onboarding.validate import normalize_github_repo, validate_play_store_package

    err = validate_play_store_package(body.play_store)
    if err:
        raise HTTPException(422, err)
    repo, gerr = normalize_github_repo(body.github)
    if gerr:
        raise HTTPException(422, gerr)
    product = (body.product or "").strip() or body.play_store.strip()
    with session_scope() as session:
        from echolens.db.models import Product
        prod = session.scalars(select(Product).where(Product.name == product)).first()
        if prod is None:
            prod = Product(name=product, package_name=body.play_store.strip(), github_repo=repo)
            session.add(prod)
            session.flush()
        pid = prod.id
        st = add_source(session, "play_store", body.play_store.strip(), product)
        st.product_id = pid
        if repo:
            st2 = add_source(session, "github", repo, product)
            st2.product_id = pid
    threading.Thread(target=_onboard_bg, args=(product, pid), daemon=True).start()
    return {"status": "backfilling", "product": product, "product_id": pid,
            "play_store": body.play_store.strip(), "github": repo}


@app.get("/onboard/status")
def onboard_status(product: str) -> dict:
    """Live view for the onboarding wait screen: source health, whether the
    backfill is still running, the health snapshot so far, and any anomalies
    already surfaced."""
    from echolens.collectors.registry import source_health
    from echolens.onboarding.snapshot import health_snapshot
    with session_scope() as session:
        health = source_health(session, product=product)
        # "backfilling" until every source has at least completed one run
        backfilling = any(h["status"] in ("idle", "running") and h["never_collected"]
                          for h in health) or any(h["status"] == "running" for h in health)
        snap = health_snapshot(session, product=product)
        anomalies = [_anomaly_dict(session, a) for a in session.scalars(
            select(AnomalyEvent).where(AnomalyEvent.status == "pending").order_by(AnomalyEvent.id)).all()]
        return {"product": product, "backfilling": backfilling, "sources": health,
                "snapshot": snap, "anomalies": anomalies}


@app.post("/import/reviews")
async def import_reviews(file: UploadFile = File(...), product: str = "", source: str = "csv",
                        user: dict = Depends(require_role("admin"))) -> dict:
    """Import a CSV of reviews from any export (App Store, Zendesk, spreadsheet).
    Widens the evidence base beyond the live scrapers. Idempotent by content hash."""
    from echolens.importers.csv_reviews import import_reviews_csv
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1", errors="replace")
    with session_scope() as session:
        result = import_reviews_csv(session, text, product=(product or None), source=(source or "csv"))
    return result


@app.get("/snapshot")
def snapshot(product: str | None = None, product_id: int | None = None, days: int = 90) -> dict:
    """Health snapshot for a product (or the whole corpus) — powers the
    'Investigate now on anything' entry point outside onboarding."""
    from echolens.onboarding.snapshot import health_snapshot
    with session_scope() as session:
        if product is None:
            p = _scope(session, product_id)
            product = p.name if p else None
        return health_snapshot(session, product=product, days=days)


@app.post("/search/embed")
def search_embed(user: dict = Depends(require_role("admin"))) -> dict:
    """Backfill embeddings over the corpus so semantic search activates (v1.0)."""
    from echolens.search.semantic import embed_corpus
    with session_scope() as session:
        return {"embedded": embed_corpus(session)}


@app.post("/anomalies/scan")
def anomalies_scan(product_id: int | None = None) -> dict:
    from echolens.detector.detect import scan
    with session_scope() as session:
        p = _scope(session, product_id)
        events = scan(session, product=(p.name if p else None), product_id=(p.id if p else None))
        return {"detected": [e.slug for e in events], "product": p.name if p else None}


@app.get("/anomalies")
def list_anomalies(product_id: int | None = None) -> dict:
    with session_scope() as session:
        p = _scope(session, product_id)
        stmt = select(AnomalyEvent).where(AnomalyEvent.merged_into_id.is_(None))
        if p is not None:
            stmt = stmt.where(AnomalyEvent.product_id == p.id)
        rows = session.scalars(stmt.order_by(AnomalyEvent.id)).all()
        return {"anomalies": [_anomaly_dict(session, a) for a in rows]}


@app.post("/anomalies/triage")
@limiter.limit("10/minute")
def anomalies_triage(request: Request, run: bool = False, product_id: int | None = None,
                     user: dict = Depends(require_role("reviewer"))) -> dict:
    from echolens.orchestrator.triage import Orchestrator
    to_run: list[tuple[int, str]] = []
    skipped_already_triaged = 0
    with session_scope() as session:
        p = _scope(session, product_id)
        pid = p.id if p else None
        decisions = Orchestrator(session, daily_limit=_daily_limit(session, pid),
                                 product_id=pid).triage()
        out = [{"anomaly": d.anomaly.slug, "decision": d.decision, "reason": d.reason,
                "budget_tier": d.budget_tier,
                "merge_into": d.merge_into.slug if d.merge_into else None} for d in decisions]
        if run:
            for d in decisions:
                if d.decision != "investigate":
                    continue
                # Idempotency guard: never open a SECOND case for an anomaly that
                # already has one (this is what caused duplicate cases on re-triage).
                existing = session.scalars(select(Investigation).where(
                    Investigation.anomaly_id == d.anomaly.id)).first()
                if existing is not None:
                    skipped_already_triaged += 1
                    continue
                tier = d.budget_tier or "standard"
                inv = Investigation(anomaly_id=d.anomaly.id, status="running", opened_by="anomaly",
                                    budget_tier=tier, budget_json={}, product_id=pid)
                session.add(inv)
                d.anomaly.status = "investigating"
                session.flush()
                to_run.append((inv.id, tier))
    # Run the investigations in the background AFTER the triage commit — so the
    # request returns immediately (no proxy timeout that left cases stuck as
    # "pending triage") and the rows are visible to the worker sessions.
    for inv_id, tier in to_run:
        threading.Thread(target=_run_investigation_bg, args=(inv_id, tier), daemon=True).start()
    return {
        "decisions": out,
        "started_investigations": [i for i, _ in to_run],
        "skipped_already_triaged": skipped_already_triaged,
        "summary": (f"{len(out)} anomalies: {skipped_already_triaged} already triaged, "
                    f"{len(to_run)} new → investigating"),
    }


class NewCase(BaseModel):
    anomaly_slug: str | None = None
    description: str | None = None
    tier: str = "standard"
    product_id: int | None = None


@app.post("/investigations")
@limiter.limit("6/minute")  # each run costs money — cap runaway spend (v1.0)
def start_investigation(request: Request, body: NewCase,
                        user: dict = Depends(require_role("reviewer"))) -> dict:
    """Start an investigation for an existing anomaly, or open a manual case
    from a free-text description. Runs in the background; poll the trace."""
    with session_scope() as session:
        prod = _scope(session, body.product_id)
        pid = prod.id if prod else None
        opened_by = "anomaly"
        if body.anomaly_slug:
            anomaly = session.scalars(select(AnomalyEvent).where(
                AnomalyEvent.slug == body.anomaly_slug)).first()
            if anomaly is None:
                raise HTTPException(404, f"no anomaly '{body.anomaly_slug}'")
            # Concurrency guard: don't spawn a second investigation for an anomaly
            # that already has one running — return the in-flight one instead.
            running = session.scalars(select(Investigation).where(
                Investigation.anomaly_id == anomaly.id,
                Investigation.status == "running")).first()
            if running is not None:
                return {"status": "already_running", "investigation_id": running.id,
                        "anomaly_id": anomaly.id}
        elif body.description:
            opened_by = "manual"
            anomaly = AnomalyEvent(
                slug=f"manual-{int(time.time())}", type="manual",
                metric="manual case", delta=0.0, z=0.0, window="n/a",
                description=body.description.strip(), status="pending", product_id=pid)
            session.add(anomaly)
            session.flush()
        else:
            raise HTTPException(422, "provide anomaly_slug or description")
        # Create the investigation row NOW so we can return its id and the UI can
        # jump straight to the live trace; the loop itself runs in the background.
        inv = Investigation(anomaly_id=anomaly.id, status="running",
                            opened_by=opened_by, budget_tier=body.tier, budget_json={},
                            data_notes=_data_notes(session), product_id=pid)
        session.add(inv)
        anomaly.status = "investigating"
        session.flush()
        investigation_id, anomaly_id = inv.id, anomaly.id

    threading.Thread(target=_run_investigation_bg,
                     args=(investigation_id, body.tier), daemon=True).start()
    return {"status": "started", "investigation_id": investigation_id, "anomaly_id": anomaly_id}


@app.get("/investigations")
def list_investigations(product_id: int | None = None) -> dict:
    with session_scope() as session:
        p = _scope(session, product_id)
        stmt = select(Investigation).order_by(Investigation.id.desc())
        if p is not None:
            stmt = stmt.where(Investigation.product_id == p.id)
        rows = session.scalars(stmt).all()
        return {"investigations": [
            {"id": i.id, "status": i.status, "opened_by": i.opened_by,
             "budget_tier": i.budget_tier, "anomaly_id": i.anomaly_id} for i in rows]}


@app.get("/investigations/{inv_id}")
def get_investigation(inv_id: int) -> dict:
    with session_scope() as session:
        inv = session.get(Investigation, inv_id)
        if inv is None:
            raise HTTPException(404, "no such investigation")
        return _investigation_dict(session, inv)


def _run_challenge_bg(inv_id: int, note: str) -> None:
    """Run a challenge re-investigation (created synchronously by the review
    endpoint) off the request path so the HTTP call returns immediately."""
    from echolens.investigator.graph import Investigator
    from echolens.recommender.recommend import recommend
    with session_scope() as session:
        inv_row = session.get(Investigation, inv_id)
        if inv_row is None:
            return
        anomaly = session.get(AnomalyEvent, inv_row.anomaly_id)
        inv = Investigator(session, anomaly, tier=inv_row.budget_tier, opened_by="challenge",
                           context_note=note, reopens_investigation_id=inv_row.reopens_investigation_id,
                           existing_investigation=inv_row).run()
        finding = session.scalars(select(Finding).where(
            Finding.investigation_id == inv.id).order_by(Finding.id.desc())).first()
        if finding is not None:
            recommend(session, finding)
            _try_notify(session, finding)


def _resume_investigation_bg(inv_id: int) -> None:
    from echolens.investigator.graph import Investigator
    from echolens.recommender.recommend import recommend
    with session_scope() as session:
        inv = session.get(Investigation, inv_id)
        if inv is None or inv.paused:
            return
        inv = Investigator.resume(session, inv)
        finding = session.scalars(select(Finding).where(
            Finding.investigation_id == inv.id).order_by(Finding.id.desc())).first()
        if finding is not None:
            recommend(session, finding)
            _try_notify(session, finding)


@app.post("/investigations/{inv_id}/pause")
def pause_investigation(inv_id: int, user: dict = Depends(require_role("reviewer"))) -> dict:
    with session_scope() as session:
        inv = session.get(Investigation, inv_id)
        if inv is None:
            raise HTTPException(404, "no such investigation")
        inv.paused = True
        return {"status": "pausing", "id": inv_id}


@app.post("/investigations/{inv_id}/resume")
def resume_investigation(inv_id: int, user: dict = Depends(require_role("reviewer"))) -> dict:
    with session_scope() as session:
        inv = session.get(Investigation, inv_id)
        if inv is None:
            raise HTTPException(404, "no such investigation")
        if inv.status != "running":
            raise HTTPException(422, f"cannot resume a {inv.status} investigation")
        inv.paused = False
    threading.Thread(target=_resume_investigation_bg, args=(inv_id,), daemon=True).start()
    return {"status": "resuming", "id": inv_id}


@app.post("/investigations/{inv_id}/escalate")
def escalate_investigation(inv_id: int, user: dict = Depends(require_role("reviewer"))) -> dict:
    with session_scope() as session:
        inv = session.get(Investigation, inv_id)
        if inv is None:
            raise HTTPException(404, "no such investigation")
        inv.escalated = True
        return {"status": "escalated", "id": inv_id, "by": user["email"]}


@app.get("/investigations/{inv_id}/trace")
def get_trace(inv_id: int, after: int = 0) -> dict:
    with session_scope() as session:
        inv = session.get(Investigation, inv_id)
        if inv is None:
            raise HTTPException(404, "no such investigation")
        steps = session.scalars(select(TraceStep).where(
            TraceStep.investigation_id == inv_id, TraceStep.seq > after
        ).order_by(TraceStep.seq)).all()
        return {"status": inv.status, "steps": [_trace_dict(t) for t in steps]}


@app.get("/investigations/{inv_id}/trace/stream")
def stream_trace(inv_id: int) -> StreamingResponse:
    """SSE tail of the trace_steps table until the investigation stops running."""
    def gen():
        sent = 0
        while True:
            with session_scope() as session:
                inv = session.get(Investigation, inv_id)
                if inv is None:
                    yield f"event: error\ndata: {json.dumps({'error': 'not found'})}\n\n"
                    return
                steps = session.scalars(select(TraceStep).where(
                    TraceStep.investigation_id == inv_id, TraceStep.seq > sent
                ).order_by(TraceStep.seq)).all()
                for t in steps:
                    sent = t.seq
                    yield f"event: step\ndata: {json.dumps(_trace_dict(t))}\n\n"
                if inv.status != "running":
                    yield f"event: done\ndata: {json.dumps({'status': inv.status})}\n\n"
                    return
            time.sleep(0.5)
    return StreamingResponse(gen(), media_type="text/event-stream")


class ReviewBody(BaseModel):
    action: str  # approve | challenge
    note: str = ""
    reason: str | None = None  # v5.0 structured challenge category


@app.post("/findings/{finding_id}/review")
def review_finding(finding_id: int, body: ReviewBody,
                   user: dict = Depends(require_role("reviewer"))) -> dict:
    from echolens import review
    with session_scope() as session:
        finding = session.get(Finding, finding_id)
        if finding is None:
            raise HTTPException(404, "no such finding")
        if body.action == "approve":
            review.approve(session, finding, body.note, user_id=user["id"])
            return {"status": "approved", "finding_id": finding_id, "by": user["email"]}
        if body.action == "challenge":
            if not body.note.strip():
                raise HTTPException(422, "challenge requires a note")
            # Create the re-opened row synchronously, then run the loop in the
            # background so the HTTP request returns immediately (a full
            # investigation can take many minutes — it must not block the request).
            reopened = review.record_challenge(session, finding, body.note,
                                               reason=body.reason, user_id=user["id"])
            reopened_id = reopened.id
            note = body.note
    if body.action == "challenge":
        threading.Thread(target=_run_challenge_bg, args=(reopened_id, note), daemon=True).start()
        return {"status": "challenged", "reopened_investigation_id": reopened_id, "by": user["email"]}
    raise HTTPException(422, "action must be approve or challenge")


@app.get("/calibration")
def calibration_view(product_id: int | None = None) -> dict:
    """v5.0 trust page: stated-confidence-vs-approval curve + known weak spots."""
    from echolens.calibration import calibration, weak_spots
    with session_scope() as session:
        p = _scope(session, product_id)
        pid = p.id if p else None
        return {**calibration(session, pid), "weak_spots": weak_spots(session, pid),
                "product": p.name if p else None}


@app.post("/findings/{finding_id}/recommend")
def recommend_finding(finding_id: int) -> dict:
    from echolens.recommender.recommend import recommend
    with session_scope() as session:
        finding = session.get(Finding, finding_id)
        if finding is None:
            raise HTTPException(404, "no such finding")
        recs = recommend(session, finding)
        return {"recommendations": [
            {"rank": r.rank, "action": r.action, "impact": r.impact, "effort": r.effort}
            for r in recs]}


# ── v4.0: actionable delivery (tickets, GitHub issues, Slack, alerts) ────

def _github_repo(session) -> str | None:
    """The repo to file issues into: the single connected GitHub source, else
    the configured default. (Our beachhead is one product per workspace.)"""
    from echolens.db.models import CollectorState
    rows = session.scalars(select(CollectorState).where(
        CollectorState.source == "github", CollectorState.enabled == True)).all()  # noqa: E712
    if len(rows) == 1:
        return rows[0].identifier
    return settings.github_default_repo or None


@app.get("/findings/{finding_id}/issue")
def finding_issue_markdown(finding_id: int) -> dict:
    """Copy-to-clipboard, ticket-ready markdown for a finding."""
    from echolens.exporting import finding_ticket
    from echolens.notify import deep_link
    with session_scope() as session:
        finding = session.get(Finding, finding_id)
        if finding is None:
            raise HTTPException(404, "no such finding")
        repo = _github_repo(session)
        inv = session.get(Investigation, finding.investigation_id)
        ticket = finding_ticket(session, finding, repo=repo,
                                deep_link=deep_link(inv.id) if inv else None)
        return {**ticket, "repo": repo}


@app.post("/findings/{finding_id}/github-issue")
def finding_github_issue(finding_id: int, user: dict = Depends(require_role("reviewer"))) -> dict:
    """Open a GitHub issue from a finding, evidence chain included."""
    from echolens.exporting import finding_ticket
    from echolens.integrations.github_issue import GitHubIssueError, create_issue
    from echolens.notify import deep_link
    with session_scope() as session:
        finding = session.get(Finding, finding_id)
        if finding is None:
            raise HTTPException(404, "no such finding")
        repo = _github_repo(session)
        if not repo:
            raise HTTPException(422, "No GitHub repo connected. Connect a repo on Sources, or set GITHUB_DEFAULT_REPO.")
        inv = session.get(Investigation, finding.investigation_id)
        ticket = finding_ticket(session, finding, repo=repo,
                                deep_link=deep_link(inv.id) if inv else None)
        try:
            issue = create_issue(repo, ticket["title"], ticket["body"])
        except GitHubIssueError as err:
            raise HTTPException(422, str(err))
        from echolens.fixwatch import link_issue
        if issue.get("number"):
            link_issue(session, finding, repo, int(issue["number"]), issue.get("url", ""))
        return {"repo": repo, **issue}


@app.post("/findings/{finding_id}/notify")
def finding_notify(finding_id: int, user: dict = Depends(require_role("reviewer"))) -> dict:
    """Send a finding's alert now (bypasses the severity gate)."""
    from echolens.notify import notify_finding
    with session_scope() as session:
        finding = session.get(Finding, finding_id)
        if finding is None:
            raise HTTPException(404, "no such finding")
        return notify_finding(session, finding, force=True)


def _slack_note(payload: dict) -> str:
    """Pull the reviewer's note out of a Slack interactive payload's input
    blocks (payload.state.values → first non-empty plain_text_input)."""
    values = (payload.get("state") or {}).get("values") or {}
    for block in values.values():
        if not isinstance(block, dict):
            continue
        for field in block.values():
            if isinstance(field, dict) and field.get("value"):
                return str(field["value"]).strip()
    return ""


def _do_approve(finding_id: int, note: str) -> dict:
    from echolens import review as review_mod
    with session_scope() as session:
        finding = session.get(Finding, finding_id)
        if finding is None:
            raise HTTPException(404, "no such finding")
        review_mod.approve(session, finding, note)
        result = {"status": "approved", "finding_id": finding.id}
        if settings.auto_create_issue_on_approve:
            result["issue"] = _auto_issue(session, finding)
        return result


def _do_challenge(finding_id: int, note: str) -> int:
    from echolens import review as review_mod
    with session_scope() as session:
        finding = session.get(Finding, finding_id)
        if finding is None:
            raise HTTPException(404, "no such finding")
        return review_mod.challenge(session, finding, note).id


def _slack_challenge_bg(finding_id: int, note: str) -> None:
    try:
        _do_challenge(finding_id, note)
    except Exception as err:
        log.error("slack_challenge_failed", finding_id=finding_id, error=str(err))


@app.post("/integrations/slack/act")
async def slack_act(request: Request) -> dict:
    """Reply-to-act from Slack: an approve/challenge button (or a simple JSON
    body) maps to the review endpoint. No dashboard visit required.

    Accepts either Slack's interactive `payload` form field or a JSON body
    {token, action, finding_id, note}. Guarded by SLACK_ACTION_TOKEN.

    The blocking review work runs off the event loop (a challenge re-runs a full
    investigation): the JSON path awaits it in a worker thread; the Slack path
    acknowledges immediately (within Slack's 3s window) and finishes in the
    background."""
    from echolens.notify import parse_action_value

    ctype = request.headers.get("content-type", "")
    is_slack = "application/json" not in ctype
    action, finding_id, note, token = None, None, "", ""
    if not is_slack:
        body = await request.json()
        token = body.get("token", "")
        action = body.get("action")
        finding_id = body.get("finding_id")
        note = body.get("note", "") or ""
    else:  # Slack interactivity: form-encoded `payload`
        form = await request.form()
        payload = json.loads(form.get("payload", "{}"))
        token = form.get("token", "") or request.headers.get("x-echolens-token", "") or payload.get("token", "")
        actions = payload.get("actions", [])
        if actions:
            try:
                action, finding_id = parse_action_value(actions[0].get("value", ""))
            except ValueError:
                raise HTTPException(422, "unrecognized Slack action value")
        note = _slack_note(payload)

    expected = settings.slack_action_token
    if not expected or token != expected:
        raise HTTPException(401, "invalid or missing slack action token")
    if action not in ("approve", "challenge") or finding_id is None:
        raise HTTPException(422, "provide action (approve|challenge) and finding_id")
    finding_id = int(finding_id)

    if action == "challenge":
        if is_slack and not note.strip():
            # a button carries no note; keep the challenge functional
            note = "Challenged from Slack — please re-examine this finding."
        if not note.strip():
            raise HTTPException(422, "a challenge needs a note")
        if is_slack:
            threading.Thread(target=_slack_challenge_bg, args=(finding_id, note), daemon=True).start()
            return {"status": "challenge_started", "finding_id": finding_id}
        reopened = await run_in_threadpool(_do_challenge, finding_id, note)
        return {"status": "challenged", "reopened_investigation_id": reopened}

    return await run_in_threadpool(_do_approve, finding_id, note or "approved from Slack")


def _auto_issue(session, finding) -> dict:
    from echolens.exporting import finding_ticket
    from echolens.integrations.github_issue import GitHubIssueError, create_issue
    from echolens.notify import deep_link
    repo = _github_repo(session)
    if not repo:
        return {"error": "no repo configured"}
    inv = session.get(Investigation, finding.investigation_id)
    ticket = finding_ticket(session, finding, repo=repo, deep_link=deep_link(inv.id) if inv else None)
    try:
        issue = create_issue(repo, ticket["title"], ticket["body"])
    except GitHubIssueError as err:
        return {"error": str(err)}
    from echolens.fixwatch import link_issue
    if issue.get("number"):
        link_issue(session, finding, repo, int(issue["number"]), issue.get("url", ""))
    return issue


@app.post("/alerts/digest")
def alerts_digest(hours: int = 24, user: dict = Depends(require_role("reviewer"))) -> dict:
    """Daily rollup: post one summary of findings drafted in the last `hours` to
    Slack. Used by the scheduled GitHub Action so PMs get a quiet digest."""
    from datetime import timedelta
    from echolens.impact import severity
    from echolens.notify import _send_slack, deep_link
    with session_scope() as session:
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        findings = [f for f in session.scalars(select(Finding).order_by(Finding.id.desc())).all()
                    if f.created_at and aware_utc(f.created_at) >= since]
        if not findings:
            return {"sent": False, "reason": "no findings in window"}
        lines = []
        for f in findings[:20]:
            fj = f.json or {}
            sev = severity(float(fj.get("confidence", 0.0)), fj.get("impact", {}))
            link = deep_link(f.investigation_id)
            label = fj.get("summary") or "finding"
            lines.append(f"• *{sev['band']}* — {label}" + (f" (<{link}|case #{f.investigation_id}>)" if link else ""))
        payload = {"blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": f"EchoLens digest · {len(findings)} findings"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}},
        ]}
        ok = _send_slack(payload)
        return {"sent": ok, "count": len(findings)}


# ── v6.0: closed-loop verification (fix watch, patterns, product health) ─

@app.post("/webhooks/github")
async def github_webhook(request: Request) -> dict:
    """GitHub issue events. When a finding's issue CLOSES, start a fix-watch on
    the metric it was meant to fix (verified signature if a secret is set)."""
    raw = await request.body()
    secret = settings.github_webhook_secret
    if secret:
        import hashlib
        import hmac
        sig = request.headers.get("x-hub-signature-256", "")
        expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            raise HTTPException(401, "invalid webhook signature")
    event = request.headers.get("x-github-event", "")
    try:
        payload = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(400, "invalid JSON")
    if event == "issues" and payload.get("action") == "closed":
        issue = payload.get("issue", {})
        repo = (payload.get("repository") or {}).get("full_name", "")
        closed_at = None
        if issue.get("closed_at"):
            try:
                closed_at = datetime.fromisoformat(str(issue["closed_at"]).replace("Z", "+00:00"))
            except ValueError:
                pass
        from echolens.fixwatch import on_issue_closed
        with session_scope() as session:
            watch = on_issue_closed(session, repo, int(issue.get("number", 0)), closed_at)
            return {"ok": True, "watch_id": watch.id if watch else None,
                    "status": watch.status if watch else "no_matching_finding"}
    return {"ok": True, "ignored": event or "unknown"}


@app.post("/fixwatch/evaluate")
def fixwatch_evaluate(user: dict = Depends(require_role("reviewer"))) -> dict:
    """Advance every fix-watch: confirm fixes that worked, re-open the ones that
    didn't, and catch regressions. Called by the scheduled job (unprompted)."""
    from echolens.fixwatch import check_regressions, evaluate
    with session_scope() as session:
        return {"evaluated": evaluate(session), "regressions": check_regressions(session)}


@app.get("/fixwatch")
def fixwatch_list(product_id: int | None = None) -> dict:
    from echolens.db.models import FixWatch
    with session_scope() as session:
        p = _scope(session, product_id)
        stmt = select(FixWatch).order_by(FixWatch.id.desc())
        if p is not None:
            stmt = stmt.where(FixWatch.product_id == p.id)
        rows = session.scalars(stmt).all()
        return {"watches": [
            {"id": w.id, "finding_id": w.finding_id, "investigation_id": w.investigation_id,
             "repo": w.repo, "issue_number": w.issue_number, "issue_url": w.issue_url,
             "status": w.status, "metric": w.metric, "baseline_rate": w.baseline_rate,
             "post_rate": w.post_rate,
             "fix_date": w.fix_date.isoformat() if w.fix_date else None} for w in rows]}


@app.get("/patterns")
def patterns_view(product_id: int | None = None) -> dict:
    """The validated pattern library — (trigger, cause, fix) proven by confirmed fixes."""
    from echolens.patterns import patterns
    with session_scope() as session:
        p = _scope(session, product_id)
        return {"patterns": patterns(session, p.id if p else None),
                "product": p.name if p else None}


@app.get("/overview")
def overview(product_id: int | None = None) -> dict:
    """Outcome-oriented product-health dashboard (the PM's monthly review)."""
    import statistics as _stats
    from echolens.db.models import FixWatch
    with session_scope() as session:
        prod = _scope(session, product_id)
        pid = prod.id if prod else None
        w_stmt = select(FixWatch)
        if pid is not None:
            w_stmt = w_stmt.where(FixWatch.product_id == pid)
        watches = session.scalars(w_stmt).all()
        confirmed = [w for w in watches if w.status == "confirmed"]
        in_verification = [w for w in watches if w.status in ("issue_open", "watching")]
        regressed = [w for w in watches if w.status == "regressed"]
        confirmed_inv = {w.investigation_id for w in confirmed}

        q_start = _quarter_start(datetime.now(timezone.utc))
        confirmed_q = [w for w in confirmed if w.confirmed_at and aware_utc(w.confirmed_at) >= q_start]

        mttrs = []
        for w in confirmed:
            inv = session.get(Investigation, w.investigation_id)
            if inv and inv.created_at and w.confirmed_at:
                mttrs.append((aware_utc(w.confirmed_at) - aware_utc(inv.created_at)).days)
        mttr = round(_stats.mean(mttrs), 1) if mttrs else None

        # open problems = resolved cases not yet confirmed-fixed, ranked by impact
        open_problems = []
        op_stmt = select(Investigation).where(Investigation.status == "resolved")
        if pid is not None:
            op_stmt = op_stmt.where(Investigation.product_id == pid)
        for inv in session.scalars(op_stmt).all():
            if inv.id in confirmed_inv:
                continue
            finding = session.scalars(select(Finding).where(
                Finding.investigation_id == inv.id).order_by(Finding.id.desc())).first()
            if finding is None:
                continue
            impact = (finding.json or {}).get("impact", {})
            open_problems.append({
                "investigation_id": inv.id, "summary": finding.summary,
                "impact_score": impact.get("impact_score", 0.0),
                "affected_pct": impact.get("affected_pct", 0.0),
            })
        open_problems.sort(key=lambda p: -p["impact_score"])
        from echolens.themes import theme_lifecycle
        chronic = [t for t in theme_lifecycle(session, product_id=pid) if t["status"] == "chronic"]
        return {
            "open_problems": open_problems[:10],
            "open_problem_count": len(open_problems),
            "in_verification": len(in_verification),
            "confirmed_fixes_total": len(confirmed),
            "confirmed_fixes_quarter": len(confirmed_q),
            "regressions": len(regressed),
            "mean_days_to_confirmed_fix": mttr,
            "chronic_themes": chronic,
            "product": prod.name if prod else None,
        }


def _quarter_start(now: datetime) -> datetime:
    q_month = 3 * ((now.month - 1) // 3) + 1
    return now.replace(month=q_month, day=1, hour=0, minute=0, second=0, microsecond=0)


# ── v7.0: conversational layer, weekly brief, theme lifecycle ────────────

class ChatBody(BaseModel):
    message: str
    product_id: int | None = None


@app.post("/chat")
def chat_endpoint(body: ChatBody, user: dict = Depends(current_user)) -> dict:
    """Ask the verified knowledge anything. Returns a finding-cited answer, or —
    for an investigate-intent question — launches a case that streams in-thread."""
    from echolens import chat as chat_mod
    with session_scope() as session:
        prod = _scope(session, body.product_id)
        pid = prod.id if prod else None
        decision = chat_mod.route(session, body.message, product_id=pid,
                                  product_name=(prod.name if prod else None))
        if decision.get("type") != "launch":
            return decision
        if user.get("role") not in ("reviewer", "admin"):
            return {"type": "answer", "citations": [],
                    "text": "I can look into that, but opening an investigation needs reviewer access."}
        anomaly = AnomalyEvent(slug=f"chat-{int(time.time())}", type="manual", metric="chat question",
                               delta=0.0, z=0.0, window="n/a",
                               description=decision["description"], status="pending", product_id=pid)
        session.add(anomaly)
        session.flush()
        inv = Investigation(anomaly_id=anomaly.id, status="running", opened_by="manual",
                            budget_tier="standard", budget_json={}, data_notes=_data_notes(session),
                            product_id=pid)
        session.add(inv)
        anomaly.status = "investigating"
        session.flush()
        inv_id = inv.id
    threading.Thread(target=_run_investigation_bg, args=(inv_id, "standard"), daemon=True).start()
    return {"type": "investigation", "investigation_id": inv_id,
            "text": f"Opening an investigation into that — case #{inv_id}. It's streaming now."}


class FollowupBody(BaseModel):
    question: str


@app.post("/findings/{finding_id}/followup")
def finding_followup(finding_id: int, body: FollowupBody,
                     user: dict = Depends(require_role("reviewer"))) -> dict:
    """Targeted follow-up on a finding (e.g. 'does this affect iOS too?') appended
    as an addendum — no full re-investigation."""
    from echolens.chat import followup
    with session_scope() as session:
        finding = session.get(Finding, finding_id)
        if finding is None:
            raise HTTPException(404, "no such finding")
        return followup(session, finding, body.question)


@app.get("/brief")
def brief_view(product_id: int | None = None) -> dict:
    """Preview the weekly brief (also what the scheduled send composes)."""
    from echolens.brief import weekly_brief
    with session_scope() as session:
        p = _scope(session, product_id)
        return {**weekly_brief(session, product_id=(p.id if p else None)),
                "product": p.name if p else None}


@app.post("/brief/send")
def brief_send(user: dict = Depends(require_role("reviewer"))) -> dict:
    """Compose and deliver the weekly brief to Slack/email (scheduled, unprompted)."""
    from echolens.brief import weekly_brief
    from echolens.notify import _send_email, _send_slack, deep_link
    with session_scope() as session:
        b = weekly_brief(session)

    def _linkify(text: str) -> str:
        import re
        def repl(m):
            cid = m.group(1)
            link = deep_link(int(cid))
            return f"<{link}|case #{cid}>" if link else f"case #{cid}"
        return re.sub(r"case #(\d+)", repl, text)

    body_md = "\n".join(_linkify(line) for line in b["lines"])
    payload = {"blocks": [
        {"type": "header", "text": {"type": "plain_text", "text": f"EchoLens weekly brief · {b['generated']}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": body_md}},
    ]}
    slack = _send_slack(payload)
    email = _send_email(f"EchoLens weekly brief · {b['generated']}", "\n".join(b["lines"]))
    return {"sent": {"slack": slack, "email": email}, "brief": b}


@app.get("/themes")
def themes_view(product_id: int | None = None) -> dict:
    """Theme lifecycle: emergence → peak → resolved / chronic (>60d unresolved)."""
    from echolens.themes import theme_lifecycle
    with session_scope() as session:
        p = _scope(session, product_id)
        return {"themes": theme_lifecycle(session, product_id=(p.id if p else None)),
                "product": p.name if p else None}


@app.get("/costs")
def costs(product_id: int | None = None) -> dict:
    with session_scope() as session:
        p = _scope(session, product_id)
        calls = _product_llm_calls(session, p.id if p else None)
        per_agent: dict[str, Any] = {}
        for c in calls:
            a = per_agent.setdefault(c.agent, {"calls": 0, "tokens": 0, "cost": 0.0, "ms": 0})
            a["calls"] += 1
            a["tokens"] += c.tokens_in + c.tokens_out
            a["cost"] += c.cost
            a["ms"] += c.ms
        for a in per_agent.values():
            a["cost"] = round(a["cost"], 4)
            a["avg_ms"] = round(a["ms"] / a["calls"], 1) if a["calls"] else 0
        return {
            "total_cost_usd": round(sum(c.cost for c in calls), 4),
            "total_tokens": sum(c.tokens_in + c.tokens_out for c in calls),
            "per_agent": per_agent,
        }


# ── UI-facing aggregates (Milestone 3) ─────────────────────────────────

_HUMAN_BY_STATUS = {"resolved": "Approved"}


def _today() -> date:
    """Real 'today' for spend/volume-per-day counters — investigations and
    llm_calls are timestamped at real wall-clock time, so this must be now."""
    return datetime.now(timezone.utc).date()


def _limits(session, product_id: int | None = None) -> dict:
    """Effective budget limits: per-product overrides > workspace overrides >
    config defaults (v8.0 — each product keeps its own budgets)."""
    from echolens.db.models import Product
    row = session.get(Setting, "limits")
    defaults = {
        "daily_investigations": ORCHESTRATOR_DAILY_INVESTIGATIONS,
        "per_case_budget": BUDGET_TIERS["standard"].max_cost_usd,
        "per_case_wall_min": BUDGET_TIERS["standard"].max_wall_clock_s // 60,
    }
    merged = {**defaults, **(row.value if row else {})}
    if product_id is not None:
        p = session.get(Product, product_id)
        if p is not None and p.limits_json:
            merged = {**merged, **p.limits_json}
    return merged


def _daily_limit(session, product_id: int | None = None) -> int:
    return int(_limits(session, product_id)["daily_investigations"])


def _money(x: float) -> str:
    """Costs are fractions of a cent per call — show enough precision to be real
    (a $0.0031 case must not display as $0.00)."""
    x = float(x or 0)
    return f"${x:.4f}" if 0 < x < 1 else f"${x:.2f}"


def _cost_by_investigation(session) -> dict[int, dict]:
    agg: dict[int, dict] = {}
    for c in session.scalars(select(LLMCall)).all():
        if c.investigation_id is None:
            continue
        a = agg.setdefault(c.investigation_id, {"cost": 0.0, "tokens": 0, "queries": 0})
        a["cost"] += c.cost
        a["tokens"] += c.tokens_in + c.tokens_out
    for inv in session.scalars(select(Investigation)).all():
        a = agg.setdefault(inv.id, {"cost": 0.0, "tokens": 0, "queries": 0})
        a["queries"] = int(str(inv.budget_json.get("tool_calls", "0/0")).split("/")[0])
        a["duration"], a["duration_flagged"] = _case_duration(inv)
    return agg


def _fmt_duration(seconds: float) -> str:
    """Human duration: '45s', '1m 20s', '2h 5m'. Never a raw minute count."""
    s = max(0, int(seconds))
    if s < 60:
        return f"{s}s"
    m, sec = divmod(s, 60)
    if m < 60:
        return f"{m}m {sec}s" if sec else f"{m}m"
    h, m = divmod(m, 60)
    return f"{h}h {m}m" if m else f"{h}h"


def _case_duration(inv: Investigation) -> tuple[str, bool]:
    """(display, suspicious). A case's wall-clock can never exceed its tier cap —
    if the stored timestamps say otherwise they're wrong (e.g. a row created at
    seed time, resolved days later), so FLAG it instead of presenting it as fact."""
    if not (inv.resolved_at and inv.created_at):
        return "—", False
    secs = (aware_utc(inv.resolved_at) - aware_utc(inv.created_at)).total_seconds()
    tier = BUDGET_TIERS.get(inv.budget_tier or "standard", BUDGET_TIERS["standard"])
    cap = tier.max_wall_clock_s * EXTENSION_FACTOR
    if secs > cap:
        return f"> {_fmt_duration(cap)}", True
    return _fmt_duration(secs), False


def _status_label(status: str) -> str:
    return {
        "resolved": "Resolved", "insufficient_evidence": "Insufficient evidence",
        "needs_human": "Needs human", "budget_exhausted": "Budget exhausted",
        "running": "Investigating",
    }.get(status, status)


def _product_investigations(session, product_id: int | None):
    stmt = select(Investigation)
    if product_id is not None:
        stmt = stmt.where(Investigation.product_id == product_id)
    return session.scalars(stmt).all()


def _product_llm_calls(session, product_id: int | None):
    """LLM calls scoped through their investigation's product."""
    calls = session.scalars(select(LLMCall)).all()
    if product_id is None:
        return calls
    ids = {i.id for i in _product_investigations(session, product_id)}
    return [c for c in calls if c.investigation_id in ids]


@app.get("/feed/summary")
def feed_summary(product_id: int | None = None) -> dict:
    with session_scope() as session:
        p = _scope(session, product_id)
        pid = p.id if p else None
        today = _today()
        invs = _product_investigations(session, pid)
        n_today = [i for i in invs if i.created_at and i.created_at.date() == today]
        spent = sum(c.cost for c in _product_llm_calls(session, pid)
                    if c.created_at and c.created_at.date() == today)
        return {"investigations_today": len(n_today),
                "daily_limit": _daily_limit(session, pid),
                "spent_today": round(spent, 4),
                "product": p.name if p else None}


@app.get("/archive")
def archive(product_id: int | None = None) -> dict:
    with session_scope() as session:
        p = _scope(session, product_id)
        pid = p.id if p else None
        costs = _cost_by_investigation(session)
        rows = []
        resolved_approved = 0
        stmt = select(Investigation).order_by(Investigation.id.desc())
        if pid is not None:
            stmt = stmt.where(Investigation.product_id == pid)
        for inv in session.scalars(stmt).all():
            if inv.status == "running":
                continue
            finding = session.scalars(select(Finding).where(
                Finding.investigation_id == inv.id).order_by(Finding.id.desc())).first()
            fb = session.scalars(select(ReviewFeedback).join(
                Finding, Finding.id == ReviewFeedback.finding_id).where(
                Finding.investigation_id == inv.id).order_by(ReviewFeedback.id.desc())).first()
            human = "—"
            if fb:
                human = "Approved" if fb.action == "approve" else "Challenged"
            if human == "Approved":
                resolved_approved += 1
            c = costs.get(inv.id, {})
            rows.append({
                "id": f"#{inv.id}",
                "cause": finding.summary if finding else "(no finding)",
                "status": _status_label(inv.status),
                "conf": round(finding.confidence, 2) if finding else 0.0,
                "human": human,
                "cost": f"${c.get('cost', 0):.2f}",
                "time": c.get("duration", "—"),
                "summary": finding.json.get("prose", "") if finding else "",
            })
        total = len(rows)
        return {
            "rows": rows, "count": total,
            "resolved_pct": round(100 * resolved_approved / total) if total else 0,
        }


_SOURCE_META = {
    "play_store": {"icon": "▶", "label": "Google Play reviews"},
    "app_store": {"icon": "⌘", "label": "App Store reviews"},
    "github": {"icon": "⌥", "label": "GitHub issues + releases"},
    "csv": {"icon": "⇪", "label": "Imported reviews (CSV)"},
}


@app.get("/sources")
def sources(product_id: int | None = None) -> dict:
    from echolens.collectors.registry import source_health
    from echolens.db.models import CollectorState
    with session_scope() as session:
        prod = _scope(session, product_id)
        s_stmt = select(CollectorState)
        if prod is not None:
            s_stmt = s_stmt.where(CollectorState.product_id == prod.id)
        states = session.scalars(s_stmt).all()
        health = {(h["source"], h["identifier"]): h for h in source_health(session)}
        connected = []
        for st in states:
            if not st.enabled:
                continue
            meta = _SOURCE_META.get(st.source, {"icon": "•", "label": st.source})
            if st.source in ("play_store", "app_store"):
                vol = session.scalar(select(func.count(Review.id)).where(
                    Review.product == st.product, Review.source == st.source)) or 0
            elif st.source == "github":
                vol = session.scalar(select(func.count(Issue.id)).where(Issue.product == st.product)) or 0
            else:
                vol = 0
            h = health.get((st.source, st.identifier), {})
            stale = bool(h.get("stale"))
            status = {"healthy": "Healthy", "error": "Error", "running": "Syncing…"}.get(st.status, "Idle")
            if stale and st.status != "error":
                status = "Stale"
            last_run = aware_utc(st.last_run_at)
            why = None
            if st.last_error:
                when = last_run.strftime("%H:%M") if last_run else "last run"
                why = f"collector failed at {when}: {st.last_error}"
            elif stale and h.get("stale_since"):
                why = f"no successful pull since {h['stale_since']}"
            connected.append({
                "icon": meta["icon"], "name": meta["label"], "detail": f"{st.identifier} · {st.product}",
                "source": st.source, "identifier": st.identifier,
                "status": "Error" if st.status == "error" else status,
                "stale": stale, "staleSince": h.get("stale_since"), "why": why,
                "lastSuccess": (last_run.isoformat() if (last_run and st.status != "error") else None),
                "lastPull": (f"pulled {last_run.date().isoformat()}" if last_run else "not yet collected"),
                "volume": f"{vol:,} items", "error": st.last_error,
            })
        # Imported (CSV) reviews aren't a pull collector, so surface them from the
        # corpus directly whenever any exist (identified by the import ext_id prefix,
        # regardless of the source label the user chose).
        n_csv = session.scalar(select(func.count(Review.id)).where(Review.ext_id.like("csv_%"))) or 0
        if n_csv:
            connected.append({
                "icon": _SOURCE_META["csv"]["icon"], "name": _SOURCE_META["csv"]["label"],
                "detail": "uploaded exports", "status": "Healthy", "stale": False, "staleSince": None,
                "lastPull": "imported", "volume": f"{n_csv:,} items", "error": None})
        # If nothing is configured, show the built-in demo corpus so the page
        # is never blank (it's still real counts).
        if not connected:
            n_reviews = session.scalar(select(func.count(Review.id))) or 0
            n_issues = session.scalar(select(func.count(Issue.id))) or 0
            n_releases = session.scalar(select(func.count(Release.id))) or 0
            if n_reviews or n_issues:
                connected = [
                    {"icon": "▶", "name": "Google Play reviews (demo)", "detail": "synthetic Lumo dataset",
                     "status": "Healthy", "lastPull": "seeded", "volume": f"{n_reviews:,} items"},
                    {"icon": "⌥", "name": "GitHub issues (demo)", "detail": "synthetic Lumo dataset",
                     "status": "Healthy", "lastPull": "seeded", "volume": f"{n_issues + n_releases} items"},
                ]
        return {"connected": connected, "product": prod.name if prod else None,
                "available": ["Zendesk export", "Discord community", "In-app feedback"]}


@app.get("/costs/summary")
def costs_summary(product_id: int | None = None) -> dict:
    with session_scope() as session:
        p = _scope(session, product_id)
        pid = p.id if p else None
        calls = _product_llm_calls(session, pid)
        invs = _product_investigations(session, pid)
        costs = _cost_by_investigation(session)
        resolved = [i for i in invs if i.status == "resolved"]
        dead = [i for i in invs if i.status in ("insufficient_evidence", "budget_exhausted")]
        spent_today = sum(c.cost for c in calls if c.created_at and c.created_at.date() == _today())
        total = round(sum(c.cost for c in calls), 4)
        avg_resolved = (round(sum(costs.get(i.id, {}).get("cost", 0) for i in resolved) / len(resolved), 4)
                        if resolved else 0.0)
        dead_spend = round(sum(costs.get(i.id, {}).get("cost", 0) for i in dead), 4)
        rows = []
        row_stmt = select(Investigation).order_by(Investigation.id.desc())
        if pid is not None:
            row_stmt = row_stmt.where(Investigation.product_id == pid)
        for inv in session.scalars(row_stmt).all():
            finding = session.scalars(select(Finding).where(
                Finding.investigation_id == inv.id).order_by(Finding.id.desc())).first()
            c = costs.get(inv.id, {})
            rows.append({
                "id": f"#{inv.id}",
                "outcome": f"{_status_label(inv.status)} — {finding.summary[:40] if finding else ''}",
                "status": inv.status,
                "tokens": f"{c.get('tokens', 0) / 1000:.1f}k",
                "queries": c.get("queries", 0),
                "time": c.get("duration", "—"),
                "time_flagged": bool(c.get("duration_flagged")),
                "cost": _money(c.get("cost", 0)),
            })
        return {
            "stats": {
                "spent_today": round(spent_today, 4),
                "avg_per_resolved": avg_resolved,
                "dead_end_spend": dead_spend,
                "analyst_hours_saved": len(resolved) * 3,
                "resolved_count": len(resolved),
            },
            "month_to_date": total,
            "budget": 25.0,
            "product": p.name if p else None,
            "limits": _limits(session, pid),
            "rows": rows,
        }


class LimitsBody(BaseModel):
    daily_investigations: int | None = None
    per_case_budget: float | None = None
    per_case_wall_min: int | None = None


@app.put("/settings/limits")
def set_limits(body: LimitsBody, user: dict = Depends(require_role("admin"))) -> dict:
    """Adjust workspace budget limits (admin). Persisted; the orchestrator's
    daily cap reads from here."""
    with session_scope() as session:
        current = _limits(session)
        for k in ("daily_investigations", "per_case_budget", "per_case_wall_min"):
            v = getattr(body, k)
            if v is not None:
                current[k] = v
        row = session.get(Setting, "limits")
        if row is None:
            row = Setting(key="limits", value={})
            session.add(row)
        row.value = current
        session.flush()
        return current
