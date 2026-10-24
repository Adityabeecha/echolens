"""Evidence rules: what may count as evidence, and how strongly it may count.

One block per rule. Every LLM step is a ScriptedLLM and the one network call
(GitHub compare) is faked, so these run offline and deterministically.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from echolens.db.models import (AnomalyEvent, Base, CollectorState, Product, Release,
                                Review, TraceStep)
from echolens.eval.harness import ScriptedLLM
from echolens.investigator import guards
from echolens.investigator.graph import Investigator

NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _product(s, name="Tiny", channels=()):
    p = Product(name=name)
    s.add(p)
    s.flush()
    for src in channels:
        s.add(CollectorState(source=src, identifier=f"{name}-{src}", product=name,
                             product_id=p.id, enabled=True, status="healthy"))
    s.flush()
    return p


def _review(s, product, ext, text, rating, days_ago=0, version="3.2.0", at=None):
    r = Review(ext_id=ext, text=text, rating=rating, version=version, os_version="Android 15",
               created_at=at or (NOW - timedelta(days=days_ago)), product=product)
    s.add(r)
    return r


def _investigator(s, product, llm=None, description="sync drains battery"):
    a = AnomalyEvent(slug=f"t-{product.id}-{description[:10]}", type="theme_volume_surge",
                     metric="'sync battery' complaints", delta=1.0, z=3.0, window="7d",
                     description=description, product_id=product.id)
    s.add(a)
    s.flush()
    return Investigator(s, a, llm=llm or ScriptedLLM([]))


def _hyp(hid="H1", statement="The new background sync drains the battery", conf=0.5, **kw):
    return {"id": hid, "statement": statement, "confidence": conf, "status": "active",
            "evidence_for": [], "evidence_against": [], "next_test": "",
            "boost_if_rejected": [], **kw}


def _state(**kw):
    base = {"trigger": {}, "hypotheses": [], "evidence": [], "proposed": None,
            "budget_stop_reason": None, "status": "running", "status_reason": "",
            "last_tool": None}
    return base | kw


def _traces(s, inv, kind=None):
    rows = s.query(TraceStep).filter_by(investigation_id=inv.inv.id).order_by(TraceStep.seq).all()
    return [r.content_json for r in rows if kind is None or r.kind == kind]


# ── 1. exact short duplicates always merge ─────────────────────────────

def test_identical_short_quotes_from_one_source_merge():
    ev = [{"id": "ev_001", "source": "play_store", "snippet": "It works fine, no complaints"}]
    # Too short for the Jaccard rule (it needs >= 3 tokens) — merged anyway.
    assert Investigator._near_duplicate("it works fine — no complaints!", "play_store", ev) == "ev_001"
    # Another channel saying the same words is corroboration, not a duplicate.
    assert Investigator._near_duplicate("It works fine, no complaints", "github", ev) is None
    # Same words, different quote: not merged by the exact rule.
    assert Investigator._near_duplicate("It works fine", "play_store", ev) is None


def test_long_near_duplicates_still_use_jaccard():
    ev = [{"id": "ev_001", "source": "play_store",
           "snippet": "battery drains fast since the last update badly"}]
    assert Investigator._near_duplicate("battery drains fast since the last update, badly!!",
                                        "play_store", ev) == "ev_001"


# ── 2. a happy review cannot support a problem ─────────────────────────

def test_positive_without_complaint_classification():
    assert guards.positive_without_complaint("Works great, love the new sync", 5)
    assert guards.positive_without_complaint("Nice", 4)
    # A bug report in a good mood still carries a complaint cue.
    assert not guards.positive_without_complaint("Great app but it crashes on export", 5)
    assert not guards.positive_without_complaint("Love it but sync drains my battery", 4)
    assert not guards.positive_without_complaint("Works great", 3)    # not 4–5★


def test_five_star_praise_is_rejected_as_support_and_logged():
    from echolens.tools.search_reviews import search_reviews
    s = _session()
    p = _product(s)
    _review(s, "Tiny", "r-happy", "Works great, love the new sync feature", 5)
    _review(s, "Tiny", "r-angry", "The new sync drains my battery overnight", 1)
    _review(s, "Tiny", "r-happy2", "Love the new sync, it is perfect", 5)
    s.flush()
    llm = ScriptedLLM([{"evidence": [
        {"ref": "r-happy", "snippet": "love the new sync", "supports": ["H1"], "contradicts": []},
        {"ref": "r-angry", "snippet": "sync drains my battery", "supports": ["H1"], "contradicts": []},
        # Cited both ways: it may stand as counter-evidence, never as support.
        {"ref": "r-happy2", "snippet": "Love the new sync", "supports": ["H1"], "contradicts": ["H1"]},
    ], "hypothesis_updates": []}])
    inv = _investigator(s, p, llm)
    result = search_reviews(s, query="sync", product="Tiny")
    st = _state(hypotheses=[_hyp()], last_tool={"name": "search_reviews", "args": {"query": "sync"},
                                                "result": result, "tests_hypothesis": "H1"})
    st = inv._update(st)
    by_ref = {e["ref"]: e for e in st["evidence"]}
    assert "r-happy" not in by_ref
    assert by_ref["r-angry"]["supports"] == ["H1"]
    assert by_ref["r-happy2"]["supports"] == [] and by_ref["r-happy2"]["contradicts"] == ["H1"]
    h1 = st["hypotheses"][0]
    assert by_ref["r-angry"]["id"] in h1["evidence_for"]
    assert by_ref["r-happy2"]["id"] not in h1["evidence_for"]
    fails = [t for t in _traces(s, inv, "FAIL") if "positive review" in t.get("text", "")]
    assert len(fails) == 2
    # The tool's own metadata travels with the evidence.
    assert by_ref["r-angry"]["meta"]["rating"] == 1


# ── 3. single-channel products ─────────────────────────────────────────

def _ev(eid, source, snippet, supports=("H1",), **meta):
    return {"id": eid, "source": source, "ref": f"ref-{eid}", "snippet": snippet,
            "supports": list(supports), "contradicts": [], **({"meta": meta} if meta else {})}


def _three_reviews_and_a_release():
    return [
        _ev("ev_001", "play_store", "Battery dies by noon since the update", date="2026-10-12", version="3.2.0"),
        _ev("ev_002", "play_store", "Background sync keeps my phone awake all night", date="2026-10-13", version="3.2.0"),
        _ev("ev_003", "play_store", "Phone gets hot while the app syncs photos", date="2026-10-14", version="3.2.1"),
        _ev("ev_004", "release_notes", "v3.2.0: background photo sync on by default",
            released_at="2026-10-10"),
    ]


def test_single_channel_bar_a_reviews_plus_a_release():
    ev = _three_reviews_and_a_release()
    h = _hyp(evidence_for=[e["id"] for e in ev])
    basis = guards.single_channel_support(h, ev)
    assert basis and "release" in basis
    # A release long before the complaints is not time-matched.
    ev[3]["meta"]["released_at"] = "2026-08-01"
    assert guards.single_channel_support(h, ev) is None


def test_identical_quotes_count_once_toward_the_single_channel_bar():
    ev = _three_reviews_and_a_release()
    ev[2]["snippet"] = ev[1]["snippet"].upper() + "!!"   # same quote, louder
    h = _hyp(evidence_for=[e["id"] for e in ev])
    assert guards.single_channel_support(h, ev) is None


def test_single_channel_bar_b_five_reviews_over_three_days():
    texts = ["Battery dies by noon", "Phone is hot all night", "Lost half my charge on the bus",
             "Drains 30 percent an hour", "Battery health warning after a week of this"]
    ev = [_ev(f"ev_00{i}", "play_store", t, date=f"2026-10-1{i % 3}") for i, t in enumerate(texts)]
    h = _hyp(evidence_for=[e["id"] for e in ev])
    assert "3 different days" in guards.single_channel_support(h, ev)
    for e in ev:
        e["meta"]["date"] = "2026-10-11"                   # one bad afternoon
    assert guards.single_channel_support(h, ev) is None


def _seed_one_version(s):
    for i in range(4):
        _review(s, "Tiny", f"bg-{i}", "battery battery drains", 1, days_ago=5 + i, version="3.2.0")
    s.flush()


def test_single_channel_case_resolves_labelled_and_capped():
    s = _session()
    p = _product(s, channels=("play_store",))
    _seed_one_version(s)
    ev = _three_reviews_and_a_release()
    llm = ScriptedLLM([{"summary": "Background photo sync drains battery",
                        "prose": "Reviews describe battery drain after v3.2.0 [ev_001] [ev_002], "
                                 "which turned background photo sync on by default [ev_004].",
                        "confidence": 0.9, "supported_hypothesis": "H1",
                        "checked": ["play_store", "release_notes"], "what_would_settle_it": ""}])
    inv = _investigator(s, p, llm)
    assert inv._single_channel is True
    st = _state(hypotheses=[_hyp(conf=0.72, evidence_for=[e["id"] for e in ev])], evidence=ev)
    st = inv._check(st)
    assert st["status"] == "resolved"
    h1 = st["hypotheses"][0]
    assert h1["status"] == guards.SINGLE_CHANNEL_STATUS != "supported"
    assert h1["confidence"] <= guards.SINGLE_CHANNEL_CONFIDENCE_CAP
    assert any(guards.SINGLE_CHANNEL_LABEL in t.get("text", "") for t in _traces(s, inv, "CHECK"))
    finding = inv._draft_finding(st)
    assert finding["support_level"] == "single_channel"
    assert finding["support_label"] == guards.SINGLE_CHANNEL_LABEL
    assert finding["confidence"] <= guards.SINGLE_CHANNEL_CONFIDENCE_CAP   # model said 0.9
    assert "one feedback channel" in finding["single_channel_note"]


def test_multi_channel_products_keep_the_current_rule():
    s = _session()
    p = _product(s, channels=("play_store", "github"))
    _seed_one_version(s)
    ev = _three_reviews_and_a_release()
    inv = _investigator(s, p)
    assert inv._single_channel is False
    st = inv._check(_state(hypotheses=[_hyp(conf=0.72, evidence_for=[e["id"] for e in ev])],
                           evidence=ev))
    assert st["status"] == "running"                 # 0.72 < 0.80: no shortcut
    assert st["hypotheses"][0]["status"] == "active"


def test_on_one_channel_a_release_note_is_not_a_second_source():
    ev = [_ev("ev_001", "play_store", "Battery dies by noon since the update", date="2026-10-12"),
          _ev("ev_002", "release_notes", "v3.2.0: background sync", released_at="2026-10-10")]
    h = _hyp(conf=0.85, evidence_for=["ev_001", "ev_002"])
    assert guards.two_source_rule(h, ev)                                  # unknown / multi
    assert not guards.two_source_rule(h, ev, guards.SINGLE_CHANNEL_NON_FEEDBACK)
    s = _session()
    p = _product(s, channels=("play_store",))
    _seed_one_version(s)
    inv = _investigator(s, p)
    st = inv._check(_state(hypotheses=[h], evidence=ev))
    assert st["status"] == "running"                 # neither bar met


def test_products_without_collectors_are_unchanged():
    s = _session()
    p = _product(s)                                  # e.g. the synthetic demo
    inv = _investigator(s, p)
    assert inv._single_channel is False and inv._ignore_sources == frozenset()


# ── 4. outages hit every version at once ───────────────────────────────

def _outage_corpus(s):
    """Quiet for three weeks on three versions, then login failures on all of
    them within the same 48 hours."""
    start = NOW - timedelta(days=22)
    for d in range(21):
        for v in ("3.0.1", "3.1.0", "3.2.0"):
            _review(s, "Tiny", f"ok-{d}-{v}", "nice app, does the job", 5,
                    at=start + timedelta(days=d), version=v)
    for d in (21, 22):
        for v in ("3.0.1", "3.1.0", "3.2.0"):
            for k in range(3):
                _review(s, "Tiny", f"down-{d}-{v}-{k}",
                        f"Login fails, auth server outage? attempt {k}", 1,
                        at=start + timedelta(days=d, hours=k), version=v)
    s.flush()


def test_simultaneous_onset_is_measured():
    from echolens.tools.onset import simultaneous_onset
    s = _session()
    _product(s)
    _outage_corpus(s)
    res = simultaneous_onset(s, term="login auth", product="Tiny")
    assert res["simultaneous"] is True
    assert res["versions_active"] == 3 and res["versions_with_onset"] == 3


def test_server_side_cause_survives_the_version_spread_refutation():
    s = _session()
    p = _product(s)
    _outage_corpus(s)
    inv = _investigator(s, p, description="login fails auth")
    contradicted = inv._attempt_refutation(_hyp(statement="An auth server outage makes login fail"))
    assert contradicted is False
    refute = _traces(s, inv, "REFUTE")[-1]
    assert "server-side" in refute["text"] and "does NOT" in refute["text"]


def test_a_version_specific_cause_is_still_refuted_by_a_simultaneous_onset():
    s = _session()
    p = _product(s)
    _outage_corpus(s)
    inv = _investigator(s, p, description="login fails auth")
    assert inv._attempt_refutation(_hyp(statement="Release v3.2 broke login auth")) is True
    assert "UNDERCUTS" in _traces(s, inv, "REFUTE")[-1]["text"]


# ── 5. remove only the ungrounded sentences ────────────────────────────

_GROUNDED = "Battery complaints rose sharply after the update [ev_001]."
_UNCITED = "The crash was caused by the v3.2 release."


def test_strip_ungrounded_splits_published_from_working():
    kept, removed, grounded = guards.strip_ungrounded(f"{_GROUNDED} {_UNCITED}", {"ev_001"})
    assert kept == _GROUNDED and removed == [_UNCITED] and grounded
    _, _, grounded = guards.strip_ungrounded(_UNCITED, {"ev_001"})
    assert not grounded


def _finding(prose):
    return {"summary": "Battery drain after the update", "prose": prose, "confidence": 0.7,
            "supported_hypothesis": None, "checked": ["play_store"], "what_would_settle_it": "x"}


def _draft(prose):
    s = _session()
    p = _product(s)
    inv = _investigator(s, p, ScriptedLLM([_finding(prose), _finding(prose)]))
    st = _state(status="needs_human", status_reason="test", hypotheses=[_hyp()],
                evidence=[_ev("ev_001", "play_store", "battery dies")])
    return s, inv, st, inv._draft_finding(st)


def test_a_partly_grounded_draft_publishes_its_grounded_part():
    s, inv, st, f = _draft(f"{_GROUNDED} {_UNCITED}")
    assert f["prose"] == _GROUNDED
    assert f["working_hypotheses"] == [_UNCITED]
    assert f["working_hypothesis_label"] == guards.WORKING_HYPOTHESIS_LABEL
    assert "grounding_violations" not in f and "rejected_draft" not in f
    assert _UNCITED not in f["prose"]
    assert st["status"] == "needs_human"             # not upgraded by the cleanup
    assert any("removed 1 uncited" in t.get("text", "") for t in _traces(s, inv, "CHECK"))


def test_a_draft_with_nothing_grounded_stays_blocked():
    _, _, st, f = _draft(_UNCITED)
    assert f["grounding_violations"] == [_UNCITED]
    assert f["rejected_draft"] == _UNCITED
    assert _UNCITED not in f["prose"]
    assert "working_hypotheses" not in f
    assert st["status"] == "needs_human"


# ── 6. commit / PR context between releases ───────────────────────────

def _compare_payload():
    return {
        "commits": [
            {"sha": "a" * 40, "commit": {"message": "Merge pull request #412 from acme/sync\n\n"
                                                    "Enable background photo sync by default",
                                         "author": {"date": "2026-10-08T10:00:00Z"}}},
            {"sha": "b" * 40, "commit": {"message": "Tune sync interval (#415)\n\nlong body " * 20,
                                         "author": {"date": "2026-10-09T10:00:00Z"}}},
            {"sha": "c" * 40, "commit": {"message": "Fix typo", "author": {}}},
        ],
        "files": [{"filename": f"app/sync/file{i}.kt", "status": "modified", "additions": 3,
                   "deletions": 1, "patch": "@@ -1,3 +1,4 @@\n" + "+line\n" * 200}
                  for i in range(40)],
    }


@pytest.fixture
def repo_session(monkeypatch):
    s = _session()
    p = _product(s, name="Acme", channels=())
    s.add(CollectorState(source="github", identifier="acme/app", product="Acme",
                         product_id=p.id, enabled=True, status="healthy"))
    s.add(Release(version="3.1.0", notes="old", product="Acme",
                  released_at=datetime(2026, 9, 1, tzinfo=timezone.utc)))
    s.add(Release(version="3.2.0", notes="new sync", product="Acme",
                  released_at=datetime(2026, 10, 10, tzinfo=timezone.utc)))
    s.flush()
    calls = []

    def fake(repo, base, head, timeout=10.0):
        calls.append((repo, base, head))
        return _compare_payload()
    import echolens.collectors.github as gh
    monkeypatch.setattr(gh, "fetch_compare", fake)
    return s, calls


def test_release_changes_between_tags_are_capped_and_parsed(repo_session):
    from echolens.tools.registry import run_tool
    s, calls = repo_session
    out = run_tool(s, "get_release_changes", {"version": "v3.2"}, product="Acme")
    assert calls == [("acme/app", "3.1.0", "3.2.0")]
    assert out["available"] and out["base"] == "3.1.0" and out["head"] == "3.2.0"
    first, second, third = out["commits"]
    assert first["ref"] == "commit aaaaaaa"
    assert first["pr"] == 412 and first["pr_title"] == "Enable background photo sync by default"
    assert second["pr"] == 415 and second["pr_title"] == "Tune sync interval"
    assert third["pr"] is None and third["message"] == "Fix typo"
    assert len(out["files"]) == 30 and out["total_files"] == 40 and out["truncated"]
    excerpts = [f for f in out["files"] if "excerpt" in f]
    assert len(excerpts) == 5 and all(len(f["excerpt"]) <= 160 for f in excerpts)
    assert all(len(c["message"]) <= 160 for c in out["commits"])


def test_release_changes_by_date_range(repo_session):
    from echolens.tools.registry import run_tool
    s, calls = repo_session
    run_tool(s, "get_release_changes", {"date_from": "2026-10-01", "date_to": "2026-10-15"},
             product="Acme")
    assert calls == [("acme/app", "3.1.0", "3.2.0")]


def test_release_changes_without_a_repo_say_so_and_never_fetch(monkeypatch):
    import echolens.collectors.github as gh
    from echolens.tools.registry import run_tool
    monkeypatch.setattr(gh, "fetch_compare", lambda *a, **k: pytest.fail("must not fetch"))
    s = _session()
    _product(s, channels=("play_store",))
    out = run_tool(s, "get_release_changes", {"version": "3.2"}, product="Tiny")
    assert out["available"] is False and "No GitHub repository" in out["note"]


def test_release_changes_are_registered_documented_and_citable(repo_session):
    from echolens.investigator.graph import _collect_refs
    from echolens.investigator.prompts import plan_system
    from echolens.tools.registry import TOOLS, run_tool
    assert TOOLS["get_release_changes"].source == "github_commits"
    assert "get_release_changes" in plan_system()
    s, _ = repo_session
    out = run_tool(s, "get_release_changes", {"version": "3.2.0"}, product="Acme")
    assert "commit aaaaaaa" in _collect_refs(out)    # citable as evidence


# ── 7. very small apps ─────────────────────────────────────────────────

def _quiet_baseline(s, product="Tiny"):
    """56 days, one review a day, ratings 4/5: steady, and well under ten a week."""
    for d in range(15, 71):
        _review(s, product, f"base-{d}", "nice app", 5 if d % 2 else 4, days_ago=d)


def _scan(s):
    from echolens.detector.detect import scan
    return scan(s, as_of=NOW, persist=False, product="Tiny")


def test_one_or_two_reviews_do_not_raise_a_z_score_signal():
    s = _session()
    _product(s)
    _quiet_baseline(s)
    _review(s, "Tiny", "low-1", "meh", 1, days_ago=3)
    _review(s, "Tiny", "low-2", "not for me", 1, days_ago=2)
    s.flush()
    from echolens.detector.detect import choose_windows, detect_rating_drop, very_low_volume
    win = choose_windows(s, NOW, "Tiny")
    assert very_low_volume(s, NOW, win, "Tiny")
    drop = detect_rating_drop(s, NOW, win, "Tiny")
    assert drop is not None and drop.support == 2    # the z-score alone would fire
    assert not [e for e in _scan(s) if e.type == "rating_drop"]


def test_three_distinct_reviews_raise_a_labelled_low_volume_watch():
    s = _session()
    _product(s)
    _quiet_baseline(s)
    for i, text in enumerate(["Export fails every time", "export fails with an error",
                              "Export fails since yesterday", "Export fails every time"]):
        _review(s, "Tiny", f"exp-{i}", text, 2, days_ago=i + 1)
    s.flush()
    watches = [e for e in _scan(s) if e.type == "low_volume_watch"]
    assert len(watches) == 1
    w = watches[0]
    assert "export fails" in w.metric and "low-volume watch" in w.metric
    assert w.description.startswith("Low-volume watch: 3 distinct reviews")
    assert "not a measured spike" in w.description


def test_two_distinct_reviews_are_not_enough_for_a_watch():
    s = _session()
    _product(s)
    _quiet_baseline(s)
    for i, text in enumerate(["Export fails every time", "Export fails every time!",
                              "export fails with an error"]):
        _review(s, "Tiny", f"exp-{i}", text, 2, days_ago=i + 1)
    s.flush()
    assert not [e for e in _scan(s) if e.type == "low_volume_watch"]


def test_busy_products_are_untouched_by_the_small_app_rules():
    s = _session()
    _product(s)
    for d in range(1, 71):
        for k in range(4):
            _review(s, "Tiny", f"busy-{d}-{k}", "nice app", 5, days_ago=d)
    s.flush()
    from echolens.detector.detect import choose_windows, very_low_volume
    assert not very_low_volume(s, NOW, choose_windows(s, NOW, "Tiny"), "Tiny")
