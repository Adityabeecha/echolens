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
from echolens import auth
from echolens.db.models import (
    AnomalyEvent, Base, CollectorState, Finding, FixWatch, Investigation, LLMCall,
    Product, Review, ReviewFeedback, TriageDecision)

PASSWORD = "correct-horse-battery-9"


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


def _counts(monkeypatch, n: int, paths: list[str], repeat: int = 1) -> dict[str, int]:
    """Statements per path; with `repeat`, the count of the LAST of that many
    calls (the steady state once anything cached or stored is in place)."""
    eng = _engine()
    Session = _wire(monkeypatch, eng)
    _build(Session, n)
    from echolens.api.app import app
    client = TestClient(app)
    out = {}
    for path in paths:
        for _ in range(repeat - 1):
            client.get(path)
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


def test_portfolio_board_stays_under_a_fixed_budget(monkeypatch):
    """Absolute ceilings, so a later change cannot reintroduce a per-product
    query that happens to cost the same at both scales by accident."""
    counts = _counts(monkeypatch, 6, ["/portfolio", "/portfolio/brief", "/portfolio/themes"])
    # /portfolio now serves stored rows. The first call (nothing stored yet)
    # computes the board AND reads the fingerprint and writes the rows: one
    # more than the old 15. Every later call reads the stored rows instead.
    assert counts["/portfolio"] <= 16
    assert _counts(monkeypatch, 6, ["/portfolio"], repeat=2)["/portfolio"] <= 10
    assert counts["/portfolio/brief"] <= 25
    assert counts["/portfolio/themes"] <= 6


def test_batched_theme_comparison_matches_per_product_rates(monkeypatch):
    """The one-pass corpus must report the same rates theme_rate does."""
    from echolens.vocab import canonical_theme, compare_theme, negative_corpus
    eng = _engine()
    Session = _wire(monkeypatch, eng)
    _build(Session, 3)
    with Session() as s:
        names = ["app-0", "app-1", "app-2"]
        corpus = negative_corpus(s, names, 30)
        for words in (["battery", "drain"], ["login", "crash"], ["sync"]):
            theme = canonical_theme(words)
            assert (compare_theme(s, theme, names, 30)
                    == compare_theme(s, theme, names, 30, corpus=corpus))


def test_batched_portfolio_matches_single_product_snapshot(monkeypatch):
    from echolens.portfolio import portfolio, product_snapshot
    eng = _engine()
    Session = _wire(monkeypatch, eng)
    _build(Session, 4)
    now = datetime.now(timezone.utc)
    with Session() as s:
        board = {r["product_id"]: r for r in portfolio(s, now)["products"]}
        for p in s.query(Product).all():
            assert product_snapshot(s, p, now) == board[p.id]


def test_batched_briefs_match_single_product_briefs(monkeypatch):
    from echolens.backlog import resolution_rate
    from echolens.brief import weekly_brief, weekly_briefs
    eng = _engine()
    Session = _wire(monkeypatch, eng)
    _build(Session, 4)
    now = datetime.now(timezone.utc)
    with Session() as s:
        ids = [p.id for p in s.query(Product).all()]
        batch = weekly_briefs(s, ids, now)
        for pid in ids:
            assert batch[pid] == weekly_brief(s, now, pid)
            assert batch[pid]["resolution_rate"] == resolution_rate(s, pid)


# ── auth: cookie session, CSRF, SSE, headers ────────────────────────────

@pytest.fixture()
def prod_client(monkeypatch):
    """Real auth over an in-memory DB with one reviewer and one admin.

    https base URL: the session cookie is Secure, and a client honouring that
    (as httpx and every browser do) will not send it over plain http."""
    monkeypatch.setattr(settings, "echolens_env", "production")
    monkeypatch.setattr(settings, "jwt_secret", "test-secret-" + "x" * 32)
    monkeypatch.setattr(settings, "session_cookie_samesite", "lax")
    monkeypatch.setattr(settings, "session_cookie_secure", True)
    eng = _engine()
    Session = _wire(monkeypatch, eng)
    with Session() as s:
        auth.create_user(s, "rev@team.com", PASSWORD, "reviewer")
        auth.create_user(s, "admin@team.com", PASSWORD, "admin")
        s.add(Product(name="app", is_demo=True))
        s.commit()
    from echolens.api.app import app
    app.state.limiter.reset()  # login is rate-limited per IP across the suite
    return TestClient(app, base_url="https://testserver")


def _login(client, email="rev@team.com"):
    r = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return r


def test_login_sets_httponly_session_and_readable_csrf_cookie(prod_client):
    r = _login(prod_client)
    cookies = r.headers.get_list("set-cookie")
    session = next(c for c in cookies if c.startswith(auth.SESSION_COOKIE + "="))
    csrf = next(c for c in cookies if c.startswith(auth.CSRF_COOKIE + "="))
    assert "HttpOnly" in session and "Secure" in session and "samesite=lax" in session.lower()
    assert "HttpOnly" not in csrf and "Secure" in csrf
    body = r.json()
    assert body["csrf_token"] and body["csrf_token"] in csrf
    # Automation still gets a bearer token in the body.
    assert body["token"]


def test_cookie_alone_authenticates_reads(prod_client):
    _login(prod_client)
    me = prod_client.get("/auth/me")
    assert me.status_code == 200 and me.json()["email"] == "rev@team.com"


