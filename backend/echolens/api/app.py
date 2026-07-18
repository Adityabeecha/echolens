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
from datetime import date

from fastapi import Depends, FastAPI, HTTPException, Request
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
    TraceStep,
    TriageDecision,
)
from echolens.db.session import init_db, session_scope
from echolens.logging import get_logger

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
        "hypotheses": [{"id": h.hid, "statement": h.statement, "confidence": h.confidence,
                        "status": h.status, **h.json} for h in hyps],
        "evidence": [{"id": e.eid, "source": e.source, "ref": e.ref, "snippet": e.snippet,
                      "retrieved_by": e.retrieved_by, **e.json} for e in evs],
        "finding": None if finding is None else {
            "id": finding.id, "status": finding.status, **finding.json},
        "recommendations": [{"rank": r.rank, "action": r.action, "impact": r.impact,
                             "effort": r.effort, "rationale": r.rationale} for r in recs],
    }


def _trace_dict(t: TraceStep) -> dict:
    return {"seq": t.seq, "kind": t.kind, "content": t.content_json,
            "tokens": t.tokens, "ms": t.ms}


# ── background investigation runner ────────────────────────────────────

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
    """First user ever = bootstrap admin (no auth needed). After that, only an
    existing admin may create users — this closes open self-service admin signup."""
    from echolens.db.models import User
    with session_scope() as session:
        first_user = session.scalar(select(User).limit(1)) is None
        if first_user:
            role = "admin"  # bootstrap the first account as admin
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
        decisions = Orchestrator(session).triage()
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
                            opened_by=opened_by, budget_tier=body.tier, budget_json={})
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
            reopened = review.challenge(session, finding, body.note, user_id=user["id"])
            return {"status": "challenged", "reopened_investigation_id": reopened.id, "by": user["email"]}
        raise HTTPException(422, "action must be approve or challenge")


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

TODAY = date(2026, 7, 17)  # the synthetic corpus's "now"
_HUMAN_BY_STATUS = {"resolved": "Approved"}


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
        invs = session.scalars(select(Investigation)).all()
        today = [i for i in invs if i.created_at and i.created_at.date() == TODAY]
        spent = sum(c.cost for c in session.scalars(select(LLMCall)).all()
                    if c.created_at and c.created_at.date() == TODAY)
        return {"investigations_today": len(today),
                "daily_limit": ORCHESTRATOR_DAILY_INVESTIGATIONS,
                "spent_today": round(spent, 2)}


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


@app.get("/sources")
def sources() -> dict:
    with session_scope() as session:
        n_reviews = session.scalar(select(func.count(Review.id))) or 0
        n_issues = session.scalar(select(func.count(Issue.id))) or 0
        n_releases = session.scalar(select(func.count(Release.id))) or 0
        return {"connected": [
            {"icon": "▶", "name": "Google Play reviews", "detail": "app: com.lumo.photos · 1–2★ prioritized",
             "status": "Healthy", "lastPull": "pulled 12m ago", "volume": f"{n_reviews:,} total"},
            {"icon": "⌥", "name": "GitHub issues", "detail": "lumo-app/lumo-android · issues + reactions",
             "status": "Healthy", "lastPull": "pulled 12m ago", "volume": f"{n_issues} total"},
            {"icon": "≡", "name": "Release notes", "detail": "changelog feed · versions + rollout dates",
             "status": "Healthy", "lastPull": "pulled 1h ago", "volume": f"{n_releases} total"},
        ], "available": ["App Store reviews", "Zendesk / CSV import", "Discord community", "In-app feedback"]}


@app.get("/costs/summary")
def costs_summary() -> dict:
    with session_scope() as session:
        calls = session.scalars(select(LLMCall)).all()
        invs = session.scalars(select(Investigation)).all()
        costs = _cost_by_investigation(session)
        resolved = [i for i in invs if i.status == "resolved"]
        dead = [i for i in invs if i.status in ("insufficient_evidence", "budget_exhausted")]
        spent_today = sum(c.cost for c in calls if c.created_at and c.created_at.date() == TODAY)
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
            "limits": {
                "daily_investigations": ORCHESTRATOR_DAILY_INVESTIGATIONS,
                "per_case_budget": BUDGET_TIERS["standard"].max_cost_usd,
                "per_case_wall_min": BUDGET_TIERS["standard"].max_wall_clock_s // 60,
            },
            "rows": rows,
        }
