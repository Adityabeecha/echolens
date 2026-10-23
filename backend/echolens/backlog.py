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

import math
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

# Age saturates rather than multiplying without limit. At this many days a
# problem has proven it is not self-resolving; beyond it, more age adds little.
PERSISTENCE_HALF_LIFE = 30.0

QUARTER_CAPACITY_DAYS = 20.0   # a sane default sprint-ish capacity; caller overrides
PLAN_KEY = "backlog_plan"

# ── PM overrides (set by a reviewer, persisted with the plan) ───────────
# Impact on a 1–5 scale. The measured default comes from the severity band; an
# override scales value by IMPACT_FACTOR[override] / IMPACT_FACTOR[default], so
# moving a "medium" (3) item to 5 makes it 4x as valuable, and back to 3 is a
# no-op. Doubling per step keeps the scale legible: each notch is "twice that".
IMPACT_FACTOR = {1: 0.25, 2: 0.5, 3: 1.0, 4: 2.0, 5: 4.0}
IMPACT_FROM_BAND = {"low": 2, "medium": 3, "high": 4}
EFFORT_OVERRIDE_RANGE = (0.5, 365.0)

# A manual priority segment. EchoLens has no data on who pays or where in the
# funnel a complaint sits, so the PM says so and value is multiplied by a fixed,
# documented factor. One segment per item — they do not stack, so a single
# item cannot be inflated 4x by ticking every box.
PRIORITY_SEGMENTS: dict[str, dict] = {
    "paying_users": {
        "label": "Affects paying users", "factor": 2.0,
        "why": "Set by you: hurts revenue directly, so value counts double (x2).",
    },
    "checkout_onboarding": {
        "label": "Affects checkout/onboarding", "factor": 1.5,
        "why": "Set by you: blocks the path to activation or purchase, so value counts x1.5.",
    },
}


def clean_overrides(raw: dict | None) -> dict[str, dict]:
    """Validate PM overrides into {"<investigation_id>": {effort_days, impact,
    segment}}. Unknown keys, out-of-range values and empty entries are dropped
    rather than stored, so a bad client can never poison the ranking."""
    out: dict[str, dict] = {}
    for key, val in (raw or {}).items():
        try:
            iid = str(int(key))
        except (TypeError, ValueError):
            continue
        if not isinstance(val, dict):
            continue
        entry: dict = {}
        days = val.get("effort_days")
        if days is not None:
            try:
                d = float(days)
                lo, hi = EFFORT_OVERRIDE_RANGE
                if lo <= d <= hi:
                    entry["effort_days"] = round(d, 1)
            except (TypeError, ValueError):
                pass
        impact = val.get("impact")
        if impact is not None:
            try:
                lvl = int(impact)
                if lvl in IMPACT_FACTOR:
                    entry["impact"] = lvl
            except (TypeError, ValueError):
                pass
        seg = val.get("segment")
        if seg in PRIORITY_SEGMENTS:
            entry["segment"] = seg
        if entry:
            out[iid] = entry
    return out


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
        # ext_id is repo-qualified ("owner/repo#123"), so match on the suffix —
        # a bare "#123" lookup silently found nothing and every item fell
        # through to "effort unknown".
        issue = session.scalars(select(Issue).where(
            Issue.ext_id.like(f"%#{watch.issue_number}"))).first()
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
    """Share of resolved cases that ended in a verified fix, in [0, 1].

    Counted over DISTINCT investigations, not FixWatch rows. One case can carry
    several watches (link_issue dedupes on (repo, issue_number), not on
    finding_id, and two endpoints can each file an issue for the same finding),
    so the raw watch count could exceed the number of resolved cases and push
    this above 1.0. That made `1 - rate` negative, which flipped the sign of
    every score below and sorted the WORST problems last — the highest-severity,
    longest-open items were systematically excluded from the quarter plan.
    Clamped as a second line of defence.
    """
    inv_stmt = select(Investigation).where(Investigation.status == "resolved")
    w_stmt = select(FixWatch).where(FixWatch.status == "confirmed")
    if product_id is not None:
        inv_stmt = inv_stmt.where(Investigation.product_id == product_id)
        w_stmt = w_stmt.where(FixWatch.product_id == product_id)
    resolved_ids = {i.id for i in session.scalars(inv_stmt).all()}
    if not resolved_ids:
        return 0.0
    confirmed_ids = {w.investigation_id for w in session.scalars(w_stmt).all()
                     if w.investigation_id in resolved_ids}
    return round(min(1.0, len(confirmed_ids) / len(resolved_ids)), 3)


