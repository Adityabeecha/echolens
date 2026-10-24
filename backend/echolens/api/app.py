"""FastAPI surface (PRD §8) + M2 additions (triage, recommend).

Investigations run in a background thread with their own DB session so the
trace endpoints can tail progress live (poll or SSE) — this is what the
Milestone-3 Investigation screen consumes.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Any

from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import func, select, update

from echolens.cases import case_history, case_title, case_view, derive_status
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
    FixWatch,
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
    # A process restart kills onboarding workers but leaves their persisted
    # source rows marked running. Recover those before exposing health views.
    with session_scope() as session:
        _expire_stuck_onboarding_sources(session, expire_all=True)
    _bootstrap()  # free-tier: seed + first admin from env, no shell needed
    # Resume interrupted work AFTER the app starts accepting requests. Recovery
    # used to run synchronously here, before ``yield``; a single 45-minute case
    # therefore kept the whole deployment unready and its proxy returned 503 to
    # every case refresh for the duration of the resumed LLM loop.
    _start_recovery_bg()
    yield


def _recover_running_bg() -> None:
    """Resume interrupted investigations without blocking API availability."""
    try:
        from echolens.investigator.recover import resume_running
        with session_scope() as s:
            recovered = resume_running(s)
        if recovered:
            log.info("startup_recovery", investigations=recovered)
    except Exception as err:
        log.error("startup_recovery_failed", error=str(err))


def _start_recovery_bg() -> threading.Thread:
    thread = threading.Thread(
        target=_recover_running_bg,
        name="echolens-startup-recovery",
        daemon=True,
    )
    thread.start()
    return thread


def _bootstrap() -> None:
    """Seed demo data and/or create the first admin from env vars, so a shell-
    less free-tier deploy is self-sufficient. Both steps are idempotent."""
    from echolens.auth import create_user
    from echolens.db.models import Review, User

    try:
        with session_scope() as s:
            if settings.seed_on_start and s.scalar(select(Review).limit(1)) is None:
                # The corpus, the demo product and its history (cases, fixes,
                # verdicts) — deterministic, no LLM. Only on an empty database.
                from echolens.synthetic.demo_story import seed_demo
                counts = seed_demo(s)
                log.info("bootstrap_seeded", story=counts.get("story"))
            if settings.bootstrap_admin_email and settings.bootstrap_admin_password:
                if s.scalar(select(User).limit(1)) is None:
                    create_user(s, settings.bootstrap_admin_email,
                                settings.bootstrap_admin_password, "admin")
                    log.info("bootstrap_admin_created", email=settings.bootstrap_admin_email)
    except Exception as err:
        # Loud, and specific about the consequence: with no admin and
        # auth_signup blocked in production, the instance cannot be administered
        # at all. A one-line "bootstrap_failed" gave no hint of that.
        log.error("bootstrap_failed", error=str(err),
                  consequence="no admin user may exist; set BOOTSTRAP_ADMIN_EMAIL/PASSWORD "
                              "and restart, or the instance cannot be administered")


limiter = Limiter(key_func=get_remote_address, default_limits=["240/minute"])
app = FastAPI(title="EchoLens API", version="1.0.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
log = get_logger("api")

# CORS: explicit allowlist in prod; permissive in dev for localhost tooling.
_cors_origins = settings.cors_list or (["*"] if settings.echolens_env == "dev" else [])


def cors_allows_credentials(origins: list[str]) -> bool:
    """Credentialed CORS only for an explicit list. A "*" anywhere in it — e.g.
    CORS_ORIGINS="*" set by hand — keeps credentials off rather than letting
    Starlette reflect every origin with the visitor's session cookie."""
    return bool(origins) and "*" not in origins


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    # The browser session is a cookie, so a split-origin frontend needs
    # credentialed CORS — but ONLY with an explicit origin list. With "*"
    # Starlette would reflect any origin while allowing credentials, letting
    # every website read responses with the visitor's session. Dev's "*" (auth
    # off, Vite proxies same-origin anyway) therefore stays uncredentialed.
    allow_credentials=cors_allows_credentials(_cors_origins),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    """Baseline hardening on every API response. The API serves JSON and SSE,
    never a page meant to be framed or sniffed into HTML."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Frame-Options", "DENY")
    return response


# ── serializers ────────────────────────────────────────────────────────

def _top_theme_surges(session, anomalies: list[AnomalyEvent]) -> dict:
    """product_id -> its loudest theme surge, for every product that has a
    negative-review spike in `anomalies`. One query instead of one per spike."""
    pids = {a.product_id for a in anomalies if a.type == "negative_review_spike"}
    if not pids:
        return {}
    out: dict = {}
    stmt = select(AnomalyEvent).where(AnomalyEvent.type == "theme_volume_surge")
    if None not in pids:
        stmt = stmt.where(AnomalyEvent.product_id.in_(pids))
    for t in session.scalars(stmt.order_by(AnomalyEvent.z.desc(), AnomalyEvent.id)).all():
        out.setdefault(t.product_id, t)
        out.setdefault(None, t)  # an unscoped spike takes the workspace's loudest
    return out


def _anomaly_headline(session, a: AnomalyEvent, top_themes: dict | None = None) -> str:
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
        if top_themes is not None:
            theme = top_themes.get(a.product_id)
        else:
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


def _anomaly_dict(session, a: AnomalyEvent, td=None, inv=None, top_themes=None) -> dict:
    return {
        "slug": a.slug, "type": a.type, "metric": a.metric, "delta": a.delta,
        "z": a.z, "window": a.window, "description": a.description, "status": a.status,
        "headline": _anomaly_headline(session, a, top_themes), "product_id": a.product_id,
        "triage": None if td is None else {
            "decision": td.decision, "reason": td.reason, "budget_tier": td.budget_tier,
            "merge_into_anomaly_id": td.merge_into_anomaly_id,
        },
        "investigation_id": inv.id if inv else None,
    }


def _anomaly_dicts(session, anomalies: list[AnomalyEvent]) -> list[dict]:
    """Serialize an anomaly list with two bounded relation queries."""
    ids = [a.id for a in anomalies]
    if not ids:
        return []
    decisions: dict[int, TriageDecision] = {}
    for row in session.scalars(select(TriageDecision).where(
            TriageDecision.anomaly_id.in_(ids)).order_by(TriageDecision.id)).all():
        decisions[row.anomaly_id] = row
    investigations: dict[int, Investigation] = {}
    for row in session.scalars(select(Investigation).where(
            Investigation.anomaly_id.in_(ids)).order_by(Investigation.id)).all():
        investigations[row.anomaly_id] = row
    top_themes = _top_theme_surges(session, anomalies)
    return [_anomaly_dict(session, a, decisions.get(a.id), investigations.get(a.id), top_themes)
            for a in anomalies]


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
    # The title is a problem statement, never a metric name — the case detail and
    # the case list must not disagree about what this case is called.
    title = case_title(finding, anomaly)
    # ...and they must not disagree about its state either, so the derivation
    # lives once, in echolens.cases, and both read it.
    watch = session.scalars(select(FixWatch).where(
        FixWatch.investigation_id == inv.id).order_by(FixWatch.id.desc())).first()
    case_status, case_why = derive_status(inv, finding, watch)
    return {
        "id": inv.id, "anomaly_id": inv.anomaly_id, "status": inv.status,
        "case_status": case_status, "case_why": case_why,
        "title": title,
        "opened_by": inv.opened_by, "budget_tier": inv.budget_tier,
        "budget": inv.budget_json, "paused": inv.paused, "escalated": inv.escalated,
        "reopens_investigation_id": inv.reopens_investigation_id,
        "data_notes": inv.data_notes or [],
        # v13: the case's own audit trail, so History is a tab rather than a
        # thing that happened somewhere you can no longer see.
        "history": _extension_history(session, inv),
        "hypotheses": [{"id": h.hid, "statement": h.statement, "confidence": h.confidence,
                        "status": h.status, **h.json} for h in hyps],
        "evidence": _with_translations(session, inv, [
            {"id": e.eid, "source": e.source, "ref": e.ref, "snippet": e.snippet,
             "retrieved_by": e.retrieved_by, **e.json} for e in evs]),
        "finding": None if finding is None else {
            "id": finding.id, "status": finding.status, **finding.json,
            **_finding_extras(session, finding, recs, inv.status)},
        "recommendations": [{"rank": r.rank, "action": r.action, "impact": r.impact,
                             "effort": r.effort, "rationale": r.rationale} for r in recs],
        # v15: the product decision in force (fix now / park / won't fix), and
        # whether this dead-end case can be continued with more budget.
        "product_decision": None if finding is None else _decision_view(session, finding.id),
        "extension": _extension_view(session, inv),
    }


def _with_translations(session, inv: Investigation, evidence: list[dict]) -> list[dict]:
    """Attach {lang, lang_name, text_en} to evidence quoting a non-English
    review. The snippet itself is never touched — it stays verbatim."""
    from echolens.db.models import Product
    from echolens.translate import translations_for
    try:
        prod = session.get(Product, inv.product_id) if inv.product_id else None
        found = translations_for(session, [e["ref"] for e in evidence],
                                 prod.name if prod else None)
    except Exception as err:  # a presentation extra must never break the case
        log.warning("evidence_translations_failed", investigation_id=inv.id, error=str(err))
        return evidence
    return [{**e, "translation": found[e["ref"]]} if e["ref"] in found else e
            for e in evidence]


def _decision_view(session, finding_id: int) -> dict | None:
    from echolens.review import decision_dict, latest_decision
    return decision_dict(latest_decision(session, finding_id))


def _extension_history(session, inv):
    events = case_history(session, inv)
    reasons = {ext.get("at"): ext.get("reason", "") for ext in inv.extensions_json or []
               if ext.get("by") == "auto"}
    for event in events:
        if event["kind"] == "extended" and event.get("by") == "auto":
            event["note"] = reasons.get(event["at"], "")
    return events


def _extension_view(session, inv: Investigation) -> dict | None:
    if inv.status == "running":
        return None
    from echolens.investigator.recover import extension_offer
    try:
        return extension_offer(session, inv)
    except Exception as err:  # a presentation extra must never break the case
        log.warning("extension_offer_failed", investigation_id=inv.id, error=str(err))
        return None


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
               "baseline_rate": watch.baseline_rate, "post_rate": watch.post_rate,
               "fixed_in_version": watch.fixed_in_version}
        if watch.status in ("issue_open", "watching") and not watch.fixed_in_version:
            fix["version_hint"] = True   # UI nudges: set the version so the window starts at release
        if watch.fixed_in_version and watch.status in ("issue_open", "waiting_for_release"):
            from echolens.fixwatch import release_state
            fix["release"] = release_state(session, watch)
    # v10: how broadly this finding's own cited evidence is corroborated. The
    # two-source rule proves at least two channels agree; this reports the actual
    # spread, so "proven across reviews, GitHub and support" is a fact the finding
    # carries rather than a claim it makes.
    breadth = None
    try:
        from echolens.db.models import Investigation, Product
        from echolens.feedback_graph import evidence_breadth
        inv = session.get(Investigation, finding.investigation_id)
        prod = session.get(Product, inv.product_id) if inv and inv.product_id else None
        refs = [e.ref for e in session.scalars(select(EvidenceRow).where(
            EvidenceRow.investigation_id == finding.investigation_id)).all()]
        breadth = evidence_breadth(session, refs, prod.name if prod else None)
    except Exception as err:  # never let a presentation extra break the finding
        log.warning("evidence_breadth_failed", finding_id=finding.id, error=str(err))

    return {
        "decision": decision_doc(fj, list(recs), impact, status),
        "severity": severity(float(fj.get("confidence", 0.0)), impact),
        "fix": fix,
        "breadth": breadth,
        # The trust badge: sources, the two-source rule, the confidence band.
        "trust": _finding_trust(session, finding),
    }


def _finding_trust(session, finding) -> dict | None:
    from echolens.evidence_summary import finding_trust
    try:
        return finding_trust(session, finding)
    except Exception as err:  # a presentation extra must never break the finding
        log.warning("finding_trust_failed", finding_id=finding.id, error=str(err))
        return None


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


_queue_worker_active: set[int | None] = set()
# The set above is mutated from several request threads. `if x in s: ... s.add(x)`
# is check-then-act: two concurrent POSTs both passed the membership test before
# either added, so two drain workers ran for one product and the daily cap was
# a suggestion. The docstring below claimed this could not happen.
_queue_worker_lock = threading.Lock()


def _drain_queue_bg(product_id: int | None) -> None:
    """Run the queue sequentially until it empties or the daily budget is spent.

    One worker per product: a second call while one is draining is a no-op, so
    pressing the button twice cannot run the same item twice or blow past the
    cap by racing.
    """
    from echolens.orchestrator import queue as q

    with _queue_worker_lock:
        if product_id in _queue_worker_active:
            return
        _queue_worker_active.add(product_id)
    try:
        while True:
            with session_scope() as session:
                limit = _daily_limit(session, product_id)
                row = q.claim_next(session, product_id, limit)
                if row is None:
                    return  # queue empty, or today's budget is gone
                queue_id = row.id
                investigation_id, tier = _open_claimed(session, row, product_id)
            _run_claimed_bg(queue_id, investigation_id, tier)
    finally:
        with _queue_worker_lock:
            _queue_worker_active.discard(product_id)


def _open_claimed(session, row, product_id: int | None) -> tuple[int, str]:
    """Create the Investigation for a queue row that was just claimed."""
    anomaly = session.get(AnomalyEvent, row.anomaly_id)
    tier = row.budget_tier
    inv = Investigation(anomaly_id=row.anomaly_id, status="running",
                        opened_by="anomaly", budget_tier=tier, budget_json={},
                        data_notes=_data_notes(session, product_id),
                        product_id=(anomaly.product_id if anomaly else product_id))
    session.add(inv)
    if anomaly is not None:
        anomaly.status = "investigating"
    session.flush()
    row.investigation_id = inv.id
    return inv.id, tier


def _run_claimed_bg(queue_id: int, investigation_id: int, tier: str) -> None:
    """Run a claimed row's investigation and close the row either way."""
    from echolens.orchestrator import queue as q
    ok = True
    try:
        _run_investigation_bg(investigation_id, tier)
    except Exception as err:  # one bad case must not stall the queue
        ok = False
        log.error("queued_investigation_failed", queue_id=queue_id, error=str(err))
    with session_scope() as session:
        q.finish(session, queue_id, investigation_id, ok=ok)


def _fail_investigation(session, inv_row, reason: str) -> None:
    """End a case honestly instead of leaving it stuck at "running"."""
    inv_row.status = "insufficient_evidence"
    inv_row.resolved_at = datetime.now(timezone.utc)
    notes = list(inv_row.data_notes or [])
    notes.append(f"Investigation could not run: {reason}.")
    inv_row.data_notes = notes
    session.flush()


def _mark_investigation_failed(investigation_id: int, error: str) -> None:
    """Best-effort status write from a failed background thread, on its own
    session — the one that raised is already rolled back."""
    try:
        with session_scope() as session:
            row = session.get(Investigation, investigation_id)
            if row is not None and row.status == "running":
                _fail_investigation(session, row, f"an internal error stopped it ({error[:120]})")
    except Exception as err:
        log.error("mark_failed_failed", investigation_id=investigation_id, error=str(err))


def _run_investigation_bg(investigation_id: int, tier: str) -> None:
    """Run the loop on an investigation row that was already created (so the
    POST could return its id immediately for the UI to jump to)."""
    from echolens.investigator.graph import Investigator
    from echolens.recommender.recommend import recommend

    try:
        with session_scope() as session:
            inv_row = session.get(Investigation, investigation_id)
            if inv_row is None:
                log.error("run_investigation_missing", investigation_id=investigation_id)
                return
            anomaly = session.get(AnomalyEvent, inv_row.anomaly_id) if inv_row.anomaly_id else None
            if anomaly is None:
                # Deleting a product purges its anomalies while an investigation
                # for it may still be queued. This used to dereference None,
                # kill the daemon thread silently, and leave the case at
                # "running" FOREVER — invisible in /archive (which skips running)
                # and un-resumable, because resume re-enters the same crash.
                _fail_investigation(session, inv_row, "its source signal no longer exists")
                return
            anomaly.status = "investigating"
            inv = Investigator(session, anomaly, tier=tier,
                               existing_investigation=inv_row).run()
            finding = session.scalars(select(Finding).where(
                Finding.investigation_id == inv.id).order_by(Finding.id.desc())).first()
            if finding is not None:
                # The investigation and its finding are the core result. Make
                # them durable before optional action drafting/delivery: a bad
                # recommendation payload or provider outage must not roll back a
                # completed case and make recovery run the whole loop again.
                finding_id = finding.id
                session.commit()
                try:
                    recommend(session, finding)
                except Exception as err:
                    session.rollback()
                    log.error("recommend_failed", finding_id=finding_id,
                              error=f"{type(err).__name__}: {err}")
                    finding = session.get(Finding, finding_id)
                _try_notify(session, finding)
    except Exception as err:
        # A dead background thread must not strand the case. Without this the row
        # sat at "running" permanently with no error anywhere the user could see.
        log.error("run_investigation_failed", investigation_id=investigation_id, error=str(err))
        _mark_investigation_failed(investigation_id, str(err))


def _unique_slug(prefix: str) -> str:
    """A slug for an ad-hoc case's anomaly row (the column is UNIQUE): the time
    for readability plus a random suffix, so same-tick launches never collide."""
    import secrets
    return f"{prefix}-{time.time_ns()}-{secrets.token_hex(3)}"


# ── endpoints ──────────────────────────────────────────────────────────

from echolens.auth import (
    CSRF_COOKIE, DEV_ADMIN, GUEST, SESSION_COOKIE, authenticate, clear_session_cookies,
    create_token, create_user, current_user, new_csrf_token, principal_from_token,
    require_role, session_token, set_session_cookies)


class SignupBody(BaseModel):
    email: str
    password: str
    role: str = "viewer"


class LoginBody(BaseModel):
    email: str
    password: str


@app.post("/auth/signup")
@limiter.limit("5/minute")  # bcrypt per call; unthrottled it was a cheap DoS
def auth_signup(body: SignupBody, request: Request, response: Response) -> dict:
    """User creation. In production the FIRST admin must come from the
    BOOTSTRAP_ADMIN_* env (not open self-service) — otherwise a stranger could
    claim admin by being first to hit this endpoint. After an admin exists, only
    an admin may create users. In dev, the first signup bootstraps an admin."""
    from echolens.db.models import User
    with session_scope() as session:
        first_user = session.scalar(select(User).limit(1)) is None
        if first_user:
            if settings.auth_required:
                raise HTTPException(
                    403,
                    "Open signup is disabled when authentication is required. Create the first admin via the "
                    "BOOTSTRAP_ADMIN_EMAIL / BOOTSTRAP_ADMIN_PASSWORD environment variables.",
                )
            role = "admin"  # dev bootstrap
        else:
            caller = current_user(request)  # 401 without a token in prod
            if caller["role"] != "admin":
                raise HTTPException(403, "only an admin can create users")
            role = body.role
        from echolens.auth import password_problem
        problem = password_problem(body.password)
        if problem:
            raise HTTPException(422, problem)
        try:
            user = create_user(session, body.email, body.password, role)
        except ValueError as err:
            raise HTTPException(422, str(err))
        token = create_token(user)
        out = {"id": user.id, "email": user.email, "role": user.role, "token": token}
        # Only a self-service signup becomes the browser's session. An admin
        # creating a colleague must stay signed in as themselves, not be
        # silently switched into the new account.
        if first_user:
            out["csrf_token"] = set_session_cookies(response, token)
        return out


