"""v12 — the product-knowledge brain: a learned causal model of how it breaks.

Exit criteria under test:
  1. a risky proposed change is flagged BEFORE it ships, from learned history
  2. a new team member queries the failure modes instead of reading postmortems
  plus: the brain self-calibrates — a cause that stops holding retires itself.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from echolens.db.models import (
    AnomalyEvent, Base, Finding, FixWatch, Investigation, KnowledgeEdge, Product)

NOW = datetime(2026, 7, 20, tzinfo=timezone.utc)


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _confirmed(s, pid, *, cause, terms, n=1, symptom_text="", verified_from=1):
    """N confirmed fixes for the same cause — how the brain earns an edge."""
    invs = []
    for k in range(n):
        a = AnomalyEvent(slug=f"{cause[:8]}-{verified_from + k}", type="theme_volume_surge",
                         metric=cause, delta=0.3, z=3.0, window="7d",
                         description=f"{cause}. {symptom_text}", status="closed", product_id=pid)
        s.add(a); s.flush()
        inv = Investigation(anomaly_id=a.id, status="resolved", opened_by="anomaly",
                            budget_tier="standard", budget_json={}, product_id=pid,
                            created_at=NOW - timedelta(days=30 + k))
        s.add(inv); s.flush()
        f = Finding(investigation_id=inv.id, summary=f"{cause}. {symptom_text}",
                    confidence=0.88, status="approved", product_id=pid,
                    json={"summary": cause, "prose": symptom_text})
        s.add(f); s.flush()
        s.add(FixWatch(finding_id=f.id, investigation_id=inv.id, repo="o/r",
                       issue_number=verified_from + k, status="confirmed",
                       terms=terms, metric="m", product_id=pid,
                       confirmed_at=NOW - timedelta(days=10 + k)))
        invs.append(inv)
    s.flush()
    return invs


# ── mining ──────────────────────────────────────────────────────────────

def test_the_brain_learns_a_causal_edge_from_confirmed_fixes():
    from echolens.brain import edges, rebuild
    s = _session()
    p = Product(name="Lumo"); s.add(p); s.flush()
    _confirmed(s, p.id, cause="Background sync holds a wakelock",
               terms=["sync", "wakelock", "battery"],
               symptom_text="draining the battery overnight", n=4)
    s.commit()

    rebuild(s, p.id)
    e = edges(s, p.id)
    assert e, "a confirmed sync->battery pattern must become an edge"
    top = e[0]
    assert top["subsystem"] == "sync" and top["symptom"] == "battery-drain"
    assert top["verified_count"] == 4
    assert "sync" in top["statement"] and "battery" in top["statement"]
    assert 0.5 <= top["confidence"] < 1.0, "confidence is earned, never certain"


def test_confidence_rises_with_more_confirmations():
    from echolens.brain import _confidence
    assert _confidence(1, 0) < _confidence(4, 0) < _confidence(20, 0) < 1.0


def test_a_finding_with_no_recognisable_subsystem_makes_no_edge():
    from echolens.brain import edges, rebuild
    s = _session()
    p = Product(name="Lumo"); s.add(p); s.flush()
    _confirmed(s, p.id, cause="The mascot's hat looks odd", terms=["hat", "mascot"])
    s.commit()
    rebuild(s, p.id)
    assert edges(s, p.id) == []


# ── exit criterion 1: risky change flagged BEFORE it ships ──────────────

def test_a_risky_pr_is_flagged_pre_ship_with_a_cited_reason():
    """THE exit criterion. The brain has learned sync->battery; a PR that touches
    sync must be flagged before merge, grounded in the real cases."""
    from echolens.brain import rebuild, review_change
    s = _session()
    p = Product(name="Lumo"); s.add(p); s.flush()
    invs = _confirmed(s, p.id, cause="Background sync holds a wakelock",
                      terms=["sync", "wakelock", "battery"],
                      symptom_text="draining the battery overnight", n=3)
    s.commit()
    rebuild(s, p.id)

    pr = ("PR #812: Rework the background sync scheduler to batch uploads more "
          "aggressively when the device is idle.")
    review = review_change(s, pr, p.id)
    assert review["risk"] in ("elevated", "high")
    assert "sync" in review["subsystems_touched"]
    flag = review["flags"][0]
    assert flag["symptom"] == "battery-drain"
    assert flag["case_ids"], "the flag must cite the cases it learned from"
    assert flag["case_ids"][0] == invs[0].id
    assert "battery" in review["summary"].lower()
    assert flag["recommendation"], "prevention: it must suggest what to test"


def test_a_change_touching_an_unknown_area_is_not_falsely_flagged():
    from echolens.brain import rebuild, review_change
    s = _session()
    p = Product(name="Lumo"); s.add(p); s.flush()
    _confirmed(s, p.id, cause="Background sync holds a wakelock",
               terms=["sync", "wakelock"], symptom_text="battery drain", n=2)
    s.commit()
    rebuild(s, p.id)
    review = review_change(s, "PR: tweak the About page copyright year", p.id)
    assert review["risk"] == "clear" and review["flags"] == []
    assert "doesn't touch" in review["summary"] or "no known" in review["summary"].lower()


# ── exit criterion 2: onboarding oracle, cited to real findings ─────────

def test_a_new_pm_can_query_the_failure_modes_instead_of_reading_postmortems():
    from echolens.brain import ask, rebuild
    s = _session()
    p = Product(name="Lumo"); s.add(p); s.flush()
    invs = _confirmed(s, p.id, cause="Background sync holds a wakelock",
                      terms=["sync", "battery"], symptom_text="battery drain overnight", n=3)
    _confirmed(s, p.id, cause="Onboarding step 3 confuses new users",
               terms=["onboarding", "signup"], symptom_text="users are leaving confused",
               n=2, verified_from=50)
    s.commit()
    rebuild(s, p.id)

    ans = ask(s, "what usually goes wrong with releases here?", p.id, "Lumo")
    assert ans["grounded"] is True
    assert "Lumo" in ans["answer"]
    assert "sync" in ans["answer"].lower() and "onboarding" in ans["answer"].lower()
    assert "case #" in ans["answer"], "every claim is cited to a real case"


def test_the_oracle_focuses_when_the_question_names_a_subsystem():
    from echolens.brain import ask, rebuild
    s = _session()
    p = Product(name="Lumo"); s.add(p); s.flush()
    _confirmed(s, p.id, cause="Sync wakelock", terms=["sync", "battery"],
               symptom_text="battery drain", n=2)
    _confirmed(s, p.id, cause="Checkout timeout", terms=["checkout", "payment"],
               symptom_text="users overcharged and angry", n=2, verified_from=50)
    s.commit()
    rebuild(s, p.id)
    ans = ask(s, "any risks around payments and checkout?", p.id, "Lumo")
    assert "payment" in ans["answer"].lower() or "billing" in ans["answer"].lower()


def test_the_oracle_admits_an_empty_brain_rather_than_generalising():
    from echolens.brain import ask
    s = _session()
    p = Product(name="New"); s.add(p); s.commit()
    ans = ask(s, "what goes wrong here?", p.id, "New")
    assert ans["grounded"] is False
    assert "New" in ans["answer"] and "confirmed fixes" in ans["answer"]


# ── self-calibration: knowledge that stops predicting retires ───────────

def test_an_edge_that_keeps_missing_decays_and_retires():
    """The honesty guard on the brain itself: a cause that stops holding must
    give itself up rather than linger as confident folklore."""
    from echolens.brain import edges, rebuild, record_outcome
    s = _session()
    p = Product(name="Lumo"); s.add(p); s.flush()
    _confirmed(s, p.id, cause="Sync wakelock", terms=["sync", "battery"],
               symptom_text="battery drain", n=2)
    s.commit()
    rebuild(s, p.id)
    assert edges(s, p.id)[0]["confidence"] >= 0.5

    # the subsystem keeps being changed, and the symptom keeps NOT appearing
    for _ in range(8):
        record_outcome(s, "sync", "battery-drain", held=False, product_id=p.id)
    s.commit()

    active = edges(s, p.id)
    assert not any(e["subsystem"] == "sync" for e in active), \
        "an edge that stopped predicting should have retired"
    retired = edges(s, p.id, include_retired=True)
    sync_edge = [e for e in retired if e["subsystem"] == "sync"][0]
    assert sync_edge["status"] == "retired"
    assert sync_edge["confidence"] < 0.5


def test_a_correct_prediction_reinforces_the_edge():
    from echolens.brain import edges, rebuild, record_outcome
    s = _session()
    p = Product(name="Lumo"); s.add(p); s.flush()
    _confirmed(s, p.id, cause="Sync wakelock", terms=["sync", "battery"],
               symptom_text="battery drain", n=1)
    s.commit()
    rebuild(s, p.id)
    before = edges(s, p.id)[0]["confidence"]
    for _ in range(5):
        record_outcome(s, "sync", "battery-drain", held=True, product_id=p.id)
    s.commit()
    assert edges(s, p.id)[0]["confidence"] > before


def test_calibration_from_history_grades_edges_against_real_cases():
    from echolens.brain import calibrate_from_history, edges, rebuild
    s = _session()
    p = Product(name="Lumo"); s.add(p); s.flush()
    _confirmed(s, p.id, cause="Sync wakelock", terms=["sync", "battery"],
               symptom_text="battery drain", n=2)
    # a NEW resolved sync case that did NOT drain battery — a miss for the edge
    a = AnomalyEvent(slug="sync-miss", type="theme_volume_surge", metric="m", delta=0.2,
                     z=2.0, window="7d", description="sync is slow to start",
                     status="closed", product_id=p.id)
    s.add(a); s.flush()
    inv = Investigation(anomaly_id=a.id, status="resolved", opened_by="anomaly",
                        budget_tier="quick", budget_json={}, product_id=p.id,
                        created_at=NOW - timedelta(days=3))
    s.add(inv); s.flush()
    s.add(Finding(investigation_id=inv.id, summary="Sync startup is slow", confidence=0.8,
                  status="approved", product_id=p.id,
                  json={"summary": "sync slow to start", "prose": "slow loading"}))
    s.commit()
    rebuild(s, p.id)

    res = calibrate_from_history(s, p.id, as_of=NOW)
    assert res["tested"] >= 1
    assert res["misses"] >= 1, "the non-battery sync case is a miss for sync->battery"


# ── scoping ─────────────────────────────────────────────────────────────

def test_the_brain_is_product_scoped():
    from echolens.brain import edges, rebuild
    s = _session()
    a = Product(name="A"); b = Product(name="B"); s.add(a); s.add(b); s.flush()
    _confirmed(s, a.id, cause="Sync wakelock", terms=["sync", "battery"],
               symptom_text="battery drain", n=2)
    _confirmed(s, b.id, cause="Checkout fails", terms=["checkout", "payment"],
               symptom_text="users overcharged", n=2, verified_from=50)
    s.commit()
    rebuild(s, a.id); rebuild(s, b.id)
    assert edges(s, a.id)[0]["subsystem"] == "sync"
    assert edges(s, b.id)[0]["subsystem"] == "payments"
    assert all(e["subsystem"] != "payments" for e in edges(s, a.id))
