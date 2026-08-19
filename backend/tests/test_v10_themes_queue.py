"""v10: theme quality (cluster + label) and the batched investigation queue."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from echolens.db.models import (
    AnomalyEvent, Base, Investigation, Product, QueuedInvestigation, Review)

NOW = datetime(2026, 7, 20, tzinfo=timezone.utc)

# Joplin-shaped: three distinct problems, phrased the way people actually write.
JOPLIN = [
    "I'm getting extra blank lines between paragraphs in the editor after the update",
    "The editor adds blank lines between my paragraphs, it's really annoying",
    "Extra empty lines keep appearing between lines when I type in Joplin",
    "Sync with Dropbox fails silently, I'm never told it didn't work",
    "Joplin sync to Dropbox just stops working, no error message at all",
    "Dropbox synchronisation fails and it's silent, notes don't upload",
    "My notes disappeared after switching to my other device",
    "Lost all my notes when I moved between devices, it's a disaster",
    "Notes vanish when syncing across devices, I'm losing work",
]


class GroupingLLM:
    """The batched grouping call. The third group is deliberately mislabelled
    with the product's own name at low confidence — the guards must catch it."""

    def __init__(self, clusters=None):
        self.calls = 0
        self._clusters = clusters

    def complete_json(self, system, user, schema, agent):
        self.calls += 1
        clusters = self._clusters if self._clusters is not None else [
            {"review_ids": [0, 1, 2],
             "statement": "Editor inserts extra blank lines after the latest update",
             "slug": "editor-blank-lines", "label_confidence": 0.86},
            {"review_ids": [3, 4, 5],
             "statement": "Dropbox sync fails silently with no error shown",
             "slug": "dropbox-sync-silent", "label_confidence": 0.81},
            {"review_ids": [6, 7, 8], "statement": "Joplin",
             "slug": "joplin", "label_confidence": 0.3},
        ]

        class R:
            parsed = {"clusters": clusters}
        return R()


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _joplin(s):
    """Seed the Joplin corpus and return the SESSION (callers keep using it)."""
    s.add(Product(name="Joplin", package_name="net.cozic.joplin"))
    s.flush()
    for i, text in enumerate(JOPLIN):
        s.add(Review(source="play_store", ext_id=f"j{i}", rating=1, text=text,
                     product="Joplin", created_at=NOW - timedelta(days=i % 7)))
    s.commit()
    return s


# ── FIX 1: theme quality ────────────────────────────────────────────────

JUNK = ["i'm", "it's", "joplin", "lines between", "app", "the app", "great app",
        "Joplin app is bad", "notes", "im"]


@pytest.mark.parametrize("junk", JUNK)
def test_junk_labels_are_rejected(junk):
    """The exact garbage the n-gram version surfaced on real data."""
    from echolens.themes.discover import banned_terms, is_usable_statement
    banned = banned_terms("Joplin", "net.cozic.joplin")
    assert is_usable_statement(junk, banned) is False


@pytest.mark.parametrize("good", [
    "Editor inserts extra blank lines after the latest update",
    "Dropbox sync fails silently with no error shown",
    "Notes disappear after switching between devices",
])
def test_real_problem_statements_are_accepted(good):
    from echolens.themes.discover import banned_terms, is_usable_statement
    assert is_usable_statement(good, banned_terms("Joplin", "net.cozic.joplin")) is True


def test_discovery_yields_sentences_not_word_fragments():
    """The headline requirement: 'blank lines' becomes a problem statement."""
    s = _joplin(_session())
    from echolens.themes.discover import discover_themes
    llm = GroupingLLM()
    r = discover_themes(s, "Joplin", llm=llm, package_name="net.cozic.joplin", as_of=NOW)

    assert llm.calls == 1, "labelling must be ONE batched call, not one per cluster"
    assert len(r["themes"]) == 3
    for th in r["themes"]:
        assert len(th["statement"].split()) >= 4, f"not a sentence: {th['statement']!r}"
        assert th["count"] >= 2, "a group of one is not a theme"
        assert th["verbatims"], "every theme carries the reviews that produced it"
    labels = " | ".join(t["statement"].lower() for t in r["themes"])
    for junk in ("i'm", "it's", "lines between"):
        assert junk not in labels.split(" | "), f"junk theme survived: {junk}"


