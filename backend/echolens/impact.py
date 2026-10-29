"""Impact quantification (v4.0) — turns a confirmed cause into the numbers a PM
needs to prioritise: how many users, how much rating, which cohorts.

DETERMINISTIC math over the same corpus the agent cited — no LLM, no invented
figures. Everything is an estimate over observed reviews and is labelled as such;
the trust chain (every claim → evidence) is unchanged.
"""
from __future__ import annotations

import re

import statistics
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import Review
from echolens.detector.detect import reference_now
from echolens.textkit import clean_headline, tokenize
from echolens.timeutil import aware_utc
from echolens.tools._util import match_score

# words that are structural to a finding, not the theme itself
_GENERIC = {
    "review", "reviews", "star", "stars", "daily", "volume", "rating", "ratings",
    "average", "share", "complaint", "complaints", "negative", "spike", "surge",
    "drop", "case", "investigation", "cause", "causes", "drives", "driving",
    "users", "user", "update", "issue", "issues", "report", "reports", "feedback",
    "week", "version",
    # Finding-narration words. A real finding produced the terms
    # ['supported', 'release', 'introduced', 'broadly', 'reported', 'battery'];
    # these feed FixWatch matching and the pattern library, so verbs like these
    # matched unrelated complaints.
    "supported", "rejected", "hypothesis", "introduced", "introduces", "introduce",
    "broadly", "broad", "reported", "reporting", "recent", "recently", "release",
    "released", "releases", "regression", "regressed", "affecting", "affects",
    "affected", "caused", "causing", "linked", "likely", "widespread", "since",
    "after", "before", "new", "change", "changes", "changed", "app", "apps",
    "evidence", "finding", "confidence", "rising", "rise", "increase", "increased",
    "negatives", "baseline", "recent", "vs",
    "surged", "surge", "surging", "rose", "jumped", "spiked", "consistent", "always",
    "likely", "possibly", "probably", "suggests", "supports", "indicates", "shows",
    "began", "begins", "started", "worsened", "worse", "mechanism", "specific",
}

RECENT_DAYS = 7
# Below this many recent negative reviews, a percentage share is noise dressed
# as a statistic (1 of 1 is "100%"), so it is not reported as one.
MIN_SHARE_DENOMINATOR = 5
BASELINE_DAYS = 28


