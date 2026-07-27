"""Public-demo mode: read-only guests, and Google sign-in.

The whole point of guest mode is that an anonymous visitor can READ everything
and CHANGE nothing. These tests pin that boundary, because the failure mode is
silent and expensive: a guest promoted to admin on a public URL can spend the
deployment's OpenAI credits and delete its data.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from echolens import auth
from echolens.config import settings
from echolens.db.models import Base, User


@pytest.fixture()
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, expire_on_commit=False)()


class FakeRequest:
    def __init__(self, headers=None):
        self.headers = headers or {}


@pytest.fixture()
def prod(monkeypatch):
    """Real auth, i.e. not the dev bypass."""
    monkeypatch.setattr(settings, "echolens_env", "production")
    return monkeypatch


# ── guest admission ────────────────────────────────────────────────────

def test_no_token_is_rejected_when_guests_are_off(prod):
    prod.setattr(settings, "allow_guest", False)
    with pytest.raises(HTTPException) as e:
        auth.current_user(FakeRequest())
    assert e.value.status_code == 401


def test_no_token_becomes_a_viewer_when_guests_are_on(prod):
    prod.setattr(settings, "allow_guest", True)
    user = auth.current_user(FakeRequest())
    assert user["role"] == "viewer"
    assert user["guest"] is True
    # No users row backs a guest; attributing writes to id 0 would be a lie.
    assert user["id"] is None


def test_guest_can_read_but_cannot_review_or_admin(prod):
    """The actual security boundary: every endpoint that spends money or
    mutates state is behind require_role('reviewer') or ('admin')."""
    prod.setattr(settings, "allow_guest", True)
    guest = auth.current_user(FakeRequest())

    # viewer-level dependency admits the guest
    assert auth.require_role("viewer")(user=guest) is guest

    for level in ("reviewer", "admin"):
        with pytest.raises(HTTPException) as e:
            auth.require_role(level)(user=guest)
        assert e.value.status_code == 403


def test_guest_mode_never_grants_admin(prod):
    """Guard against the obvious regression: reusing the dev bypass (which
    returns a full ADMIN) for the public demo path."""
    prod.setattr(settings, "allow_guest", True)
    assert auth.current_user(FakeRequest())["role"] != "admin"
    assert auth.GUEST["role"] == "viewer"


def test_a_bad_token_is_401_even_with_guests_on(prod):
    """A token that fails to verify is a broken session, not an anonymous
    visitor. Downgrading it to guest would hide expiry from the user and make a
    tampered token look like a successful anonymous call."""
    prod.setattr(settings, "allow_guest", True)
    with pytest.raises(HTTPException) as e:
        auth.current_user(FakeRequest({"Authorization": "Bearer not-a-real-token"}))
    assert e.value.status_code == 401


def test_guest_dict_is_copied_not_shared(prod):
    """current_user returns a fresh dict; a caller mutating it must not change
    the role every later guest receives."""
    prod.setattr(settings, "allow_guest", True)
    first = auth.current_user(FakeRequest())
    first["role"] = "admin"
    assert auth.current_user(FakeRequest())["role"] == "viewer"


# ── Google account mapping ─────────────────────────────────────────────

def test_google_user_is_created_with_the_configured_role(db):
    u = auth.upsert_google_user(db, "someone@gmail.com", "reviewer")
    assert u.email == "someone@gmail.com"
    assert u.role == "reviewer"
    assert u.id is not None


def test_google_user_cannot_be_password_logged_in(db):
    """The stored marker is not a bcrypt hash, so the password endpoint can
    never authenticate an SSO-only account."""
    auth.upsert_google_user(db, "sso@gmail.com", "reviewer")
    assert auth.authenticate(db, "sso@gmail.com", "") is None
    assert auth.authenticate(db, "sso@gmail.com", auth.SSO_ONLY) is None
    assert auth.authenticate(db, "sso@gmail.com", "password") is None


def test_signing_in_twice_reuses_one_row(db):
    a = auth.upsert_google_user(db, "dup@gmail.com", "reviewer")
    b = auth.upsert_google_user(db, "dup@gmail.com", "reviewer")
    assert a.id == b.id
    assert db.query(User).filter_by(email="dup@gmail.com").count() == 1


def test_google_sign_in_never_demotes_an_admin(db):
    """An admin who is not on the Google allowlist signs in and stays admin."""
    auth.create_user(db, "boss@team.com", "pw", "admin")
    u = auth.upsert_google_user(db, "boss@team.com", "reviewer")
    assert u.role == "admin"


def test_google_sign_in_can_promote(db):
    auth.create_user(db, "quiet@team.com", "pw", "viewer")
    u = auth.upsert_google_user(db, "quiet@team.com", "admin")
    assert u.role == "admin"


def test_linking_google_keeps_an_existing_password(db):
    """Signing in with Google must not clobber the stored hash and silently
    disable the user's existing password login."""
    auth.create_user(db, "both@team.com", "hunter2", "reviewer")
    auth.upsert_google_user(db, "both@team.com", "reviewer")
    assert auth.authenticate(db, "both@team.com", "hunter2") is not None


