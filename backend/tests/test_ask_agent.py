from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from echolens import ask
from echolens.db.models import (AnomalyEvent, Base, Finding, Investigation,
                                Product, Review)
from echolens.eval.harness import ScriptedLLM

NOW = datetime(2026, 7, 20, tzinfo=timezone.utc)


@pytest.fixture()
def world():
    e = create_engine("sqlite://")
    Base.metadata.create_all(e)
    s = Session(e)
    p = Product(name="Lumo")
    s.add(p)
    s.flush()
    a = AnomalyEvent(slug="a1", type="volume_spike", metric="battery drain", delta=1.0,
                     z=3.0, window="7d", description="d", status="investigating",
                     product_id=p.id)
    s.add(a)
    s.flush()
    inv = Investigation(anomaly_id=a.id, status="resolved", budget_tier="standard",
                        product_id=p.id)
    s.add(inv)
    s.flush()
    s.add(Finding(investigation_id=inv.id, product_id=p.id, confidence=0.88,
                  status="approved",
                  summary="Battery drains from a wakelock in the 3.2 sync scheduler",
                  json={"summary": "Battery drains overnight",
                        "prose": "3.2 holds a wakelock."}))
    for i in range(12):
        s.add(Review(source="play_store", ext_id=f"r{i}", rating=1,
                     text="battery dies so fast", created_at=NOW - timedelta(days=i),
                     product="Lumo"))
    s.flush()
    yield s, p.id, inv.id
    s.close()


def test_a_paraphrase_reaches_the_right_finding(world):
    s, pid, inv_id = world
    llm = ScriptedLLM([{"action": "answer",
                        "answer": "It is a wakelock held by the 3.2 sync scheduler.",
                        "cites_cases": [inv_id], "confident": True}])
    r = ask.answer(s, "the app eats my charge", llm, product_id=pid, product_name="Lumo")
    assert [c["investigation_id"] for c in r.citations] == [inv_id]
    assert r.tool_calls == []


def test_it_queries_the_corpus_when_findings_do_not_cover_the_question(world):
    s, pid, _ = world
    llm = ScriptedLLM([
        {"action": "tool", "tool": {"name": "review_stats", "args": {"term": "battery"}}},
        {"action": "answer", "answer": "12 reviews mention battery.", "cites_cases": []},
    ])
    r = ask.answer(s, "how many people mention battery?", llm, product_id=pid,
                   product_name="Lumo")
    assert [t["name"] for t in r.tool_calls] == ["review_stats"]
    assert r.steps == 2


def test_a_citation_the_model_invents_is_dropped(world):
    s, pid, _ = world
    llm = ScriptedLLM([{"action": "answer", "answer": "See case #999.",
                        "cites_cases": [999], "confident": True}])
    r = ask.answer(s, "anything", llm, product_id=pid, product_name="Lumo")
    assert r.citations == []


def test_tool_calls_are_capped(world):
    s, pid, _ = world
    llm = ScriptedLLM([{"action": "tool",
                        "tool": {"name": "review_stats", "args": {"term": "battery"}}}] * 8)
    r = ask.answer(s, "loop forever", llm, product_id=pid, product_name="Lumo")
    assert len(r.tool_calls) <= ask.MAX_TOOL_CALLS
    assert r.steps <= ask.MAX_STEPS


def test_an_unknown_tool_does_not_crash_the_answer(world):
    s, pid, _ = world
    llm = ScriptedLLM([
        {"action": "tool", "tool": {"name": "drop_database", "args": {}}},
        {"action": "answer", "answer": "Recovered.", "cites_cases": []},
    ])
    r = ask.answer(s, "try a bad tool", llm, product_id=pid, product_name="Lumo")
    assert r.text == "Recovered."
    assert r.tool_calls == []


def test_a_failing_tool_is_reported_back_not_raised(world):
    s, pid, _ = world
    llm = ScriptedLLM([
        {"action": "tool", "tool": {"name": "review_stats", "args": {}}},
        {"action": "answer", "answer": "Could not measure that.", "cites_cases": []},
    ])
    r = ask.answer(s, "bad args", llm, product_id=pid, product_name="Lumo")
    assert r.text == "Could not measure that."


def test_a_model_that_never_answers_degrades_honestly(world):
    s, pid, _ = world
    r = ask.answer(s, "anything", ScriptedLLM([]), product_id=pid, product_name="Lumo")
    assert r.confident is False
    assert "couldn't work that out" in r.text


def test_findings_from_another_product_are_never_offered(world):
    s, pid, _ = world
    other = Product(name="Other")
    s.add(other)
    s.flush()
    a = AnomalyEvent(slug="o1", type="volume_spike", metric="x", delta=1.0, z=3.0,
                     window="7d", description="d", status="investigating",
                     product_id=other.id)
    s.add(a)
    s.flush()
    inv = Investigation(anomaly_id=a.id, status="resolved", budget_tier="standard",
                        product_id=other.id)
    s.add(inv)
    s.flush()
    s.add(Finding(investigation_id=inv.id, product_id=other.id, confidence=0.9,
                  status="approved", summary="secret from another product", json={}))
    s.flush()

    block = ask._findings_block(ask._knowledge(s, pid))
    assert "secret from another product" not in block


def test_best_existing_answer_finds_a_solved_case(world):
    s, pid, inv_id = world
    hit = ask.best_existing_answer(s, "battery drain", product_id=pid)
    assert hit is not None and hit[1].id == inv_id
    assert ask.best_existing_answer(s, "checkout payments", product_id=pid) is None
