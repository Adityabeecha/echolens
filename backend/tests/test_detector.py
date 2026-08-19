"""Anomaly detector: deterministic, threshold-driven (PRD §4.1)."""
from __future__ import annotations

from echolens.db.models import AnomalyEvent
from echolens.detector.detect import (
    detect_issue_velocity,
    detect_theme_surges,
    detect_volume_spike,
    scan,
)


def test_volume_spike_detected(session):
    c = detect_volume_spike(session)
    assert c is not None
    assert c.type == "negative_review_spike"
    assert c.z >= 3.0  # SEV1 — a real spike, not noise
    assert c.severity == "SEV1"


def test_theme_surge_flags_battery(session):
    cands = detect_theme_surges(session)
    slugs = {c.slug for c in cands}
    assert "auto-theme-battery-drain" in slugs
    battery = next(c for c in cands if c.slug == "auto-theme-battery-drain")
    assert battery.z >= 2.0


def test_issue_velocity_surge(session):
    cands = detect_issue_velocity(session)
    # The term is derived from Lumo's OWN issue text, so assert the signal, not
    # a hardcoded slug — the detector no longer ships anyone else's keywords.
    assert any(c.type == "issue_velocity_surge" and "battery" in c.metric.lower()
               for c in cands), [c.slug for c in cands]


def test_scan_is_idempotent(session):
    first = {e.slug for e in scan(session)}
    before = session.query(AnomalyEvent).count()
    second = {e.slug for e in scan(session)}  # re-run must not duplicate
    after = session.query(AnomalyEvent).count()
    assert first == second
    assert before == after


def test_detector_is_deterministic(session):
    a = detect_volume_spike(session)
    b = detect_volume_spike(session)
    assert (a.z, a.delta) == (b.z, b.delta)
