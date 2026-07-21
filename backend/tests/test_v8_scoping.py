"""v8.0 tests: product scoping isolation (API-level) and scan/triage idempotency."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import echolens.db.session as db_session
from echolens.db.models import (
    AnomalyEvent, Base, Finding, FixWatch, Investigation, LLMCall, Product, Review)


def _seed_product(s, name, *, summary, slug, rating_text="battery drain awful"):
    """A product with its own corpus, anomaly, case, finding and cost row."""
    from datetime import datetime, timedelta, timezone
    p = Product(name=name)
    s.add(p); s.flush()
    now = datetime.now(timezone.utc)
    for i in range(6):
        s.add(Review(source="play_store", ext_id=f"{slug}_r{i}", rating=1, text=rating_text,
                     created_at=now - timedelta(days=i), product=name))
    a = AnomalyEvent(slug=slug, type="theme_volume_surge", metric=f"{name} metric",
                     delta=0.2, z=2.5, window="7d", description=f"{name} anomaly",
                     status="pending", product_id=p.id)
    s.add(a); s.flush()
    inv = Investigation(anomaly_id=a.id, status="resolved", opened_by="anomaly",
                        budget_tier="quick", budget_json={}, product_id=p.id)
    s.add(inv); s.flush()
    f = Finding(investigation_id=inv.id, summary=summary, confidence=0.85, status="approved",
                json={"summary": summary, "confidence": 0.85, "impact": {"impact_score": 0.5}},
                product_id=p.id)
    s.add(f); s.flush()
    s.add(LLMCall(investigation_id=inv.id, agent="investigator.plan", model="m",
                  tokens_in=100, tokens_out=50, cost=0.01, ms=10))
    s.add(FixWatch(finding_id=f.id, investigation_id=inv.id, repo="r/r", issue_number=p.id,
                   status="confirmed", terms=["battery", "drain"], metric="m",
                   baseline_rate=5.0, post_rate=0.0, confirmed_at=now, product_id=p.id))
    s.flush()
    return p, inv, f


@pytest.fixture()
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as s:
        _seed_product(s, "Alpha", summary="Alpha battery drain cause", slug="alpha-1")
        _seed_product(s, "Beta", summary="Beta checkout crash cause", slug="beta-1",
                      rating_text="checkout crash awful")
        s.commit()
    monkeypatch.setattr(db_session, "_engine", engine)
    monkeypatch.setattr(db_session, "_SessionLocal", Session)
    monkeypatch.setattr(db_session, "get_engine", lambda db_url=None: engine)
    import echolens.api.app as app_mod
    monkeypatch.setattr(app_mod, "_run_investigation_bg", lambda *a, **k: None)
    with Session() as s:
        ids = {p.name: p.id for p in s.scalars(select(Product)).all()}
    return TestClient(app_mod.app), ids, Session


# ── T1: no screen for product A may contain product B's rows ────────────

def test_every_screen_is_product_scoped(client):
    tc, ids, _ = client
    a, b = ids["Alpha"], ids["Beta"]

    # Case Feed
    slugs_a = {x["slug"] for x in tc.get(f"/anomalies?product_id={a}").json()["anomalies"]}
    slugs_b = {x["slug"] for x in tc.get(f"/anomalies?product_id={b}").json()["anomalies"]}
    assert slugs_a == {"alpha-1"} and slugs_b == {"beta-1"}

    # Archive
    arch_a = tc.get(f"/archive?product_id={a}").json()["rows"]
    assert arch_a and all("Alpha" in r["cause"] for r in arch_a)

    # Costs — only this product's LLM spend
    costs_a = tc.get(f"/costs/summary?product_id={a}").json()
    costs_b = tc.get(f"/costs/summary?product_id={b}").json()
    assert len(costs_a["rows"]) == 1 and len(costs_b["rows"]) == 1
    assert costs_a["rows"][0]["id"] != costs_b["rows"][0]["id"]

    # Product Health
    ov_a = tc.get(f"/overview?product_id={a}").json()
    assert ov_a["product"] == "Alpha" and ov_a["confirmed_fixes_total"] == 1

    # Patterns / Calibration / Themes
    assert tc.get(f"/patterns?product_id={a}").json()["product"] == "Alpha"
    assert tc.get(f"/calibration?product_id={a}").json()["product"] == "Alpha"
    assert tc.get(f"/themes?product_id={a}").json()["product"] == "Alpha"

    # Ask EchoLens answers only from the active product's cases
    ans_a = tc.post("/chat", json={"message": "tell me about the cause", "product_id": a}).json()
    ans_b = tc.post("/chat", json={"message": "tell me about the cause", "product_id": b}).json()
    cites_a = {c["investigation_id"] for c in (ans_a.get("citations") or [])}
    cites_b = {c["investigation_id"] for c in (ans_b.get("citations") or [])}
    assert cites_a and cites_b and cites_a.isdisjoint(cites_b)


def test_chat_says_no_investigations_for_empty_product(client):
    tc, _, Session = client
    with Session() as s:
        p = Product(name="Gamma")
        s.add(p); s.commit()
        gid = p.id
    r = tc.post("/chat", json={"message": "what is broken", "product_id": gid}).json()
    assert "no investigations" in r["text"].lower() and "gamma" in r["text"].lower()


def test_products_list_and_activate(client):
    tc, ids, _ = client
    body = tc.get("/products").json()
    assert {p["name"] for p in body["products"]} >= {"Alpha", "Beta"}
    assert tc.post(f"/products/{ids['Beta']}/activate").json()["active_product_id"] == ids["Beta"]


def test_activation_survives_a_refresh(client):
    """The switch must be READ BACK, not just echoed. Asserting only the activate
    response let a bug through where the write was silently skipped and the next
    boot snapped back to the first product."""
    tc, ids, _ = client
    tc.post(f"/products/{ids['Beta']}/activate")
    assert tc.get("/products").json()["active_product_id"] == ids["Beta"]
    tc.post(f"/products/{ids['Alpha']}/activate")
    assert tc.get("/products").json()["active_product_id"] == ids["Alpha"]


def test_delete_product_cascades_and_requires_typed_name(client):
    tc, ids, Session = client
    a = ids["Alpha"]
    assert tc.delete(f"/products/{a}?confirm=wrong").status_code == 422
    assert tc.delete(f"/products/{a}?confirm=Alpha").status_code == 200
    with Session() as s:
        assert s.scalars(select(Product).where(Product.name == "Alpha")).first() is None
        assert not s.scalars(select(AnomalyEvent).where(AnomalyEvent.product_id == a)).all()
        assert not s.scalars(select(Investigation).where(Investigation.product_id == a)).all()
        assert not s.scalars(select(Review).where(Review.product == "Alpha")).all()
    # the other product is untouched
    assert tc.get(f"/anomalies?product_id={ids['Beta']}").json()["anomalies"]


# ── T2: scan + triage are safe to press repeatedly ──────────────────────

def test_scan_is_idempotent_across_repeats(client):
    tc, ids, Session = client
    a = ids["Alpha"]
    counts = []
    for _ in range(3):
        tc.post(f"/anomalies/scan?product_id={a}")
        with Session() as s:
            counts.append(len(s.scalars(select(AnomalyEvent).where(
                AnomalyEvent.product_id == a)).all()))
    assert counts[0] == counts[1] == counts[2], f"scan created duplicates: {counts}"


def test_scan_plus_triage_three_times_keeps_case_count_stable(client, monkeypatch):
    tc, ids, Session = client
    a = ids["Alpha"]
    import echolens.orchestrator.triage as triage_mod
    from echolens.orchestrator.triage import Decision

    class FakeOrch:
        """Always proposes investigating every pending anomaly for the product."""
        def __init__(self, session, daily_limit=5, product_id=None):
            self.session, self.pid = session, product_id

        def triage(self, persist=True):
            stmt = select(AnomalyEvent).where(AnomalyEvent.status == "pending")
            if self.pid is not None:
                stmt = stmt.where(AnomalyEvent.product_id == self.pid)
            return [Decision(anomaly=x, decision="investigate", reason="r", budget_tier="quick")
                    for x in self.session.scalars(stmt).all()]

    monkeypatch.setattr(triage_mod, "Orchestrator", FakeOrch)
    counts = []
    for _ in range(3):
        tc.post(f"/anomalies/scan?product_id={a}")
        tc.post(f"/anomalies/triage?run=true&product_id={a}")
        with Session() as s:
            counts.append(len(s.scalars(select(Investigation).where(
                Investigation.product_id == a)).all()))
    assert counts[0] == counts[1] == counts[2], f"triage duplicated cases: {counts}"


def test_preview_triage_does_not_consume_the_pending_queue(client, monkeypatch):
    """run=false is a PREVIEW. It used to persist decisions and flip anomalies to
    'triaged', so the scheduled job (which never passed run=true) silently ate the
    queue and opened nothing — anomalies sat triaged forever with no case."""
    tc, ids, Session = client
    a = ids["Alpha"]
    import echolens.orchestrator.triage as triage_mod
    from echolens.orchestrator.triage import Decision

    class FakeOrch:
        def __init__(self, session, daily_limit=5, product_id=None):
            self.session, self.pid = session, product_id

        def triage(self, persist=True):
            rows = self.session.scalars(select(AnomalyEvent).where(
                AnomalyEvent.status == "pending",
                AnomalyEvent.product_id == self.pid)).all()
            ds = [Decision(anomaly=x, decision="investigate", reason="r", budget_tier="quick")
                  for x in rows]
            if persist:
                for d in ds:
                    d.anomaly.status = "triaged"
                self.session.flush()
            return ds

    monkeypatch.setattr(triage_mod, "Orchestrator", FakeOrch)

    def pending():
        with Session() as s:
            return len(s.scalars(select(AnomalyEvent).where(
                AnomalyEvent.product_id == a, AnomalyEvent.status == "pending")).all())

    before = pending()
    assert before, "fixture must have a pending anomaly for this to mean anything"
    body = tc.post(f"/anomalies/triage?product_id={a}").json()   # no run=true
    assert pending() == before, "a preview must leave the queue untouched"
    assert "preview" in body["summary"] and "nothing started" in body["summary"]


def test_triage_reports_already_triaged(client, monkeypatch):
    tc, ids, _ = client
    a = ids["Alpha"]
    import echolens.orchestrator.triage as triage_mod
    from echolens.orchestrator.triage import Decision

    class FakeOrch:
        def __init__(self, session, daily_limit=5, product_id=None):
            self.session, self.pid = session, product_id

        def triage(self, persist=True):
            x = self.session.scalars(select(AnomalyEvent).where(
                AnomalyEvent.slug == "alpha-1")).first()
            x.status = "pending"
            self.session.flush()
            return [Decision(anomaly=x, decision="investigate", reason="r", budget_tier="quick")]

    monkeypatch.setattr(triage_mod, "Orchestrator", FakeOrch)
    r = tc.post(f"/anomalies/triage?run=true&product_id={a}").json()
    assert r["skipped_already_triaged"] == 1  # alpha-1 already has a case
    assert "already triaged" in r["summary"] and "nothing new" in r["summary"]


# ── T4.3: duration formatting + sanity cap ──────────────────────────────

def test_duration_formatter():
    from echolens.api.app import _fmt_duration
    assert _fmt_duration(0) == "0s"
    assert _fmt_duration(45) == "45s"
    assert _fmt_duration(60) == "1m"
    assert _fmt_duration(80) == "1m 20s"
    assert _fmt_duration(3600) == "1h"
    assert _fmt_duration(7500) == "2h 5m"
    assert "m" in _fmt_duration(3291 * 60)  # never a raw "3291m"


def test_case_duration_flags_impossible_wall_clock():
    """A stored wall-clock beyond the tier cap is flagged, not shown as fact."""
    from datetime import datetime, timedelta, timezone
    from echolens.api.app import _case_duration
    from echolens.db.models import Investigation
    start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    sane = Investigation(anomaly_id=1, budget_tier="standard", budget_json={},
                         created_at=start, resolved_at=start + timedelta(minutes=12))
    txt, flagged = _case_duration(sane)
    assert txt == "12m" and flagged is False
    # 3291 minutes on a 45-min tier is impossible → flagged
    bad = Investigation(anomaly_id=1, budget_tier="standard", budget_json={},
                        created_at=start, resolved_at=start + timedelta(minutes=3291))
    txt, flagged = _case_duration(bad)
    assert flagged is True and txt.startswith(">")


def test_a_case_follows_its_anomalys_product_not_the_clients_claim(client):
    """Real bug: starting an investigation from the onboarding wizard sent the
    PREVIOUS product's id, so the case was filed under the wrong product (and
    'back' then landed on the wrong feed). The anomaly's product must win."""
    tc, ids, Session = client
    a, b = ids["Alpha"], ids["Beta"]
    with Session() as s:
        s.add(AnomalyEvent(slug="beta-2", type="theme_volume_surge", metric="m",
                           delta=0.2, z=2.5, window="7d", description="beta signal",
                           status="pending", product_id=b))
        s.commit()
    # client wrongly claims product A while opening B's anomaly
    r = tc.post("/investigations", json={"anomaly_slug": "beta-2", "tier": "quick",
                                         "product_id": a})
    assert r.status_code == 200
    with Session() as s:
        inv = s.get(Investigation, r.json()["investigation_id"])
        assert inv.product_id == b, "the case must belong to the anomaly's product"
    # and it shows up on B's feed, not A's
    assert any(x["slug"] == "beta-2" for x in tc.get(f"/anomalies?product_id={b}").json()["anomalies"])
    assert not any(x["slug"] == "beta-2" for x in tc.get(f"/anomalies?product_id={a}").json()["anomalies"])


def test_deletion_preview_reports_what_would_be_destroyed(client):
    """A confirmation that says 'cannot be undone' without saying what 'this' is
    asks the user to trust a number they can't see."""
    tc, ids, _ = client
    r = tc.get(f"/products/{ids['Alpha']}/deletion-preview")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Alpha"
    assert body["reviews"] == 6      # seeded corpus
    assert body["cases"] == 1 and body["findings"] == 1
    # and it counts only THIS product's rows
    beta = tc.get(f"/products/{ids['Beta']}/deletion-preview").json()
    assert beta["name"] == "Beta" and beta["reviews"] == 6


def test_deletion_preview_404s_for_a_product_that_is_gone(client):
    tc, ids, _ = client
    tc.delete(f"/products/{ids['Alpha']}?confirm=Alpha")
    assert tc.get(f"/products/{ids['Alpha']}/deletion-preview").status_code == 404
