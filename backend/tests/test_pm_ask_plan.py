"""Ask and Plan, PM-facing: streamed progress, answer provenance, a next step
instead of a dead end, editable Plan estimates and a manual priority segment."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from echolens import ask, backlog, chat
from echolens.config import settings
from echolens.db import session as db_session
from echolens.db.models import (AnomalyEvent, Base, EvidenceRow, Finding, Investigation,
                                Product, Review)
from echolens.eval.harness import ScriptedLLM

NOW = datetime.now(timezone.utc)


def _case(s, pid, summary, *, slug, volume=40, age_days=20, conf=0.85):
    a = AnomalyEvent(slug=slug, type="theme_volume_surge", metric=summary, delta=0.3, z=3.0,
                     window="7d", description=summary, status="closed", product_id=pid)
    s.add(a); s.flush()
    inv = Investigation(anomaly_id=a.id, status="resolved", opened_by="anomaly",
                        budget_tier="standard", budget_json={}, product_id=pid,
                        created_at=NOW - timedelta(days=age_days))
    s.add(inv); s.flush()
    s.add(Finding(investigation_id=inv.id, summary=summary, confidence=conf,
                  status="approved", product_id=pid,
                  json={"summary": summary, "prose": f"{summary} confirmed.",
                        "impact": {"impact_score": 0.5, "affected_pct": 30.0,
                                   "affected_volume": volume, "rating_impact": 0.3}}))
    s.add(EvidenceRow(investigation_id=inv.id, eid="ev_000", source="play_store",
                      ref=f"{slug}-r0", snippet="…", retrieved_by="search_reviews", json={}))
    s.flush()
    return inv


@pytest.fixture()
def world(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as s:
        p = Product(name="Lumo"); s.add(p); s.flush()
        battery = _case(s, p.id, "Battery drains from background sync", slug="c1", volume=40)
        crash = _case(s, p.id, "Export crashes on large files", slug="c2", volume=10)
        # a detected, never-investigated signal
        s.add(AnomalyEvent(slug="sig1", type="manual", metric="paywall complaints",
                           delta=0.4, z=3.1, window="7d",
                           description="Paywall shown to subscribed users",
                           status="pending", product_id=p.id))
        for i in range(6):
            s.add(Review(source="play_store", ext_id=f"r{i}", rating=1,
                         text="paywall again after paying", created_at=NOW - timedelta(days=i),
                         product="Lumo"))
        s.commit()
        ids = {"pid": p.id, "battery": battery.id, "crash": crash.id}
    monkeypatch.setattr(db_session, "_engine", engine)
    monkeypatch.setattr(db_session, "_SessionLocal", Session)
    monkeypatch.setattr(db_session, "get_engine", lambda db_url=None: engine)
    import echolens.api.app as app_mod
    monkeypatch.setattr(app_mod, "_run_investigation_bg", lambda *a, **k: None)
    app_mod.limiter.reset()
    return TestClient(app_mod.app), ids, Session, app_mod


def _sse(text: str) -> list[tuple[str, dict]]:
    out = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def _scripted(monkeypatch, app_mod, script):
    """Let the real Ask agent run against a scripted model, no API key."""
    monkeypatch.setattr(settings, "openai_api_key", "test-key", raising=False)
    monkeypatch.setattr(app_mod, "_metered_llm",
                        lambda session, prefix, product_id=None: ScriptedLLM(list(script)))


# ── 19: provenance ──────────────────────────────────────────────────────

def test_an_investigated_topic_is_labelled_with_its_case(world):
    tc, ids, _, _ = world
    r = tc.post("/chat", json={"message": "tell me about battery drain",
                               "product_id": ids["pid"]}).json()
    assert r["basis"]["kind"] == "investigation"
    assert r["basis"]["case_id"] == ids["battery"]
    assert r["basis"]["label"] == f"From verified investigation (case #{ids['battery']})"
    assert r["next_step"] is None          # backed by a case: no dead end to fix


def test_a_waiting_signal_is_labelled_as_not_investigated(world):
    tc, ids, _, _ = world
    r = tc.post("/chat", json={"message": "what about the paywall?",
                               "product_id": ids["pid"]}).json()
    assert r["basis"]["kind"] == "signals"
    assert r["basis"]["label"] == "From waiting signals (not investigated)"
    assert r["basis"]["caution"]
    assert "Paywall shown to subscribed users" in r["text"]


def test_a_raw_search_answer_carries_a_caution(world, monkeypatch):
    tc, ids, _, app_mod = world
    _scripted(monkeypatch, app_mod, [
        {"action": "tool", "tool": {"name": "review_stats", "args": {"term": "refund"},
                                    "why": "count refund mentions"}},
        {"action": "answer", "answer": "A handful of reviews mention refunds.",
         "cites_cases": [], "confident": True},
    ])
    r = tc.post("/chat", json={"message": "do people want refunds?",
                               "product_id": ids["pid"]}).json()
    assert r["basis"]["kind"] == "raw_search"
    assert r["basis"]["label"] == "From raw feedback search (not investigated)"
    assert r["basis"]["caution"] == chat.RAW_CAUTION
    assert r["next_step"]["kind"] == "investigate"


def test_every_chat_answer_has_a_basis(world):
    tc, ids, _, _ = world
    for q in ("hello there", "what is the biggest problem?", "tell me about export crashes"):
        r = tc.post("/chat", json={"message": q, "product_id": ids["pid"]}).json()
        assert r.get("basis") and r["basis"]["label"], q


# ── 20: next step instead of a dead end ─────────────────────────────────

def test_an_uninvestigated_topic_offers_to_start_an_investigation(world):
    tc, ids, _, _ = world
    r = tc.post("/chat", json={"message": "tell me about dark mode",
                               "product_id": ids["pid"]}).json()
    assert r["basis"]["kind"] == "none"
    assert r["next_step"] == {"kind": "investigate", "question": "tell me about dark mode",
                              "allowed": True, "reason": None}


def test_viewers_and_guests_are_told_why_they_cannot_start_one(world):
    _, _, _, app_mod = world
    resp = {"type": "answer", "basis": chat.basis_none()}
    viewer = app_mod._chat_next_step(resp, {"role": "viewer"}, "dark mode")
    guest = app_mod._chat_next_step(resp, {"role": "viewer", "guest": True}, "dark mode")
    assert viewer["allowed"] is False and "reviewer access" in viewer["reason"]
    assert guest["allowed"] is False and "Guests" in guest["reason"]


def test_force_investigate_launches_even_for_a_topic_question(world):
    """The card's launch used to be ignored unless the router already wanted to
    launch, so it re-answered the question instead of opening a case."""
    tc, ids, Session, _ = world
    r = tc.post("/chat", json={"message": "tell me about battery drain",
                               "product_id": ids["pid"], "force_investigate": True}).json()
    assert r["type"] == "investigation" and r["investigation_id"]
    assert r["basis"]["kind"] == "investigation_started"
    # two launches in one second must not collide on the unique slug
    r2 = tc.post("/chat", json={"message": "tell me about battery drain",
                                "product_id": ids["pid"], "force_investigate": True}).json()
    assert r2["investigation_id"] != r["investigation_id"]


def test_a_guest_never_spends_on_ask(world, monkeypatch):
    _, ids, Session, app_mod = world
    monkeypatch.setattr(settings, "openai_api_key", "test-key", raising=False)

    def boom(*a, **k):
        raise AssertionError("a guest must not build an LLM client")
    monkeypatch.setattr(app_mod, "_metered_llm", boom)
    with Session() as s:
        assert app_mod._chat_ask_llm(s, {"role": "viewer", "guest": True},
                                     "refunds?", ids["pid"], "Lumo") is None


# ── 18: streamed progress ───────────────────────────────────────────────

def test_stream_emits_steps_then_the_same_answer(world, monkeypatch):
    tc, ids, _, app_mod = world
    script = [
        {"action": "tool", "tool": {"name": "search_reviews", "args": {"query": "paywall"},
                                    "why": "see what people say"}},
        {"action": "tool", "tool": {"name": "compare_cohorts",
                                    "args": {"term": "paywall", "dimension": "version"}}},
        {"action": "answer", "answer": "Paywall complaints cluster on recent versions.",
         "cites_cases": [], "confident": True},
    ]
    _scripted(monkeypatch, app_mod, script)
    r = tc.post("/chat/stream", json={"message": "how do people feel about pricing lately?",
                                      "product_id": ids["pid"]})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = _sse(r.text)
    kinds = [e for e, _ in events]
    assert kinds[-2:] == ["answer", "done"]
    steps = [p for e, p in events if e == "step"]
    texts = [s["text"] for s in steps]
    assert "Searching reviews for 'paywall'…" in texts
    assert "Comparing versions for 'paywall'…" in texts
    tool_step = next(s for s in steps if s.get("tool") == "search_reviews")
    assert tool_step["why"] == "see what people say"
    answer = events[-2][1]
    assert answer["basis"]["kind"] == "raw_search"
    assert answer["text"] == "Paywall complaints cluster on recent versions."


def test_stream_of_a_grounded_answer_spends_nothing(world, monkeypatch):
    tc, ids, _, app_mod = world
    monkeypatch.setattr(settings, "openai_api_key", "test-key", raising=False)

    def boom(*a, **k):
        raise AssertionError("a cited answer must not call the model")
    monkeypatch.setattr(app_mod, "_metered_llm", boom)
    events = _sse(tc.post("/chat/stream", json={"message": "tell me about battery drain",
                                                "product_id": ids["pid"]}).text)
    answer = next(p for e, p in events if e == "answer")
    assert answer["basis"]["case_id"] == ids["battery"]


def test_stream_unknown_product_is_a_real_404(world):
    tc, _, _, _ = world
    assert tc.post("/chat/stream", json={"message": "x", "product_id": 9999}).status_code == 404


def test_stream_route_is_rate_limited():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1] / "echolens" / "api" / "app.py"
           ).read_text(encoding="utf-8")
    i = src.index('"/chat/stream"')
    assert "@limiter.limit" in src[i:i + 200]


def test_describe_tool_is_human_and_never_crashes():
    assert ask.describe_tool("search_reviews", {"query": "paywall"}) == \
        "Searching reviews for 'paywall'…"
    assert ask.describe_tool("compare_cohorts", {"term": "x", "dimension": "os"}) == \
        "Comparing OS versions for 'x'…"
    assert ask.describe_tool("search_reviews", {}) == "Searching reviews…"
    assert ask.describe_tool("mystery", {}) == "Running mystery…"


# ── 21 + 22: editable Plan estimates and priority segment ───────────────

def _items(plan):
    return {i["investigation_id"]: i for i in plan["proposed"] + plan["deferred"]}


def test_effort_override_rerank_and_is_marked(world):
    tc, ids, _, _ = world
    before = _items(tc.get(f"/backlog/plan?product_id={ids['pid']}").json())
    assert before[ids["battery"]]["rank"] < before[ids["crash"]]["rank"]
    assert before[ids["crash"]]["effort"]["overridden"] is False

    plan = tc.put("/backlog/plan", json={
        "product_id": ids["pid"], "included": [], "excluded": [],
        "overrides": {str(ids["crash"]): {"effort_days": 0.5}}}).json()
    after = _items(plan)
    crash = after[ids["crash"]]
    assert crash["effort"] == {"days": 0.5, "basis": "set by you", "known": True,
                               "overridden": True, "estimated": crash["effort"]["estimated"]}
    assert crash["effort"]["estimated"]["basis"] == "no effort signal yet"
    assert "set by you" in crash["defence"]
    assert plan["overrides"] == {str(ids["crash"]): {"effort_days": 0.5}}


def test_impact_override_scales_value_by_the_documented_factor(world):
    tc, ids, _, _ = world
    base = _items(tc.get(f"/backlog/plan?product_id={ids['pid']}").json())[ids["battery"]]
    default = base["impact"]["default"]
    plan = tc.put("/backlog/plan", json={
        "product_id": ids["pid"], "included": [], "excluded": [],
        "overrides": {str(ids["battery"]): {"impact": 5}}}).json()
    item = _items(plan)[ids["battery"]]
    factor = backlog.IMPACT_FACTOR[5] / backlog.IMPACT_FACTOR[default]
    assert item["impact"] == {"level": 5, "default": default, "overridden": True,
                              "factor": round(factor, 3)}
    assert item["value_per_day"] == pytest.approx(base["value_per_day"] * factor, rel=0.02)


def test_priority_segment_multiplies_value_and_is_persisted(world):
    tc, ids, _, _ = world
    base = _items(tc.get(f"/backlog/plan?product_id={ids['pid']}").json())[ids["crash"]]
    plan = tc.put("/backlog/plan", json={
        "product_id": ids["pid"], "included": [], "excluded": [],
        "overrides": {str(ids["crash"]): {"segment": "paying_users"}}}).json()
    item = _items(plan)[ids["crash"]]
    assert item["segment"]["label"] == "Affects paying users"
    assert item["segment"]["factor"] == 2.0 and item["segment"]["why"]
    assert item["value_per_day"] == pytest.approx(base["value_per_day"] * 2, rel=0.02)
    assert {s["key"] for s in plan["segments"]} == set(backlog.PRIORITY_SEGMENTS)
    # it survives a fresh read
    again = _items(tc.get(f"/backlog/plan?product_id={ids['pid']}").json())[ids["crash"]]
    assert again["segment"]["key"] == "paying_users"


def test_a_plain_save_preserves_overrides_and_an_empty_dict_clears_them(world):
    tc, ids, _, _ = world
    key = str(ids["crash"])
    tc.put("/backlog/plan", json={"product_id": ids["pid"], "included": [], "excluded": [],
                                  "overrides": {key: {"effort_days": 3, "segment": "checkout_onboarding"}}})
    # Drop/Add and capacity saves send no overrides — they must not wipe them.
    plan = tc.put("/backlog/plan", json={"product_id": ids["pid"], "included": [],
                                         "excluded": [ids["battery"]], "capacity_days": 15}).json()
    assert plan["overrides"] == {key: {"effort_days": 3.0, "segment": "checkout_onboarding"}}
    plan = tc.put("/backlog/plan", json={"product_id": ids["pid"], "included": [],
                                         "excluded": [], "overrides": {}}).json()
    assert plan["overrides"] == {}
    assert _items(plan)[ids["crash"]]["segment"] is None


def test_invalid_overrides_are_refused_or_dropped(world):
    tc, ids, _, _ = world
    base = {"product_id": ids["pid"], "included": [], "excluded": []}
    assert tc.put("/backlog/plan", json={**base, "overrides": {
        str(ids["crash"]): {"segment": "whales"}}}).status_code == 422
    assert tc.put("/backlog/plan", json={**base, "overrides": {
        str(ids["crash"]): {"impact": 9}}}).status_code == 422
    assert tc.put("/backlog/plan", json={**base, "overrides": {
        str(ids["crash"]): {"effort_days": -2}}}).status_code == 422
    # the module-level cleaner drops junk that bypasses the API
    assert backlog.clean_overrides({"x": {"impact": 3}, "7": {"impact": 0, "segment": "?"},
                                    "8": {"effort_days": 2}}) == {"8": {"effort_days": 2.0}}


def test_overridden_effort_counts_against_capacity(world):
    tc, ids, _, _ = world
    plan = tc.put("/backlog/plan", json={
        "product_id": ids["pid"], "included": [], "excluded": [], "capacity_days": 10,
        "overrides": {str(ids["battery"]): {"effort_days": 9},
                      str(ids["crash"]): {"effort_days": 4}}}).json()
    assert [i["investigation_id"] for i in plan["proposed"]] == [ids["battery"]]
    assert plan["committed_days"] == 9.0