@app.post("/auth/login")
@limiter.limit("10/minute")
def auth_login(body: LoginBody, request: Request, response: Response) -> dict:
    """Rate-limited: bcrypt is slow per attempt, which protects the password but
    makes an unthrottled endpoint a cheap way to burn every worker thread. The
    cap bounds both credential-stuffing and that DoS.

    Sets the HttpOnly session cookie for browsers. `token` stays in the body for
    non-browser clients (GitHub Actions, CLI) that send it as a Bearer header;
    the SPA ignores it and never stores it."""
    with session_scope() as session:
        user = authenticate(session, body.email, body.password)
        if user is None:
            raise HTTPException(401, "invalid credentials")
        token = create_token(user)
        return {"token": token, "role": user.role,
                "csrf_token": set_session_cookies(response, token)}


@app.post("/auth/logout")
def auth_logout(response: Response) -> dict:
    """Clear the browser session. Unauthenticated on purpose: it must work with
    an expired cookie, and the worst a forged call can do is sign someone out."""
    clear_session_cookies(response)
    return {"ok": True}


@app.get("/auth/csrf")
def auth_csrf(request: Request, response: Response) -> dict:
    """The CSRF token for the current cookie session, so a reloaded SPA can
    recover it. A frontend on another origin cannot read the API's cookie via
    document.cookie; credentialed CORS (explicit origins only) is what keeps
    this response unreadable to any other site."""
    if not request.cookies.get(SESSION_COOKIE):
        return {"csrf_token": None}
    csrf = request.cookies.get(CSRF_COOKIE)
    if not csrf:
        csrf = set_session_cookies(response, request.cookies[SESSION_COOKIE], new_csrf_token())
    return {"csrf_token": csrf}


class GoogleBody(BaseModel):
    credential: str


@app.post("/auth/google")
@limiter.limit("20/minute")
def auth_google(body: GoogleBody, request: Request, response: Response) -> dict:
    """Exchange a Google ID token for an EchoLens token.

    The ID token is verified against Google's published keys (signature,
    issuer, audience, expiry) before anything is trusted — see
    echolens.google_auth. Rate-limited because verification can trigger an
    outbound JWKS fetch.
    """
    from echolens.google_auth import GoogleAuthError, may_join, role_for, verify_id_token
    from echolens.auth import upsert_google_user

    try:
        claims = verify_id_token(body.credential)
    except GoogleAuthError as err:
        # The detail is safe to show: it describes the caller's own token, and
        # the specific reason ("not configured", "email not verified") is the
        # difference between a user retrying usefully and giving up.
        raise HTTPException(401, str(err))

    with session_scope() as session:
        from echolens.db.models import User
        existing = session.scalars(select(User).where(User.email == claims["email"])).first()
        if not may_join(claims["email"], existing is not None):
            raise HTTPException(
                403, "This Google account isn't part of this workspace. Ask an admin to invite you.")
        user = upsert_google_user(session, claims["email"], role_for(claims["email"]))
        token = create_token(user)
        return {"token": token, "role": user.role, "email": user.email,
                "csrf_token": set_session_cookies(response, token)}


@app.get("/auth/config")
def auth_config() -> dict:
    """What sign-in options this deployment offers, and whether guests are let
    in. Unauthenticated on purpose: the login screen has to read it before a
    token exists. It exposes only the public OAuth client id, which is designed
    to be embedded in a web page."""
    return {
        "google_client_id": settings.google_client_id,
        "google_enabled": bool(settings.google_client_id),
        "allow_guest": settings.allow_guest,
        "auth_required": settings.auth_required,
    }


@app.get("/auth/me")
def auth_me(user: dict = Depends(current_user)) -> dict:
    return user


# ── v8.0: products are the scope of everything ──────────────────────────

def _guest_locked(user: dict | None) -> bool:
    """True when this caller may only see demo products.

    A guest is an anonymous visitor on a public URL. Without this they saw
    every real product in the workspace — reviews, findings, costs and all —
    because `is_demo` was recorded but never enforced anywhere.
    """
    return bool(user and user.get("guest") and settings.guest_demo_only)


def _may_spend(user: dict | None) -> bool:
    """May this caller cause an LLM call?

    A guest may not. Guest mode exists so a public demo URL is browsable, and
    every route that spends money is behind require_role — except the two GETs
    that build an LLM client inline (/graph, /feed/candidates). Those served an
    anonymous visitor a fresh OpenAI call per request, on the deployment's key.

    Reads still work: the caller gets the deterministic result and a flag saying
    the richer view needs an account.
    """
    return not (user and user.get("guest"))


def _visible_products(session, user: dict | None = None):
    """The products this caller may see, newest-id-last."""
    from echolens.db.models import Product
    q = select(Product).order_by(Product.id)
    if _guest_locked(user):
        q = q.where(Product.is_demo == True)  # noqa: E712
    return session.scalars(q).all()


def _scope(session, product_id: int | None, user: dict | None = None):
    """The product this request is scoped to: the explicit id, else the first.

    An explicit id that does not exist is a 404, not a silent redirect. This
    used to fall through to "the first product", so `?product_id=999` (stale
    link, deleted product, typo) quietly operated on somebody else's data —
    PUT /backlog/plan saved the PM's edits onto Product #1's backlog, and
    /anomalies/scan scanned the wrong corpus, with no error surfaced anywhere.

    Guests are confined to demo products here, at the single choke point every
    scoped route already passes through, rather than in each route. A real
    product requested by id is a 404 for them — the same answer as a product
    that does not exist, so the response does not confirm it is there.
    """
    from echolens.db.models import Product
    if product_id is not None:
        p = session.get(Product, product_id)
        if p is None:
            raise HTTPException(404, f"no product with id {product_id}")
        if _guest_locked(user) and not p.is_demo:
            raise HTTPException(404, f"no product with id {product_id}")
        return p
    rows = _visible_products(session, user)
    # For a demo-only guest, no visible product must never mean "all products".
    # Most callers use ``None`` as the intentional workspace-wide scope for a
    # brand-new authenticated workspace, so returning it here leaked every real
    # product whenever a public deployment had not seeded a demo row.
    if _guest_locked(user) and not rows:
        raise HTTPException(404, "no demo product is available")
    return rows[0] if rows else None


def _owned(session, model, resource_id: int, product_id: int | None):
    """Fetch a row by id and REFUSE it if it belongs to another product.

    Product scoping was applied as a WHERE clause on list endpoints and nowhere
    else, so every single-resource route (`GET /investigations/{id}`,
    `POST /findings/{id}/review`, …) served or mutated any id the caller could
    guess, across every product in the workspace. Filtering a list is not
    authorisation; this is the enforcement point those routes never had.

    A cross-product id returns 404, not 403 — a 403 confirms the row exists.
    """
    row = session.get(model, resource_id)
    if row is None:
        raise HTTPException(404, f"no such {model.__tablename__.rstrip('s')}")
    owner = getattr(row, "product_id", None)
    # Legacy investigations may predate their direct product_id. Resolve their
    # anomaly instead of treating NULL as a wildcard across every product.
    if product_id is not None and owner is None and isinstance(row, Investigation):
        anomaly = session.get(AnomalyEvent, row.anomaly_id)
        owner = anomaly.product_id if anomaly else None
    if product_id is not None and owner != product_id:
        raise HTTPException(404, f"no such {model.__tablename__.rstrip('s')}")
    return row


def _owned_finding(session, finding_id: int, product_id: int | None):
    """A finding, verified to belong to the caller's product.

    Findings carry product_id directly, but older rows may not, so fall back to
    the parent investigation's scope rather than letting a NULL wave it through.
    """
    finding = session.get(Finding, finding_id)
    if finding is None:
        raise HTTPException(404, "no such finding")
    owner = finding.product_id
    if owner is None:
        inv = session.get(Investigation, finding.investigation_id)
        owner = inv.product_id if inv else None
    if product_id is not None and owner != product_id:
        raise HTTPException(404, "no such finding")
    return finding


def _user_row(session, user: dict):
    """The DB row behind the authenticated principal, for per-user settings.

    With auth on, the JWT carries a real user id. In dev mode `current_user`
    returns a synthetic admin with id 0 — falsy, and backed by no row — so a
    naive `if uid:` silently dropped every write and product switching appeared
    to work while never persisting. Resolve the dev principal by email (creating
    its row once) so local behaviour matches production instead of diverging.
    """
    from echolens.db.models import User
    uid = user.get("id")
    if uid:
        return session.get(User, uid)
    email = user.get("email")
    if not email:
        return None
    row = session.scalars(select(User).where(User.email == email)).first()
    if row is None:
        row = User(email=email, password_hash="!dev-no-login", role=user.get("role", "admin"))
        session.add(row)
        session.flush()
    return row


def _product_dict(p) -> dict:
    return {"id": p.id, "name": p.name, "package_name": p.package_name,
            "github_repo": p.github_repo, "is_demo": p.is_demo,
            "created_at": p.created_at.isoformat() if p.created_at else None}


@app.get("/products")
def list_products(user: dict = Depends(current_user)) -> dict:
    """Every product + the caller's last-active one. The client uses this on boot
    to decide between Today and the add-product wizard (server-derived)."""
    from echolens.db.models import Product, User
    with session_scope() as session:
        # Guests see only demo products: this list drives the switcher, so
        # anything here is a product the visitor can open.
        rows = _visible_products(session, user)
        active = None
        u = _user_row(session, user)
        if u is not None and u.last_active_product_id:
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
    """Admin-only, deliberately.

    A product is a billing and scope boundary, not a document. Creating one
    attaches collectors that keep pulling every few hours and opens a new
    corpus that investigations run against — an ongoing commitment on the
    workspace owner's API key, not a single action. `reviewer` is "can act on
    the work" (investigate, approve, challenge); `admin` is "can change what
    the system watches and what it costs".
    """
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
        # Via _scope so a guest cannot activate — or learn the name of — a
        # product they are not allowed to see. `session.get` bypassed that.
        p = _scope(session, product_id, user)
        if p is None:
            raise HTTPException(404, "no such product")
        u = _user_row(session, user)
        if u is None:
            # A guest has no `users` row to remember anything on, which is
            # expected, not an error: their active product lives in the URL.
            # This used to 500, so switching product as a guest always failed.
            if user.get("guest"):
                return {"active_product_id": product_id, "name": p.name,
                        "persisted": False}
            raise HTTPException(500, "could not resolve the current user to persist the switch")
        u.last_active_product_id = product_id
        return {"active_product_id": product_id, "name": p.name, "persisted": True}


@app.get("/products/{product_id}/deletion-preview")
def product_deletion_preview(product_id: int, user: dict = Depends(current_user)) -> dict:
    """What deleting this product would destroy.

    A destructive confirmation that says "this cannot be undone" without saying
    what "this" is asks the user to trust a number they cannot see. These are the
    real counts.
    """
    from echolens.db.models import (
        AnomalyEvent, CollectorState, Finding, Investigation, Product, Review)
    with session_scope() as session:
        # _scope, not session.get: this returns a product's NAME and its review,
        # case and finding counts, so an unscoped lookup let a demo visitor
        # enumerate every real product in the workspace by id.
        p = _scope(session, product_id, user)
        if p is None:
            raise HTTPException(404, "no such product")

        def count(model, *where):
            return len(session.scalars(select(model).where(*where)).all())

        return {
            "id": p.id,
            "name": p.name,
            "is_demo": p.is_demo,
            "reviews": count(Review, Review.product == p.name),
            "cases": count(Investigation, Investigation.product_id == p.id),
            "findings": count(Finding, Finding.product_id == p.id),
            "anomalies": count(AnomalyEvent, AnomalyEvent.product_id == p.id),
            "sources": count(CollectorState, CollectorState.product_id == p.id),
        }


@app.delete("/products/{product_id}")
def delete_product(product_id: int, confirm: str = "",
                   user: dict = Depends(require_role("admin"))) -> dict:
    """Delete a product and cascade its data. Requires ?confirm=<exact name>."""
    from echolens.db.models import (
        AnomalyEvent, CollectorState, Comment, EvidenceRow, FeedbackEntry, Finding,
        FixWatch, HypothesisRow, Investigation, Issue, KnowledgeEdge, LLMCall, Mention,
        Post, Product, QueuedInvestigation, Recommendation, Release, Review,
        ReviewFeedback, ReviewRequest, TraceStep, TriageDecision, User,
        FindingDecision, ShareLink, SavedView, SentAlert)
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

        # Mentions hang off comments, so they go first — deleting the comment
        # out from under them is the same FK violation one level down.
        comment_ids = [c.id for c in session.scalars(select(Comment).where(
            Comment.product_id == product_id)).all()]
        _purge(Mention, Mention.comment_id, comment_ids)

        _purge(ReviewFeedback, ReviewFeedback.finding_id, find_ids)
        # v15: decisions and share links hang off findings. Deleting a product
        # must also kill its public links, or a token would outlive its data.
        _purge(FindingDecision, FindingDecision.finding_id, find_ids)
        _purge(ShareLink, ShareLink.finding_id, find_ids)
        _purge(Recommendation, Recommendation.finding_id, find_ids)
        _purge(TraceStep, TraceStep.investigation_id, inv_ids)
        _purge(HypothesisRow, HypothesisRow.investigation_id, inv_ids)
        _purge(EvidenceRow, EvidenceRow.investigation_id, inv_ids)
        _purge(LLMCall, LLMCall.investigation_id, inv_ids)
        # Spend with no case (chat, triage, themes, graph) is tagged by product.
        _purge(LLMCall, LLMCall.product_id, [product_id])
        _purge(TriageDecision, TriageDecision.anomaly_id, anom_ids)
        # Anything that references an investigation must be gone before the
        # investigations themselves, hence two ordered passes rather than one
        # loop over every product-scoped model.
        _purge(Comment, Comment.investigation_id, inv_ids)
        _purge(ReviewRequest, ReviewRequest.investigation_id, inv_ids)
        _purge(QueuedInvestigation, QueuedInvestigation.investigation_id, inv_ids)
        for model in (FixWatch, Finding, Investigation, AnomalyEvent, CollectorState,
                      QueuedInvestigation, KnowledgeEdge, Comment, Mention, ReviewRequest, SavedView,
                      SentAlert):
            for row in session.scalars(select(model).where(model.product_id == product_id)).all():
                session.delete(row)
        # Older collector rows were created before product_id was populated.
        # They are still owned by their product name and must not survive a
        # delete only to be inherited by a later product with the same name.
        for row in session.scalars(select(CollectorState).where(
                CollectorState.product == name, CollectorState.product_id.is_(None))).all():
            session.delete(row)
        # Corpus rows are keyed by product NAME, not id. FeedbackEntry was
        # missing: every v2 source (Hacker News, Stack Overflow, GitHub
        # Discussions, PRs/commits) lands there, so deleting a product left its
        # entire non-store corpus behind, and a product recreated with the same
        # name silently inherited it.
        for model in (Review, Issue, Post, Release, FeedbackEntry):
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
def collect_run(user: dict = Depends(require_role("admin"))) -> dict:
    """Dev convenience: seed the synthetic corpus if empty (real collectors are M3)."""
    from echolens.db.models import Review
    from echolens.synthetic.demo_story import seed_demo
    with session_scope() as session:
        if session.scalar(select(Review).limit(1)) is not None:
            return {"status": "already_populated"}
        counts = seed_demo(session)
    return {"status": "seeded", "counts": counts}


class ConnectSource(BaseModel):
    source: str            # any key of collectors.registry._BUILDERS
    identifier: str        # package name / repo / search term
    product: str | None = None
    product_id: int | None = None


@app.get("/sources/available")
def sources_available() -> dict:
    """The connectable sources, from the registry.

    Served rather than hardcoded in the frontend so a source can never appear in
    the form without a collector behind it — the connect form and _BUILDERS
    cannot drift apart.
    """
    from echolens.collectors.registry import SOURCE_INFO, _BUILDERS

    return {"sources": [
        {"source": s,
         "label": SOURCE_INFO.get(s, {}).get("label", s.replace("_", " ").title()),
         "hint": SOURCE_INFO.get(s, {}).get("hint", "")}
        for s in sorted(_BUILDERS)
    ]}


@app.post("/sources/connect")
def connect_source(body: ConnectSource, user: dict = Depends(require_role("admin"))) -> dict:
    """Register a real data source (v1.0). Collection happens on the schedule
    or via POST /collectors/run.

    product_id wins over the free-text `product`. Sources is a per-product
    screen, but its form defaulted the name to "" — and add_source falls back to
    `product or identifier`, so the source attached to a product named after the
    raw PACKAGE rather than the one being viewed. Nothing errored; the data just
    filed itself somewhere invisible.
    """
    from echolens.collectors.registry import add_source
    with session_scope() as session:
        product = body.product
        if body.product_id is not None:
            prod = _scope(session, body.product_id, user)
            if prod is not None:
                product = prod.name
        try:
            st = add_source(session, body.source, body.identifier, product,
                            body.product_id)
        except ValueError as err:
            raise HTTPException(422, str(err))
        # Scope the collector row too, so product-filtered health and collection
        # actually see it.
        if body.product_id is not None:
            st.product_id = body.product_id
            session.flush()
        return {"connected": {"source": st.source, "identifier": st.identifier, "product": st.product}}


@app.post("/collectors/run")
def collectors_run(product_id: int | None = None,
                   user: dict = Depends(require_role("reviewer"))) -> dict:
    """Run every configured collector once (deterministic, no LLM)."""
    from echolens.collectors.registry import run_all
    started = time.monotonic()
    with session_scope() as session:
        prod = _scope(session, product_id, user)
        results = run_all(session, product_id=(prod.id if prod else None))
        translation = _translate_after_collect(session, prod, user)
        return {"translation": translation, "results": [
            {"source": r.source, "identifier": r.identifier, "fetched": r.fetched,
             "inserted": r.inserted, "error": r.error,
             "duration_seconds": r.duration_s} for r in results],
                "duration_seconds": round(time.monotonic() - started, 2)}


def _translate_product(session, prod, user: dict | None) -> dict:
    """Detect languages, then translate what is pending — with a live model
    only when a key is set and the caller may spend. Capped per run and by the
    product's `daily_translation_usd` limit; spend is recorded with its id."""
    from echolens.translate import metered_client, translate_reviews
    llm = (metered_client(session, prod.id)
           if prod is not None and settings.openai_api_key and _may_spend(user) else None)
    daily = _limits(session, prod.id if prod else None).get("daily_translation_usd")
    return translate_reviews(session, prod, llm, daily_usd=daily)


def _translate_after_collect(session, prod, user: dict | None) -> dict | None:
    if prod is None:
        return None
    try:
        return _translate_product(session, prod, user)
    except Exception as err:  # translation is an extra; collection already succeeded
        log.warning("translate_after_collect_failed", product_id=prod.id, error=str(err))
        return None


@app.post("/translate")
@limiter.limit("6/minute")  # may spend on a model
def translate_now(request: Request, product_id: int | None = None,
                  user: dict = Depends(require_role("reviewer"))) -> dict:
    """Translate this product's non-English reviews now (on demand). Analysis
    reads the translations; quotes keep the original text."""
    with session_scope() as session:
        prod = _scope(session, product_id, user)
        if prod is None:
            raise HTTPException(404, "no product to translate")
        out = _translate_product(session, prod, user)
        if not settings.openai_api_key:
            out["note"] = "No model key is configured, so nothing was translated."
        return {**out, "product": prod.name}


class RetryBody(BaseModel):
    source: str
    identifier: str
    product_id: int | None = None


