from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from echolens.db.models import Base, EvidenceRow, Finding, Investigation, Product, Release, Review


@pytest.fixture()
def story(monkeypatch):
    import echolens.db.session as db
    from echolens.api.app import app

    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    monkeypatch.setattr(db, "get_engine", lambda db_url=None: engine)
    monkeypatch.setattr(db, "_SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with sessionmaker(bind=engine, expire_on_commit=False)() as s:
        product = Product(name="Test app")
        other = Product(name="Other app")
        s.add_all([product, other])
        s.flush()
        inv = Investigation(product_id=product.id, status="resolved")
        s.add(inv)
        s.flush()
        finding = Finding(investigation_id=inv.id, product_id=product.id,
            summary="Sync crashes after uploads", confidence=.89,
            json={"impact": {"terms": ["sync crashes"]}, "supported_hypothesis": "H1"})
        s.add(finding)
        s.add(Release(product=product.name, version="3.2.0", notes="Background sync",
                      released_at=now - timedelta(days=10)))
        # Prior ratings: five 5-star reviews. Recent: one 1-star sync complaint
        # and four 1-star battery complaints. Only sync contributes to this card.
        for i in range(5):
            s.add(Review(product=product.name, ext_id=f"old{i}", rating=5,
                         text="Works well", created_at=now - timedelta(days=20)))
        for i in range(5):
            s.add(Review(product=product.name, ext_id=f"new{i}", rating=1,
                         text="Sync crashes after upload" if i == 0 else "Battery drains",
                         created_at=now - timedelta(days=2 if i == 0 else 0)))
        s.add_all([
            EvidenceRow(investigation_id=inv.id, eid="ev_001", source="play_store", ref="new0",
                        snippet="Sync crashes after upload", retrieved_by="search_reviews",
                        json={"supports": ["H1"]}),
            EvidenceRow(investigation_id=inv.id, eid="ev_002", source="release_notes", ref="3.2.0",
                        snippet="Background sync", retrieved_by="get_release_notes",
                        json={"supports": ["H1"], "meta": {"version": "3.2.0"}}),
            Review(product=other.name, ext_id="new0", rating=1, text="Sync crashes elsewhere",
                   created_at=now - timedelta(days=60)),
        ])
        s.commit()
        yield TestClient(app), s, product, other, inv, finding, now
    engine.dispose()


def focus(story):
    client, _, product, _, inv, _, _ = story
    response = client.get(f"/today/overview?product_id={product.id}&investigation_id={inv.id}")
    assert response.status_code == 200
    return response.json()["focus"]


def test_focus_measures_own_theme_and_preserves_the_cited_quote(story):
    data = focus(story)
    assert data["one_star_share"] == {"matching": 1, "total": 5, "pct": 20.0, "days": 30}
    assert data["rating_drag"] == .8  # 1/5 * (1 - 5), not the whole 4-star fall.
    assert data["quote"]["text"] == "Sync crashes after upload"
    assert data["release"]["days_after"] == 8


def test_later_release_is_never_presented_as_the_cause(story):
    _, s, product, _, _, _, now = story
    release = s.query(Release).filter_by(product=product.name).one()
    release.released_at = now - timedelta(days=1)
    s.commit()
    assert focus(story)["release"] is None


def test_older_matching_complaint_blocks_an_apparent_release_link(story):
    _, s, product, _, _, _, now = story
    s.add(Review(product=product.name, ext_id="early", rating=2,
                 text="Sync crashes after upload", created_at=now - timedelta(days=70)))
    s.commit()
    assert focus(story)["release"] is None


@pytest.mark.parametrize("change", ["praise", "struck"])
def test_quote_cannot_be_praise_rejected_or_invented(story, change):
    _, s, product, _, inv, finding, _ = story
    if change == "praise":
        row = s.query(Review).filter_by(product=product.name, ext_id="new0").one()
        row.rating, row.text = 5, "Wonderful app"
    elif change == "struck":
        finding.json = {**finding.json, "rejected_evidence": [{"eid": "ev_001"}]}
    s.commit()
    assert focus(story)["quote"] is None


def test_quote_is_retrieved_from_its_review_ref_not_the_evidence_paraphrase(story):
    _, s, _, _, inv, _, _ = story
    s.query(EvidenceRow).filter_by(investigation_id=inv.id, eid="ev_001").one().snippet = "Invented quote"
    s.commit()
    assert focus(story)["quote"]["text"] == "Sync crashes after upload"


def test_focus_rejects_another_products_investigation(story):
    client, _, _, other, inv, _, _ = story
    assert client.get(f"/today/overview?product_id={other.id}&investigation_id={inv.id}").status_code == 404


def test_missing_theme_does_not_become_a_false_measurement(story):
    _, s, _, _, _, finding, _ = story
    finding.json = {}
    s.commit()
    data = focus(story)
    assert data["rating_drag"] is None
    assert data["one_star_share"]["pct"] is None
    assert data["release"] is None


def test_small_samples_do_not_claim_a_percentage_or_rating_drag(story):
    _, s, product, _, _, _, _ = story
    s.query(Review).filter_by(product=product.name, ext_id="new4").delete()
    s.commit()
    data = focus(story)
    assert data["rating_drag"] is None
    assert data["one_star_share"]["pct"] is None
    assert data["one_star_share"]["matching"] == 1


def test_overlapping_themes_keep_their_own_one_star_numerators(story):
    client, s, product, _, _, _, _ = story
    row = s.query(Review).filter_by(product=product.name, ext_id="new0").one()
    row.text = "Sync crashes and battery drains after upload"
    other = Investigation(product_id=product.id, status="resolved")
    s.add(other)
    s.flush()
    s.add(Finding(investigation_id=other.id, product_id=product.id,
                  summary="Battery drains", confidence=.8, json={"impact": {"terms": ["battery drains"]}}))
    s.commit()
    assert focus(story)["one_star_share"]["matching"] == 1
    data = client.get(f"/today/overview?product_id={product.id}&investigation_id={other.id}").json()["focus"]
    assert data["one_star_share"]["matching"] == 5


def test_watch_exposes_its_actual_window_and_today_dismissal(story):
    from echolens.db.models import FixWatch
    client, s, product, _, inv, finding, now = story
    watch = FixWatch(product_id=product.id, investigation_id=inv.id, finding_id=finding.id,
                     repo="local/demo", issue_number=1, issue_url="", metric="sync crashes",
                     status="watching", window_days=21, fix_date=now - timedelta(days=5))
    s.add(watch)
    s.commit()
    data = client.get(f"/fixwatch?product_id={product.id}").json()["watches"][0]
    assert data["window_days"] == 21
    assert data["dismissed_today"] is False
