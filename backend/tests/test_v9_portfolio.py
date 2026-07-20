"""v9.0 — portfolio: one brain across every product.

Exit criteria under test:
  1. a fix verified on one product MEASURABLY shortcuts an investigation on another
  2. the PM opens one screen and knows which product to touch first
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from echolens.db.models import (
    AnomalyEvent, Base, Finding, FixWatch, Investigation, Product,
    Recommendation, Review)

NOW = datetime(2026, 7, 20, tzinfo=timezone.utc)


@pytest.fixture()
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _product(s, name, **kw):
    p = Product(name=name, **kw)
    s.add(p); s.flush()
    return p


def _reviews(s, product, n, text, rating=1, days_ago=3):
    for i in range(n):
        s.add(Review(source="play_store", ext_id=f"{product}-{text[:6]}-{i}-{days_ago}",
                     rating=rating, text=text, product=product,
                     created_at=NOW - timedelta(days=days_ago, hours=i)))
    s.flush()


def _confirmed_fix(s, product: Product, *, cause, fix, terms):
    """A fix that shipped on `product` and was VERIFIED to work — the only thing
    that earns a pattern."""
    a = AnomalyEvent(slug=f"{product.name}-a1", type="theme_volume_surge",
                     metric="battery mentions", delta=0.3, z=3.0, window="7d",
                     description=cause, status="closed", product_id=product.id)
    s.add(a); s.flush()
    inv = Investigation(anomaly_id=a.id, status="resolved", opened_by="anomaly",
                        budget_tier="standard", budget_json={"iterations": "6/12"},
                        product_id=product.id)
    s.add(inv); s.flush()
    f = Finding(investigation_id=inv.id, summary=cause, confidence=0.88, status="approved",
                json={"summary": cause, "prose": cause, "impact": {"impact_score": 0.6}},
                product_id=product.id)
    s.add(f); s.flush()
    s.add(Recommendation(finding_id=f.id, rank=1, action=fix, rationale="r"))
    s.add(FixWatch(finding_id=f.id, investigation_id=inv.id, repo="o/r", issue_number=1,
                   status="confirmed", terms=terms, metric="battery mentions",
                   baseline_rate=8.0, post_rate=1.0, confirmed_at=NOW - timedelta(days=10),
                   product_id=product.id))
    s.flush()
    return inv, f


# ── shared theme vocabulary ─────────────────────────────────────────────

def test_the_same_complaint_gets_the_same_id_across_wordings():
    from echolens.vocab import canonical_theme
    a = canonical_theme(["battery", "drain"])
    b = canonical_theme(["draining", "battery", "fast"])
    c = canonical_theme(["power", "overheating"])
    assert a["id"] == b["id"] == c["id"] == "battery-drain"
    assert a["is_family"] is True
    # and genuinely different complaints must NOT collapse together
    assert canonical_theme(["checkout", "payment"])["id"] != a["id"]


def test_unknown_themes_still_get_a_stable_shared_id():
    """Emergent themes are the common case on a real app — they must line up
    across products without being in any curated list."""
    from echolens.vocab import canonical_theme
    x = canonical_theme(["widget", "resizing"])
    y = canonical_theme(["resizing", "widget"])   # order must not matter
    assert x["id"] == y["id"] and x["is_family"] is False


def test_measurement_words_never_become_a_theme():
    from echolens.vocab import canonical_theme
    assert canonical_theme(["daily", "1-star", "review", "volume"])["id"] == "other"


def test_theme_rates_compare_products_as_shares_not_counts(session):
    """A 3000-review app and a 40-review app must be comparable."""
    from echolens.vocab import canonical_theme, compare_theme
    s = session
    _product(s, "Big"); _product(s, "Small")
    _reviews(s, "Big", 20, "battery drain is awful")
    _reviews(s, "Big", 180, "checkout is broken")           # battery = 10% of negatives
    _reviews(s, "Small", 8, "battery drain is awful")
    _reviews(s, "Small", 2, "checkout is broken")           # battery = 80% of negatives
    s.commit()
    rows = compare_theme(s, canonical_theme(["battery", "drain"]), ["Big", "Small"], days=30,
                         as_of=NOW)
    assert rows[0]["product"] == "Small", "the loudest product by RATE must rank first"
    assert rows[0]["rate_pct"] > rows[1]["rate_pct"]


# ── cross-product pattern transfer ──────────────────────────────────────

def test_own_product_pattern_still_outranks_a_borrowed_one(session):
    """A fix proven on THIS app is stronger evidence than the same fix proven
    elsewhere — borrowing must never displace local knowledge."""
    from echolens.patterns import matching_pattern
    s = session
    lumo = _product(s, "Lumo")
    app_b = _product(s, "AppB")
    _confirmed_fix(s, lumo, cause="Lumo: sync wakelock drains battery",
                   fix="release the wakelock", terms=["battery", "drain", "sync"])
    _confirmed_fix(s, app_b, cause="AppB: local battery cause",
                   fix="local fix", terms=["battery", "drain"])
    target = AnomalyEvent(slug="b-new", type="theme_volume_surge", metric="battery drain",
                          delta=0.3, z=3.0, window="7d",
                          description="battery drain complaints spiking",
                          status="pending", product_id=app_b.id)
    s.add(target); s.commit()
    pat = matching_pattern(s, target)
    assert pat is not None and pat["cross_product"] is False
    assert "AppB" in pat["cause"]


def test_a_verified_fix_on_one_product_becomes_a_prior_on_another(session):
    from echolens.patterns import matching_pattern
    s = session
    lumo = _product(s, "Lumo")
    app_b = _product(s, "AppB")
    _confirmed_fix(s, lumo, cause="Background sync holds a wakelock, draining battery",
                   fix="release the wakelock when the queue empties",
                   terms=["battery", "drain", "sync"])
    target = AnomalyEvent(slug="b-new", type="theme_volume_surge", metric="battery mentions",
                          delta=0.3, z=3.0, window="7d",
                          description="battery draining fast after update",
                          status="pending", product_id=app_b.id)
    s.add(target); s.commit()

    pat = matching_pattern(s, target)
    assert pat is not None, "AppB should inherit Lumo's verified battery pattern"
    assert pat["cross_product"] is True and pat["from_product"] == "Lumo"


def test_an_unrelated_product_pattern_is_not_borrowed(session):
    """Transfer must be theme-matched, not 'any verified fix anywhere'."""
    from echolens.patterns import matching_pattern
    s = session
    lumo = _product(s, "Lumo")
    app_b = _product(s, "AppB")
    _confirmed_fix(s, lumo, cause="Checkout total miscalculates shipping",
                   fix="fix the tax rule", terms=["checkout", "shipping", "payment"])
    target = AnomalyEvent(slug="b-new", type="theme_volume_surge", metric="battery mentions",
                          delta=0.3, z=3.0, window="7d",
                          description="battery draining fast", status="pending",
                          product_id=app_b.id)
    s.add(target); s.commit()
    assert matching_pattern(s, target) is None


# ── exit criterion 1: the shortcut is MEASURABLE ────────────────────────

def _run_case(s, anomaly, script, tier="standard"):
    from echolens.eval.harness import ScriptedLLM
    from echolens.investigator.graph import Investigator
    return Investigator(s, anomaly, llm=ScriptedLLM(script), tier=tier).run()


def test_a_borrowed_pattern_measurably_shortcuts_the_investigation(session):
    """THE exit criterion. Same anomaly, same evidence, same conclusion — but the
    seeded run skips the cold-start hypothesis-generation iteration because the
    proven cause is already on the board.
    """
    from echolens.tools.search_github_issues import search_github_issues
    from echolens.tools.search_reviews import search_reviews
    s = session
    lumo = _product(s, "Lumo")
    app_b = _product(s, "AppB")
    _reviews(s, "AppB", 12, "battery drain awful since the update")
    from echolens.db.models import Issue
    s.add(Issue(ext_id="#77", title="battery drain from sync wakelock",
                body_snippet="wakelock never released when the queue empties",
                state="open", reactions=40, created_at=NOW - timedelta(days=2),
                product="AppB"))
    s.commit()

    ref_r = search_reviews(s, query="battery drain", product="AppB")["reviews"][0]["ref"]
    ref_g = search_github_issues(s, query="battery drain wakelock", product="AppB")["issues"][0]["ref"]

    def evidence_script(with_seed: bool):
        """Identical work in both runs. The COLD run must first invent the
        hypothesis; the seeded run already has it."""
        steps = []
        if not with_seed:
            steps.append({"thought": "No prior. Forming hypotheses from scratch.",
                          "action": "revise_hypotheses",
                          "hypotheses": [{"id": "H1", "statement": "sync drains battery",
                                          "confidence": 0.4, "status": "active"}]})
        steps += [
            {"thought": "Check the complaints.", "action": "call_tool",
             "tool": {"name": "search_reviews", "args": {"query": "battery drain"},
                      "tests_hypothesis": "H1"}},
            {"evidence": [{"ref": ref_r, "snippet": "battery drain since update",
                           "supports": ["H1"], "contradicts": []}],
             "hypothesis_updates": [{"id": "H1", "new_confidence": 0.65,
                                     "based_on_refs": [ref_r], "note": "reviews agree"}]},
            {"thought": "Corroborate in a second source.", "action": "call_tool",
             "tool": {"name": "search_github_issues", "args": {"query": "battery drain wakelock"},
                      "tests_hypothesis": "H1"}},
            {"evidence": [{"ref": ref_g, "snippet": "wakelock never released",
                           "supports": ["H1"], "contradicts": []}],
             "hypothesis_updates": [{"id": "H1", "new_confidence": 0.86,
                                     "based_on_refs": [ref_g], "note": "mechanism confirmed"}]},
            {"summary": "Sync wakelock drains battery",
             "prose": f"The drain is caused by the sync wakelock [{ref_r}][{ref_g}].".replace(
                 ref_r, "ev_001").replace(ref_g, "ev_002"),
             "confidence": 0.86, "supported_hypothesis": "H1",
             "checked": ["play_store", "github"], "what_would_settle_it": ""},
        ]
        return steps

    def iters(inv):
        return int(str((inv.budget_json or {}).get("iterations", "0/0")).split("/")[0])

    # ── cold run: no pattern exists anywhere yet ──
    cold_anomaly = AnomalyEvent(slug="b-cold", type="theme_volume_surge",
                                metric="battery mentions", delta=0.3, z=3.0, window="7d",
                                description="battery draining fast", status="pending",
                                product_id=app_b.id)
    s.add(cold_anomaly); s.commit()
    cold = _run_case(s, cold_anomaly, evidence_script(with_seed=False))

    # ── now Lumo verifies a fix for the same theme ──
    _confirmed_fix(s, lumo, cause="Background sync holds a wakelock, draining battery",
                   fix="release the wakelock when the queue empties",
                   terms=["battery", "drain", "sync"])
    seeded_anomaly = AnomalyEvent(slug="b-seeded", type="theme_volume_surge",
                                  metric="battery mentions", delta=0.3, z=3.0, window="7d",
                                  description="battery draining fast", status="pending",
                                  product_id=app_b.id)
    s.add(seeded_anomaly); s.commit()
    seeded = _run_case(s, seeded_anomaly, evidence_script(with_seed=True))

    assert seeded.seeded_from_pattern is not None
    assert seeded.seeded_from_pattern["cross_product"] is True
    assert seeded.seeded_from_pattern["from_product"] == "Lumo"
    # same destination…
    assert cold.status == seeded.status == "resolved"
    # …reached in fewer iterations
    assert iters(seeded) < iters(cold), (
        f"transfer must shorten the loop: seeded={iters(seeded)} cold={iters(cold)}")

    from echolens.portfolio import transfer_stats
    stats = transfer_stats(s)
    assert stats["sufficient"] and stats["iterations_saved_pct"] > 0


def test_a_borrowed_prior_still_has_to_earn_its_evidence(session):
    """A transfer is a place to look, never a conclusion — the seeded hypothesis
    starts BELOW the insufficient-evidence line and must clear the two-source
    rule on this product's own data."""
    from echolens.config import INSUFFICIENT_CONFIDENCE, SEEDED_PRIOR_CONFIDENCE
    assert SEEDED_PRIOR_CONFIDENCE < INSUFFICIENT_CONFIDENCE

    from echolens.eval.harness import ScriptedLLM
    from echolens.investigator.graph import Investigator
    s = session
    lumo = _product(s, "Lumo")
    app_b = _product(s, "AppB")
    _confirmed_fix(s, lumo, cause="Background sync holds a wakelock, draining battery",
                   fix="release it", terms=["battery", "drain", "sync"])
    a = AnomalyEvent(slug="b-noevid", type="theme_volume_surge", metric="battery mentions",
                     delta=0.3, z=3.0, window="7d", description="battery draining fast",
                     status="pending", product_id=app_b.id)
    s.add(a); s.commit()
    # the agent immediately gives up: no evidence gathered on AppB at all
    inv = Investigator(s, a, llm=ScriptedLLM([
        {"thought": "Nothing to corroborate the borrowed prior.", "action": "conclude",
         "conclusion": {"status": "insufficient_evidence", "reason": "no local evidence"}},
        {"summary": "Insufficient evidence", "prose": "Nothing on AppB corroborates it.",
         "confidence": 0.4, "supported_hypothesis": None, "checked": ["play_store"],
         "what_would_settle_it": "AppB-side reviews mentioning battery"},
    ]), tier="quick").run()
    assert inv.status == "insufficient_evidence"
    f = s.scalars(select(Finding).where(Finding.investigation_id == inv.id)).first()
    assert f.json.get("supported_hypothesis") is None, \
        "a borrowed pattern must never be reported as a supported cause on its own"