def test_low_confidence_label_falls_back_to_a_real_verbatim():
    """Never show a one-word theme — use a sentence a customer actually wrote."""
    s = _joplin(_session())
    from echolens.themes.discover import discover_themes
    r = discover_themes(s, "Joplin", llm=GroupingLLM(), package_name="net.cozic.joplin",
                        as_of=NOW)
    fell_back = [t for t in r["themes"] if t["label_source"] == "verbatim"]
    assert len(fell_back) == 1, "the 0.3-confidence 'Joplin' label should be replaced"
    t = fell_back[0]
    assert t["statement"] != "Joplin"
    assert t["statement"] in [" ".join(x.split()) for x in JOPLIN]
    assert "joplin" not in t["slug"], "the rejected label must not survive as the slug"


def test_the_products_own_name_is_never_a_theme():
    s = _joplin(_session())
    from echolens.themes.discover import discover_themes
    r = discover_themes(s, "Joplin", llm=GroupingLLM(clusters=[
        {"review_ids": [0, 1, 2], "statement": "Joplin is broken",
         "slug": "joplin-broken", "label_confidence": 0.9}]),
        package_name="net.cozic.joplin", as_of=NOW)
    assert r["themes"][0]["label_source"] == "verbatim"


def test_singleton_groups_are_not_themes():
    s = _joplin(_session())
    from echolens.themes.discover import discover_themes
    r = discover_themes(s, "Joplin", llm=GroupingLLM(clusters=[
        {"review_ids": [0], "statement": "Editor inserts extra blank lines on update",
         "slug": "x", "label_confidence": 0.9}]), as_of=NOW)
    assert r["themes"] == []


def test_discovery_is_cached_until_new_reviews_arrive():
    """Embedding + an LLM call per page load would be absurd."""
    s = _joplin(_session())
    from echolens.themes.discover import cached_themes
    llm = GroupingLLM()
    first = cached_themes(s, "Joplin", llm=llm, as_of=NOW)
    second = cached_themes(s, "Joplin", llm=llm, as_of=NOW)
    assert first["cached"] is False and second["cached"] is True
    assert llm.calls == 1, "the cached read must not call the LLM again"

    s.add(Review(source="play_store", ext_id="new", rating=1,
                 product="Joplin", text="Search returns nothing for tags now",
                 created_at=NOW))
    s.commit()
    third = cached_themes(s, "Joplin", llm=llm, as_of=NOW)
    assert third["cached"] is False, "new data must invalidate the cache"
    assert llm.calls == 2


# ── FIX 2: the queue ────────────────────────────────────────────────────

def _queue_three(s, pid):
    from echolens.orchestrator.queue import enqueue_theme
    return [enqueue_theme(s, product_id=pid, slug=f"theme-{i}", statement=f"Problem {i}",
                          selection_order=i) for i in range(3)]


def test_three_selected_with_a_daily_limit_of_two_defers_the_third():
    """The stated scenario: 2 run, 1 queues for tomorrow — visibly, not silently."""
    from echolens.orchestrator.queue import queue_view
    s = _session()
    p = Product(name="Joplin")
    s.add(p)
    s.flush()
    _queue_three(s, p.id)
    s.commit()

    view = queue_view(s, p.id, daily_limit=2, as_of=NOW)
    assert [q["status"] for q in view["queued"]] == ["queued", "queued", "deferred"]
    assert view["queued"][2]["note"] == "daily limit reached — runs tomorrow"
    assert view["remaining_today"] == 2
    # nothing was dropped
    assert len(view["queued"]) == 3


