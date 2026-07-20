"""v8.0: prove product scoping reaches the EVIDENCE layer, not just the UI.

Scoping the API but not the tools would be the worst kind of half-fix: the Case
Feed would look isolated while an investigation quietly cited another product's
reviews as proof. These tests plant a decoy product whose corpus is engineered to
poison a Lumo golden (same words, same window, opposite story) and assert:

  1. every corpus tool honours the product filter
  2. the investigator forces its own product — the agent cannot widen it
  3. the six goldens still pass with that decoy sitting in the same database
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from echolens.db.migrate import DEMO_PRODUCT, backfill_products
from echolens.db.models import AnomalyEvent, Issue, Post, Product, Release, Review
from echolens.eval import harness
from echolens.tools.registry import run_tool

DECOY = "Decoy Co"


def _plant_decoy(session) -> Product:
    """A second product that talks about battery drain in the same window as
    Lumo's golden — but blames the OS. If any of it leaks into a Lumo case, the
    decoy-rejection golden flips."""
    p = Product(name=DECOY, package_name="com.decoy.app", github_repo="decoy/app")
    session.add(p)
    session.flush()
    base = datetime(2026, 7, 12, tzinfo=timezone.utc)
    for i in range(40):
        session.add(Review(
            source="play_store", ext_id=f"decoy_r{i}", rating=1,
            text="battery drain is terrible since the Android 15 update, background sync fine",
            version="9.9.9", os_version="Android 15",
            created_at=base + timedelta(hours=i), product=DECOY))
    session.add(Issue(
        ext_id="#9999", title="battery drain from background sync wakelock",
        body_snippet="decoy issue: battery drain caused by the OS, not our app",
        state="open", reactions=999, created_at=base, product=DECOY))
    session.add(Post(
        source="reddit", ext_id="decoy_post_1", subreddit="decoy",
        text_snippet="battery drain everywhere after the update", created_at=base,
        product=DECOY))
    session.add(Release(
        version="9.9.9", notes="decoy release: background sync battery rewrite",
        released_at=base, product=DECOY))
    session.flush()
    return p


_fresh_session = harness.fresh_session  # bound now: the eval test patches the name


def _scoped_session():
    """Lumo's synthetic corpus, migrated into a real Product, plus the decoy."""
    s = _fresh_session()
    backfill_products(s)          # stamps the untagged Lumo corpus as DEMO_PRODUCT
    _plant_decoy(s)
    lumo = s.scalars(select(Product).where(Product.name == DEMO_PRODUCT)).first()
    for a in s.scalars(select(AnomalyEvent)).all():
        a.product_id = lumo.id    # every golden anomaly belongs to Lumo
    s.commit()
    return s


@pytest.fixture()
def scoped():
    return _scoped_session()


# ── 1. the tools themselves ─────────────────────────────────────────────

def test_every_corpus_tool_honours_the_product_filter(scoped):
    s = scoped
    lumo_refs = {r.ext_id for r in s.scalars(
        select(Review).where(Review.product == DEMO_PRODUCT)).all()}

    revs = run_tool(s, "search_reviews", {"query": "battery drain", "rating_max": 2},
                    product=DEMO_PRODUCT)["reviews"]
    assert revs, "scoping must not empty the corpus"
    assert all(r["ref"] in lumo_refs for r in revs)

    issues = run_tool(s, "search_github_issues", {"query": "battery drain wakelock"},
                      product=DEMO_PRODUCT)["issues"]
    assert all("#9999" not in i["ref"] for i in issues)

    posts = run_tool(s, "search_reddit", {"query": "battery drain"},
                     product=DEMO_PRODUCT)["posts"]
    assert all(p["ref"] != "decoy_post_1" for p in posts)

    rels = run_tool(s, "get_release_notes", {}, product=DEMO_PRODUCT)["releases"]
    assert all(r["version"] != "9.9.9" for r in rels)

    # the aggregate tools too — a leaked cohort silently skews every rate
    cohorts = run_tool(s, "compare_cohorts", {"term": "battery", "dimension": "version"},
                       product=DEMO_PRODUCT)
    assert "9.9.9" not in str(cohorts)


def test_the_decoy_is_actually_reachable_when_unscoped(scoped):
    """Guards the test above: without a product it DOES come back, so the
    assertions prove filtering rather than an empty decoy."""
    issues = run_tool(scoped, "search_github_issues", {"query": "battery drain wakelock"})["issues"]
    assert any("#9999" in i["ref"] for i in issues)


# ── 2. the agent cannot widen its own scope ─────────────────────────────

def test_investigator_forces_its_product_over_the_models_args(scoped):
    """`product` is not in any tool's model-facing schema, and run_tool stamps
    the case's own product last — so a model asking for the decoy gets Lumo."""
    from echolens.investigator.graph import Investigator
    s = scoped
    anomaly = s.scalars(select(AnomalyEvent).where(AnomalyEvent.slug == "demo1")).first()
    inv = Investigator(s, anomaly, llm=harness.ScriptedLLM([]), tier="quick")
    assert inv._product_name == DEMO_PRODUCT

    lumo_refs = {r.ext_id for r in s.scalars(
        select(Review).where(Review.product == DEMO_PRODUCT)).all()}
    out = run_tool(s, "search_reviews",
                   {"query": "battery drain", "rating_max": 2, "product": DECOY},
                   product=inv._product_name)
    assert out["reviews"] and all(r["ref"] in lumo_refs for r in out["reviews"])


def test_an_unscoped_legacy_case_still_reads_everything(scoped):
    """Pre-v8 cases have no product_id; they must keep working, not break."""
    from echolens.investigator.graph import Investigator
    s = scoped
    anomaly = s.scalars(select(AnomalyEvent).where(AnomalyEvent.slug == "demo1")).first()
    anomaly.product_id = None
    s.flush()
    inv = Investigator(s, anomaly, llm=harness.ScriptedLLM([]), tier="quick")
    assert inv._product_name is None


# ── 3. the goldens, run per product ─────────────────────────────────────

def test_goldens_still_pass_with_a_second_product_in_the_database(monkeypatch):
    """The eval suite, scoped: same six scenarios, but every session now holds a
    decoy product engineered to break them. Pass rate must stay 100%."""
    monkeypatch.setattr(harness, "fresh_session", _scoped_session)
    report = harness.run_all()
    failed = [s["name"] for s in report["scenarios"] if not s["passed"]]
    assert not failed, f"goldens broke under product scoping: {failed}"
    assert report["claim_grounding_pct"] == 100.0
    assert report["honesty_pct"] == 100.0