def test_admin_allowlist_is_case_insensitive(monkeypatch):
    from echolens import google_auth
    monkeypatch.setattr(settings, "google_admin_emails", "Owner@Gmail.com")
    monkeypatch.setattr(settings, "google_default_role", "reviewer")
    assert google_auth.role_for("owner@gmail.com") == "admin"
    assert google_auth.role_for("OWNER@GMAIL.COM") == "admin"
    assert google_auth.role_for("someone.else@gmail.com") == "reviewer"


# ── Google token verification ──────────────────────────────────────────

def test_verification_refuses_when_unconfigured(monkeypatch):
    from echolens import google_auth
    monkeypatch.setattr(settings, "google_client_id", "")
    with pytest.raises(google_auth.GoogleAuthError):
        google_auth.verify_id_token("anything")


def test_verification_rejects_garbage(monkeypatch):
    """An unsigned/!JWT string must never authenticate. This is the attack:
    the credential is attacker-supplied, and decoding without verifying would
    let anyone log in as anyone by editing the payload."""
    from echolens import google_auth
    monkeypatch.setattr(settings, "google_client_id", "test-client-id.apps.googleusercontent.com")
    monkeypatch.setattr(google_auth, "_keys", lambda force=False: {"keys": []})
    for bad in ("", "not-a-jwt", "a.b.c", "null"):
        with pytest.raises(google_auth.GoogleAuthError):
            google_auth.verify_id_token(bad)


def test_verification_rejects_a_self_signed_token(monkeypatch):
    """A token we sign ourselves with a symmetric key is structurally valid
    but not from Google, so it must be refused."""
    from jose import jwt as jose_jwt
    from echolens import google_auth
    monkeypatch.setattr(settings, "google_client_id", "test-client-id.apps.googleusercontent.com")
    monkeypatch.setattr(google_auth, "_keys", lambda force=False: {"keys": []})
    forged = jose_jwt.encode(
        {"email": "attacker@evil.com", "email_verified": True,
         "iss": "https://accounts.google.com",
         "aud": "test-client-id.apps.googleusercontent.com"},
        "attacker-key", algorithm="HS256")
    with pytest.raises(google_auth.GoogleAuthError):
        google_auth.verify_id_token(forged)


# ── product scoping of queued themes ───────────────────────────────────
# Reported symptom: after adding a SECOND product and queueing a theme on it,
# opening the resulting case returned 404.

def test_two_products_get_their_own_anomaly_for_the_same_theme(db):
    """Slugs are namespaced per product by the API, but the lookup that decides
    "does this already exist?" ignored the product, so the second product's
    theme could adopt the first product's anomaly — and the case created from
    it then belonged to the wrong product and 404'd on open."""
    from echolens.db.models import Product
    from echolens.orchestrator.queue import enqueue_theme

    a = Product(name="Aurora"); b = Product(name="Borealis")
    db.add_all([a, b]); db.flush()

    r1 = enqueue_theme(db, product_id=a.id, slug=f"theme-p{a.id}-battery",
                       statement="Battery drains overnight")
    r2 = enqueue_theme(db, product_id=b.id, slug=f"theme-p{b.id}-battery",
                       statement="Battery drains overnight")

    assert r1["status"] == "queued"
    assert r2["status"] == "queued", "the second product must not be told it is 'already' queued"

    from echolens.db.models import AnomalyEvent
    an1 = db.get(AnomalyEvent, r1["anomaly_id"])
    an2 = db.get(AnomalyEvent, r2["anomaly_id"])
    assert an1.id != an2.id
    assert an1.product_id == a.id
    assert an2.product_id == b.id


def test_find_existing_is_scoped_to_the_product(db):
    """A theme queued on product A must not read as existing on product B."""
    from echolens.db.models import Product
    from echolens.orchestrator.queue import enqueue_theme, find_existing

    a = Product(name="Aurora"); b = Product(name="Borealis")
    db.add_all([a, b]); db.flush()
    slug = "theme-shared-battery"          # same slug on purpose
    enqueue_theme(db, product_id=a.id, slug=slug, statement="Battery")

    assert find_existing(db, a.id, slug) is not None, "A's own theme is already queued"
    assert find_existing(db, b.id, slug) is None, "B must be free to queue its own"


