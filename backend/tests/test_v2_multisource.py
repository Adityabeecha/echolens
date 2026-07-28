"""v2.0 multi-source collectors.

Every test injects `fetch_fn`, so nothing here touches the network. Each is
named for what breaks if the behaviour is reverted.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from echolens.collectors.chrome_web_store import ChromeWebStoreCollector, _parse_batch
from echolens.collectors.feedback_base import ext_id_for
from echolens.collectors.github_extra import (
    GitHubActivityCollector, GitHubDiscussionsCollector, _split_repo)
from echolens.collectors.hacker_news import HackerNewsCollector
from echolens.collectors.registry import SOURCE_INFO, _BUILDERS
from echolens.collectors.stack_overflow import StackOverflowCollector
from echolens.db.models import FeedbackEntry, Review
from echolens.feedback import CHANNELS, TEAM_CHANNELS, collect_items

NOW = datetime(2026, 7, 20, tzinfo=timezone.utc)


def _epoch(dt: datetime) -> int:
    return int(dt.timestamp())


# ── Hacker News ─────────────────────────────────────────────────────────

def _hn_payload(hits):
    return {"hits": hits}


def _hn_story(oid="1", title="App crashes", text="", at=NOW, comment=None):
    hit = {"objectID": oid, "title": title, "story_text": text,
           "created_at_i": _epoch(at), "points": 12, "author": "someone"}
    if comment is not None:
        hit = {"objectID": oid, "comment_text": comment,
               "created_at_i": _epoch(at), "author": "someone"}
    return hit


def test_hn_ingests_stories_and_comments(session):
    c = HackerNewsCollector("lumo", "Lumo", fetch_fn=lambda: _hn_payload([
        _hn_story("1", "Lumo battery drain", "since the update"),
        _hn_story("2", comment="Battery dies in about two hours on my device now."),
    ]))
    r = c.run(session)
    assert r.ok and r.inserted == 2
    rows = session.scalars(select(FeedbackEntry)).all()
    assert {row.channel for row in rows} == {"hacker_news"}


def test_hn_skips_reflex_comments(session):
    """A two-word 'same here' would dilute every theme it landed in."""
    c = HackerNewsCollector("lumo", "Lumo", fetch_fn=lambda: _hn_payload([
        _hn_story("1", comment="same here"),
    ]))
    r = c.run(session)
    assert r.inserted == 0


def test_hn_strips_html_so_tags_do_not_become_vocabulary(session):
    c = HackerNewsCollector("lumo", "Lumo", fetch_fn=lambda: _hn_payload([
        _hn_story("1", comment="<p>The battery &quot;drains&quot; overnight every single time.</p>"),
    ]))
    c.run(session)
    row = session.scalars(select(FeedbackEntry)).first()
    assert "<p>" not in row.text and "&quot;" not in row.text
    assert '"drains"' in row.text


def test_hn_returns_items_oldest_first(session):
    """The base class freezes the watermark at a failed item and resumes there,
    which is only correct if items ascend in time."""
    older, newer = NOW - timedelta(days=3), NOW
    c = HackerNewsCollector("lumo", "Lumo", fetch_fn=lambda: _hn_payload([
        _hn_story("2", "newer", "body text here", at=newer),
        _hn_story("1", "older", "body text here", at=older),
    ]))
    items = c.fetch(since=None, limit=10)
    assert [i["objectID"] for i in items] == ["1", "2"]


def test_hn_rerun_does_not_duplicate(session):
    payload = _hn_payload([_hn_story("1", "Lumo battery drain", "since the update")])
    HackerNewsCollector("lumo", "Lumo", fetch_fn=lambda: payload).run(session)
    r2 = HackerNewsCollector("lumo", "Lumo", fetch_fn=lambda: payload).run(session)
    assert r2.inserted == 0 and r2.skipped_duplicate == 1


def test_undated_item_is_skipped_not_stamped_with_now(session):
    """Detectors bucket by created_at; an invented date reads as activity that
    never happened."""
    c = HackerNewsCollector("lumo", "Lumo", fetch_fn=lambda: _hn_payload([
        {"objectID": "1", "title": "Lumo crash", "story_text": "on launch",
         "created_at_i": None, "created_at": None},
    ]))
    r = c.run(session)
    assert r.inserted == 0
    assert session.scalars(select(FeedbackEntry)).first() is None


# ── Stack Overflow ──────────────────────────────────────────────────────

def _so_payload(items):
    return {"items": items}


def _so_q(qid=1, title="Lumo sync fails", body="<p>It stops after a while.</p>",
          at=NOW, answered=False):
    return {"question_id": qid, "title": title, "body": body,
            "creation_date": _epoch(at), "is_answered": answered,
            "score": 3, "tags": ["lumo"], "link": "https://so/q/1"}


def test_stack_overflow_ingests_questions(session):
    c = StackOverflowCollector("lumo", "Lumo", fetch_fn=lambda: _so_payload([_so_q()]))
    r = c.run(session)
    assert r.ok and r.inserted == 1
    row = session.scalars(select(FeedbackEntry)).first()
    assert row.channel == "stack_overflow"
    assert row.author_kind == "engineer"
    assert row.status == "unanswered"


def test_stack_overflow_drops_code_blocks_from_text(session):
    """A pasted stack trace is not the user's description and swamps themes."""
    body = "<p>Sync breaks.</p><pre>Traceback most recent call last File x</pre>"
    c = StackOverflowCollector("lumo", "Lumo",
                               fetch_fn=lambda: _so_payload([_so_q(body=body)]))
    c.run(session)
    row = session.scalars(select(FeedbackEntry)).first()
    assert "Sync breaks" in row.text
    assert "Traceback" not in row.text


