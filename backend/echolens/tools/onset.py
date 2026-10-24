"""Simultaneous onset: did a complaint start on the same day on every version?

The version-spread refutation reads "complaints are spread evenly across
versions" as evidence AGAINST a cause. For a client bug that is right. For a
server or back-end outage it is exactly backwards: an outage hits every
installed version at once, so an even spread is its signature, not a
contradiction. This tells the two apart. Deterministic counting, no LLM; used
by the investigator's refutation step, not offered to the planner.

Precisely:
- Onset date D: analyze_trend's changepoint for the term (negatives only),
  rising, with a >= 3x jump (or from a baseline of zero).
- Active versions: major.minor cohorts with any review in [D-7d, D+1d].
- A version has a sudden onset when its matching negatives in the 48 h
  [D, D+1d] run at >= 3x its daily rate over the 7 days before D (a zero
  baseline is floored at one review a week, so a single mention cannot clear
  it on an otherwise silent version), with at least one mention in the 48 h.
- Simultaneous: >= 2 active versions, and >= 80% of them show the onset.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import Review
from echolens.tools._util import match_score, terms_of

ONSET_MULTIPLIER = 3.0
ONSET_HOURS = 48
BEFORE_DAYS = 7
SHARE_OF_VERSIONS = 0.8
MIN_ACTIVE_VERSIONS = 2


def _cohort(version: str | None) -> str:
    v = version or "unknown"
    return ".".join(v.split(".")[:2]) if v != "unknown" else v


def simultaneous_onset(session: Session, term: str, product: str | None = None) -> dict:
    from echolens.tools.analyze_trend import analyze_trend

    trend = analyze_trend(session, term=term, negatives_only=True, product=product)
    cp = trend.get("changepoint") or {}
    out = {"simultaneous": False, "date": cp.get("date"), "versions_active": 0,
           "versions_with_onset": 0, "versions": []}
    rising = cp.get("direction") == "rising" and cp.get("date")
    jump = cp.get("multiplier")
    sudden = (jump is not None and jump >= ONSET_MULTIPLIER) or (
        jump is None and (cp.get("before_mean") or 0) == 0 and (cp.get("after_mean") or 0) > 0)
    if not (rising and sudden):
        return out

    onset = date.fromisoformat(cp["date"])
    window_days = ONSET_HOURS // 24
    first, last = onset - timedelta(days=BEFORE_DAYS), onset + timedelta(days=window_days - 1)
    stmt = select(Review)
    if product:
        stmt = stmt.where(Review.product == product)
    terms = terms_of(term)
    per: dict[str, dict] = {}
    for r in session.scalars(stmt).all():
        day = r.created_at.date()
        if not (first <= day <= last):
            continue
        c = per.setdefault(_cohort(r.version), {"before": 0, "after": 0})
        if r.rating > 2 or match_score(r.text, terms) == 0:
            continue
        c["after" if day >= onset else "before"] += 1

    versions = []
    for name, c in sorted(per.items()):
        before_rate = max(c["before"] / BEFORE_DAYS, 1 / BEFORE_DAYS)
        after_rate = c["after"] / window_days
        versions.append({"version": name, "before_per_day": round(c["before"] / BEFORE_DAYS, 2),
                         "after_per_day": round(after_rate, 2),
                         "onset": c["after"] >= 1 and after_rate >= ONSET_MULTIPLIER * before_rate})
    hit = sum(1 for v in versions if v["onset"])
    out.update(versions_active=len(versions), versions_with_onset=hit, versions=versions,
               simultaneous=(len(versions) >= MIN_ACTIVE_VERSIONS
                             and hit / len(versions) >= SHARE_OF_VERSIONS))
    return out