@app.post("/collectors/retry")
def collectors_retry(body: RetryBody, user: dict = Depends(require_role("reviewer"))) -> dict:
    """Retry ONE source now (the 'Retry now' action on a stale/failed source)."""
    from echolens.collectors.registry import SourceConfig, run_one
    with session_scope() as session:
        from echolens.db.models import CollectorState
        prod = _scope(session, body.product_id, user)
        st = session.scalars(select(CollectorState).where(
            CollectorState.source == body.source,
            CollectorState.identifier == body.identifier,
            CollectorState.product_id == (prod.id if prod else None))).first()
        if st is None:
            raise HTTPException(404, "no such source")
        res = run_one(session, SourceConfig(
            st.source, st.identifier, st.product, st.product_id,
            st.id, st.watermark))
        return {"source": res.source, "identifier": res.identifier,
                "inserted": res.inserted, "error": res.error}


@app.post("/collectors/reset")
def collectors_reset(body: RetryBody, user: dict = Depends(require_role("admin"))) -> dict:
    """Clear one source cursor and replay its bounded backfill; keep feedback."""
    from echolens.collectors.registry import reset_source
    with session_scope() as session:
        product = _scope(session, body.product_id, user)
        try:
            result = reset_source(session, body.source, body.identifier,
                                  product.id if product else None)
        except LookupError as err:
            raise HTTPException(404, str(err))
        except RuntimeError as err:
            raise HTTPException(409, str(err))
        except ValueError as err:
            raise HTTPException(400, str(err))
        error = result.error or (f"{result.failed_items} items could not be ingested"
                                 if result.failed_items else None)
        return {"source": result.source, "identifier": result.identifier,
                "fetched": result.fetched, "inserted": result.inserted,
                "skipped_duplicate": result.skipped_duplicate, "error": error,
                "duration_seconds": result.duration_s}


@app.get("/collectors")
def collectors_health(product_id: int | None = None,
                      user: dict = Depends(current_user)) -> dict:
    from echolens.db.models import CollectorState
    with session_scope() as session:
        prod = _scope(session, product_id, user)
        stmt = select(CollectorState)
        if prod is not None:
            stmt = stmt.where(CollectorState.product_id == prod.id)
        rows = session.scalars(stmt).all()
        return {"collectors": [
            {"source": c.source, "identifier": c.identifier, "product": c.product,
             "status": c.status, "watermark": c.watermark, "items_last_run": c.items_last_run,
             "last_error": c.last_error,
             "last_run_at": c.last_run_at.isoformat() if c.last_run_at else None,
             "enabled": c.enabled} for c in rows]}


def _data_notes(session, product_id: int | None = None) -> list[str]:
    """Disclosure strings for any source that is stale RIGHT NOW, captured when an
    investigation starts so its finding can say what was unavailable."""
    from echolens.collectors.registry import source_health
    from echolens.db.models import Product
    product = session.get(Product, product_id) if product_id is not None else None
    notes = []
    for h in source_health(session, product=(product.name if product else None)):
        if h["stale"]:
            label = _SOURCE_META.get(h["source"], {}).get("label", h["source"])
            when = f" since {h['stale_since']}" if h.get("stale_since") else ""
            notes.append(f"{label} ({h['identifier']}) was unavailable{when} during this "
                         f"investigation — conclusions may be incomplete.")
    return notes


ONBOARD_EXPECTED_SECONDS = 120
ONBOARD_TIMEOUT_SECONDS = 180
ONBOARD_TIMEOUT_ERROR = (
    "Initial sync stopped responding after 3 minutes. Retry this source."
)
ONBOARD_INTERRUPTED_ERROR = (
    "Sync was interrupted when EchoLens restarted. Retry this source."
)


def _expire_stuck_onboarding_sources(
    session,
    product_id: int | None = None,
    now: datetime | None = None,
    expire_all: bool = False,
) -> int:
    """Atomically finish abandoned source runs owned by the lifecycle.

    The conditional UPDATE is the ownership check: a completed worker no
    longer has ``status=running`` and a newer retry has a fresh ``last_run_at``,
    so neither can be overwritten by an old watchdog.
    """
    from echolens.db.models import CollectorState

    cutoff = (now or datetime.now(timezone.utc)) - timedelta(
        seconds=ONBOARD_TIMEOUT_SECONDS)
    conditions = [CollectorState.status == "running"]
    if not expire_all:
        conditions.extend([
            CollectorState.last_run_at.is_not(None),
            CollectorState.last_run_at <= cutoff,
        ])
    if product_id is not None:
        conditions.append(CollectorState.product_id == product_id)
    result = session.execute(
        update(CollectorState)
        .where(*conditions)
        .values(
            status="error",
            last_error=(ONBOARD_INTERRUPTED_ERROR if expire_all
                        else ONBOARD_TIMEOUT_ERROR),
        )
    )
    return int(result.rowcount or 0)


def _onboard_watchdog(product_id: int) -> None:
    """Expire a worker that never reaches a terminal source state."""
    time.sleep(ONBOARD_TIMEOUT_SECONDS)
    attempt = 0
    while True:
        attempt += 1
        try:
            with session_scope() as session:
                changed = _expire_stuck_onboarding_sources(session, product_id)
            if changed:
                log.error("onboard_backfill_timed_out", product_id=product_id,
                          sources=changed)
            return
        except Exception as err:
            # SQLite can briefly hold the writer lock while ingestion commits.
            # Keep retrying: a finite budget could strand a persisted running
            # row after the worker releases its transaction lock.
            log.warning("onboard_watchdog_retry", product_id=product_id,
                        attempt=attempt, error=str(err))
            time.sleep(5)


def _onboard_bg(product: str, product_id: int | None = None) -> None:
    """Hands-off backfill: pull every configured source once, then scan. Runs in
    a thread so POST /onboard returns immediately and the wizard can poll."""
    from echolens.collectors.registry import run_all
    from echolens.detector.detect import scan
    try:
        with session_scope() as session:
            run_all(session, limit=300, product_id=product_id,
                    timeout_s=ONBOARD_TIMEOUT_SECONDS)
        # Before the scan, so the first themes already count translated reviews.
        with session_scope() as session:
            from echolens.db.models import Product
            prod = session.get(Product, product_id) if product_id is not None else None
            _translate_after_collect(session, prod, None)
        with session_scope() as session:
            scan(session, product=product, product_id=product_id)
        log.info("onboard_backfill_done", product=product)
    except Exception as err:  # never crash the worker; the source shows its error
        log.error("onboard_backfill_failed", product=product, error=str(err))


class OnboardBody(BaseModel):
    play_store: str
    github: str | None = None
    # Keep the old API behaviour (issues + releases only) when this field is
    # omitted. The onboarding UI sends all three when the user chooses "All".
    github_sources: list[str] = Field(default_factory=lambda: ["github"], max_length=3)
    product: str | None = None
    app_store: str | None = None
    chrome_web_store: str | None = None
    hacker_news: str | None = None
    stack_overflow: str | None = None


@app.post("/onboard")
def onboard(body: OnboardBody, user: dict = Depends(require_role("admin"))) -> dict:
    """Add a real product in one shot: validate the inputs, register the sources,
    and kick off a hands-off backfill. The wizard then polls /onboard/status.

    Admin for the same reason as POST /products, which this is a superset of:
    it also registers recurring collectors and starts a 90-day backfill.
    """
    from echolens.collectors.registry import add_source
    from echolens.onboarding.validate import normalize_github_repo, validate_play_store_package

    err = validate_play_store_package(body.play_store)
    if err:
        raise HTTPException(422, err)
    repo, gerr = normalize_github_repo(body.github)
    if gerr:
        raise HTTPException(422, gerr)
    allowed_github = {"github", "github_discussions", "github_activity"}
    github_sources = list(dict.fromkeys(body.github_sources))
    unknown_github = set(github_sources) - allowed_github
    if unknown_github:
        raise HTTPException(422, f"unknown GitHub source: {sorted(unknown_github)[0]}")
    if repo and not github_sources:
        raise HTTPException(422, "select at least one GitHub source")
    product = (body.product or "").strip() or body.play_store.strip()
    with session_scope() as session:
        from echolens.db.models import Product
        prod = session.scalars(select(Product).where(Product.name == product)).first()
        if prod is None:
            prod = Product(name=product, package_name=body.play_store.strip(), github_repo=repo)
            session.add(prod)
            session.flush()
        pid = prod.id
        add_source(session, "play_store", body.play_store.strip(), product, pid)
        if repo:
            for source in github_sources:
                add_source(session, source, repo, product, pid)
        additional = {
            "app_store": body.app_store,
            "chrome_web_store": body.chrome_web_store,
            "hacker_news": body.hacker_news,
            "stack_overflow": body.stack_overflow,
        }
        connected_additional = []
        for source, identifier in additional.items():
            if identifier and identifier.strip():
                add_source(session, source, identifier.strip(), product, pid)
                connected_additional.append(source)
        from echolens.db.models import CollectorState
        connected_states = session.scalars(select(CollectorState).where(
            CollectorState.product_id == pid,
            CollectorState.enabled == True,  # noqa: E712
        )).all()
        started_at = datetime.now(timezone.utc)
        for state in connected_states:
            state.status = "running"
            state.last_run_at = started_at
            state.last_error = None
    threading.Thread(target=_onboard_bg, args=(product, pid), daemon=True).start()
    threading.Thread(target=_onboard_watchdog, args=(pid,), daemon=True).start()
    return {"status": "backfilling", "product": product, "product_id": pid,
            "play_store": body.play_store.strip(), "github": repo,
            "github_sources": github_sources if repo else [],
            "additional_sources": connected_additional}


@app.get("/onboard/preview")
@limiter.limit("30/minute")  # each call reaches out to Google Play / GitHub
def onboard_preview(request: Request, play_store: str | None = None,
                    github: str | None = None,
                    user: dict = Depends(require_role("admin"))) -> dict:
    """What the wizard is about to connect, before it connects it: the Play
    Store listing's title and ratings, or the repo's name and open issues.
    Short timeout, never an error status — a slow store just says so."""
    from echolens.onboarding.preview import preview_github, preview_play_store
    out: dict = {}
    if play_store is not None and play_store.strip():
        out["play_store"] = preview_play_store(play_store)
    if github is not None and github.strip():
        out["github"] = preview_github(github)
    return out


@app.get("/onboard/status")
def onboard_status(product: str, user: dict = Depends(current_user)) -> dict:
    """Live view for the onboarding wait screen: source health, whether the
    backfill is still running, the health snapshot so far, and any anomalies
    already surfaced."""
    from echolens.collectors.registry import source_health
    from echolens.db.models import Product
    from echolens.onboarding.snapshot import health_snapshot
    with session_scope() as session:
        # This route is looked up by NAME, so it cannot use _scope (which takes
        # an id). Check visibility explicitly: without it a demo visitor could
        # confirm a real product exists and read its health snapshot by
        # guessing the name. 404 rather than 403 — the same answer as a name
        # that does not exist, so the response reveals nothing either way.
        named = session.scalars(select(Product).where(Product.name == product)).first()
        if named is not None and _guest_locked(user) and not named.is_demo:
            raise HTTPException(404, "no such product")
        health = source_health(session, product=product)
        # "backfilling" until every source has at least completed one run
        backfilling = any(h["status"] in ("idle", "running") and h["never_collected"]
                          for h in health) or any(h["status"] == "running" for h in health)
        snap = health_snapshot(session, product=product)
        # Scoped to THIS product. Unscoped, the wizard showed another product's
        # signals, and clicking through to the new product's feed found none of
        # them — they were never its anomalies.
        prod = session.scalars(select(Product).where(Product.name == product)).first()
        a_stmt = select(AnomalyEvent).where(AnomalyEvent.status == "pending")
        if prod is not None:
            a_stmt = a_stmt.where(AnomalyEvent.product_id == prod.id)
        anomalies = _anomaly_dicts(
            session, session.scalars(a_stmt.order_by(AnomalyEvent.id)).all())
        started_values = [
            datetime.fromisoformat(h["last_run_at"])
            for h in health if h["last_run_at"] is not None
        ]
        started_at = min(started_values) if started_values else None
        checked_sources = sum(h["status"] in ("healthy", "error") for h in health)
        failed_sources = sum(h["status"] == "error" for h in health)
        timed_out_sources = sum(
            h["status"] == "error" and (
                h.get("last_error") == ONBOARD_TIMEOUT_ERROR
                or "timed out" in (h.get("last_error") or "").lower()
            )
            for h in health
        )
        return {"product": product, "product_id": prod.id if prod else None,
                "backfilling": backfilling, "sources": health,
                "progress": {
                    "checked_sources": checked_sources,
                    "failed_sources": failed_sources,
                    "timed_out_sources": timed_out_sources,
                    "total_sources": len(health),
                    "expected_seconds": ONBOARD_EXPECTED_SECONDS,
                    "timeout_seconds": ONBOARD_TIMEOUT_SECONDS,
                    "started_at": started_at.isoformat() if started_at else None,
                },
                "snapshot": snap, "anomalies": anomalies}


# ── v12: the product-knowledge brain ────────────────────────────────────

@app.get("/brain")
def brain_view(product_id: int | None = None, include_retired: bool = False,
               user: dict = Depends(current_user)) -> dict:
    """The learned causal map: which subsystems, when changed, cause which
    symptoms — with the confidence each belief has earned."""
    from echolens.brain import edges
    with session_scope() as session:
        p = _scope(session, product_id, user)
        pid = p.id if p else None
        return {"edges": edges(session, pid, include_retired=include_retired),
                "retired": edges(session, pid, include_retired=True) if include_retired else None,
                "product": p.name if p else None}


@app.post("/brain/rebuild")
def brain_rebuild(product_id: int | None = None,
                  user: dict = Depends(require_role("reviewer"))) -> dict:
    """Re-mine edges from confirmed fixes and grade them against resolved cases."""
    from echolens.brain import calibrate_from_history, edges, rebuild
    with session_scope() as session:
        p = _scope(session, product_id, user)
        pid = p.id if p else None
        built = rebuild(session, pid)
        graded = calibrate_from_history(session, pid)
        return {**built, "calibration": graded, "edges_now": edges(session, pid)}


class ReviewDoc(BaseModel):
    text: str
    product_id: int | None = None


@app.post("/brain/review")
@limiter.limit("20/minute")
def brain_review(body: ReviewDoc, request: Request,
                 user: dict = Depends(current_user)) -> dict:
    """Design-doc / PR review: flag a proposed change against learned history
    BEFORE it ships. Prevention, not detection."""
    from echolens.brain import review_change
    with session_scope() as session:
        p = _scope(session, body.product_id, user)
        return {**review_change(session, body.text, p.id if p else None),
                "product": p.name if p else None}


class BrainQuestion(BaseModel):
    question: str
    product_id: int | None = None


@app.post("/brain/ask")
@limiter.limit("20/minute")
def brain_ask(body: BrainQuestion, request: Request,
              user: dict = Depends(current_user)) -> dict:
    """The onboarding oracle: 'what usually goes wrong here?', cited to real cases."""
    from echolens.brain import ask
    with session_scope() as session:
        p = _scope(session, body.product_id, user)
        return ask(session, body.question, p.id if p else None, p.name if p else None)


# ── v11: the quality backlog ────────────────────────────────────────────

@app.get("/backlog")
def backlog_view(product_id: int | None = None,
                 user: dict = Depends(current_user)) -> dict:
    """Every open problem, ranked by impact-per-effort, each line defended."""
    from echolens.backlog import backlog
    with session_scope() as session:
        p = _scope(session, product_id, user)
        return {**backlog(session, p.id if p else None), "product": p.name if p else None}


@app.get("/backlog/plan")
def backlog_plan_view(product_id: int | None = None,
                      capacity_days: float | None = Query(None, gt=0, le=10000),
                      kind: str = Query("bugs", pattern="^(bugs|requests|all)$"),
                      user: dict = Depends(current_user)) -> dict:
    """The proposed "what to fix next" draft, respecting the PM's own edits.
    `kind` picks bug findings, user requests, or both."""
    from echolens.backlog import quarter_plan
    with session_scope() as session:
        p = _scope(session, product_id, user)
        return {**quarter_plan(session, p.id if p else None, capacity_days, kind=kind),
                "product": p.name if p else None}


class PlanOverride(BaseModel):
    """A reviewer's per-item estimate. Every field optional; None = use EchoLens's."""
    effort_days: float | None = Field(None, ge=0.5, le=365)
    impact: int | None = Field(None, ge=1, le=5)
    segment: str | None = None   # a key of backlog.PRIORITY_SEGMENTS


class PlanBody(BaseModel):
    # Investigation ids, or request slugs (request-p{id}-…) for user requests.
    included: list[int | str] = Field(default_factory=list, max_length=500)
    excluded: list[int | str] = Field(default_factory=list, max_length=500)
    notes: dict[str, str] | None = None
    # Keyed by investigation id or request slug. Omitted keeps the saved
    # overrides (like notes).
    overrides: dict[str, PlanOverride] | None = None
    # Bounded: a negative capacity produced a plan the API reported back with a
    # straight face (capacity_days: -50.0), and an unbounded one is meaningless.
    capacity_days: float | None = Field(None, gt=0, le=10000)
    product_id: int | None = None
    kind: str = Field("bugs", pattern="^(bugs|requests|all)$")   # the view to answer with


@app.put("/backlog/plan")
def backlog_plan_save(body: PlanBody,
                      user: dict = Depends(require_role("reviewer"))) -> dict:
    """The PM edits and owns the plan; a later re-rank proposes around it."""
    from echolens.backlog import PRIORITY_SEGMENTS, quarter_plan, save_plan
    overrides = None
    if body.overrides is not None:
        bad = sorted({o.segment for o in body.overrides.values()
                      if o.segment and o.segment not in PRIORITY_SEGMENTS})
        if bad:
            raise HTTPException(422, f"unknown priority segment: {', '.join(bad)}")
        overrides = {k: o.model_dump() for k, o in body.overrides.items()}
    with session_scope() as session:
        p = _scope(session, body.product_id, user)
        pid = p.id if p else None
        save_plan(session, pid, included=body.included, excluded=body.excluded,
                  notes=body.notes, capacity_days=body.capacity_days,
                  overrides=overrides)
        return {**quarter_plan(session, pid, kind=body.kind), "product": p.name if p else None}


# ── v16: specs from user requests ───────────────────────────────────────

def _request_spec(session, p, slug: str, user: dict | None) -> dict:
    """The spec for one of THIS product's requests, or 404. A live model only
    rewrites the stories/criteria when a key is set and the caller may spend."""
    from echolens.prd import get_spec
    if p is None:
        raise HTTPException(404, "no such request")
    llm = (_metered_llm(session, "spec", p.id)
           if settings.openai_api_key and _may_spend(user) else None)
    spec = get_spec(session, p.id, p.name, slug, llm=llm)
    if spec is None:
        raise HTTPException(404, "no such request")
    return spec


@app.get("/requests/{slug}/spec")
@limiter.limit("20/minute")  # may build an LLM client inline
def request_spec(request: Request, slug: str, product_id: int | None = None,
                 user: dict = Depends(current_user)) -> dict:
    """A Markdown PRD for a feature request: problem, who asks, stories,
    acceptance criteria, scope, open questions and the quoted evidence."""
    with session_scope() as session:
        p = _scope(session, product_id, user)
        return {**_request_spec(session, p, slug, user), "product": p.name if p else None}


