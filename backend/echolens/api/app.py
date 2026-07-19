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

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import func, select

from echolens.config import BUDGET_TIERS, ORCHESTRATOR_DAILY_INVESTIGATIONS, settings
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
            **_finding_extras(finding, recs, inv.status)},
        "recommendations": [{"rank": r.rank, "action": r.action, "impact": r.impact,
                             "effort": r.effort, "rationale": r.rationale} for r in recs],
    }


def _finding_extras(finding, recs, status: str) -> dict:
    """The decision doc + severity, computed from the finding's impact + actions
    (v4.0) so the UI answers What's broken / How bad / What to do above the fold."""
    from echolens.impact import decision_doc, severity
    fj = finding.json or {}
    impact = fj.get("impact", {})
    return {
        "decision": decision_doc(fj, list(recs), impact, status),
        "severity": severity(float(fj.get("confidence", 0.0)), impact),
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


def _onboard_bg(product: str) -> None:
    """Hands-off backfill: pull every configured source once, then scan. Runs in
    a thread so POST /onboard returns immediately and the wizard can poll."""
    from echolens.collectors.registry import run_all
    from echolens.detector.detect import scan
    try:
        with session_scope() as session:
            run_all(session, limit=300)  # 90-day-ish backfill for a first run
        with session_scope() as session:
            scan(session)
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
        add_source(session, "play_store", body.play_store.strip(), product)
        if repo:
            add_source(session, "github", repo, product)
    threading.Thread(target=_onboard_bg, args=(product,), daemon=True).start()
    return {"status": "backfilling", "product": product, "play_store": body.play_store.strip(),
            "github": repo}


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


@app.get("/snapshot")
def snapshot(product: str | None = None, days: int = 90) -> dict:
    """Health snapshot for a product (or the whole corpus) — powers the
    'Investigate now on anything' entry point outside onboarding."""
    from echolens.onboarding.snapshot import health_snapshot
    with session_scope() as session:
        return health_snapshot(session, product=product, days=days)


@app.post("/search/embed")
def search_embed(user: dict = Depends(require_role("admin"))) -> dict:
    """Backfill embeddings over the corpus so semantic search activates (v1.0)."""
    from echolens.search.semantic import embed_corpus
    with session_scope() as session:
        return {"embedded": embed_corpus(session)}


@app.post("/anomalies/scan")
def anomalies_scan() -> dict:
    from echolens.detector.detect import scan
    with session_scope() as session:
        events = scan(session)
        return {"detected": [e.slug for e in events]}


@app.get("/anomalies")
def list_anomalies() -> dict:
    with session_scope() as session:
        rows = session.scalars(select(AnomalyEvent).order_by(AnomalyEvent.id)).all()
        return {"anomalies": [_anomaly_dict(session, a) for a in rows]}


@app.post("/anomalies/triage")
@limiter.limit("10/minute")
def anomalies_triage(request: Request, run: bool = False,
                     user: dict = Depends(require_role("reviewer"))) -> dict:
    from echolens.orchestrator.triage import Orchestrator, run_triaged
    with session_scope() as session:
        decisions = Orchestrator(session, daily_limit=_daily_limit(session)).triage()
        out = [{"anomaly": d.anomaly.slug, "decision": d.decision, "reason": d.reason,
                "budget_tier": d.budget_tier,
                "merge_into": d.merge_into.slug if d.merge_into else None} for d in decisions]
        started = []
        if run:
            for inv in run_triaged(session, decisions):
                started.append(inv.id)
        return {"decisions": out, "started_investigations": started}


class NewCase(BaseModel):
    anomaly_slug: str | None = None
    description: str | None = None
    tier: str = "standard"


@app.post("/investigations")
@limiter.limit("6/minute")  # each run costs money — cap runaway spend (v1.0)
def start_investigation(request: Request, body: NewCase,
                        user: dict = Depends(require_role("reviewer"))) -> dict:
    """Start an investigation for an existing anomaly, or open a manual case
    from a free-text description. Runs in the background; poll the trace."""
    with session_scope() as session:
        opened_by = "anomaly"
        if body.anomaly_slug:
            anomaly = session.scalars(select(AnomalyEvent).where(
                AnomalyEvent.slug == body.anomaly_slug)).first()
            if anomaly is None:
                raise HTTPException(404, f"no anomaly '{body.anomaly_slug}'")
        elif body.description:
            opened_by = "manual"
            anomaly = AnomalyEvent(
                slug=f"manual-{int(time.time())}", type="manual",
                metric="manual case", delta=0.0, z=0.0, window="n/a",
                description=body.description.strip(), status="pending")
            session.add(anomaly)
            session.flush()
        else:
            raise HTTPException(422, "provide anomaly_slug or description")
        # Create the investigation row NOW so we can return its id and the UI can
        # jump straight to the live trace; the loop itself runs in the background.
        inv = Investigation(anomaly_id=anomaly.id, status="running",
                            opened_by=opened_by, budget_tier=body.tier, budget_json={},
                            data_notes=_data_notes(session))
        session.add(inv)
        anomaly.status = "investigating"
        session.flush()
        investigation_id, anomaly_id = inv.id, anomaly.id

    threading.Thread(target=_run_investigation_bg,
                     args=(investigation_id, body.tier), daemon=True).start()
    return {"status": "started", "investigation_id": investigation_id, "anomaly_id": anomaly_id}


@app.get("/investigations")
def list_investigations() -> dict:
    with session_scope() as session:
        rows = session.scalars(select(Investigation).order_by(Investigation.id.desc())).all()
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
            reopened = review.challenge(session, finding, body.note, user_id=user["id"], reason=body.reason)
            return {"status": "challenged", "reopened_investigation_id": reopened.id, "by": user["email"]}
        raise HTTPException(422, "action must be approve or challenge")


@app.get("/calibration")
def calibration_view() -> dict:
    """v5.0 trust page: stated-confidence-vs-approval curve + known weak spots."""
    from echolens.calibration import calibration, weak_spots
    with session_scope() as session:
        return {**calibration(session), "weak_spots": weak_spots(session)}


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
        return create_issue(repo, ticket["title"], ticket["body"])
    except GitHubIssueError as err:
        return {"error": str(err)}


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


@app.get("/costs")
def costs() -> dict:
    with session_scope() as session:
        calls = session.scalars(select(LLMCall)).all()
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


def _limits(session) -> dict:
    """Effective budget limits: stored overrides, else config defaults."""
    row = session.get(Setting, "limits")
    defaults = {
        "daily_investigations": ORCHESTRATOR_DAILY_INVESTIGATIONS,
        "per_case_budget": BUDGET_TIERS["standard"].max_cost_usd,
        "per_case_wall_min": BUDGET_TIERS["standard"].max_wall_clock_s // 60,
    }
    return {**defaults, **(row.value if row else {})}


def _daily_limit(session) -> int:
    return int(_limits(session)["daily_investigations"])


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
        a["minutes"] = _minutes(inv)
    return agg


def _minutes(inv: Investigation) -> int:
    if inv.resolved_at and inv.created_at:
        return max(1, round((inv.resolved_at - inv.created_at).total_seconds() / 60))
    return 0


def _status_label(status: str) -> str:
    return {
        "resolved": "Resolved", "insufficient_evidence": "Insufficient evidence",
        "needs_human": "Needs human", "budget_exhausted": "Budget exhausted",
        "running": "Investigating",
    }.get(status, status)


@app.get("/feed/summary")
def feed_summary() -> dict:
    with session_scope() as session:
        today = _today()
        invs = session.scalars(select(Investigation)).all()
        n_today = [i for i in invs if i.created_at and i.created_at.date() == today]
        spent = sum(c.cost for c in session.scalars(select(LLMCall)).all()
                    if c.created_at and c.created_at.date() == today)
        return {"investigations_today": len(n_today),
                "daily_limit": _daily_limit(session),
                "spent_today": round(spent, 4)}


@app.get("/archive")
def archive() -> dict:
    with session_scope() as session:
        costs = _cost_by_investigation(session)
        rows = []
        resolved_approved = 0
        for inv in session.scalars(select(Investigation).order_by(Investigation.id.desc())).all():
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
                "time": f"{c.get('minutes', 0)}m",
                "summary": finding.json.get("prose", "") if finding else "",
            })
        total = len(rows)
        return {
            "rows": rows, "count": total,
            "resolved_pct": round(100 * resolved_approved / total) if total else 0,
        }