def test_the_queue_runs_in_priority_then_selection_order():
    from echolens.orchestrator.queue import enqueue_anomaly, enqueue_theme, pending
    s = _session()
    p = Product(name="Joplin")
    s.add(p)
    s.flush()
    enqueue_theme(s, product_id=p.id, slug="t-a", statement="A", selection_order=0)
    enqueue_theme(s, product_id=p.id, slug="t-b", statement="B", selection_order=1)
    sev1 = AnomalyEvent(slug="spike", type="negative_review_spike", metric="m",
                        delta=0.5, z=4.2, window="7d", description="1-star spike",
                        status="pending", product_id=p.id)
    s.add(sev1)
    s.flush()
    enqueue_anomaly(s, sev1)
    s.commit()
    order = [r.title for r in pending(s, p.id)]
    assert order[0] == "1-star spike", "a real SEV1 spike outranks manual picks"
    assert order[1:] == ["A", "B"], "manual picks keep the order they were selected in"


def test_selecting_a_theme_already_under_investigation_does_not_duplicate():
    from echolens.orchestrator.queue import enqueue_theme
    s = _session()
    p = Product(name="Joplin")
    s.add(p)
    s.flush()
    first = enqueue_theme(s, product_id=p.id, slug="t-a", statement="A")
    assert first["status"] == "queued"
    again = enqueue_theme(s, product_id=p.id, slug="t-a", statement="A")
    assert again["status"] == "already" and again["reason"] == "queued"
    s.commit()
    assert len(s.scalars(select(QueuedInvestigation)).all()) == 1
    assert len(s.scalars(select(AnomalyEvent)).all()) == 1


def test_a_theme_with_an_open_case_links_to_it_instead_of_queueing():
    from echolens.orchestrator.queue import enqueue_theme
    s = _session()
    p = Product(name="Joplin")
    s.add(p)
    s.flush()
    a = AnomalyEvent(slug="t-a", type="manual_theme", metric="theme volume", delta=0.0,
                     z=0.0, window="90d", description="A", status="investigating",
                     product_id=p.id)
    s.add(a)
    s.flush()
    inv = Investigation(anomaly_id=a.id, status="running", opened_by="anomaly",
                        budget_tier="quick", budget_json={}, product_id=p.id)
    s.add(inv)
    s.commit()

    res = enqueue_theme(s, product_id=p.id, slug="t-a", statement="A")
    assert res["status"] == "already"
    assert res["reason"] == "investigating"
    assert res["investigation_id"] == inv.id, "the UI needs the case to link to"
    assert s.scalars(select(QueuedInvestigation)).all() == []


def test_manual_themes_create_the_same_records_as_spike_driven_ones():
    """So dedupe, scoping and the archive apply without a parallel code path."""
    from echolens.orchestrator.queue import enqueue_theme
    s = _session()
    p = Product(name="Joplin")
    s.add(p)
    s.flush()
    enqueue_theme(s, product_id=p.id, slug="t-a", statement="Sync fails silently")
    s.commit()
    a = s.scalars(select(AnomalyEvent).where(AnomalyEvent.slug == "t-a")).first()
    assert a is not None
    assert a.type == "manual_theme" and a.product_id == p.id
    assert a.description == "Sync fails silently"


def test_claim_next_stops_at_the_daily_budget():
    from echolens.orchestrator.queue import claim_next
    s = _session()
    p = Product(name="Joplin")
    s.add(p)
    s.flush()
    _queue_three(s, p.id)
    # two cases already created today
    for _ in range(2):
        s.add(Investigation(anomaly_id=None, status="resolved", opened_by="anomaly",
                            budget_tier="quick", budget_json={}, product_id=p.id,
                            created_at=NOW))
    s.commit()
    assert claim_next(s, p.id, daily_limit=2, as_of=NOW) is None, "budget spent"
    assert claim_next(s, p.id, daily_limit=3, as_of=NOW) is not None


def test_cancel_removes_a_queued_item_but_not_a_running_one():
    from echolens.orchestrator.queue import cancel
    s = _session()
    p = Product(name="Joplin")
    s.add(p)
    s.flush()
    rows = _queue_three(s, p.id)
    s.commit()
    assert cancel(s, rows[0]["queue_id"]) is True
    running = s.get(QueuedInvestigation, rows[1]["queue_id"])
    running.status = "running"
    s.flush()
    assert cancel(s, rows[1]["queue_id"]) is False, "cancelling mid-run would orphan a case"
