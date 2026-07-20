from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import Review
from echolens.tools._util import parse_date, terms_of, match_score


def _daily_series(
    session: Session, metric: str, start: datetime, end: datetime,
    product: str | None = None,
) -> list[float]:
    """metric: 'one_star_volume' | 'avg_rating' | 'term_share:<term>'
    (share of negatives mentioning the term, in %)."""
    stmt = select(Review).where(Review.created_at >= start, Review.created_at <= end)
    if product:
        stmt = stmt.where(Review.product == product)
    rows = session.scalars(stmt).all()
    daily = defaultdict(list)
    for r in rows:
        daily[r.created_at.date()].append(r)

    series: list[float] = []
    for day in sorted(daily):
        rs = daily[day]
        if metric == "one_star_volume":
            series.append(float(sum(1 for r in rs if r.rating == 1)))
        elif metric == "avg_rating":
            series.append(sum(r.rating for r in rs) / len(rs))
        elif metric.startswith("term_share:"):
            terms = terms_of(metric.split(":", 1)[1])
            neg = [r for r in rs if r.rating <= 2]
            hits = sum(1 for r in neg if match_score(r.text, terms) > 0)
            series.append(round(100 * hits / len(neg), 2) if neg else 0.0)
        else:
            raise ValueError(f"unknown metric: {metric}")
    return series


def compare_periods(
    session: Session,
    metric: str,
    before_from: str,
    before_to: str,
    after_from: str,
    after_to: str,
    product: str | None = None,
) -> dict:
    """Deterministic before/after stats: means, delta %, z-score of the
    after-mean against the before-period distribution."""
    before = _daily_series(session, metric, parse_date(before_from), parse_date(before_to), product)
    after = _daily_series(session, metric, parse_date(after_from), parse_date(after_to), product)
    if not before or not after:
        return {"metric": metric, "error": "one of the periods has no data"}

    mean_b = statistics.mean(before)
    mean_a = statistics.mean(after)
    std_b = statistics.stdev(before) if len(before) > 1 else 0.0
    z = round((mean_a - mean_b) / std_b, 2) if std_b > 0 else None
    return {
        "metric": metric,
        "before": {"from": before_from, "to": before_to, "days": len(before), "mean": round(mean_b, 2)},
        "after": {"from": after_from, "to": after_to, "days": len(after), "mean": round(mean_a, 2)},
        "delta_pct": round(100 * (mean_a - mean_b) / mean_b, 1) if mean_b else None,
        "z_score": z,
    }