def theme_terms(anomaly, finding_json: dict) -> list[str]:
    """The complaint keywords to measure impact against, drawn from the finding
    summary + supported hypothesis + anomaly, minus structural words."""
    # The detector's own theme ("'battery drain' complaints …") is the most
    # reliable signal of what complaints to match, so its words lead.
    description = getattr(anomaly, "description", "") or ""
    quoted = " ".join(re.findall(r"['‘“\"]([^'’”\"]{3,40})['’”\"]", description))
    parts = [quoted, finding_json.get("summary", ""), finding_json.get("prose", "")[:300],
             description, getattr(anomaly, "metric", "") or ""]
    seen: list[str] = []
    for tok in tokenize(" ".join(parts)):
        tok = tok.strip("'\"‘’“”")
        if not tok or tok.isdigit() or tok.replace(".", "").isdigit():
            continue
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

    # A share needs a denominator big enough to be a share. 1-of-1 is "100% of
    # negative reviews" on a sample of one, which then contributes 0.5 to
    # impact_score and pushes severity toward high on a single review.
    affected_pct = (round(100 * len(matching) / len(recent_neg), 1)
                    if len(recent_neg) >= MIN_SHARE_DENOMINATOR else 0.0)
    share_measurable = len(recent_neg) >= MIN_SHARE_DENOMINATOR
    base_avg = _mean_rating(baseline)
    recent_avg = _mean_rating(recent)
    rating_impact = (round(max(0.0, base_avg - recent_avg), 2)
                     if base_avg is not None and recent_avg is not None else 0.0)

    blast = _blast_radius(session, terms, recent_start, product)

    # v10: the same complaint filed in two places is ONE affected person. Counting
    # it per channel inflates impact exactly when a problem is being escalated —
    # the worst moment to overstate. `cross_source` counts distinct witnesses
    # across every channel; `affected_volume` stays the store-review figure the
    # rating maths depends on.
    cross = _cross_source_impact(session, terms, product, recent_start, now)

    # a single 0..1 impact score used for severity + alert routing
    impact_score = min(1.0, 0.5 * (affected_pct / 100) + 0.3 * min(1.0, len(matching) / 40)
                       + 0.2 * min(1.0, rating_impact / 0.6))
    # Whether we could measure impact AT ALL. Without this, an unmeasured case
    # and a genuinely tiny one both scored 0.0 and both rendered as "low" — the
    # difference between "we looked and it is small" and "we could not look".
    measured = bool(share_measurable or len(matching) or rating_impact)

    return {
        "cross_source": cross,
        "terms": terms,
        "measured": measured,                    # False = no data, NOT "low impact"
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
    except Exception as err:
        # Impact must survive a missing feedback layer — but a hard zero is
        # indistinguishable from "genuinely nobody else reported this", and it
        # is rendered as fact. Say it is unknown, and LOG it: this silently
        # swallowed real query and normalisation failures.
        from echolens.logging import get_logger
        get_logger("impact").warning("cross_source_failed", error=str(err))
        return {"witnesses": 0, "raw_mentions": 0, "collapsed_duplicates": 0,
                "channels": [], "distinct_channels": 0, "measured": False}


def _blast_radius(session, terms, recent_start, product: str | None = None) -> dict:
    """Which app version the complaint concentrates in (the decoy-killer, reused
    for prioritisation). Deterministic cohort counting.

    Scoped by product. compare_cohorts accepts `product` and this never passed
    it, so every other product's reviews were pooled into this product's version
    cohorts — and the result is rendered as fact ("concentrated in 3.2, 4x the
    next version") where "3.2" could be a different app's version string.
    """
    if not terms:
        return {"dimension": "version", "top_cohort": None, "ratio": None, "exclusive": False}
    from echolens.tools.compare_cohorts import compare_cohorts
    res = compare_cohorts(session, term=" ".join(terms), dimension="version",
                          date_from=recent_start.date().isoformat(), product=product)
    return {
        "dimension": "version",
        "top_cohort": res.get("highest_cohort"),
        "ratio": res.get("highest_vs_next_ratio"),
        "exclusive": res.get("only_in_top_cohort", False),
    }


def severity(confidence: float, impact: dict) -> dict:
    """Severity = how bad × how sure. Confidence is the agent's; impact is the
    deterministic score. Drives alert routing (instant vs digest).

    `impact_score` is clamped: it was only bounded at its own construction site,
    so any other producer could hand in a value above 1.0 and yield a severity
    score above 1.0 — a number outside its own stated range.

    A band of "unknown" is returned when impact could not be measured at all.
    Previously that case scored 0.0 and rendered as "low", which is a claim:
    it told the reader we had looked and found little, when we had not looked.
    """
    raw = impact.get("impact_score", 0.0)
    try:
        raw = max(0.0, min(1.0, float(raw)))
    except (TypeError, ValueError):
        raw = 0.0
    score = round(max(0.0, min(1.0, confidence)) * raw, 3)
    # `measured` is absent on findings written before it existed; treat a
    # present impact payload as measured so old rows keep their band.
    if impact.get("measured") is False:
        return {"score": score, "band": "unknown"}
    band = "high" if score >= 0.5 else "medium" if score >= 0.25 else "low"
    return {"score": score, "band": band}


def _pct(x) -> str:
    return f"{x:.0f}%"


def problem_numbers(session: Session, product: str, finding, anomaly) -> dict:
    """This problem's own numbers, the ones Today shows: its pull on the rating
    (last 7 days against the 28 before) and its share of one-star reviews in
    30 days. One definition for every surface — the GitHub issue used to say
    "0.89★ lost" (the whole app's rating fall) where Today said 0.23★."""
    from statistics import mean
    from echolens.cases import _terms
    from echolens.textkit import tokenize
    from echolens.vocab import _norm

    needles = [{_norm(w) for w in tokenize(t)} for t in _terms(finding, anomaly)]

    def matches(row):
        words = {_norm(w) for w in tokenize(row.text_en or row.text)}
        return row.rating <= 2 and any(n and n <= words for n in needles)

    now = reference_now(session, product)
    rows = list(session.scalars(select(Review).where(Review.product == product,
        Review.created_at > now - timedelta(days=35), Review.created_at <= now)))
    recent = [r for r in rows if aware_utc(r.created_at) > now - timedelta(days=7)]
    prior = [r for r in rows if aware_utc(r.created_at) <= now - timedelta(days=7)]
    drag = None
    if needles and len(recent) >= 5 and len(prior) >= 5:
        baseline = mean(r.rating for r in prior)
        # Change in this theme's pull on the average: share × (rating − prior
        # overall average), recent 7 days minus prior 28 days. Not additive
        # across overlapping cases; an estimate, not a causal rating forecast.
        contribution = (sum(r.rating - baseline for r in recent if matches(r)) / len(recent)
                        - sum(r.rating - baseline for r in prior if matches(r)) / len(prior))
        drag = round(max(0.0, -contribution), 2)
    one_star = [r for r in rows if r.rating == 1
                and aware_utc(r.created_at) >= now.replace(hour=0, minute=0, second=0, microsecond=0)
                - timedelta(days=29)]
    matching = sum(matches(r) for r in one_star)
    share = {"matching": matching, "total": len(one_star), "days": 30,
             "pct": round(100 * matching / len(one_star), 1) if needles and len(one_star) >= 5 else None}
    return {"rating_drag": drag, "one_star_share": share}


def impact_line(impact: dict, numbers: dict | None = None) -> str:
    """One-line 'how bad' summary for the decision doc, Slack, and tickets.

    With `numbers` (problem_numbers) it states the problem's own rating pull
    and one-star share, matching Today and the problem page. It never states
    the app's overall rating fall as this problem's loss."""
    bits = []
    share = (numbers or {}).get("one_star_share") or {}
    if share.get("pct"):
        bits.append(f"{share['pct']:.0f}% of one-star reviews in the last 30 days "
                    f"({share['matching']} of {share['total']})")
    elif impact.get("affected_volume"):
        bits.append(f"≈{_pct(impact['affected_pct'])} of recent negative reviews "
                    f"({impact['affected_volume']} in the last {RECENT_DAYS} days)")
    if (numbers or {}).get("rating_drag"):
        bits.append(f"est. {numbers['rating_drag']:.2f}★ off the rating (last 7 days vs the 28 before)")
    br = impact.get("blast_radius") or {}
    if br.get("top_cohort") and br.get("top_cohort") != "unknown":
        if br.get("exclusive"):
            bits.append(f"seen only in {br['top_cohort']}")
        elif br.get("ratio"):
            bits.append(f"concentrated in {br['top_cohort']} ({br['ratio']}× the next version)")
        else:
            bits.append(f"concentrated in {br['top_cohort']}")
    return "; ".join(bits) or "impact too small to quantify from current data."


def decision_doc(finding_json: dict, recommendations: list, impact: dict, status: str,
                 numbers: dict | None = None) -> dict:
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
        "whats_broken": clean_headline(finding_json.get("summary", "")),
        "how_bad": impact_line(impact, numbers),
        "what_to_do": what_to_do,
    }
