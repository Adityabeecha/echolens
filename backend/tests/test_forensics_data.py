"""Forensics data: the temporal-order guard, per-case guard results, guard
stats/config, causal chain, complaint timeline, live cases and citations."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from echolens.db.models import (
    AnomalyEvent, EvidenceRow, Finding, HypothesisRow, Investigation, LLMCall, Product,
    QueuedInvestigation, Release, Review, TraceStep)
from echolens.forensics import (
    causal_chain, citations, guard_config, guard_results, guard_stats, live_investigations,
    release_markers, timeline)
from echolens.investigator import guards

# ── 1. temporal-order guard (pure) ──────────────────────────────────────


def _ev(eid, source, **meta):
    return {"id": eid, "source": source, "ref": eid, "snippet": "", "meta": meta}


def test_release_after_first_complaint_is_a_violation():
    h = {"id": "H1", "statement": "v3.2 sync drains battery", "evidence_for": ["ev_001", "ev_002"]}
    ev = [_ev("ev_001", "play_store", date="2026-07-01"),
          _ev("ev_002", "release_notes", version="3.2.0", released_at="2026-07-08")]
    hit = guards.temporal_order_violation(h, ev)
    assert hit == {"release": "3.2.0", "release_date": "2026-07-08",
                   "first_complaint": "2026-07-01", "complaint_id": "ev_001"}


def test_release_before_first_complaint_passes():
    h = {"id": "H1", "statement": "v3.2 sync drains battery", "evidence_for": ["ev_001", "ev_002"]}
    ev = [_ev("ev_001", "play_store", date="2026-07-11"),
          _ev("ev_002", "release_notes", version="3.2.0", released_at="2026-07-08")]
    assert guards.temporal_order_violation(h, ev) is None


def test_named_version_is_dated_from_the_release_table():
    h = {"id": "H1", "statement": "Release 3.2 broke sync", "evidence_for": ["ev_001"]}
    ev = [_ev("ev_001", "play_store", date="2026-07-01")]
    assert guards.temporal_order_violation(h, ev, {"3.2.0": "2026-07-08"})["release"] == "3.2.0"
    assert guards.temporal_order_violation(h, ev, {"3.2.0": "2026-06-20"}) is None


def test_citing_an_older_release_does_not_excuse_the_named_one():
    h = {"id": "H1", "statement": "v3.2.0 broke sync", "evidence_for": ["ev_001", "ev_002"]}
    ev = [_ev("ev_001", "play_store", date="2026-07-01"),
          _ev("ev_002", "release_notes", version="3.1.0", released_at="2026-04-20")]
    hit = guards.temporal_order_violation(h, ev, {"3.2.0": "2026-07-08", "3.1.0": "2026-04-20"})
    assert hit and hit["release"] == "3.2.0"


def test_undated_or_release_free_hypotheses_are_never_guessed_at():
    h = {"id": "H1", "statement": "Server outage", "evidence_for": ["ev_001"]}
    assert guards.temporal_order_violation(h, [_ev("ev_001", "play_store", date="2026-07-01")]) is None
    h2 = {"id": "H2", "statement": "v3.2 broke sync", "evidence_for": ["ev_001"]}
    assert guards.temporal_order_violation(h2, [_ev("ev_001", "play_store")], {"3.2.0": "2026-07-08"}) is None


# ── 1b. the guard in the real loop (ScriptedLLM) ────────────────────────

def _script(review_args):
    from echolens.eval.harness import scope_of
    from echolens.tools.search_github_issues import search_github_issues
    from echolens.tools.search_reviews import search_reviews

    def build(s):
        scope = scope_of(s)
        ref_r = search_reviews(s, product=scope, **review_args)["reviews"][0]["ref"]
        ref_g = search_github_issues(s, "background sync battery wakelock", product=scope)["issues"][0]["ref"]
        return [
            {"thought": "Spike after v3.2.", "action": "revise_hypotheses",
             "hypotheses": [{"id": "H1", "statement": "v3.2 background sync causes battery drain",
                             "confidence": 0.5, "status": "active"}]},
            {"thought": "Read complaints.", "action": "call_tool",
             "tool": {"name": "search_reviews", "args": review_args, "tests_hypothesis": "H1"}},
            {"evidence": [{"ref": ref_r, "snippet": "battery drain", "supports": ["H1"], "contradicts": []}],
             "hypothesis_updates": [{"id": "H1", "new_confidence": 0.65, "based_on_refs": [ref_r], "note": ""}]},
            {"thought": "Corroborate.", "action": "call_tool",
             "tool": {"name": "search_github_issues", "args": {"query": "background sync battery wakelock"},
                      "tests_hypothesis": "H1"}},
            {"evidence": [{"ref": ref_g, "snippet": "wakelock never released", "supports": ["H1"], "contradicts": []}],
             "hypothesis_updates": [{"id": "H1", "new_confidence": 0.85, "new_status": "supported",
                                     "based_on_refs": [ref_g], "note": "mechanism"}]},
            {"summary": "Background sync in v3.2 drives the battery spike",
             "prose": "Battery complaints are caused by the v3.2 background sync [ev_001][ev_002].",
             "confidence": 0.85, "supported_hypothesis": "H1", "checked": ["play_store", "github"],
             "what_would_settle_it": ""},
        ]
    return build


def _run(review_args):
    from echolens.eval.harness import ScriptedLLM, fresh_session
    from echolens.investigator.graph import Investigator
    s = fresh_session()
    anomaly = s.scalars(select(AnomalyEvent).where(AnomalyEvent.slug == "demo1")).first()
    inv = Investigator(s, anomaly, llm=ScriptedLLM(_script(review_args)(s)), tier="quick").run()
    return s, inv


def test_loop_refuses_a_release_that_shipped_after_the_complaints():
    # Complaints from January cannot have been caused by July's v3.2.
    s, inv = _run({"query": "battery", "date_to": "2026-02-01", "rating_max": 2})
    h1 = s.scalars(select(HypothesisRow).where(HypothesisRow.investigation_id == inv.id,
                                               HypothesisRow.hid == "H1")).one()
    assert h1.status != "supported"
    assert inv.status != "resolved"
    refutes = [t.content_json for t in s.scalars(select(TraceStep).where(
        TraceStep.investigation_id == inv.id, TraceStep.kind == "REFUTE")).all()
        if t.content_json.get("guard") == "temporal_order"]
    assert refutes and refutes[0]["release_date"] == "2026-07-08"
    assert refutes[0]["first_complaint"] < "2026-07-08"
    assert "2026-07-08" in refutes[0]["text"] and refutes[0]["first_complaint"] in refutes[0]["text"]


def test_loop_allows_a_release_that_shipped_before_the_complaints():
    s, inv = _run({"query": "battery drain", "date_from": "2026-07-11", "rating_max": 2})
    h1 = s.scalars(select(HypothesisRow).where(HypothesisRow.investigation_id == inv.id,
                                               HypothesisRow.hid == "H1")).one()
    assert inv.status == "resolved" and h1.status == "supported"
    assert not [t for t in s.scalars(select(TraceStep).where(
        TraceStep.investigation_id == inv.id, TraceStep.kind == "REFUTE")).all()
        if t.content_json.get("guard") == "temporal_order"]


# ── 2. guard results per case ───────────────────────────────────────────

def _by_key(results):
    return {g["key"]: g for g in results}


def test_guard_results_cover_every_guard_in_order():
    keys = [g["key"] for g in guard_results([], None, [])]
    assert keys == ["citation", "two_source", "single_source_cap", "temporal_order", "speculation"]
    assert all(g["status"] == "not_applicable" for g in guard_results([], None, []))


def test_guard_results_read_what_the_case_stored():
    hyps = [{"id": "H1", "statement": "s", "confidence": 0.9, "status": "supported",
             "evidence_for": ["ev_001", "ev_002"]},
            {"id": "H2", "statement": "t", "confidence": 0.75, "status": "active", "evidence_for": []}]
    finding = {"prose": "x [ev_001].", "working_hypotheses": ["Maybe the CDN caused it."]}
    steps = [("FAIL", {"error": "ref not present in tool result"}),
             ("REFUTE", {"guard": "temporal_order", "hypothesis": "H3", "release": "3.2.0",
                         "release_date": "2026-07-08", "first_complaint": "2026-07-01"})]
    g = _by_key(guard_results(hyps, finding, steps))
    assert g["citation"]["status"] == "stripped"
    assert g["two_source"]["status"] == "pass"
    assert g["single_source_cap"]["status"] == "capped" and "H2" in g["single_source_cap"]["detail"]
    assert g["temporal_order"]["status"] == "blocked" and "2026-07-01" in g["temporal_order"]["detail"]
    assert g["speculation"]["status"] == "stripped"
    assert set(g["citation"]) == {"key", "label", "status", "detail"}


def test_blocked_grounding_and_refused_resolution():
    hyps = [{"id": "H1", "statement": "s", "confidence": 0.6, "status": "active", "evidence_for": []}]
    finding = {"grounding_violations": ["It was caused by the CDN."]}
    steps = [("CHECK", {"text": "Declared resolution REJECTED by guard: no hypothesis meets …"})]
    g = _by_key(guard_results(hyps, finding, steps))
    assert g["citation"]["status"] == "blocked"
    assert g["two_source"]["status"] == "blocked"


def test_single_channel_case_is_capped_not_two_source():
    hyps = [{"id": "H1", "statement": "s", "confidence": 0.75,
             "status": guards.SINGLE_CHANNEL_STATUS, "evidence_for": []}]
    g = _by_key(guard_results(hyps, {"prose": "x"}, []))
    assert g["two_source"]["status"] == "not_applicable"
    assert g["single_source_cap"]["status"] == "capped"


def test_investigation_payload_carries_guards_and_causal_chain():
    from echolens.api.app import _investigation_dict
    s, inv = _run({"query": "battery drain", "date_from": "2026-07-11", "rating_max": 2})
    d = _investigation_dict(s, inv)
    assert [g["key"] for g in d["guards"]][0] == "citation"
    assert _by_key(d["guards"])["temporal_order"]["status"] == "pass"
    chain = d["finding"]["causal_chain"]
    assert chain["mechanism"]["text"] == "v3.2 background sync causes battery drain"
    assert chain["trigger"]["evidence_ids"] == ["ev_002"]      # the GitHub issue
    assert chain["symptom"]["evidence_ids"] == ["ev_001"]      # the review


# ── 3. guard stats + config ─────────────────────────────────────────────

def test_guard_config_is_the_constants_in_force():
    cfg = guard_config()
    assert cfg["single_source_cap"] == 0.75 and cfg["temporal_order"] is True
    assert cfg["two_source"]["min_sources"] == 2


def test_guard_stats_count_interventions_per_window(session):
    now = datetime(2026, 10, 25, tzinfo=timezone.utc)
    pid = session.scalars(select(Product.id)).first()

    def case_(days_ago, finding_json, steps=()):
        inv = Investigation(status="needs_human", product_id=pid,
                            created_at=(now - timedelta(days=days_ago)).replace(tzinfo=None))
        session.add(inv)
        session.flush()
        session.add(Finding(investigation_id=inv.id, summary="s", confidence=0.5,
                            json=finding_json, product_id=pid))
        for i, (kind, content) in enumerate(steps):
            session.add(TraceStep(investigation_id=inv.id, seq=i + 1, kind=kind, content_json=content))
        session.flush()

    case_(5, {"working_hypotheses": ["x"]})
    case_(60, {"grounding_violations": ["y"]})
    case_(200, {"working_hypotheses": ["z"]})       # outside 90 days
    case_(10, {"prose": "fine"})
    stats = guard_stats(session, pid, now)
    g = {x["key"]: x["interventions"] for x in stats["guards"]}
    assert g["speculation"] == {"d30": 1, "d90": 1}
    assert g["citation"] == {"d30": 0, "d90": 1}
    assert stats["cases_checked"]["d90"] >= 3 and stats["cases_checked"]["d30"] >= 2


# ── 4. causal chain ─────────────────────────────────────────────────────

def test_causal_chain_is_null_unless_supported():
    hyps = [{"id": "H1", "statement": "s", "confidence": 0.6, "status": "active", "evidence_for": []}]
    assert causal_chain({"supported_hypothesis": "H1"}, hyps, []) is None
    assert causal_chain({"supported_hypothesis": None}, hyps, []) is None


def test_causal_chain_quotes_only_what_the_case_holds():
    hyps = [{"id": "H1", "statement": "Sync worker holds a wakelock", "confidence": 0.9,
             "status": "supported", "evidence_for": ["ev_001", "ev_002", "ev_003"]}]
    ev = [{"id": "ev_001", "source": "play_store", "snippet": "battery dies overnight"},
          {"id": "ev_002", "source": "release_notes", "snippet": "3.2: new background sync"},
          {"id": "ev_003", "source": "play_store", "snippet": "phone hot since update"}]
    finding = {"supported_hypothesis": "H1", "prose": "Hot phones [ev_003][ev_002]. Heat [ev_003].",
               "impact": {"measured": True, "affected_volume": 12, "affected_pct": 30.0,
                          "rating_impact": 0.4}}
    chain = causal_chain(finding, hyps, ev)
    assert chain["trigger"] == {"text": "3.2: new background sync", "evidence_ids": ["ev_002"]}
    assert chain["mechanism"]["evidence_ids"] == ["ev_001", "ev_002", "ev_003"]
    assert chain["symptom"] == {"text": "phone hot since update", "evidence_ids": ["ev_003"]}
    assert chain["impact"]["affected_pct"] == 30.0 and "0.40" in chain["impact"]["text"]
    finding["impact"] = {"measured": False}
    assert causal_chain(finding, hyps, ev)["impact"] is None


# ── 5. complaint timeline ───────────────────────────────────────────────

@pytest.fixture()
def bare():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from echolens.db.models import Base
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    with sessionmaker(bind=eng, expire_on_commit=False)() as s:
        yield s


def _review(s, i, day, rating, text="ok", product="P"):
    s.add(Review(ext_id=f"r{i}", rating=rating, text=text, product=product,
                 created_at=datetime(2026, 7, day, 12)))


def test_timeline_series_is_zero_filled_and_counted(bare):
    _review(bare, 1, 10, 1, "battery dies")
    _review(bare, 2, 10, 2, "slow")
    _review(bare, 3, 10, 5)
    _review(bare, 4, 12, 1, "Battery drain")
    _review(bare, 5, 12, 1, "x", product="Other")
    bare.flush()
    end = datetime(2026, 7, 12, 23, tzinfo=timezone.utc)
    t = timeline(bare, "P", days=3, end=end, theme_terms=["battery"])
    assert [d["date"] for d in t["series"]] == ["2026-07-10", "2026-07-11", "2026-07-12"]
    assert t["series"][0] == {"date": "2026-07-10", "negative": 2, "one_star": 1, "total": 3}
    assert t["series"][1]["total"] == 0
    assert t["series"][2] == {"date": "2026-07-12", "negative": 1, "one_star": 1, "total": 1}
    assert [d["total"] for d in t["theme"]["series"]] == [1, 0, 1]


def test_release_markers_flag_quick_patch_bumps_as_hotfixes(bare):
    for v, d in [("3.1.0", datetime(2026, 6, 20)), ("3.2.0", datetime(2026, 7, 1)),
                 ("3.2.1", datetime(2026, 7, 6)), ("3.2.2", datetime(2026, 7, 30)),
                 ("4.0.0", datetime(2026, 8, 2))]:
        bare.add(Release(version=v, notes="", released_at=d, product="P"))
    bare.add(Release(version="9.9.9", notes="", released_at=datetime(2026, 7, 7), product="Other"))
    bare.flush()
    marks = release_markers(bare, "P", datetime(2026, 7, 1, tzinfo=timezone.utc),
                            datetime(2026, 8, 5, tzinfo=timezone.utc))
    assert marks == [
        {"version": "3.2.0", "date": "2026-07-01", "kind": "release"},
        {"version": "3.2.1", "date": "2026-07-06", "kind": "hotfix"},
        {"version": "3.2.2", "date": "2026-07-30", "kind": "release"},   # 24 days on
        {"version": "4.0.0", "date": "2026-08-02", "kind": "release"},
    ]


# ── 6. live investigations ──────────────────────────────────────────────

def test_live_investigations_report_progress_and_cost(bare):
    now = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
    inv = Investigation(status="running", product_id=1, created_at=datetime(2026, 10, 25, 11, 58))
    done = Investigation(status="resolved", product_id=1)
    other = Investigation(status="running", product_id=2)
    bare.add_all([inv, done, other])
    bare.flush()
    bare.add_all([
        TraceStep(investigation_id=inv.id, seq=1, kind="THINK", content_json={"text": "plan"}),
        TraceStep(investigation_id=inv.id, seq=2, kind="TOOL", content_json={"code": "x" * 300}),
        LLMCall(investigation_id=inv.id, agent="a", cost=0.01),
        LLMCall(investigation_id=inv.id, agent="a", cost=0.0025),
        QueuedInvestigation(product_id=1, title="Login loop", status="queued"),
        QueuedInvestigation(product_id=1, title="claimed", status="running", investigation_id=inv.id),
    ])
    bare.flush()
    rows = live_investigations(bare, 1, now)
    running = [r for r in rows if r["status"] == "running"]
    assert [r["id"] for r in running] == [inv.id]
    r = running[0]
    assert r["elapsed_s"] == 120 and r["step_count"] == 2
    assert r["current_step"]["kind"] == "TOOL" and len(r["current_step"]["text"]) == 140
    assert r["cost_usd_so_far"] == 0.0125 and r["title"] == "claimed"
    queued = [r for r in rows if r["status"] == "queued"]
    assert [q["title"] for q in queued] == ["Login loop"] and queued[0]["id"] is None


# ── 7. citation detail ──────────────────────────────────────────────────

def test_citations_map_both_ways(bare):
    inv = Investigation(status="resolved", product_id=1)
    bare.add(inv)
    bare.flush()
    _review(bare, 1, 10, 1, "Since 3.2 the Battery Dies Overnight, every night.")
    bare.add_all([
        EvidenceRow(investigation_id=inv.id, eid="ev_001", source="play_store", ref="r1",
                    snippet="the battery dies overnight", retrieved_by="t", json={"supports": ["H1"]}),
        EvidenceRow(investigation_id=inv.id, eid="ev_002", source="github", ref="issue acme/app#42",
                    snippet="wakelock", retrieved_by="t", json={}),
        HypothesisRow(investigation_id=inv.id, hid="H2", statement="s", confidence=0.5,
                      status="active", json={"evidence_for": ["ev_002"]}),
        Finding(investigation_id=inv.id, summary="s", confidence=0.9, json={
            "prose": 'Users say "battery dies overnight" [ev_001]. A wakelock leaks [ev_002][ev_001].'}),
    ])
    bare.flush()
    out = citations(bare, inv, "P")
    assert len(out["sentences"]) == 2
    c = {x["id"]: x for x in out["citations"]}
    assert c["ev_001"]["claim_spans"] == [0, 1] and c["ev_002"]["claim_spans"] == [1]
    assert c["ev_001"]["highlight"] == "Battery Dies Overnight"      # the review's own casing
    assert c["ev_001"]["supports"] == ["H1"] and c["ev_002"]["supports"] == ["H2"]
    assert c["ev_002"]["url"] == "https://github.com/acme/app/issues/42"
    assert c["ev_001"]["url"] is None and c["ev_002"]["highlight"] is None


# ── API: routes, scoping, guests ────────────────────────────────────────

def _client(monkeypatch):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    import echolens.db.session as db_session
    from echolens import auth
    from echolens.config import settings
    from echolens.db.models import Base

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as s:
        s.add_all([Product(name="Lumo (demo)", is_demo=True), Product(name="Secret", is_demo=False)])
        s.flush()
        s.add_all([Investigation(status="running", product_id=1),
                   Investigation(status="resolved", product_id=2)])
        tok = auth.create_token(auth.create_user(s, "admin@team.com", "pw", "admin"))
        s.commit()
    monkeypatch.setattr(db_session, "_engine", engine)
    monkeypatch.setattr(db_session, "_SessionLocal", Session)
    monkeypatch.setattr(db_session, "get_engine", lambda db_url=None: engine)
    monkeypatch.setattr(settings, "echolens_env", "staging")
    monkeypatch.setattr(settings, "allow_guest", True)
    monkeypatch.setattr(settings, "guest_demo_only", True)
    from echolens.api.app import app
    return TestClient(app, raise_server_exceptions=False), {"Authorization": f"Bearer {tok}"}


def test_routes_answer_and_live_is_not_an_id(monkeypatch):
    tc, admin = _client(monkeypatch)
    r = tc.get("/investigations/live?product_id=1")
    assert r.status_code == 200 and [x["id"] for x in r.json()["investigations"]] == [1]
    assert tc.get("/guards/config").json()["single_source_cap"] == 0.75
    assert tc.get("/guards/stats?product_id=1").status_code == 200
    t = tc.get("/timeline?product_id=1&days=7&investigation_id=1")
    assert t.status_code == 200 and len(t.json()["series"]) == 7 and "theme" in t.json()
    assert tc.get("/investigations/1/citations?product_id=1").json()["citations"] == []


def test_guests_only_see_demo_products(monkeypatch):
    tc, admin = _client(monkeypatch)
    for url in ("/investigations/live?product_id=2", "/guards/stats?product_id=2",
                "/timeline?product_id=2", "/investigations/2/citations?product_id=2",
                "/timeline?product_id=1&investigation_id=2"):
        assert tc.get(url).status_code == 404, url
    assert tc.get("/guards/stats?product_id=2", headers=admin).status_code == 200
    assert tc.get("/investigations/2/citations?product_id=2", headers=admin).status_code == 200
