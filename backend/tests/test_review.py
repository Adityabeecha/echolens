"""Human review loop: approve closes the case; challenge re-opens it with the
reviewer's note injected as context (PRD §4.1)."""
from __future__ import annotations

from echolens import review
from echolens.db.models import AnomalyEvent, Finding, Investigation, ReviewFeedback, TraceStep
from echolens.eval.harness import ScriptedLLM
from echolens.investigator.graph import Investigator
from echolens.tools.search_github_issues import search_github_issues
from echolens.tools.search_reviews import search_reviews


def _resolved_finding(session) -> Finding:
    ref_r = search_reviews(session, query="battery drain", date_from="2026-07-11", rating_max=2)["reviews"][0]["ref"]
    ref_g = search_github_issues(session, "background sync battery wakelock")["issues"][0]["ref"]
    anomaly = session.query(AnomalyEvent).filter_by(slug="demo1").one()
    responses = [
        {"thought": "form", "action": "revise_hypotheses",
         "hypotheses": [{"id": "H1", "statement": "sync causes drain", "confidence": 0.5, "status": "active"}]},
        {"thought": "reviews", "action": "call_tool",
         "tool": {"name": "search_reviews", "args": {"query": "battery drain", "date_from": "2026-07-11", "rating_max": 2}, "tests_hypothesis": "H1"}},
        {"evidence": [{"ref": ref_r, "snippet": "drain since update", "supports": ["H1"], "contradicts": []}],
         "hypothesis_updates": [{"id": "H1", "new_confidence": 0.6, "based_on_refs": [ref_r], "note": "x"}]},
        {"thought": "github", "action": "call_tool",
         "tool": {"name": "search_github_issues", "args": {"query": "background sync battery wakelock"}, "tests_hypothesis": "H1"}},
        {"evidence": [{"ref": ref_g, "snippet": "wakelock leak", "supports": ["H1"], "contradicts": []}],
         "hypothesis_updates": [{"id": "H1", "new_confidence": 0.85, "based_on_refs": [ref_g], "note": "confirmed"}]},
        {"summary": "sync drives the spike", "prose": "The spike is caused by v3.2 sync [ev_001][ev_002].",
         "confidence": 0.85, "supported_hypothesis": "H1", "checked": ["play_store", "github"], "what_would_settle_it": ""},
    ]
    inv = Investigator(session, anomaly, llm=ScriptedLLM(responses)).run()
    assert inv.status == "resolved"
    return session.query(Finding).filter_by(investigation_id=inv.id).one()


def test_approve_closes_the_case(session):
    finding = _resolved_finding(session)
    review.approve(session, finding, note="looks right")
    assert finding.status == "approved"
    inv = session.get(Investigation, finding.investigation_id)
    assert inv.status == "resolved"
    assert session.get(AnomalyEvent, inv.anomaly_id).status == "closed"
    fb = session.query(ReviewFeedback).filter_by(finding_id=finding.id).one()
    assert fb.action == "approve"


def test_challenge_reopens_with_note_injected(session):
    finding = _resolved_finding(session)
    old_inv_id = finding.investigation_id
    note = "Battery complaints also mention charging speed — check charger reviews first."

    reopen_script = ScriptedLLM([
        {"thought": "Addressing the challenge about chargers.", "action": "conclude",
         "conclusion": {"status": "insufficient_evidence", "reason": "charger angle unconfirmed"}},
        {"summary": "reopened", "prose": "Re-checked per the challenge; evidence remains thin.",
         "confidence": 0.4, "supported_hypothesis": None, "checked": ["play_store"],
         "what_would_settle_it": "charger-segmented reviews"},
    ])
    reopened = review.challenge(session, finding, note, llm=reopen_script)

    assert finding.status == "challenged"
    fb = session.query(ReviewFeedback).filter_by(finding_id=finding.id, action="challenge").one()
    assert fb.note == note
    assert reopened.id != old_inv_id
    assert reopened.opened_by == "challenge"
    assert reopened.reopens_investigation_id == old_inv_id
    # the note is injected into the new investigation's trace as context
    thinks = session.query(TraceStep).filter_by(investigation_id=reopened.id, kind="THINK").all()
    assert any(note in t.content_json.get("text", "") for t in thinks)


def test_challenge_requires_a_note(session):
    finding = _resolved_finding(session)
    try:
        review.challenge(session, finding, "   ")
        raised = False
    except ValueError:
        raised = True
    assert raised