@app.post("/requests/{slug}/ticket")
def request_ticket_create(slug: str, tracker: str = "github", product_id: int | None = None,
                          user: dict = Depends(require_role("reviewer"))) -> dict:
    """File a request's spec to GitHub, Linear or Jira — the same body the
    spec modal shows. Not linked for fix-watch: there is no fix to verify."""
    from echolens.integrations.trackers import TRACKERS, TrackerError, configured_trackers
    from echolens.prd import file_spec
    if tracker not in TRACKERS:
        raise HTTPException(422, f"unknown tracker '{tracker}' — use github, linear or jira")
    if not configured_trackers()[tracker]:
        raise HTTPException(422, f"{tracker.capitalize()} is not configured on this deployment.")
    with session_scope() as session:
        p = _scope(session, product_id, user)
        spec = _request_spec(session, p, slug, user)
        repo = _github_repo(session, p.id)
        if tracker == "github" and not repo:
            raise HTTPException(422, "No GitHub repo connected. Connect a repo on Sources, or set GITHUB_DEFAULT_REPO.")
        try:
            issue = file_spec(tracker, spec, repo=repo)
        except TrackerError as err:
            # Upstream bodies can carry account details; log them, return a generic line.
            log.warning("ticket_failed", tracker=tracker, request=slug, error=str(err))
            raise HTTPException(422, f"could not create the {tracker} issue — see server logs")
        return {"tracker": tracker, "repo": repo if tracker == "github" else None, **issue}


# ── v10: the unified feedback graph ─────────────────────────────────────

@app.get("/graph")
@limiter.limit("20/minute")  # builds an LLM client inline — cap runaway spend
def feedback_graph(request: Request, product_id: int | None = None,
                   days: int = Query(90, ge=1, le=365),
                   limit: int = Query(10, ge=1, le=100),
                   user: dict = Depends(current_user)) -> dict:
    """Cross-channel problem nodes: one complaint, every voice.

    Ranked by how INDEPENDENT the witnesses are, not how many there are — a
    problem four channels agree on outranks a louder one only the store has seen.
    """
    from echolens.feedback_graph import build_graph
    with session_scope() as session:
        prod = _scope(session, product_id, user)
        if prod is None:
            return {"nodes": [], "product": None, "channels": []}
        llm = (_metered_llm(session, "feedback_graph", prod.id)
               if settings.openai_api_key and _may_spend(user) else None)
        out = build_graph(session, prod.name, llm=llm, days=days, limit=limit)
        if llm is None and settings.openai_api_key:
            out["llm_skipped"] = "sign in for LLM-grouped nodes"
        return out


@app.get("/graph/channels")
def graph_channels(product_id: int | None = None,
                   user: dict = Depends(current_user)) -> dict:
    """Which channels this product has, and how much each contributes."""
    from echolens.feedback import CHANNELS, channel_meta, collect_items, configured_channels
    with session_scope() as session:
        prod = _scope(session, product_id, user)
        name = prod.name if prod else None
        items = collect_items(session, name, negatives_only=False)
        counts: dict[str, int] = {}
        for i in items:
            counts[i.channel] = counts.get(i.channel, 0) + 1
        connected = configured_channels(session, name)
        return {
            "product": name,
            "connected": [{"channel": c, **channel_meta(c), "items": counts.get(c, 0)}
                          for c in connected],
            "available": [{"channel": c, **meta} for c, meta in CHANNELS.items()
                          if c not in connected],
        }


def _upload_text(raw: bytes, filename: str | None) -> str:
    """An upload as CSV text, converting Excel first.

    Both import routes take CSV text, so .xlsx is converted here rather than
    given its own importer — the column-alias tolerance and dedup rules are
    inherited, and the same data imports identically either way.

    Detection is by content, not extension: latin-1 never raises, so an .xlsx
    that reached the decode path below would silently become a page of binary
    garbage that parses as a single junk row instead of erroring.
    """
    from echolens.importers.spreadsheet import looks_like_xlsx, xlsx_to_csv

    if looks_like_xlsx(raw, filename):
        try:
            return xlsx_to_csv(raw)
        except ValueError as err:
            raise HTTPException(422, str(err))
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1", errors="replace")


@app.post("/import/feedback")
async def import_feedback(file: UploadFile = File(...), channel: str = "support",
                          product: str = "",
                          user: dict = Depends(require_role("admin"))) -> dict:
    """Import support tickets / in-app feedback / forum threads from a CSV or
    Excel workbook."""
    from echolens.importers.feedback_csv import import_feedback_csv
    # Bounded. `await file.read()` with no cap pulled the entire upload into
    # memory (and csv.DictReader then held a second copy), so one large POST
    # could OOM the single worker this deployment runs.
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"file too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB)")
    text = _upload_text(raw, file.filename)
    try:
        with session_scope() as session:
            return import_feedback_csv(session, text, channel=channel,
                                       product=(product or None))
    except ValueError as err:
        raise HTTPException(422, str(err))


@app.get("/feed/candidates")
@limiter.limit("20/minute")  # builds an LLM client inline — cap runaway spend
def feed_candidates(request: Request, product_id: int | None = None,
                    limit: int = Query(6, ge=1, le=50),
                    refresh: bool = False, user: dict = Depends(current_user)) -> dict:
    """Themes worth investigating that are not yet anomalies.

    A freshly-connected product often has no spike to detect — the detector needs
    a baseline, and a mature app may simply be steadily bad rather than newly
    bad. These come from clustering complaints by meaning, not from counting
    n-grams, which is why they are sentences rather than words.
    """
    from echolens.intent import count_intents
    from echolens.orchestrator.queue import find_existing
    from echolens.themes.discover import cached_themes
    from echolens.themes.overrides import apply_overrides, get_overrides
    from echolens.themes.requests import cached_requests

    with session_scope() as session:
        prod = _scope(session, product_id, user)
        if prod is None:
            return {"candidates": [], "requests": [], "product": None, "engine": "none"}
        # A guest gets the cache or the deterministic fallback, never a fresh
        # LLM call. `refresh` deliberately DEFEATS the cache, so it is the one
        # knob an anonymous caller could use to force unlimited spend — it is
        # honoured only for someone who could pay for it.
        may_spend = _may_spend(user)
        llm = (_metered_llm(session, "themes", prod.id)
               if settings.openai_api_key and may_spend else None)
        result = cached_themes(session, prod.name, llm=llm, limit=limit,
                               package_name=prod.package_name,
                               force=refresh and may_spend)
        out = []
        for th in result.get("themes", []):
            slug = f"theme-p{prod.id}-{th['slug']}"
            # Already queued or investigated? Say so and link, rather than
            # offering a button that would quietly create a duplicate.
            existing = find_existing(session, prod.id, slug)
            out.append({
                "slug": slug,
                "statement": th["statement"],
                "count": th["count"],
                "verbatims": th["verbatims"],
                "trend": th["trend"],
                "label_source": th["label_source"],
                "first_seen": th.get("first_seen"),
                "existing": existing,
                # A cache written before intents existed has none; the quotes
                # are a fair, if smaller, sample of the same reviews.
                "intents": th.get("intents") or count_intents(
                    (v, None) for v in th.get("verbatims") or []),
            })
        # Feature requests / improvements from 3-5 star reviews. Display-only:
        # a wish list is not something to root-cause, so these are not queued.
        req = cached_requests(session, prod.name, llm=llm, limit=limit,
                              package_name=prod.package_name, force=refresh and may_spend)
        requests_out = [{
            "slug": f"request-p{prod.id}-{r['slug']}",
            "statement": r["statement"], "phrase": r.get("phrase"),
            "count": r["count"], "verbatims": r["verbatims"], "trend": r["trend"],
            "label_source": r["label_source"], "avg_rating": r.get("avg_rating"),
            "first_seen": r.get("first_seen"), "intents": r.get("intents"),
            "existing": None,
        } for r in req.get("requests", [])]
        # Corrections people made (rename / merge / mute) go on LAST — after
        # display_themes has merged wording variants and formatted titles — so
        # a name a person typed always wins over a generated one.
        overrides = get_overrides(session, prod.id)
        muted_n = len([o for o in overrides.values() if o.muted])
        out = apply_overrides(out, overrides)
        requests_out = apply_overrides(requests_out, overrides)
        return {"candidates": out, "requests": requests_out, "product": prod.name,
                "engine": result.get("engine"), "cached": result.get("cached", False),
                "reviews_considered": result.get("reviews_considered", 0),
                "requests_considered": req.get("reviews_considered", 0),
                "muted": muted_n,
                "other": result.get("other", 0)}


# ── v10: the investigation queue ────────────────────────────────────────

class QueueThemes(BaseModel):
    slugs: list[str] = Field(default_factory=list, max_length=100)
    statements: dict[str, str] = Field(default_factory=dict, max_length=100)
    tier: str = "quick"
    product_id: int | None = None


@app.post("/queue/themes")
@limiter.limit("20/minute")
def queue_themes(request: Request, body: QueueThemes,
                 user: dict = Depends(require_role("reviewer"))) -> dict:
    """Queue selected themes. Batch by design: selecting three things should cost
    one decision, not three clicks that each fight the daily budget."""
    from echolens.orchestrator.queue import enqueue_theme, queue_view

    with session_scope() as session:
        prod = _scope(session, body.product_id, user)
        pid = prod.id if prod else None
        from echolens.detector.incidents import commit_incident
        queued, already = [], []
        for i, slug in enumerate(body.slugs):
            # Picking an incident sends its lead's slug. The other members are
            # named on the lead's description and recorded as merged into it,
            # BEFORE queueing, so the case starts with the whole picture.
            folded = commit_incident(session, slug, pid, prod.name if prod else None)
            res = enqueue_theme(session, product_id=pid, slug=slug,
                                statement=body.statements.get(slug, ""),
                                tier=body.tier, selection_order=i)
            if folded:
                res["incident_members"] = folded
            (already if res["status"] == "already" else queued).append(res)
        limit = _daily_limit(session, pid)
        view = queue_view(session, pid, limit)

    if queued:
        threading.Thread(target=_drain_queue_bg, args=(pid,), daemon=True).start()
    deferred = len([q for q in view["queued"] if q["status"] == "deferred"])
    parts = []
    if queued:
        parts.append(f"{len(queued)} queued")
    if deferred:
        parts.append(f"{deferred} waiting for tomorrow's budget")
    if already:
        parts.append(f"{len(already)} already under investigation")
    return {"queued": queued, "already": already, "queue": view,
            "summary": " · ".join(parts) or "nothing to queue"}


@app.get("/queue")
def queue_list(product_id: int | None = None, user: dict = Depends(current_user)) -> dict:
    from echolens.orchestrator.queue import queue_view
    with session_scope() as session:
        prod = _scope(session, product_id, user)
        pid = prod.id if prod else None
        return queue_view(session, pid, _daily_limit(session, pid))


@app.delete("/queue/{queue_id}")
def queue_cancel(queue_id: int, product_id: int | None = None,
                 user: dict = Depends(require_role("reviewer"))) -> dict:
    from echolens.db.models import QueuedInvestigation
    from echolens.orchestrator.queue import cancel
    with session_scope() as session:
        # Ownership check first. This took a bare id and cancelled it, so a
        # reviewer scoped to one product could cancel ANOTHER product's queued
        # work just by knowing the number.
        p = _scope(session, product_id, user)
        _owned(session, QueuedInvestigation, queue_id, p.id if p else None)
        if not cancel(session, queue_id):
            raise HTTPException(409, "that item is already running or finished")
    return {"cancelled": queue_id}


@app.post("/queue/{queue_id}/run-now")
@limiter.limit("6/minute")  # each one is a paid run past the budget
def queue_run_now(request: Request, queue_id: int, product_id: int | None = None,
                  user: dict = Depends(require_role("reviewer"))) -> dict:
    """Run ONE deferred item now, past today's cap, and record who did it.

    The cap stays the default for everything else; this is a deliberate,
    audited exception for a single row. The cost shown is an estimate.
    """
    from echolens.db.models import QueuedInvestigation
    from echolens.orchestrator import queue as q
    with session_scope() as session:
        p = _scope(session, product_id, user)
        pid = p.id if p else None
        row = _owned(session, QueuedInvestigation, queue_id, pid)
        estimate = q.estimate_cost(session, row.budget_tier or "quick", pid)
        who = user.get("email") or f"user:{user.get('id')}"
        claimed = q.claim_override(session, queue_id, user=who, estimate_usd=estimate["usd"])
        if claimed is None:
            raise HTTPException(409, "that item is already running or finished")
        investigation_id, tier = _open_claimed(session, claimed, pid)
    threading.Thread(target=_run_claimed_bg, args=(queue_id, investigation_id, tier),
                     daemon=True).start()
    return {"status": "started", "queue_id": queue_id, "investigation_id": investigation_id,
            "estimate": estimate, "override_by": who}


class ThemeOverrideBody(BaseModel):
    slug: str = Field(min_length=1, max_length=128)
    action: str
    label: str | None = Field(default=None, max_length=200)
    into: str | None = Field(default=None, max_length=128)
    product_id: int | None = None


@app.get("/themes/overrides")
def theme_overrides_list(product_id: int | None = None,
                         user: dict = Depends(current_user)) -> dict:
    from echolens.themes.overrides import override_dicts
    with session_scope() as session:
        p = _scope(session, product_id, user)
        return {"overrides": override_dicts(session, p.id if p else None)}


@app.post("/themes/overrides")
def theme_overrides_set(body: ThemeOverrideBody,
                        user: dict = Depends(require_role("reviewer"))) -> dict:
    """Rename, merge or mute a discovered theme for this product. Persisted,
    so the correction survives the next re-discovery."""
    from echolens.themes.overrides import override_dicts, set_override
    with session_scope() as session:
        p = _scope(session, body.product_id, user)
        pid = p.id if p else None
        try:
            set_override(session, pid, body.slug, body.action, label=body.label,
                         into=body.into, user=user.get("email"))
        except ValueError as err:
            raise HTTPException(422, str(err))
        return {"overrides": override_dicts(session, pid)}


@app.get("/intents")
def intents_view(product_id: int | None = None, days: int = Query(90, ge=1, le=365),
                 user: dict = Depends(current_user)) -> dict:
    """What this product's reviews are FOR, over the window: bug, feature
    request, UX confusion, praise, other."""
    with session_scope() as session:
        p = _scope(session, product_id, user)
        return _product_intents(session, p.name if p else None, days)


def _product_intents(session, product: str | None, days: int = 90) -> dict:
    from echolens.detector.detect import reference_now
    from echolens.intent import count_intents, empty_counts
    if not product:
        return {"product": None, "days": days, "total": 0, "counts": empty_counts()}
    now = reference_now(session, product)
    rows = session.execute(select(Review.text, Review.rating).where(
        Review.product == product,
        Review.created_at >= (now - timedelta(days=days)).replace(tzinfo=None))
        .limit(20000)).all()
    counts = count_intents((t, r) for t, r in rows)
    return {"product": product, "days": days, "total": len(rows), "counts": counts}


@app.post("/import/reviews")
async def import_reviews(file: UploadFile = File(...), product: str = "", source: str = "csv",
                        product_id: int | None = None,
                        user: dict = Depends(require_role("admin"))) -> dict:
    """Import reviews from any export (App Store, Zendesk, spreadsheet) as CSV
    or Excel. Widens the evidence base beyond the live scrapers. Idempotent by
    content hash.

    product_id wins over the free-text `product`. Import is offered from a
    per-product screen, but the form defaulted the name to "" and the importer
    then wrote Review(product=None) — the rows landed attached to NO product and
    were invisible to every scoped screen in the app.
    """
    from echolens.importers.csv_reviews import import_reviews_csv
    # Bounded. `await file.read()` with no cap pulled the entire upload into
    # memory (and csv.DictReader then held a second copy), so one large POST
    # could OOM the single worker this deployment runs.
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"file too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB)")
    text = _upload_text(raw, file.filename)
    with session_scope() as session:
        name = product or None
        if product_id is not None:
            prod = _scope(session, product_id, user)
            if prod is not None:
                name = prod.name
        try:
            result = import_reviews_csv(session, text, product=name, source=(source or "csv"))
        except ValueError as err:
            raise HTTPException(422, str(err))
    return result


@app.get("/snapshot")
def snapshot(product: str | None = None, product_id: int | None = None,
             days: int = Query(90, ge=1, le=365),
             user: dict = Depends(current_user)) -> dict:
    """Health snapshot for a product (or the whole corpus) — powers the
    'Investigate now on anything' entry point outside onboarding."""
    from echolens.onboarding.snapshot import health_snapshot
    with session_scope() as session:
        if _guest_locked(user) and product is not None:
            if product not in {p.name for p in _visible_products(session, user)}:
                raise HTTPException(404, "no such product")
        if product is None:
            p = _scope(session, product_id, user)
            product = p.name if p else None
        return health_snapshot(session, product=product, days=days)


@app.get("/today/overview")
def today_overview_view(product_id: int | None = None,
                  user: dict = Depends(current_user)) -> dict:
    """What Today draws around the score: releases inside the charted window,
    the rating-drop breakdown (an estimate), when sources last synced, and the
    fixes confirmed in the last two weeks that this user has not dismissed."""
    from echolens.evidence_summary import recent_confirmed_fixes
    from echolens.overview import overview
    with session_scope() as session:
        p = _scope(session, product_id, user)
        fixes = recent_confirmed_fixes(session, p.id, user.get("id")) if p is not None else []
        return {**overview(session, p), "confirmed_fixes": fixes}


@app.post("/fixwatch/{watch_id}/dismiss")
def fixwatch_dismiss(watch_id: int, product_id: int | None = None,
                     user: dict = Depends(require_role("reviewer"))) -> dict:
    """Hide a "Fix confirmed" card from YOUR Today. Per user: a teammate who has
    not seen it yet still does."""
    from echolens.db.models import FixWatch
    from echolens.evidence_summary import dismiss_fix
    with session_scope() as session:
        p = _scope(session, product_id, user)
        watch = _owned(session, FixWatch, watch_id, p.id if p else None)
        if user.get("id") is None:
            raise HTTPException(422, "sign in to dismiss")
        dismiss_fix(session, user["id"], watch.id)
        return {"dismissed": watch.id}


@app.post("/search/embed")
def search_embed(product_id: int | None = None,
                 user: dict = Depends(require_role("admin"))) -> dict:
    """Backfill embeddings over the corpus so semantic search activates (v1.0)."""
    from echolens.search.semantic import embed_corpus
    with session_scope() as session:
        prod = _scope(session, product_id, user)
        return {"embedded": embed_corpus(session, product=(prod.name if prod else None))}


@app.post("/anomalies/scan")
def anomalies_scan(product_id: int | None = None,
                   user: dict = Depends(require_role("reviewer"))) -> dict:
    from echolens.detector.detect import scan
    with session_scope() as session:
        p = _scope(session, product_id, user)
        events = scan(session, product=(p.name if p else None), product_id=(p.id if p else None))
        return {"detected": [e.slug for e in events], "product": p.name if p else None}


@app.get("/anomalies")
def list_anomalies(product_id: int | None = None, user: dict = Depends(current_user)) -> dict:
    with session_scope() as session:
        p = _scope(session, product_id, user)
        stmt = select(AnomalyEvent).where(AnomalyEvent.merged_into_id.is_(None))
        if p is not None:
            stmt = stmt.where(AnomalyEvent.product_id == p.id)
        rows = session.scalars(stmt.order_by(AnomalyEvent.id)).all()
        return {"anomalies": _anomaly_dicts(session, rows)}


