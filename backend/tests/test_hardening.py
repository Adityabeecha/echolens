"""Hardening: LLM backoff on transient errors, and investigation recovery."""
from __future__ import annotations

from contextlib import contextmanager
import threading
import time

import pytest

from echolens.db.models import AnomalyEvent, Finding, Investigation, TraceStep
from echolens.eval.harness import ScriptedLLM
from echolens.investigator.graph import Investigator
from echolens.investigator.recover import resume_running
from echolens.llm.client import LLMResult, LLMServiceError
from echolens.tools.search_github_issues import search_github_issues
from echolens.tools.search_reviews import search_reviews


def test_llm_backoff_retries_transient_then_succeeds(monkeypatch):
    from echolens.llm import openai_client as oc

    class FakeRateLimit(Exception):
        pass

    monkeypatch.setattr(oc, "_TRANSIENT", (FakeRateLimit,))

    calls = {"n": 0}

    class FakeResp:
        class _Choice:
            class _Msg:
                content = '{"ok": true}'
            message = _Msg()
        choices = [_Choice()]
        usage = type("U", (), {"prompt_tokens": 1, "completion_tokens": 1})()

    client = oc.OpenAIClient.__new__(oc.OpenAIClient)
    client.model = "gpt-4o-mini"
    client._on_call = None
    client._max_retries = 5
    client._base_delay = 0.0
    client._sleep = lambda _d: None  # don't actually wait

    def fake_create(**_kw):
        calls["n"] += 1
        if calls["n"] < 3:
            raise FakeRateLimit("429")
        return FakeResp()

    client._client = type("C", (), {"chat": type("Ch", (), {"completions": type("Co", (), {"create": staticmethod(fake_create)})()})()})()
    res = client.complete_json("s", "u", {"type": "object"}, "agent")
    assert res.parsed == {"ok": True}
    assert calls["n"] == 3  # failed twice, succeeded on the third


def test_llm_translates_a_persistent_provider_503(monkeypatch):
    from echolens.llm import openai_client as oc

    class FakeUnavailable(Exception):
        pass

    monkeypatch.setattr(oc, "_TRANSIENT", (FakeUnavailable,))
    client = oc.OpenAIClient.__new__(oc.OpenAIClient)
    client.model = "gpt-4o-mini"
    client._on_call = None
    client._max_retries = 0
    client._base_delay = 0.0
    client._sleep = lambda _d: None
    client._max_total_s = 1.0
    client._supports_temperature = False

    def unavailable(**_kw):
        raise FakeUnavailable("503 Service Unavailable")

    completions = type("Completions", (), {"create": staticmethod(unavailable)})()
    client._client = type(
        "Client", (), {"chat": type("Chat", (), {"completions": completions})()})()

    with pytest.raises(LLMServiceError, match="service unavailable"):
        client.complete_json("system", "user", {"type": "object"}, "investigator.finding")


def _run_partial_then_orphan(session):
    """Run one investigation, then simulate a crash: flip it back to running
    with a checkpoint so recovery has something to resume."""
    ref_r = search_reviews(session, query="battery drain", date_from="2026-07-11", rating_max=2)["reviews"][0]["ref"]
    ref_g = search_github_issues(session, "background sync battery wakelock")["issues"][0]["ref"]
    anomaly = session.query(AnomalyEvent).filter_by(slug="demo1").one()
    resp = [
        {"thought": "form", "action": "revise_hypotheses",
         "hypotheses": [{"id": "H1", "statement": "sync drains battery", "confidence": 0.5, "status": "active"}]},
        {"thought": "reviews", "action": "call_tool",
         "tool": {"name": "search_reviews", "args": {"query": "battery drain", "date_from": "2026-07-11", "rating_max": 2}, "tests_hypothesis": "H1"}},
        {"evidence": [{"ref": ref_r, "snippet": "drain", "supports": ["H1"], "contradicts": []}],
         "hypothesis_updates": [{"id": "H1", "new_confidence": 0.6, "based_on_refs": [ref_r], "note": "x"}]},
        {"thought": "github", "action": "call_tool",
         "tool": {"name": "search_github_issues", "args": {"query": "background sync battery wakelock"}, "tests_hypothesis": "H1"}},
        {"evidence": [{"ref": ref_g, "snippet": "wakelock", "supports": ["H1"], "contradicts": []}],
         "hypothesis_updates": [{"id": "H1", "new_confidence": 0.85, "based_on_refs": [ref_g], "note": "confirmed"}]},
        {"summary": "sync drives spike", "prose": "Caused by v3.2 sync [ev_001][ev_002].",
         "confidence": 0.85, "supported_hypothesis": "H1", "checked": ["play_store", "github"], "what_would_settle_it": ""},
    ]
    inv = Investigator(session, anomaly, llm=ScriptedLLM(resp)).run()
    assert inv.checkpoint_json is not None  # checkpoint was written each iteration
    return inv


