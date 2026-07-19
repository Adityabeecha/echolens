"""Instant health snapshot (v3.0) — what EchoLens already knows about a product
before any investigation runs. Powers the onboarding wait screen ("while the
backfill runs, here's what we found") and the "Investigate now on anything"
entry point.

Pure reads over the corpus, no LLM. Themes are EMERGENT (see textkit.top_themes)
so this works on any app, not a keyword list tuned for Lumo.
"""
from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import Review
from echolens.detector.detect import LOW_VOLUME_PER_DAY, reference_now
from echolens.textkit import is_probably_english, top_themes

WEEKS = 12  # how much recent history to chart


def _at(r: Review) -> datetime:
    """SQLite drops tzinfo on round-trip; normalize to UTC-aware for comparisons."""
    dt = r.created_at
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _weekly_series(reviews: list[Review], now, weeks: int) -> list[dict]:
    """Bucket reviews into `weeks` trailing 7-day windows: count + mean rating."""
    buckets: list[dict] = []
    for w in range(weeks):
        end = now - timedelta(days=7 * w)
        start = end - timedelta(days=7)
        window = [r for r in reviews if start < _at(r) <= end]
        buckets.append({
            "week_start": start.date().isoformat(),
            "count": len(window),
            "avg_rating": round(statistics.mean([r.rating for r in window]), 2) if window else None,
        })
    buckets.reverse()  # oldest → newest for charting
    return buckets


def health_snapshot(session: Session, product: str | None = None, days: int = 90) -> dict:
    """A read-only portrait of a product's feedback: volume, rating trend, top
    negative themes, and a data-quality verdict."""
    now = reference_now(session)
    start = now - timedelta(days=days)
    q = select(Review).where(Review.created_at >= start)
    if product:
        q = q.where(Review.product == product)
    reviews = session.scalars(q).all()

    n = len(reviews)
    span_days = max(1, (now.date() - start.date()).days)
    avg_per_day = n / span_days

    negatives = [r for r in reviews if r.rating <= 2]
    english_neg = [r.text for r in negatives if is_probably_english(r.text)]
    non_english = sum(1 for r in reviews if r.text and not is_probably_english(r.text))

    weekly = _weekly_series(reviews, now, WEEKS)
    recent = [r.rating for r in reviews if _at(r) > now - timedelta(days=7)]
    prior = [r.rating for r in reviews if now - timedelta(days=14) < _at(r) <= now - timedelta(days=7)]
    rating_now = round(statistics.mean(recent), 2) if recent else None
    rating_prev = round(statistics.mean(prior), 2) if prior else None

    low_volume = avg_per_day < LOW_VOLUME_PER_DAY
    return {
        "product": product,
        "reviews": n,
        "window_days": days,
        "date_from": start.date().isoformat(),
        "date_to": now.date().isoformat(),
        "avg_per_day": round(avg_per_day, 1),
        "negatives": len(negatives),
        "rating_now": rating_now,
        "rating_prev": rating_prev,
        "rating_delta": (round(rating_now - rating_prev, 2)
                         if rating_now is not None and rating_prev is not None else None),
        "weekly": weekly,
        "top_themes": top_themes(english_neg, k=6),
        "non_english": non_english,
        "data_quality": {
            "low_volume": low_volume,
            "note": (f"Low review volume ({avg_per_day:.1f}/day) — anomaly detection will use "
                     f"wider 28-day windows to avoid firing on noise." if low_volume else None),
            "non_english_note": (f"{non_english} non-English reviews are counted for volume and "
                                 f"rating but skipped for theme matching." if non_english else None),
        },
    }
