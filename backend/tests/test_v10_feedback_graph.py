"""v10 — the unified feedback graph: one complaint, every voice.

Exit criteria under test:
  1. one root cause proven from >= 3 different sources in a single finding
  2. duplicate cross-source complaints collapse to ONE impact number
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from echolens.db.models import (
    Base, FeedbackEntry, Investigation, Issue, Post, Product, Review)

NOW = datetime(2026, 7, 20, tzinfo=timezone.utc)
COMPLAINT = "Background sync drains the battery overnight"


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _four_witnesses(s, product="Lumo"):
    """The same problem, reported in four different places by four kinds of person."""
    s.add(Product(name=product))
    s.add(Review(source="play_store", ext_id="r1", rating=1,
                 text="Battery drains overnight, something keeps syncing in the background",
                 product=product, created_at=NOW - timedelta(days=2)))
    s.add(Issue(ext_id="#412", title="Background sync holds a wakelock",
                body_snippet="the sync service never releases the wakelock, battery dies",
                state="open", reactions=31, product=product,
                created_at=NOW - timedelta(days=3)))
    s.add(FeedbackEntry(channel="support", ext_id="support-88",
                        text="Customer reports the battery is empty each morning since 3.2",
                        product=product, author_kind="agent", priority="p1",
                        status="open", created_at=NOW - timedelta(days=1)))
    s.add(Post(source="reddit", ext_id="t3_x1", subreddit="androidapps",
               text_snippet="anyone else getting massive battery drain from the sync?",
               product=product, created_at=NOW - timedelta(days=4)))
    s.commit()
    return s


# ── normalisation ───────────────────────────────────────────────────────

def test_every_channel_normalises_into_one_shape():
    from echolens.feedback import collect_items
    s = _four_witnesses(_session())
    items = collect_items(s, "Lumo", since=NOW - timedelta(days=30), until=NOW)
    assert {i.channel for i in items} == {"play_store", "github", "support", "reddit"}
    for i in items:
        assert i.ref and i.text and i.created_at is not None
        assert i.audience in {"users", "engineers", "support", "community"}
    # who is speaking is preserved, not flattened away
    kinds = {i.channel: i.author_kind for i in items}
    assert kinds["github"] == "engineer" and kinds["support"] == "agent"


def test_a_high_reaction_issue_outweighs_a_passing_mention():
    from echolens.feedback import collect_items
    s = _four_witnesses(_session())
    items = {i.channel: i for i in collect_items(s, "Lumo", since=NOW - timedelta(days=30),
                                                 until=NOW)}
    assert items["github"].weight > items["reddit"].weight
    # ...but bounded, so one loud issue can't dominate the whole graph
    assert items["github"].weight <= 3.0


# ── corroboration: breadth beats volume ─────────────────────────────────

def _items(channel, n, distinct=True):
    from echolens.feedback import FeedbackItem
    return [FeedbackItem(ref=f"{channel}-{i}", channel=channel,
                         text=f"complaint {channel} {i}" if distinct else "same complaint",
                         created_at=NOW) for i in range(n)]


def test_four_channels_beat_forty_reviews_in_one():
    """THE scoring claim: diversity of source outranks raw volume."""
    from echolens.feedback import corroboration
    loud = corroboration(_items("play_store", 40))
    broad = corroboration(_items("play_store", 1) + _items("github", 1)
                          + _items("support", 1) + _items("reddit", 1))
    assert broad["score"] > loud["score"], (
        f"breadth must win: broad={broad['score']} loud={loud['score']}")
    assert loud["band"] == "single-source" and broad["band"] == "corroborated"


def test_no_single_channel_can_prove_a_problem_alone():
    """However loud one channel gets, it stays under the cap — that ceiling is
    what makes 'volume is not corroboration' structural rather than advisory."""
    from echolens.feedback import CHANNEL_CAP, corroboration
    for n in (5, 50, 500):
        assert corroboration(_items("play_store", n))["score"] <= CHANNEL_CAP + 1e-9


def test_corroboration_rises_with_each_independent_channel():
    from echolens.feedback import corroboration
    scores = []
    for chans in (["play_store"], ["play_store", "github"],
                  ["play_store", "github", "support"],
                  ["play_store", "github", "support", "reddit"]):
        items = [x for c in chans for x in _items(c, 2)]
        scores.append(corroboration(items)["score"])
    assert scores == sorted(scores), f"more channels must never score lower: {scores}"
    assert scores[2] > scores[1] > scores[0]


# ── exit criterion 2: duplicates collapse to ONE impact number ──────────

def test_the_same_complaint_in_two_channels_counts_once():
    """A user who files a ticket and then leaves a review is one affected person.
    Counting them twice inflates impact exactly when a problem is escalating."""
    from echolens.feedback import FeedbackItem, dedupe_witnesses
    same = "Battery drains overnight after the update"
    items = [
        FeedbackItem(ref="r1", channel="play_store", text=same, created_at=NOW),
        FeedbackItem(ref="s1", channel="support", text=same, created_at=NOW),
        FeedbackItem(ref="r2", channel="play_store", text="Sync keeps failing", created_at=NOW),
    ]
    kept, collapsed = dedupe_witnesses(items)
    assert len(kept) == 2 and collapsed == 1
    # the reach is remembered even though the count isn't doubled
    survivor = [k for k in kept if k.text == same][0]
    assert "support" in survivor.meta["also_seen_in"]


def test_impact_reports_deduplicated_witnesses_across_channels():
    from echolens.impact import quantify
    s = _session()
    s.add(Product(name="Lumo"))
    dup = "Battery drains overnight after the update"
    s.add(Review(source="play_store", ext_id="r1", rating=1, text=dup,
                 product="Lumo", created_at=NOW - timedelta(days=1)))
    s.add(FeedbackEntry(channel="support", ext_id="s1", text=dup, product="Lumo",
                        created_at=NOW - timedelta(days=1)))
    s.add(Review(source="play_store", ext_id="r2", rating=1,
                 text="Battery drain is terrible since I updated", product="Lumo",
                 created_at=NOW - timedelta(days=2)))
    s.commit()

    anomaly = type("A", (), {"description": "battery drain", "metric": "battery mentions"})()
    imp = quantify(s, anomaly, {"summary": "Battery drains overnight", "prose": ""},
                   product="Lumo")
    cross = imp["cross_source"]
    assert cross["raw_mentions"] == 3
    assert cross["witnesses"] == 2, "the duplicated complaint must count once"
    assert cross["collapsed_duplicates"] == 1
    assert set(cross["channels"]) == {"play_store", "support"}


# ── exit criterion 1: >= 3 sources behind one finding ───────────────────

def test_a_finding_reports_the_breadth_of_its_own_evidence():
    from echolens.feedback_graph import evidence_breadth
    s = _four_witnesses(_session())
    refs = ["r1", "issue #412", "support support-88", "t3_x1"]
    breadth = evidence_breadth(s, refs, "Lumo", as_of=NOW)
    assert breadth["distinct_channels"] >= 3, breadth
    assert breadth["band"] == "corroborated"
    audiences = {c["audience"] for c in breadth["channels"]}
    assert {"users", "engineers", "support"} <= audiences


def test_breadth_is_honest_when_everything_came_from_one_place():
    from echolens.feedback_graph import evidence_breadth
    s = _four_witnesses(_session())
    breadth = evidence_breadth(s, ["r1"], "Lumo", as_of=NOW)
    assert breadth["distinct_channels"] == 1
    assert breadth["band"] == "single-source"


# ── channel of origin ───────────────────────────────────────────────────

def test_channel_of_origin_names_who_reports_it_and_who_never_sees_it():
    from echolens.feedback import channel_of_origin, corroboration
    corr = corroboration(_items("github", 3) + _items("play_store", 2))
    origin = channel_of_origin(corr, ["github", "play_store", "support"])
    assert [c["channel"] for c in origin["silent"]] == ["support"]
    assert "engineers on GitHub" in origin["summary"]
    assert "Support tickets" in origin["summary"]
    assert origin["loudest"] in {"github", "play_store"}


# ── the graph ───────────────────────────────────────────────────────────

class GraphLLM:
    """One batched call that groups the four witnesses into a single problem."""
    def __init__(self):
        self.calls = 0

    def complete_json(self, system, user, schema, agent):
        self.calls += 1

        class R:
            parsed = {"clusters": [{
                "review_ids": [0, 1, 2, 3],
                "statement": "Background sync drains the battery overnight",
                "slug": "sync-battery-drain", "label_confidence": 0.88}]}
        return R()


def test_the_graph_makes_four_witnesses_one_problem():
    """The headline: four channels, one node, counted once."""
    from echolens.feedback_graph import build_graph
    s = _four_witnesses(_session())
    llm = GraphLLM()
    g = build_graph(s, "Lumo", llm=llm, as_of=NOW)

    assert llm.calls == 1, "grouping must stay ONE batched call"
    assert len(g["nodes"]) == 1, "four reports of one problem are one node"
    node = g["nodes"][0]
    assert node["corroboration"]["distinct_channels"] == 4
    assert node["corroboration"]["band"] == "corroborated"
    assert node["impact_witnesses"] == 4
    assert g["corroborated"] == 1
    # every witness is retrievable, with its channel attributed
    assert {w["channel"] for w in node["witnesses"]} == {
        "play_store", "github", "support", "reddit"}


def test_the_graph_ranks_breadth_above_volume():
    from echolens.feedback_graph import build_graph
    s = _four_witnesses(_session())
    # a louder single-channel problem that should still rank BELOW the broad one
    for i in range(12):
        s.add(Review(source="play_store", ext_id=f"noise{i}", rating=1,
                     text=f"The new icon is ugly and I hate the redesign {i}",
                     product="Lumo", created_at=NOW - timedelta(days=5)))
    s.commit()

    class TwoGroups:
        def complete_json(self, system, user, schema, agent):
            class R:
                parsed = {"clusters": [
                    {"review_ids": list(range(4, 16)),
                     "statement": "The redesigned icon is disliked",
                     "slug": "icon-redesign", "label_confidence": 0.8},
                    {"review_ids": [0, 1, 2, 3],
                     "statement": "Background sync drains the battery overnight",
                     "slug": "sync-battery", "label_confidence": 0.9},
                ]}
            return R()

    g = build_graph(s, "Lumo", llm=TwoGroups(), as_of=NOW)
    assert len(g["nodes"]) == 2
    top = g["nodes"][0]
    assert top["corroboration"]["distinct_channels"] > g["nodes"][1]["corroboration"]["distinct_channels"]
    assert top["impact_witnesses"] < g["nodes"][1]["impact_witnesses"], (
        "the top node should have FEWER witnesses but more channels — that's the point")


def test_an_empty_product_yields_no_nodes_rather_than_guesses():
    from echolens.feedback_graph import build_graph
    s = _session()
    s.add(Product(name="Empty"))
    s.commit()
    g = build_graph(s, "Empty", llm=GraphLLM(), as_of=NOW)
    assert g["nodes"] == [] and g["items_considered"] == 0


# ── the new channels ────────────────────────────────────────────────────

def test_support_csv_imports_under_any_vendors_column_names():
    from echolens.importers.feedback_csv import import_feedback_csv
    s = _session()
    csv_text = (
        "Ticket ID,Subject,Created At,Priority,Status\n"
        "4411,App crashes when I open settings,2026-07-18,P1,open\n"
        "4412,Battery drains overnight,2026-07-17T09:30:00Z,normal,closed\n"
    )
    res = import_feedback_csv(s, csv_text, channel="support", product="Lumo")
    s.commit()
    assert res["inserted"] == 2 and res["skipped"] == 0
    rows = s.query(FeedbackEntry).all()
    assert {r.priority for r in rows} == {"P1", "normal"}
    assert all(r.channel == "support" and r.product == "Lumo" for r in rows)


def test_reimporting_the_same_export_inserts_nothing_new():
    from echolens.importers.feedback_csv import import_feedback_csv
    s = _session()
    csv_text = "id,body,date\n1,Sync keeps failing,2026-07-18\n"
    import_feedback_csv(s, csv_text, channel="support", product="Lumo")
    s.commit()
    again = import_feedback_csv(s, csv_text, channel="support", product="Lumo")
    s.commit()
    assert again["inserted"] == 0 and again["skipped"] == 1


def test_undated_rows_are_reported_not_silently_dropped():
    """Feedback with no usable date can't be windowed, so it can't be used — but
    the import must say so rather than quietly losing rows."""
    from echolens.importers.feedback_csv import import_feedback_csv
    s = _session()
    res = import_feedback_csv(s, "id,body,date\n1,Something broke,not-a-date\n",
                              channel="in_app", product="Lumo")
    assert res["inserted"] == 0 and res["undated"] == 1
    assert res["problems"] and "date" in res["problems"][0]


def test_an_unknown_channel_is_refused():
    from echolens.importers.feedback_csv import import_feedback_csv
    with pytest.raises(ValueError):
        import_feedback_csv(_session(), "id,body,date\n1,x,2026-07-18\n",
                            channel="telepathy")


# ── the "sync/battery on every new product" bug ─────────────────────────

def test_a_new_product_is_not_scanned_for_the_demos_themes():
    """Reported bug: every newly added product surfaced "Sync/battery issue
    reports" on its first scan. The detector had Lumo's demo themes hardcoded as
    the default, so every product on the system was measured against them."""
    from echolens.detector.detect import scan
    s = _session()
    p = Product(name="Firefox", package_name="org.mozilla.firefox")
    s.add(p)
    s.flush()
    # A real product with its own, entirely unrelated complaints.
    for i in range(40):
        s.add(Review(source="play_store", ext_id=f"ff{i}", rating=1,
                     text="Tabs keep reloading when I switch between them",
                     product="Firefox", created_at=NOW - timedelta(days=i % 20)))
    s.add(Issue(ext_id="#900", title="Tab reload on switch",
                body_snippet="tabs discard state when switching", state="open",
                reactions=4, product="Firefox", created_at=NOW - timedelta(days=2)))
    s.commit()

    found = scan(s, product="Firefox", product_id=p.id, as_of=NOW)
    blob = " ".join(f"{a.metric} {a.description}".lower() for a in found)
    for ghost in ("sync/battery", "battery drain", "shipping cost", "print-shipping"):
        assert ghost not in blob, f"the demo's theme leaked into Firefox: {ghost!r}"


def test_derived_terms_come_from_the_products_own_words():
    from echolens.detector.detect import _derived_terms
    terms = [t for t, _label in _derived_terms(
        ["tabs keep reloading when switching"] * 6 + ["tab reload loses my place"] * 4)]
    assert terms, "a product with real complaints must yield terms"
    assert any("tab" in t for t in terms)
    assert not any("battery" in t or "shipping" in t for t in terms)


def test_too_little_data_yields_no_invented_themes():
    """Silent beats invented: 3 reviews cannot characterise a product."""
    from echolens.detector.detect import _derived_terms
    assert _derived_terms(["it broke", "bad", "please fix"]) == []