@app.get("/cases")
def list_cases(product_id: int | None = None, user: dict = Depends(current_user)) -> dict:
    """The unified case list — one lifecycle, one status vocabulary.

    Replaces the three overlapping surfaces (feed / health / archive) that each
    described the same case differently. Everything a card renders is decided
    here so the same case cannot look like two different things on two screens.
    """
    from echolens.detector.incidents import incident_view
    from echolens.orchestrator.queue import queue_view
    from echolens.themes.overrides import muted_word_sets
    with session_scope() as session:
        p = _scope(session, product_id, user)
        pid = p.id if p else None
        view = case_view(session, pid)
        name = p.name if p else None
        # Signals: intent counts, muted themes hidden, related ones grouped into
        # incidents. Members stay in `signals`; incidents only reference them.
        view["signals"], view["incidents"] = incident_view(
            session, name, view["signals"], muted_word_sets(session, pid))
        view["intents"] = _product_intents(session, name)
        # Queued rows past today's cap say so, with the override's estimate.
        limit = _daily_limit(session, pid)
        q = {i["queue_id"]: i for i in queue_view(session, pid, limit)["queued"]}
        for row in view["cases"]:
            item = q.get(row.get("queue_id")) if row.get("queue_id") is not None else None
            if item is None:
                continue
            row["deferred"] = item["status"] == "deferred"
            row["budget_tier"] = item.get("budget_tier")
            if row["deferred"]:
                row["why"] = item["note"]
                row["estimate"] = item.get("estimate")
        # The trust badge on every card with a finding, batched for the list.
        from echolens.evidence_summary import trust_for_cases
        trust = trust_for_cases(session, [r["id"] for r in view["cases"]
                                          if r.get("id") is not None and r.get("finding_id")])
        for row in view["cases"]:
            row["trust"] = trust.get(row.get("id"))
        view["daily_limit"] = limit
        return view


# Named Cases filters. Personal view writes use the same reviewer/CSRF guard
# as other app mutations; guests keep their views in the browser instead.
class SavedViewBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    params: dict[str, str] = Field(default_factory=dict, max_length=6)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        if not value.strip():
            raise ValueError("Give the view a name")
        return value.strip()

    @field_validator("params")
    @classmethod
    def case_filters(cls, value):
        if set(value) - {"tab", "sev", "source", "range", "intent", "q"}:
            raise ValueError("Only Cases filters can be saved")
        if any(len(v) > 500 for v in value.values()):
            raise ValueError("Filter values must be 500 characters or fewer")
        return {k: v for k, v in value.items() if v}


def _view_query(session, user, product_id):
    from echolens.db.models import SavedView
    if user.get("guest") or user.get("id") is None:
        raise HTTPException(403, "Sign in to store views on the server")
    _scope(session, product_id, user)
    return select(SavedView).where(SavedView.user_id == user["id"],
                                   SavedView.product_id == product_id)


def _saved_view_dict(row):
    return {"id": row.id, "product_id": row.product_id, "name": row.name,
            "params": row.params, "created_at": aware_utc(row.created_at).isoformat()}


def _flush_view(session):
    from sqlalchemy.exc import IntegrityError
    try:
        session.flush()
    except IntegrityError:
        raise HTTPException(409, "A view with that name already exists")


@app.get("/views")
def list_saved_views(product_id: int = Query(gt=0), user: dict = Depends(current_user)) -> dict:
    from echolens.db.models import SavedView
    with session_scope() as session:
        stmt = _view_query(session, user, product_id)
        return {"views": [_saved_view_dict(v) for v in session.scalars(
            stmt.order_by(SavedView.created_at, SavedView.id)).all()]}


@app.post("/views", status_code=201)
def create_saved_view(body: SavedViewBody, product_id: int = Query(gt=0),
                      user: dict = Depends(require_role("reviewer"))) -> dict:
    from sqlalchemy import JSON, insert, literal
    from sqlalchemy.exc import IntegrityError
    from echolens.db.models import Product, SavedView
    with session_scope() as session:
        stmt = _view_query(session, user, product_id)
        # Postgres serializes creations for this product. SQLite ignores FOR
        # UPDATE, so keep its cap check inside the atomic INSERT as well.
        session.execute(select(Product.id).where(Product.id == product_id).with_for_update())
        count = select(func.count()).select_from(stmt.subquery()).scalar_subquery()
        values = select(literal(user["id"]), literal(product_id), literal(body.name),
                        literal(body.params, type_=JSON), literal(datetime.now(timezone.utc)))
        create = insert(SavedView).from_select(
            ["user_id", "product_id", "name", "params", "created_at"],
            values.where(count < 20)).returning(SavedView)
        try:
            row = session.scalars(create).one_or_none()
        except IntegrityError:
            raise HTTPException(409, "A view with that name already exists")
        if row is None:
            raise HTTPException(409, "You can save up to 20 views per product")
        return _saved_view_dict(row)


@app.put("/views/{view_id}")
def update_saved_view(view_id: int, body: SavedViewBody, product_id: int = Query(gt=0),
                      user: dict = Depends(require_role("reviewer"))) -> dict:
    from echolens.db.models import SavedView
    with session_scope() as session:
        row = session.scalar(_view_query(session, user, product_id).where(SavedView.id == view_id))
        if row is None:
            raise HTTPException(404, "No saved view with that id")
        row.name, row.params = body.name, body.params
        _flush_view(session)
        return _saved_view_dict(row)


@app.delete("/views/{view_id}")
def delete_saved_view(view_id: int, product_id: int = Query(gt=0),
                      user: dict = Depends(require_role("reviewer"))) -> dict:
    from echolens.db.models import SavedView
    with session_scope() as session:
        row = session.scalar(_view_query(session, user, product_id).where(SavedView.id == view_id))
        if row is None:
            raise HTTPException(404, "No saved view with that id")
        session.delete(row)
        return {"deleted": view_id}


def _triage_summary(considered: int, already: int, started: int, run: bool) -> str:
    """One line the reviewer can trust. The old wording said '0 new → investigating'
    on a preview, which claimed work that never happened."""
    if considered == 0:
        return "Nothing pending — every anomaly already has a case or was dismissed."
    n = f"{considered} anomaly" if considered == 1 else f"{considered} anomalies"
    if not run:
        return f"{n} reviewed — preview only, nothing started. Press Run triage to open cases."
    if started == 0:
        if already:
            return f"{n}, already triaged — every one has a case; nothing new to open."
        return f"{n}, none met the bar to investigate."
    kept = f", {already} already triaged" if already else ""
    return f"{n}{kept} → investigating {started}."


@app.post("/anomalies/triage")
@limiter.limit("10/minute")
def anomalies_triage(request: Request, run: bool = False, product_id: int | None = None,
                     user: dict = Depends(require_role("reviewer"))) -> dict:
    from echolens.orchestrator.triage import Orchestrator
    to_run: list[tuple[int, str]] = []
    skipped_already_triaged = 0
    with session_scope() as session:
        p = _scope(session, product_id, user)
        pid = p.id if p else None
        # A preview (run=false) must not consume the pending queue — see
        # Orchestrator.triage(persist=...).
        decisions = Orchestrator(session, daily_limit=_daily_limit(session, pid),
                                 product_id=pid).triage(persist=run)
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
        "summary": _triage_summary(len(out), skipped_already_triaged, len(to_run), run),
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
        prod = _scope(session, body.product_id, user)
        pid = prod.id if prod else None
        opened_by = "anomaly"
        if body.anomaly_slug:
            anomaly_stmt = select(AnomalyEvent).where(
                AnomalyEvent.slug == body.anomaly_slug)
            if pid is not None:
                anomaly_stmt = anomaly_stmt.where(AnomalyEvent.product_id == pid)
            anomaly = session.scalars(anomaly_stmt).first()
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
            # Never adopt scope from a row found workspace-wide. With a scoped
            # request, the query above proves the anomaly belongs to this
            # product before either the duplicate guard or creation can expose
            # another product's case id.
        elif body.description:
            opened_by = "manual"
            anomaly = AnomalyEvent(
                slug=_unique_slug("manual"), type="manual",
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
                            data_notes=_data_notes(session, pid), product_id=pid)
        session.add(inv)
        anomaly.status = "investigating"
        session.flush()
        investigation_id, anomaly_id = inv.id, anomaly.id

    threading.Thread(target=_run_investigation_bg,
                     args=(investigation_id, body.tier), daemon=True).start()
    return {"status": "started", "investigation_id": investigation_id, "anomaly_id": anomaly_id}


@app.get("/investigations")
def list_investigations(product_id: int | None = None, user: dict = Depends(current_user)) -> dict:
    """Every investigation, plus anything still waiting to become one.

    The frontend's work-watcher polls this and refreshes the screens when the
    busy count falls. Queued items live in `queued_investigations` and have no
    Investigation row until they are claimed, so returning only Investigation
    rows made the watcher blind to them: it saw zero busy work, stopped polling,
    and the queue only appeared to advance when the user reloaded the page.
    """
    from echolens.db.models import QueuedInvestigation
    with session_scope() as session:
        p = _scope(session, product_id, user)
        stmt = select(Investigation).order_by(Investigation.id.desc())
        if p is not None:
            stmt = stmt.where(Investigation.product_id == p.id)
        rows = session.scalars(stmt).all()
        out = [{"id": i.id, "status": i.status, "opened_by": i.opened_by,
                "budget_tier": i.budget_tier, "anomaly_id": i.anomaly_id} for i in rows]

        # Pending queue entries, as work the watcher can count. `investigation_id`
        # is null until one is claimed, so an entry that already has one is
        # skipped — it is the Investigation row above and must not count twice.
        q_stmt = select(QueuedInvestigation).where(
            QueuedInvestigation.status.in_(("queued", "running")),
            QueuedInvestigation.investigation_id.is_(None))
        if p is not None:
            q_stmt = q_stmt.where(QueuedInvestigation.product_id == p.id)
        for q in session.scalars(q_stmt.order_by(QueuedInvestigation.id.desc())).all():
            out.append({"id": None, "queue_id": q.id, "status": q.status,
                        "opened_by": q.source, "budget_tier": q.budget_tier,
                        "anomaly_id": q.anomaly_id})
        return {"investigations": out}


@app.get("/investigations/{inv_id}")
def get_investigation(inv_id: int, product_id: int | None = None,
                      user: dict = Depends(current_user)) -> dict:
    with session_scope() as session:
        p = _scope(session, product_id, user)
        inv = _owned(session, Investigation, inv_id, p.id if p else None)
        return _investigation_dict(session, inv)


# ── v5.0 collaboration ──────────────────────────────────────────────────

class CommentBody(BaseModel):
    body: str
    parent_id: int | None = None


class ReviewRequestBody(BaseModel):
    requested_of_id: int | None = None
    note: str = ""


class ResolveRequestBody(BaseModel):
    status: str          # approved | changes_requested | cancelled


@app.get("/investigations/{inv_id}/comments")
def list_comments(inv_id: int, product_id: int | None = None,
                  user: dict = Depends(current_user)) -> dict:
    """The discussion on a case. Readable by anyone who can read the case,
    guests included — reading a thread leaks nothing the case itself doesn't."""
    from echolens.collab import comment_thread
    with session_scope() as session:
        p = _scope(session, product_id, user)
        inv = _owned(session, Investigation, inv_id, p.id if p else None)
        return {"investigation_id": inv.id, "comments": comment_thread(session, inv.id)}


@app.post("/investigations/{inv_id}/comments")
def post_comment(inv_id: int, body: CommentBody, product_id: int | None = None,
                 user: dict = Depends(require_role("reviewer"))) -> dict:
    """Post a comment. Reviewer or above: the GUEST principal has id None by
    design, and an unattributed comment on a review thread is worse than none."""
    from echolens.collab import add_comment, comment_thread
    with session_scope() as session:
        p = _scope(session, product_id, user)
        inv = _owned(session, Investigation, inv_id, p.id if p else None)
        try:
            comment = add_comment(session, inv.id, body.body, user.get("id"),
                                  parent_id=body.parent_id)
        except ValueError as err:
            raise HTTPException(422, str(err))
        return {"posted": comment.id,
                "comments": comment_thread(session, inv.id)}


@app.patch("/comments/{comment_id}")
def patch_comment(comment_id: int, body: CommentBody, product_id: int | None = None,
                  user: dict = Depends(require_role("reviewer"))) -> dict:
    from echolens.collab import edit_comment
    from echolens.db.models import Comment
    with session_scope() as session:
        p = _scope(session, product_id, user)
        comment = _owned(session, Comment, comment_id, p.id if p else None)
        try:
            edit_comment(session, comment, body.body, user.get("id"))
        except PermissionError as err:
            raise HTTPException(403, str(err))
        except ValueError as err:
            raise HTTPException(422, str(err))
        return {"edited": comment.id}


@app.delete("/comments/{comment_id}")
def remove_comment(comment_id: int, product_id: int | None = None,
                   user: dict = Depends(require_role("reviewer"))) -> dict:
    from echolens.collab import delete_comment
    from echolens.db.models import Comment
    with session_scope() as session:
        p = _scope(session, product_id, user)
        comment = _owned(session, Comment, comment_id, p.id if p else None)
        try:
            delete_comment(session, comment, user.get("id"),
                           is_admin=(user.get("role") == "admin"))
        except PermissionError as err:
            raise HTTPException(403, str(err))
        return {"deleted": comment.id}


@app.get("/mentions")
def list_mentions(product_id: int | None = None, unread_only: bool = True,
                  limit: int = Query(50, ge=1, le=200),
                  user: dict = Depends(require_role("reviewer"))) -> dict:
    """Your mention inbox. Always the CALLER's — a user id is never taken from
    the query string, so one user cannot read another's inbox."""
    from echolens.collab import inbox
    with session_scope() as session:
        p = _scope(session, product_id, user)
        uid = user.get("id")
        if uid is None:
            return {"mentions": [], "unread": 0}
        rows = inbox(session, uid, product_id=(p.id if p else None),
                     unread_only=unread_only, limit=limit)
        return {"mentions": rows, "unread": sum(1 for r in rows if not r["read"])}


@app.post("/mentions/read")
def read_mentions(mention_ids: list[int] | None = None, product_id: int | None = None,
                  user: dict = Depends(require_role("reviewer"))) -> dict:
    from echolens.collab import mark_read
    if mention_ids is not None and len(mention_ids) > 200:
        raise HTTPException(422, "at most 200 mentions can be marked at once")
    with session_scope() as session:
        p = _scope(session, product_id, user)
        uid = user.get("id")
        if uid is None:
            return {"marked": 0}
        return {"marked": mark_read(session, uid, mention_ids,
                                    product_id=(p.id if p else None))}


@app.post("/investigations/{inv_id}/review-request")
def create_review_request(inv_id: int, body: ReviewRequestBody,
                          product_id: int | None = None,
                          user: dict = Depends(require_role("reviewer"))) -> dict:
    from echolens.collab import request_review
    with session_scope() as session:
        p = _scope(session, product_id, user)
        inv = _owned(session, Investigation, inv_id, p.id if p else None)
        try:
            req = request_review(session, inv.id, user.get("id"),
                                 requested_of_id=body.requested_of_id, note=body.note)
        except ValueError as err:
            raise HTTPException(422, str(err))
        return {"request_id": req.id, "status": req.status}


@app.post("/review-requests/{req_id}/resolve")
def resolve_review_request(req_id: int, body: ResolveRequestBody,
                           product_id: int | None = None,
                           user: dict = Depends(require_role("reviewer"))) -> dict:
    """Close a review request. Deliberately does NOT move the finding's status —
    approve/challenge remain the only paths to that, so a sign-off cannot
    smuggle a conclusion past the evidence checks."""
    from echolens.collab import resolve_request
    from echolens.db.models import ReviewRequest
    with session_scope() as session:
        p = _scope(session, product_id, user)
        req = _owned(session, ReviewRequest, req_id, p.id if p else None)
        try:
            resolve_request(session, req, body.status)
        except ValueError as err:
            raise HTTPException(422, str(err))
        return {"request_id": req.id, "status": req.status}


@app.get("/team")
def team_view(product_id: int | None = None,
              user: dict = Depends(current_user)) -> dict:
    """Team dashboard: what is awaiting review and who is discussing what."""
    from echolens.collab import team_activity
    with session_scope() as session:
        p = _scope(session, product_id, user)
        if p is None:
            return {"awaiting_review": [], "recent_comments": [],
                    "contributors": [], "open_request_count": 0, "product": None}
        return {**team_activity(session, p.id), "product": p.name}


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


def _extend_investigation_bg(inv_id: int, note: str) -> None:
    """Run a reviewer-granted extension (v15). Same guard as every other
    background run: a crash must not leave the case stuck at "running"."""
    from echolens.investigator.graph import Investigator
    from echolens.recommender.recommend import recommend
    try:
        with session_scope() as session:
            inv = session.get(Investigation, inv_id)
            if inv is None or inv.status != "running":
                return
            inv = Investigator.resume(session, inv, reason=note)
            finding = session.scalars(select(Finding).where(
                Finding.investigation_id == inv.id).order_by(Finding.id.desc())).first()
            if finding is not None:
                recommend(session, finding)
                _try_notify(session, finding)
    except Exception as err:
        log.error("extension_failed", investigation_id=inv_id, error=str(err))
        _mark_investigation_failed(inv_id, str(err))


@app.post("/investigations/{inv_id}/extend")
@limiter.limit("6/minute")  # each extension spends money — same cap as starting a case
def extend_investigation(request: Request, inv_id: int, product_id: int | None = None,
                         user: dict = Depends(require_role("reviewer"))) -> dict:
    """Continue a dead-end case (budget ran out / not enough evidence) from its
    checkpoint with EXTENSION_STEPS more steps. At most MAX_HUMAN_EXTENSIONS
    per case; the response carries the estimate shown on the button."""
    from echolens.investigator.recover import extension_trace_note, grant_extension
    with session_scope() as session:
        p = _scope(session, product_id, user)
        inv = _owned(session, Investigation, inv_id, p.id if p else None)
        try:
            granted = grant_extension(session, inv, by=user.get("email"))
        except ValueError as err:
            raise HTTPException(422, str(err))
        note = extension_trace_note(granted["prior_status"], granted["steps"])
    threading.Thread(target=_extend_investigation_bg, args=(inv_id, note), daemon=True).start()
    return {"status": "extending", "id": inv_id, "by": user["email"], **granted}


@app.post("/investigations/{inv_id}/pause")
def pause_investigation(inv_id: int, product_id: int | None = None,
                       user: dict = Depends(require_role("reviewer"))) -> dict:
    with session_scope() as session:
        p = _scope(session, product_id, user)
        inv = _owned(session, Investigation, inv_id, p.id if p else None)
        inv.paused = True
        return {"status": "pausing", "id": inv_id}


@app.post("/investigations/{inv_id}/resume")
def resume_investigation(inv_id: int, product_id: int | None = None,
                        user: dict = Depends(require_role("reviewer"))) -> dict:
    with session_scope() as session:
        p = _scope(session, product_id, user)
        inv = _owned(session, Investigation, inv_id, p.id if p else None)
        if inv.status != "running":
            raise HTTPException(422, f"cannot resume a {inv.status} investigation")
        inv.paused = False
    threading.Thread(target=_resume_investigation_bg, args=(inv_id,), daemon=True).start()
    return {"status": "resuming", "id": inv_id}


@app.post("/investigations/{inv_id}/escalate")
def escalate_investigation(inv_id: int, product_id: int | None = None,
                          user: dict = Depends(require_role("reviewer"))) -> dict:
    with session_scope() as session:
        p = _scope(session, product_id, user)
        inv = _owned(session, Investigation, inv_id, p.id if p else None)
        inv.escalated = True
        return {"status": "escalated", "id": inv_id, "by": user["email"]}


@app.get("/investigations/{inv_id}/trace")
def get_trace(inv_id: int, after: int = Query(0, ge=0, le=2_147_483_647),
              product_id: int | None = None,
              user: dict = Depends(current_user)) -> dict:
    with session_scope() as session:
        p = _scope(session, product_id, user)
        inv = _owned(session, Investigation, inv_id, p.id if p else None)
        steps = session.scalars(select(TraceStep).where(
            TraceStep.investigation_id == inv_id, TraceStep.seq > after
        ).order_by(TraceStep.seq)).all()
        return {"status": inv.status, "steps": [_trace_dict(t) for t in steps]}


