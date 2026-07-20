"""compare_cohorts (v2.0): prove version-specific causation deterministically.

Splits reviews into cohorts by version / OS and compares a cohort's complaint
rate for a term against the rest. This is the decoy-killer in one call:
"v3.2 users complain about battery 4x more than v3.1 users on the same OS."
No LLM — pure counting.
"""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import Review
from echolens.tools._util import match_score, parse_date, terms_of


def compare_cohorts(
    session: Session,
    term: str,
    dimension: str = "version",   # "version" | "os"
    date_from: str | None = None,
    date_to: str | None = None,
    os_version: str | None = None,     # hold OS fixed while comparing versions
    version_prefix: str | None = None, # hold version fixed while comparing OS
    product: str | None = None,
) -> dict:
    stmt = select(Review)
    if product:
        stmt = stmt.where(Review.product == product)
    if date_from:
        stmt = stmt.where(Review.created_at >= parse_date(date_from))
    if date_to:
        stmt = stmt.where(Review.created_at <= parse_date(date_to))
    if os_version:
        stmt = stmt.where(Review.os_version == os_version)
    if version_prefix:
        stmt = stmt.where(Review.version.like(f"{version_prefix}%"))
    rows = session.scalars(stmt).all()

    terms = terms_of(term)

    def cohort_key(r: Review) -> str:
        if dimension == "os":
            return r.os_version or "unknown"
        # group by major.minor of version (e.g. 3.2)
        v = r.version or "unknown"
        return ".".join(v.split(".")[:2]) if v != "unknown" else v

    agg: dict[str, dict] = defaultdict(lambda: {"total": 0, "neg": 0, "term_neg": 0})
    for r in rows:
        c = agg[cohort_key(r)]
        c["total"] += 1
        if r.rating <= 2:
            c["neg"] += 1
            if match_score(r.text, terms) > 0:
                c["term_neg"] += 1

    cohorts = []
    for key, c in agg.items():
        share = round(100 * c["term_neg"] / c["neg"], 1) if c["neg"] else 0.0
        cohorts.append({
            "cohort": key, "reviews": c["total"], "negatives": c["neg"],
            "term_share_of_negatives_pct": share,
        })
    cohorts.sort(key=lambda x: -x["term_share_of_negatives_pct"])

    top, rest = (cohorts[0] if cohorts else None), cohorts[1:]
    ratio = None
    only_in_top = False
    if top and rest:
        next_share = max((r["term_share_of_negatives_pct"] for r in rest), default=0.0)
        top_share = top["term_share_of_negatives_pct"]
        if next_share > 0:
            ratio = round(top_share / next_share, 1)
        elif top_share > 0:
            only_in_top = True  # the complaint appears in ONLY the top cohort — strongest signal
    return {
        "term": term, "dimension": dimension,
        "held_fixed": {"os_version": os_version, "version_prefix": version_prefix},
        "cohorts": cohorts,
        "highest_cohort": top["cohort"] if top else None,
        "highest_vs_next_ratio": ratio,  # e.g. 4.0 → "4x more than the next cohort"
        "only_in_top_cohort": only_in_top,  # true → effectively exclusive to that cohort
    }
