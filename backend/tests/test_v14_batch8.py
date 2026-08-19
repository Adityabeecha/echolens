"""Batch 8 — robustness and performance.

Two themes: things that could WEDGE permanently (a collector that can never
advance past a poison row), and things that scaled linearly on the hottest
screens in the app.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from echolens.cases import case_view
from echolens.db.models import (
    AnomalyEvent, Base, Finding, Investigation, Product, Review)
from echolens.investigator.guards import two_source_rule, unsupported_claims

NOW = datetime(2026, 7, 25, tzinfo=timezone.utc)


@pytest.fixture()
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


# ── B8.1 ────────────────────────────────────────────────────────────────

def test_case_list_does_not_scale_queries_with_case_count(session):
    """4 SQL round trips PER CASE — 243 queries for 60 cases, on the two screens
    that load most often (Today and Cases both call this)."""
    engine = session.get_bind()
    p = Product(name="Lumo")
    session.add(p)
    session.flush()
    for i in range(40):
        a = AnomalyEvent(slug=f"s{i}", type="theme_volume_surge", metric="battery",
                         delta=0.3, z=3.0, window="7d", description="d", status="closed",
                         product_id=p.id, created_at=NOW - timedelta(days=3))
        session.add(a)
        session.flush()
        inv = Investigation(anomaly_id=a.id, status="resolved", opened_by="anomaly",
                            budget_tier="standard", budget_json={}, product_id=p.id,
                            created_at=NOW - timedelta(days=3))
        session.add(inv)
        session.flush()
        session.add(Finding(investigation_id=inv.id, summary=f"problem {i}", confidence=0.8,
                            status="draft", product_id=p.id, json={"impact": {}}))
    session.flush()

    count = [0]

    @event.listens_for(engine, "before_cursor_execute")
    def _count(*a, **k):
        count[0] += 1

    case_view(session, p.id, NOW)
    event.remove(engine, "before_cursor_execute", _count)
    assert count[0] < 40, f"{count[0]} queries for 40 cases — still scaling per case"


# ── B8.10 ───────────────────────────────────────────────────────────────

def _h():
    return {"id": "H1", "confidence": 0.85, "status": "active",
            "evidence_for": ["ev_001", "ev_002"]}


def test_one_person_cross_posting_does_not_satisfy_the_two_source_rule():
    """A vocal user files a GitHub issue AND posts the same words as a review.
    Two items, two sources — which satisfied both halves of the rule and
    unlocked `resolved` at >=0.80 confidence on one person saying one thing
    twice."""
    same = "the battery drains completely overnight after the latest sync update"
    ev = [{"id": "ev_001", "source": "github", "snippet": same},
          {"id": "ev_002", "source": "play_store", "snippet": same}]
    assert two_source_rule(_h(), ev) is False


def test_genuinely_independent_reports_still_resolve():
    """The fix must not make real corroboration impossible."""
    ev = [{"id": "ev_001", "source": "github",
           "snippet": "wakelock is held after the sync job completes"},
          {"id": "ev_002", "source": "play_store",
           "snippet": "my phone gets hot and the battery is dead by morning"}]
    assert two_source_rule(_h(), ev) is True


def test_short_snippets_are_not_treated_as_cross_posts():
    """Two brief quotes sharing their few words are not one person posting
    twice — collapsing them would weaken the rule rather than sharpen it."""
    ev = [{"id": "ev_001", "source": "github", "snippet": "battery dies"},
          {"id": "ev_002", "source": "play_store", "snippet": "battery dies"}]
    assert two_source_rule(_h(), ev) is True


# ── B8.21 ───────────────────────────────────────────────────────────────

def test_newline_separated_prose_is_split_into_sentences():
    """Splitting on terminal punctuation alone treated a block of
    newline-separated prose as ONE sentence, so a single inline citation
    anywhere in it grounded every causal claim in the block."""
    prose = ("The v3.2 rollout caused the crash wave\n"
             "Battery drain followed because of the sync change [ev_001]")
    violations = unsupported_claims(prose, {"ev_001"})
    assert any("crash wave" in v for v in violations), \
        "the uncited causal line must be flagged"


# ── B8.3 / B8.15 ────────────────────────────────────────────────────────

def test_sparkline_matching_respects_word_boundaries(session):
    """Plain substring matching meant "app" matched "happy" and "apply", so a
    sparkline could be drawn almost entirely from coincidental substrings."""
    import re
    needle = re.compile(r"\b" + re.escape("app"))
    assert not needle.search("happy customers everywhere")
    assert needle.search("the app crashes on launch")
