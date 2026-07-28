"""Roadmap verification (v3/v4/v6/v7): the claims, asserted rather than assumed.

Each test pins a behaviour the roadmap promises, so a later refactor that
quietly removes it fails here instead of in a demo.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from echolens import brain, chat, fixwatch
from echolens.config import BUDGET_TIERS
from echolens.db.models import (AnomalyEvent, Base, CollectorState, Finding,
                                Investigation, KnowledgeEdge, Issue, Post,
                                Product, Review)
from echolens.investigator import guards
from echolens.investigator.memory import digest_text
from echolens.orchestrator.triage import adaptive_tier

NOW = datetime(2026, 7, 20, tzinfo=timezone.utc)


def _db():
    e = create_engine("sqlite://")
    Base.metadata.create_all(e)
    return Session(e)


def _anomaly(s, slug, metric="battery drain", z=3.0, typ="volume_spike", product_id=None):
    a = AnomalyEvent(slug=slug, type=typ, metric=metric, delta=1.0, z=z, window="7d",
                     description=f"{metric} surge", status="pending", product_id=product_id)
    s.add(a)
    s.flush()
    return a


# ── v3: adaptive budgets ────────────────────────────────────────────────

def test_budget_tiers_actually_differ():
    """Three tiers that resolve to the same limits would make adaptive_tier
    cosmetic."""
    it = [BUDGET_TIERS[t].max_iterations for t in ("quick", "standard", "deep")]
    cost = [BUDGET_TIERS[t].max_cost_usd for t in ("quick", "standard", "deep")]
    assert it == sorted(it) and len(set(it)) == 3
    assert cost == sorted(cost) and len(set(cost)) == 3


def test_a_sharp_single_source_spike_is_cheaper_to_investigate():
    with _db() as s:
        assert adaptive_tier(_anomaly(s, "sharp", z=4.5), s, "standard") == "quick"


def test_a_signal_echoed_in_other_sources_earns_a_bigger_budget():
    """More places saying it means more to weigh, so scope goes UP."""
    with _db() as s:
        a = _anomaly(s, "fuzzy", z=1.0, typ="theme_volume_surge")
        assert adaptive_tier(a, s, "standard") == "standard"
        s.add(Issue(ext_id="r#1", title="battery drain", body_snippet="x", state="open",
                    reactions=0, created_at=NOW, product="Lumo"))
        s.add(Post(ext_id="p1", source="reddit", text_snippet="battery drain",
                   created_at=NOW, product="Lumo"))
        s.flush()
        assert adaptive_tier(a, s, "standard") == "deep"


# ── v3: Bayesian confidence ─────────────────────────────────────────────

def test_confidence_moves_monotonically_with_evidence_strength():
    labels = ["strong_against", "moderate_against", "weak_against", "neutral",
              "weak_support", "moderate_support", "strong_support"]
    vals = [guards.bayesian_update(0.5, lab) for lab in labels]
    assert vals == sorted(vals)
    assert len(set(vals)) == len(vals)


def test_confidence_stays_a_probability_and_never_saturates():
    for prior in (0.0, 0.01, 0.5, 0.99, 1.0):
        for lab in ("strong_support", "strong_against", "neutral"):
            v = guards.bayesian_update(prior, lab)
            assert 0.0 < v < 1.0


def test_an_unrecognised_likelihood_is_neutral():
    """An unknown label must not silently move confidence in either direction."""
    assert guards.bayesian_update(0.42, "not_a_real_label") == 0.42


# ── v4: the brain self-calibrates ───────────────────────────────────────

def test_a_belief_that_keeps_missing_retires_itself():
    """The strongest claim on the roadmap: knowledge that stops predicting is
    given up. A brain that cannot abandon a belief is folklore."""
    with _db() as s:
        edge = KnowledgeEdge(product_id=1, subsystem="sync scheduler",
                             symptom="battery drain", supports=1, refutes=0, status="active")
        s.add(edge)
        s.flush()
        for _ in range(8):
            brain.record_outcome(s, "sync scheduler", "battery drain",
                                 held=False, product_id=1)
            if edge.status == "retired":
                break
        assert edge.status == "retired"


def test_a_belief_that_keeps_holding_stays_active():
    with _db() as s:
        edge = KnowledgeEdge(product_id=2, subsystem="cache", symptom="stale data",
                             supports=1, refutes=0, status="active")
        s.add(edge)
        s.flush()
        for _ in range(6):
            brain.record_outcome(s, "cache", "stale data", held=True, product_id=2)
        assert edge.status == "active"
        assert brain._confidence(edge.supports, edge.refutes) > 0.8


# ── v4: cross-investigation memory ──────────────────────────────────────

def _resolved_case(s, product, metric, cause):
    a = _anomaly(s, f"old-{metric}", metric=metric, product_id=product.id)
    inv = Investigation(anomaly_id=a.id, status="resolved", budget_tier="standard",
                        product_id=product.id, resolved_at=NOW - timedelta(days=60))
    s.add(inv)
    s.flush()
    s.add(Finding(investigation_id=inv.id, product_id=product.id, confidence=0.9,
                  status="approved", summary=cause,
                  json={"summary": cause, "supported_hypothesis": cause}))
    s.flush()
    return inv


def test_a_new_case_inherits_what_an_old_one_proved():
    with _db() as s:
        p = Product(name="Lumo")
        s.add(p)
        s.flush()
        _resolved_case(s, p, "battery drain",
                       "Battery drain caused by a wakelock in the 3.2 sync scheduler")
        digest = digest_text(s, _anomaly(s, "new", metric="battery drain", product_id=p.id))
        assert digest and "wakelock" in digest


def test_an_unrelated_case_inherits_nothing():
    """Priming every investigation with every past case would bias them all."""
    with _db() as s:
        p = Product(name="Lumo")
        s.add(p)
        s.flush()
        _resolved_case(s, p, "battery drain", "Wakelock in the sync scheduler")
        assert digest_text(s, _anomaly(s, "u", metric="checkout payment failure",
                                       product_id=p.id)) is None


# ── v6: fix verification ────────────────────────────────────────────────

def _watch_scenario(s, label, before, after, days_since_fix, n):
    p = Product(name=label)
    s.add(p)
    s.flush()
    s.add(CollectorState(source="play_store", identifier=label, product=label,
                         status="healthy", enabled=True, last_run_at=NOW, product_id=p.id))
    a = _anomaly(s, f"w{n}", product_id=p.id)
    inv = Investigation(anomaly_id=a.id, status="resolved", budget_tier="standard",
                        product_id=p.id)
    s.add(inv)
    s.flush()
    f = Finding(investigation_id=inv.id, product_id=p.id, confidence=0.9,
                status="approved", summary="battery drain from wakelock")
    s.add(f)
    s.flush()
    fixed = NOW - timedelta(days=days_since_fix)
    for tag, start, per in (("b", fixed - timedelta(days=20), before), ("a", fixed, after)):
        for d in range(20):
            for i in range(per):
                s.add(Review(source="play_store", ext_id=f"{n}{tag}{d}{i}", rating=1,
                             text="battery drain is terrible",
                             created_at=start + timedelta(days=d), product=label))
    s.flush()
    w = fixwatch.link_issue(s, f, "acme/x", 100 + n)
    w.product_id = p.id
    s.flush()
    fixwatch.on_issue_closed(s, "acme/x", 100 + n, closed_at=fixed)
    fixwatch.evaluate(s, as_of=NOW)
    return w


def test_a_fix_that_worked_is_confirmed():
    with _db() as s:
        w = _watch_scenario(s, "FIXED", 5, 0, 40, 1)
        assert w.status == "confirmed"
        assert w.baseline_rate > 0 and w.post_rate == 0.0


def test_a_fix_that_did_nothing_reopens():
    with _db() as s:
        assert _watch_scenario(s, "NOCHANGE", 5, 5, 40, 2).status == "persists_reopened"


def test_a_half_fix_is_inconclusive_not_confirmed():
    """A confirmed fix is mined by the brain as ground truth, so a 50% drop must
    escalate to a human rather than bank itself as verified."""
    with _db() as s:
        assert _watch_scenario(s, "PARTIAL", 10, 5, 40, 3).status == "inconclusive"


def test_nothing_is_concluded_before_the_window_closes():
    with _db() as s:
        assert _watch_scenario(s, "EARLY", 5, 5, 6, 4).status == "watching"


# ── v7: chat cites real cases ───────────────────────────────────────────

def _chat_fixture(s, finding_json):
    p = Product(name="Lumo")
    s.add(p)
    s.flush()
    a = _anomaly(s, "c1", product_id=p.id)
    inv = Investigation(anomaly_id=a.id, status="resolved", budget_tier="standard",
                        product_id=p.id)
    s.add(inv)
    s.flush()
    s.add(Finding(investigation_id=inv.id, product_id=p.id, confidence=0.88,
                  status="approved", summary="Battery drain from a wakelock",
                  json=finding_json))
    s.flush()
    return p


def test_chat_answers_a_topic_question_with_a_citation():
    with _db() as s:
        p = _chat_fixture(s, {"summary": "Battery drains overnight on 3.2"})
        r = chat.route(s, "tell me about battery drain", product_id=p.id)
        assert r["type"] == "answer"
        assert len(r["citations"]) == 1
        assert "Battery drains overnight" in r["text"]


def test_chat_answer_is_never_a_subjectless_fragment():
    """decision_doc reads json["summary"]; a finding whose JSON was never written
    produced the answer " — case #1." with no subject. The Finding.summary
    column holds the same text and is now the fallback."""
    with _db() as s:
        p = _chat_fixture(s, {"prose": "only prose, no summary key"})
        r = chat.route(s, "tell me about battery drain", product_id=p.id)
        assert not r["text"].strip().startswith("—")
        assert "Battery drain from a wakelock" in r["text"]
        assert len(r["citations"]) == 1


def test_chat_admits_when_it_has_not_investigated_something():
    """The honesty property: no case must never be answered with a guess."""
    with _db() as s:
        p = _chat_fixture(s, {"summary": "Battery drains overnight"})
        r = chat.route(s, "tell me about the checkout flow", product_id=p.id)
        assert r["citations"] == []
        assert "haven't investigated" in r["text"]


def test_an_investigate_question_launches_rather_than_guessing():
    with _db() as s:
        p = _chat_fixture(s, {"summary": "Battery drains overnight"})
        assert chat.route(s, "why is the battery draining?", product_id=p.id)["type"] == "launch"
