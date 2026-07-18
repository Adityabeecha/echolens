"""Recommender: ranked actions for resolved findings only."""
from __future__ import annotations

from echolens.db.models import Finding, Investigation
from echolens.eval.harness import ScriptedLLM
from echolens.recommender.recommend import recommend


def _finding(session, supported):
    inv = Investigation(anomaly_id=None, status="resolved", budget_tier="standard", budget_json={})
    session.add(inv)
    session.flush()
    f = Finding(investigation_id=inv.id, summary="s", confidence=0.85, status="draft",
                json={"summary": "s", "prose": "p", "supported_hypothesis": supported})
    session.add(f)
    session.flush()
    return f


def test_recommends_ranked_actions_for_resolved(session):
    finding = _finding(session, supported="H1")
    script = ScriptedLLM([{"actions": [
        {"rank": 2, "action": "Fix wakelock in BackgroundSyncWorker", "impact": "HIGH", "effort": "MED"},
        {"rank": 1, "action": "Make background sync opt-in via flag", "impact": "HIGH", "effort": "LOW"},
        {"rank": 3, "action": "Defer sync to charging + Wi-Fi", "impact": "MED", "effort": "MED"},
    ]}])
    recs = recommend(session, finding, llm=script)
    assert [r.rank for r in recs] == [1, 2, 3]  # sorted by rank
    assert recs[0].impact == "HIGH" and recs[0].effort == "LOW"


def test_no_recommendations_without_a_confirmed_cause(session):
    finding = _finding(session, supported=None)  # insufficient / needs_human
    recs = recommend(session, finding, llm=ScriptedLLM([{"actions": []}]))
    assert recs == []
