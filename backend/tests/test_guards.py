"""Honesty + budget guards are deterministic code — test them like it."""
from __future__ import annotations

from echolens.config import BUDGET_TIERS
from echolens.investigator.guards import (
    budget_exceeded,
    classify_end_state,
    conflicting_evidence,
    resolvable_hypothesis,
    two_source_rule,
    unsupported_claims,
)
from echolens.investigator.state import Budget


def _h(conf=0.85, ev_for=("ev_001", "ev_002"), status="active"):
    return {"id": "H1", "statement": "x", "confidence": conf, "status": status,
            "evidence_for": list(ev_for), "evidence_against": []}


def _ev(eid, source):
    return {"id": eid, "source": source, "ref": "r", "snippet": "s",
            "supports": ["H1"], "contradicts": []}


def test_two_source_rule_requires_distinct_sources():
    same = [_ev("ev_001", "play_store"), _ev("ev_002", "play_store")]
    distinct = [_ev("ev_001", "play_store"), _ev("ev_002", "github")]
    assert not two_source_rule(_h(), same)
    assert two_source_rule(_h(), distinct)


def test_two_source_rule_requires_two_items():
    assert not two_source_rule(_h(ev_for=("ev_001",)), [_ev("ev_001", "github")])


def test_resolvable_needs_confidence_and_sources():
    ev = [_ev("ev_001", "play_store"), _ev("ev_002", "github")]
    assert resolvable_hypothesis([_h(conf=0.85)], ev) is not None
    assert resolvable_hypothesis([_h(conf=0.7)], ev) is None          # confidence too low
    assert resolvable_hypothesis([_h(conf=0.9, status="rejected")], ev) is None


def test_budget_exceeded_lists_reasons():
    b = Budget(tier=BUDGET_TIERS["quick"])
    assert budget_exceeded(b) == []
    b.iterations = 5
    b.cost_usd = 0.30
    reasons = budget_exceeded(b)
    assert any("iterations" in r for r in reasons)
    assert any("cost" in r for r in reasons)


def test_classify_end_state_is_honest():
    assert classify_end_state([_h(conf=0.3)])[0] == "insufficient_evidence"
    assert classify_end_state([_h(conf=0.6)])[0] == "needs_human"
    assert classify_end_state([])[0] == "insufficient_evidence"


def test_conflicting_evidence_flags_split_hypotheses():
    h = _h()
    h["evidence_against"] = ["ev_003", "ev_004"]
    assert conflicting_evidence([h])
    assert not conflicting_evidence([_h()])


def test_claim_grounding_scan():
    ids = {"ev_001", "ev_002"}
    ok = "Battery complaints are caused by background sync [ev_001] [ev_002]. Users are unhappy."
    assert unsupported_claims(ok, ids) == []
    bare = "The spike was caused by the v3.2 release. It is what it is."
    assert len(unsupported_claims(bare, ids)) == 1
    fake_ref = "The spike was caused by the release [ev_999]."
    assert len(unsupported_claims(fake_ref, ids)) == 1
    no_claims = "We checked reviews and issues. Evidence was thin."
    assert unsupported_claims(no_claims, ids) == []
