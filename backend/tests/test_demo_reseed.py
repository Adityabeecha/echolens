"""Reseeding the demo: a long-lived deploy's demo gets re-dated to today, and
nothing outside the `is_demo` product is ever read, moved or deleted.

FK enforcement is ON (like production Postgres), so a purge that misses a table
fails here instead of on the live database.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from echolens.config import settings
from echolens.db import session as db_session
from echolens.db.models import (AnomalyEvent, Base, Investigation, Product, Review,
                                ThemeOverride)
from echolens.synthetic.demo_story import demo_is_stale, reseed_demo, seed_demo


@pytest.fixture()
def Session_(monkeypatch):
    import echolens.llm.openai_client as oc

    class Refuse:
        def __init__(self, *a, **k):
            raise AssertionError("a demo reseed must never build a live LLM client")

    monkeypatch.setattr(oc, "OpenAIClient", Refuse)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def _fk(dbapi_conn, _rec):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_session, "_engine", engine)
    monkeypatch.setattr(db_session, "_SessionLocal", S)
    monkeypatch.setattr(db_session, "get_engine", lambda db_url=None: engine)
    monkeypatch.setattr(settings, "echolens_env", "dev", raising=False)
    return S


def _demo(s):
    return s.scalars(select(Product).where(Product.is_demo.is_(True))).one()


def _real_product(s) -> int:
    """A real workspace next to the demo, with a case and a theme rename."""
    p = Product(name="Acme")
    s.add(p)
    s.flush()
    old = datetime(2026, 7, 1)
    s.add(Review(source="play_store", ext_id="acme_1", rating=1, text="login loop",
                 created_at=old, product="Acme"))
    a = AnomalyEvent(slug="acme-a", type="volume_spike", metric="login", delta=1.0, z=3.0,
                     window="7d", description="d", status="investigating", product_id=p.id)
    s.add(a)
    s.flush()
    s.add(Investigation(anomaly_id=a.id, status="resolved", budget_tier="standard",
                        product_id=p.id))
    s.add(ThemeOverride(product_id=p.id, slug="login", label="Login loop"))
    s.flush()
    return p.id


def _age_demo(s, days: int) -> None:
    """Pretend the demo was seeded `days` ago — the live deploy's situation."""
    demo = _demo(s)
    for r in s.scalars(select(Review).where(Review.product == demo.name)).all():
        r.created_at = r.created_at - timedelta(days=days)
    s.flush()


def test_a_stale_demo_is_redated_and_real_products_are_untouched(Session_):
    with Session_() as s:
        seed_demo(s)
        demo_id = _demo(s).id
        real_id = _real_product(s)
        s.add(ThemeOverride(product_id=demo_id, slug="battery", muted=True))
        _age_demo(s, 90)
        s.commit()
        assert demo_is_stale(s)
        n_reviews = s.scalar(select(func.count(Review.id)).where(Review.product == _demo(s).name))

        counts = reseed_demo(s)
        s.commit()

        demo = _demo(s)
        assert demo.id == demo_id == counts["product_id"]     # same id: links survive
        assert counts["story"]["cases"] >= 4
        assert not demo_is_stale(s)
        latest = s.scalar(select(func.max(Review.created_at)).where(Review.product == demo.name))
        assert latest.replace(tzinfo=None) > datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=2)
        # No duplicates: the old corpus went before the new one came in.
        assert s.scalar(select(func.count(Review.id)).where(Review.product == demo.name)) == n_reviews
        # The demo's own overrides are reset with it.
        assert s.scalars(select(ThemeOverride).where(ThemeOverride.product_id == demo_id)).first() is None

        # The real product: every row still there, still its own.
        assert s.get(Product, real_id).is_demo is False
        assert s.scalar(select(func.count(Review.id)).where(Review.product == "Acme")) == 1
        assert s.scalar(select(func.count(Investigation.id)).where(
            Investigation.product_id == real_id)) == 1
        assert s.scalars(select(ThemeOverride).where(ThemeOverride.product_id == real_id)).one().label \
            == "Login loop"


def test_no_demo_product_means_nothing_is_created(Session_):
    with Session_() as s:
        _real_product(s)
        s.commit()
        assert demo_is_stale(s) is False
        assert reseed_demo(s) == {"skipped": "no demo product"}
        assert s.scalar(select(func.count(Product.id))) == 1
        assert s.scalar(select(func.count(Review.id))) == 1


def test_refresh_is_a_noop_while_fresh_and_force_is_admin_only(Session_):
    from echolens.api.app import _refresh_demo, demo_refresh
    with Session_() as s:
        seed_demo(s)
        s.commit()
    assert demo_refresh(force=False, user={"role": "reviewer"}) == {"status": "fresh"}
    assert _refresh_demo() == {"status": "fresh"}
    with pytest.raises(HTTPException) as err:
        demo_refresh(force=True, user={"role": "reviewer"})
    assert err.value.status_code == 403
    with Session_() as s:
        _age_demo(s, 30)
        s.commit()
    out = _refresh_demo()
    assert out["status"] == "refreshed", out
    with Session_() as s:
        assert not demo_is_stale(s)


def test_deleting_a_product_also_removes_its_theme_overrides(Session_):
    from fastapi.testclient import TestClient
    from echolens.api.app import app
    from echolens.db.models import CaseMerge
    with Session_() as s:
        pid = _real_product(s)
        a = s.scalars(select(AnomalyEvent).where(AnomalyEvent.product_id == pid)).one()
        dup = Investigation(anomaly_id=a.id, status="merged", budget_tier="standard", product_id=pid)
        s.add(dup)
        s.flush()
        keep = s.scalars(select(Investigation).where(Investigation.product_id == pid,
                                                     Investigation.status == "resolved")).one()
        s.add(CaseMerge(source_id=dup.id, target_id=keep.id))
        s.commit()
    r = TestClient(app).delete(f"/products/{pid}?confirm=Acme")
    assert r.status_code == 200, r.text
    with Session_() as s:
        assert s.scalar(select(func.count(ThemeOverride.id))) == 0
        assert s.scalar(select(func.count(CaseMerge.id))) == 0
        assert s.scalar(select(func.count(Review.id))) == 0


def test_seeded_exhibits_quote_the_real_text(Session_):
    """Every demo exhibit shows the cited item's own words, not a stand-in."""
    from echolens.db.models import EvidenceRow
    with Session_() as s:
        seed_demo(s)
        s.commit()
        demo = _demo(s)
        inv_ids = [i.id for i in s.scalars(select(Investigation).where(
            Investigation.product_id == demo.id)).all()]
        rows = s.scalars(select(EvidenceRow).where(EvidenceRow.investigation_id.in_(inv_ids))).all()
        assert rows
        stand_ins = {"the complaint as written", "the release note", "the engineering report",
                     "one community report"}
        for e in rows:
            assert e.snippet and e.snippet.strip().lower() not in stand_ins, (e.eid, e.snippet)
