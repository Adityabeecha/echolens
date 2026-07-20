"""Calibration + weak-spot analysis (v5.0) — correctness made measurable.

Over every human-reviewed finding, compare the confidence EchoLens stated with
whether a reviewer approved it. Renders as the in-product calibration curve, and
— the trust loop — feeds a corrective note back into the investigator's prompt
when it is systematically overconfident or repeatedly wrong in the same way.

Pure reads + arithmetic, no LLM.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import Finding, ReviewFeedback

# confidence buckets for the curve
_BUCKETS = [(0.0, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)]

_REASON_LABELS = {
    "wrong_cause": "wrong root cause",
    "weak_evidence": "evidence too weak",
    "wrong_severity": "severity/impact off",
    "already_knew": "already known",
}
_REASON_GUIDANCE = {
    "wrong_cause": "Before concluding, run a segmentation/refutation query that could DISPROVE the "
                   "leading cause (e.g. does the effect also appear where it shouldn't?).",
    "weak_evidence": "Hold strictly to the two-source rule; prefer detailed, multi-signal evidence over "
                     "single one-line reviews before raising confidence.",
    "wrong_severity": "Sanity-check severity against the affected-volume and rating numbers; don't overstate "
                      "a narrow issue.",
    "already_knew": "Check whether this cause is already known (prior findings) before spending budget re-proving it.",
}


def _verdict(session: Session, finding: Finding) -> str | None:
    """'approve' / 'challenge' from the finding's latest review, or None."""
    fb = session.scalars(
        select(ReviewFeedback).where(ReviewFeedback.finding_id == finding.id)
        .order_by(ReviewFeedback.id.desc())
    ).first()
    return fb.action if fb else None


def _findings(session: Session, product_id: int | None):
    stmt = select(Finding)
    if product_id is not None:
        stmt = stmt.where(Finding.product_id == product_id)
    return session.scalars(stmt).all()


def _reviewed(session: Session, product_id: int | None = None) -> list[tuple[float, str]]:
    """(stated_confidence, verdict) for every reviewed finding in this product."""
    out = []
    for f in _findings(session, product_id):
        v = _verdict(session, f)
        if v in ("approve", "challenge"):
            out.append((float(f.confidence or 0.0), v))
    return out


def calibration(session: Session, product_id: int | None = None) -> dict:
    """Stated-confidence vs. actual-approval curve over this product's findings."""
    data = _reviewed(session, product_id)
    n = len(data)
    points = []
    for lo, hi in _BUCKETS:
        bucket = [v for c, v in data if lo <= c < hi]
        approved = sum(1 for v in bucket if v == "approve")
        points.append({
            "range": f"{int(lo * 100)}–{int(hi * 100) if hi <= 1 else 100}%",
            "midpoint": round((lo + min(hi, 1.0)) / 2, 3),
            "count": len(bucket),
            "approval_rate": round(approved / len(bucket), 3) if bucket else None,
        })
    approved_total = sum(1 for _, v in data if v == "approve")
    overall_rate = round(approved_total / n, 3) if n else None
    mean_conf = round(sum(c for c, _ in data) / n, 3) if n else None
    # systematic overconfidence: stated confidence runs above realized accuracy
    gap = round(mean_conf - overall_rate, 3) if (mean_conf is not None and overall_rate is not None) else None
    return {
        "n_reviewed": n,
        "sufficient": n >= 20,                 # exit criterion: curve needs ≥20
        "points": points,
        "overall_approval_rate": overall_rate,
        "mean_stated_confidence": mean_conf,
        "overconfidence_gap": gap,
        "overconfident": bool(gap is not None and n >= 8 and gap >= 0.1),
        "headline": _headline(points, overall_rate),
    }


def _headline(points: list[dict], overall_rate) -> str | None:
    # pick the most-populated bucket with data for the "when we say X, we're right Y" line
    best = max((p for p in points if p["count"] and p["approval_rate"] is not None),
               key=lambda p: p["count"], default=None)
    if best is None:
        return None
    return (f"When EchoLens says {int(best['midpoint'] * 100)}%, it is approved "
            f"{int(best['approval_rate'] * 100)}% of the time.")


def weak_spots(session: Session, product_id: int | None = None) -> dict:
    """Roll up structured challenge reasons into visible failure modes (v5.0),
    scoped to one product."""
    scope = None
    if product_id is not None:
        scope = {f.id for f in _findings(session, product_id)}
    counts: dict[str, int] = {}
    for fb in session.scalars(
        select(ReviewFeedback).where(ReviewFeedback.action == "challenge")).all():
        if scope is not None and fb.finding_id not in scope:
            continue
        if fb.reason:
            counts[fb.reason] = counts.get(fb.reason, 0) + 1
    spots = [{"reason": r, "label": _REASON_LABELS.get(r, r), "count": c,
              "guidance": _REASON_GUIDANCE.get(r, "")}
             for r, c in sorted(counts.items(), key=lambda kv: -kv[1])]
    return {"total_challenges": sum(counts.values()), "spots": spots}


def guidance_text(session: Session, product_id: int | None = None) -> str:
    """The corrective note injected into the investigator's prompt (empty when
    there's nothing learned yet). This is the visible trust loop: past human
    verdicts change future behavior — learned per product."""
    lines: list[str] = []
    cal = calibration(session, product_id)
    if cal["overconfident"]:
        lines.append(
            f"CALIBRATION: over the last {cal['n_reviewed']} reviewed findings your stated confidence has "
            f"run ~{int(cal['overconfidence_gap'] * 100)} points above your human-approved accuracy "
            f"({int(cal['mean_stated_confidence'] * 100)}% stated vs {int(cal['overall_approval_rate'] * 100)}% "
            "approved). Be more conservative: demand stronger corroboration before high confidence.")
    ws = weak_spots(session, product_id)
    if ws["spots"]:
        top = ws["spots"][0]
        lines.append(f"KNOWN WEAK SPOT: reviewers most often reject findings for '{top['label']}' "
                     f"({top['count']}×). {top['guidance']}")
    return "\n".join(lines)
