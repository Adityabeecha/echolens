"""v5.0 collaboration: comments, @mentions, review sign-off, team dashboard.

The security properties get as much weight as the features: comments are a new
write surface reachable by id, so cross-product access and guest writes are
tested as first-class behaviour rather than assumed.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from echolens import auth, collab
from echolens.db import session as db_session
from echolens.db.models import (AnomalyEvent, Base, Comment, Investigation,
                                Mention, Product, ReviewRequest, User)


def _db():
    e = create_engine("sqlite://")
    Base.metadata.create_all(e)
    return Session(e)


def _case(s, product, slug="c1"):
    a = AnomalyEvent(slug=slug, type="volume_spike", metric="battery drain", delta=1.0,
                     z=3.0, window="7d", description="d", status="investigating",
                     product_id=product.id)
    s.add(a)
    s.flush()
    inv = Investigation(anomaly_id=a.id, status="resolved", budget_tier="standard",
                        product_id=product.id)
    s.add(inv)
    s.flush()
    return inv


def _user(s, email, role="reviewer"):
    u = User(email=email, password_hash="x", role=role)
    s.add(u)
    s.flush()
    return u


# ── comments ────────────────────────────────────────────────────────────

def test_a_comment_is_attributed_and_readable():
    with _db() as s:
        p = Product(name="Lumo")
        s.add(p)
        s.flush()
        inv = _case(s, p)
        u = _user(s, "ana@acme.com")
        collab.add_comment(s, inv.id, "I think this is the wakelock again.", u.id)
        thread = collab.comment_thread(s, inv.id)
        assert len(thread) == 1
        assert thread[0]["author"] == "ana"
        assert "wakelock" in thread[0]["body"]


def test_a_comment_must_have_an_author():
    """The GUEST principal carries id None precisely so nothing attributes its
    writes to user 0. An unattributed comment on a review thread is worse than
    no comment at all."""
    with _db() as s:
        p = Product(name="Lumo")
        s.add(p)
        s.flush()
        inv = _case(s, p)
        with pytest.raises(ValueError, match="signed-in"):
            collab.add_comment(s, inv.id, "anonymous opinion", None)


def test_an_empty_comment_is_refused():
    with _db() as s:
        p = Product(name="Lumo")
        s.add(p)
        s.flush()
        inv = _case(s, p)
        u = _user(s, "ana@acme.com")
        with pytest.raises(ValueError):
            collab.add_comment(s, inv.id, "   ", u.id)


def test_threads_stay_one_level_deep():
    """A reply-to-a-reply chain buries the decision a PM came to find, so a
    nested reply re-attaches to the root."""
    with _db() as s:
        p = Product(name="Lumo")
        s.add(p)
        s.flush()
        inv = _case(s, p)
        u = _user(s, "ana@acme.com")
        root = collab.add_comment(s, inv.id, "root", u.id)
        reply = collab.add_comment(s, inv.id, "reply", u.id, parent_id=root.id)
        deep = collab.add_comment(s, inv.id, "reply to reply", u.id, parent_id=reply.id)
        assert deep.parent_id == root.id
        thread = collab.comment_thread(s, inv.id)
        assert len(thread) == 1 and len(thread[0]["replies"]) == 2


def test_a_reply_cannot_be_attached_to_another_cases_comment():
    with _db() as s:
        p = Product(name="Lumo")
        s.add(p)
        s.flush()
        inv_a, inv_b = _case(s, p, "a"), _case(s, p, "b")
        u = _user(s, "ana@acme.com")
        root = collab.add_comment(s, inv_a.id, "on case A", u.id)
        with pytest.raises(ValueError, match="does not belong"):
            collab.add_comment(s, inv_b.id, "smuggled", u.id, parent_id=root.id)


def test_deleting_a_comment_keeps_the_thread_honest():
    """Soft delete: the replies keep their anchor and the audit trail behind a
    challenge decision is not silently rewritten."""
    with _db() as s:
        p = Product(name="Lumo")
        s.add(p)
        s.flush()
        inv = _case(s, p)
        u = _user(s, "ana@acme.com")
        root = collab.add_comment(s, inv.id, "the original claim", u.id)
        collab.add_comment(s, inv.id, "a reply that must survive", u.id, parent_id=root.id)
        collab.delete_comment(s, root, u.id)
        thread = collab.comment_thread(s, inv.id)
        assert thread[0]["deleted"] is True
        assert thread[0]["body"] is None
        assert len(thread[0]["replies"]) == 1


def test_you_cannot_delete_someone_elses_comment():
    with _db() as s:
        p = Product(name="Lumo")
        s.add(p)
        s.flush()
        inv = _case(s, p)
        ana, bo = _user(s, "ana@acme.com"), _user(s, "bo@acme.com")
        c = collab.add_comment(s, inv.id, "mine", ana.id)
        with pytest.raises(PermissionError):
            collab.delete_comment(s, c, bo.id)
        assert collab.delete_comment(s, c, bo.id, is_admin=True).deleted_at is not None


def test_you_cannot_edit_someone_elses_comment():
    with _db() as s:
        p = Product(name="Lumo")
        s.add(p)
        s.flush()
        inv = _case(s, p)
        ana, bo = _user(s, "ana@acme.com"), _user(s, "bo@acme.com")
        c = collab.add_comment(s, inv.id, "mine", ana.id)
        with pytest.raises(PermissionError):
            collab.edit_comment(s, c, "hijacked", bo.id)


# ── mentions ────────────────────────────────────────────────────────────

def test_a_mention_resolves_to_a_real_user():
    with _db() as s:
        p = Product(name="Lumo")
        s.add(p)
        s.flush()
        inv = _case(s, p)
        ana, bo = _user(s, "ana@acme.com"), _user(s, "bo@acme.com")
        collab.add_comment(s, inv.id, "@bo can you confirm the wakelock?", ana.id)
        rows = s.scalars(select(Mention)).all()
        assert [m.user_id for m in rows] == [bo.id]


def test_a_mention_of_nobody_is_dropped():
    """An @handle nobody owns must not become a notification pointing nowhere."""
    with _db() as s:
        p = Product(name="Lumo")
        s.add(p)
        s.flush()
        inv = _case(s, p)
        ana = _user(s, "ana@acme.com")
        collab.add_comment(s, inv.id, "@nobody @ghost please look", ana.id)
        assert s.scalars(select(Mention)).all() == []


def test_mentioning_yourself_does_not_fill_your_own_inbox():
    with _db() as s:
        p = Product(name="Lumo")
        s.add(p)
        s.flush()
        inv = _case(s, p)
        ana = _user(s, "ana@acme.com")
        collab.add_comment(s, inv.id, "note to self @ana", ana.id)
        assert s.scalars(select(Mention)).all() == []


def test_a_full_email_and_a_bare_handle_both_resolve():
    with _db() as s:
        p = Product(name="Lumo")
        s.add(p)
        s.flush()
        inv = _case(s, p)
        ana, bo = _user(s, "ana@acme.com"), _user(s, "bo@acme.com")
        collab.add_comment(s, inv.id, "@bo@acme.com and @BO again", ana.id)
        assert {m.user_id for m in s.scalars(select(Mention)).all()} == {bo.id}


def test_editing_a_typo_does_not_un_notify_someone():
    """They may already have acted on the notification."""
    with _db() as s:
        p = Product(name="Lumo")
        s.add(p)
        s.flush()
        inv = _case(s, p)
        ana, bo = _user(s, "ana@acme.com"), _user(s, "bo@acme.com")
        c = collab.add_comment(s, inv.id, "@bo look at this", ana.id)
        collab.edit_comment(s, c, "actually never mind", ana.id)
        assert len(s.scalars(select(Mention)).all()) == 1


def test_the_inbox_shows_unread_mentions_and_can_be_cleared():
    with _db() as s:
        p = Product(name="Lumo")
        s.add(p)
        s.flush()
        inv = _case(s, p)
        ana, bo = _user(s, "ana@acme.com"), _user(s, "bo@acme.com")
        collab.add_comment(s, inv.id, "@bo one", ana.id)
        collab.add_comment(s, inv.id, "@bo two", ana.id)
        assert len(collab.inbox(s, bo.id)) == 2
        assert collab.mark_read(s, bo.id) == 2
        assert collab.inbox(s, bo.id) == []


def test_one_user_cannot_clear_anothers_inbox():
    with _db() as s:
        p = Product(name="Lumo")
        s.add(p)
        s.flush()
        inv = _case(s, p)
        ana, bo = _user(s, "ana@acme.com"), _user(s, "bo@acme.com")
        collab.add_comment(s, inv.id, "@bo look", ana.id)
        assert collab.mark_read(s, ana.id) == 0
        assert len(collab.inbox(s, bo.id)) == 1


def test_a_deleted_comment_drops_out_of_the_inbox():
    with _db() as s:
        p = Product(name="Lumo")
        s.add(p)
        s.flush()
        inv = _case(s, p)
        ana, bo = _user(s, "ana@acme.com"), _user(s, "bo@acme.com")
        c = collab.add_comment(s, inv.id, "@bo look", ana.id)
        collab.delete_comment(s, c, ana.id)
        assert collab.inbox(s, bo.id) == []


# ── review sign-off ─────────────────────────────────────────────────────

def test_a_review_request_does_not_change_the_finding():
    """Sign-off records who agreed; approve/challenge remain the only paths to
    a finding's status, so it cannot smuggle a conclusion past the guards."""
    with _db() as s:
        p = Product(name="Lumo")
        s.add(p)
        s.flush()
        inv = _case(s, p)
        ana = _user(s, "ana@acme.com")
        req = collab.request_review(s, inv.id, ana.id, note="does the evidence hold?")
        before = inv.status
        collab.resolve_request(s, req, "approved")
        assert req.status == "approved" and req.resolved_at is not None
        assert inv.status == before


