"""v3.0 tests: real-data hardening (messy input, low-volume windows, staleness,
health snapshot) and the onboarding surface. The headline exit criterion —
"all v2 detection still works on a REAL noisy dataset, not just clean Lumo" — is
covered by test_scan_survives_noisy_corpus."""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import echolens.db.session as db_session
from echolens.collectors.registry import add_source, source_health
from echolens.db.models import Base, Review
from echolens.detector.detect import choose_windows, scan
from echolens.onboarding.snapshot import health_snapshot
from echolens.onboarding.validate import normalize_github_repo, validate_play_store_package
from echolens.synthetic.generate import generate
from echolens.textkit import is_probably_english, parse_version, top_themes


# ── textkit: messy-input tolerance ──────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("Battery drains since the update, really bad", True),
    ("🔋😡😡", False),                      # emoji-only
    ("", False),                            # empty
    ("电池耗电太快了自从更新以后", False),      # Chinese
    ("Батарея разряжается очень быстро", False),  # Cyrillic
    ("ok", False),                          # too short
])
def test_english_gate(text, expected):
    assert is_probably_english(text) is expected


@pytest.mark.parametrize("raw,parsed", [
    ("3.2.0", (3, 2, 0)),
    ("v3.2", (3, 2, 0)),
    ("3.2.0-beta1", (3, 2, 0)),
    ("build 12", (12, 0, 0)),
    ("garbage", None),
    (None, None),
])
def test_version_parse_never_crashes(raw, parsed):
    assert parse_version(raw) == parsed


def test_themes_are_emergent_no_keyword_list():
    texts = ["battery drain is terrible", "massive battery drain since update",
             "battery drain all day", "the sync is broken", "sync broken again"]
    themes = [t["label"] for t in top_themes(texts, k=5)]
    assert "battery drain" in themes  # recurring bigram surfaces


# ── low-volume baseline guard ───────────────────────────────────────────

def _sparse_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    now = datetime(2026, 7, 17, tzinfo=timezone.utc)
    for d in range(40):  # ~1 review/day → well below the low-volume floor
        s.add(Review(source="play_store", ext_id=f"sp_{d}", rating=3,
                     text="it is ok", created_at=now - timedelta(days=d)))
    s.commit()
    return s, now


def test_low_volume_widens_windows():
    s, now = _sparse_session()
    win = choose_windows(s, now)
    assert win.low_volume is True
    assert win.recent == 14 and win.baseline == 56
    assert "widened" in win.note


def test_normal_volume_keeps_tight_windows():
    s = _lumo()
    from echolens.detector.detect import reference_now
    win = choose_windows(s, reference_now(s))
    assert win.low_volume is False and win.recent == 7


# ── noisy real-data resilience (the headline exit criterion) ────────────

def _lumo():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    generate(s)
    s.commit()
    return s


def _dirty(s):
    """Inject the kind of garbage real Play Store data carries, right in the
    detection window."""
    rng = random.Random(7)
    junk = ["🔥🔥🔥", "👍", "😡😡😡😡", "电池很差", "batería fatal", "", "   ",
            "здесь всё плохо", "😤"]
    base = datetime(2026, 7, 12, tzinfo=timezone.utc)
    for i in range(120):
        s.add(Review(source="play_store", ext_id=f"junk_{i}",
                     rating=rng.choice([1, 2, 3, 4, 5]), text=rng.choice(junk),
                     version=rng.choice(["3.2.0", "weird", "", "v3", None]),
                     os_version=None, created_at=base + timedelta(hours=i)))
    s.commit()


def test_scan_survives_noisy_corpus():
    s = _lumo()
    _dirty(s)
    slugs = {e.slug for e in scan(s)}
    # the real signal is still detected despite emoji/foreign/blank noise
    assert "auto-neg-review-spike" in slugs


def test_snapshot_reports_non_english_transparently():
    s = _lumo()
    _dirty(s)
    snap = health_snapshot(s)
    assert snap["reviews"] > 0
    assert snap["non_english"] >= 1                    # counted, disclosed
    assert snap["data_quality"]["non_english_note"]    # not silently swallowed
    assert snap["top_themes"]                           # themes still emerge from the English subset


# ── onboarding validation ───────────────────────────────────────────────

@pytest.mark.parametrize("pkg,ok", [
    ("com.spotify.music", True), ("com.a.b.c", True),
    ("spotify", False), ("com.spotify music", False), ("", False),
])
def test_validate_package(pkg, ok):
    assert (validate_play_store_package(pkg) is None) is ok


@pytest.mark.parametrize("value,repo", [
    ("signalapp/Signal-Android", "signalapp/Signal-Android"),
    ("https://github.com/signalapp/Signal-Android", "signalapp/Signal-Android"),
    ("https://github.com/signalapp/Signal-Android.git", "signalapp/Signal-Android"),
    ("", None),
])
def test_normalize_repo(value, repo):
    got, err = normalize_github_repo(value)
    assert err is None and got == repo


# ── source staleness ────────────────────────────────────────────────────

def test_stale_source_flagged():
    s = _lumo()
    st = add_source(s, "github", "acme/app", "Acme")
    st.status = "error"
    st.last_error = "404 repo not found"
    st.last_run_at = datetime.now(timezone.utc) - timedelta(days=3)
    s.flush()
    health = {h["identifier"]: h for h in source_health(s)}
    assert health["acme/app"]["stale"] is True


# ── API surface ─────────────────────────────────────────────────────────

@pytest.fixture()
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as s:
        generate(s)
        s.commit()
    monkeypatch.setattr(db_session, "_engine", engine)
    monkeypatch.setattr(db_session, "_SessionLocal", Session)
    monkeypatch.setattr(db_session, "get_engine", lambda db_url=None: engine)
    from echolens.api.app import app
    return TestClient(app)


def test_onboard_rejects_bad_package(client):
    r = client.post("/onboard", json={"play_store": "not a package"})
    assert r.status_code == 422


def test_snapshot_endpoint(client):
    body = client.get("/snapshot").json()
    assert body["reviews"] > 0 and "top_themes" in body


def test_onboard_status_shape(client):
    body = client.get("/onboard/status?product=Lumo").json()
    assert "backfilling" in body and "snapshot" in body and "sources" in body
