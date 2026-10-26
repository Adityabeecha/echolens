"""All products, Sources import, and Settings: the CSV column mapping and its
preview, detector sensitivity, admin alert settings, the costs breakdown, and
the product rows' rating line, topics and top-problem verdict."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import echolens.db.session as db_session
from echolens.db.models import (
    AnomalyEvent, Base, Finding, Investigation, LLMCall, Product, Review, Setting)
from echolens.detector import detect
from echolens.importers.csv_reviews import guess_mapping, import_reviews_csv, preview_reviews_csv

NOW = datetime.now(timezone.utc)


@pytest.fixture()
def Session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, expire_on_commit=False), eng


# ── CSV column mapping ──────────────────────────────────────────────────

ODD = ("Comment,Stars,When,Build,Store,Who\n"
       "Crashes on export,1,2026-10-01,3.2.0,App Store,ana\n"
       ",2,2026-10-02,3.2.0,App Store,bo\n"
       "Love it,great,2026-10-03,3.2.0,Google Play,cy\n"
       "Crashes on export,1,2026-10-01,3.2.0,App Store,ana\n"
       "Slow to open,2,,3.2.1,iOS,di\n")
MAPPING = {"text": "Comment", "rating": "Stars", "date": "When", "version": "Build",
           "source": "Store", "author": "Who"}


def test_mapping_reads_columns_the_aliases_never_would(Session):
    S, _ = Session
    with S() as s:
        r = import_reviews_csv(s, ODD, product="P", source="csv", mapping=MAPPING)
        assert (r["imported"], r["skipped"], r["total"]) == (2, 3, 5)
        assert r["reasons"] == {"no review text": 1, "no rating from 1 to 5": 1,
                                "already imported, or repeated in the file": 1}
        rows = {x.text: x for x in s.scalars(select(Review)).all()}
        assert rows["Crashes on export"].version == "3.2.0" and rows["Crashes on export"].source == "app_store"
        assert rows["Slow to open"].source == "app_store" and rows["Slow to open"].created_at.year == 1970  # undated
        assert r["undated"] == 1


def test_mapping_is_checked_and_text_is_required(Session):
    S, _ = Session
    with S() as s:
        with pytest.raises(ValueError, match="review text"):
            import_reviews_csv(s, ODD, product="P", mapping={**MAPPING, "text": None})
        with pytest.raises(ValueError, match="no column named"):
            import_reviews_csv(s, ODD, product="P", mapping={**MAPPING, "rating": "Score"})


def test_without_a_mapping_the_importer_reads_what_it_always_read(Session):
    S, _ = Session
    csv_text = "text,rating,date,source\nBattery drains,1,2026-10-01,App Store\n"
    with S() as s:
        assert import_reviews_csv(s, csv_text, product="P", source="csv")["imported"] == 1
        # A per-row Source column is ignored unless someone matched it.
        assert s.scalars(select(Review)).one().source == "csv"
        # And the same file, now matched by hand, is recognised as already imported.
        again = import_reviews_csv(s, csv_text, product="P", source="csv",
                                   mapping={"text": "text", "rating": "rating", "date": "date"})
        assert again["imported"] == 0 and again["reasons"] == {"already imported, or repeated in the file": 1}


def test_guess_and_preview_write_nothing(Session):
    S, _ = Session
    assert guess_mapping(["Review", "Score", "created_at", "app_version", "Platform", "user"]) == {
        "text": "Review", "rating": "Score", "version": "app_version", "date": "created_at",
        "source": None, "author": "user"}
    with S() as s:
        p = preview_reviews_csv(s, ODD, product="P", mapping=MAPPING, sample=2)
        assert p["columns"][:2] == ["Comment", "Stars"] and len(p["rows"]) == 2
        assert (p["would_import"], p["skipped"], p["total"]) == (2, 3, 5)
        assert [x["row"] for x in p["problems"]] == [3, 4, 5]
        assert s.scalars(select(Review)).all() == []
        assert preview_reviews_csv(s, ODD, product="P")["mapping"]["text"] == "Comment"   # guessed
        unguessable = preview_reviews_csv(s, "Notes,Score\nhello,1\n", product="P")
        assert unguessable["error"] and unguessable["mapping"]["text"] is None


# ── detector sensitivity ────────────────────────────────────────────────

def _scan_with(monkeypatch, s, pid, z_values):
    cands = [detect.Candidate(slug=f"auto-theme-t{i}", type="theme_volume_surge", metric=f"t{i}",
                              delta=1.0, z=z, window="7d", description="d", severity=detect._severity(z))
             for i, z in enumerate(z_values)]
    monkeypatch.setattr(detect, "detect_volume_spike", lambda *a, **k: None)
    monkeypatch.setattr(detect, "detect_rating_drop", lambda *a, **k: None)
    monkeypatch.setattr(detect, "detect_theme_surges", lambda *a, **k: list(cands))
    monkeypatch.setattr(detect, "detect_issue_velocity", lambda *a, **k: [])
    monkeypatch.setattr(detect, "very_low_volume", lambda *a, **k: False)
    return sorted(round(e.z, 1) for e in detect.scan(s, as_of=NOW, product="P", product_id=pid))


def test_default_sensitivity_keeps_every_spike(Session, monkeypatch):
    S, _ = Session
    with S() as s:
        p = Product(name="P")
        s.add(p)
        s.flush()
        assert detect.min_case_z(s, p.id) == detect.MIN_CASE_Z == 1.0
        assert _scan_with(monkeypatch, s, p.id, [1.2, 2.2, 3.4]) == [1.2, 2.2, 3.4]


def test_raised_sensitivity_drops_weaker_spikes_per_product(Session, monkeypatch):
    S, _ = Session
    with S() as s:
        p = Product(name="P", limits_json={"detector_min_z": 2.5})
        s.add(p)
        s.flush()
        assert detect.min_case_z(s, p.id) == 2.5
        assert _scan_with(monkeypatch, s, p.id, [1.2, 2.2, 3.4]) == [3.4]   # a SEV2 below the bar drops too
        p.limits_json = {"detector_min_z": 9}
        assert detect.min_case_z(s, p.id) == detect.MAX_CASE_Z               # clamped, never above SEV1


# ── API: limits, alerts, costs, import, portfolio ───────────────────────

@pytest.fixture()
def api(Session, monkeypatch):
    S, eng = Session
    with S() as s:
        p, q = Product(name="Lumo", is_demo=True), Product(name="Other")
        s.add_all([p, q])
        s.flush()
        # Twelve weeks of reviews: a 4.5★ product falling to 2★ in the last weeks.
        for d in range(0, 84):
            rating = 2 if d < 14 else 5 if d % 2 else 4
            s.add(Review(source="play_store", ext_id=f"r{d}", rating=rating, text="sync drains battery",
                         product="Lumo", created_at=NOW - timedelta(days=d, hours=1)))
        anomaly = AnomalyEvent(slug="p1-battery", type="theme_volume_surge", metric="battery share of negatives",
                               delta=1.0, z=3.0, window="7d", description="battery", status="investigated",
                               product_id=p.id)
        s.add(anomaly)
        s.flush()
        inv = Investigation(status="resolved", product_id=p.id, anomaly_id=anomaly.id, budget_json={},
                            created_at=NOW - timedelta(days=1))
        s.add(inv)
        s.flush()
        s.add(Finding(investigation_id=inv.id, summary="Battery drain since 3.2.0", confidence=0.9, product_id=p.id,
                      json={"support_level": "supported", "confidence": 0.9,
                            "impact": {"affected_pct": 60.0, "affected_volume": 12, "rating_impact": 0.84,
                                       "measured": True}}))
        s.add(LLMCall(investigation_id=inv.id, product_id=p.id, agent="investigator", model="m",
                      tokens_in=10, tokens_out=10, cost=0.42, ms=1, created_at=NOW))
        s.commit()
        pid, qid = p.id, q.id
    monkeypatch.setattr(db_session, "_engine", eng)
    monkeypatch.setattr(db_session, "_SessionLocal", S)
    monkeypatch.setattr(db_session, "get_engine", lambda db_url=None: eng)
    from echolens.api.app import app
    c = TestClient(app)
    c.pid, c.qid, c.S, c.app = pid, qid, S, app
    return c


def _as(client, role):
    from echolens.auth import current_user
    client.app.dependency_overrides[current_user] = lambda: {"id": 7, "email": f"{role}@x.co", "role": role}


def test_sensitivity_is_an_admin_limit_within_bounds(api):
    try:
        _as(api, "reviewer")
        assert api.put(f"/settings/limits?product_id={api.pid}", json={"detector_min_z": 2.0}).status_code == 403
        _as(api, "admin")
        assert api.put(f"/settings/limits?product_id={api.pid}", json={"detector_min_z": 0.5}).status_code == 422
        r = api.put(f"/settings/limits?product_id={api.pid}", json={"detector_min_z": 2.0})
        assert r.status_code == 200 and r.json()["detector_min_z"] == 2.0
    finally:
        api.app.dependency_overrides.clear()
    with api.S() as s:
        assert detect.min_case_z(s, api.pid) == 2.0
        assert detect.min_case_z(s, api.qid) == 1.0                         # the other product is unchanged
    assert api.get(f"/costs/summary?product_id={api.pid}").json()["limits"]["detector_min_z"] == 2.0


def test_alert_settings_default_to_config_and_admins_change_them(api, monkeypatch):
    from echolens import notify
    from echolens.config import settings
    monkeypatch.setattr(settings, "alerts_enabled", True)
    monkeypatch.setattr(settings, "alert_instant_min_severity", 0.5)
    monkeypatch.setattr(settings, "auto_create_issue_on_approve", False)
    got = api.get("/settings/alerts").json()
    assert (got["alerts_enabled"], got["alert_instant_min_severity"], got["auto_create_issue_on_approve"]) == (True, 0.5, False)
    assert set(got) >= {"slack_connected", "github_connected"}
    try:
        _as(api, "reviewer")
        assert api.put("/settings/alerts", json={"alerts_enabled": False}).status_code == 403
        _as(api, "admin")
        assert api.put("/settings/alerts", json={"alert_instant_min_severity": 1.5}).status_code == 422
        r = api.put("/settings/alerts", json={"alerts_enabled": False, "auto_create_issue_on_approve": True})
        assert r.status_code == 200 and r.json()["alerts_enabled"] is False
        assert r.json()["alert_instant_min_severity"] == 0.5                 # untouched fields keep their value
    finally:
        api.app.dependency_overrides.clear()
    with api.S() as s:
        finding = s.scalars(select(Finding)).first()
        assert notify.notify_finding(s, finding)["routed"] == "disabled"    # the stored choice is what alerts read
        assert s.get(Setting, "alerts").value["auto_create_issue_on_approve"] is True


def test_costs_show_this_month_per_product_and_per_problem(api):
    body = api.get(f"/costs/summary?product_id={api.pid}").json()
    assert body["month_to_date"] == 0.42 and body["investigations_this_month"] == 1
    assert body["per_problem"] == 0.42
    rows = {r["product"]: r for r in body["by_product"]}
    assert rows["Lumo"]["month_to_date"] == 0.42 and rows["Lumo"]["investigations"] == 1
    assert rows["Other"]["month_to_date"] == 0.0


def test_import_preview_and_mapping_through_the_api(api):
    files = {"file": ("odd.csv", ODD.encode(), "text/csv")}
    prev = api.post(f"/import/reviews/preview?product_id={api.qid}", files=files,
                    data={"mapping": json.dumps(MAPPING)})
    assert prev.status_code == 200 and prev.json()["would_import"] == 2
    bad = api.post(f"/import/reviews/preview?product_id={api.qid}", files=files, data={"mapping": "{nope"})
    assert bad.status_code == 422
    r = api.post(f"/import/reviews?product_id={api.qid}", files=files, data={"mapping": json.dumps(MAPPING)})
    assert r.status_code == 200 and r.json()["imported"] == 2 and r.json()["skipped"] == 3
    with api.S() as s:
        assert s.scalars(select(Review).where(Review.product == "Other")).all()


def test_sources_name_unsupported_tools_honestly(api):
    assert {"Zendesk", "Intercom"} <= set(api.get(f"/sources?product_id={api.pid}").json()["available"])


def test_portfolio_row_has_the_rating_line_topics_and_top_problem_verdict(api):
    from echolens.portfolio import portfolio
    with api.S() as s:
        row = next(r for r in portfolio(s, as_of=NOW)["products"] if r["product"] == "Lumo")
    weeks = row["rating_weekly"]
    assert len(weeks) == 12 and weeks[-1] == 2.0 and weeks[0] > 4
    assert row["top_topics"] == ["battery"]
    top = row["top_problem"]
    assert top["support_level"] == "supported" and top["needs_review"] is False and top["rating_impact"] == 0.84
    assert row["confirmed_open"] == 1