def test_asking_twice_does_not_stack_duplicate_requests():
    with _db() as s:
        p = Product(name="Lumo")
        s.add(p)
        s.flush()
        inv = _case(s, p)
        ana = _user(s, "ana@acme.com")
        a = collab.request_review(s, inv.id, ana.id)
        b = collab.request_review(s, inv.id, ana.id)
        assert a.id == b.id
        assert len(s.scalars(select(ReviewRequest)).all()) == 1


def test_you_cannot_request_review_from_a_user_who_does_not_exist():
    with _db() as s:
        p = Product(name="Lumo")
        s.add(p)
        s.flush()
        inv = _case(s, p)
        ana = _user(s, "ana@acme.com")
        with pytest.raises(ValueError, match="does not exist"):
            collab.request_review(s, inv.id, ana.id, requested_of_id=9999)


def test_a_request_cannot_be_resolved_back_to_pending():
    with _db() as s:
        p = Product(name="Lumo")
        s.add(p)
        s.flush()
        inv = _case(s, p)
        req = collab.request_review(s, inv.id, _user(s, "ana@acme.com").id)
        with pytest.raises(ValueError):
            collab.resolve_request(s, req, "pending")


# ── team dashboard ──────────────────────────────────────────────────────

def test_the_team_dashboard_is_product_scoped():
    """One product's dashboard must never show another's activity."""
    with _db() as s:
        lumo, other = Product(name="Lumo"), Product(name="Other")
        s.add_all([lumo, other])
        s.flush()
        inv_l, inv_o = _case(s, lumo, "l"), _case(s, other, "o")
        ana = _user(s, "ana@acme.com")
        collab.add_comment(s, inv_l.id, "lumo discussion", ana.id)
        collab.add_comment(s, inv_o.id, "other product discussion", ana.id)
        collab.request_review(s, inv_o.id, ana.id)

        view = collab.team_activity(s, product_id=lumo.id)
        assert len(view["recent_comments"]) == 1
        assert "lumo" in view["recent_comments"][0]["excerpt"]
        assert view["open_request_count"] == 0