# An SSE tail must end. Without a ceiling the generator looped forever whenever
# a case was stuck at "running" (which, before the _run_investigation_bg guard,
# happened whenever a background thread died), pinning a threadpool worker and
# opening a DB connection twice a second until the pool was exhausted.
SSE_MAX_SECONDS = 15 * 60


def _sse(event: str, payload: dict) -> str:
    """One server-sent event. Kept as a helper so the wire format lives in one
    place rather than being re-escaped at four call sites."""
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


@app.get("/investigations/{inv_id}/trace/stream")
async def stream_trace(inv_id: int, request: Request, product_id: int | None = None,
                       token: str | None = None) -> StreamingResponse:
    """SSE tail of the trace_steps table until the investigation stops running.

    Auth: the Authorization header, else the session cookie (the browser opens
    the stream with `new EventSource(url, {withCredentials: true})`, which sends
    it), else — DEPRECATED, for one release — `?token=`. A JWT in the query
    string lands in proxy and access logs and browser history, so the frontend
    no longer sends one; any caller still doing so is logged.
    """
    # This route authenticates by hand (the token may still arrive in the query
    # string), so there is no `user` dependency to hand to _scope. Build the
    # same principal shape those dependencies produce, so guest scoping and the
    # role-from-DB lookup apply here too.
    user: dict = dict(GUEST)
    if settings.auth_required:
        raw, _via_cookie = session_token(request)
        if raw is None and token:
            log.warning("deprecated_query_token", route="trace/stream",
                        detail="?token= is deprecated; use the session cookie or a Bearer header")
            raw = token
        ok = False
        if raw:
            try:
                user = principal_from_token(raw)
                ok = True
            except HTTPException:
                ok = False
        # A guest may tail a demo product's trace, but only when guests are
        # allowed at all; otherwise a token is still required.
        if not ok and settings.allow_guest and not raw:
            ok = True
        if not ok:
            raise HTTPException(401, "missing or invalid token")
    else:
        user = dict(DEV_ADMIN)

    with session_scope() as session:
        p = _scope(session, product_id, user)
        _owned(session, Investigation, inv_id, p.id if p else None)

    async def gen():
        sent = 0
        started = time.monotonic()
        while True:
            # Stop when the client goes away. Nothing checked this, so closing
            # the tab left the loop running server-side until the case settled.
            if await request.is_disconnected():
                return
            if time.monotonic() - started > SSE_MAX_SECONDS:
                yield _sse("done", {"status": "stream_timeout"})
                return
            with session_scope() as session:
                inv = session.get(Investigation, inv_id)
                if inv is None:
                    yield _sse("error", {"error": "not found"})
                    return
                steps = session.scalars(select(TraceStep).where(
                    TraceStep.investigation_id == inv_id, TraceStep.seq > sent
                ).order_by(TraceStep.seq)).all()
                for t in steps:
                    sent = t.seq
                    yield _sse("step", _trace_dict(t))
                if inv.status != "running":
                    yield _sse("done", {"status": inv.status})
                    return
            # await, not time.sleep: a blocking sleep held a threadpool worker
            # hostage for the entire life of the stream.
            await asyncio.sleep(0.5)
    return StreamingResponse(gen(), media_type="text/event-stream")


class ReviewBody(BaseModel):
    action: str  # approve | challenge
    note: str = ""
    reason: str | None = None  # v5.0 structured challenge category


@app.post("/findings/{finding_id}/review")
def review_finding(finding_id: int, body: ReviewBody, product_id: int | None = None,
                   user: dict = Depends(require_role("reviewer"))) -> dict:
    from echolens import review
    with session_scope() as session:
        p = _scope(session, product_id, user)
        finding = _owned_finding(session, finding_id, p.id if p else None)
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


# ── v15: product decisions, partial challenges, sharing ─────────────────

class DecisionBody(BaseModel):
    decision: str                       # fix_now | park | wont_fix | cleared
    revisit_by: date | None = None      # park only
    reason: str = Field("", max_length=2000)


@app.post("/findings/{finding_id}/decision")
def decide_finding(finding_id: int, body: DecisionBody, product_id: int | None = None,
                   user: dict = Depends(require_role("reviewer"))) -> dict:
    """Record what the team is doing about a finding — separate from whether it
    is true. Parked and won't-fix findings leave the open-problem lists."""
    from echolens import review
    with session_scope() as session:
        p = _scope(session, product_id, user)
        finding = _owned_finding(session, finding_id, p.id if p else None)
        revisit = (datetime.combine(body.revisit_by, datetime.min.time(), tzinfo=timezone.utc)
                   if body.revisit_by else None)
        try:
            review.decide(session, finding, body.decision, revisit_by=revisit,
                          reason=body.reason, user_id=user["id"])
        except ValueError as err:
            raise HTTPException(422, str(err))
        return {"finding_id": finding_id, "product_decision": _decision_view(session, finding_id),
                "by": user["email"]}


class RejectEvidenceBody(BaseModel):
    note: str = Field("", max_length=2000)
    reason: str | None = None


@app.post("/findings/{finding_id}/evidence/{eid}/reject")
def reject_finding_evidence(finding_id: int, eid: str, body: RejectEvidenceBody,
                            product_id: int | None = None,
                            user: dict = Depends(require_role("reviewer"))) -> dict:
    """Partial challenge: "this quote doesn't support it". Re-checks the
    two-source rule on what remains instead of re-opening the case."""
    from echolens import review
    with session_scope() as session:
        p = _scope(session, product_id, user)
        finding = _owned_finding(session, finding_id, p.id if p else None)
        if finding.status == "challenged":
            raise HTTPException(422, "this finding was challenged and re-opened — review the new case")
        try:
            result = review.reject_evidence(session, finding, eid, note=body.note,
                                            reason=body.reason, user_id=user["id"])
        except LookupError as err:
            raise HTTPException(404, str(err))
        except ValueError as err:
            raise HTTPException(422, str(err))
        return {**result, "finding_status": finding.status, "by": user["email"]}


class EditRecommendationBody(BaseModel):
    effort: str | None = None
    impact: str | None = None
    note: str = Field("", max_length=2000)


@app.patch("/findings/{finding_id}/recommendations/{rank}")
def edit_finding_recommendation(finding_id: int, rank: int, body: EditRecommendationBody,
                                product_id: int | None = None,
                                user: dict = Depends(require_role("reviewer"))) -> dict:
    """Partial challenge: correct one action's effort/impact, nothing else."""
    from echolens import review
    with session_scope() as session:
        p = _scope(session, product_id, user)
        finding = _owned_finding(session, finding_id, p.id if p else None)
        try:
            rec = review.edit_recommendation(session, finding, rank, effort=body.effort,
                                             impact=body.impact, note=body.note,
                                             user_id=user["id"])
        except LookupError as err:
            raise HTTPException(404, str(err))
        except ValueError as err:
            raise HTTPException(422, str(err))
        return {"rank": rec.rank, "action": rec.action, "impact": rec.impact,
                "effort": rec.effort, "by": user["email"]}


@app.get("/findings/{finding_id}/brief")
def finding_brief(finding_id: int, link: str | None = Query(None, max_length=500),
                  product_id: int | None = None, user: dict = Depends(current_user)) -> dict:
    """Clean Markdown for Slack/Notion: headline, impact, a few user quotes,
    recommended actions, a link. No evidence ids, no internal statuses."""
    from echolens.exporting import share_brief
    with session_scope() as session:
        p = _scope(session, product_id, user)
        finding = _owned_finding(session, finding_id, p.id if p else None)
        return share_brief(session, finding, link=link)


def _active_share(session, finding_id: int):
    from echolens.db.models import ShareLink
    return session.scalars(select(ShareLink).where(
        ShareLink.finding_id == finding_id, ShareLink.revoked_at.is_(None))
        .order_by(ShareLink.id.desc())).first()


def _share_dict(link) -> dict:
    if link is None:
        return {"active": False, "token": None, "created_at": None, "url": None}
    base = settings.app_base_url.rstrip("/")
    return {"active": True, "token": link.token,
            "created_at": aware_utc(link.created_at).isoformat() if link.created_at else None,
            "url": f"{base}/#/share/{link.token}" if base else None}


@app.get("/findings/{finding_id}/share")
def get_share_link(finding_id: int, product_id: int | None = None,
                   user: dict = Depends(require_role("reviewer"))) -> dict:
    with session_scope() as session:
        p = _scope(session, product_id, user)
        _owned_finding(session, finding_id, p.id if p else None)
        return _share_dict(_active_share(session, finding_id))


@app.post("/findings/{finding_id}/share")
def create_share_link(finding_id: int, product_id: int | None = None,
                      user: dict = Depends(require_role("reviewer"))) -> dict:
    """A read-only public link to this finding's brief. Idempotent: an active
    link is returned rather than minting a second credential for one brief."""
    import secrets
    from echolens.db.models import ShareLink
    with session_scope() as session:
        p = _scope(session, product_id, user)
        finding = _owned_finding(session, finding_id, p.id if p else None)
        link = _active_share(session, finding_id)
        if link is None:
            link = ShareLink(finding_id=finding.id, token=secrets.token_urlsafe(32),
                             product_id=finding.product_id, created_by=user.get("id"))
            session.add(link)
            session.flush()
        return _share_dict(link)


@app.delete("/findings/{finding_id}/share")
def revoke_share_link(finding_id: int, product_id: int | None = None,
                      user: dict = Depends(require_role("reviewer"))) -> dict:
    with session_scope() as session:
        p = _scope(session, product_id, user)
        _owned_finding(session, finding_id, p.id if p else None)
        from echolens.db.models import ShareLink
        now = datetime.now(timezone.utc)
        for link in session.scalars(select(ShareLink).where(
                ShareLink.finding_id == finding_id, ShareLink.revoked_at.is_(None))).all():
            link.revoked_at = now
        return _share_dict(None)


@app.get("/share/{token}")
@limiter.limit("60/minute")  # public and unauthenticated — cap token guessing
def public_share(token: str, request: Request) -> dict:
    """The ONE unauthenticated read in the API: a shared brief, by token.

    Returns the brief and nothing else — no ids, no product list, no case
    links — so a leaked token exposes exactly what its sharer chose to share,
    and revoking it ends that. Unknown and revoked tokens are the same 404.
    """
    from echolens.db.models import ShareLink
    from echolens.exporting import share_brief
    if not (16 <= len(token) <= 64):
        raise HTTPException(404, "this link is not valid")
    with session_scope() as session:
        link = session.scalars(select(ShareLink).where(ShareLink.token == token)).first()
        if link is None or link.revoked_at is not None:
            raise HTTPException(404, "this link is not valid or has been revoked")
        finding = session.get(Finding, link.finding_id)
        if finding is None:
            raise HTTPException(404, "this link is not valid or has been revoked")
        brief = share_brief(session, finding)
        from echolens.db.models import Product
        prod = session.get(Product, finding.product_id) if finding.product_id else None
        return {**brief, "product": prod.name if prod else None,
                "shared_at": aware_utc(link.created_at).isoformat() if link.created_at else None}


@app.get("/calibration")
def calibration_view(product_id: int | None = None, user: dict = Depends(current_user)) -> dict:
    """v5.0 trust page: stated-confidence-vs-approval curve + known weak spots."""
    from echolens.calibration import calibration, weak_spots
    with session_scope() as session:
        p = _scope(session, product_id, user)
        pid = p.id if p else None
        return {**calibration(session, pid), "weak_spots": weak_spots(session, pid),
                "product": p.name if p else None}


@app.post("/findings/{finding_id}/recommend")
@limiter.limit("10/minute")  # each call hits the LLM — cap runaway spend
def recommend_finding(request: Request, finding_id: int, product_id: int | None = None,
                      user: dict = Depends(require_role("reviewer"))) -> dict:
    from echolens.recommender.recommend import recommend
    with session_scope() as session:
        p = _scope(session, product_id, user)
        finding = _owned_finding(session, finding_id, p.id if p else None)
        recs = recommend(session, finding)
        return {"recommendations": [
            {"rank": r.rank, "action": r.action, "impact": r.impact, "effort": r.effort}
            for r in recs]}


# ── v4.0: actionable delivery (tickets, GitHub issues, Slack, alerts) ────

def _metered_llm(session, agent_prefix: str, product_id: int | None = None):
    """An OpenAIClient whose spend is RECORDED.

    These call sites used `on_call=lambda *a: None`, so LLM work done outside an
    investigation (theme discovery, the feedback graph) was invisible to every
    cost report and counted against no budget. investigation_id is None because
    there is no case to attribute it to — but the tokens and dollars are real and
    now appear in the ledger.
    """
    from echolens.llm.openai_client import OpenAIClient

    def _record(agent, model, tokens_in, tokens_out, cost, ms):
        session.add(LLMCall(investigation_id=None, product_id=product_id,
                            agent=f"{agent_prefix}.{agent}",
                            model=model, tokens_in=tokens_in, tokens_out=tokens_out,
                            cost=cost, ms=ms))

    return OpenAIClient(on_call=_record)


def _github_repo(session, product_id: int | None = None) -> str | None:
    """The repo to file a finding's issue into — THIS product's repo.

    This used to return a repo only when exactly one was connected workspace-wide
    and otherwise fall back to GITHUB_DEFAULT_REPO. The moment a second product
    was added, every finding from every product filed into the default repo:
    verified by test, issues for product B landed in product A's tracker (or in
    whatever GITHUB_DEFAULT_REPO named). Scoped requests use only that product's
    sources or the explicitly configured default. Global single-repo inference
    is reserved for unscoped requests.
    """
    from echolens.db.models import CollectorState
    base = select(CollectorState).where(
        CollectorState.source == "github", CollectorState.enabled == True)  # noqa: E712
    if product_id is not None:
        scoped = session.scalars(base.where(CollectorState.product_id == product_id)).all()
        if len(scoped) == 1:
            return scoped[0].identifier
        if len(scoped) > 1:
            return scoped[0].identifier  # deterministic: first configured wins
        return settings.github_default_repo or None
    rows = session.scalars(base).all()
    if len(rows) == 1:
        return rows[0].identifier
    return settings.github_default_repo or None


@app.get("/findings/{finding_id}/issue")
def finding_issue_markdown(finding_id: int, product_id: int | None = None,
                          user: dict = Depends(current_user)) -> dict:
    """Copy-to-clipboard, ticket-ready markdown for a finding."""
    from echolens.exporting import finding_ticket
    from echolens.notify import deep_link
    with session_scope() as session:
        p = _scope(session, product_id, user)
        finding = _owned_finding(session, finding_id, p.id if p else None)
        repo = _github_repo(session, finding.product_id)
        inv = session.get(Investigation, finding.investigation_id)
        ticket = finding_ticket(session, finding, repo=repo,
                                deep_link=deep_link(inv.id) if inv else None)
        return {**ticket, "repo": repo}


@app.post("/findings/{finding_id}/github-issue")
def finding_github_issue(finding_id: int, product_id: int | None = None,
                         user: dict = Depends(require_role("reviewer"))) -> dict:
    """Open a GitHub issue from a finding, evidence chain included."""
    from echolens.exporting import finding_ticket
    from echolens.integrations.github_issue import GitHubIssueError, create_issue
    from echolens.notify import deep_link
    with session_scope() as session:
        p = _scope(session, product_id, user)
        finding = _owned_finding(session, finding_id, p.id if p else None)
        repo = _github_repo(session, p.id if p else finding.product_id)
        if not repo:
            raise HTTPException(422, "No GitHub repo connected. Connect a repo on Sources, or set GITHUB_DEFAULT_REPO.")
        inv = session.get(Investigation, finding.investigation_id)
        ticket = finding_ticket(session, finding, repo=repo,
                                deep_link=deep_link(inv.id) if inv else None)
        try:
            issue = create_issue(repo, ticket["title"], ticket["body"])
        except GitHubIssueError as err:
            # Log the upstream body, return a generic message. GitHubIssueError
            # embeds `resp.text[:200]` verbatim, which was echoed to any viewer.
            log.warning("github_issue_failed", finding_id=finding_id, error=str(err))
            raise HTTPException(422, "could not create the GitHub issue — see server logs")
        from echolens.fixwatch import link_issue
        if issue.get("number"):
            link_issue(session, finding, repo, int(issue["number"]), issue.get("url", ""))
        return {"repo": repo, **issue}


@app.get("/integrations/trackers")
def integrations_trackers(user: dict = Depends(current_user)) -> dict:
    """Which issue trackers this deployment can file to. Booleans only — the
    credentials themselves never leave the server."""
    from echolens.integrations.trackers import TRACKERS, configured_trackers
    configured = configured_trackers()
    labels = {"github": "GitHub", "linear": "Linear", "jira": "Jira"}
    return {"trackers": [{"id": t, "label": labels[t], "configured": configured[t]}
                         for t in TRACKERS]}


@app.post("/findings/{finding_id}/ticket")
def finding_ticket_create(finding_id: int, tracker: str = "github",
                          product_id: int | None = None,
                          user: dict = Depends(require_role("reviewer"))) -> dict:
    """File a finding to GitHub, Linear or Jira. Same ticket body everywhere
    (exporting.finding_ticket); only GitHub issues are linked for fix-watch,
    because the close webhook only exists there."""
    from echolens.exporting import finding_ticket
    from echolens.integrations.trackers import (
        TRACKERS, TrackerError, configured_trackers, create_ticket)
    from echolens.notify import deep_link
    if tracker not in TRACKERS:
        raise HTTPException(422, f"unknown tracker '{tracker}' — use github, linear or jira")
    if not configured_trackers()[tracker]:
        raise HTTPException(422, f"{tracker.capitalize()} is not configured on this deployment.")
    with session_scope() as session:
        p = _scope(session, product_id, user)
        finding = _owned_finding(session, finding_id, p.id if p else None)
        repo = _github_repo(session, p.id if p else finding.product_id)
        if tracker == "github" and not repo:
            raise HTTPException(422, "No GitHub repo connected. Connect a repo on Sources, or set GITHUB_DEFAULT_REPO.")
        inv = session.get(Investigation, finding.investigation_id)
        ticket = finding_ticket(session, finding, repo=repo,
                                deep_link=deep_link(inv.id) if inv else None)
        try:
            issue = create_ticket(tracker, ticket["title"], ticket["body"], repo=repo)
        except TrackerError as err:
            # Upstream bodies can carry account details; log them, return a generic line.
            log.warning("ticket_failed", tracker=tracker, finding_id=finding_id, error=str(err))
            raise HTTPException(422, f"could not create the {tracker} issue — see server logs")
        if tracker == "github" and issue.get("number"):
            from echolens.fixwatch import link_issue
            link_issue(session, finding, repo, int(issue["number"]), issue.get("url", ""))
        return {"tracker": tracker, "repo": repo if tracker == "github" else None, **issue}


@app.post("/findings/{finding_id}/notify")
def finding_notify(finding_id: int, product_id: int | None = None,
                   user: dict = Depends(require_role("reviewer"))) -> dict:
    """Send a finding's alert now (bypasses the severity gate)."""
    from echolens.notify import notify_finding
    with session_scope() as session:
        p = _scope(session, product_id, user)
        finding = _owned_finding(session, finding_id, p.id if p else None)
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
        # No product scope here on purpose: this runs from a Slack button,
        # which has no request context and is workspace-wide by design. The
        # SLACK_ACTION_TOKEN is the authorisation boundary for this path.
        finding = session.get(Finding, finding_id)
        if finding is None:
            raise HTTPException(404, "no such finding")
        # user_id=None was written silently, so a Slack-originated approval left
        # no attributable actor in the audit trail. There is no JWT on this path,
        # so record the channel it came from rather than pretending it was nobody.
        review_mod.approve(session, finding, f"[via Slack] {note}" if note else "[via Slack]")
        result = {"status": "approved", "finding_id": finding.id}
        if settings.auto_create_issue_on_approve:
            result["issue"] = _auto_issue(session, finding)
        return result


