"""Today overview — the context around the score.

Three small, deterministic reads that make the Today header honest:

  releases          — what shipped inside the charted window, so a rating dip
                      can be lined up against the version that caused it.
  rating_breakdown  — when the average rating fell, which complaint themes
                      account for the fall. An ESTIMATE, labelled as one, whose
                      parts always sum to the total.
  freshness         — when this product's sources last pulled, so "nothing is
                      wrong" is never read off data that stopped arriving.

No LLM, no invented figures: every number is counted from the corpus.
"""
from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from echolens.db.models import (
    AnomalyEvent, CollectorState, Finding, Investigation, Product, Release, Review)
from echolens.detector.detect import reference_now
from echolens.onboarding.snapshot import WEEKS
from echolens.textkit import tokenize
from echolens.timeutil import aware_utc
from echolens.vocab import FAMILIES, _norm, theme_of

# Same windows the portfolio trend and impact maths use: the last week against
# the four weeks before it.
RECENT_DAYS = 7
PRIOR_DAYS = 28
# Below this many reviews in either window, an average rating is an anecdote.
MIN_SAMPLE = 5
# A fall smaller than this is rounding noise, not a drop worth explaining.
MIN_DROP = 0.05
MAX_THEMES = 3
# Older than this, Today offers to collect again.
STALE_AFTER_HOURS = 6

METHOD = ("Estimate. Each theme's part is how much its pull on the average changed: "
          "recent share × (recent theme avg − prior overall avg) minus "
          "prior share × (prior theme avg − prior overall avg). Reviews rated 1–2★ are "
          "assigned to the complaint theme whose vocabulary they match most; everything "
          "else is \"other\". The parts sum to the total change.")


def _short_date(dt: datetime) -> str:
    """"Jul 10" — strftime's %-d is not portable to Windows."""
    return f"{dt.strftime('%b')} {dt.day}"


def _version_label(version: str) -> str:
    v = (version or "").strip()
    return v if v[:1] in ("v", "V") else f"v{v}"


# ── releases ────────────────────────────────────────────────────────────

def releases_in_window(session: Session, product: str | None,
                       now: datetime | None = None, weeks: int = WEEKS) -> list[dict]:
    """Releases shipped inside the same trailing window the weekly chart draws.

    Scoped by product name (Release has no product_id): two products can both
    ship "v1.0.0", and one product's release must never mark another's chart.
    """
    now = now or reference_now(session, product)
    start = now - timedelta(days=7 * weeks)
    stmt = (select(Release).where(Release.released_at > start, Release.released_at <= now)
            .order_by(Release.released_at, Release.id))
    if product:
        stmt = stmt.where(Release.product == product)
    out = []
    for rel in session.scalars(stmt).all():
        at = aware_utc(rel.released_at)
        label = _version_label(rel.version)
        out.append({"version": rel.version, "released_at": at.isoformat(),
                    "label": f"{label} shipped {_short_date(at)}"})
    return out


# ── rating-drop breakdown ───────────────────────────────────────────────

def _theme_catalogue(session: Session, product_id: int | None) -> tuple[list[dict], dict[str, int]]:
    """Themes a review can be assigned to, and the case that explains each.

    The curated families, plus any emergent theme a resolved finding on this
    product named — so a complaint EchoLens already investigated is measured on
    the same axis as the case that explained it.
    """
    themes: dict[str, dict] = {
        fid: {"id": fid, "label": label, "vocab": {_norm(v) for v in vocab}}
        for fid, (label, vocab) in FAMILIES.items()}
    cases: dict[str, int] = {}
    stmt = (select(Investigation, AnomalyEvent)
            .outerjoin(AnomalyEvent, AnomalyEvent.id == Investigation.anomaly_id)
            .where(Investigation.status == "resolved"))
    if product_id is not None:
        stmt = stmt.where(Investigation.product_id == product_id)
    pairs = session.execute(stmt.order_by(Investigation.id)).all()
    latest: dict[int, Finding] = {}
    ids = [inv.id for inv, _ in pairs]
    if ids:
        for f in session.scalars(select(Finding).where(
                Finding.investigation_id.in_(ids)).order_by(Finding.id)).all():
            latest[f.investigation_id] = f
    for inv, anomaly in pairs:
        f = latest.get(inv.id)
        if f is None:
            continue
        t = theme_of(anomaly, {"summary": f.summary, **(f.json or {})})
        if t["id"] == "other":
            continue
        themes.setdefault(t["id"], {"id": t["id"], "label": t["label"],
                                    "vocab": {_norm(v) for v in t["terms"]}})
        # Later ids overwrite earlier ones: the newest explanation wins.
        cases[t["id"]] = inv.id
    return list(themes.values()), cases


def _assign(text: str | None, themes: list[dict]) -> str | None:
    """The theme a review's words match most; ties break by id so the same
    review always lands in the same theme."""
    toks = {_norm(t) for t in tokenize(text)}
    if not toks:
        return None
    best, best_hits = None, 0
    for t in sorted(themes, key=lambda x: x["id"]):
        hits = len(toks & t["vocab"])
        if hits > best_hits:
            best, best_hits = t["id"], hits
    return best


def _signed(x: float) -> str:
    return f"{x:+.2f}".replace("-", "−")