def test_the_dashboard_surfaces_what_is_awaiting_review():
    with _db() as s:
        p = Product(name="Lumo")
        s.add(p)
        s.flush()
        inv = _case(s, p)
        ana, bo = _user(s, "ana@acme.com"), _user(s, "bo@acme.com")
        collab.request_review(s, inv.id, ana.id, requested_of_id=bo.id,
                              note="check the evidence")
        view = collab.team_activity(s, product_id=p.id)
        assert view["open_request_count"] == 1
        assert view["awaiting_review"][0]["requested_of"] == "bo"


# ── the HTTP surface: scoping, guests, IDOR ─────────────────────────────

@pytest.fixture()
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session_ = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_session, "_engine", engine)
    monkeypatch.setattr(db_session, "_SessionLocal", Session_)
    monkeypatch.setattr(db_session, "get_engine", lambda db_url=None: engine)
    from fastapi.testclient import TestClient
    from echolens.api.app import app
    with Session_() as s:
        real, demo = Product(name="Real"), Product(name="Demo", is_demo=True)
        s.add_all([real, demo])
        s.flush()
        inv_real, inv_demo = _case(s, real, "r"), _case(s, demo, "d")
        s.commit()
        ids = {"real": real.id, "demo": demo.id,
               "inv_real": inv_real.id, "inv_demo": inv_demo.id}
    return TestClient(app), ids