_SOURCE_META = {
    "play_store": {"icon": "▶", "label": "Google Play reviews"},
    "github": {"icon": "⌥", "label": "GitHub issues + releases"},
}


@app.get("/sources")
def sources() -> dict:
    from echolens.collectors.registry import source_health
    from echolens.db.models import CollectorState
    with session_scope() as session:
        states = session.scalars(select(CollectorState)).all()
        health = {(h["source"], h["identifier"]): h for h in source_health(session)}
        connected = []
        for st in states:
            if not st.enabled:
                continue
            meta = _SOURCE_META.get(st.source, {"icon": "•", "label": st.source})
            if st.source == "play_store":
                vol = session.scalar(select(func.count(Review.id)).where(Review.product == st.product)) or 0
            elif st.source == "github":
                vol = session.scalar(select(func.count(Issue.id)).where(Issue.product == st.product)) or 0
            else:
                vol = 0
            h = health.get((st.source, st.identifier), {})
            stale = bool(h.get("stale"))
            status = {"healthy": "Healthy", "error": "Error", "running": "Syncing…"}.get(st.status, "Idle")
            if stale and st.status != "error":
                status = "Stale"
            connected.append({
                "icon": meta["icon"], "name": meta["label"], "detail": f"{st.identifier} · {st.product}",
                "status": "Error" if st.status == "error" else status,
                "stale": stale, "staleSince": h.get("stale_since"),
                "lastPull": (f"pulled {st.last_run_at.date().isoformat()}" if st.last_run_at else "not yet collected"),
                "volume": f"{vol:,} items", "error": st.last_error,
            })
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
        return {"connected": connected,
                "available": ["App Store reviews", "Zendesk / CSV import", "Discord community", "In-app feedback"]}