def test_stack_overflow_api_error_is_surfaced_not_swallowed(session):
    def boom():
        raise RuntimeError("Stack Overflow error 502: throttle violation")

    r = StackOverflowCollector("lumo", "Lumo", fetch_fn=boom).run(session)
    assert not r.ok and "throttle" in r.error


def test_answered_state_is_recorded(session):
    c = StackOverflowCollector("lumo", "Lumo",
                               fetch_fn=lambda: _so_payload([_so_q(answered=True)]))
    c.run(session)
    assert session.scalars(select(FeedbackEntry)).first().status == "answered"


# ── GitHub Discussions ──────────────────────────────────────────────────

def _disc_payload(nodes):
    return {"data": {"repository": {"discussions": {"nodes": nodes}}}}


def _disc(did="D1", num=1, title="Battery drain", body="Since 3.2 it dies fast.",
          at=NOW, comments=()):
    return {"id": did, "number": num, "title": title, "bodyText": body,
            "createdAt": at.isoformat(), "url": "https://gh/d/1",
            "category": {"name": "Bug"}, "answer": None,
            "comments": {"nodes": list(comments)}}


def test_discussions_ingest_thread_and_comments(session):
    payload = _disc_payload([_disc(comments=[
        {"id": "C1", "bodyText": "Same on my phone since the update.",
         "createdAt": NOW.isoformat(), "url": "https://gh/c/1"},
    ])])
    r = GitHubDiscussionsCollector("acme/lumo", "Lumo", fetch_fn=lambda: payload).run(session)
    assert r.ok and r.inserted == 2


def test_discussions_are_a_separate_channel_from_issues(session):
    """Issues are filed by people who know how to file issues; discussions are
    where everyone else asks 'is it just me?'. Breadth scoring must treat them
    as independent witnesses."""
    r = GitHubDiscussionsCollector("acme/lumo", "Lumo",
                                   fetch_fn=lambda: _disc_payload([_disc()])).run(session)
    assert r.inserted == 1
    assert session.scalars(select(FeedbackEntry)).first().channel == "github_discussion"
    assert "github_discussion" in CHANNELS
    assert CHANNELS["github_discussion"]["audience"] != CHANNELS["github"]["audience"]


def test_discussions_graphql_errors_are_reported(session):
    def boom():
        raise RuntimeError("GitHub GraphQL: Bad credentials")

    r = GitHubDiscussionsCollector("acme/lumo", "Lumo", fetch_fn=boom).run(session)
    assert not r.ok and "Bad credentials" in r.error


def test_split_repo_rejects_a_bare_name():
    with pytest.raises(ValueError):
        _split_repo("lumo")
    assert _split_repo("acme/lumo") == ("acme", "lumo")


# ── GitHub activity (PRs / commits) ─────────────────────────────────────

def _activity(pulls=(), commits=()):
    return {"pulls": list(pulls), "commits": list(commits)}


def _pr(num=7, title="Fix battery drain", merged=NOW):
    return {"number": num, "title": title, "body": "Caps the wakelock.",
            "merged_at": merged.isoformat() if merged else None,
            "html_url": "https://gh/pr/7"}


def _commit(sha="abc123", msg="Cap the wakelock", at=NOW):
    return {"sha": sha, "commit": {"message": msg, "author": {"date": at.isoformat()}},
            "html_url": "https://gh/c/abc123"}


def test_activity_ingests_merged_prs_and_commits(session):
    r = GitHubActivityCollector("acme/lumo", "Lumo",
                                fetch_fn=lambda: _activity([_pr()], [_commit()])).run(session)
    assert r.ok and r.inserted == 2


