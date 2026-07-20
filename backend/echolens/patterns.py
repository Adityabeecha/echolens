"""Validated pattern library (v6.0) — earned, not asserted.

A pattern is `(trigger, cause, fix, verified success)` built EXCLUSIVELY from
fixes that were confirmed to work (FixWatch status='confirmed'). The investigator
uses a matching pattern as a starting prior, so a recurring problem shortcuts to
the hypothesis that has already been proven twice.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import AnomalyEvent, Finding, FixWatch, Investigation, Recommendation
from echolens.impact import theme_terms


def patterns(session: Session, product_id: int | None = None) -> list[dict]:
    """Every validated pattern for this product, most-verified first. Grouped by
    theme signature so repeated confirmations accumulate a verified count."""
    stmt = select(FixWatch).where(FixWatch.status == "confirmed")
    if product_id is not None:
        stmt = stmt.where(FixWatch.product_id == product_id)
    groups: dict[tuple, dict] = {}
    for w in session.scalars(stmt).all():
        finding = session.get(Finding, w.finding_id)
        inv = session.get(Investigation, w.investigation_id)
        anomaly = session.get(AnomalyEvent, inv.anomaly_id) if inv else None
        rec = session.scalars(select(Recommendation).where(
            Recommendation.finding_id == w.finding_id).order_by(Recommendation.rank)).first()
        sig = tuple(sorted(w.terms)[:3])
        if not sig:
            continue
        p = groups.setdefault(sig, {
            "terms": list(sig),
            "trigger": (anomaly.type if anomaly else "anomaly"),
            "cause": (finding.summary if finding else ""),
            "fix": (rec.action if rec else ""),
            "verified_count": 0,
            "cases": [],
        })
        p["verified_count"] += 1
        p["cases"].append(w.investigation_id)
    return sorted(groups.values(), key=lambda p: -p["verified_count"])


def matching_pattern(session: Session, anomaly: AnomalyEvent, min_verified: int = 1) -> dict | None:
    """The best validated pattern whose theme overlaps this anomaly, or None.
    Only patterns from the SAME product count as a prior."""
    cand = set(theme_terms(anomaly, {"summary": anomaly.description or "", "prose": ""}))
    if not cand:
        return None
    best, best_key = None, (0, 0)
    for p in patterns(session, getattr(anomaly, "product_id", None)):
        if p["verified_count"] < min_verified:
            continue
        overlap = len(set(p["terms"]) & cand)
        if overlap:
            key = (p["verified_count"], overlap)
            if key > best_key:
                best, best_key = p, key
    return best
