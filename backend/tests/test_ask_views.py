"""Saved Cases views use cookie auth, CSRF, ownership and product scoping."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from echolens import auth
from echolens.config import settings
from echolens.db import session as db_session
from echolens.db.models import Base, Product, User


@pytest.fixture()
def world(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_session, "_engine", engine)
    monkeypatch.setattr(db_session, "_SessionLocal", Session)
    monkeypatch.setattr(db_session, "get_engine", lambda db_url=None: engine)
    monkeypatch.setattr(settings, "echolens_env", "production")
    monkeypatch.setattr(settings, "allow_guest", True)
    monkeypatch.setattr(settings, "jwt_secret", "views-test-secret-at-least-thirty-two-characters")
    with Session() as s:
        products = [Product(name="One", is_demo=True), Product(name="Two", is_demo=True)]
        users = [User(email=f"{n}@test.local", password_hash="unused", role=r)
                 for n, r in [("alice", "reviewer"), ("bob", "reviewer"), ("viewer", "viewer")]]
        s.add_all(products + users); s.commit()
        ids = [p.id for p in products]
        tokens = [auth.create_token(u) for u in users]
    import echolens.api.app as app_mod
    app_mod.limiter.reset()
    clients = [TestClient(app_mod.app) for _ in users]
    for tc, token in zip(clients, tokens):
        tc.cookies.set(auth.SESSION_COOKIE, token)
        tc.cookies.set(auth.CSRF_COOKIE, "test-csrf")
        tc.headers["X-CSRF-Token"] = "test-csrf"
    yield clients, ids, TestClient(app_mod.app)
    for tc in clients: tc.close()
    engine.dispose()


def _create(tc, pid, name="Needs review", params=None):
    return tc.post(f"/views?product_id={pid}", json={"name": name, "params": params or {
        "tab": "needs-review", "sev": "high", "source": "play_store", "range": "7",
        "intent": "bug", "q": "battery"}})


def test_saved_view_crud_roundtrips_every_filter(world):
    (alice, *_), (pid, _), _ = world
    assert alice.get(f"/views?product_id={pid}").json() == {"views": []}
    created = _create(alice, pid)
    assert created.status_code == 201, created.text
    view = created.json()
    assert view["name"] == "Needs review" and view["product_id"] == pid
    assert view["created_at"] and len(view["params"]) == 6
    assert alice.get(f"/views?product_id={pid}").json()["views"] == [view]
    changed = alice.put(f"/views/{view['id']}?product_id={pid}",
                        json={"name": "Battery", "params": {"q": "battery", "intent": "bug"}})
    assert changed.status_code == 200
    assert changed.json()["params"] == {"q": "battery", "intent": "bug"}
    assert changed.json()["name"] == "Battery"
    assert alice.delete(f"/views/{view['id']}?product_id={pid}").status_code == 200
    assert alice.get(f"/views?product_id={pid}").json() == {"views": []}


def test_other_users_cannot_see_edit_or_delete_a_view(world):
    (alice, bob, _), (pid, _), _ = world
    created = _create(alice, pid).json()
    assert bob.get(f"/views?product_id={pid}").json() == {"views": []}
    path = f"/views/{created['id']}?product_id={pid}"
    assert bob.put(path, json={"name": "Stolen", "params": {}}).status_code == 404
    assert bob.delete(path).status_code == 404
    # The same name belongs to a separate namespace for each user.
    assert _create(bob, pid).status_code == 201
    assert alice.get(f"/views?product_id={pid}").json()["views"][0]["name"] == "Needs review"


def test_views_are_scoped_to_the_exact_product(world):
    (alice, *_), (pid, other), _ = world
    created = _create(alice, pid).json()
    assert alice.get(f"/views?product_id={other}").json() == {"views": []}
    assert alice.put(f"/views/{created['id']}?product_id={other}",
                     json={"name": "Moved", "params": {}}).status_code == 404
    assert alice.delete(f"/views/{created['id']}?product_id={other}").status_code == 404
    assert _create(alice, other).status_code == 201
    assert alice.get("/views?product_id=99999").status_code == 404
    assert alice.get("/views").status_code == 422


def test_twenty_view_limit_is_per_user_and_product(world):
    (alice, bob, _), (pid, other), _ = world
    rows = [_create(alice, pid, f"View {i}") for i in range(20)]
    assert all(r.status_code == 201 for r in rows)
    assert _create(alice, pid, "Overflow").status_code == 409
    assert len(alice.get(f"/views?product_id={pid}").json()["views"]) == 20
    assert _create(alice, other, "Overflow").status_code == 201
    assert _create(bob, pid, "Overflow").status_code == 201
    # Rename at the limit remains possible; deleting frees one slot.
    first = rows[0].json()["id"]
    assert alice.put(f"/views/{first}?product_id={pid}",
                     json={"name": "Renamed", "params": {}}).status_code == 200
    assert alice.delete(f"/views/{first}?product_id={pid}").status_code == 200
    assert _create(alice, pid, "Replacement").status_code == 201


def test_names_are_trimmed_and_unique_within_the_owner_product(world):
    (alice, *_), (pid, _), _ = world
    first = _create(alice, pid, "  Review  ").json()
    assert first["name"] == "Review"
    assert _create(alice, pid, "Review").status_code == 409
    second = _create(alice, pid, "Other").json()
    assert alice.put(f"/views/{second['id']}?product_id={pid}",
                     json={"name": "Review", "params": {}}).status_code == 409
    assert alice.put(f"/views/{first['id']}?product_id={pid}",
                     json={"name": "Review", "params": {}}).status_code == 200


@pytest.mark.parametrize("body", [{"name": " ", "params": {}},
    {"name": "x" * 81, "params": {}}, {"name": "X", "params": {"product_id": "2"}},
    {"name": "X", "params": {"q": "x" * 501}}])
def test_invalid_views_are_rejected_without_writing(world, body):
    (alice, *_), (pid, _), _ = world
    assert alice.post(f"/views?product_id={pid}", json=body).status_code == 422
    assert alice.get(f"/views?product_id={pid}").json() == {"views": []}


def test_guests_use_local_views_and_viewers_cannot_mutate_server_views(world):
    (alice, _, viewer), (pid, _), guest = world
    row = _create(alice, pid).json()
    assert guest.get(f"/views?product_id={pid}").status_code == 403
    assert _create(guest, pid).status_code == 403
    assert viewer.get(f"/views?product_id={pid}").json() == {"views": []}
    assert _create(viewer, pid).status_code == 403
    path = f"/views/{row['id']}?product_id={pid}"
    assert viewer.put(path, json={"name": "X", "params": {}}).status_code == 403
    assert viewer.delete(path).status_code == 403


def test_cookie_mutations_require_csrf(world):
    (alice, *_), (pid, _), _ = world
    row = _create(alice, pid).json()
    del alice.headers["X-CSRF-Token"]
    assert _create(alice, pid, "No csrf").status_code == 403
    path = f"/views/{row['id']}?product_id={pid}"
    assert alice.put(path, json={"name": "X", "params": {}}).status_code == 403
    assert alice.delete(path).status_code == 403
    assert alice.get(f"/views?product_id={pid}").status_code == 200


def test_deleting_a_product_removes_its_saved_views_on_sqlite(world, monkeypatch):
    (alice, *_), (pid, _), _ = world
    # Development's synthetic principal is supported, and SQLite has no FK
    # enforcement by default: the explicit product purge must cover this table.
    monkeypatch.setattr(settings, "echolens_env", "dev")
    assert _create(alice, pid).status_code == 201
    assert alice.delete(f"/products/{pid}?confirm=One").status_code == 200
    from echolens.db.models import SavedView
    with db_session._SessionLocal() as s:
        assert s.query(SavedView).count() == 0


def test_a_slot_claimed_between_count_and_insert_cannot_exceed_the_limit(world, monkeypatch):
    (alice, *_), (pid, _), _ = world
    for i in range(19):
        assert _create(alice, pid, f"View {i}").status_code == 201
    # Deterministically interleave a competing commit after any standalone
    # count query. An atomic guarded INSERT has no such race window.
    from echolens.db.models import SavedView
    SessionClass = db_session._SessionLocal.class_
    original = SessionClass.scalar
    injected = False

    def racing_count(self, statement, *args, **kwargs):
        nonlocal injected
        result = original(self, statement, *args, **kwargs)
        if not injected and str(statement).startswith("SELECT count(") and "saved_views" in str(statement):
            injected = True
            with db_session._SessionLocal() as competing:
                competing.add(SavedView(user_id=1, product_id=pid, name="Competing view", params={}))
                competing.commit()
        return result

    monkeypatch.setattr(SessionClass, "scalar", racing_count)
    response = _create(alice, pid, "Last slot")
    assert response.status_code in (201, 409)
    assert len(alice.get(f"/views?product_id={pid}").json()["views"]) == 20
