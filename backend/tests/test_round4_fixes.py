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
