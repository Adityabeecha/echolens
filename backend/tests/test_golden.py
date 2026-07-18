"""Golden investigation scenarios (PRD §11), hermetic via a scripted LLM.

The FakeLLM replays a fixed sequence of structured responses, so these tests
exercise the REAL LangGraph loop, guards, persistence, and trace — everything
except the model itself. Live-model runs happen via the CLI.
"""
from __future__ import annotations

from echolens.db.models import AnomalyEvent, Finding, Issue, TraceStep
from echolens.investigator.graph import Investigator
from echolens.llm.client import LLMResult
from echolens.tools.search_reviews import search_reviews


class FakeLLM:
    def __init__(self, responses: list[dict]):
        self.responses = list(responses)
        self.calls: list[str] = []

    def complete_json(self, system, user, json_schema, agent) -> LLMResult:
        self.calls.append(agent)
        parsed = self.responses.pop(0)
        return LLMResult(parsed=parsed, tokens_in=200, tokens_out=80, ms=5, model="fake")


def _hypotheses_step():
    return {
        "thought": "Spike began 3 days after v3.2; the Android 15 rollout is a plausible decoy.",
        "action": "revise_hypotheses",
        "hypotheses": [
            {"id": "H1", "statement": "v3.2 background sync causes battery drain",
             "confidence": 0.5, "status": "active", "next_test": "search negative reviews"},
            {"id": "H2", "statement": "Android 15 OS update causes the drain",
             "confidence": 0.4, "status": "active", "next_test": "segment by version"},
        ],
    }


def test_golden_clear_cause_resolves_with_evidence_chain(session):
    anomaly = session.query(AnomalyEvent).filter_by(slug="demo1").one()

    review_args = {"query": "battery drain background", "date_from": "2026-07-11", "rating_max": 2}
    ref1 = search_reviews(session, **review_args)["reviews"][0]["ref"]
    wakelock = session.query(Issue).filter(Issue.title.contains("wakelock")).one()
    ref2 = f"issue {wakelock.ext_id}"

    llm = FakeLLM([
        _hypotheses_step(),
        {"thought": "Check what the negative reviews say.", "action": "call_tool",
         "tool": {"name": "search_reviews", "args": review_args, "tests_hypothesis": "H1"}},
        {"evidence": [{"ref": ref1, "snippet": "battery dies since update",
                       "supports": ["H1"], "contradicts": []}],
         "hypothesis_updates": [{"id": "H1", "new_confidence": 0.65,
                                 "based_on_refs": [ref1], "note": "review language ties drain to update"}]},
        {"thought": "Corroborate with a second, independent source.", "action": "call_tool",
         "tool": {"name": "search_github_issues",
                  "args": {"query": "background sync battery wakelock"}, "tests_hypothesis": "H1"}},
        {"evidence": [{"ref": ref2, "snippet": "wakelock never released when queue empty",
                       "supports": ["H1"], "contradicts": ["H2"]}],
         "hypothesis_updates": [
             {"id": "H1", "new_confidence": 0.85, "based_on_refs": [ref2], "note": "mechanism confirmed"},
             {"id": "H2", "new_confidence": 0.2, "new_status": "rejected",
              "based_on_refs": [ref2], "note": "app-level mechanism, not OS"}]},
        {"summary": "Background sync in v3.2 drives the battery spike",
         "prose": "Battery complaints are caused by the v3.2 background sync [ev_001] [ev_002]. "
                  "The OS update was ruled out.",
         "confidence": 0.85, "supported_hypothesis": "H1",
         "checked": ["play_store", "github"], "what_would_settle_it": ""},
    ])

    inv = Investigator(session, anomaly, llm=llm, tier="standard").run()

    assert inv.status == "resolved"
    trace_kinds = {t.kind for t in session.query(TraceStep).filter_by(investigation_id=inv.id)}
    assert {"THINK", "TOOL", "EVID", "UPDT", "CHECK"} <= trace_kinds

    finding = session.query(Finding).filter_by(investigation_id=inv.id).one()
    assert finding.json["supported_hypothesis"] == "H1"
    assert "ev_001" in finding.json["prose"] and "ev_002" in finding.json["prose"]
    assert not finding.json.get("grounding_violations")


def test_golden_insufficient_evidence_is_honest(session):
    anomaly = session.query(AnomalyEvent).filter_by(slug="demo2").one()
    llm = FakeLLM([
        {"thought": "Shipping-cost complaints; no obvious release link.", "action": "revise_hypotheses",
         "hypotheses": [{"id": "H1", "statement": "pricing change drove complaints",
                         "confidence": 0.4, "status": "active", "next_test": ""}]},
        {"thought": "Nothing corroborates beyond one post; evidence is thin.", "action": "conclude",
         "conclusion": {"status": "insufficient_evidence",
                        "reason": "single weak source; no version correlation"}},
        {"summary": "Insufficient evidence for the shipping-cost spike",
         "prose": "We checked reviews and community posts. No hypothesis passed the bar.",
         "confidence": 0.4, "supported_hypothesis": None,
         "checked": ["play_store", "reddit"],
         "what_would_settle_it": "pricing-experiment flag history and order data"},
    ])
    inv = Investigator(session, anomaly, llm=llm).run()
    assert inv.status == "insufficient_evidence"
    finding = session.query(Finding).filter_by(investigation_id=inv.id).one()
    assert finding.json["what_would_settle_it"]


def test_golden_guard_rejects_unsupported_resolution(session):
    """The agent tries to declare victory with zero evidence — the two-source
    guard must reject it and the loop must end honestly."""
    anomaly = session.query(AnomalyEvent).filter_by(slug="demo1").one()
    llm = FakeLLM([
        {"thought": "It's obviously the sync feature.", "action": "revise_hypotheses",
         "hypotheses": [{"id": "H1", "statement": "sync causes drain",
                         "confidence": 0.9, "status": "active", "next_test": ""}]},
        {"thought": "Confident enough.", "action": "conclude",
         "conclusion": {"status": "resolved", "reason": "high confidence", "supported_hypothesis": "H1"}},
        {"thought": "Guard rejected it; I lack evidence.", "action": "conclude",
         "conclusion": {"status": "insufficient_evidence", "reason": "no retrievable evidence gathered"}},
        {"summary": "Insufficient evidence", "prose": "No evidence was collected to support a conclusion.",
         "confidence": 0.0, "supported_hypothesis": None, "checked": [],
         "what_would_settle_it": "actual tool-backed evidence from two sources"},
    ])
    inv = Investigator(session, anomaly, llm=llm).run()
    assert inv.status == "insufficient_evidence"  # NOT resolved
    rejections = [t for t in session.query(TraceStep).filter_by(investigation_id=inv.id, kind="CHECK")
                  if "REJECTED" in t.content_json.get("text", "")]
    assert rejections, "check node must trace the rejected resolution"
