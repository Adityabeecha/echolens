"""Theme names are noun phrases, case headlines are clean, and the portfolio
never prints "null% negative"."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from echolens.textkit import THEME_LABEL_MAX, clean_headline, theme_label
from echolens.vocab import canonical_theme

# ── 1. emergent theme names ─────────────────────────────────────────────

BAD = {"Behind Cost", "Further Google", "Appear Background", "Automatic Conflict"}
_BAD_EDGES = {"behind", "further", "appear", "even", "though", "automatic"}


@pytest.mark.parametrize("terms,text", [
    (["behind", "cost"], None),
    (["further", "google"], None),
    (["appear", "background"], None),
    (["automatic", "conflict"], None),
    # The live names came from the alphabetically first two of up to six terms.
    (["cost", "shipping", "behind"], "Shipping cost is way behind what they promised"),
    (["background", "sync", "appear"], "Photos don't appear, background sync is broken"),
    (["conflict", "automatic", "calendar"], "Automatic updates cause a calendar conflict"),
    (["google", "further", "login"], "Google login fails, further attempts lock me out"),
])
def test_bad_live_names_become_noun_phrases(terms, text):
    theme = canonical_theme(terms, text)
    label = theme["label"]
    assert label not in BAD
    words = label.lower().split()
    assert words[0] not in _BAD_EDGES and words[-1] not in _BAD_EDGES
    assert label == label[:1].upper() + label[1:].lower() or words[0] == "google"
    assert len(label) <= THEME_LABEL_MAX


def test_specific_bad_examples_fall_back_to_the_content_noun():
    assert canonical_theme(["behind", "cost"])["label"] == "Cost"
    assert canonical_theme(["further", "google"])["label"] == "Google"
    assert canonical_theme(["appear", "background"])["label"] == "Background"
    assert canonical_theme(["automatic", "conflict"])["label"] == "Conflict"


@pytest.mark.parametrize("terms,text,expected", [
    (["background", "sync", "photos"], "background sync stopped working", "Background sync"),
    (["shipping", "cost"], None, "Shipping cost"),
    (["video", "crash"], "every video crash happens on 4K", "Video crash"),
    (["conflict", "automatic", "calendar"], "Automatic updates cause a calendar conflict",
     "Calendar conflict"),
])
def test_good_phrases_are_kept_in_sentence_case(terms, text, expected):
    assert theme_label(terms, text) == expected


def test_adjective_modifier_needs_the_text_to_have_said_it():
    assert theme_label(["automatic", "backup"]) == "Backup"
    assert theme_label(["automatic", "backup"], "the automatic backup never runs") == "Automatic backup"


def test_families_and_ids_are_unchanged():
    # Stored overrides and cross-product comparisons key on the id.
    assert canonical_theme(["behind", "cost"])["id"] == "behind-cost"
    assert canonical_theme(["further", "google"])["id"] == "further-google"
    assert canonical_theme(["automatic", "conflict"])["id"] == "automatic-conflict"
    battery = canonical_theme(["battery", "drain"])
    assert battery["id"] == "battery-drain" and battery["label"] == "Battery drain"


def test_no_noun_at_all_is_other():
    assert theme_label(["further", "behind", "appear"]) is None
    assert canonical_theme(["even", "though"])["label"] == "Other"


def test_label_is_bounded():
    long = "supercalifragilisticexpialidocious"
    assert len(theme_label([long, long + "x"]) or "") <= THEME_LABEL_MAX


# ── 2. case headlines ───────────────────────────────────────────────────

def test_headline_strips_citation_tags():
    assert clean_headline("Release v3.2.0 broke sync [ev_001][ev_002].") == "Release v3.2.0 broke sync."
    assert clean_headline("Sync breaks [ev_001] after login [ev_014]") == "Sync breaks after login"


def test_headline_keeps_version_lowercase_and_straight_quotes():
    assert clean_headline("V3.2.0’s background sync drains battery") == \
        "v3.2.0's background sync drains battery"
    assert clean_headline("“Save” fails on Android") == '"Save" fails on Android'
    assert clean_headline("Vimeo uploads stall") == "Vimeo uploads stall"


def test_case_title_uses_the_clean_headline():
    from echolens.cases import case_title
    from echolens.db.models import Finding
    f = Finding(summary="V3.2.0’s sync bug [ev_001][ev_003]")
    assert case_title(f, None) == "v3.2.0's sync bug"


def test_decision_doc_headline_is_clean_for_slack_and_email():
    from echolens.impact import decision_doc
    d = decision_doc({"summary": "Login loop [ev_002]"}, [], {}, "resolved")
    assert d["whats_broken"] == "Login loop"


# ── 3. negative share ───────────────────────────────────────────────────

@pytest.fixture()
def session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from echolens.db.models import Base
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as s:
        yield s


def _product(session, name):
    from echolens.db.models import Product
    p = Product(name=name)
    session.add(p)
    session.flush()
    return p


def _reviews(session, product, n, when, rating=1):
    from echolens.db.models import Review
    for i in range(n):
        session.add(Review(product=product, rating=rating, text=f"review {i}",
                           created_at=when, ext_id=f"{product}-{when:%j}-{rating}-{i}"))
    session.flush()


def test_old_data_only_gives_null_rate_with_reason(session):
    from echolens.portfolio import product_snapshot
    now = datetime(2026, 10, 25, tzinfo=timezone.utc)
    p = _product(session, "Quiet")
    _reviews(session, "Quiet", 12, now - timedelta(days=20))
    row = product_snapshot(session, p, now)
    assert row["has_data"] is True
    assert row["negative_rate_pct"] is None
    assert row["negative_rate_reason"] == "no reviews in the last 7 days"


def test_thin_recent_window_says_how_thin(session):
    from echolens.portfolio import product_snapshot
    now = datetime(2026, 10, 25, tzinfo=timezone.utc)
    p = _product(session, "Thin")
    _reviews(session, "Thin", 2, now - timedelta(days=1))
    row = product_snapshot(session, p, now)
    assert row["negative_rate_pct"] is None
    assert row["negative_rate_reason"].startswith("only 2 reviews in the last 7 days")


def test_real_rate_has_one_decimal_and_no_reason(session):
    from echolens.portfolio import product_snapshot
    now = datetime(2026, 10, 25, tzinfo=timezone.utc)
    p = _product(session, "Busy")
    _reviews(session, "Busy", 1, now - timedelta(days=1), rating=1)
    _reviews(session, "Busy", 6, now - timedelta(days=1), rating=5)
    row = product_snapshot(session, p, now)
    assert row["negative_rate_pct"] == 14.3
    assert row["negative_rate_reason"] is None


def test_no_data_has_no_reason(session):
    from echolens.portfolio import product_snapshot
    now = datetime(2026, 10, 25, tzinfo=timezone.utc)
    row = product_snapshot(session, _product(session, "Empty"), now)
    assert row["has_data"] is False
    assert row["negative_rate_pct"] is None and row["negative_rate_reason"] is None
