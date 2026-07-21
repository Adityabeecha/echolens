"""Deterministic anomaly detector (PRD §4.1). Pure stats, no LLM, unit-tested.

Signals:
- negative_review_spike  — z-score of daily 1-star volume vs a trailing baseline
- theme_volume_surge     — jump in a term's share of negative reviews / posts
- issue_velocity_surge   — jump in GitHub issues/week matching a term

The detector only NOTICES anomalies and scores their severity. Deciding which
ones deserve an investigation is the orchestrator's judgment call (triage),
never the detector's — that split is the whole point of the architecture.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from echolens.db.models import AnomalyEvent, Issue, Post, Review
from echolens.tools._util import match_score, terms_of

AS_OF = datetime(2026, 7, 17, tzinfo=timezone.utc)  # fallback only
RECENT_DAYS = 7
BASELINE_DAYS = 28

# v3.0 baseline quality guard: below this average daily review volume, a 7-day
# window is too noisy to trust, so the detector honestly WIDENS its windows
# instead of firing on statistical noise (and says so).
LOW_VOLUME_PER_DAY = 3
LOW_VOLUME_RECENT_DAYS = 14
LOW_VOLUME_BASELINE_DAYS = 56


def reference_now(session: Session, product: str | None = None) -> datetime:
    """The 'now' we reason from: the latest review timestamp in the corpus. Works
    for both the frozen synthetic set and live real data — never a hardcoded date.

    Scoped by product. Unscoped, one product's healthy collector supplied the
    clock for a product whose own collector had stalled, so every window for the
    stalled product landed after its last review and silently measured zero —
    a dead source read as "no complaints" instead of "no data".
    """
    stmt = select(Review.created_at)
    if product:
        stmt = stmt.where(Review.product == product)
    latest = session.scalar(stmt.order_by(Review.created_at.desc()).limit(1))
    if latest is None and product:
        # this product has no corpus at all — fall back to the global clock
        latest = session.scalar(
            select(Review.created_at).order_by(Review.created_at.desc()).limit(1))
    if latest is None:
        return AS_OF
    return latest if latest.tzinfo else latest.replace(tzinfo=timezone.utc)


@dataclass
class Windows:
    """The recent/baseline window sizes a scan should use, widened automatically
    when the corpus is too sparse for a 7-day window to be meaningful."""
    recent: int = RECENT_DAYS
    baseline: int = BASELINE_DAYS
    low_volume: bool = False

    @property
    def note(self) -> str:
        return (f" (low review volume — widened to {self.recent}d/{self.baseline}d windows)"
                if self.low_volume else "")


def choose_windows(session: Session, as_of: datetime, product: str | None = None) -> Windows:
    """Pick window sizes from the corpus density near `as_of` (v3.0)."""
    span = BASELINE_DAYS + RECENT_DAYS
    start = as_of - timedelta(days=span)
    stmt = select(func.count(Review.id)).where(
        Review.created_at >= start, Review.created_at <= as_of)
    if product:
        stmt = stmt.where(Review.product == product)
    n = session.scalar(stmt) or 0
    if n / span < LOW_VOLUME_PER_DAY:
        return Windows(LOW_VOLUME_RECENT_DAYS, LOW_VOLUME_BASELINE_DAYS, low_volume=True)
    return Windows()

# What the detector watches. (term, human label). Kept small and explicit.
# Themes are DERIVED per product from its own feedback (see _derived_terms).
# These constants remain only as an explicit operator override via settings.
# They used to be the defaults, which meant every product on the system was
# scanned for the synthetic demo's themes — a brand-new product would reliably
# surface "sync/battery issue reports" it had never had.
POST_TERMS = [("slow", "'app is slow' mentions")]


def _derived_terms(texts: list[str], k: int = 5) -> list[tuple[str, str]]:
    """The themes THIS product's users actually complain about.

    Emergent, from the corpus in front of us, with no fixed keyword list — the
    same rule textkit.top_themes already follows. Lumo still finds battery and
    shipping because its reviews genuinely say so, not because they were baked
    into the detector.
    """
    from echolens.textkit import top_themes, tokenize
    usable = [t for t in texts if (t or "").strip()]
    if len(usable) < 5:
        return []   # too little to characterise; better silent than invented

    # Overlapping n-grams describe ONE problem, not several: "keep reloading",
    # "reloading switch" and "switch between" all came from the same sentence and
    # would otherwise open five near-identical cases for a single complaint.
    # A new term must share no word with one already accepted.
    out: list[tuple[str, str]] = []
    claimed: set[str] = set()
    for th in top_themes(usable, k=k * 3):
        label = (th.get("label") or "").strip()
        if not label:
            continue
        words = set(tokenize(label))
        if not words or words & claimed:
            continue
        claimed |= words
        out.append((label, f"'{label}' complaints"))
        if len(out) >= k:
            break
    return out

# Severity thresholds on the z-score.
SEV1_Z, SEV2_Z, SEV3_Z = 3.0, 2.0, 1.0


@dataclass
class Candidate:
    slug: str
    type: str
    metric: str
    delta: float
    z: float
    window: str
    description: str
    severity: str = field(default="SEV3")


def _severity(z: float) -> str:
    if z >= SEV1_Z:
        return "SEV1"
    if z >= SEV2_Z:
        return "SEV2"
    return "SEV3"


def _daily_counts(rows, key, start: datetime, end: datetime) -> list[float]:
    daily: dict = defaultdict(float)
    d = start.date()
    while d <= end.date():
        daily[d] = 0.0
        d += timedelta(days=1)
    for r in rows:
        day = key(r)
        if start.date() <= day <= end.date():
            daily[day] += 1
    return [daily[d] for d in sorted(daily)]


def _zscore(recent: list[float], baseline: list[float]) -> tuple[float, float]:
    """(z, delta_pct) of the recent mean against the baseline distribution."""
    if not recent or not baseline:
        return 0.0, 0.0
    mean_r, mean_b = statistics.mean(recent), statistics.mean(baseline)
    std_b = statistics.stdev(baseline) if len(baseline) > 1 else 0.0
    z = (mean_r - mean_b) / std_b if std_b > 0 else 0.0
    delta = (mean_r - mean_b) / mean_b if mean_b else 0.0
    return round(z, 2), round(delta, 3)


def detect_volume_spike(session: Session, as_of: datetime | None = None,
                        win: Windows | None = None, product: str | None = None) -> Candidate | None:
    as_of = as_of or reference_now(session, product)
    win = win or Windows()
    start = as_of - timedelta(days=win.baseline + win.recent)
    stmt = select(Review).where(Review.rating == 1, Review.created_at >= start)
    if product:
        stmt = stmt.where(Review.product == product)
    rows = session.scalars(stmt).all()
    series = _daily_counts(rows, lambda r: r.created_at.date(), start, as_of)
    if len(series) <= win.recent:
        return None
    baseline, recent = series[:-win.recent], series[-win.recent:]
    z, delta = _zscore(recent, baseline)
    if z < SEV3_Z:
        return None
    return Candidate(
        slug="auto-neg-review-spike", type="negative_review_spike",
        metric="daily 1-star review volume", delta=delta, z=z, window=f"{win.recent}d",
        description=f"1-star reviews {delta:+.0%} vs trailing {win.baseline}d baseline "
                    f"(z={z}); recent window ends {as_of.date()}.{win.note}",
        severity=_severity(z),
    )


def _share_series(rows, text_of, day_of, terms, start, as_of, negatives_only):
    """Per-day share (%) of items mentioning the term."""
    by_day_total: dict = defaultdict(int)
    by_day_hit: dict = defaultdict(int)
    for r in rows:
        day = day_of(r)
        if not (start.date() <= day <= as_of.date()):
            continue
        if negatives_only and getattr(r, "rating", 1) > 2:
            continue
        by_day_total[day] += 1
        if match_score(text_of(r), terms) > 0:
            by_day_hit[day] += 1
    d = start.date()
    series = []
    while d <= as_of.date():
        tot = by_day_total.get(d, 0)
        series.append(100 * by_day_hit.get(d, 0) / tot if tot else 0.0)
        d += timedelta(days=1)
    return series


def detect_rating_drop(session: Session, as_of: datetime | None = None,
                       win: Windows | None = None, product: str | None = None) -> Candidate | None:
    """Theme-agnostic: a real drop in average star rating. Works for ANY app,
    no keyword list required."""
    as_of = as_of or reference_now(session, product)
    win = win or Windows()
    start = as_of - timedelta(days=win.baseline + win.recent)
    stmt = select(Review).where(Review.created_at >= start)
    if product:
        stmt = stmt.where(Review.product == product)
    rows = session.scalars(stmt).all()
    daily: dict = defaultdict(list)
    for r in rows:
        if start.date() <= r.created_at.date() <= as_of.date():
            daily[r.created_at.date()].append(r.rating)
    days = sorted(daily)
    series = [statistics.mean(daily[d]) for d in days if daily[d]]
    if len(series) <= win.recent:
        return None
    baseline, recent = series[:-win.recent], series[-win.recent:]
    mean_b, mean_r = statistics.mean(baseline), statistics.mean(recent)
    std_b = statistics.stdev(baseline) if len(baseline) > 1 else 0.0
    drop = mean_b - mean_r
    z = round(drop / std_b, 2) if std_b > 0 else 0.0
    if drop < 0.3 or z < SEV3_Z:   # not a meaningful drop
        return None
    return Candidate(
        slug="auto-rating-drop", type="rating_drop",
        metric="average star rating", delta=round(-drop / mean_b, 3), z=z, window=f"{win.recent}d",
        description=f"Average rating fell from {mean_b:.2f}★ to {mean_r:.2f}★ over the last "
                    f"{win.recent} days (z={z}).{win.note}",
        severity=_severity(z),
    )


def detect_theme_surges(session: Session, as_of: datetime | None = None,
                        win: Windows | None = None, product: str | None = None) -> list[Candidate]:
    as_of = as_of or reference_now(session, product)
    win = win or Windows()
    start = as_of - timedelta(days=win.baseline + win.recent)
    r_stmt = select(Review).where(Review.created_at >= start)
    p_stmt = select(Post).where(Post.created_at >= start)
    if product:
        r_stmt = r_stmt.where(Review.product == product)
        p_stmt = p_stmt.where(Post.product == product)
    reviews = session.scalars(r_stmt).all()
    posts = session.scalars(p_stmt).all()
    out: list[Candidate] = []

    from echolens.config import settings
    # A real product supplies its OWN themes; the built-in Lumo terms are only the
    # demo default and are dropped once a real operator configures their terms.
    extra = settings.extra_theme_terms
    theme_terms = ([(t, f"'{t}' complaints") for t in extra] if extra
                   else _derived_terms([r.text for r in reviews if (r.rating or 5) <= 2]))
    for term, label in theme_terms:
        terms = terms_of(term)
        series = _share_series(reviews, lambda r: r.text, lambda r: r.created_at.date(),
                               terms, start, as_of, negatives_only=True)
        baseline, recent = series[:-win.recent], series[-win.recent:]
        z, delta = _zscore(recent, baseline)
        if z < SEV3_Z or statistics.mean(recent) < 3:
            continue
        out.append(Candidate(
            slug=f"auto-theme-{term.replace(' ', '-')}", type="theme_volume_surge",
            metric=f"{label} share of negative reviews", delta=delta, z=z, window=f"{win.recent}d",
            description=f"{label}: {statistics.mean(recent):.0f}% of recent negatives vs "
                        f"{statistics.mean(baseline):.0f}% baseline (z={z}).{win.note}",
            severity=_severity(z),
        ))

    # POST_TERMS are Lumo-demo specific; skip them for a real configured product.
    for term, label in ([] if extra else POST_TERMS):
        terms = terms_of(term)
        series = _share_series(posts, lambda p: p.text_snippet, lambda p: p.created_at.date(),
                               terms, start, as_of, negatives_only=False)
        baseline, recent = series[:-win.recent], series[-win.recent:]
        z, delta = _zscore(recent, baseline)
        if z < SEV3_Z:
            continue
        out.append(Candidate(
            slug=f"auto-post-{term.replace(' ', '-')}", type="theme_volume_surge",
            metric=f"{label} on Reddit", delta=delta, z=z, window=f"{win.recent}d",
            description=f"{label}: community chatter up (z={z}); low separation from baseline variance.",
            severity=_severity(z),
        ))
    return out


def detect_issue_velocity(session: Session, as_of: datetime | None = None,
                          win: Windows | None = None, product: str | None = None) -> list[Candidate]:
    as_of = as_of or reference_now(session, product)
    win = win or Windows()
    start = as_of - timedelta(days=win.baseline + win.recent)
    stmt = select(Issue).where(Issue.created_at >= start)
    if product:
        stmt = stmt.where(Issue.product == product)
    issues = session.scalars(stmt).all()
    out: list[Candidate] = []
    from echolens.config import settings
    # ISSUE_TERMS are Lumo-demo specific; a real product uses its own themes.
    issue_terms = ([(t, f"'{t}' issue reports") for t in settings.extra_theme_terms]
                   if settings.extra_theme_terms
                   else [(term, f"'{term}' issue reports") for term, _ in _derived_terms(
                       [f"{i.title} {i.body_snippet or ''}" for i in issues], k=3)])
    for term, label in issue_terms:
        terms = terms_of(term)
        hits = [i for i in issues if match_score(i.title + " " + i.body_snippet, terms) > 0]
        series = _daily_counts(hits, lambda i: i.created_at.date(), start, as_of)
        baseline, recent = series[:-win.recent], series[-win.recent:]
        z, delta = _zscore(recent, baseline)
        recent_count = sum(recent)
        if recent_count < 2:
            continue
        out.append(Candidate(
            slug=f"auto-issues-{term.split()[0]}", type="issue_velocity_surge",
            metric=f"{label} per week", delta=delta, z=z, window=f"{RECENT_DAYS}d",
            description=f"{label}: {recent_count:.0f} new issues this week (z={z}); "
                        f"same window and theme as the review signal.",
            severity=_severity(max(z, SEV2_Z)),
        ))
    return out


# v8.0 noise gate: a signal below this z never becomes a case at all.
MIN_CASE_Z = SEV3_Z          # detector-level filter, not a display filter
MERGE_WINDOW_DAYS = 7        # same metric within N days → same anomaly, not a new one


def scan(session: Session, as_of: datetime | None = None, persist: bool = True,
         product: str | None = None, product_id: int | None = None) -> list[AnomalyEvent]:
    """Run every detector for ONE product and UPSERT the results.

    Dedupe key is (product_id, type, metric, overlapping window): re-running a
    scan updates the open anomaly for that window instead of inserting a second
    row — so "Scan now" is safe to press repeatedly. Signals below MIN_CASE_Z are
    dropped here (noise gate), never surfaced as cases."""
    if as_of is None:
        as_of = reference_now(session, product)
    win = choose_windows(session, as_of, product)
    candidates: list[Candidate] = []
    spike = detect_volume_spike(session, as_of, win, product)
    if spike:
        candidates.append(spike)
    drop = detect_rating_drop(session, as_of, win, product)
    if drop:
        candidates.append(drop)
    candidates += detect_theme_surges(session, as_of, win, product)
    candidates += detect_issue_velocity(session, as_of, win, product)
    # Noise gate: a weak SEV3 signal (z below threshold) never becomes a case.
    # Detectors that assert their own significance (SEV1/SEV2 — e.g. issue
    # velocity, which counts real new issues) are not z-gated.
    candidates = [c for c in candidates
                  if c.severity in ("SEV1", "SEV2") or abs(c.z) >= MIN_CASE_Z]

    window_start = as_of - timedelta(days=win.recent)
    events: list[AnomalyEvent] = []
    for c in candidates:
        slug = f"p{product_id}-{c.slug}" if product_id else c.slug
        # Dedupe key: the product-scoped slug identifies (product, detector, metric);
        # re-scanning the same window UPSERTS it instead of inserting a duplicate.
        prior = session.scalars(select(AnomalyEvent).where(AnomalyEvent.slug == slug)).first()
        if prior is not None:
            fresh = prior.window_end is None or (
                window_start - _aware(prior.window_end)) <= timedelta(days=MERGE_WINDOW_DAYS)
            prior.z, prior.delta = c.z, c.delta
            prior.description, prior.window = c.description, c.window
            if fresh:  # same ongoing window → extend it
                prior.window_start = prior.window_start or window_start
            else:      # a new occurrence after a gap → restart the window
                prior.window_start = window_start
            prior.window_end = as_of
            events.append(prior)
            continue
        ev = AnomalyEvent(
            slug=slug, type=c.type, metric=c.metric, delta=c.delta, z=c.z,
            window=c.window, description=c.description, status="pending",
            product_id=product_id, window_start=window_start, window_end=as_of,
        )
        if persist:
            session.add(ev)
        events.append(ev)
    if persist:
        session.flush()
    return events


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