@app.get("/costs/summary")
def costs_summary() -> dict:
    with session_scope() as session:
        calls = session.scalars(select(LLMCall)).all()
        invs = session.scalars(select(Investigation)).all()
        costs = _cost_by_investigation(session)
        resolved = [i for i in invs if i.status == "resolved"]
        dead = [i for i in invs if i.status in ("insufficient_evidence", "budget_exhausted")]
        spent_today = sum(c.cost for c in calls if c.created_at and c.created_at.date() == _today())
        total = round(sum(c.cost for c in calls), 4)
        avg_resolved = (round(sum(costs.get(i.id, {}).get("cost", 0) for i in resolved) / len(resolved), 4)
                        if resolved else 0.0)
        dead_spend = round(sum(costs.get(i.id, {}).get("cost", 0) for i in dead), 4)
        rows = []
        for inv in session.scalars(select(Investigation).order_by(Investigation.id.desc())).all():
            finding = session.scalars(select(Finding).where(
                Finding.investigation_id == inv.id).order_by(Finding.id.desc())).first()
            c = costs.get(inv.id, {})
            rows.append({
                "id": f"#{inv.id}",
                "outcome": f"{_status_label(inv.status)} — {finding.summary[:40] if finding else ''}",
                "status": inv.status,
                "tokens": f"{c.get('tokens', 0) / 1000:.1f}k",
                "queries": c.get("queries", 0),
                "time": f"{c.get('minutes', 0)}m",
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
            "limits": _limits(session),
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
