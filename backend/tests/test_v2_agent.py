"""v2.0 smarter-agent internals: memory, Bayesian confidence, budget extension,
hypothesis dependencies, and specialist delegation."""
from __future__ import annotations

from datetime import datetime, timezone

from echolens.config import BUDGET_TIERS
from echolens.db.models import AnomalyEvent, Finding, Investigation, TraceStep
from echolens.eval.harness import ScriptedLLM
from echolens.investigator import guards, memory
from echolens.investigator.graph import Investigator
from echolens.investigator.specialists import run_specialist
from echolens.investigator.state import Budget


# ── cross-investigation memory ──────────────────────────────────────────

def test_memory_recalls_related_confirmed_cause(session):
    # a past resolved case about battery
    inv = Investigation(anomaly_id=None, status="resolved", budget_tier="standard",
                        budget_json={}, resolved_at=datetime(2026, 7, 16, tzinfo=timezone.utc))
    session.add(inv); session.flush()
    session.add(Finding(investigation_id=inv.id, summary="Background sync causes battery drain",
                        confidence=0.85, status="approved", json={"supported_hypothesis": "H1"}))
    session.flush()
    # a new battery anomaly should recall it
    anomaly = AnomalyEvent(slug="new-batt", type="theme_volume_surge",
                           metric="battery complaints share", delta=0.2, z=2.5, window="7d",
                           description="battery drain complaints rising", status="pending")
    session.add(anomaly); session.flush()
    digest = memory.digest_text(session, anomaly)
    assert digest is not None and "battery drain" in digest.lower()


def test_memory_silent_when_unrelated(session):
    anomaly = AnomalyEvent(slug="unrel", type="theme_volume_surge",
                           metric="checkout crash on ipad", delta=0.2, z=2.5, window="7d",
                           description="crash after coupon removal", status="pending")
    session.add(anomaly); session.flush()
    assert memory.digest_text(session, anomaly) is None


# ── Bayesian confidence ─────────────────────────────────────────────────

def test_bayesian_update_moves_the_right_way():
    assert guards.bayesian_update(0.5, "strong_support") > 0.8
    assert guards.bayesian_update(0.5, "strong_against") < 0.2
    assert guards.bayesian_update(0.5, "neutral") == 0.5
    # monotonic in strength
    assert (guards.bayesian_update(0.5, "moderate_support")
            > guards.bayesian_update(0.5, "weak_support") > 0.5)


# ── budget extension ────────────────────────────────────────────────────

def test_budget_exceeded_honors_extension_factor():
    b = Budget(tier=BUDGET_TIERS["quick"])  # max_iterations = 5
    b.iterations = 5
    assert guards.budget_exceeded(b)          # exhausted at base cap
    b.extension_factor = 1.5                    # cap now 7.5
    assert not guards.budget_exceeded(b)        # 5 < 7.5 → room again
    b.iterations = 8
    assert guards.budget_exceeded(b)            # 8 ≥ 7.5 → exhausted again


# ── hypothesis dependency tracking ──────────────────────────────────────

def test_rejecting_a_rival_boosts_the_dependent(session):
    anomaly = session.query(AnomalyEvent).filter_by(slug="demo1").one()
    inv = Investigator(session, anomaly, llm=ScriptedLLM([]))
    state = {
        "hypotheses": [
            {"id": "H1", "statement": "os", "confidence": 0.3, "status": "rejected",
             "evidence_for": [], "evidence_against": ["ev_001"], "boost_if_rejected": []},
            {"id": "H2", "statement": "app", "confidence": 0.6, "status": "active",
             "evidence_for": ["ev_001", "ev_002"], "evidence_against": [], "boost_if_rejected": ["H1"]},
        ],
        "evidence": [{"id": "ev_001", "source": "play_store"}, {"id": "ev_002", "source": "github"}],
    }
    inv._apply_dependencies(state, newly_rejected=["H1"])
    h2 = next(h for h in state["hypotheses"] if h["id"] == "H2")
    assert h2["confidence"] > 0.6  # auto-boosted because its rival H1 was rejected


# ── specialists ─────────────────────────────────────────────────────────

def test_run_specialist_returns_analysis():
    llm = ScriptedLLM([{"dominant_theme": "battery", "themes": [{"theme": "battery", "tone": "angry"}],
                        "takeaway": "Battery is the dominant complaint."}])
    out = run_specialist(llm, "sentiment_analyst", "some reviews")
    assert out and out["dominant_theme"] == "battery"
    assert run_specialist(llm, "no_such_specialist", "x") is None


def test_delegate_produces_a_spec_trace_step(session):
    anomaly = session.query(AnomalyEvent).filter_by(slug="demo1").one()
    llm = ScriptedLLM([
        {"thought": "let a specialist break down the sentiment", "action": "delegate",
         "delegate": {"specialist": "sentiment_analyst", "focus": "battery", "tests_hypothesis": "H1"}},
        {"dominant_theme": "battery drain", "themes": [{"theme": "battery", "tone": "frustrated"}],
         "takeaway": "Battery drain dominates the negatives."},
        {"thought": "thin, concluding honestly", "action": "conclude",
         "conclusion": {"status": "insufficient_evidence", "reason": "analysis only, no corroboration"}},
        {"summary": "Insufficient", "prose": "We analyzed sentiment but gathered no corroborating evidence.",
         "confidence": 0.3, "supported_hypothesis": None, "checked": ["play_store"],
         "what_would_settle_it": "cross-source corroboration"},
    ])
    inv = Investigator(session, anomaly, llm=llm).run()
    specs = session.query(TraceStep).filter_by(investigation_id=inv.id, kind="SPEC").all()
    assert specs, "delegation should record a SPEC trace step"
    assert "battery" in specs[0].content_json.get("text", "").lower()