def test_checkpoint_written_each_iteration(session):
    inv = _run_partial_then_orphan(session)
    assert "hypotheses" in inv.checkpoint_json
    assert inv.checkpoint_json["budget"]["iterations"] >= 1


def test_resume_running_recovers_orphan(session):
    inv = _run_partial_then_orphan(session)
    # simulate a crash mid-run: mark it running again with its checkpoint intact
    inv.status = "running"
    session.flush()
    acted = resume_running(session, llm=ScriptedLLM([
        {"thought": "already have two-source support; concluding.", "action": "conclude",
         "conclusion": {"status": "resolved", "reason": "H1 supported", "supported_hypothesis": "H1"}},
        {"summary": "resumed + resolved", "prose": "v3.2 sync caused it [ev_001][ev_002].",
         "confidence": 0.85, "supported_hypothesis": "H1", "checked": ["play_store", "github"], "what_would_settle_it": ""},
    ]))
    assert inv.id in acted
    session.refresh(inv)
    assert inv.status != "running"  # recovery drove it to a terminal state
    # a "Resumed after interruption" THINK step was recorded
    thinks = session.query(TraceStep).filter_by(investigation_id=inv.id, kind="THINK").all()
    assert any("Resumed" in t.content_json.get("text", "") for t in thinks)


def test_orphan_without_checkpoint_closed_honestly(session):
    anomaly = session.query(AnomalyEvent).filter_by(slug="demo2").one()
    inv = Investigation(anomaly_id=anomaly.id, status="running", budget_tier="standard",
                        budget_json={}, checkpoint_json=None)
    session.add(inv)
    session.flush()
    resume_running(session, llm=ScriptedLLM([]))
    session.refresh(inv)
    assert inv.status == "needs_human"  # no checkpoint → closed, not left orphaned


def test_provider_503_during_final_draft_keeps_an_honest_finding(session):
    class FinalDraftUnavailable:
        def complete_json(self, _system, _user, _schema, agent):
            if agent == "investigator.plan":
                return LLMResult(
                    parsed={"thought": "Nothing defensible remains.", "action": "conclude",
                            "conclusion": {"status": "insufficient_evidence",
                                           "reason": "No corroborated cause."}},
                    tokens_in=10, tokens_out=5, ms=1, model="unavailable-test",
                )
            raise LLMServiceError("upstream returned 503")

    anomaly = session.query(AnomalyEvent).filter_by(slug="demo2").one()
    inv = Investigator(session, anomaly, llm=FinalDraftUnavailable()).run()
    finding = session.query(Finding).filter_by(investigation_id=inv.id).one()

    assert inv.status == "insufficient_evidence"
    assert finding.summary == "Investigation ended: insufficient_evidence"
    assert "upstream returned 503" not in finding.json["prose"]


def test_startup_recovery_returns_immediately_while_resume_runs(monkeypatch):
    from echolens.api import app as app_mod
    from echolens.investigator import recover

    started = threading.Event()
    release = threading.Event()

    def slow_resume(_session):
        started.set()
        release.wait(timeout=2)
        return []

    @contextmanager
    def fake_scope():
        yield object()

    monkeypatch.setattr(recover, "resume_running", slow_resume)
    monkeypatch.setattr(app_mod, "session_scope", fake_scope)

    before = time.monotonic()
    thread = app_mod._start_recovery_bg()
    elapsed = time.monotonic() - before
    try:
        assert elapsed < 0.2
        assert started.wait(timeout=1)
        assert thread.is_alive()
    finally:
        release.set()
        thread.join(timeout=1)