def test_cookie_write_requires_matching_csrf_header(prod_client):
    csrf = _login(prod_client).json()["csrf_token"]
    assert prod_client.post("/products/1/activate").status_code == 403
    assert prod_client.post("/products/1/activate",
                            headers={"X-CSRF-Token": "forged"}).status_code == 403
    ok = prod_client.post("/products/1/activate", headers={"X-CSRF-Token": csrf})
    assert ok.status_code == 200, ok.text


def test_cookie_write_with_csrf_header_but_no_csrf_cookie_is_refused(prod_client):
    """The header alone proves nothing: it must match the cookie."""
    csrf = _login(prod_client).json()["csrf_token"]
    prod_client.cookies.delete(auth.CSRF_COOKIE)
    assert prod_client.post("/products/1/activate",
                            headers={"X-CSRF-Token": csrf}).status_code == 403


def test_cors_never_credentials_a_wildcard():
    from echolens.api.app import cors_allows_credentials
    assert cors_allows_credentials(["https://app.example.com"])
    assert not cors_allows_credentials([])
    assert not cors_allows_credentials(["*"])
    assert not cors_allows_credentials(["https://app.example.com", "*"])


def test_bearer_writes_need_no_csrf(prod_client):
    token = _login(prod_client).json()["token"]
    prod_client.cookies.clear()
    r = prod_client.post("/products/1/activate", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text


def test_csrf_endpoint_recovers_token_after_reload(prod_client):
    csrf = _login(prod_client).json()["csrf_token"]
    assert prod_client.get("/auth/csrf").json()["csrf_token"] == csrf


def test_logout_clears_the_session(prod_client):
    _login(prod_client)
    out = prod_client.post("/auth/logout")
    assert out.status_code == 200
    cleared = out.headers.get_list("set-cookie")
    for name in (auth.SESSION_COOKIE, auth.CSRF_COOKIE):
        assert any(c.startswith(name + "=") and "Max-Age=0" in c for c in cleared), name
    assert prod_client.get("/auth/me").status_code == 401


def test_cookie_role_still_comes_from_the_database(prod_client):
    """A demoted user loses their powers on the next request, cookie or not."""
    _login(prod_client, "admin@team.com")
    from echolens.db.models import User
    from echolens.db.session import session_scope
    with session_scope() as s:
        s.query(User).filter_by(email="admin@team.com").one().role = "viewer"
    assert prod_client.get("/auth/me").json()["role"] == "viewer"


def test_admin_creating_a_user_keeps_the_admin_session(prod_client):
    csrf = _login(prod_client, "admin@team.com").json()["csrf_token"]
    r = prod_client.post("/auth/signup", headers={"X-CSRF-Token": csrf},
                         json={"email": "new@team.com", "password": PASSWORD, "role": "viewer"})
    assert r.status_code == 200, r.text
    assert not any(c.startswith(auth.SESSION_COOKIE + "=")
                   for c in r.headers.get_list("set-cookie"))
    assert prod_client.get("/auth/me").json()["email"] == "admin@team.com"


def test_samesite_none_for_split_origin_deploys(prod_client, monkeypatch):
    monkeypatch.setattr(settings, "session_cookie_samesite", "none")
    cookies = _login(prod_client).headers.get_list("set-cookie")
    assert all("samesite=none" in c.lower() and "Secure" in c for c in cookies)


def test_production_refuses_an_insecure_session_cookie(monkeypatch):
    monkeypatch.setattr(settings, "echolens_env", "production")
    monkeypatch.setattr(settings, "session_cookie_secure", False)
    assert any("SESSION_COOKIE_SECURE" in p for p in settings.check_production_ready())


def _resolved_case():
    from echolens.db.session import session_scope
    with session_scope() as s:
        inv = Investigation(status="resolved", product_id=1, budget_json={})
        s.add(inv)
        s.flush()
        return inv.id


def test_trace_stream_authenticates_with_the_cookie(prod_client):
    _login(prod_client)
    iid = _resolved_case()
    r = prod_client.get(f"/investigations/{iid}/trace/stream?product_id=1")
    assert r.status_code == 200 and "event: done" in r.text


def test_trace_stream_query_token_still_works_but_is_logged(prod_client, monkeypatch):
    import echolens.api.app as app_mod
    token = _login(prod_client).json()["token"]
    prod_client.cookies.clear()
    warnings = []

    class Log:
        def warning(self, event, **kw):
            warnings.append(event)

        def __getattr__(self, _name):
            return lambda *a, **k: None

    monkeypatch.setattr(app_mod, "log", Log())
    iid = _resolved_case()
    r = prod_client.get(f"/investigations/{iid}/trace/stream?product_id=1&token={token}")
    assert r.status_code == 200
    assert "deprecated_query_token" in warnings
    assert prod_client.get(f"/investigations/{iid}/trace/stream?product_id=1").status_code == 401


def test_api_sends_security_headers(prod_client):
    r = prod_client.get("/auth/config")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


def test_dev_mode_needs_no_cookie_or_csrf(monkeypatch):
    eng = _engine()
    _wire(monkeypatch, eng)
    from echolens.api.app import app
    client = TestClient(app)
    assert client.get("/auth/me").json()["role"] == "admin"
    assert client.post("/anomalies/scan").status_code != 403