# ── exit criterion 2: one screen says which product to touch first ──────

def test_the_board_ranks_the_burning_product_first(session):
    from echolens.portfolio import portfolio
    s = session
    calm = _product(s, "Calm")
    burning = _product(s, "Burning")
    _reviews(s, "Calm", 5, "works fine", rating=5)
    # Burning: an unfixed high-severity problem + a regression
    a = AnomalyEvent(slug="burn-1", type="negative_review_spike", metric="1-star volume",
                     delta=0.9, z=6.0, window="7d", description="crashes everywhere",
                     status="closed", product_id=burning.id)
    s.add(a); s.flush()
    inv = Investigation(anomaly_id=a.id, status="resolved", opened_by="anomaly",
                        budget_tier="standard", budget_json={"iterations": "5/12"},
                        product_id=burning.id, created_at=NOW - timedelta(days=2))
    s.add(inv); s.flush()
    f = Finding(investigation_id=inv.id, summary="Login crash on 3.2", confidence=0.9,
                status="approved", product_id=burning.id,
                json={"summary": "Login crash on 3.2", "impact": {
                    "impact_score": 0.95, "affected_pct": 40.0, "affected_volume": 900}})
    s.add(f); s.flush()
    s.add(FixWatch(finding_id=f.id, investigation_id=inv.id, repo="o/r", issue_number=9,
                   status="regressed", terms=["login", "crash"], metric="m",
                   baseline_rate=5.0, post_rate=9.0, product_id=burning.id))
    s.commit()

    board = portfolio(s, NOW)
    assert board["products"][0]["product"] == "Burning"
    assert board["products"][0]["score"] > board["products"][-1]["score"]
    assert "Burning" in board["verdict"], "the verdict must NAME the product to open"
    # and it must justify itself, not just assert a number
    assert board["products"][0]["reasons"], "a ranking a PM can't audit is one they won't trust"
    assert any(r["kind"] == "regression" for r in board["products"][0]["reasons"])


