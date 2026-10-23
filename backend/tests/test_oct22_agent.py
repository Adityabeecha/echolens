"""Regressions for the 2026-10-22 review: agent guards, tools and LLM client."""
from __future__ import annotations

from datetime import datetime, timezone

from echolens.db.models import Release
from echolens.investigator.guards import (
    CAUSAL_MARKERS, resolvable_hypothesis, unsupported_claims)
from echolens.tools.get_release_notes import get_release_notes


def test_blame_and_breakage_phrasing_needs_a_citation():
    for claim in ["v3.2 is the culprit.", "The update broke sync.",
                  "This is a direct consequence of v3.2.", "v3.2 is to blame.",
                  "v3.2 introduced a regression.", "Sync regressed in 3.2.",
                  "The wakelock kills the battery."]:
        assert unsupported_claims(claim, set()), claim
        assert not unsupported_claims(claim.rstrip(".") + " [ev_001].", {"ev_001"}), claim


def test_plain_description_is_not_a_causal_claim():
    for text in ["Users report battery drain.", "Sync is enabled by default."]:
        assert not CAUSAL_MARKERS.search(text), text


def test_parked_hypothesis_cannot_resolve():
    ev = [{"id": "ev_001", "source": "play_store", "snippet": "battery dies overnight"},
          {"id": "ev_002", "source": "github", "snippet": "wakelock held by sync worker"}]
    h = {"id": "H1", "status": "parked", "confidence": 0.95,
         "evidence_for": ["ev_001", "ev_002"]}
    assert resolvable_hypothesis([h], ev) is None
    assert resolvable_hypothesis([dict(h, status="active")], ev) is not None


def _release(session, version):
    session.add(Release(version=version, notes=f"Lumo v{version}",
                        released_at=datetime(2026, 7, 10, tzinfo=timezone.utc)))
    session.flush()


def test_release_notes_wildcards_and_v_prefix(session):
    _release(session, "9.7.1")
    everything = get_release_notes(session)["total_matching"]
    for v in ["*", "any", "", "%"]:
        assert get_release_notes(session, version=v)["total_matching"] == everything, v
    for v in ["v9.7", "9.7", "V9"]:
        assert get_release_notes(session, version=v)["total_matching"] == 1, v
    assert get_release_notes(session, version="99.0")["total_matching"] == 0


def test_unknown_budget_tier_falls_back_to_standard():
    from echolens.config import BUDGET_TIERS
    from echolens.investigator.state import Budget
    assert Budget.for_tier("Quick").tier is BUDGET_TIERS["quick"]
    assert Budget.for_tier("nonsense").tier is BUDGET_TIERS["standard"]
    assert Budget.for_tier(None).tier is BUDGET_TIERS["standard"]


def test_finding_text_hygiene():
    from echolens.investigator.guards import (
        dedupe_refs, tidy_prose, tidy_summary, unseen_code_spans)
    assert tidy_summary("H1 supported: release v3.2 drains battery.") == "Release v3.2 drains battery."
    assert tidy_summary("Sync drains battery") == "Sync drains battery"
    prose = ("Reviews report drain [ev_001]. "
             "This satisfies the two-source rule with 0.90 confidence [ev_001].")
    assert tidy_prose(prose) == "Reviews report drain [ev_001]."
    assert unseen_code_spans("Disable `auto_photo_sync`.", "background sync") == "Disable auto photo sync."
    assert unseen_code_spans("Disable `auto_photo_sync`.", "flag auto_photo_sync on") == "Disable `auto_photo_sync`."
    assert dedupe_refs(["ev_001", "ev_001", "ev_002"]) == ["ev_001", "ev_002"]


def test_theme_terms_lead_with_the_detected_theme():
    from echolens.impact import theme_terms

    class A:
        description = "'battery drain' complaints: 100% of recent negatives vs 13% baseline (z=2.75)."
        metric = "battery share"
    terms = theme_terms(A(), {"summary": "H1 supported: release v3.2.0 introduced a broadly "
                                          "reported battery-drain regression.", "prose": ""})
    assert terms[:2] == ["battery", "drain"]
    assert not {"supported", "introduced", "broadly", "reported"} & set(terms)


def test_string_supports_keep_the_link():
    from echolens.investigator.graph import _as_ids
    assert _as_ids("H1") == ["H1"]
    assert _as_ids("H1, H3") == ["H1", "H3"]
    assert _as_ids(["H2"]) == ["H2"]
    assert _as_ids(None) == []


def test_ask_ranking_answers_from_signals_without_a_model(session):
    from echolens.chat import route
    from echolens.detector.detect import scan
    scan(session)
    out = route(session, "What's our biggest unresolved complaint?")
    assert out["type"] == "answer"
    assert out.get("grounded") is True
    assert "strongest signal" in out["text"]
    assert "investigated yet" in out["text"]
