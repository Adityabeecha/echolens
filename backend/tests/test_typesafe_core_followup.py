"""Reproductions for concrete defects behind the TypeSafe core flags."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from echolens.db.models import Base, Finding, Investigation, KnowledgeEdge, Product, Review, Release


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _case(db, pid, text="sync battery drain"):
    inv = Investigation(product_id=pid, status="resolved", opened_by="manual", budget_tier="quick",
                        budget_json={})
    db.add(inv)
    db.flush()
    finding = Finding(investigation_id=inv.id, product_id=pid, summary=text, confidence=0.8,
                      status="approved", json={})
    db.add(finding)
    db.flush()
    return inv, finding


def test_unscoped_brain_calibration_cannot_grade_other_products(db):
    from echolens.brain import calibrate_from_history
    edge = KnowledgeEdge(product_id=None, subsystem="sync", symptom="battery-drain", supports=1,
                         refutes=0, verified_count=1, case_ids=[], terms=[])
    db.add(edge)
    _case(db, 2)
    result = calibrate_from_history(db, None)
    assert result["tested"] == 0
    assert edge.supports == 1


def test_legacy_finding_inherits_its_investigation_product(db):
    from echolens.db.migrate import backfill_products
    first, second = Product(name="First"), Product(name="Second")
    db.add_all([first, second])
    db.flush()
    _, finding = _case(db, second.id)
    finding.product_id = None
    db.flush()
    backfill_products(db)
    assert finding.product_id == second.id


def test_duplicate_case_migration_is_idempotent(db):
    from echolens.db.migrate import dedupe_cases
    first, _ = _case(db, 1)
    second, _ = _case(db, 1)
    first.anomaly_id = second.anomaly_id = 77
    db.flush()
    assert dedupe_cases(db)["merged_duplicates"] == 1
    notes = list(second.data_notes)
    assert dedupe_cases(db)["merged_duplicates"] == 0
    assert second.data_notes == notes


@pytest.mark.parametrize("tool", ["search", "stats", "cohorts", "trend", "periods", "releases"])
def test_date_only_upper_bound_includes_the_whole_day(db, tool):
    from echolens.tools.search_reviews import search_reviews
    from echolens.tools.review_stats import review_stats
    from echolens.tools.compare_cohorts import compare_cohorts
    from echolens.tools.analyze_trend import analyze_trend
    from echolens.tools.compare_periods import compare_periods
    from echolens.tools.get_release_notes import get_release_notes
    for day in range(1, 6):
        at = datetime(2026, 9, day, 12, tzinfo=timezone.utc)
        db.add(Review(source="play_store", ext_id=str(day), rating=1, text="battery drain", created_at=at,
                      product="A", version="1.0"))
        db.add(Release(version=str(day), released_at=at, notes="battery patch", product="A"))
    db.flush()
    kwargs = dict(date_from="2026-09-01", date_to="2026-09-04", product="A")
    if tool == "search":
        assert search_reviews(db, "battery", **kwargs)["total_matches"] == 4
    elif tool == "stats":
        assert review_stats(db, "battery", **kwargs)["total_reviews"] == 4
    elif tool == "cohorts":
        assert compare_cohorts(db, "battery", **kwargs)["cohorts"][0]["reviews"] == 4
    elif tool == "trend":
        assert analyze_trend(db, "battery", **kwargs)["days"] == 4
    elif tool == "releases":
        assert get_release_notes(db, **kwargs)["total_matching"] == 4
    else:
        result = compare_periods(db, "one_star_volume", "2026-09-01", "2026-09-02",
                                 "2026-09-03", "2026-09-04", product="A")
        assert result["before"]["days"] == result["after"]["days"] == 2


def test_explicit_timestamp_upper_bound_remains_precise(db):
    from echolens.tools.search_reviews import search_reviews
    db.add(Review(source="play_store", ext_id="late", rating=1, text="battery drain", product="A",
                  created_at=datetime(2026, 9, 4, 12)))
    db.flush()
    assert search_reviews(db, "battery", date_to="2026-09-04T00:00:00Z")["total_matches"] == 0


def test_long_reviews_with_shared_prefix_are_not_collapsed():
    from echolens.feedback import FeedbackItem, dedupe_witnesses
    prefix = "This is my detailed experience using the application every day. " * 4
    items = [FeedbackItem(ref=str(i), channel="support", text=prefix + ending, created_at=None)
             for i, ending in enumerate(["The payment failed.", "My account was deleted."])]
    kept, collapsed = dedupe_witnesses(items)
    assert len(kept) == 2
    assert collapsed == 0


def test_quarter_plan_exposes_only_explicit_overrides(db):
    from echolens.backlog import quarter_plan, save_plan
    from tests.test_v11_backlog import _problem
    product = Product(name="A")
    db.add(product)
    db.flush()
    case, _ = _problem(db, product.id, summary="broken sync")
    save_plan(db, product.id, included=[], excluded=[], capacity_days=60)
    plan = quarter_plan(db, product.id)
    assert [item["investigation_id"] for item in plan["proposed"]] == [case.id]
    assert plan["included"] == []
    assert plan["excluded"] == []


def test_plan_notes_can_be_cleared(db):
    from echolens.backlog import save_plan
    save_plan(db, 1, included=[], excluded=[], notes={"12": "old note"})
    saved = save_plan(db, 1, included=[], excluded=[], notes={})
    assert saved["notes"] == {}


def test_weekly_resolution_rate_counts_cases_not_fix_watches(db):
    from echolens.brief import _resolution_rate
    from echolens.db.models import FixWatch
    inv, finding = _case(db, 1)
    for n in range(3):
        db.add(FixWatch(investigation_id=inv.id, finding_id=finding.id, product_id=1,
                        repo="owner/repo", issue_number=n, status="confirmed", terms=[], metric="m"))
    db.flush()
    assert _resolution_rate(db, 1) == 1.0


def test_triage_service_failure_keeps_anomalies_pending(db):
    from echolens.db.models import AnomalyEvent
    from echolens.llm.client import LLMServiceError
    from echolens.orchestrator.triage import Orchestrator

    class Unavailable:
        def complete_json(self, *args):
            raise LLMServiceError("temporary outage")

    anomaly = AnomalyEvent(slug="new-signal", type="negative_review_spike", metric="negative",
                           delta=1, z=3, window="7d", status="pending", product_id=1)
    db.add(anomaly)
    db.flush()
    result = Orchestrator(db, llm=Unavailable(), product_id=1).triage()
    assert [decision.decision for decision in result] == ["defer"]
    assert anomaly.status == "pending"


def test_llm_retry_timeout_shrinks_to_remaining_budget(monkeypatch):
    import httpx
    from openai import APITimeoutError
    from echolens.llm import openai_client as oc
    from tests.test_model_compat import _Resp, _fake_openai

    clock = [0.0]
    requests = []

    class Completions:
        def create(self, **kwargs):
            requests.append(kwargs)
            if len(requests) == 1:
                clock[0] += 18
                raise APITimeoutError(request=httpx.Request("POST", "https://example.test"))
            return _Resp()

    monkeypatch.setattr(oc, "OpenAI", lambda **kw: _fake_openai(Completions(), **kw))
    monkeypatch.setattr(oc.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(oc.random, "uniform", lambda *args: 0)
    client = oc.OpenAIClient(model="test", max_total_s=20, base_delay=1,
                             sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    assert client.complete_json("s", "u", {"type": "object"}, "test").parsed == {"ok": True}
    assert requests[0].get("timeout", 90) == 20
    assert requests[1].get("timeout", 90) == 1


def test_json_repair_retry_does_not_reset_llm_deadline(monkeypatch):
    from echolens.llm import openai_client as oc
    from echolens.llm.client import LLMServiceError
    from tests.test_model_compat import _Resp, _fake_openai

    clock = [0.0]
    calls = []

    class Completions:
        def create(self, **kwargs):
            calls.append(kwargs)
            clock[0] += 20
            response = _Resp()
            response.choices[0].message.content = "invalid json"
            return response

    monkeypatch.setattr(oc, "OpenAI", lambda **kw: _fake_openai(Completions(), **kw))
    monkeypatch.setattr(oc.time, "monotonic", lambda: clock[0])
    with pytest.raises(LLMServiceError):
        oc.OpenAIClient(model="test", max_total_s=20).complete_json("s", "u", {"type": "object"}, "test")
    assert len(calls) == 1


@pytest.mark.parametrize("text,versions", [("checkout error", ["1.0", "2.0"]),
                                         ("battery drain", ["1.0"]),
                                         ("battery drain", ["1.0", "2.0"])])
def test_followup_does_not_invent_exclusivity_without_comparative_signal(db, text, versions):
    from echolens.chat import followup
    product = Product(name="A")
    db.add(product)
    db.flush()
    _, finding = _case(db, product.id, text="battery drain")
    finding.json = {"summary": "battery drain"}
    for index, version in enumerate(versions):
        db.add(Review(source="play_store", ext_id=str(index), product="A", text=text,
                      rating=1, version=version, created_at=datetime(2026, 9, 1)))
    db.flush()
    answer = followup(db, finding, "Which version is affected?")["answer"]
    assert "largely exclusive" not in answer
    assert "Other cohorts are comparatively clean" not in answer
