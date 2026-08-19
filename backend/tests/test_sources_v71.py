"""v7.1 tests: App Store collector (iTunes RSS, injected), universal CSV import,
and the deeper-evidence caps."""
from __future__ import annotations

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from echolens.collectors.app_store import AppStoreCollector
from echolens.db.models import Base, Review
from echolens.importers.csv_reviews import import_reviews_csv


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


# ── App Store collector (injected iTunes RSS payload) ───────────────────

def _rss_entry(rid, rating, text, version, updated):
    return {
        "id": {"label": rid},
        "im:rating": {"label": str(rating)},
        "content": {"label": text},
        "im:version": {"label": version},
        "updated": {"label": updated},
    }


def test_app_store_collector_ingests_and_dedups():
    s = _session()
    entries = [
        _rss_entry("r1", 1, "app crashes on launch since the update", "3.2.0", "2026-07-15T10:00:00-07:00"),
        _rss_entry("r2", 5, "love it", "3.2.0", "2026-07-14T09:00:00-07:00"),
    ]
    c = AppStoreCollector("324684580", product="Acme", fetch_fn=lambda: entries)
    res = c.run(s)
    assert res.inserted == 2 and res.error is None
    assert s.scalar(select(func.count(Review.id)).where(Review.source == "app_store")) == 2
    # re-run is idempotent (the watermark skips already-seen reviews)
    res2 = AppStoreCollector("324684580", product="Acme", fetch_fn=lambda: entries).run(s)
    assert res2.inserted == 0
    assert s.scalar(select(func.count(Review.id)).where(Review.source == "app_store")) == 2


# ── universal CSV import ────────────────────────────────────────────────

def test_csv_import_flexible_headers_and_idempotent():
    s = _session()
    csv_text = (
        "Rating,Review,Date,Version\n"
        "1,Battery drains fast after the update,2026-07-10,4.1.0\n"
        "5,Great app,2026-07-11,4.1.0\n"
        ",,2026-07-12,\n"                      # empty text → skipped
    )
    r = import_reviews_csv(s, csv_text, product="Acme", source="app_store")
    assert r["imported"] == 2 and r["skipped"] == 1 and r["total"] == 3
    rows = s.scalars(select(Review)).all()
    assert {row.rating for row in rows} == {1, 5}
    assert all(row.product == "Acme" and row.source == "app_store" for row in rows)
    # re-import same file → all dedup
    r2 = import_reviews_csv(s, csv_text, product="Acme", source="app_store")
    assert r2["imported"] == 0 and r2["skipped"] == 3


def test_csv_import_alternate_column_names():
    s = _session()
    csv_text = "score,content,created_at\n2,slow to load,2026-06-01\n"
    r = import_reviews_csv(s, csv_text)
    assert r["imported"] == 1
    row = s.scalars(select(Review)).first()
    assert row.rating == 2 and "slow to load" in row.text


# ── deeper-evidence caps ────────────────────────────────────────────────

def test_evidence_caps_raised():
    from echolens.config import MAX_EVIDENCE_PER_UPDATE, TOOL_RESULT_MAX_ITEMS
    assert TOOL_RESULT_MAX_ITEMS >= 12          # more reviews surfaced per search
    assert MAX_EVIDENCE_PER_UPDATE >= 5         # more evidence kept per tool result
