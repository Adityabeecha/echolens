"""The demo seed tells a whole story: real cases with traces, two verified
fixes, reviewer verdicts and product decisions — deterministically, no LLM."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from echolens.db.models import (
    AnomalyEvent, Base, CollectorState, EvidenceRow, Finding, FindingDecision, FixWatch,
    HypothesisRow, Investigation, Product, Review, ReviewFeedback, TraceStep)
from echolens.synthetic.demo_story import seed_demo, seed_demo_story


def _session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, expire_on_commit=False)()


@pytest.fixture()
def no_live_llm(monkeypatch):
    import echolens.llm.openai_client as oc

    class Refuse:
        def __init__(self, *a, **k):
            raise AssertionError("the demo seed must never build a live LLM client")

    monkeypatch.setattr(oc, "OpenAIClient", Refuse)


@pytest.fixture()
def seeded(no_live_llm):
    s = _session()
    counts = seed_demo(s)
    s.commit()
    yield s, counts
    s.close()


def _demo(s):
    return s.scalars(select(Product).where(Product.is_demo.is_(True))).one()


def test_every_case_is_a_real_investigation_with_a_trace(seeded):
    s, counts = seeded
    demo = _demo(s)
    invs = s.scalars(select(Investigation).where(Investigation.product_id == demo.id)).all()
    assert counts["story"]["cases"] == len(invs) >= 4
    for inv in invs:
        steps = s.scalar(select(func.count(TraceStep.id)).where(TraceStep.investigation_id == inv.id))
        assert steps >= 5, (inv.id, steps)               # never "No trace was recorded"
        assert s.scalars(select(HypothesisRow).where(HypothesisRow.investigation_id == inv.id)).first()
        f = s.scalars(select(Finding).where(Finding.investigation_id == inv.id)).first()
        assert f is not None and f.summary and f.json.get("prose")
        assert inv.budget_json.get("iterations")
    # Cases with a named cause (approving "no cause found" also marks a case
    # resolved, so the cause is what counts).
    resolved = [i for i in invs if i.status == "resolved" and s.scalars(select(Finding).where(
        Finding.investigation_id == i.id)).first().json.get("supported_hypothesis")]
    assert len(resolved) >= 3
    for inv in resolved:                                  # two sources behind each cause
        sources = {e.source for e in s.scalars(select(EvidenceRow).where(
            EvidenceRow.investigation_id == inv.id))}
        assert len(sources) >= 2, (inv.id, sources)
    assert {"resolved", "insufficient_evidence"} <= {i.status for i in invs}
    # Cases sit on a timeline, not all at "now".
    assert len({i.created_at.date() for i in invs}) >= 6


def test_two_fixes_are_confirmed_by_the_real_rule(seeded):
    from echolens import fixwatch
    from echolens.evidence_summary import recent_confirmed_fixes
    from echolens.patterns import patterns
    s, counts = seeded
    demo = _demo(s)
    confirmed = s.scalars(select(FixWatch).where(FixWatch.status == "confirmed")).all()
    assert counts["story"]["fixes_confirmed"] == len(confirmed) == 2
    for w in confirmed:
        assert w.baseline_rate and w.baseline_rate > 0
        assert w.post_rate is not None and w.post_rate <= w.baseline_rate * fixwatch.CONFIRM_DROP
        assert w.chart_json and w.chart_json["before"] and w.chart_json["after"]
        assert w.product_id == demo.id
    # One more is in flight: its issue is open.
    assert s.scalars(select(FixWatch).where(FixWatch.status == "issue_open")).first()
    assert len(recent_confirmed_fixes(s, demo.id, user_id=1)) == 2   # the Today card
    assert patterns(s, demo.id)                                      # Learned patterns


def test_verdicts_give_calibration_a_curve_and_decisions_exist(seeded):
    from echolens.calibration import calibration
    s, counts = seeded
    actions = [fb.action for fb in s.scalars(select(ReviewFeedback))]
    assert 10 <= len(actions) <= 12 and counts["story"]["verdicts"] == len(actions)
    assert actions.count("challenge") >= 2 and actions.count("approve") >= 6
    reasons = {fb.reason for fb in s.scalars(select(ReviewFeedback).where(
        ReviewFeedback.action == "challenge"))}
    assert reasons and None not in reasons
    # A challenge re-opens its case, as it does in the product.
    assert s.scalars(select(Investigation).where(Investigation.opened_by == "challenge")).first()
    curve = calibration(s, _demo(s).id)
    assert curve["n_reviewed"] >= 10 and len([p for p in curve["points"] if p["count"]]) >= 3
    decisions = sorted(d.decision for d in s.scalars(select(FindingDecision)))
    assert decisions == ["park", "wont_fix"]
    park = s.scalars(select(FindingDecision).where(FindingDecision.decision == "park")).one()
    assert park.revisit_by is not None and park.reason


def test_seed_is_deterministic(no_live_llm):
    def shape():
        s = _session()
        seed_demo(s)
        s.commit()
        rows = [(i.status, i.opened_by, s.scalars(select(Finding).where(
                    Finding.investigation_id == i.id)).first().summary)
                for i in s.scalars(select(Investigation).order_by(Investigation.id))]
        watches = [(w.status, w.baseline_rate, w.post_rate)
                   for w in s.scalars(select(FixWatch).order_by(FixWatch.id))]
        return rows, watches
    assert shape() == shape()


def test_story_is_idempotent_and_never_touches_real_products(seeded):
    s, _ = seeded
    real = Product(name="Acme", package_name="com.acme")
    s.add(real)
    s.flush()
    s.add(Review(source="play_store", ext_id="acme-1", rating=1, text="Acme crashed exporting an album",
                 product="Acme", created_at=_demo_now(s)))
    s.commit()
    before = s.scalar(select(func.count(Investigation.id)))
    assert seed_demo_story(s) == {"skipped": "demo already has cases"}
    assert s.scalar(select(func.count(Investigation.id))) == before
    assert not s.scalars(select(Investigation).where(Investigation.product_id == real.id)).first()
    assert s.scalars(select(Review).where(Review.ext_id == "acme-1")).one().text.startswith("Acme crashed")
    # No collector row was invented for the demo: the scheduler must not scrape it.
    assert s.scalars(select(CollectorState)).all() == []


def _demo_now(s):
    from echolens.detector.detect import reference_now
    return reference_now(s, _demo(s).name)


def test_story_needs_a_demo_product(no_live_llm):
    s = _session()
    assert seed_demo_story(s) == {"skipped": "no demo product"}


def test_legacy_generate_is_untouched():
    """The eval and golden suites call generate(session) and rely on it alone."""
    from echolens.synthetic.generate import generate
    s = _session()
    generate(s)
    s.commit()
    assert s.scalars(select(Investigation)).all() == []
    assert {a.slug for a in s.scalars(select(AnomalyEvent))} == {"demo1", "demo2"}
    assert s.scalars(select(Product)).all() == []


def test_bootstrap_seeds_the_story(monkeypatch, no_live_llm):
    from echolens.api import app as app_mod
    from echolens.config import settings
    from echolens.db import session as db_session
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng, expire_on_commit=False)
    monkeypatch.setattr(db_session, "_engine", eng)
    monkeypatch.setattr(db_session, "_SessionLocal", Session)
    monkeypatch.setattr(db_session, "get_engine", lambda db_url=None: eng)
    monkeypatch.setattr(settings, "seed_on_start", True, raising=False)
    monkeypatch.setattr(settings, "bootstrap_admin_email", "", raising=False)
    app_mod._bootstrap()
    with Session() as s:
        assert s.scalar(select(func.count(Investigation.id))) >= 4
        assert s.scalars(select(FixWatch).where(FixWatch.status == "confirmed")).first()


def test_challenge_reopens_survive_the_startup_dedupe(seeded):
    """dedupe_cases runs on every startup; a challenge's re-opened case shares
    its anomaly with the original and must not be merged away."""
    from echolens.db.migrate import dedupe_cases
    s, _ = seeded
    dedupe_cases(s)
    s.commit()
    assert not s.scalars(select(Investigation).where(
        Investigation.status == "merged_duplicate")).first()


def test_every_screen_has_content_through_the_api(monkeypatch, no_live_llm):
    from fastapi.testclient import TestClient

    from echolens.db import session as db_session
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng, expire_on_commit=False)
    with Session() as s:
        seed_demo(s)
        s.commit()
        pid = _demo(s).id
        inv_ids = [i.id for i in s.scalars(select(Investigation))]
    monkeypatch.setattr(db_session, "_engine", eng)
    monkeypatch.setattr(db_session, "_SessionLocal", Session)
    monkeypatch.setattr(db_session, "get_engine", lambda db_url=None: eng)
    from echolens.api.app import app
    c = TestClient(app)
    q = f"?product_id={pid}"
    cases = c.get(f"/cases{q}").json()["cases"]
    assert len(cases) == len(inv_ids)
    for inv_id in inv_ids:                                # every case shows its steps
        trace = c.get(f"/investigations/{inv_id}/trace{q}").json()
        assert trace["steps"], inv_id
    assert c.get(f"/patterns{q}").json()["patterns"]
    assert c.get(f"/calibration{q}").json()["n_reviewed"] >= 10
    assert len(c.get(f"/today/overview{q}").json()["confirmed_fixes"]) == 2
    plan = c.get(f"/backlog/plan{q}").json()
    assert plan["proposed"] or plan["deferred"]
    assert {d["decision"]["decision"] for d in plan["set_aside"]} >= {"park"}
