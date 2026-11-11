"""Phase 2: a product can be added from any one source, not only Google Play."""
import importlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from echolens.db import session as db_session
from echolens.db.models import Base, CollectorState, Product


@pytest.fixture()
def api(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_session, "_engine", engine)
    monkeypatch.setattr(db_session, "_SessionLocal", Session)
    monkeypatch.setattr(db_session, "get_engine", lambda db_url=None: engine)
    app_mod = importlib.import_module("echolens.api.app")
    monkeypatch.setattr(app_mod, "_onboard_bg", lambda *a: None)
    monkeypatch.setattr(app_mod, "_onboard_watchdog", lambda *a: None)
    return TestClient(app_mod.app), Session


def _sources(Session):
    with Session() as s:
        return {row.source for row in s.scalars(select(CollectorState))}


def test_app_store_only_product(api):
    client, Session = api
    r = client.post("/onboard", json={"app_store": "id1435127111", "product": "KeePassium"})
    assert r.status_code == 200, r.text
    assert r.json()["play_store"] is None
    assert _sources(Session) == {"app_store"}
    with Session() as s:
        prod = s.scalars(select(Product)).one()
        assert prod.name == "KeePassium" and prod.package_name is None


def test_github_only_product_is_named_after_the_repo(api):
    client, Session = api
    r = client.post("/onboard", json={"github": "https://github.com/nextcloud/server"})
    assert r.status_code == 200, r.text
    assert r.json()["product"] == "server"
    assert _sources(Session) == {"github"}


def test_no_source_at_all_is_a_clear_422(api):
    client, _ = api
    r = client.post("/onboard", json={"product": "Nothing"})
    assert r.status_code == 422
    assert "at least one place" in r.json()["detail"]
    # An unavailable source alone does not count as one.
    r = client.post("/onboard", json={"product": "Ext", "chrome_web_store": "aapbdbdomjkkjkaonfhkkikfgjllcleb"})
    assert r.status_code == 422


def test_a_search_term_alone_needs_a_typed_name(api):
    client, _ = api
    r = client.post("/onboard", json={"hacker_news": "Bitwarden"})
    assert r.status_code == 422 and "name" in r.json()["detail"]
    assert client.post("/onboard", json={"hacker_news": "Bitwarden", "product": "Bitwarden"}).status_code == 200


def test_play_store_still_works_and_is_still_validated(api):
    client, Session = api
    assert client.post("/onboard", json={"play_store": "not a package"}).status_code == 422
    r = client.post("/onboard", json={"play_store": "com.acme.app"})
    assert r.status_code == 200 and r.json()["product"] == "com.acme.app"
    assert _sources(Session) == {"play_store"}


def test_app_store_preview_reads_the_listing():
    from echolens.onboarding.preview import preview_app_store
    ok = preview_app_store("https://apps.apple.com/us/app/keepassium/id1435127111", fetch_fn=lambda i: {
        "trackName": "KeePassium", "artistName": "KeePassium Labs",
        "userRatingCount": 1234, "averageUserRating": 4.71})
    assert ok["ok"] and ok["identifier"] == "1435127111"
    assert ok["title"] == "KeePassium" and ok["score"] == 4.71
    missing = preview_app_store("1435127111", fetch_fn=lambda i: None)
    assert missing["kind"] == "not_found"
    assert preview_app_store("not-an-id")["kind"] == "invalid"

    def boom(_):
        raise RuntimeError("down")
    assert preview_app_store("1435127111", fetch_fn=boom)["kind"] == "unavailable"
