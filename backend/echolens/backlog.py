"""The quality backlog — from findings to a defended plan.

EchoLens used to end at a ticket: here is a problem, here is the evidence, good
luck. But a PM does not decide one problem at a time; they decide what fits in a
quarter. This module makes that jump — a ranked, defended backlog with an
effort estimate and a projected outcome per line.

Three commitments shape it:

* **Every line is defended.** A ranked list nobody can audit is a ranked list
  nobody will follow, so each item carries the finding, its evidence refs and
  the arithmetic behind its score.
* **Effort is measured or absent, never invented.** Where linked issues give
  signal (labels, how long comparable fixes actually took) it is used and its
  basis is stated. Where they do not, the item says "effort unknown" and is
  ranked on impact alone rather than on a fabricated number.
* **The system proposes, the human disposes.** The plan is a draft the PM edits
  and owns; their include/exclude decisions persist and are never silently
  overwritten by a re-rank.
"""
from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import (
    AnomalyEvent, EvidenceRow, Finding, FixWatch, Investigation, Issue, Setting)
from echolens.impact import severity
from echolens.timeutil import aware_utc

# Effort in ideal engineer-days. Labels are a coarse signal, so the buckets are
# coarse too — claiming a 3.5-day estimate from a GitHub label would be false
# precision.
EFFORT_BUCKETS = {"trivial": 0.5, "small": 2.0, "medium": 5.0, "large": 13.0}
DEFAULT_EFFORT = EFFORT_BUCKETS["medium"]

# Label vocabularies seen on real repos, mapped to a bucket.
LABEL_EFFORT: dict[str, str] = {
    "good first issue": "trivial", "good-first-issue": "trivial", "easy": "trivial",
    "trivial": "trivial", "typo": "trivial", "docs": "trivial",
    "small": "small", "minor": "small", "bug": "small", "chore": "small",
    "enhancement": "medium", "medium": "medium", "refactor": "medium",
    "epic": "large", "major": "large", "architecture": "large", "large": "large",
    "breaking-change": "large", "needs-design": "large",
}

QUARTER_CAPACITY_DAYS = 20.0   # a sane default sprint-ish capacity; caller overrides
PLAN_KEY = "backlog_plan"


# ── effort ──────────────────────────────────────────────────────────────


def _label_effort(labels: list[str] | None) -> tuple[float | None, str | None]:
    """Effort implied by issue labels, if any of them say anything about size."""
    for raw in labels or []:
        bucket = LABEL_EFFORT.get(str(raw).strip().lower())
        if bucket:
            return EFFORT_BUCKETS[bucket], f"label '{raw}'"
    return None, None


def historical_fix_days(session: Session, product_id: int | None) -> float | None:
    """How long this product's fixes have ACTUALLY taken, issue-open to confirmed.

    The most honest effort signal available: it is this team's own track record
    rather than an industry average.
    """
    stmt = select(FixWatch).where(FixWatch.status == "confirmed")
    if product_id is not None:
        stmt = stmt.where(FixWatch.product_id == product_id)
    spans = []
    for w in session.scalars(stmt).all():
        inv = session.get(Investigation, w.investigation_id)
        if inv is None or not inv.created_at or not w.fix_date:
            continue
        days = (aware_utc(w.fix_date) - aware_utc(inv.created_at)).days
        if 0 < days < 365:
            spans.append(float(days))
    return round(statistics.median(spans), 1) if spans else None


def estimate_effort(session: Session, finding: Finding,
                    product_id: int | None = None,
                    history: float | None = None) -> dict:
    """Effort for one backlog item, with its basis attached.

    Order of preference: what the linked issue's labels say, then what fixes on
    this product have historically taken, then nothing — and "nothing" is
    reported as unknown rather than filled with a default that would quietly
    reorder the backlog.
    """
    watch = session.scalars(select(FixWatch).where(
        FixWatch.finding_id == finding.id).order_by(FixWatch.id.desc())).first()
    if watch is not None:
        issue = session.scalars(select(Issue).where(
            Issue.ext_id == f"#{watch.issue_number}")).first()
        days, basis = _label_effort(issue.labels if issue else None)
        if days is not None:
            return {"days": days, "basis": basis, "known": True}

    if history is None:
        history = historical_fix_days(session, product_id)
    if history is not None:
        return {"days": history, "basis": f"median past fix took {history:.0f}d",
                "known": True}
    return {"days": DEFAULT_EFFORT, "basis": "no effort signal yet", "known": False}


