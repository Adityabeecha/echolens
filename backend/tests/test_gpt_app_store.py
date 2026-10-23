"""App Store RSS collection through injected feeds and isolated SQLite."""
from datetime import datetime

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from echolens.collectors.app_store import AppStoreCollector
from echolens.collectors.registry import SourceConfig, add_source
from echolens.db.models import Base, CollectorState, Review


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def entry(rid="1001", date="2026-10-20T12:00:00Z", **changes):
    return {"id": {"label": rid}, "im:rating": {"label": "2"},
            "title": {"label": "Crashes on launch"},
            "content": {"label": "Opening large videos crashes the app."},
            "im:version": {"label": "4.2.1"}, "updated": {"label": date}, **changes}


@pytest.fixture
def payload():
    return {"feed": {"entry": [
        {"id": {"label": "https://apps.apple.com/us/app/test/id123"},
         "im:name": {"label": "Test app"}},  # metadata, not a review
        entry(), entry("1002", "2026-10-21T10:00:00-07:00"),
    ]}}


def test_feed_fields_dedup_and_watermark(db, payload):
    collector = AppStoreCollector("123", "Video", fetch_fn=lambda: payload)
    result = collector.run(db)
    assert result.ok and result.inserted == 2
    rows = db.scalars(select(Review).order_by(Review.created_at)).all()
    assert rows[0].ext_id.startswith("appstore:123:")
    assert rows[0].source == "app_store" and rows[0].product == "Video"
    assert rows[0].rating == 2 and rows[0].version == "4.2.1"
    assert rows[0].text == "Crashes on launch\n\nOpening large videos crashes the app."
    assert rows[0].created_at == datetime(2026, 10, 20, 12)
    assert result.watermark == "2026-10-21T17:00:00+00:00"
    assert collector.run(db).inserted == 0
    assert len(db.scalars(select(Review)).all()) == 2
    state = db.scalars(select(CollectorState)).one()
    assert state.status == "healthy" and state.identifier == "123"


def test_incremental_collection_filters_older_and_equal_dates(db):
    AppStoreCollector("123", "Video", fetch_fn=lambda: [entry()]).run(db)
    collector = AppStoreCollector("123", "Video", fetch_fn=lambda: [
        entry("older", "2026-10-19T00:00:00Z"), entry(),
        entry("new", "2026-10-22T03:00:00Z")])
    result = collector.run(db)
    assert result.ok and result.inserted == 1 and result.fetched == 1
    assert result.watermark == "2026-10-22T03:00:00+00:00"


def test_watermark_accepts_naive_prior_timestamp():
    collector = AppStoreCollector("123", fetch_fn=lambda: [entry()])
    assert len(collector.fetch("2026-10-19T12:00:00", 10)) == 1


def test_ids_are_qualified_by_app_and_product(db):
    collectors = [AppStoreCollector("123", "Video", fetch_fn=lambda: [entry()]),
                  AppStoreCollector("456", "Video", fetch_fn=lambda: [entry()]),
                  AppStoreCollector("123", "Other", fetch_fn=lambda: [entry()])]
    assert [c.run(db).inserted for c in collectors] == [1, 1, 1]
    ids = [r.ext_id for r in db.scalars(select(Review)).all()]
    assert len(set(ids)) == 3
    assert ids[0].startswith("appstore:123:") and ids[1].startswith("appstore:456:")


@pytest.mark.parametrize("broken", [
    None, "not an entry", {}, {"updated": {"label": "invalid"}},
    {"updated": {"label": []}}, {"im:rating": {"label": "garbage"}},
    {"im:rating": {"label": "0"}}, {"im:rating": {"label": "6"}},
    {"im:rating": {"label": "2.5"}}, {"im:rating": None},
    {"id": {"label": ""}}, {"id": {"label": []}},
    {"title": None, "content": {"label": []}},
])
def test_malformed_entry_is_skipped_without_poisoning_batch(db, broken):
    bad = {**entry("bad"), **broken} if isinstance(broken, dict) and broken else broken
    result = AppStoreCollector("123", fetch_fn=lambda: [bad, entry()]).run(db)
    assert result.ok and result.inserted == 1 and result.failed_items == 0
    assert result.watermark == "2026-10-20T12:00:00+00:00"
    assert len(db.scalars(select(Review)).all()) == 1


@pytest.mark.parametrize("identifier", [
    "123", " 123 ", "https://apps.apple.com/us/app/video/id123",
    "https://apps.apple.com/gb/app/id123?l=en-GB", "https://apps.apple.com/app/video/id123/",
])
def test_registry_accepts_and_canonicalizes_ids_and_store_urls(db, identifier):
    state = add_source(db, "app_store", identifier, "Video")
    assert state.identifier == "123"
    collector = SourceConfig("app_store", identifier, "Video").build()
    assert isinstance(collector, AppStoreCollector) and collector.identifier == "123"
    assert add_source(db, "app_store", "123", "Video").id == state.id


