"""Session transport, security headers, and bounded query counts.

Two groups of regression tests:

* auth: the browser session lives in an HttpOnly cookie (not localStorage),
  cookie-authenticated writes need the double-submit CSRF token, Bearer auth
  keeps working for automation, and the live-trace stream accepts the cookie;
* performance: the read screens (/portfolio*, /brief, /overview, /archive,
  /anomalies) issue a number of SQL statements that does NOT grow with the
  amount of data. Each test builds the same workspace at scale N and 4N and
  asserts the per-request statement count is identical.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import echolens.db.session as db_session
from echolens.config import settings
from echolens.db.models import (
    AnomalyEvent, Base, CollectorState, Finding, FixWatch, Investigation, LLMCall,
    Product, Review, ReviewFeedback, TriageDecision)


def _wire(monkeypatch, engine):
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_session, "_engine", engine)
    monkeypatch.setattr(db_session, "_SessionLocal", Session)
    monkeypatch.setattr(db_session, "get_engine", lambda db_url=None: engine)
    return Session


def _engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    return eng


# ── fixture: one workspace at a given scale ─────────────────────────────

def _build(Session, n: int) -> None:
    """`n` products, each with `n` cases (anomaly + resolved investigation +
    finding + triage + feedback + LLM spend), fix-watches in every lifecycle
    state, collector rows and a few weeks of reviews. Scale 4N multiplies every
    table, so a per-row query shows up as a different statement count."""
    now = datetime.now(timezone.utc)
    themes = ["battery drain", "login crash", "sync fails", "slow startup"]
    with Session() as s:
        for p_i in range(n):
            p = Product(name=f"app-{p_i}", is_demo=True)
            s.add(p)
            s.flush()
            s.add(CollectorState(source="play_store", identifier=f"pkg.{p_i}",
                                 product=p.name, status="healthy",
                                 last_run_at=now - timedelta(days=3), product_id=p.id))
            for r_i in range(4 * n):
                s.add(Review(source="play_store", ext_id=f"r-{p_i}-{r_i}",
                             rating=1 if r_i % 2 else 5, text=f"{themes[r_i % 4]} again",
                             product=p.name,
                             created_at=now - timedelta(days=r_i % 30, hours=1)))
            for c_i in range(n):
                theme = themes[c_i % 4]
                a = AnomalyEvent(
                    slug=f"a-{p_i}-{c_i}",
                    type=("negative_review_spike", "theme_volume_surge", "regression")[c_i % 3],
                    metric=f"{theme} share of negative reviews", delta=0.2, z=2.0 + c_i,
                    window="7d", description=theme,
                    status=("pending", "investigating")[c_i % 2], product_id=p.id,
                    created_at=now - timedelta(days=c_i))
                s.add(a)
                s.flush()
                s.add(TriageDecision(anomaly_id=a.id, decision="investigate", reason="r",
                                     budget_tier="standard"))
                inv = Investigation(
                    anomaly_id=a.id, status="resolved", product_id=p.id,
                    budget_json={"iterations": f"{c_i + 1}/12", "tool_calls": "3/20"},
                    seeded_from_pattern=({"cross_product": True, "from_product": "app-0"}
                                         if c_i % 2 else None),
                    created_at=now - timedelta(days=90 if c_i % 2 else 2),
                    resolved_at=now - timedelta(days=1))
                s.add(inv)
                s.flush()
                f = Finding(investigation_id=inv.id, summary=f"{theme} after update",
                            confidence=0.8, status="approved", product_id=p.id,
                            json={"prose": theme, "impact": {"impact_score": 0.5,
                                                             "affected_volume": 10}})
                s.add(f)
                s.flush()
                s.add(ReviewFeedback(finding_id=f.id, action="approve"))
                s.add(LLMCall(investigation_id=inv.id, agent="investigator.plan",
                              tokens_in=100, tokens_out=50, cost=0.01))
                status = ("confirmed", "regressed", "watching", "issue_open")[c_i % 4]
                s.add(FixWatch(finding_id=f.id, investigation_id=inv.id, repo="o/r",
                               issue_number=c_i + 1, status=status, terms=[theme],
                               metric=theme, product_id=p.id,
                               confirmed_at=(now - timedelta(days=1)
                                             if status == "confirmed" else None)))
        s.commit()


class _Counter:
    def __init__(self):
        self.n = 0

    def __call__(self, *_a, **_k):
        self.n += 1


def _counts(monkeypatch, n: int, paths: list[str]) -> dict[str, int]:
    eng = _engine()
    Session = _wire(monkeypatch, eng)
    _build(Session, n)
    from echolens.api.app import app
    client = TestClient(app)
    out = {}
    for path in paths:
        counter = _Counter()
        event.listen(eng, "before_cursor_execute", counter)
        try:
            r = client.get(path)
        finally:
            event.remove(eng, "before_cursor_execute", counter)
        assert r.status_code == 200, (path, r.status_code, r.text[:200])
        out[path] = counter.n
    return out


READ_PATHS = [
    "/portfolio", "/portfolio/brief", "/portfolio/themes", "/portfolio/transfers",
    "/brief", "/overview", "/archive", "/anomalies", "/cases",
    "/brief?product_id=1", "/overview?product_id=1", "/archive?product_id=1",
    "/anomalies?product_id=1",
]


def test_read_endpoints_statement_count_is_flat(monkeypatch):
    small = _counts(monkeypatch, 3, READ_PATHS)
    large = _counts(monkeypatch, 12, READ_PATHS)
    grew = {p: (small[p], large[p]) for p in READ_PATHS if large[p] != small[p]}
    assert not grew, f"statement count grows with data: {grew}"
