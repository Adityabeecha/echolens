"""v11 — the quality backlog: findings become a defended, ranked plan.

Exit criteria under test:
  a PM can build part of a sprint from the ranked backlog, and every item
  traces to verified evidence AND a projected outcome.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from echolens.db.models import (
    AnomalyEvent, Base, EvidenceRow, Finding, FixWatch, Investigation, Issue,
    Product, Setting)

NOW = datetime(2026, 7, 20, tzinfo=timezone.utc)


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _problem(s, pid, *, summary, conf=0.85, impact_score=0.6, volume=40,
             affected_pct=35.0, rating_impact=0.4, age_days=20, evidence=2,
             slug=None, labels=None, issue_number=None, confirmed=False):
    """A resolved case with a finding — i.e. a backlog candidate."""
    a = AnomalyEvent(slug=slug or f"a-{summary[:12]}", type="theme_volume_surge",
                     metric=summary, delta=0.3, z=3.0, window="7d",
                     description=summary, status="closed", product_id=pid)
    s.add(a); s.flush()
    inv = Investigation(anomaly_id=a.id, status="resolved", opened_by="anomaly",
                        budget_tier="standard", budget_json={}, product_id=pid,
                        created_at=NOW - timedelta(days=age_days))
    s.add(inv); s.flush()
    f = Finding(investigation_id=inv.id, summary=summary, confidence=conf,
                status="approved", product_id=pid,
                json={"summary": summary, "confidence": conf,
                      "impact": {"impact_score": impact_score, "affected_pct": affected_pct,
                                 "affected_volume": volume, "rating_impact": rating_impact}})
    s.add(f); s.flush()
    for i in range(evidence):
        s.add(EvidenceRow(investigation_id=inv.id, eid=f"ev_{i:03d}",
                          source="play_store", ref=f"{slug or summary[:6]}-r{i}",
                          snippet="…", retrieved_by="search_reviews", json={}))
    if issue_number is not None:
        s.add(Issue(ext_id=f"#{issue_number}", title=summary, body_snippet="",
                    state="open", reactions=3, labels=labels or [],
                    created_at=NOW - timedelta(days=age_days)))
        s.add(FixWatch(finding_id=f.id, investigation_id=inv.id, repo="o/r",
                       issue_number=issue_number,
                       status="confirmed" if confirmed else "issue_open",
                       terms=["x"], metric="m", product_id=pid,
                       fix_date=NOW - timedelta(days=2) if confirmed else None,
                       confirmed_at=NOW if confirmed else None))
    s.flush()
    return inv, f


# ── every line is defended ──────────────────────────────────────────────

def test_every_backlog_item_traces_to_evidence_and_a_projection():
    """THE exit criterion: nothing is ranked without something behind it."""
    from echolens.backlog import backlog
    s = _session()
    p = Product(name="Lumo"); s.add(p); s.flush()
    _problem(s, p.id, summary="Sync drains battery", slug="b1")
    _problem(s, p.id, summary="Checkout fails on card entry", slug="b2",
             impact_score=0.4, volume=12, age_days=5)
    s.commit()

    board = backlog(s, p.id, as_of=NOW)
    assert len(board["items"]) == 2
    for item in board["items"]:
        assert item["evidence_count"] >= 1, "an item with no evidence must not be ranked"
        assert item["evidence_refs"], "the refs must be retrievable, not just counted"
        assert "projected" in item and "basis" in item["projected"]
        assert item["defence"], "every line carries the arithmetic that placed it"
        assert item["rank"] >= 1


def test_the_score_uses_the_stated_formula():
    """severity x volume x persistence x (1 - resolution_rate) — a bigger, older,
    more severe problem must outrank a smaller newer one."""
    from echolens.backlog import backlog
    s = _session()
    p = Product(name="Lumo"); s.add(p); s.flush()
    _problem(s, p.id, summary="Big old severe problem", slug="big",
             conf=0.95, impact_score=0.9, volume=200, age_days=60)
    _problem(s, p.id, summary="Small new mild problem", slug="small",
             conf=0.6, impact_score=0.2, volume=3, age_days=2)
    s.commit()
    items = {i["summary"]: i for i in backlog(s, p.id, as_of=NOW)["items"]}
    assert items["Big old severe problem"]["score"] > items["Small new mild problem"]["score"]


def test_a_verified_fix_leaves_the_backlog():
    from echolens.backlog import backlog
    s = _session()
    p = Product(name="Lumo"); s.add(p); s.flush()
    _problem(s, p.id, summary="Already fixed", slug="done", issue_number=1, confirmed=True)
    _problem(s, p.id, summary="Still broken", slug="open")
    s.commit()
    summaries = [i["summary"] for i in backlog(s, p.id, as_of=NOW)["items"]]
    assert summaries == ["Still broken"]


# ── effort ──────────────────────────────────────────────────────────────

def test_effort_comes_from_issue_labels_when_they_say_something():
    from echolens.backlog import backlog
    s = _session()
    p = Product(name="Lumo"); s.add(p); s.flush()
    _problem(s, p.id, summary="Tiny fix", slug="tiny", issue_number=10,
             labels=["good first issue"])
    s.commit()
    item = backlog(s, p.id, as_of=NOW)["items"][0]
    assert item["effort"]["days"] == 0.5 and item["effort"]["known"] is True
    assert "good first issue" in item["effort"]["basis"]


def test_effort_falls_back_to_this_products_own_track_record():
    """Not an industry average — what fixes here have actually taken."""
    from echolens.backlog import backlog, historical_fix_days
    s = _session()
    p = Product(name="Lumo"); s.add(p); s.flush()
    # two confirmed fixes that took ~10 days each
    for n in (1, 2):
        inv, f = _problem(s, p.id, summary=f"Past fix {n}", slug=f"past{n}",
                          issue_number=n, confirmed=True, age_days=12)
    _problem(s, p.id, summary="New problem, no labels", slug="new")
    s.commit()
    assert historical_fix_days(s, p.id) is not None
    item = [i for i in backlog(s, p.id, as_of=NOW)["items"]
            if i["summary"] == "New problem, no labels"][0]
    assert item["effort"]["known"] is True
    assert "median past fix" in item["effort"]["basis"]


def test_unknown_effort_is_declared_not_invented():
    from echolens.backlog import backlog
    s = _session()
    p = Product(name="Lumo"); s.add(p); s.flush()
    _problem(s, p.id, summary="No signal at all", slug="none")
    s.commit()
    board = backlog(s, p.id, as_of=NOW)
    assert board["items"][0]["effort"]["known"] is False
    assert board["unknown_effort"] == 1


def test_ranking_is_impact_per_effort_not_impact_alone():
    """The actual PM calculus: a slightly smaller problem that is 10x cheaper
    should outrank a marginally bigger one."""
    from echolens.backlog import backlog
    s = _session()
    p = Product(name="Lumo"); s.add(p); s.flush()
    _problem(s, p.id, summary="Huge effort slightly bigger", slug="huge",
             impact_score=0.62, volume=45, issue_number=1, labels=["epic"])
    _problem(s, p.id, summary="Cheap and nearly as valuable", slug="cheap",
             impact_score=0.55, volume=40, issue_number=2, labels=["good first issue"])
    s.commit()
    items = backlog(s, p.id, as_of=NOW)["items"]
    assert items[0]["summary"] == "Cheap and nearly as valuable"
    # ...and the raw score genuinely favoured the other one
    by_score = sorted(items, key=lambda i: -i["score"])
    assert by_score[0]["summary"] == "Huge effort slightly bigger"


# ── projected outcome ───────────────────────────────────────────────────

def test_rating_recovery_shows_its_working():
    from echolens.backlog import rating_recovery
    r = rating_recovery({"rating_impact": 0.40, "affected_pct": 50.0}, confidence=0.8)
    assert r["stars"] == round(0.40 * 0.5 * 0.8, 2)
    assert "0.40★ lost" in r["basis"] and "50%" in r["basis"] and "80%" in r["basis"]


def test_no_measurable_drop_projects_nothing_rather_than_a_guess():
    from echolens.backlog import rating_recovery
    r = rating_recovery({"rating_impact": 0.0, "affected_pct": 40.0}, confidence=0.9)
    assert r["stars"] == 0.0 and r["confident"] is False
    assert "no measurable rating drop" in r["basis"]


# ── the quarter plan: proposed, then owned ──────────────────────────────

def test_the_plan_fills_capacity_and_never_exceeds_it():
    from echolens.backlog import quarter_plan
    s = _session()
    p = Product(name="Lumo"); s.add(p); s.flush()
    for n in range(6):   # 6 items x 5d medium effort = 30d of work
        _problem(s, p.id, summary=f"Problem {n}", slug=f"p{n}",
                 impact_score=0.5 + n / 100, volume=20 + n)
    s.commit()
    plan = quarter_plan(s, p.id, capacity_days=12.0, as_of=NOW)
    assert plan["committed_days"] <= 12.0
    assert plan["proposed"], "a plan with capacity must propose something"
    assert plan["deferred"], "and must say what did not fit"
    assert len(plan["proposed"]) + len(plan["deferred"]) == 6


def test_the_pm_owns_the_plan_and_a_rerank_respects_it():
    """The system proposes, the human disposes — an exclusion must survive."""
    from echolens.backlog import quarter_plan, save_plan
    s = _session()
    p = Product(name="Lumo"); s.add(p); s.flush()
    invs = [_problem(s, p.id, summary=f"Problem {n}", slug=f"p{n}",
                     impact_score=0.9 - n / 10)[0] for n in range(4)]
    s.commit()

    top = quarter_plan(s, p.id, capacity_days=20.0, as_of=NOW)["proposed"][0]
    top_id = top["investigation_id"]
    bottom_id = invs[-1].id

    save_plan(s, p.id, included=[bottom_id], excluded=[top_id], capacity_days=20.0)
    s.commit()

    plan = quarter_plan(s, p.id, as_of=NOW)
    ids = [i["investigation_id"] for i in plan["proposed"]]
    assert top_id not in ids, "an excluded item must not be re-proposed"
    assert bottom_id in ids, "an explicitly included item stays in"
    assert plan["owned"] is True
    assert plan["proposed"][0]["investigation_id"] == bottom_id, \
        "the PM's picks lead the plan"


def test_the_plan_projects_a_total_outcome():
    from echolens.backlog import quarter_plan
    s = _session()
    p = Product(name="Lumo"); s.add(p); s.flush()
    _problem(s, p.id, summary="A", slug="a", rating_impact=0.4, affected_pct=50.0, conf=0.8)
    _problem(s, p.id, summary="B", slug="b", rating_impact=0.2, affected_pct=50.0, conf=0.8)
    s.commit()
    plan = quarter_plan(s, p.id, capacity_days=20.0, as_of=NOW)
    assert plan["projected_stars"] > 0
    assert plan["projected_stars"] == round(
        sum(i["projected"]["stars"] for i in plan["proposed"]), 2)


def test_an_empty_backlog_proposes_nothing_rather_than_filler():
    from echolens.backlog import quarter_plan
    s = _session()
    p = Product(name="Lumo"); s.add(p); s.commit()
    plan = quarter_plan(s, p.id, capacity_days=20.0, as_of=NOW)
    assert plan["proposed"] == [] and plan["committed_days"] == 0


def test_the_backlog_is_product_scoped():
    from echolens.backlog import backlog
    s = _session()
    a = Product(name="A"); b = Product(name="B"); s.add(a); s.add(b); s.flush()
    _problem(s, a.id, summary="A problem", slug="pa")
    _problem(s, b.id, summary="B problem", slug="pb")
    s.commit()
    assert [i["summary"] for i in backlog(s, a.id, as_of=NOW)["items"]] == ["A problem"]
    assert [i["summary"] for i in backlog(s, b.id, as_of=NOW)["items"]] == ["B problem"]
