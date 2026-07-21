"""Impact quantification (v4.0) — turns a confirmed cause into the numbers a PM
needs to prioritise: how many users, how much rating, which cohorts.

DETERMINISTIC math over the same corpus the agent cited — no LLM, no invented
figures. Everything is an estimate over observed reviews and is labelled as such;
the trust chain (every claim → evidence) is unchanged.
"""
from __future__ import annotations

import statistics
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import Review
from echolens.detector.detect import reference_now
from echolens.textkit import tokenize
from echolens.timeutil import aware_utc
from echolens.tools._util import match_score

# words that are structural to a finding, not the theme itself
_GENERIC = {
    "review", "reviews", "star", "stars", "daily", "volume", "rating", "ratings",
    "average", "share", "complaint", "complaints", "negative", "spike", "surge",
    "drop", "case", "investigation", "cause", "causes", "drives", "driving",
    "users", "user", "update", "issue", "issues", "report", "reports", "feedback",
    "week", "version",
}

RECENT_DAYS = 7
BASELINE_DAYS = 28


def theme_terms(anomaly, finding_json: dict) -> list[str]:
    """The complaint keywords to measure impact against, drawn from the finding
    summary + supported hypothesis + anomaly, minus structural words."""
    parts = [finding_json.get("summary", ""), finding_json.get("prose", "")[:300],
             getattr(anomaly, "description", "") or "", getattr(anomaly, "metric", "") or ""]
    seen: list[str] = []
    for tok in tokenize(" ".join(parts)):
        if tok not in _GENERIC and tok not in seen:
            seen.append(tok)
    return seen[:6] or tokenize(finding_json.get("summary", ""))[:3]


def _mean_rating(rows) -> float | None:
    vals = [r.rating for r in rows]
    return round(statistics.mean(vals), 2) if vals else None


def quantify(session: Session, anomaly, finding_json: dict, product: str | None = None) -> dict:
    """Estimate affected-user share, rating impact, and blast radius for a
    finding. Safe on any corpus (returns zeros rather than raising)."""
    terms = theme_terms(anomaly, finding_json)
    now = reference_now(session, product)
    recent_start = now - timedelta(days=RECENT_DAYS)
    base_start = now - timedelta(days=BASELINE_DAYS + RECENT_DAYS)

    stmt = select(Review).where(Review.created_at >= base_start)
    if product:
        stmt = stmt.where(Review.product == product)
    rows = session.scalars(stmt).all()

    recent = [r for r in rows if aware_utc(r.created_at) > recent_start]
    baseline = [r for r in rows if base_start <= aware_utc(r.created_at) <= recent_start]
    recent_neg = [r for r in recent if r.rating <= 2]
    matching = [r for r in recent_neg if terms and match_score(r.text, terms) > 0]

    affected_pct = round(100 * len(matching) / len(recent_neg), 1) if recent_neg else 0.0
    base_avg = _mean_rating(baseline)
    recent_avg = _mean_rating(recent)
    rating_impact = (round(max(0.0, base_avg - recent_avg), 2)
                     if base_avg is not None and recent_avg is not None else 0.0)

    blast = _blast_radius(session, terms, recent_start)

    # v10: the same complaint filed in two places is ONE affected person. Counting
    # it per channel inflates impact exactly when a problem is being escalated —
    # the worst moment to overstate. `cross_source` counts distinct witnesses
    # across every channel; `affected_volume` stays the store-review figure the
    # rating maths depends on.
    cross = _cross_source_impact(session, terms, product, recent_start, now)

    # a single 0..1 impact score used for severity + alert routing
    impact_score = min(1.0, 0.5 * (affected_pct / 100) + 0.3 * min(1.0, len(matching) / 40)
                       + 0.2 * min(1.0, rating_impact / 0.6))

    return {
        "cross_source": cross,
        "terms": terms,
        "affected_pct": affected_pct,            # % of recent negative reviews on this theme
        "affected_volume": len(matching),         # count of those reviews (last 7d)
        "recent_negatives": len(recent_neg),
        "rating_now": recent_avg,
        "rating_baseline": base_avg,
        "rating_impact": rating_impact,           # est. stars lost vs baseline
        "blast_radius": blast,                    # cohort concentration
        "impact_score": round(impact_score, 3),
        "as_of": now.date().isoformat(),
    }