def backlog(session: Session, product_id: int | None = None,
            as_of: datetime | None = None) -> dict:
    """Every open problem, ranked, defended, with an effort estimate."""
    now = as_of or datetime.now(timezone.utc)
    rate = resolution_rate(session, product_id)
    history = historical_fix_days(session, product_id)
    overrides = load_plan(session, product_id)["overrides"]

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
        age_days = max(1, (now - (aware_utc(inv.created_at) or now)).days)
        # Persistence SATURATES. As a raw multiplier it dominated everything: a
        # 730-day-old trivial case outscored a 1-day-old critical one by ~730x
        # regardless of severity or volume. Age is evidence that a problem is
        # not self-resolving, and that evidence stops accumulating — a two-year
        # -old problem is not twice as urgent as a one-year-old one.
        persistence = 1.0 + math.log1p(age_days / PERSISTENCE_HALF_LIFE)

        # The stated formula: severity x volume x persistence x (1 - resolution).
        # (volume + 1) so a real severity signal isn't zeroed by a corpus that
        # hasn't accumulated matching reviews yet.
        score = sev["score"] * (volume + 1) * persistence * (1 - rate)

        effort = estimate_effort(session, finding, product_id, history)
        ov = overrides.get(str(inv.id), {})
        if "effort_days" in ov:
            # The PM's number wins and counts as known: dividing by it is the
            # whole point of supplying it. The estimate stays visible beside it.
            effort = {"days": ov["effort_days"], "basis": "set by you", "known": True,
                      "overridden": True, "estimated": effort}
        else:
            effort = {**effort, "overridden": False}
        default_level = IMPACT_FROM_BAND.get(sev["band"], 3)
        level = ov.get("impact", default_level)
        impact_factor = IMPACT_FACTOR[level] / IMPACT_FACTOR[default_level]
        seg_key = ov.get("segment")
        seg = PRIORITY_SEGMENTS.get(seg_key) if seg_key else None
        seg_factor = seg["factor"] if seg else 1.0
        value = score * impact_factor * seg_factor
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
            "persistence_days": age_days,
            "effort": effort,
            # Impact-per-effort: the actual PM calculus. When effort is UNKNOWN
            # we rank on impact alone rather than dividing by DEFAULT_EFFORT —
            # the docstring always promised that, but the default was applied
            # unconditionally and silently reordered the backlog on a number
            # nobody supplied.
            # Impact and segment overrides scale the score before the division.
            "value_per_day": round(
                value / max(0.5, effort["days"]) if effort.get("known") else value, 2),
            "impact": {"level": level, "default": default_level,
                       "overridden": "impact" in ov, "factor": round(impact_factor, 3)},
            "segment": ({"key": seg_key, "label": seg["label"], "factor": seg["factor"],
                         "why": seg["why"]} if seg else None),
            "projected": recovery,
            "evidence_refs": evidence,
            "evidence_count": len(evidence),
            "theme": (anomaly.metric if anomaly else None),
            "defence": _defence(sev, volume, persistence, rate, effort, recovery, len(evidence),
                                impact_factor if "impact" in ov else None, seg),
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


def _defence(sev, volume, persistence, rate, effort, recovery, n_evidence,
             impact_factor: float | None = None, segment: dict | None = None) -> str:
    """The one line that justifies this item's place in the ranking. Anything a
    PM overrode is named as theirs, so the arithmetic stays auditable."""
    bits = [f"{sev['band']} severity ({sev['score']:.2f})"]
    if volume:
        bits.append(f"{volume} affected reviews")
    bits.append(f"open {persistence}d")
    if recovery["confident"]:
        bits.append(f"~{recovery['stars']:.2f}★ recoverable")
    bits.append(f"{effort['days']:g}d effort ({effort['basis']})")
    if impact_factor is not None:
        bits.append(f"impact x{impact_factor:g} (set by you)")
    if segment:
        bits.append(f"x{segment['factor']:g} {segment['label'].lower()} (set by you)")
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
            "overrides": clean_overrides(value.get("overrides")),
            "capacity_days": value.get("capacity_days", QUARTER_CAPACITY_DAYS),
            "owned": bool(value.get("owned", False)),
            "updated": value.get("updated")}


def save_plan(session: Session, product_id: int | None, *, included: list[int],
              excluded: list[int], notes: dict | None = None,
              capacity_days: float | None = None,
              overrides: dict | None = None) -> dict:
    """Persist the PM's edits. Once saved the plan is theirs: a later re-rank
    proposes around their decisions rather than reversing them.

    `overrides` follows the same rule as `notes`: omitted (None) keeps what was
    saved, so a plain include/exclude save never wipes the PM's estimates; a
    dict replaces them wholesale (send {} to clear)."""
    prior = load_plan(session, product_id)
    value = {
        "included": sorted(set(int(x) for x in included)),
        "excluded": sorted(set(int(x) for x in excluded)),
        "notes": {str(k): v for k, v in (notes if notes is not None else prior["notes"]).items()},
        "overrides": (clean_overrides(overrides) if overrides is not None
                      else prior["overrides"]),
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
        "included": saved["included"],
        "excluded": saved["excluded"],
        "capacity_days": capacity,
        "committed_days": round(used, 1),
        "remaining_days": round(max(0.0, capacity - used), 1),
        "projected_stars": round(sum(i["projected"]["stars"] for i in chosen), 2),
        "owned": saved["owned"],
        "notes": saved["notes"],
        "overrides": saved["overrides"],
        # What the override controls mean, so the UI never hardcodes a factor.
        "segments": [{"key": k, **v} for k, v in PRIORITY_SEGMENTS.items()],
        "impact_scale": {str(k): v for k, v in IMPACT_FACTOR.items()},
        "resolution_rate": board["resolution_rate"],
        "median_fix_days": board["median_fix_days"],
        "unknown_effort": board["unknown_effort"],
        "generated": board["generated"],
    }
