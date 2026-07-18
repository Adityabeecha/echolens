"""Orchestrator triage: LLM proposes, code enforces the daily cap."""
from __future__ import annotations

from echolens.db.models import AnomalyEvent, TriageDecision
from echolens.detector.detect import scan
from echolens.eval.harness import ScriptedLLM
from echolens.orchestrator.triage import Orchestrator


def _pending(session):
    return {a.slug: a for a in session.query(AnomalyEvent).filter_by(status="pending")}


def test_triage_applies_and_persists_decisions(session):
    scan(session)
    script = {"decisions": [
        {"anomaly": "auto-neg-review-spike", "decision": "investigate",
         "reason": "clear spike", "budget_tier": "standard"},
        {"anomaly": "auto-issues-background", "decision": "merge",
         "reason": "same signal", "merge_into": "auto-neg-review-spike"},
        {"anomaly": "auto-theme-battery-drain", "decision": "ignore",
         "reason": "duplicate theme"},
    ]}
    decisions = Orchestrator(session, llm=ScriptedLLM([script])).triage()
    by_slug = {d.anomaly.slug: d for d in decisions}

    assert by_slug["auto-neg-review-spike"].decision == "investigate"
    assert by_slug["auto-neg-review-spike"].budget_tier == "standard"
    merged = by_slug["auto-issues-background"]
    assert merged.decision == "merge" and merged.merge_into.slug == "auto-neg-review-spike"

    # persisted + anomaly statuses updated
    assert session.query(TriageDecision).count() >= 3
    spike = session.query(AnomalyEvent).filter_by(slug="auto-neg-review-spike").one()
    assert spike.status == "triaged"
    assert session.query(AnomalyEvent).filter_by(slug="auto-issues-background").one().status == "merged"


def test_daily_cap_is_enforced_in_code(session):
    """The model may propose many investigations; the cap keeps only the
    highest-severity ones and defers the rest."""
    scan(session)
    pending = _pending(session)
    script = {"decisions": [
        {"anomaly": s, "decision": "investigate", "reason": "x", "budget_tier": "standard"}
        for s in pending
    ]}
    decisions = Orchestrator(session, llm=ScriptedLLM([script]), daily_limit=1).triage()
    investigate = [d for d in decisions if d.decision == "investigate"]
    assert len(investigate) == 1
    # the survivor is the highest-|z| anomaly
    assert abs(investigate[0].anomaly.z) == max(abs(a.z) for a in pending.values())
    deferred = [d for d in decisions if d.decision == "ignore" and "cap" in d.reason]
    assert deferred


def test_unmentioned_anomalies_default_to_ignore(session):
    scan(session)
    decisions = Orchestrator(session, llm=ScriptedLLM([{"decisions": []}])).triage()
    assert decisions
    assert all(d.decision == "ignore" for d in decisions)