def test_a_guest_can_read_a_thread_but_not_post(client, monkeypatch):
    from echolens.config import settings
    c, ids = client
    monkeypatch.setattr(settings, "echolens_env", "staging", raising=False)
    monkeypatch.setattr(settings, "allow_guest", True, raising=False)

    r = c.get(f"/investigations/{ids['inv_demo']}/comments?product_id={ids['demo']}")
    assert r.status_code == 200
    w = c.post(f"/investigations/{ids['inv_demo']}/comments?product_id={ids['demo']}",
               json={"body": "guest opinion"})
    assert w.status_code == 403


def test_a_guest_cannot_read_a_real_products_thread(client, monkeypatch):
    """404, not 403 — a 403 would confirm the case exists."""
    from echolens.config import settings
    c, ids = client
    monkeypatch.setattr(settings, "echolens_env", "staging", raising=False)
    monkeypatch.setattr(settings, "allow_guest", True, raising=False)
    r = c.get(f"/investigations/{ids['inv_real']}/comments?product_id={ids['real']}")
    assert r.status_code == 404


def test_a_comment_cannot_be_read_across_products(client):
    """Filtering a list is not authorisation; single-resource routes need the
    ownership check too."""
    c, ids = client
    r = c.get(f"/investigations/{ids['inv_real']}/comments?product_id={ids['demo']}")
    assert r.status_code == 404


def test_posting_and_reading_a_comment_over_http(client):
    c, ids = client
    r = c.post(f"/investigations/{ids['inv_real']}/comments?product_id={ids['real']}",
               json={"body": "the evidence looks thin to me"})
    assert r.status_code == 200, r.text
    assert len(r.json()["comments"]) == 1
    got = c.get(f"/investigations/{ids['inv_real']}/comments?product_id={ids['real']}")
    assert "thin" in got.json()["comments"][0]["body"]


def test_an_over_long_comment_is_422_not_500(client):
    c, ids = client
    r = c.post(f"/investigations/{ids['inv_real']}/comments?product_id={ids['real']}",
               json={"body": "x" * (collab.MAX_COMMENT_CHARS + 1)})
    assert r.status_code == 422


def test_the_team_endpoint_is_scoped(client):
    c, ids = client
    c.post(f"/investigations/{ids['inv_real']}/comments?product_id={ids['real']}",
           json={"body": "real product talk"})
    view = c.get(f"/team?product_id={ids['demo']}").json()
    assert view["recent_comments"] == []
