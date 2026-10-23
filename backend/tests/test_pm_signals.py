"""PM signals: requests from users, intent labels, incident grouping, editable
themes, and the daily-cap override."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from echolens.db.models import (
    AnomalyEvent, Base, Investigation, LLMCall, Product, QueuedInvestigation, Review,
    TriageDecision)
from echolens.intent import (
    BUG, FEATURE_REQUEST, OTHER, PRAISE, UX_CONFUSION, classify, count_intents,
    primary_intent)

NOW = datetime(2026, 7, 20, tzinfo=timezone.utc)


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _product(s, name="Notely"):
    p = Product(name=name)
    s.add(p)
    s.flush()
    return p


def _review(s, i, text, rating, product="Notely", days_ago=1):
    s.add(Review(source="play_store", ext_id=f"r{product}{i}", rating=rating, text=text,
                 product=product, created_at=NOW - timedelta(days=days_ago)))


# ── item 6: intent labels ───────────────────────────────────────────────

@pytest.mark.parametrize("text,rating,expected", [
    ("App crashes every time I open a note", 1, BUG),
    ("Sync doesn't work since the update", 2, BUG),
    ("Great app but it crashes on export", 5, BUG),
    ("Love it, but I wish it had dark mode", 4, FEATURE_REQUEST),
    ("Please add an export to PDF", 3, FEATURE_REQUEST),
    ("Can you add tags? Would be great", 5, FEATURE_REQUEST),
    ("Really confusing, I can't find the settings", 3, UX_CONFUSION),
    ("How do I share a notebook?", 4, UX_CONFUSION),
    ("Love this app, works perfectly", 5, PRAISE),
    ("It is fine I guess", 3, OTHER),
])
def test_intent_classification(text, rating, expected):
    assert classify(text, rating) == expected


def test_missing_in_a_one_star_review_is_data_loss_not_a_request():
    assert classify("All my notes are missing", 1) == BUG
    assert classify("Missing a widget for the home screen", 4) == FEATURE_REQUEST


def test_counts_always_carry_every_intent_and_primary_breaks_ties():
    counts = count_intents([("crashes", 1), ("please add tags", 4)])
    assert set(counts) == {BUG, FEATURE_REQUEST, UX_CONFUSION, PRAISE, OTHER}
    assert primary_intent(counts) == BUG          # tie -> earlier in INTENTS
    assert primary_intent(count_intents([])) is None


# ── item 5: requests from users (3-5 star) ──────────────────────────────

def _request_corpus(s):
    _product(s)
    texts = [
        ("Love it, but I wish it had dark mode", 4),
        ("Please add dark mode, my eyes hurt at night", 5),
        ("Would love a dark mode option", 4),
        ("Great app. Can you add export to pdf?", 5),
        ("It would be great if you could add export to pdf", 3),
        ("Works perfectly, thank you", 5),            # praise: not a request
        ("Crashes when I open it, please add a fix", 1),  # 1-star: never here
    ]
    for i, (t, r) in enumerate(texts):
        _review(s, i, t, r, days_ago=i % 5)
    s.commit()


def test_requests_group_by_what_is_asked_for():
    from echolens.themes.requests import discover_requests
    s = _session()
    _request_corpus(s)
    out = discover_requests(s, "Notely", as_of=NOW)
    by_phrase = {r["phrase"]: r for r in out["requests"]}
    assert set(by_phrase) == {"dark mode", "export pdf"}
    dark = by_phrase["dark mode"]
    assert dark["count"] == 3
    assert dark["statement"] == "Users ask for dark mode"
    assert dark["intents"][FEATURE_REQUEST] == 3
    assert len(dark["verbatims"]) == 3
    assert all("Crashes" not in v for r in out["requests"] for v in r["verbatims"])


def test_request_labelling_llm_is_optional_and_guarded():
    from echolens.themes.requests import discover_requests

    class LLM:
        def complete_json(self, *a, **k):
            class R:
                parsed = {"clusters": [
                    {"index": 0, "statement": "Notely", "slug": "x", "label_confidence": 0.9},
                    {"index": 1, "statement": "Export notes as a PDF document",
                     "slug": "pdf", "label_confidence": 0.9}]}
            return R()

    s = _session()
    _request_corpus(s)
    out = discover_requests(s, "Notely", as_of=NOW, llm=LLM())
    stmts = [r["statement"] for r in out["requests"]]
    assert "Users ask for dark mode" in stmts            # product-name label refused
    assert "Export notes as a PDF document" in stmts


# ── item 7: incident grouping ───────────────────────────────────────────

def _signal(s, pid, slug, typ, z, start_days=7, end_days=0, metric="m"):
    a = AnomalyEvent(slug=f"p{pid}-{slug}", type=typ, metric=metric, delta=0.5, z=z,
                     window="7d", description=f"{typ} desc", status="pending",
                     product_id=pid, window_start=NOW - timedelta(days=start_days),
                     window_end=NOW - timedelta(days=end_days))
    s.add(a)
    s.flush()
    return a


def test_overlapping_product_wide_and_same_theme_signals_group():
    from echolens.cases import signal_rows
    from echolens.detector.incidents import incident_view
    s = _session()
    p = _product(s)
    _review(s, 1, "sync fails every time", 1)
    _signal(s, p.id, "auto-neg-review-spike", "negative_review_spike", 3.5)
    _signal(s, p.id, "auto-rating-drop", "rating_drop", 2.1)
    _signal(s, p.id, "auto-theme-sync", "theme_volume_surge", 2.5)
    _signal(s, p.id, "auto-issues-sync", "issue_velocity_surge", 1.2)
    _signal(s, p.id, "auto-theme-battery", "theme_volume_surge", 2.0)
    # same type, but a window weeks earlier -> not the same incident
    _signal(s, p.id, "old-rating", "rating_drop", 4.0, start_days=60, end_days=50)
    s.commit()
    signals, incidents = incident_view(s, "Notely", signal_rows(s, p.id))
    assert len(signals) == 6                              # members never disappear
    groups = {i["lead"]: set(i["members"]) for i in incidents}
    assert groups == {
        f"p{p.id}-auto-neg-review-spike": {f"p{p.id}-auto-neg-review-spike",
                                           f"p{p.id}-auto-rating-drop"},
        f"p{p.id}-auto-theme-sync": {f"p{p.id}-auto-theme-sync",
                                     f"p{p.id}-auto-issues-sync"},
    }
    sync = next(sg for sg in signals if sg["slug"].endswith("auto-theme-sync"))
    assert sync["intents"][BUG] == 1
    issues = next(sg for sg in signals if sg["slug"].endswith("auto-issues-sync"))
    assert issues["intents"] is None                      # no reviews behind it


def test_committing_an_incident_investigates_the_lead_and_notes_the_rest():
    from echolens.detector.incidents import RELATED_MARKER, commit_incident, preserve_note
    s = _session()
    p = _product(s)
    lead = _signal(s, p.id, "auto-neg-review-spike", "negative_review_spike", 3.5)
    other = _signal(s, p.id, "auto-rating-drop", "rating_drop", 2.1)
    s.commit()
    folded = commit_incident(s, lead.slug, p.id, "Notely")
    assert folded == [other.slug]
    assert RELATED_MARKER in lead.description
    assert "Average rating is falling" in lead.description
    td = s.scalars(select(TriageDecision).where(TriageDecision.anomaly_id == other.id)).one()
    assert td.decision == "merge" and td.merge_into_anomaly_id == lead.id
    assert other.status == "merged"
    # the anomaly row itself is intact
    assert s.get(AnomalyEvent, other.id).merged_into_id is None
    # a re-scan rewriting the description keeps the note
    assert RELATED_MARKER in preserve_note(lead.description, "1-star reviews +80%")
    # a slug that leads nothing is a no-op
    assert commit_incident(s, other.slug, p.id, "Notely") == []


# ── item 8: editable themes ─────────────────────────────────────────────

def test_rename_merge_mute_apply_after_display():
    from echolens.themes.overrides import apply_overrides, get_overrides, set_override
    s = _session()
    p = _product(s)
    themes = [
        {"slug": "theme-p1-sync-fails", "statement": "Sync fails", "count": 4,
         "verbatims": ["a"], "intents": {"bug": 4}},
        {"slug": "theme-p1-sync-silent", "statement": "Sync silent", "count": 2,
         "verbatims": ["b"], "intents": {"bug": 2}},
        {"slug": "theme-p1-battery", "statement": "Battery drain", "count": 3,
         "verbatims": ["c"], "intents": {"bug": 3}},
    ]
    set_override(s, p.id, "theme-p1-sync-fails", "rename", label="Dropbox sync breaks")
    set_override(s, p.id, "theme-p1-sync-silent", "merge", into="theme-p1-sync-fails")
    set_override(s, p.id, "theme-p1-battery", "mute")
    out = apply_overrides(themes, get_overrides(s, p.id))
    assert [t["slug"] for t in out] == ["theme-p1-sync-fails"]
    assert out[0]["statement"] == "Dropbox sync breaks"
    assert out[0]["count"] == 6 and out[0]["verbatims"] == ["a", "b"]
    assert out[0]["intents"]["bug"] == 6
    with pytest.raises(ValueError):
        set_override(s, p.id, "theme-p1-sync-fails", "merge", into="theme-p1-sync-silent")
    set_override(s, p.id, "theme-p1-battery", "unmute")
    assert len(apply_overrides(themes, get_overrides(s, p.id))) == 2


def test_muted_theme_stops_new_detector_signals_only_for_its_terms():
    from echolens.themes.overrides import is_muted_slug, slug_words
    muted = [slug_words("theme-p1-dropbox-sync-silent")]
    assert is_muted_slug("auto-theme-sync", muted)
    assert is_muted_slug("p1-auto-issues-dropbox", muted)
    assert not is_muted_slug("auto-theme-sync-speed", muted)
    assert not is_muted_slug("auto-theme-battery", muted)


def test_scan_skips_muted_theme_but_keeps_product_wide(monkeypatch):
    from echolens.detector import detect
    from echolens.themes.overrides import set_override
    s = _session()
    p = _product(s)
    set_override(s, p.id, "theme-p1-sync-fails", "mute")
    mk = lambda slug, typ: detect.Candidate(slug=slug, type=typ, metric="m", delta=1.0,
                                           z=3.5, window="7d", description="d",
                                           severity="SEV1")
    monkeypatch.setattr(detect, "detect_volume_spike",
                        lambda *a, **k: mk("auto-neg-review-spike", "negative_review_spike"))
    monkeypatch.setattr(detect, "detect_rating_drop", lambda *a, **k: None)
    monkeypatch.setattr(detect, "detect_theme_surges",
                        lambda *a, **k: [mk("auto-theme-sync", "theme_volume_surge"),
                                         mk("auto-theme-battery", "theme_volume_surge")])
    monkeypatch.setattr(detect, "detect_issue_velocity", lambda *a, **k: [])
    events = detect.scan(s, as_of=NOW, product="Notely", product_id=p.id)
    assert sorted(e.slug for e in events) == [f"p{p.id}-auto-neg-review-spike",
                                              f"p{p.id}-auto-theme-battery"]


# ── item 9: daily cap transparency + override ───────────────────────────

def test_deferred_items_say_why_and_carry_an_estimate():
    from echolens.config import BUDGET_TIERS
    from echolens.orchestrator.queue import estimate_cost, queue_view
    s = _session()
    p = _product(s)
    for i in range(3):
        a = _signal(s, p.id, f"x{i}", "manual_theme", 0.0)
        s.add(QueuedInvestigation(product_id=p.id, anomaly_id=a.id, status="queued",
                                  source="manual_theme", priority=60, selection_order=i,
                                  budget_tier="quick", title=f"t{i}"))
    s.commit()
    view = queue_view(s, p.id, daily_limit=1, as_of=NOW)
    deferred = [i for i in view["queued"] if i["status"] == "deferred"]
    assert len(deferred) == 2
    assert deferred[0]["note"] == "Deferred: daily limit 1 reached; runs tomorrow"
    est = deferred[0]["estimate"]
    assert est["is_estimate"] and est["basis"] == "tier_cap"
    assert est["usd"] == BUDGET_TIERS["quick"].max_cost_usd
    # with enough real cases at the tier, the median of their actual cost wins
    for cost in (0.02, 0.04, 0.10):
        inv = Investigation(anomaly_id=None, status="resolved", opened_by="anomaly",
                            budget_tier="quick", budget_json={}, product_id=p.id)
        s.add(inv)
        s.flush()
        s.add(LLMCall(investigation_id=inv.id, agent="a", model="m", tokens_in=1,
                      tokens_out=1, cost=cost, ms=1))
    s.flush()
    est = estimate_cost(s, "quick", p.id)
    assert est["basis"] == "median" and est["usd"] == 0.04 and est["samples"] == 3


@pytest.fixture()
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as s:
        p = _product(s)
        _request_corpus_rows(s)
        for i in range(2):
            a = _signal(s, p.id, f"q{i}", "manual_theme", 0.0)
            s.add(QueuedInvestigation(product_id=p.id, anomaly_id=a.id, status="queued",
                                      source="manual_theme", priority=60, selection_order=i,
                                      budget_tier="quick", title=f"queued {i}"))
        _signal(s, p.id, "auto-neg-review-spike", "negative_review_spike", 3.5)
        _signal(s, p.id, "auto-rating-drop", "rating_drop", 2.1)
        s.commit()
        pid = p.id

    import echolens.api.app as app_module
    import echolens.db.session as dbs
    monkeypatch.setattr(dbs, "_engine", engine, raising=False)
    monkeypatch.setattr(dbs, "_SessionLocal", Session, raising=False)
    monkeypatch.setattr(app_module, "_daily_limit", lambda session, product_id=None: 0)
    ran = []
    monkeypatch.setattr(app_module, "_run_claimed_bg", lambda *a: ran.append(a))
    monkeypatch.setattr(app_module, "_drain_queue_bg", lambda *a: None)
    c = TestClient(app_module.app)
    c.pid, c.ran, c.Session, c.app = pid, ran, Session, app_module.app
    return c


def _request_corpus_rows(s):
    for i, (t, r) in enumerate([("I wish it had dark mode", 4),
                                ("Please add dark mode", 5),
                                ("Crashes on start", 1)]):
        _review(s, i, t, r, days_ago=i)


def test_cases_view_exposes_deferred_incidents_and_intents(client):
    v = client.get(f"/cases?product_id={client.pid}").json()
    queued = [c for c in v["cases"] if c["queue_id"] is not None]
    assert queued and all(c["deferred"] for c in queued)
    assert queued[0]["why"] == "Deferred: daily limit 0 reached; runs tomorrow"
    assert queued[0]["estimate"]["is_estimate"] is True
    assert len(v["incidents"]) == 1 and len(v["incidents"][0]["members"]) == 2
    assert v["intents"]["counts"][FEATURE_REQUEST] == 2
    assert v["intents"]["counts"][BUG] == 1
    assert client.get(f"/intents?product_id={client.pid}").json()["total"] == 3


def test_run_now_bypasses_the_cap_for_one_row_and_records_it(client):
    qid = client.get(f"/cases?product_id={client.pid}").json()["cases"][0]["queue_id"]
    r = client.post(f"/queue/{qid}/run-now?product_id={client.pid}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["estimate"]["is_estimate"] and body["investigation_id"]
    assert client.ran and client.ran[0][0] == qid
    with client.Session() as s:
        row = s.get(QueuedInvestigation, qid)
        assert row.status == "running" and row.override_by == "dev@localhost"
        assert row.override_at is not None and row.override_estimate_usd is not None
        # the other row is still waiting for tomorrow
        others = s.scalars(select(QueuedInvestigation).where(
            QueuedInvestigation.id != qid)).all()
        assert all(o.status == "queued" for o in others)
    assert client.post(f"/queue/{qid}/run-now?product_id={client.pid}").status_code == 409


def test_overrides_and_run_now_require_reviewer(client):
    from echolens.auth import current_user
    client.app.dependency_overrides[current_user] = lambda: {
        "id": 9, "email": "v@x", "role": "viewer"}
    try:
        assert client.post("/themes/overrides", json={
            "slug": "theme-p1-x", "action": "mute",
            "product_id": client.pid}).status_code == 403
        assert client.post(f"/queue/1/run-now?product_id={client.pid}").status_code == 403
        assert client.get(f"/themes/overrides?product_id={client.pid}").status_code == 200
    finally:
        client.app.dependency_overrides.clear()


def test_feed_returns_requests_and_honours_overrides(client):
    feed = client.get(f"/feed/candidates?product_id={client.pid}").json()
    slugs = [r["slug"] for r in feed["requests"]]
    assert slugs == [f"request-p{client.pid}-dark-mode"]
    slug = slugs[0]
    r = client.post("/themes/overrides", json={"slug": slug, "action": "rename",
                                                "label": "Dark theme", "product_id": client.pid})
    assert r.status_code == 200
    feed = client.get(f"/feed/candidates?product_id={client.pid}").json()
    assert feed["requests"][0]["statement"] == "Dark theme"
    client.post("/themes/overrides", json={"slug": slug, "action": "mute",
                                           "product_id": client.pid})
    feed = client.get(f"/feed/candidates?product_id={client.pid}").json()
    assert feed["requests"] == [] and feed["muted"] == 1
    bad = client.post("/themes/overrides", json={"slug": slug, "action": "explode",
                                                 "product_id": client.pid})
    assert bad.status_code == 422


def test_queueing_an_incident_lead_folds_the_members(client):
    v = client.get(f"/cases?product_id={client.pid}").json()
    inc = v["incidents"][0]
    r = client.post("/queue/themes", json={"slugs": [inc["lead"]],
                                           "statements": {inc["lead"]: inc["title"]},
                                           "product_id": client.pid})
    assert r.status_code == 200
    assert r.json()["queued"][0]["incident_members"] == inc["members"][1:]
    v = client.get(f"/cases?product_id={client.pid}").json()
    assert v["incidents"] == []
    folded = [sg for sg in v["signals"] if sg["slug"] in inc["members"][1:]]
    assert folded and all(sg["dismissed"] for sg in folded)
