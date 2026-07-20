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


def _best_overlap(pats: list[dict], cand: set[str], min_verified: int) -> dict | None:
    best, best_key = None, (0, 0)
    for p in pats:
        if p["verified_count"] < min_verified:
            continue
        overlap = len(set(p["terms"]) & cand)
        if overlap:
            key = (p["verified_count"], overlap)
            if key > best_key:
                best, best_key = p, key
    return best


def matching_pattern(session: Session, anomaly: AnomalyEvent, min_verified: int = 1) -> dict | None:
    """The best validated pattern to use as a prior for this anomaly.

    v9.0 — knowledge compounds ACROSS products. Own-product patterns still win
    outright: a fix proven on this very app is stronger evidence than the same
    fix proven elsewhere. Only when this product has nothing do we look at the
    rest of the portfolio, matched on the shared theme vocabulary rather than raw
    strings (see vocab.canonical_theme). A borrowed pattern is always tagged with
    where it came from — it is a place to look first, never a conclusion.
    """
    cand = set(theme_terms(anomaly, {"summary": anomaly.description or "", "prose": ""}))
    if not cand:
        return None
    pid = getattr(anomaly, "product_id", None)

    own = _best_overlap(patterns(session, pid), cand, min_verified)
    if own is not None:
        return {**own, "cross_product": False, "from_product": None}

    return cross_product_pattern(session, anomaly, min_verified)


def cross_product_pattern(session: Session, anomaly: AnomalyEvent,
                          min_verified: int = 1) -> dict | None:
    """A pattern verified on a DIFFERENT product whose canonical theme matches."""
    from echolens.db.models import Product
    from echolens.vocab import canonical_theme

    pid = getattr(anomaly, "product_id", None)
    theme = canonical_theme(theme_terms(anomaly, {"summary": anomaly.description or "",
                                                  "prose": ""}))
    if theme["id"] == "other":
        return None

    best, best_key = None, (0, 0)
    for other in session.scalars(select(Product)).all():
        if pid is not None and other.id == pid:
            continue
        for p in patterns(session, other.id):
            if p["verified_count"] < min_verified:
                continue
            # match on the SHARED axis, so "battery drain" and "draining fast"
            # count as the same complaint across two apps
            if canonical_theme(p["terms"])["id"] != theme["id"]:
                continue
            key = (p["verified_count"], len(set(p["terms"]) & set(theme["terms"])))
            if key > best_key:
                best, best_key = {**p, "cross_product": True,
                                  "from_product": other.name,
                                  "theme_id": theme["id"],
                                  "theme_label": theme["label"]}, key
    return best