def test_unmerged_prs_are_ignored(session):
    """An open PR has not shipped, so it cannot explain a change in behaviour."""
    r = GitHubActivityCollector("acme/lumo", "Lumo",
                                fetch_fn=lambda: _activity([_pr(merged=None)])).run(session)
    assert r.inserted == 0


def test_team_activity_is_not_counted_as_a_complaint_witness(session):
    """The decisive one. A maintainer's own PR describing a bug must never
    corroborate that users hit it — otherwise a team corroborates itself."""
    GitHubActivityCollector("acme/lumo", "Lumo",
                            fetch_fn=lambda: _activity([_pr()], [_commit()])).run(session)
    assert session.scalars(select(FeedbackEntry)).all(), "rows were stored"

    items = collect_items(session, product="Lumo", since=NOW - timedelta(days=30),
                          until=NOW + timedelta(days=1))
    assert [i for i in items if i.channel in TEAM_CHANNELS] == []


def test_team_channels_are_declared(session):
    assert TEAM_CHANNELS == frozenset({"github_pr", "github_commit"})


# ── Chrome Web Store ────────────────────────────────────────────────────

def test_chrome_web_store_ingests_reviews(session):
    rows = [["revid0001", 2, "Breaks on every page since the last update.", _epoch(NOW)]]
    r = ChromeWebStoreCollector("abcdefghijklmnopqrstuvwxyz123456", "Lumo",
                                fetch_fn=lambda: rows).run(session)
    assert r.ok and r.inserted == 1
    # Scoped to this source: the shared fixture seeds a synthetic play_store
    # corpus, so an unfiltered .first() reads someone else's row.
    rev = session.scalars(select(Review).where(
        Review.source == "chrome_web_store")).first()
    assert rev is not None and rev.rating == 2
    assert rev.ext_id.startswith("cws_")


def test_chrome_web_store_unrecognised_shape_raises_loudly():
    """No API exists, so the format can change. A shape we don't know must fail
    visibly (source marked stale) rather than return zero rows that read as
    'no complaints'."""
    with pytest.raises(RuntimeError, match="unrecognised response shape"):
        _parse_batch("totally not the envelope we expect")


def test_chrome_web_store_row_missing_a_rating_is_skipped(session):
    """rating<=2 is every negativity filter; a missing rating must not become 0."""
    rows = [["revid0002", None, "some text that is long enough", _epoch(NOW)]]
    r = ChromeWebStoreCollector("ext", "Lumo", fetch_fn=lambda: rows).run(session)
    assert r.inserted == 0


def test_chrome_web_store_handles_millisecond_timestamps(session):
    """The endpoint has used both seconds and ms; ms read as seconds lands the
    review ~50,000 years in the future and out of every detector window."""
    rows = [["revid0003", 1, "Crashes constantly on load.", _epoch(NOW) * 1000]]
    ChromeWebStoreCollector("ext", "Lumo", fetch_fn=lambda: rows).run(session)
    rev = session.scalars(select(Review).where(
        Review.ext_id == "cws_revid0003")).first()
    assert rev is not None and rev.created_at.year == 2026


# ── ext_id safety ───────────────────────────────────────────────────────

def test_ext_id_is_channel_qualified_so_channels_cannot_collide():
    """ext_id is globally unique; two channels both numbering from 1 would
    otherwise drop each other's rows as duplicates."""
    assert ext_id_for("hacker_news", "1") != ext_id_for("stack_overflow", "1")


def test_ext_id_hashes_rather_than_truncates_a_long_id():
    """Right-truncation is what collapsed distinct GitHub issues onto one id."""
    a = ext_id_for("forum", "x" * 200 + "A")
    b = ext_id_for("forum", "x" * 200 + "B")
    assert a != b
    assert len(a) <= 96 and len(b) <= 96


# ── registry wiring ─────────────────────────────────────────────────────

def test_every_source_has_a_label_and_hint():
    """The connect form is served from the registry, so a real source without
    info would render as a blank option.

    Asserted over SOURCE_INFO rather than _BUILDERS: other tests inject fake
    collectors into _BUILDERS at import time, and this test must not depend on
    whether they ran first.
    """
    for src, info in SOURCE_INFO.items():
        assert src in _BUILDERS, f"{src} has info but no collector"
        assert info["label"] and info["hint"]


def test_all_new_sources_are_connectable():
    for src in ("hacker_news", "stack_overflow", "chrome_web_store",
                "github_discussions", "github_activity"):
        assert src in _BUILDERS
        assert _BUILDERS[src]("ident", "Product") is not None