def test_legacy_unscoped_anomaly_is_claimed_not_duplicated(db):
    """Rows created before product scoping have product_id=None. Queueing that
    theme should adopt the row for the product rather than leaving a NULL that
    no scoped query will match again."""
    from echolens.db.models import AnomalyEvent, Product
    from echolens.orchestrator.queue import enqueue_theme

    p = Product(name="Aurora"); db.add(p); db.flush()
    legacy = AnomalyEvent(slug="theme-legacy", type="manual_theme", metric="m",
                          delta=0.0, z=0.0, window="90d", description="old",
                          status="pending", product_id=None)
    db.add(legacy); db.flush()

    r = enqueue_theme(db, product_id=p.id, slug="theme-legacy", statement="old")
    assert r["anomaly_id"] == legacy.id, "should reuse the row, not duplicate it"
    assert db.get(AnomalyEvent, legacy.id).product_id == p.id


def test_junk_credentials_do_not_hammer_google(monkeypatch):
    """A refetch of Google's key set is only justified by an UNKNOWN key id
    (a rotation). Refetching on every failure turned a flood of junk
    credentials into a flood of outbound requests to Google."""
    from echolens import google_auth
    monkeypatch.setattr(settings, "google_client_id", "test-client.apps.googleusercontent.com")

    fetches = {"n": 0}

    def fake_keys(force=False):
        fetches["n"] += 1
        return {"keys": [{"kid": "real-key-id"}]}

    monkeypatch.setattr(google_auth, "_keys", fake_keys)

    for bad in ("not-a-jwt", "", "a.b.c", "x.y", "null"):
        with pytest.raises(google_auth.GoogleAuthError):
            google_auth.verify_id_token(bad)

    assert fetches["n"] == 0, "malformed tokens must not trigger a JWKS fetch"