@pytest.mark.parametrize("identifier", [
    "", "id123", "123abc", "12/34", "１２３", "https://example.com/app/id123",
    "https://apps.apple.com.evil.test/us/app/id123", "https://apps.apple.com/us/app/no-id",
    "https://apps.apple.com/us/app/id123abc", "https://apps.apple.com@evil.test/app/id123",
])
def test_invalid_identifier_is_rejected_before_registry_write(db, identifier):
    with pytest.raises(ValueError):
        AppStoreCollector(identifier)
    with pytest.raises(ValueError):
        add_source(db, "app_store", identifier, "Video")
    assert db.scalars(select(CollectorState)).all() == []


def test_existing_legacy_review_is_not_inserted_again(db):
    import hashlib
    tag = hashlib.sha1(b"Video").hexdigest()[:6]
    db.add(Review(source="app_store", ext_id=f"as_{tag}_1001", product="Video",
                  rating=2, text="Existing review", created_at=datetime(2026, 10, 20, 12)))
    db.flush()
    result = AppStoreCollector("123", "Video", fetch_fn=lambda: [entry()]).run(db)
    assert result.ok and result.inserted == 0 and result.skipped_duplicate == 1
    assert len(db.scalars(select(Review)).all()) == 1


def test_live_fetch_uses_up_to_ten_public_feed_pages_offline(db, monkeypatch):
    urls = []
    def handler(request):
        urls.append(str(request.url))
        return httpx.Response(200, json={"feed": {"entry": [entry(str(len(urls)))]}})
    client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client(
        transport=httpx.MockTransport(handler), **kwargs))
    result = AppStoreCollector("123", "Video").run(db, limit=500)
    assert result.ok and result.inserted == 10
    assert urls == [f"https://itunes.apple.com/us/rss/customerreviews/page={n}/id=123/sortby=mostrecent/json"
                    for n in range(1, 11)]


def test_pagination_stops_at_an_empty_feed(db, monkeypatch):
    urls = []
    def handler(request):
        urls.append(str(request.url))
        return httpx.Response(200, json={"feed": {"entry": [entry()] if len(urls) == 1 else []}})
    client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client(
        transport=httpx.MockTransport(handler), **kwargs))
    result = AppStoreCollector("123", "Video").run(db, limit=500)
    assert result.ok and result.inserted == 1 and len(urls) == 2


def test_duplicate_ids_are_upserted_even_without_watermark_filter(db):
    result = AppStoreCollector("123", "Video").run(db, prefetched=[entry(), entry()])
    assert result.ok and result.inserted == 1 and result.skipped_duplicate == 1
    assert len(db.scalars(select(Review)).all()) == 1


def test_failed_page_keeps_previous_watermark_and_does_not_ingest_partial_fetch(db, monkeypatch):
    collector = AppStoreCollector("123", "Video", fetch_fn=lambda: [entry()])
    first = collector.run(db)
    calls = []
    def handler(request):
        calls.append(str(request.url))
        if len(calls) == 1:
            return httpx.Response(200, json={"feed": {"entry": [entry("new", "2026-10-22T00:00:00Z")]}})
        return httpx.Response(503, json={})
    client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client(
        transport=httpx.MockTransport(handler), **kwargs))
    result = AppStoreCollector("123", "Video").run(db)
    state = db.scalars(select(CollectorState)).one()
    assert not result.ok and "503" in result.error
    assert state.watermark == first.watermark and state.status == "error"
    assert len(db.scalars(select(Review)).all()) == 1
    assert len(calls) == 2


@pytest.mark.parametrize("payload", [{}, {"feed": []}, {"feed": {"entry": "invalid"}}])
def test_malformed_feed_is_an_error_not_a_healthy_empty_run(db, payload):
    result = AppStoreCollector("123", fetch_fn=lambda: payload).run(db)
    assert not result.ok and result.error and result.inserted == 0
    assert db.scalars(select(CollectorState)).one().watermark is None


def test_single_review_envelope_and_country_override(db, monkeypatch):
    urls = []
    def handler(request):
        urls.append(str(request.url))
        return httpx.Response(200, json={"feed": {"entry": entry()}})
    client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client(
        transport=httpx.MockTransport(handler), **kwargs))
    result = AppStoreCollector("123", country="GB").run(db, limit=1)
    assert result.ok and result.inserted == 1
    assert urls == ["https://itunes.apple.com/gb/rss/customerreviews/page=1/id=123/sortby=mostrecent/json"]


def test_registry_uses_canonical_default_product_for_store_url(db):
    first = add_source(db, "app_store", "https://apps.apple.com/us/app/video/id123")
    second = add_source(db, "app_store", "123")
    assert first.id == second.id and first.product == "123"
