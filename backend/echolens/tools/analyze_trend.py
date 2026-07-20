"""analyze_trend (v2.0): statistical decomposition of a term's daily signal.

Deterministic changepoint detection (a mean-shift / CUSUM-style scan — no heavy
deps), plus baseline, peak, and how sharp the shift is. Gives the investigator
quantitative ammunition beyond a single z-score: "battery mentions changed on
2026-07-11 — an 8.4x jump over baseline."
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import Review
from echolens.tools._util import match_score, parse_date, terms_of


def analyze_trend(
    session: Session,
    term: str,
    date_from: str | None = None,
    date_to: str | None = None,
    negatives_only: bool = True,
    product: str | None = None,
) -> dict:
    stmt = select(Review)
    if product:
        stmt = stmt.where(Review.product == product)
    if date_from:
        stmt = stmt.where(Review.created_at >= parse_date(date_from))
    if date_to:
        stmt = stmt.where(Review.created_at <= parse_date(date_to))
    rows = session.scalars(stmt).all()

    terms = terms_of(term)
    daily: dict = defaultdict(int)
    if rows:
        start = min(r.created_at.date() for r in rows)
        end = max(r.created_at.date() for r in rows)
        d = start
        while d <= end:
            daily[d] = 0
            d += timedelta(days=1)
    for r in rows:
        if negatives_only and r.rating > 2:
            continue
        if match_score(r.text, terms) > 0:
            daily[r.created_at.date()] += 1

    days = sorted(daily)
    series = [daily[d] for d in days]
    if len(series) < 4:
        return {"term": term, "days": len(series), "changepoint": None,
                "note": "not enough data for a trend"}

    # Changepoint: the split that maximizes the difference of means on either side.
    best_i, best_gap, best_before, best_after = None, -1.0, 0.0, 0.0
    for i in range(2, len(series) - 1):
        before = statistics.mean(series[:i])
        after = statistics.mean(series[i:])
        gap = after - before
        if gap > best_gap:
            best_i, best_gap, best_before, best_after = i, gap, before, after

    baseline = statistics.mean(series[: best_i]) if best_i else statistics.mean(series)
    peak = max(series)
    peak_day = days[series.index(peak)]
    multiplier = round(best_after / best_before, 1) if best_before > 0 else None

    return {
        "term": term,
        "days": len(series),
        "baseline_per_day": round(baseline, 2),
        "peak_per_day": peak,
        "peak_day": peak_day.isoformat(),
        "changepoint": {
            "date": days[best_i].isoformat() if best_i else None,
            "before_mean": round(best_before, 2),
            "after_mean": round(best_after, 2),
            "multiplier": multiplier,  # e.g. 8.4 → "8.4x jump at the changepoint"
        },
        "recent_tail": [{"date": d.isoformat(), "count": daily[d]} for d in days[-10:]],
    }
