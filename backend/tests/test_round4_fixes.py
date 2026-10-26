"""Fixes found while checking the redesign on the demo.

1. Plan effort: a product's fix track record is calendar time (case to shipped
   fix), so it sizes an item instead of being read as engineer-days.
2. Release exhibits stored as a release-page URL still get their date.
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from echolens.backlog import EFFORT_BUCKETS, history_bucket
from echolens.db.models import Base, Release


def _session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, expire_on_commit=False)()


def test_calendar_fix_history_sizes_the_item_instead_of_counting_as_days():
    assert history_bucket(2) == "trivial"
    assert history_bucket(8) == "small"
    assert history_bucket(25.5) == "medium"        # the demo's track record
    assert history_bucket(60) == "large"
    # A 26-day end-to-end fix is a medium job, so several fit a 20-day plan.
    assert EFFORT_BUCKETS[history_bucket(25.5)] < 20


def test_effort_from_history_keeps_its_basis_and_uses_the_bucket(monkeypatch):
    from echolens import backlog
    finding = SimpleNamespace(id=1, json={}, investigation_id=1)
    out = backlog.estimate_effort(None, finding, product_id=1, history=25.5, watch=None, issue=None)
    assert out["days"] == EFFORT_BUCKETS["medium"]
    assert out["known"] is True
    assert "median past fix" in out["basis"] and "medium" in out["basis"]


def test_release_exhibit_stored_as_a_url_is_dated():
    from echolens.forensics import _exhibit_meta
    s = _session()
    s.add(Release(version="3.2.0", notes="Background photo sync, on by default.",
                  released_at=datetime(2026, 10, 13, 9), product="Lumo"))
    s.add(Release(version="v4.0.0", notes="Desktop beta.",
                  released_at=datetime(2026, 11, 2, 9), product="Lumo"))
    s.commit()
    evs = [SimpleNamespace(eid="ev_001", source="release_notes",
                           ref="https://github.com/lumo-app/lumo/releases/tag/v3.2.0"),
           SimpleNamespace(eid="ev_002", source="release_notes", ref="release v3.2.0"),
           SimpleNamespace(eid="ev_003", source="release_notes", ref="release 4.0.0")]
    meta = _exhibit_meta(s, evs, "Lumo")
    assert meta["ev_001"]["date"] == "2026-10-13"
    assert meta["ev_002"]["date"] == "2026-10-13"
    assert meta["ev_003"]["date"] == "2026-11-02"   # stored with a leading "v"


# --- Second pass: what a real product (KeePassXC, Nextcloud, Brave) showed ---

def _db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    return eng, sessionmaker(bind=eng, expire_on_commit=False)


def _play(n, start=0):
    return [{"reviewId": f"r{i}", "score": 1 + i % 5, "content": f"review {i}",
             "at": f"2026-10-{1 + i % 20:02d}T10:00:00"} for i in range(start, start + n)]


def test_collector_saves_a_page_in_a_few_statements_not_one_per_review():
    from sqlalchemy import event, func, select
    from echolens.collectors.play_store import PlayStoreCollector
    from echolens.db.models import Review
    eng, Session = _db()
    calls = []
    event.listen(eng, "before_cursor_execute", lambda *a, **k: calls.append(1))
    with Session() as s:
        r = PlayStoreCollector("app", product="P", fetch_fn=lambda: _play(300)).run(s, limit=300)
        s.commit()
        assert r.inserted == 300
        assert s.scalar(select(func.count(Review.id))) == 300
    # Was ~1,200 round trips against a remote DB (4-5 minutes on onboarding).
    assert len(calls) < 60
    # A second run finds them all already there.
    with Session() as s:
        assert PlayStoreCollector("app", product="P", fetch_fn=lambda: _play(300)).run(s, limit=300).inserted == 0


def test_a_malformed_review_falls_back_to_one_at_a_time_and_keeps_the_rest():
    from sqlalchemy import func, select
    from echolens.collectors.play_store import PlayStoreCollector
    from echolens.db.models import Review
    _, Session = _db()
    page = _play(5) + [{"reviewId": "bad", "score": "not a number", "at": "2026-10-02T10:00:00"}]
    with Session() as s:
        PlayStoreCollector("app", product="P", fetch_fn=lambda: page).run(s)
        s.commit()
        assert s.scalar(select(func.count(Review.id))) == 5


def test_issue_templates_do_not_become_themes():
    from echolens.textkit import issue_boilerplate, issue_text
    template = ("## Overview\n<!-- describe the bug -->\n- [ ] I searched existing issues\n"
                "[NOTE]: # ( Give a BRIEF summary )\nSteps to reproduce the behavior\n")
    bodies = [template + f"Quick unlock fails after update {i} see https://x.io/{i}" for i in range(20)]
    boiler = issue_boilerplate(bodies)
    assert "steps to reproduce the behavior" in boiler
    text = issue_text("Quick unlock broken", bodies[0], boiler)
    assert "Quick unlock fails" in text
    for junk in ("Overview", "searched", "NOTE", "Steps to reproduce", "https", "describe"):
        assert junk not in text
    # Too few issues to tell a template from a coincidence.
    assert issue_boilerplate(bodies[:3]) == set()


def test_scan_and_investigations_wait_for_the_first_read(api_db_r4):
    from echolens.db.models import CollectorState, Product
    client, Session = api_db_r4
    with Session() as s:
        p = Product(name="Fresh", package_name="com.fresh")
        s.add(p); s.flush()
        s.add(CollectorState(source="play_store", identifier="com.fresh", product="Fresh",
                             product_id=p.id, status="running"))
        s.commit(); pid = p.id
    scan = client.post(f"/anomalies/scan?product_id={pid}").json()
    assert scan["reading_first"] is True and scan["detected"] == []
    r = client.post("/investigations", json={"product_id": pid, "description": "why is login failing"})
    assert r.status_code == 409
    assert client.get(f"/sources?product_id={pid}").json()["reading_first"] is True


def test_chrome_web_store_is_offered_as_unavailable_not_connectable(api_db_r4):
    client, _ = api_db_r4
    avail = client.get("/sources/available").json()
    assert "chrome_web_store" in {u["source"] for u in avail["unavailable"]}
    r = client.post("/sources/connect", json={"source": "chrome_web_store", "identifier": "abc"})
    assert r.status_code == 422


def test_week_on_week_rating_needs_enough_reviews_in_both_weeks():
    from echolens.db.models import Review
    from echolens.onboarding.snapshot import health_snapshot
    _, Session = _db()
    with Session() as s:
        now = datetime(2026, 10, 20, 12)
        for i in range(5):     # the KeePassXC case: a handful a week
            s.add(Review(source="play_store", ext_id=f"a{i}", rating=1 if i == 0 else 5, text="x",
                         created_at=now, product="K"))
            s.add(Review(source="play_store", ext_id=f"b{i}", rating=5, text="x",
                         created_at=datetime(2026, 10, 10, 12), product="K"))
        s.commit()
        snap = health_snapshot(s, "K")
    assert snap["rating_delta"] is None
    assert snap["rating_basis"] == "window"


def test_a_rescan_closes_untouched_spikes_it_no_longer_finds():
    from echolens.db.models import AnomalyEvent, Investigation, Product
    from echolens.detector.detect import _retire_untouched_issue_spikes
    _, Session = _db()
    with Session() as s:
        p = Product(name="K"); s.add(p); s.flush()
        def spike(slug):
            ev = AnomalyEvent(slug=slug, type="issue_velocity_surge", metric=slug, delta=1, z=1,
                              window="7d", description="", status="pending", product_id=p.id)
            s.add(ev); s.flush(); return ev
        junk, real, worked = spike("p1-auto-issues-brief"), spike("p1-auto-issues-quick"), spike("p1-auto-issues-tray")
        s.add(Investigation(anomaly_id=worked.id, status="running", product_id=p.id))
        s.flush()
        _retire_untouched_issue_spikes(s, p.id, {"p1-auto-issues-quick"})
        assert (junk.status, real.status, worked.status) == ("closed", "pending", "pending")


def test_sources_that_cannot_run_here_show_as_off_not_broken(api_db_r4, monkeypatch):
    from echolens.config import settings
    from echolens.db.models import CollectorState, Product
    monkeypatch.setattr(settings, "github_token", "")
    client, Session = api_db_r4
    with Session() as s:
        p = Product(name="Old", package_name="com.old"); s.add(p); s.flush()
        for src, st in (("chrome_web_store", "error"), ("github_discussions", "error"), ("play_store", "healthy")):
            s.add(CollectorState(source=src, identifier="x", product="Old", product_id=p.id, status=st,
                                 last_error="boom" if st == "error" else None))
        s.commit(); pid = p.id
    rows = {c["source"]: c for c in client.get(f"/sources?product_id={pid}").json()["connected"]}
    assert rows["chrome_web_store"]["status"] == "Unavailable"
    assert rows["github_discussions"]["status"] == "Unavailable" and "token" in rows["github_discussions"]["why"]
    from echolens.collectors.registry import configured_sources, source_health
    with Session() as s:
        assert [c.source for c in configured_sources(s, pid)] == ["play_store"]
        assert [h["source"] for h in source_health(s, "Old")] == ["play_store"]
