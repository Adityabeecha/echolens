"""Batch 4 — security and auth.

Product scoping was applied as a WHERE clause on list endpoints and nowhere
else, so every single-resource route served or mutated any id the caller could
guess. These tests pin the enforcement point those routes never had.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from echolens.api.app import app
from echolens.db.models import AnomalyEvent, Base, Investigation, Product


@pytest.fixture()
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    ids = {}
    with Session() as s:
        for name in ("Alpha", "Beta"):
            p = Product(name=name)
            s.add(p); s.flush()
            a = AnomalyEvent(slug=f"{name}-1", type="manual", metric="m", delta=0.0, z=0.0,
                             window="7d", description="d", status="closed", product_id=p.id)
            s.add(a); s.flush()
            inv = Investigation(anomaly_id=a.id, status="resolved", opened_by="manual",
                                budget_tier="quick", budget_json={}, product_id=p.id)
            s.add(inv); s.flush()
            ids[name] = {"product": p.id, "case": inv.id}
        s.commit()

    import echolens.db.session as dbs
    monkeypatch.setattr(dbs, "_engine", engine, raising=False)
    monkeypatch.setattr(dbs, "_SessionLocal", Session, raising=False)
    c = TestClient(app)
    c.ids = ids
    return c


# ── B4.1 ────────────────────────────────────────────────────────────────

def test_a_case_from_another_product_is_not_readable(client):
    alpha, beta = client.ids["Alpha"], client.ids["Beta"]
    assert client.get(f"/investigations/{alpha['case']}"
                      f"?product_id={alpha['product']}").status_code == 200
    r = client.get(f"/investigations/{beta['case']}?product_id={alpha['product']}")
    assert r.status_code == 404, "a cross-product id must not be served"


def test_cross_product_ids_return_404_not_403(client):
    """403 confirms the row exists; 404 tells the caller nothing."""
    alpha, beta = client.ids["Alpha"], client.ids["Beta"]
    assert client.get(f"/investigations/{beta['case']}"
                      f"?product_id={alpha['product']}").status_code == 404


# ── B4.11 ───────────────────────────────────────────────────────────────

def test_an_unknown_product_id_is_a_404_not_a_silent_redirect(client):
    """_scope fell through to "the first product", so a stale or typo'd id
    quietly operated on somebody else's data — PUT /backlog/plan saved the PM's
    edits onto Product #1."""
    assert client.get("/cases?product_id=999999").status_code == 404


# ── B4.2 ────────────────────────────────────────────────────────────────

def test_webhook_refuses_to_run_unverified(client):
    """Signature verification was wrapped in `if secret:` and the secret
    defaults to "", so out of the box any unauthenticated caller could forge an
    issues/closed event and fabricate "the fix shipped"."""
    r = client.post("/webhooks/github",
                    json={"action": "closed", "issue": {"number": 1},
                          "repository": {"full_name": "o/r"}},
                    headers={"X-GitHub-Event": "issues"})
    assert r.status_code in (401, 503), "an unverified webhook must never mutate state"


# ── B4.10 ───────────────────────────────────────────────────────────────

def test_a_malformed_token_is_401_not_500():
    """int(payload["sub"]) sat outside the try, so a correctly-signed token with
    sub="abc" raised ValueError and escaped as a 500 with a stack trace."""
    from fastapi import HTTPException
    from echolens.auth import create_token, current_user
    from echolens.config import settings

    class FakeRequest:
        headers = {"Authorization": "Bearer not-a-real-token"}

    if not settings.auth_required:
        pytest.skip("auth is off in dev mode")
    with pytest.raises(HTTPException) as exc:
        current_user(FakeRequest())
    assert exc.value.status_code == 401


# ── B4.9 ────────────────────────────────────────────────────────────────

def test_every_llm_spending_endpoint_is_rate_limited():
    """Only 5 of 73 endpoints were capped, and none of the LLM-spending ones."""
    import pathlib
    src = pathlib.Path(__file__).resolve().parents[1] / "echolens" / "api" / "app.py"
    text = src.read_text(encoding="utf-8")
    for route in ("/chat", "/brain/ask", "/brain/review",
                  "/findings/{finding_id}/followup", "/integrations/slack/act"):
        i = text.index(f'"{route}"')
        window = text[i:i + 400]
        assert "@limiter.limit" in window, f"{route} spends LLM budget with no cap"