def rating_breakdown(session: Session, product: Product | None,
                     now: datetime | None = None) -> dict:
    """Which themes account for a fall in the average rating.

    Decomposition (exact, not fitted): with P the prior overall average, the
    recent average minus P equals the sum over groups of
    s'·(r' − P) − s·(r − P), where s/r are a group's share of reviews and its
    average in the prior window and s'/r' in the recent one. A theme that held
    steady contributes ~0; one whose complaints grew pulls negative. Only the
    largest negative parts are named; the rest is "other", so the parts always
    add up to the headline number.
    """
    name = product.name if product else None
    now = now or reference_now(session, name)
    recent_start = now - timedelta(days=RECENT_DAYS)
    prior_start = recent_start - timedelta(days=PRIOR_DAYS)
    stmt = select(Review.rating, Review.text, Review.created_at).where(
        Review.created_at > prior_start, Review.created_at <= now)
    if name:
        stmt = stmt.where(Review.product == name)
    rows = session.execute(stmt).all()
    recent = [(r, t) for r, t, at in rows if aware_utc(at) > recent_start]
    prior = [(r, t) for r, t, at in rows if aware_utc(at) <= recent_start]

    base = {"estimate": True, "method": METHOD,
            "window": {"recent_days": RECENT_DAYS, "prior_days": PRIOR_DAYS},
            "recent_reviews": len(recent), "prior_reviews": len(prior),
            "rating_now": None, "rating_prior": None, "delta": None,
            "dropped": False, "parts": [], "summary": None, "reason": None}
    if len(recent) < MIN_SAMPLE or len(prior) < MIN_SAMPLE:
        return {**base, "reason": (f"Needs at least {MIN_SAMPLE} reviews in the last "
                                   f"{RECENT_DAYS} days and the {PRIOR_DAYS} before it.")}

    p_avg = statistics.mean(r for r, _ in prior)
    r_avg = statistics.mean(r for r, _ in recent)
    delta = r_avg - p_avg
    out = {**base, "rating_now": round(r_avg, 2), "rating_prior": round(p_avg, 2),
           "delta": round(delta, 2)}
    if delta > -MIN_DROP:
        return {**out, "reason": "The average rating did not drop."}

    themes, cases = _theme_catalogue(session, product.id if product else None)
    labels = {t["id"]: t["label"] for t in themes}

    def groups(window):
        g: dict[str, list[int]] = {}
        for rating, text in window:
            tid = _assign(text, themes) if rating <= 2 else None
            g.setdefault(tid or "other", []).append(rating)
        return g

    g_recent, g_prior = groups(recent), groups(prior)
    n_recent, n_prior = len(recent), len(prior)

    def pull(ratings, n):
        return (len(ratings) / n) * (statistics.mean(ratings) - p_avg) if ratings else 0.0

    contrib = {tid: pull(g_recent.get(tid, []), n_recent) - pull(g_prior.get(tid, []), n_prior)
               for tid in set(g_recent) | set(g_prior) if tid != "other"}
    named = sorted(((tid, c) for tid, c in contrib.items() if round(c, 2) < 0),
                   key=lambda kv: (kv[1], kv[0]))[:MAX_THEMES]

    total = round(delta, 2)
    parts = []
    for tid, c in named:
        ratings = g_recent.get(tid, [])
        parts.append({
            "theme_id": tid, "label": labels.get(tid, tid), "contribution": round(c, 2),
            "recent_share_pct": round(100 * len(ratings) / n_recent, 1),
            "recent_reviews": len(ratings),
            "case_id": cases.get(tid),
        })
    # The remainder is computed from the ROUNDED parts so the displayed numbers
    # add up exactly; it carries every theme not named plus unthemed reviews.
    other = round(total - sum(p["contribution"] for p in parts), 2)
    parts.append({"theme_id": "other", "label": "other", "contribution": other,
                  "recent_share_pct": None, "recent_reviews": None, "case_id": None})

    bits = []
    for p in parts:
        cite = f" (case #{p['case_id']})" if p["case_id"] else ""
        label = p["label"] if p["theme_id"] == "other" else p["label"].lower()
        bits.append(f"{_signed(p['contribution'])}★ {label}{cite}")
    summary = f"Rating {_signed(total)}★ vs prior {PRIOR_DAYS // 7} weeks: " + ", ".join(bits)
    return {**out, "dropped": True, "parts": parts, "summary": summary}


# ── freshness ───────────────────────────────────────────────────────────

def freshness(session: Session, product: Product | None,
              now: datetime | None = None) -> dict:
    """When this product's sources last pulled — the most recent across them.

    Wall-clock `now`, not the corpus clock: the question is "is collection
    still running", and the corpus clock stops exactly when it isn't.
    """
    now = now or datetime.now(timezone.utc)
    stmt = select(CollectorState).where(CollectorState.enabled == True)  # noqa: E712
    if product is not None:
        # Older rows predate product_id, so fall back to the product's name.
        stmt = stmt.where(or_(CollectorState.product_id == product.id,
                              (CollectorState.product_id.is_(None))
                              & (CollectorState.product == product.name)))
    states = session.scalars(stmt).all()
    runs = [aware_utc(s.last_run_at) for s in states if s.last_run_at]
    last = max(runs) if runs else None
    age_min = max(0, int((now - last).total_seconds() // 60)) if last else None
    return {
        "last_synced_at": last.isoformat() if last else None,
        "age_minutes": age_min,
        "sources": len(states),
        "stale_after_hours": STALE_AFTER_HOURS,
        # Never-synced counts as stale only when there is something to sync.
        "stale": bool(states) and (age_min is None or age_min >= STALE_AFTER_HOURS * 60),
    }


def overview(session: Session, product: Product | None) -> dict:
    """Everything Today draws around the score, in one read."""
    name = product.name if product else None
    now = reference_now(session, name)
    return {
        "product": name,
        "product_id": product.id if product else None,
        "releases": releases_in_window(session, name, now),
        "rating_breakdown": rating_breakdown(session, product, now),
        "freshness": freshness(session, product),
    }