# ── projected outcome ───────────────────────────────────────────────────


def rating_recovery(impact: dict, confidence: float) -> dict:
    """Rating stars this fix could plausibly return.

    Deliberately conservative and deliberately explained. `rating_impact` is the
    drop already observed on this theme; recovery assumes fixing it recovers the
    share of that drop the theme actually accounts for, discounted by how sure
    we are of the cause. A number a PM will quote in a planning meeting has to
    show its working or it should not be shown at all.
    """
    lost = float(impact.get("rating_impact") or 0.0)
    share = float(impact.get("affected_pct") or 0.0) / 100.0
    conf = max(0.0, min(1.0, float(confidence or 0.0)))
    if lost <= 0 or share <= 0:
        return {"stars": 0.0, "basis": "no measurable rating drop attributed to this theme",
                "confident": False}
    stars = round(lost * share * conf, 2)
    return {
        "stars": stars,
        "basis": (f"{lost:.2f}★ lost on this theme × {share:.0%} of negatives "
                  f"× {conf:.0%} confidence"),
        "confident": stars >= 0.05,
    }


# ── ranking ─────────────────────────────────────────────────────────────


def resolution_rate(session: Session, product_id: int | None) -> float:
    inv_stmt = select(Investigation).where(Investigation.status == "resolved")
    w_stmt = select(FixWatch).where(FixWatch.status == "confirmed")
    if product_id is not None:
        inv_stmt = inv_stmt.where(Investigation.product_id == product_id)
        w_stmt = w_stmt.where(FixWatch.product_id == product_id)
    resolved = len(session.scalars(inv_stmt).all())
    confirmed = len(session.scalars(w_stmt).all())
    return round(confirmed / resolved, 3) if resolved else 0.0


def backlog(session: Session, product_id: int | None = None,
            as_of: datetime | None = None) -> dict:
    """Every open problem, ranked, defended, with an effort estimate."""
    now = as_of or datetime.now(timezone.utc)
    rate = resolution_rate(session, product_id)
    history = historical_fix_days(session, product_id)

    w_stmt = select(FixWatch)
    if product_id is not None:
        w_stmt = w_stmt.where(FixWatch.product_id == product_id)
    watches = session.scalars(w_stmt).all()
    fixed = {w.investigation_id for w in watches if w.status == "confirmed"}

    inv_stmt = select(Investigation).where(Investigation.status == "resolved")
    if product_id is not None:
        inv_stmt = inv_stmt.where(Investigation.product_id == product_id)

    items = []
    for inv in session.scalars(inv_stmt).all():
        if inv.id in fixed:
            continue        # already verified fixed — not backlog
        finding = session.scalars(select(Finding).where(
            Finding.investigation_id == inv.id).order_by(Finding.id.desc())).first()
        if finding is None:
            continue
        fj = finding.json or {}
        impact = fj.get("impact", {}) or {}
        conf = float(finding.confidence or 0.0)
        sev = severity(conf, impact)
        volume = int(impact.get("affected_volume", 0) or 0)
        persistence = max(1, (now - (aware_utc(inv.created_at) or now)).days)

        # The stated formula: severity x volume x persistence x (1 - resolution).
        # (volume + 1) so a real severity signal isn't zeroed by a corpus that
        # hasn't accumulated matching reviews yet.
        score = sev["score"] * (volume + 1) * persistence * (1 - rate)

        effort = estimate_effort(session, finding, product_id, history)
        recovery = rating_recovery(impact, conf)
        evidence = [e.ref for e in session.scalars(select(EvidenceRow).where(
            EvidenceRow.investigation_id == inv.id)).all()]
        anomaly = session.get(AnomalyEvent, inv.anomaly_id) if inv.anomaly_id else None

        items.append({
            "investigation_id": inv.id,
            "finding_id": finding.id,
            "summary": finding.summary,
            "status": finding.status,
            "confidence": round(conf, 2),
            "severity": sev,
            "score": round(score, 2),
            "volume": volume,
            "persistence_days": persistence,
            "effort": effort,
            # impact-per-effort: the actual PM calculus, not impact alone
            "value_per_day": round(score / max(0.5, effort["days"]), 2),
            "projected": recovery,
            "evidence_refs": evidence,
            "evidence_count": len(evidence),
            "theme": (anomaly.metric if anomaly else None),
            "defence": _defence(sev, volume, persistence, rate, effort, recovery, len(evidence)),
        })

    by_value = sorted(items, key=lambda i: -i["value_per_day"])
    for rank, item in enumerate(by_value, start=1):
        item["rank"] = rank
    return {
        "items": by_value,
        "resolution_rate": rate,
        "median_fix_days": history,
        "generated": now.date().isoformat(),
        "unknown_effort": len([i for i in by_value if not i["effort"]["known"]]),
    }


