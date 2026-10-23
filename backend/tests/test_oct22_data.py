"""Regression tests for the 2026-10-22 audit: scan slugs, preview purity, anchored
demo data, triage failure isolation, importer caps, GitHub collector limits."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from echolens.db.models import AnomalyEvent, Base, Product, Release, Review
from echolens.detector.detect import reference_now, scan
from echolens.synthetic.generate import END, generate


def _session(anchor=None, product: bool = False):
    eng = create_engine("sqlite://", poolclass=StaticPool,
                        connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng, expire_on_commit=False)()
    generate(s, anchor=anchor)
    if product:
        p = Product(name="Lumo (demo)", is_demo=True)
        s.add(p)
        s.flush()
        for r in s.scalars(select(Review)).all():
            r.product = p.name
        s.commit()
        return s, p
    s.commit()
    return s, None


def _autos(s):
    return [a for a in s.scalars(select(AnomalyEvent)).all() if "auto-" in a.slug]


def test_cli_and_ui_scan_share_one_slug_scheme():
    s, p = _session(product=True)
    scan(s)                                    # CLI style: no product id
    scan(s, product=p.name, product_id=p.id)   # UI style
    slugs = [a.slug for a in _autos(s)]
    assert slugs and all(sl.startswith(f"p{p.id}-") for sl in slugs)
    assert len(slugs) == len(set(slugs))
    assert all(a.product_id == p.id for a in _autos(s))


def test_legacy_unprefixed_duplicate_is_merged():
    s, p = _session(product=True)
    legacy = AnomalyEvent(slug="auto-neg-review-spike", type="negative_review_spike",
                          metric="daily 1-star review volume", delta=1, z=3, window="7d",
                          status="pending", product_id=p.id)
    s.add(legacy)
    s.flush()
    scan(s, product=p.name, product_id=p.id)
    s.refresh(legacy)
    keeper = s.scalars(select(AnomalyEvent).where(
        AnomalyEvent.slug == f"p{p.id}-auto-neg-review-spike")).one()
    assert legacy.merged_into_id == keeper.id and legacy.status == "merged"


def test_scan_without_persist_does_not_mutate_db():
    s, p = _session(product=True)
    first = scan(s, product=p.name, product_id=p.id)
    s.commit()
    row = first[0]
    before = (row.z, row.description, row.window_end.replace(tzinfo=None))
    s.execute(select(AnomalyEvent))
    # a later as_of makes the preview differ from the stored row
    later = reference_now(s, p.name) + timedelta(days=1)
    preview = scan(s, as_of=later, persist=False, product=p.name, product_id=p.id)
    assert preview
    assert not s.dirty and not s.new
    s.rollback()
    stored = s.get(AnomalyEvent, row.id)
    assert (stored.z, stored.description, stored.window_end.replace(tzinfo=None)) == before


def test_generate_default_keeps_fixed_dates_and_today_anchor_shifts():
    s, _ = _session()
    assert reference_now(s).date() == END.date()
    s2, _ = _session(anchor="today")
    today = datetime.now(timezone.utc).date()
    assert abs((reference_now(s2).date() - today).days) <= 1
    rel = s2.scalars(select(Release).order_by(Release.released_at)).all()
    assert rel[-1].released_at.date() <= today
    # the story still detects the battery spike after re-basing
    assert any(e.slug == "auto-neg-review-spike" for e in scan(s2, persist=False))
    d1 = s2.scalars(select(AnomalyEvent).where(AnomalyEvent.slug == "demo1")).one()
    assert "2026-07-11" not in d1.description


def test_run_triaged_isolates_failures(monkeypatch):
    from echolens.investigator import graph
    from echolens.orchestrator.triage import Decision, run_triaged
    s, _ = _session()
    a1 = s.scalars(select(AnomalyEvent).where(AnomalyEvent.slug == "demo1")).one()
    a2 = s.scalars(select(AnomalyEvent).where(AnomalyEvent.slug == "demo2")).one()

    class Boom:
        def __init__(self, session, anomaly, **kw):
            self.anomaly = anomaly

        def run(self):
            if self.anomaly.slug == "demo1":
                raise RuntimeError("boom")
            return "ok"

    monkeypatch.setattr(graph, "Investigator", Boom)
    out = run_triaged(s, [Decision(a1, "investigate", "x", "standard"),
                          Decision(a2, "investigate", "x", "standard")])
    assert out == ["ok"]
    assert s.get(AnomalyEvent, a1.id).status == "pending"
    assert s.get(AnomalyEvent, a2.id).status == "investigating"


def test_csv_import_row_cap_and_batched_dedupe():
    from echolens.importers import csv_reviews as m
    s, _ = _session()
    csv_text = "rating,text,date\n" + "".join(
        f"1,bad {i},2026-07-01\n" for i in range(3))
    r1 = m.import_reviews_csv(s, csv_text, product="P")
    r2 = m.import_reviews_csv(s, csv_text, product="P")
    assert r1["imported"] == 3 and r2["imported"] == 0 and r2["skipped"] == 3
    old = m.MAX_IMPORT_ROWS
    m.MAX_IMPORT_ROWS = 2
    try:
        with pytest.raises(ValueError):
            m.import_reviews_csv(s, csv_text, product="Q")
    finally:
        m.MAX_IMPORT_ROWS = old


def test_undated_csv_rows_do_not_move_reference_now():
    from echolens.importers.csv_reviews import import_reviews_csv
    s, _ = _session()
    before = reference_now(s)
    res = import_reviews_csv(s, "rating,text\n1,no date here\n", product="P")
    assert res["undated"] == 1
    assert reference_now(s) == before


def test_feedback_csv_skips_undated_and_caps_rows():
    from echolens.importers import feedback_csv as m
    s, _ = _session()
    res = m.import_feedback_csv(s, "text,created_at\nhello,\nworld,2026-07-01\n")
    assert res["inserted"] == 1 and res["undated"] == 1
    old = m.MAX_IMPORT_ROWS
    m.MAX_IMPORT_ROWS = 1
    try:
        with pytest.raises(ValueError):
            m.import_feedback_csv(s, "text,created_at\na,2026-07-01\nb,2026-07-02\n")
    finally:
        m.MAX_IMPORT_ROWS = old


def test_github_skips_undated_release_and_respects_limit():
    from echolens.collectors.github import GitHubCollector
    s, _ = _session()
    data = {
        "issues": [{"number": i, "title": f"t{i}", "created_at": f"2026-07-0{i}T00:00:00Z",
                    "updated_at": f"2026-07-0{i}T00:00:00Z"} for i in range(1, 6)],
        "releases": [{"tag_name": "v1", "published_at": None},
                     {"tag_name": "v2", "published_at": "2026-07-01T00:00:00Z"},
                     {"tag_name": "v3", "published_at": "2026-07-02T00:00:00Z"}],
    }
    c = GitHubCollector("o/r", product="P", fetch_fn=lambda: data)
    items = c.fetch(None, 2)
    assert sum(1 for i in items if i["kind"] == "issue") == 2
    assert sum(1 for i in items if i["kind"] == "release") == 2
    undated = next(i for i in items if i.get("tag_name") == "v1")
    assert c.ingest_item(s, undated)[0] is False
    assert s.scalars(select(Release).where(Release.version == "v1")).first() is None
