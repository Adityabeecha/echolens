"""v6.0 tests: closed-loop verification. One test per exit criterion —
unprompted fix confirmation + before/after chart, regression caught with prior
context, and the pattern library shortcutting an investigation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from echolens.db.models import (
    AnomalyEvent, Base, Finding, FixWatch, Investigation, Recommendation, Review, TraceStep)
from echolens.eval.harness import ScriptedLLM
from echolens.fixwatch import check_regressions, evaluate, link_issue, on_issue_closed
from echolens.patterns import matching_pattern, patterns

TZ = timezone.utc


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _finding(s, summary, metric=None):
    anomaly = AnomalyEvent(slug=f"a-{summary[:10]}-{id(summary) % 9999}", type="theme_volume_surge",
                           metric=metric or summary, delta=0.2, z=2.5, window="7d",
                           description=summary, status="closed")
    s.add(anomaly); s.flush()
    inv = Investigation(anomaly_id=anomaly.id, status="resolved", opened_by="anomaly",
                        budget_tier="quick", budget_json={},
                        created_at=datetime.now(TZ) - timedelta(days=3))
    s.add(inv); s.flush()
    f = Finding(investigation_id=inv.id, summary=summary, confidence=0.85, status="approved",
                json={"summary": summary, "confidence": 0.85})
    s.add(f); s.flush()
    s.add(Recommendation(finding_id=f.id, action=f"fix for {summary}", rank=1, impact="HIGH", effort="MED"))
    s.flush()
    return anomaly, inv, f


def _neg(s, text, when, n=1):
    for i in range(n):
        s.add(Review(source="play_store", ext_id=f"r_{text[:4]}_{when.date()}_{i}_{id(when) % 999}",
                     rating=1, text=text, created_at=when))


# ── exit #1: a fix ships, resolution detected unprompted + before/after ──

def test_fix_confirmed_unprompted_with_before_after():
    s = _session()
    fix = datetime(2026, 6, 1, tzinfo=TZ)
    for d in range(-14, 0):  # pre-fix: heavy battery complaints
        _neg(s, "battery drain terrible since update", fix + timedelta(days=d), n=4)
    for d in range(0, 15):   # post-fix: complaints gone (positive reviews)
        s.add(Review(source="play_store", ext_id=f"ok_{d}", rating=5, text="great app, love it",
                     created_at=fix + timedelta(days=d)))
    _, inv, f = _finding(s, "battery drain from the v3.2 sync")
    s.commit()

    link_issue(s, f, "acme/app", 101, "https://github.com/acme/app/issues/101")
    on_issue_closed(s, "acme/app", 101, fix)          # webhook fires
    results = evaluate(s)                              # scheduled job, unprompted

    watch = s.scalars(select(FixWatch)).first()
    assert watch.status == "confirmed"
    assert results and results[0]["status"] == "confirmed"
    chart = watch.chart_json
    assert chart and chart["before"] and chart["after"]
    before_total = sum(p["count"] for p in chart["before"])
    after_total = sum(p["count"] for p in chart["after"])
    assert before_total > 0 and after_total == 0        # the fix visibly worked


# ── exit #2: regression caught, investigation starts from prior context ──

def test_regression_detected_and_starts_from_prior_context():
    s = _session()
    fix = datetime(2026, 6, 1, tzinfo=TZ)
    for d in range(-14, 0):
        _neg(s, "battery drain terrible", fix + timedelta(days=d), n=4)
    for d in range(0, 14):
        s.add(Review(source="play_store", ext_id=f"ok_{d}", rating=5, text="great app", created_at=fix + timedelta(days=d)))
    for d in range(20, 28):  # LATER re-spike of the same theme
        _neg(s, "battery drain terrible again", fix + timedelta(days=d), n=4)
    _, inv, f = _finding(s, "battery drain from the sync")
    s.commit()

    link_issue(s, f, "acme/app", 202)
    on_issue_closed(s, "acme/app", 202, fix)
    evaluate(s)  # confirms first (post-fix window was clean)
    regressions = check_regressions(s)

    assert regressions, "a regression should be detected"
    reg = s.scalars(select(AnomalyEvent).where(AnomalyEvent.type == "regression")).first()
    assert reg is not None and reg.parent_case_id == inv.id  # linked to the original case

    # investigating the regression visibly starts from prior context
    from echolens.investigator.graph import Investigator
    responses = [
        {"thought": "prior", "action": "revise_hypotheses",
         "hypotheses": [{"id": "H1", "statement": "regression of the sync bug", "confidence": 0.4, "status": "active"}]},
        {"thought": "thin", "action": "conclude", "conclusion": {"status": "insufficient_evidence", "reason": "x"}},
        {"summary": "insufficient", "prose": "checked posts", "confidence": 0.4,
         "supported_hypothesis": None, "checked": ["play_store"], "what_would_settle_it": "more"},
    ]
    reg_inv = Investigator(s, reg, llm=ScriptedLLM(responses)).run()
    texts = [t.content_json.get("text", "") for t in s.scalars(
        select(TraceStep).where(TraceStep.investigation_id == reg_inv.id)).all()]
    assert any(f"Follow-up on case #{inv.id}" in t for t in texts)


# ── exit #3: pattern library ≥3 verified + an investigation shortcuts ────

def _confirmed(s, summary, num):
    _, inv, f = _finding(s, summary)
    from echolens.impact import theme_terms
    anomaly = s.get(AnomalyEvent, inv.anomaly_id)
    s.add(FixWatch(finding_id=f.id, investigation_id=inv.id, repo="r/r", issue_number=num,
                   status="confirmed", terms=theme_terms(anomaly, f.json), metric=summary,
                   baseline_rate=5.0, post_rate=0.0, confirmed_at=datetime.now(TZ)))
    s.flush()
    return inv


def test_pattern_library_and_shortcut():
    s = _session()
    _confirmed(s, "battery drain from background sync", 1)
    _confirmed(s, "crash on export of large albums", 2)
    _confirmed(s, "shipping cost complaints after pricing change", 3)
    s.commit()

    lib = patterns(s)
    assert len(lib) >= 3
    assert all(p["verified_count"] >= 1 and p["fix"] for p in lib)

    # a NEW anomaly on a known theme finds the validated pattern
    new = AnomalyEvent(slug="new-battery", type="theme_volume_surge", metric="battery drain share",
                       delta=0.2, z=2.6, window="7d", description="battery drain complaints rising", status="pending")
    s.add(new); s.flush()
    pat = matching_pattern(s, new)
    assert pat is not None and "battery" in " ".join(pat["terms"])

    # and the investigator visibly shortcuts on it
    from echolens.investigator.graph import Investigator
    responses = [
        {"thought": "start from the proven prior", "action": "conclude",
         "conclusion": {"status": "insufficient_evidence", "reason": "demo"}},
        {"summary": "x", "prose": "checked", "confidence": 0.3, "supported_hypothesis": None,
         "checked": ["play_store"], "what_would_settle_it": "y"},
    ]
    inv = Investigator(s, new, llm=ScriptedLLM(responses)).run()
    texts = [t.content_json.get("text", "") for t in s.scalars(
        select(TraceStep).where(TraceStep.investigation_id == inv.id)).all()]
    assert any("matches a pattern verified" in t for t in texts)