def _cross_source_impact(session, terms, product, start, end) -> dict:
    """Distinct people affected across every channel, deduplicated.

    Returns the collapsed count alongside the raw one so the difference is
    visible rather than silently applied — if 12 mentions become 9 witnesses,
    the PM should be able to see that three were the same complaint twice.
    """
    try:
        from echolens.feedback import collect_items, dedupe_witnesses
        items = [i for i in collect_items(session, product, since=start, until=end)
                 if terms and match_score(i.text, terms) > 0]
        kept, collapsed = dedupe_witnesses(items)
        # Channel coverage counts every channel that WITNESSED the problem,
        # including ones whose report was collapsed as a duplicate person. One
        # affected user, two channels that saw it — both facts are true.
        channels = set()
        for i in kept:
            channels.add(i.channel)
            channels.update(i.meta.get("also_seen_in") or [])
        channels = sorted(channels)
        return {
            "witnesses": len(kept),
            "raw_mentions": len(items),
            "collapsed_duplicates": collapsed,
            "channels": channels,
            "distinct_channels": len(channels),
        }
    except Exception:
        # impact must survive a missing/!empty feedback layer
        return {"witnesses": 0, "raw_mentions": 0, "collapsed_duplicates": 0,
                "channels": [], "distinct_channels": 0}


def _blast_radius(session, terms, recent_start) -> dict:
    """Which app version the complaint concentrates in (the decoy-killer, reused
    for prioritisation). Deterministic cohort counting."""
    if not terms:
        return {"dimension": "version", "top_cohort": None, "ratio": None, "exclusive": False}
    from echolens.tools.compare_cohorts import compare_cohorts
    res = compare_cohorts(session, term=" ".join(terms), dimension="version",
                          date_from=recent_start.date().isoformat())
    return {
        "dimension": "version",
        "top_cohort": res.get("highest_cohort"),
        "ratio": res.get("highest_vs_next_ratio"),
        "exclusive": res.get("only_in_top_cohort", False),
    }


def severity(confidence: float, impact: dict) -> dict:
    """Severity = how bad × how sure. Confidence is the agent's; impact is the
    deterministic score. Drives alert routing (instant vs digest)."""
    score = round(max(0.0, min(1.0, confidence)) * impact.get("impact_score", 0.0), 3)
    band = "high" if score >= 0.5 else "medium" if score >= 0.25 else "low"
    return {"score": score, "band": band}


def _pct(x) -> str:
    return f"{x:.0f}%"


def impact_line(impact: dict) -> str:
    """One-line 'how bad' summary for the decision doc, Slack, and tickets."""
    bits = []
    if impact.get("affected_volume"):
        bits.append(f"≈{_pct(impact['affected_pct'])} of recent negative reviews "
                    f"({impact['affected_volume']} in the last {RECENT_DAYS} days)")
    if impact.get("rating_impact"):
        bits.append(f"est. {impact['rating_impact']:.2f}★ lost vs baseline")
    br = impact.get("blast_radius") or {}
    if br.get("top_cohort") and br.get("top_cohort") != "unknown":
        if br.get("exclusive"):
            bits.append(f"seen only in {br['top_cohort']}")
        elif br.get("ratio"):
            bits.append(f"concentrated in {br['top_cohort']} ({br['ratio']}× the next version)")
        else:
            bits.append(f"concentrated in {br['top_cohort']}")
    return "; ".join(bits) or "impact too small to quantify from current data."


def decision_doc(finding_json: dict, recommendations: list, impact: dict, status: str) -> dict:
    """The three questions a PM asks, answered above the fold in ≤5 lines.
    What's broken? How bad? What do I do? — evidence stays one click away."""
    top = recommendations[0] if recommendations else None
    if top is not None:
        what_to_do = getattr(top, "action", None) or (top.get("action") if isinstance(top, dict) else None)
    elif status == "resolved":
        what_to_do = "Review the evidence and file the fix."
    else:
        what_to_do = finding_json.get("what_would_settle_it") or "Gather more evidence before acting."
    return {
        "whats_broken": finding_json.get("summary", ""),
        "how_bad": impact_line(impact),
        "what_to_do": what_to_do,
    }