def test_a_quiet_portfolio_says_so_plainly(session):
    from echolens.portfolio import portfolio
    s = session
    _product(s, "Calm"); _product(s, "Also Calm")
    _reviews(s, "Calm", 5, "great app", rating=5)
    s.commit()
    board = portfolio(s, NOW)
    assert board["needs_attention"] == 0
    assert "nothing needs you" in board["verdict"].lower()


def test_an_empty_portfolio_does_not_pretend(session):
    from echolens.portfolio import portfolio
    board = portfolio(session, NOW)
    assert board["products"] == [] and "No products" in board["verdict"]


def test_stale_sources_are_disclosed_in_the_ranking(session):
    """If we can't see a product, the board must say so rather than rank it 'healthy'."""
    from echolens.db.models import CollectorState
    from echolens.portfolio import portfolio
    s = session
    p = _product(s, "Blind")
    s.add(CollectorState(source="play_store", identifier="com.blind", product="Blind",
                         product_id=p.id, status="error",
                         last_run_at=NOW - timedelta(days=9)))
    s.commit()
    row = portfolio(s, NOW)["products"][0]
    assert any(r["kind"] == "stale" for r in row["reasons"])


def test_portfolio_brief_ranks_across_products_not_per_product(session):
    from echolens.portfolio import portfolio_brief
    s = session
    small = _product(s, "Small")
    big = _product(s, "Big")
    for prod, score, summary in ((small, 0.2, "Small: minor label bug"),
                                 (big, 0.9, "Big: checkout fails for 40%")):
        a = AnomalyEvent(slug=f"{prod.name}-x", type="theme_volume_surge", metric="m",
                         delta=0.2, z=3.0, window="7d", description="d", status="closed",
                         product_id=prod.id)
        s.add(a); s.flush()
        inv = Investigation(anomaly_id=a.id, status="resolved", opened_by="anomaly",
                            budget_tier="quick", budget_json={}, product_id=prod.id,
                            created_at=NOW - timedelta(days=1))
        s.add(inv); s.flush()
        s.add(Finding(investigation_id=inv.id, summary=summary, confidence=0.8,
                      status="approved", product_id=prod.id,
                      json={"summary": summary, "impact": {"impact_score": score}}))
    s.commit()
    b = portfolio_brief(s, NOW)
    assert [p["product"] for p in b["problems"]][0] == "Big"
    assert any("Big" in ln for ln in b["lines"])
    assert len(b["per_product"]) == 2


def test_transfer_stats_refuses_to_claim_a_speedup_without_evidence(session):
    from echolens.portfolio import transfer_stats
    stats = transfer_stats(session)
    assert stats["sufficient"] is False and stats["iterations_saved_pct"] is None