def _defence(sev, volume, persistence, rate, effort, recovery, n_evidence) -> str:
    """The one line that justifies this item's place in the ranking."""
    bits = [f"{sev['band']} severity ({sev['score']:.2f})"]
    if volume:
        bits.append(f"{volume} affected reviews")
    bits.append(f"open {persistence}d")
    if recovery["confident"]:
        bits.append(f"~{recovery['stars']:.2f}★ recoverable")
    bits.append(f"{effort['days']:g}d effort ({effort['basis']})")
    bits.append(f"{n_evidence} cited evidence item(s)")
    return " · ".join(bits)


# ── the quarter plan (proposed, then owned by the PM) ───────────────────


def _plan_key(product_id: int | None) -> str:
    return f"{PLAN_KEY}:{product_id or '_'}"


def load_plan(session: Session, product_id: int | None) -> dict:
    row = session.get(Setting, _plan_key(product_id))
    value = row.value if row and isinstance(row.value, dict) else {}
    return {"included": list(value.get("included", [])),
            "excluded": list(value.get("excluded", [])),
            "notes": dict(value.get("notes", {})),
            "capacity_days": value.get("capacity_days", QUARTER_CAPACITY_DAYS),
            "owned": bool(value.get("owned", False)),
            "updated": value.get("updated")}


def save_plan(session: Session, product_id: int | None, *, included: list[int],
              excluded: list[int], notes: dict | None = None,
              capacity_days: float | None = None) -> dict:
    """Persist the PM's edits. Once saved the plan is theirs: a later re-rank
    proposes around their decisions rather than reversing them."""
    prior = load_plan(session, product_id)
    value = {
        "included": sorted(set(int(x) for x in included)),
        "excluded": sorted(set(int(x) for x in excluded)),
        "notes": {str(k): v for k, v in (notes or prior["notes"]).items()},
        "capacity_days": float(capacity_days if capacity_days is not None
                               else prior["capacity_days"]),
        "owned": True,
        "updated": datetime.now(timezone.utc).isoformat(),
    }
    key = _plan_key(product_id)
    row = session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value
    session.flush()
    return value


def quarter_plan(session: Session, product_id: int | None = None,
                 capacity_days: float | None = None,
                 as_of: datetime | None = None) -> dict:
    """A draft "what to fix next" that fits the capacity — the PM's to edit.

    Proposals fill capacity by value-per-day. Anything the PM has explicitly
    excluded stays out; anything they have explicitly included stays in even if
    the ranking would not have chosen it. That asymmetry is the point: the
    system proposes, the human disposes.
    """
    board = backlog(session, product_id, as_of)
    saved = load_plan(session, product_id)
    capacity = float(capacity_days if capacity_days is not None else saved["capacity_days"])

    by_id = {i["investigation_id"]: i for i in board["items"]}
    included_ids = [i for i in saved["included"] if i in by_id]
    excluded = set(saved["excluded"])

    chosen = [by_id[i] for i in included_ids]
    used = sum(i["effort"]["days"] for i in chosen)

    for item in board["items"]:
        iid = item["investigation_id"]
        if iid in excluded or iid in included_ids:
            continue
        cost = item["effort"]["days"]
        if used + cost > capacity:
            continue
        chosen.append(item)
        used += cost

    chosen_ids = {i["investigation_id"] for i in chosen}
    deferred = [i for i in board["items"] if i["investigation_id"] not in chosen_ids]

    return {
        "proposed": chosen,
        "deferred": deferred,
        "capacity_days": capacity,
        "committed_days": round(used, 1),
        "remaining_days": round(max(0.0, capacity - used), 1),
        "projected_stars": round(sum(i["projected"]["stars"] for i in chosen), 2),
        "owned": saved["owned"],
        "notes": saved["notes"],
        "resolution_rate": board["resolution_rate"],
        "median_fix_days": board["median_fix_days"],
        "unknown_effort": board["unknown_effort"],
        "generated": board["generated"],
    }