def _do_challenge(finding_id: int, note: str) -> int:
    from echolens import review as review_mod
    with session_scope() as session:
        # No product scope here on purpose: this runs from a Slack button,
        # which has no request context and is workspace-wide by design. The
        # SLACK_ACTION_TOKEN is the authorisation boundary for this path.
        finding = session.get(Finding, finding_id)
        if finding is None:
            raise HTTPException(404, "no such finding")
        return review_mod.challenge(session, finding, note).id


def _slack_challenge_bg(finding_id: int, note: str) -> None:
    try:
        _do_challenge(finding_id, note)
    except Exception as err:
        log.error("slack_challenge_failed", finding_id=finding_id, error=str(err))


def _slack_signature_ok(request: Request, body: bytes) -> bool:
    """Verify Slack's v0 request signature (HMAC-SHA256 over
    "v0:{timestamp}:{body}" with the app's signing secret). Requests older
    than five minutes are refused so a captured click cannot be replayed."""
    import hashlib
    import hmac as _hmac
    secret = settings.slack_signing_secret
    if not secret:
        return False
    ts = request.headers.get("x-slack-request-timestamp", "")
    sig = request.headers.get("x-slack-signature", "")
    try:
        if abs(time.time() - int(ts)) > 300:
            return False
    except ValueError:
        return False
    base = f"v0:{ts}:".encode() + body
    expected = "v0=" + _hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
    return _hmac.compare_digest(sig, expected)


@app.post("/integrations/slack/act")
@limiter.limit("30/minute")  # a challenge here runs a FULL investigation
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
    raw_body = await request.body()  # cached by Starlette; form()/json() still work
    slack_signed = is_slack and _slack_signature_ok(request, raw_body)
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
    # compare_digest, not `!=`: a short-circuiting string compare leaks the
    # token a character at a time to anyone who can time the response, and this
    # endpoint carries full reviewer-equivalent power.
    import hmac as _hmac
    if not slack_signed and (not expected or not _hmac.compare_digest(str(token), str(expected))):
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
    repo = _github_repo(session, getattr(finding, "product_id", None))
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
def alerts_digest(hours: int = Query(24, ge=1, le=8760), product_id: int | None = None,
                  user: dict = Depends(require_role("reviewer"))) -> dict:
    """Daily rollup: post one summary of findings drafted in the last `hours` to
    Slack. Used by the scheduled GitHub Action so PMs get a quiet digest.

    Product-scoped. This used to select every Finding in the workspace, so any
    reviewer could blast findings from EVERY product to the single configured
    webhook — cross-product disclosure triggered by a principal who may only be
    meant to see one of them.
    """
    from datetime import timedelta
    from echolens.notify import notify_digest
    with session_scope() as session:
        product = _scope(session, product_id, user)
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        stmt = select(Finding).where(Finding.created_at >= since).order_by(Finding.id.desc())
        if product is not None:
            stmt = stmt.where(Finding.product_id == product.id)
        return notify_digest(session, list(session.scalars(stmt).all()))


# ── v6.0: closed-loop verification (fix watch, patterns, product health) ─

@app.post("/webhooks/github")
async def github_webhook(request: Request) -> dict:
    """GitHub issue events. When a finding's issue CLOSES, start a fix-watch on
    the metric it was meant to fix (verified signature if a secret is set)."""
    raw = await request.body()
    secret = settings.github_webhook_secret
    # Verification is MANDATORY. It used to be wrapped in `if secret:`, and the
    # secret defaults to "" — so out of the box any unauthenticated caller could
    # POST a forged issues/closed event, which starts a fix-watch, writes a
    # fix_date and a baseline_rate, and fabricates "the fix shipped on date D".
    # That then propagates into the brain and patterns as ground truth.
    if not secret:
        raise HTTPException(
            503, "GITHUB_WEBHOOK_SECRET is not configured; refusing unverified webhooks")
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
            try:
                issue_number = int(issue.get("number", 0))
            except (TypeError, ValueError):
                raise HTTPException(400, "issue.number must be an integer")
            # The closing text may say which version carries the fix.
            watch = on_issue_closed(session, repo, issue_number, closed_at,
                                    payload_text=" ".join(str(x) for x in (
                                        issue.get("title"), issue.get("body"),
                                        (payload.get("comment") or {}).get("body")) if x))
            return {"ok": True, "watch_id": watch.id if watch else None,
                    "status": watch.status if watch else "no_matching_finding"}
    return {"ok": True, "ignored": event or "unknown"}


@app.post("/fixwatch/evaluate")
def fixwatch_evaluate(product_id: int | None = None,
                      user: dict = Depends(require_role("reviewer"))) -> dict:
    """Advance every fix-watch: confirm fixes that worked, re-open the ones that
    didn't, and catch regressions. Called by the scheduled job (unprompted)."""
    from echolens.fixwatch import check_regressions, evaluate
    with session_scope() as session:
        prod = _scope(session, product_id, user)
        pid = prod.id if prod else None
        return {"evaluated": evaluate(session, product_id=pid),
                "regressions": check_regressions(session, product_id=pid)}


class FixedVersionBody(BaseModel):
    version: str | None = Field(default=None, max_length=32)   # empty/None clears it


@app.put("/findings/{finding_id}/fixed-version")
def finding_fixed_version(finding_id: int, body: FixedVersionBody, product_id: int | None = None,
                          user: dict = Depends(require_role("reviewer"))) -> dict:
    """Set which app version carries the fix. The post-fix window then opens at
    the first review on that version instead of when the issue closed."""
    from echolens.db.models import FixWatch
    from echolens.fixwatch import set_fixed_version
    with session_scope() as session:
        p = _scope(session, product_id, user)
        finding = _owned_finding(session, finding_id, p.id if p else None)
        watch = session.scalars(select(FixWatch).where(
            FixWatch.finding_id == finding.id).order_by(FixWatch.id.desc())).first()
        if watch is None:
            raise HTTPException(409, "No issue is linked to this finding yet — file one first.")
        try:
            release = set_fixed_version(session, watch, body.version)
        except ValueError:
            raise HTTPException(422, "That doesn't look like a version number (try 3.2.1).")
        return {"status": watch.status, "fixed_in_version": watch.fixed_in_version,
                "release": release}


@app.get("/findings/{finding_id}/reply-drafts")
def finding_reply_drafts(finding_id: int, product_id: int | None = None,
                         user: dict = Depends(current_user)) -> dict:
    """DRAFT replies for the reviewers a resolved finding affected. Nothing is
    posted anywhere; the team copies them into the store console."""
    from echolens.replies import reply_drafts
    with session_scope() as session:
        p = _scope(session, product_id, user)
        finding = _owned_finding(session, finding_id, p.id if p else None)
        inv = session.get(Investigation, finding.investigation_id)
        if inv is None or inv.status != "resolved":
            raise HTTPException(409, "Reply drafts are only available once the case is resolved.")
        return reply_drafts(session, finding)


@app.get("/findings/{finding_id}/followup-questions")
def finding_followup_questions(finding_id: int, product_id: int | None = None,
                               user: dict = Depends(current_user)) -> dict:
    """1-3 questions to ask affected users when a case ended on thin evidence."""
    from echolens.replies import followup_questions
    with session_scope() as session:
        p = _scope(session, product_id, user)
        finding = _owned_finding(session, finding_id, p.id if p else None)
        inv = session.get(Investigation, finding.investigation_id)
        if inv is None or inv.status not in ("insufficient_evidence", "needs_human", "budget_exhausted"):
            return {"finding_id": finding.id, "case_status": inv.status if inv else None,
                    "questions": [], "draft_only": True}
        return followup_questions(session, finding, inv)


@app.get("/fixwatch")
def fixwatch_list(product_id: int | None = None, user: dict = Depends(current_user)) -> dict:
    from echolens.db.models import FixWatch
    from echolens.fixwatch import TERMINAL_FIX_STATUSES
    with session_scope() as session:
        p = _scope(session, product_id, user)
        stmt = select(FixWatch).order_by(FixWatch.id.desc())
        if p is not None:
            stmt = stmt.where(FixWatch.product_id == p.id)
        rows = session.scalars(stmt).all()
        return {"watches": [
            {"id": w.id, "finding_id": w.finding_id, "investigation_id": w.investigation_id,
             "repo": w.repo, "issue_number": w.issue_number, "issue_url": w.issue_url,
             "status": w.status, "metric": w.metric, "baseline_rate": w.baseline_rate,
             "post_rate": w.post_rate,
             # before_after() computes this and _confirm/_inconclusive/_reopen
             # persist it, but nothing served it — so the chart existed in the
             # DB and no caller could reach it. Only sent for terminal statuses,
             # which is the only time it is non-null, so a long watch list does
             # not carry a day-by-day series per row for nothing.
             "chart": w.chart_json if w.status in TERMINAL_FIX_STATUSES else None,
             "fix_date": w.fix_date.isoformat() if w.fix_date else None,
             # The release the fix shipped in, and when reviews on it first
             # appeared — the moment the post-fix window actually opened.
             "fixed_in_version": w.fixed_in_version,
             "release_seen_at": (aware_utc(w.release_seen_at).isoformat()
                                 if w.release_seen_at else None)} for w in rows]}


@app.get("/patterns")
def patterns_view(product_id: int | None = None, user: dict = Depends(current_user)) -> dict:
    """The validated pattern library — (trigger, cause, fix) proven by confirmed fixes."""
    from echolens.patterns import patterns
    with session_scope() as session:
        p = _scope(session, product_id, user)
        return {"patterns": patterns(session, p.id if p else None),
                "product": p.name if p else None}


@app.get("/overview")
def overview(product_id: int | None = None, user: dict = Depends(current_user)) -> dict:
    """Outcome-oriented product-health dashboard (the PM's monthly review)."""
    import statistics as _stats
    from echolens.db.models import FixWatch
    with session_scope() as session:
        prod = _scope(session, product_id, user)
        pid = prod.id if prod else None
        w_stmt = select(FixWatch)
        if pid is not None:
            w_stmt = w_stmt.where(FixWatch.product_id == pid)
        watches = session.scalars(w_stmt).all()
        confirmed = [w for w in watches if w.status == "confirmed"]
        in_verification = [w for w in watches
                           if w.status in ("issue_open", "watching", "waiting_for_release")]
        regressed = [w for w in watches if w.status == "regressed"]
        confirmed_inv = {w.investigation_id for w in confirmed}

        q_start = _quarter_start(datetime.now(timezone.utc))
        confirmed_q = [w for w in confirmed if w.confirmed_at and aware_utc(w.confirmed_at) >= q_start]

        mttrs = []
        watch_inv_ids = {w.investigation_id for w in confirmed}
        watch_invs = ({inv.id: inv for inv in session.scalars(select(Investigation).where(
            Investigation.id.in_(watch_inv_ids))).all()} if watch_inv_ids else {})
        for w in confirmed:
            inv = watch_invs.get(w.investigation_id)
            if inv and inv.created_at and w.confirmed_at:
                mttrs.append((aware_utc(w.confirmed_at) - aware_utc(inv.created_at)).days)
        mttr = round(_stats.mean(mttrs), 1) if mttrs else None

        # open problems = resolved cases not yet confirmed-fixed, ranked by impact
        open_problems = []
        op_stmt = select(Investigation).where(Investigation.status == "resolved")
        if pid is not None:
            op_stmt = op_stmt.where(Investigation.product_id == pid)
        open_invs = session.scalars(op_stmt).all()
        open_findings = _latest_findings(session, [inv.id for inv in open_invs])
        from echolens.review import decision_hides, latest_decisions
        decisions = latest_decisions(session, [f.id for f in open_findings.values()])
        for inv in open_invs:
            if inv.id in confirmed_inv:
                continue
            finding = open_findings.get(inv.id)
            if finding is None:
                continue
            # v15: parked (until its date) and won't-fix are decided, not open.
            if decision_hides(decisions.get(finding.id)):
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
    force_investigate: bool = False


def _chat_ask_llm(session, user: dict, message: str, pid, pname, on_step=None):
    """The LLM agent answer, or None when this caller may not spend / it fails.
    Separate so tests can swap in a scripted model without an API key."""
    from echolens import ask as ask_mod
    if not (_may_spend(user) and settings.openai_api_key
            and ask_mod.has_anything_to_say(session, pid)):
        return None
    llm = _metered_llm(session, "ask", pid)
    return ask_mod.answer(session, message, llm, product_id=pid, product_name=pname,
                          on_step=on_step)


def _chat_next_step(resp: dict, user: dict, message: str) -> dict | None:
    """The inline "Start an investigation into …" card for an answer that is not
    backed by a verified case — so Ask never ends at a dead end. Viewers and
    guests get the card too, with the reason they cannot use it."""
    if resp.get("type") != "answer" or not message.strip():
        return None
    basis = resp.get("basis") or {}
    if basis.get("kind") == "investigation" and resp.get("confident", True) is not False:
        return None
    reason = None
    allowed = user.get("role") in ("reviewer", "admin") and not user.get("guest")
    if user.get("guest"):
        reason = ("Guests can browse the demo but can't start investigations. "
                  "Sign in with a reviewer account to open one.")
    elif not allowed:
        reason = "Starting an investigation needs reviewer access. Ask an admin to upgrade your role."
    signals = resp.get("signals") or []
    if basis.get("kind") == "signals" and signals:
        lead = signals[0]
        return {"kind": "investigate", "question": lead["title"], "slug": lead["slug"],
                "allowed": allowed, "reason": reason}
    from echolens.chat import RANK_MARKERS
    if any(marker in message.lower() for marker in RANK_MARKERS):
        return None  # A ranking question is not a topic to investigate.
    return {"kind": "investigate", "question": message.strip()[:300],
            "allowed": allowed, "reason": reason}


def _chat_finish(resp: dict, user: dict, message: str) -> dict:
    """Attach provenance (`basis`) and the next-step card to a chat response."""
    from echolens import chat as chat_mod
    if resp.get("type") == "answer" and not resp.get("basis"):
        resp["basis"] = chat_mod.basis_for_citations(resp.get("citations")) or chat_mod.basis_none()
    resp["next_step"] = _chat_next_step(resp, user, message)
    return resp


def _chat_respond(body: "ChatBody", user: dict, on_step=None) -> dict:
    """One Ask turn. Shared by POST /chat and POST /chat/stream so the two can
    never disagree on scoping, guest no-spend or the reviewer-only launch.
    `on_step` receives progress dicts ({"kind", "text", ...}) as they happen."""
    from echolens import ask as ask_mod
    from echolens import chat as chat_mod

    def emit(kind: str, text: str, **extra) -> None:
        if on_step is not None:
            on_step({"kind": kind, "text": text, **extra})

    message = body.message or ""
    with session_scope() as session:
        prod = _scope(session, body.product_id, user)
        pid = prod.id if prod else None
        pname = prod.name if prod else None
        if body.force_investigate and message.strip():
            # The "Start an investigation" card. Previously this flag was only
            # read when the router had ALREADY chosen to launch, so pressing
            # "Investigate this properly" on a topic question re-answered it.
            decision = {"type": "launch", "description": message.strip()}
        else:
            emit("route", "Checking what EchoLens has already verified…")
            decision = chat_mod.route(session, message, product_id=pid, product_name=pname)

        existing = None
        if decision.get("type") == "launch" and not body.force_investigate:
            existing = ask_mod.best_existing_answer(session, message, product_id=pid)
            if existing is not None:
                f, inv = existing
                emit("route", f"Already investigated — case #{inv.id}.")
                decision = {"type": "answer", "citations": [chat_mod._cite(f, inv)],
                            "basis": chat_mod.basis_investigation(inv.id),
                            "text": f"{f.summary} — case #{inv.id}. This was already "
                                    "investigated; start a new one if it's back."}

        if decision.get("type") != "launch":
            # A deterministic answer that already cites cases (or is built from
            # the product's own signals) is the honest answer and costs nothing;
            # only open questions go to the model.
            if decision.get("citations") or decision.get("grounded"):
                decision.pop("grounded", None)
                return _chat_finish(decision, user, message)
            try:
                result = _chat_ask_llm(session, user, message, pid, pname, on_step)
                if result is not None and result.text and (
                        result.citations or result.tool_calls or result.confident):
                    if result.citations:
                        basis = chat_mod.basis_for_citations(result.citations)
                    elif result.tool_calls:
                        basis = chat_mod.basis_raw_search()
                    else:
                        basis = chat_mod.basis_none(chat_mod.NONE_CAUTION)
                    return _chat_finish({"type": "answer", "text": result.text,
                                         "citations": result.citations,
                                         "tool_calls": result.tool_calls,
                                         "confident": result.confident,
                                         "can_investigate": True,
                                         "basis": basis}, user, message)
            except Exception as err:
                log.warning("ask_agent_failed", error=f"{type(err).__name__}: {err}")
            return _chat_finish(decision, user, message)
        if user.get("role") not in ("reviewer", "admin") or user.get("guest"):
            return _chat_finish({"type": "answer", "citations": [],
                                 "basis": chat_mod.basis_none(),
                                 "text": "I can look into that, but opening an investigation "
                                         "needs reviewer access."}, user, message)
        emit("launch", "Opening an investigation…")
        # The slug is UNIQUE, so two launches close together (a double-click on
        # the card) must not share one. time_ns alone was not enough: Windows'
        # clock ticks every 15.6 ms, so both calls read the same value.
        anomaly = AnomalyEvent(slug=_unique_slug("chat"), type="manual", metric="chat question",
                               delta=0.0, z=0.0, window="n/a",
                               description=decision["description"], status="pending", product_id=pid)
        session.add(anomaly)
        session.flush()
        inv = Investigation(anomaly_id=anomaly.id, status="running", opened_by="manual",
                            budget_tier="standard", budget_json={}, data_notes=_data_notes(session, pid),
                            product_id=pid)
        session.add(inv)
        anomaly.status = "investigating"
        session.flush()
        inv_id = inv.id
    threading.Thread(target=_run_investigation_bg, args=(inv_id, "standard"), daemon=True).start()
    return _chat_finish({
        "type": "investigation", "investigation_id": inv_id,
        "basis": {"kind": "investigation_started", "case_id": inv_id,
                  "label": f"Investigation started (case #{inv_id})", "caution": None},
        "text": f"Opening an investigation into that — case #{inv_id}. It's streaming now."},
        user, message)


@app.post("/chat")
# One Ask budget per client across /chat AND /chat/stream: two separate
# 20/minute limits let one client take 40 LLM-spending turns a minute by
# alternating routes. shared_limit counts both against the same "ask" scope.
@limiter.shared_limit("20/minute", scope="ask")
def chat_endpoint(body: ChatBody, request: Request,
                  user: dict = Depends(current_user)) -> dict:
    """Ask the verified knowledge anything. Returns a finding-cited answer, or —
    for an investigate-intent question — launches a case that streams in-thread.
    Every answer carries `basis` (where it came from) and, when it is not backed
    by a verified case, a `next_step` offering to investigate."""
    return _chat_respond(body, user)


# A streamed Ask turn must end. ask.py caps the agent at MAX_STEPS model calls,
# but a hung provider call has no ceiling of its own.
CHAT_STREAM_MAX_SECONDS = 120