def test_an_unknown_key_id_does_trigger_one_refetch(monkeypatch):
    """The rotation case: a well-formed RS256 token whose kid we have not seen
    should refetch once before being judged."""
    from echolens import google_auth
    monkeypatch.setattr(settings, "google_client_id", "test-client.apps.googleusercontent.com")

    fetches = {"n": 0}

    def fake_keys(force=False):
        fetches["n"] += 1
        return {"keys": [{"kid": "known-key"}]}

    monkeypatch.setattr(google_auth, "_keys", fake_keys)

    # A well-formed RS256 header carrying a kid the cache has never seen. Hand
    # built because jose will not sign RS256 without a real private key, and
    # the header alone is what drives the refetch decision.
    import base64, json
    def seg(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()
    header = seg({"alg": "RS256", "kid": "rotated-key"})
    payload = seg({"email": "a@b.com"})
    token = header + "." + payload + ".sig"
    with pytest.raises(google_auth.GoogleAuthError):
        google_auth.verify_id_token(token)
    assert fetches["n"] == 2, "one cached read, then one forced refetch"


def test_a_non_rs256_algorithm_is_refused(monkeypatch):
    """Closes the `alg: none` / HMAC-confusion class outright."""
    from jose import jwt as jose_jwt
    from echolens import google_auth
    monkeypatch.setattr(settings, "google_client_id", "test-client.apps.googleusercontent.com")
    monkeypatch.setattr(google_auth, "_keys", lambda force=False: {"keys": [{"kid": "k"}]})

    hs = jose_jwt.encode({"email": "a@evil.com"}, "attacker", algorithm="HS256",
                         headers={"kid": "k"})
    with pytest.raises(google_auth.GoogleAuthError) as e:
        google_auth.verify_id_token(hs)
    assert "algorithm" in str(e.value)


# ── guests see demo products only ──────────────────────────────────────
# A public demo URL must not list the workspace's real products.

def _app_client(monkeypatch):
    """A TestClient over an isolated DB holding one demo and one real product."""
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    import echolens.db.session as db_session
    from echolens.db.models import Base, Product

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as s:
        s.add_all([Product(name="Lumo (demo)", is_demo=True),
                   Product(name="Firefox", is_demo=False)])
        s.commit()
    monkeypatch.setattr(db_session, "_engine", engine)
    monkeypatch.setattr(db_session, "_SessionLocal", Session)
    monkeypatch.setattr(db_session, "get_engine", lambda db_url=None: engine)
    from echolens.api.app import app
    return TestClient(app)


def test_guest_products_list_hides_real_products(monkeypatch):
    monkeypatch.setattr(settings, "echolens_env", "staging")
    monkeypatch.setattr(settings, "allow_guest", True)
    monkeypatch.setattr(settings, "guest_demo_only", True)
    tc = _app_client(monkeypatch)

    names = [p["name"] for p in tc.get("/products").json()["products"]]
    assert names == ["Lumo (demo)"], f"a guest must see only demo products, got {names}"


def test_guest_cannot_reach_a_real_product_by_id(monkeypatch, tmp_path):
    """404, not 403: a 403 would confirm the product exists."""
    monkeypatch.setattr(settings, "echolens_env", "staging")
    monkeypatch.setattr(settings, "allow_guest", True)
    monkeypatch.setattr(settings, "guest_demo_only", True)
    tc = _app_client(monkeypatch)

    assert tc.get("/cases?product_id=2").status_code == 404   # Firefox
    assert tc.get("/cases?product_id=1").status_code == 200   # Lumo


def test_guest_portfolio_does_not_leak_real_product_names(monkeypatch):
    monkeypatch.setattr(settings, "echolens_env", "staging")
    monkeypatch.setattr(settings, "allow_guest", True)
    monkeypatch.setattr(settings, "guest_demo_only", True)
    tc = _app_client(monkeypatch)

    board = tc.get("/portfolio").json()
    assert [p["product"] for p in board["products"]] == ["Lumo (demo)"]
    # Transfer stats compare real products, so they are withheld entirely.
    assert board["transfer"] is None
    assert tc.get("/portfolio/transfers").json()["transfers"] == []


def test_the_flag_can_be_turned_off(monkeypatch, tmp_path):
    """A private deployment may want guests to see everything."""
    monkeypatch.setattr(settings, "echolens_env", "staging")
    monkeypatch.setattr(settings, "allow_guest", True)
    monkeypatch.setattr(settings, "guest_demo_only", False)
    tc = _app_client(monkeypatch)

    names = [p["name"] for p in tc.get("/products").json()["products"]]
    assert len(names) == 2


# ── the SSE trace stream ───────────────────────────────────────────────

def _stream_fixture(monkeypatch):
    """A client plus (demo_product_id, demo_inv_id, real_product_id, real_inv_id)."""
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    import echolens.db.session as db_session
    from echolens.db.models import AnomalyEvent, Base, Investigation, Product

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    out = {}
    with Session() as s:
        for name, demo in (("Lumo (demo)", True), ("Firefox", False)):
            p = Product(name=name, is_demo=demo); s.add(p); s.flush()
            a = AnomalyEvent(slug=f"s{p.id}", type="t", metric="m", delta=0.0, z=0.0,
                             window="90d", description="d", status="pending",
                             product_id=p.id)
            s.add(a); s.flush()
            inv = Investigation(anomaly_id=a.id, status="needs_review",
                                opened_by="anomaly", budget_tier="quick",
                                budget_json={}, product_id=p.id)
            s.add(inv); s.flush()
            out[name] = (p.id, inv.id)
        u = auth.create_user(s, "admin@team.com", "pw", "admin")
        out["token"] = auth.create_token(u)
        s.commit()
    monkeypatch.setattr(db_session, "_engine", engine)
    monkeypatch.setattr(db_session, "_SessionLocal", Session)
    monkeypatch.setattr(db_session, "get_engine", lambda db_url=None: engine)
    from echolens.api.app import app
    return TestClient(app, raise_server_exceptions=False), out


def test_trace_stream_does_not_500(monkeypatch):
    """It referenced an undefined `user`, so every request raised NameError and
    the live trace was a 500 in both dev and staging."""
    monkeypatch.setattr(settings, "echolens_env", "dev")
    tc, ids = _stream_fixture(monkeypatch)
    pid, iid = ids["Lumo (demo)"]
    r = tc.get(f"/investigations/{iid}/trace/stream?product_id={pid}")
    assert r.status_code == 200, r.text[:200]


def test_trace_stream_is_product_scoped_for_guests(monkeypatch):
    """This route builds its own principal (EventSource cannot send headers),
    so the guest demo-only rule has to be applied here explicitly."""
    monkeypatch.setattr(settings, "echolens_env", "staging")
    monkeypatch.setattr(settings, "allow_guest", True)
    monkeypatch.setattr(settings, "guest_demo_only", True)
    tc, ids = _stream_fixture(monkeypatch)

    demo_pid, demo_iid = ids["Lumo (demo)"]
    real_pid, real_iid = ids["Firefox"]
    assert tc.get(f"/investigations/{demo_iid}/trace/stream?product_id={demo_pid}").status_code == 200
    assert tc.get(f"/investigations/{real_iid}/trace/stream?product_id={real_pid}").status_code == 404

    # A signed-in admin still reaches both.
    tok = ids["token"]
    assert tc.get(f"/investigations/{real_iid}/trace/stream?product_id={real_pid}&token={tok}").status_code == 200


def test_trace_stream_still_401s_when_guests_are_off(monkeypatch):
    monkeypatch.setattr(settings, "echolens_env", "staging")
    monkeypatch.setattr(settings, "allow_guest", False)
    tc, ids = _stream_fixture(monkeypatch)
    pid, iid = ids["Lumo (demo)"]
    assert tc.get(f"/investigations/{iid}/trace/stream?product_id={pid}").status_code == 401