@app.post("/chat/stream")
@limiter.shared_limit("20/minute", scope="ask")  # the SAME budget as /chat, not a second one
async def chat_stream(body: ChatBody, request: Request,
                      user: dict = Depends(current_user)) -> StreamingResponse:
    """POST /chat, streamed as server-sent events so the UI can show what Ask is
    doing ("Searching reviews for 'paywall'…") instead of a bare spinner.

    Events: `step` {kind, text, tool?, why?} as they happen, then exactly one
    `answer` (the same body POST /chat returns) or `error`, then `done`.

    Auth is the normal header dependency. The trace stream authenticates by
    hand only because EventSource cannot send headers; this is read with
    fetch(), which can, so the token never has to ride in a URL. Guest scoping
    and no-spend rules are identical because both routes run _chat_respond.
    """
    import queue as queue_mod

    # Resolve the scope up front so a bad product id is a real 404, not an
    # error event inside a 200 stream.
    with session_scope() as session:
        _scope(session, body.product_id, user)

    q: queue_mod.Queue = queue_mod.Queue()

    def work() -> None:
        try:
            q.put(("answer", _chat_respond(body, user, on_step=lambda s: q.put(("step", s)))))
        except HTTPException as err:
            q.put(("error", {"error": str(err.detail), "status": err.status_code}))
        except Exception as err:
            log.warning("chat_stream_failed", error=f"{type(err).__name__}: {err}")
            q.put(("error", {"error": "Ask failed — try again."}))

    def take():
        try:
            return q.get(timeout=0.5)
        except queue_mod.Empty:
            return None

    threading.Thread(target=work, name="echolens-chat-stream", daemon=True).start()

    async def gen():
        started = time.monotonic()
        while True:
            if await request.is_disconnected():
                return
            if time.monotonic() - started > CHAT_STREAM_MAX_SECONDS:
                yield _sse("error", {"error": "Ask took too long — try again."})
                yield _sse("done", {})
                return
            item = await run_in_threadpool(take)
            if item is None:
                continue
            event, payload = item
            yield _sse(event, payload)
            if event in ("answer", "error"):
                yield _sse("done", {})
                return
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class FollowupBody(BaseModel):
    question: str


@app.post("/findings/{finding_id}/followup")
@limiter.limit("20/minute")  # each follow-up is an LLM call
def finding_followup(finding_id: int, body: FollowupBody, request: Request,
                     product_id: int | None = None,
                     user: dict = Depends(require_role("reviewer"))) -> dict:
    """Targeted follow-up on a finding (e.g. 'does this affect iOS too?') appended
    as an addendum — no full re-investigation."""
    from echolens.chat import followup
    with session_scope() as session:
        p = _scope(session, product_id, user)
        finding = _owned_finding(session, finding_id, p.id if p else None)
        return followup(session, finding, body.question)


@app.get("/brief")
def brief_view(product_id: int | None = None, user: dict = Depends(current_user)) -> dict:
    """Preview the weekly brief (also what the scheduled send composes)."""
    from echolens.brief import weekly_brief
    with session_scope() as session:
        p = _scope(session, product_id, user)
        return {**weekly_brief(session, product_id=(p.id if p else None)),
                "product": p.name if p else None}


@app.post("/brief/send")
def brief_send(user: dict = Depends(require_role("reviewer"))) -> dict:
    """Compose and deliver the weekly brief to Slack/email (scheduled, unprompted)."""
    from echolens.brief import weekly_brief
    from echolens.db.models import Product
    from echolens.notify import _send_email, _send_slack, deep_link
    with session_scope() as session:
        # v9.0: own more than one product and this becomes ONE ranked email
        # across all of them, not a per-product blast.
        n_products = len(session.scalars(select(Product)).all())
        if n_products > 1:
            from echolens.portfolio import portfolio_brief
            b = portfolio_brief(session)
        else:
            b = weekly_brief(session)

    def _linkify(text: str) -> str:
        import re
        def repl(m):
            cid = m.group(1)
            link = deep_link(int(cid))
            return f"<{link}|case #{cid}>" if link else f"case #{cid}"
        return re.sub(r"case #(\d+)", repl, text)

    title = ("EchoLens portfolio brief" if n_products > 1 else "EchoLens weekly brief")
    body_md = "\n".join(_linkify(line) for line in b["lines"])
    payload = {"blocks": [
        {"type": "header", "text": {"type": "plain_text", "text": f"{title} · {b['generated']}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": body_md}},
    ]}
    slack = _send_slack(payload)
    email = _send_email(f"{title} · {b['generated']}", "\n".join(b["lines"]))
    return {"sent": {"slack": slack, "email": email}, "brief": b}


# ── v9.0 portfolio: one brain across every product ──────────────────────

@app.get("/portfolio")
def portfolio_view(user: dict = Depends(current_user)) -> dict:
    """Ranked cross-product attention board. Deliberately NOT product-scoped —
    this is the screen you open before you know which product to open."""
    from echolens.portfolio import portfolio, transfer_stats
    with session_scope() as session:
        demo_only = _guest_locked(user)
        return {**portfolio(session, demo_only=demo_only),
                # Cross-product transfer learning compares real products, so it
                # is withheld from a demo visitor rather than filtered to one.
                "transfer": None if demo_only else transfer_stats(session)}


@app.get("/portfolio/brief")
def portfolio_brief_view(user: dict = Depends(current_user)) -> dict:
    """The weekly brief for everything you own, ranked globally by impact."""
    from echolens.portfolio import portfolio_brief
    with session_scope() as session:
        return portfolio_brief(session, demo_only=_guest_locked(user))


@app.get("/portfolio/themes")
def portfolio_themes(days: int = Query(30, ge=1, le=365),
                     limit: int = Query(8, ge=1, le=50),
                     user: dict = Depends(current_user)) -> dict:
    """The same complaint theme measured across every product on one axis.

    Rates are shares of each product's own negative reviews, so a big app and a
    small one are genuinely comparable.
    """
    from echolens.db.models import Product
    from echolens.vocab import FAMILIES, canonical_theme, compare_theme, negative_corpus
    with session_scope() as session:
        products = _visible_products(session, user)
        names = [p.name for p in products]
        if not names:
            return {"themes": [], "products": [], "days": days}

        # themes actually seen on this portfolio's findings, then the shared
        # families they map onto — emergent first, vocabulary second
        seen: dict[str, dict] = {}
        product_ids = [p.id for p in products]
        rows = session.execute(select(Finding, AnomalyEvent).join(
            Investigation, Investigation.id == Finding.investigation_id).join(
            AnomalyEvent, AnomalyEvent.id == Investigation.anomaly_id).where(
            Investigation.product_id.in_(product_ids))).all()
        for f, anomaly in rows:
            from echolens.vocab import theme_of
            t = theme_of(anomaly, f.json or {})
            if t["id"] != "other":
                seen.setdefault(t["id"], t)
        for fid in list(FAMILIES)[:6]:      # always show the common families too
            seen.setdefault(fid, canonical_theme([fid.replace("-", " ")]))

        # Every product's negative reviews read once, not per theme per product.
        corpus = negative_corpus(session, names, days)
        rows = []
        for t in list(seen.values())[:limit]:
            per = compare_theme(session, t, names, days, corpus=corpus)
            if not any(r["rate_pct"] > 0 for r in per):
                continue
            rows.append({"theme_id": t["id"], "label": t["label"],
                         "is_family": t["is_family"], "products": per,
                         "worst": per[0]["product"] if per else None})
        rows.sort(key=lambda r: -(r["products"][0]["rate_pct"] if r["products"] else 0))
        return {"themes": rows, "products": names, "days": days,
                "note": "Rate = share of that product's negative reviews mentioning the theme."}


@app.get("/portfolio/transfers")
def portfolio_transfers(user: dict = Depends(current_user)) -> dict:
    """Cases that started from another product's verified fix, and whether the
    shortcut is measurable."""
    from echolens.portfolio import recent_transfers, transfer_stats
    with session_scope() as session:
        # Transfers are inherently cross-product: every row names a real
        # product a demo visitor must not see.
        if _guest_locked(user):
            return {"transfers": [], "stats": None}
        return {"transfers": recent_transfers(session), "stats": transfer_stats(session)}


@app.get("/themes")
def themes_view(product_id: int | None = None, user: dict = Depends(current_user)) -> dict:
    """Theme lifecycle: emergence → peak → resolved / chronic (>60d unresolved)."""
    from echolens.themes import theme_lifecycle
    with session_scope() as session:
        p = _scope(session, product_id, user)
        return {"themes": theme_lifecycle(session, product_id=(p.id if p else None)),
                "product": p.name if p else None}


@app.get("/costs")
def costs(product_id: int | None = None, user: dict = Depends(current_user)) -> dict:
    with session_scope() as session:
        p = _scope(session, product_id, user)
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

MAX_UPLOAD_BYTES = 25 * 1024 * 1024   # 25 MB is a very large review export

_HUMAN_BY_STATUS = {"resolved": "Approved"}


def _today() -> date:
    """Real 'today' for spend/volume-per-day counters — investigations and
    llm_calls are timestamped at real wall-clock time, so this must be now."""
    return datetime.now(timezone.utc).date()


def _limits(session, product_id: int | None = None) -> dict:
    """Effective budget limits: per-product overrides > workspace overrides >
    config defaults (v8.0 — each product keeps its own budgets)."""
    from echolens.orchestrator.queue import effective_limits
    return effective_limits(session, product_id)


def _daily_limit(session, product_id: int | None = None) -> int:
    return int(_limits(session, product_id)["daily_investigations"])


def _money(x: float) -> str:
    """Costs are fractions of a cent per call — show enough precision to be real
    (a $0.0031 case must not display as $0.00)."""
    x = float(x or 0)
    return f"${x:.4f}" if 0 < x < 1 else f"${x:.2f}"


def _cost_by_investigation(session, product_id: int | None = None) -> dict[int, dict]:
    """Per-case cost, aggregated in SQL and scoped to one product.

    This pulled EVERY row of llm_calls and EVERY investigation into Python on
    each call — unbounded, unscoped, and /costs/summary invoked it alongside
    _product_llm_calls so the full history was loaded twice per request.
    """
    from sqlalchemy import func as _func

    inv_stmt = select(Investigation)
    if product_id is not None:
        inv_stmt = inv_stmt.where(Investigation.product_id == product_id)
    investigations = list(session.scalars(inv_stmt).all())
    inv_ids = [i.id for i in investigations]

    agg: dict[int, dict] = {}
    if inv_ids:
        totals = session.execute(
            select(LLMCall.investigation_id,
                   _func.sum(LLMCall.cost),
                   _func.sum(LLMCall.tokens_in + LLMCall.tokens_out))
            .where(LLMCall.investigation_id.in_(inv_ids))
            .group_by(LLMCall.investigation_id)
        ).all()
        for inv_id, cost, tokens in totals:
            agg[inv_id] = {"cost": float(cost or 0.0), "tokens": int(tokens or 0), "queries": 0}
    for inv in investigations:
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


def _product_llm_calls(session, product_id: int | None, since: datetime | None = None):
    """LLM calls for a product: through their investigation, or tagged directly
    (chat, triage, themes, graph — spend that has no case). `since` bounds the
    scan in SQL instead of loading the whole ledger into Python."""
    from sqlalchemy import or_
    stmt = select(LLMCall)
    if product_id is not None:
        stmt = stmt.outerjoin(Investigation, Investigation.id == LLMCall.investigation_id).where(
            or_(Investigation.product_id == product_id, LLMCall.product_id == product_id))
    if since is not None:
        stmt = stmt.where(LLMCall.created_at >= since)
    return session.scalars(stmt).all()


def _latest_findings(session, investigation_ids: list[int]) -> dict[int, Finding]:
    out: dict[int, Finding] = {}
    if not investigation_ids:
        return out
    for row in session.scalars(select(Finding).where(
            Finding.investigation_id.in_(investigation_ids)).order_by(Finding.id)).all():
        out[row.investigation_id] = row
    return out


@app.get("/feed/summary")
def feed_summary(product_id: int | None = None, user: dict = Depends(current_user)) -> dict:
    with session_scope() as session:
        p = _scope(session, product_id, user)
        pid = p.id if p else None
        today = _today()
        invs = _product_investigations(session, pid)
        n_today = [i for i in invs if i.created_at and i.created_at.date() == today]
        day_start = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)
        spent = sum(c.cost for c in _product_llm_calls(session, pid, since=day_start)
                    if c.created_at and c.created_at.date() == today)
        return {"investigations_today": len(n_today),
                "daily_limit": _daily_limit(session, pid),
                "spent_today": round(spent, 4),
                "product": p.name if p else None}


@app.get("/archive")
def archive(product_id: int | None = None, user: dict = Depends(current_user)) -> dict:
    with session_scope() as session:
        p = _scope(session, product_id, user)
        pid = p.id if p else None
        costs = _cost_by_investigation(session, pid)
        rows = []
        resolved_approved = 0
        stmt = select(Investigation).order_by(Investigation.id.desc())
        if pid is not None:
            stmt = stmt.where(Investigation.product_id == pid)
        inv_rows = [inv for inv in session.scalars(stmt).all() if inv.status != "running"]
        findings = _latest_findings(session, [inv.id for inv in inv_rows])
        feedback: dict[int, ReviewFeedback] = {}
        if inv_rows:
            for fb, inv_id in session.execute(select(
                    ReviewFeedback, Finding.investigation_id).join(
                    Finding, Finding.id == ReviewFeedback.finding_id).where(
                    Finding.investigation_id.in_([inv.id for inv in inv_rows]),
                    # whole-finding verdicts only; partial challenges (v15) are not
                    # an approve/challenge and must not relabel the row
                    ReviewFeedback.action.in_(("approve", "challenge"))).order_by(
                    ReviewFeedback.id)).all():
                feedback[inv_id] = fb
        for inv in inv_rows:
            finding = findings.get(inv.id)
            fb = feedback.get(inv.id)
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
def sources(product_id: int | None = None, user: dict = Depends(current_user)) -> dict:
    from echolens.collectors.registry import source_health
    from echolens.db.models import CollectorState
    with session_scope() as session:
        prod = _scope(session, product_id, user)
        s_stmt = select(CollectorState)
        if prod is not None:
            s_stmt = s_stmt.where(CollectorState.product_id == prod.id)
        states = session.scalars(s_stmt).all()
        health = {(h["source"], h["identifier"]): h for h in source_health(
            session, product=(prod.name if prod else None))}
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
        csv_stmt = select(func.count(Review.id)).where(Review.ext_id.like("csv_%"))
        if prod is not None:
            csv_stmt = csv_stmt.where(Review.product == prod.name)
        n_csv = session.scalar(csv_stmt) or 0
        if n_csv:
            connected.append({
                "icon": _SOURCE_META["csv"]["icon"], "name": _SOURCE_META["csv"]["label"],
                "detail": "uploaded exports", "status": "Healthy", "stale": False, "staleSince": None,
                "lastPull": "imported", "volume": f"{n_csv:,} items", "error": None})
        # If nothing is configured, show the built-in demo corpus so the page
        # is never blank (it's still real counts).
        if not connected:
            review_stmt = select(func.count(Review.id))
            issue_stmt = select(func.count(Issue.id))
            release_stmt = select(func.count(Release.id))
            if prod is not None:
                review_stmt = review_stmt.where(Review.product == prod.name)
                issue_stmt = issue_stmt.where(Issue.product == prod.name)
                release_stmt = release_stmt.where(Release.product == prod.name)
            n_reviews = session.scalar(review_stmt) or 0
            n_issues = session.scalar(issue_stmt) or 0
            n_releases = session.scalar(release_stmt) or 0
            if n_reviews or n_issues:
                connected = [
                    {"icon": "▶", "name": "Google Play reviews (demo)", "detail": "synthetic Lumo dataset",
                     "status": "Healthy", "lastPull": "seeded", "volume": f"{n_reviews:,} items"},
                    {"icon": "⌥", "name": "GitHub issues (demo)", "detail": "synthetic Lumo dataset",
                     "status": "Healthy", "lastPull": "seeded", "volume": f"{n_issues + n_releases} items"},
                ]
        from echolens.overview import freshness
        return {"connected": connected, "product": prod.name if prod else None,
                "last_synced": freshness(session, prod),
                "available": ["Zendesk export", "Discord community", "In-app feedback"]}


@app.get("/costs/summary")
def costs_summary(product_id: int | None = None, user: dict = Depends(current_user)) -> dict:
    with session_scope() as session:
        p = _scope(session, product_id, user)
        pid = p.id if p else None
        month_floor = datetime.combine(_today().replace(day=1), datetime.min.time(), tzinfo=timezone.utc)
        calls = _product_llm_calls(session, pid, since=month_floor)
        invs = _product_investigations(session, pid)
        costs = _cost_by_investigation(session, pid)
        resolved = [i for i in invs if i.status == "resolved"]
        dead = [i for i in invs if i.status in ("insufficient_evidence", "budget_exhausted")]
        today = _today()
        month_start = today.replace(day=1)
        dated_costs = [(aware_utc(c.created_at).astimezone(timezone.utc).date(), c.cost)
                       for c in calls if c.created_at]
        spent_today = sum(cost for day, cost in dated_costs if day == today)
        month_to_date = round(sum(cost for day, cost in dated_costs
                                  if month_start <= day <= today), 4)
        avg_resolved = (round(sum(costs.get(i.id, {}).get("cost", 0) for i in resolved) / len(resolved), 4)
                        if resolved else 0.0)
        dead_spend = round(sum(costs.get(i.id, {}).get("cost", 0) for i in dead), 4)
        rows = []
        row_stmt = select(Investigation).order_by(Investigation.id.desc())
        if pid is not None:
            row_stmt = row_stmt.where(Investigation.product_id == pid)
        row_invs = session.scalars(row_stmt).all()
        row_findings = _latest_findings(session, [inv.id for inv in row_invs])
        for inv in row_invs:
            finding = row_findings.get(inv.id)
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
            "month_to_date": month_to_date,
            "budget": float(_limits(session, pid)["monthly_budget"]),
            "product": p.name if p else None,
            "limits": _limits(session, pid),
            "rows": rows,
        }


class LimitsBody(BaseModel):
    daily_investigations: int | None = Field(None, ge=1, le=100)
    per_case_budget: float | None = Field(None, ge=0.01, le=1000)
    per_case_wall_min: int | None = Field(None, ge=1, le=1440)
    daily_cost_budget: float | None = Field(None, ge=0, le=10000)
    monthly_budget: float | None = Field(None, ge=0, le=100000)


@app.put("/settings/limits")
def set_limits(body: LimitsBody, product_id: int | None = None,
               user: dict = Depends(require_role("admin"))) -> dict:
    """Adjust budget limits (admin), for ONE product or for the workspace.

    With a product_id this writes that product's override, which is what
    _limits() reads back first. Without one it writes the workspace default.

    The two must match or the screen lies: Settings READ through
    /costs/summary, which is product-scoped and layers the per-product override
    on top, but WROTE here unscoped — so on any product carrying an override the
    save landed in a row the read ignored. The admin got a green "Limit saved."
    toast and the number silently reverted to the old value.
    """
    from echolens.db.models import Product
    with session_scope() as session:
        prod = _scope(session, product_id, user) if product_id is not None else None
        # Merge onto the EFFECTIVE limits for this scope, so a partial body
        # (one field) does not blank the others.
        current = _limits(session, prod.id if prod else None)
        for k in ("daily_investigations", "per_case_budget", "per_case_wall_min",
                  "daily_cost_budget", "monthly_budget"):
            v = getattr(body, k)
            if v is not None:
                current[k] = v
        if prod is not None:
            prod.limits_json = dict(current)
        else:
            row = session.get(Setting, "limits")
            if row is None:
                row = Setting(key="limits", value={})
                session.add(row)
            row.value = current
        session.flush()
        return current
