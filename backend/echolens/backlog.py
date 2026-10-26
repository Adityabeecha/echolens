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

v16: the plan also covers what users ASK for. Feature-request themes
(themes/requests.py) become plan items keyed by their public slug, ranked by
demand per engineer-day, with the same effort/impact/segment overrides as bugs.
"""
from __future__ import annotations

import math
import re
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


# ── feature requests on the plan ────────────────────────────────────────
# A request item is keyed by the slug /feed/candidates already gives it, so the
# plan, the overrides and the Cases screen all name the same thing.
REQUEST_KEY_RE = re.compile(r"^request-p\d+-[a-z0-9-]{1,48}$")
PLAN_KINDS = ("bugs", "requests", "all")
REQUEST_LIMIT = 8
# Demand = distinct requesting reviews + HAPPY_WEIGHT per 4-5★ requester. A
# happy user asking for something is telling you what keeps them; a 3★ asker
# is already lukewarm. Half a review extra, not double: the count still leads.
HAPPY_WEIGHT = 0.5
REQUEST_IMPACT_DEFAULT = 3


def plan_key(raw) -> int | str | None:
    """A plan item id: an investigation id (int) or a request slug (str)."""
    if isinstance(raw, str) and REQUEST_KEY_RE.match(raw):
        return raw
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _clean_keys(raw) -> list[int | str]:
    keys = {k for k in (plan_key(x) for x in raw or []) if k is not None}
    return (sorted(k for k in keys if isinstance(k, int))
            + sorted(k for k in keys if isinstance(k, str)))


def clean_overrides(raw: dict | None) -> dict[str, dict]:
    """Validate PM overrides into {"<investigation_id or request slug>":
    {effort_days, impact, segment}}. Unknown keys, out-of-range values and empty
    entries are dropped rather than stored, so a bad client can never poison
    the ranking."""
    out: dict[str, dict] = {}
    for key, val in (raw or {}).items():
        k = plan_key(key)
        if k is None:
            continue
        iid = str(k)
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
    watches = session.scalars(stmt).all()
    ids = list({w.investigation_id for w in watches})
    invs = {i.id: i for i in session.scalars(select(Investigation).where(
        Investigation.id.in_(ids))).all()} if ids else {}   # one query, not one per fix
    for w in watches:
        inv = invs.get(w.investigation_id)
        if inv is None or not inv.created_at or not w.fix_date:
            continue
        days = (aware_utc(w.fix_date) - aware_utc(inv.created_at)).days
        if 0 < days < 365:
            spans.append(float(days))
    return round(statistics.median(spans), 1) if spans else None


def history_bucket(calendar_days: float) -> str:
    """Coarse size from how long past fixes took end to end. Elapsed time runs
    several times the hands-on work, so the thresholds sit well above the
    bucket sizes themselves."""
    if calendar_days <= 3:
        return "trivial"
    if calendar_days <= 10:
        return "small"
    if calendar_days <= 30:
        return "medium"
    return "large"


_UNSET = object()


def estimate_effort(session: Session, finding: Finding,
                    product_id: int | None = None,
                    history: float | None = None, watch=_UNSET, issue=_UNSET) -> dict:
    """Effort for one backlog item, with its basis attached.

    Order of preference: what the linked issue's labels say, then what fixes on
    this product have historically taken, then nothing — and "nothing" is
    reported as unknown rather than filled with a default that would quietly
    reorder the backlog.
    """
    if watch is _UNSET:      # a list caller passes the watch it already loaded
        watch = session.scalars(select(FixWatch).where(
            FixWatch.finding_id == finding.id).order_by(FixWatch.id.desc())).first()
    if watch is not None:
        # ext_id is repo-qualified ("owner/repo#123"), so match on the suffix —
        # a bare "#123" lookup silently found nothing and every item fell
        # through to "effort unknown".
        if issue is _UNSET:
            issue = session.scalars(select(Issue).where(
                Issue.ext_id.like(f"%#{watch.issue_number}"))).first()
        days, basis = _label_effort(issue.labels if issue else None)
        if days is not None:
            return {"days": days, "basis": basis, "known": True}

    if history is None:
        history = historical_fix_days(session, product_id)
    if history is not None:
        # The track record is CALENDAR time from case to shipped fix — queues,
        # reviews and release trains included — not engineer-days. Used as days
        # it made every item bigger than a sprint, so nothing ever fit the plan.
        # It is a size signal instead: the same coarse buckets labels map to.
        bucket = history_bucket(history)
        return {"days": EFFORT_BUCKETS[bucket],
                "basis": f"median past fix took {history:.0f}d end to end — sized as {bucket}",
                "known": True}
    return {"days": DEFAULT_EFFORT, "basis": "no effort signal yet", "known": False}


# ── projected outcome ───────────────────────────────────────────────────


def rating_recovery(impact: dict, confidence: float) -> dict:
    """Further drift this fix could plausibly prevent in a 30-day rolling rating.

    Deliberately conservative and deliberately explained. `rating_impact` is the
    drop already observed on this theme; prevention estimates the
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
        "basis": (f"Prevents about {stars:.2f}★ of further drift (30-day rolling rating): "
                  f"{lost:.2f}★ lost (observed drop) × {share:.0%} of negatives "
                  f"× {conf:.0%} confidence. Assumes future complaints fall after the fix; "
                  "existing low ratings remain until they age out of the window."),
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


def _plan_round(value: float, digits: int) -> float:
    """Nonnegative ranking values round half up, matching the local JS preview."""
    factor = 10 ** digits
    return math.floor(value * factor + 0.5) / factor


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

    from echolens.review import decision_dict, decision_hides, latest_decisions

    # Everything per case loaded once for the whole list: this ran five
    # queries PER resolved case (finding, decision, watch, evidence, anomaly),
    # so Plan's statement count grew with the case count.
    invs = [i for i in session.scalars(inv_stmt).all() if i.id not in fixed]
    inv_ids = [i.id for i in invs]
    latest: dict[int, Finding] = {}
    refs: dict[int, list[str]] = {}
    anomalies: dict[int, AnomalyEvent] = {}
    if inv_ids:
        for f in session.scalars(select(Finding).where(
                Finding.investigation_id.in_(inv_ids)).order_by(Finding.id)).all():
            latest[f.investigation_id] = f            # ascending: newest wins
        for inv_id, ref in session.execute(select(EvidenceRow.investigation_id, EvidenceRow.ref)
                                           .where(EvidenceRow.investigation_id.in_(inv_ids))
                                           .order_by(EvidenceRow.id)).all():
            refs.setdefault(inv_id, []).append(ref)
        a_ids = [i.anomaly_id for i in invs if i.anomaly_id]
        if a_ids:
            anomalies = {a.id: a for a in session.scalars(select(AnomalyEvent).where(
                AnomalyEvent.id.in_(a_ids))).all()}
    finding_ids = [f.id for f in latest.values()]
    decisions = latest_decisions(session, finding_ids)
    watch_of: dict[int, FixWatch] = {}
    if finding_ids:
        for w in session.scalars(select(FixWatch).where(
                FixWatch.finding_id.in_(finding_ids)).order_by(FixWatch.id)).all():
            watch_of[w.finding_id] = w                # ascending: newest wins
    # The linked issues' labels, for effort — one query for every watch.
    issue_of: dict[int, Issue] = {}
    numbers = sorted({w.issue_number for w in watch_of.values() if w.issue_number is not None})
    if numbers:
        from sqlalchemy import or_
        for issue in session.scalars(select(Issue).where(
                or_(*[Issue.ext_id.like(f"%#{n}") for n in numbers])).order_by(Issue.id)).all():
            tail = issue.ext_id.rsplit("#", 1)[-1]
            if tail.isdigit():
                issue_of.setdefault(int(tail), issue)  # first match, as .first() did

    items = []
    set_aside = []
    for inv in invs:
        finding = latest.get(inv.id)
        if finding is None:
            continue
        # v15: the product decision outranks the ranking. Won't-fix leaves the
        # backlog for good; parked leaves it until its revisit date. Both are
        # reported back (not silently dropped) so the plan can say what it is
        # NOT proposing and why.
        decision = decisions.get(finding.id)      # `cleared` already counts as none
        if decision_hides(decision, now):
            set_aside.append({"investigation_id": inv.id, "finding_id": finding.id,
                              "summary": finding.summary,
                              "decision": decision_dict(decision, now)})
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

        watch = watch_of.get(finding.id)
        effort = estimate_effort(session, finding, product_id, history, watch=watch,
                                 issue=issue_of.get(watch.issue_number) if watch else None)
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
        evidence = refs.get(inv.id, [])
        anomaly = anomalies.get(inv.anomaly_id) if inv.anomaly_id else None

        items.append({
            "kind": "bug",
            "key": inv.id,
            "investigation_id": inv.id,
            "finding_id": finding.id,
            "summary": finding.summary,
            "status": finding.status,
            "confidence": round(conf, 2),
            "support_level": (finding.json or {}).get("support_level"),
            "needs_review": bool((finding.json or {}).get("needs_review")),
            "severity": sev,
            "score": round(score, 2),
            # Preserve the arithmetic input; rounded display scores cannot be
            # inverted accurately when the PM previews a different priority.
            "base_value": score,
            "tie_order": inv.id,
            "volume": volume,
            "persistence_days": age_days,
            "effort": effort,
            # Impact-per-effort: the actual PM calculus. When effort is UNKNOWN
            # we rank on impact alone rather than dividing by DEFAULT_EFFORT —
            # the docstring always promised that, but the default was applied
            # unconditionally and silently reordered the backlog on a number
            # nobody supplied.
            # Impact and segment overrides scale the score before the division.
            "value_per_day": _plan_round(
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
            "decision": decision_dict(decision, now),
        })

    by_value = sorted(items, key=lambda i: (-i["value_per_day"], i["tie_order"]))
    for rank, item in enumerate(by_value, start=1):
        item["rank"] = rank
    return {
        "items": by_value,
        "set_aside": set_aside,
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
        bits.append(f"prevents about {recovery['stars']:.2f}★ of further drift (30-day rolling rating)")
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
    return {"included": _clean_keys(value.get("included", [])),
            "excluded": _clean_keys(value.get("excluded", [])),
            "notes": dict(value.get("notes", {})),
            "overrides": clean_overrides(value.get("overrides")),
            "capacity_days": value.get("capacity_days", QUARTER_CAPACITY_DAYS),
            "owned": bool(value.get("owned", False)),
            "selected": _clean_keys(value.get("selected", value.get("included", []))),
            "saved_kind": value.get("saved_kind"),
            "updated": value.get("updated")}


def save_plan(session: Session, product_id: int | None, *, included: list[int | str],
              excluded: list[int | str], notes: dict | None = None,
              capacity_days: float | None = None,
              overrides: dict | None = None, kind: str = "bugs") -> dict:
    """Persist the PM's edits. Once saved the plan is theirs: a later re-rank
    proposes around their decisions rather than reversing them.

    `overrides` follows the same rule as `notes`: omitted (None) keeps what was
    saved, so a plain include/exclude save never wipes the PM's estimates; a
    dict replaces them wholesale (send {} to clear)."""
    prior = load_plan(session, product_id)
    value = {
        "included": _clean_keys(included),
        "excluded": _clean_keys(excluded),
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
    # Freeze this view's actual selection at Save. Re-ranking before export
    # could otherwise send a newly detected problem the reviewer never chose.
    value = {**value, "selected": [i["key"] for i in quarter_plan(
        session, product_id, kind=kind)["proposed"]], "saved_kind": kind}
    row = session.get(Setting, key)
    row.value = value
    session.flush()
    return value


def request_themes(session: Session, product_id: int | None,
                   as_of: datetime | None = None) -> list[dict]:
    """This product's request themes with their member reviews.

    The same grouping /feed/candidates runs (themes/requests.py), re-derived
    rather than read from its cache because the plan needs every member review
    — distinct requesters and their ratings are the demand — and the cache
    keeps only three quotes. Names are the deterministic phrase plus anyone's
    rename; merges pool their reviews and mutes drop out, as on Cases.
    """
    from echolens.db.models import Product
    from echolens.detector.detect import reference_now
    from echolens.themes.discover import WINDOW_DAYS, banned_terms
    from echolens.themes.overrides import _resolve, get_overrides
    from echolens.themes.requests import _candidates, _slug, _statement, group_requests

    prod = session.get(Product, product_id) if product_id is not None else None
    if prod is None:
        return []
    import copy
    from datetime import timedelta

    from echolens.memo import fingerprinted, review_fingerprint

    now = as_of or reference_now(session, prod.name)

    def compute() -> list[dict]:
        rows = _candidates(session, prod.name, WINDOW_DAYS, now)
        groups = group_requests([r.text or "" for r in rows],
                                banned_terms(prod.name, prod.package_name))[:REQUEST_LIMIT]
        out: list[dict] = []
        for i, g in enumerate(groups):
            reviews = []
            for m in g["members"]:
                r = rows[m]
                day = aware_utc(r.created_at)
                reviews.append({"id": r.id, "ext_id": r.ext_id, "source": r.source,
                                "rating": r.rating, "text": " ".join((r.text or "").split()),
                                "date": day.date().isoformat() if day else None})
            out.append({"slug": f"request-p{prod.id}-{_slug(g['phrase']) or f'request-{i + 1}'}",
                        "phrase": g["phrase"], "statement": _statement(g["phrase"]),
                        "reviews": reviews})
        return out

    # Classifying every 3-5 star review in the window ran on each Plan load (and
    # on each Drop/Add, which re-renders the plan). Recomputed now only when
    # those reviews change; overrides below are applied fresh every time.
    since = (now - timedelta(days=WINDOW_DAYS)).replace(tzinfo=None)
    themes = copy.deepcopy(fingerprinted(
        session, ("request_themes", prod.id, str(now)),
        (review_fingerprint(session, prod.name, since, min_rating=3), prod.package_name),
        compute))

    overrides = get_overrides(session, prod.id)
    by_slug = {t["slug"]: t for t in themes}
    for t in themes:
        o = overrides.get(t["slug"])
        if o is not None and o.label:
            t["statement"], t["renamed"] = o.label, True
    dropped: set[str] = set()
    for t in themes:
        target = by_slug.get(_resolve(t["slug"], overrides))
        if target is None or target is t:
            continue
        seen = {r["id"] for r in target["reviews"]}
        target["reviews"] += [r for r in t["reviews"] if r["id"] not in seen]
        dropped.add(t["slug"])
    muted = {s for s, o in overrides.items() if o.muted}
    return [t for t in themes if t["slug"] not in dropped and t["slug"] not in muted
            and _resolve(t["slug"], overrides) not in muted]


def request_demand(reviews: list[dict]) -> dict:
    """Distinct requesting reviews, how many of them are 4-5★, and the weighted
    demand those make."""
    n = len({r["id"] for r in reviews})
    happy = len({r["id"] for r in reviews if (r.get("rating") or 0) >= 4})
    return {"requesters": n, "happy": happy, "value": n + HAPPY_WEIGHT * happy}


def request_items(session: Session, product_id: int | None, overrides: dict,
                  as_of: datetime | None = None) -> list[dict]:
    """Request themes as plan items, ranked by demand per engineer-day.

    Effort works exactly as for bugs: EchoLens has no signal for how big a
    feature is, so it is DEFAULT_EFFORT marked unknown until a reviewer sets it.
    Unlike bugs the division always happens — the plan says "demand per
    engineer-day", and every unknown request divides by the same default, so
    their relative order is unchanged by it.
    """
    from echolens.intent import count_intents

    items = []
    themes = sorted(request_themes(session, product_id, as_of), key=lambda t: t["slug"])
    for tie_order, t in enumerate(themes, start=1):
        reviews = t["reviews"]
        demand = request_demand(reviews)
        ov = overrides.get(t["slug"], {})
        effort = {"days": DEFAULT_EFFORT, "basis": "no effort signal yet", "known": False}
        if "effort_days" in ov:
            effort = {"days": ov["effort_days"], "basis": "set by you", "known": True,
                      "overridden": True, "estimated": effort}
        else:
            effort = {**effort, "overridden": False}
        level = ov.get("impact", REQUEST_IMPACT_DEFAULT)
        impact_factor = IMPACT_FACTOR[level] / IMPACT_FACTOR[REQUEST_IMPACT_DEFAULT]
        seg_key = ov.get("segment")
        seg = PRIORITY_SEGMENTS.get(seg_key) if seg_key else None
        seg_factor = seg["factor"] if seg else 1.0
        value = demand["value"] * impact_factor * seg_factor
        ratings = [r["rating"] for r in reviews if r.get("rating")]
        quotes: list[str] = []
        for r in reviews:
            if r["text"] and not any(r["text"][:60].lower() == q[:60].lower() for q in quotes):
                quotes.append(r["text"])
            if len(quotes) >= 2:
                break
        dates = sorted(r["date"] for r in reviews if r.get("date"))
        items.append({
            "kind": "request",
            "key": t["slug"],
            "slug": t["slug"],
            "summary": t["statement"],
            "phrase": t["phrase"],
            "count": demand["requesters"],
            "happy_count": demand["happy"],
            "demand": round(demand["value"], 2),
            "base_value": demand["value"],
            "tie_order": tie_order,
            "avg_rating": round(sum(ratings) / len(ratings), 1) if ratings else None,
            "verbatims": quotes,
            "intents": count_intents((r["text"], r["rating"]) for r in reviews),
            "first_seen": dates[0] if dates else None,
            "last_seen": dates[-1] if dates else None,
            "effort": effort,
            "value_per_day": _plan_round(value / max(0.5, effort["days"]), 2),
            "impact": {"level": level, "default": REQUEST_IMPACT_DEFAULT,
                       "overridden": "impact" in ov, "factor": round(impact_factor, 3)},
            "segment": ({"key": seg_key, "label": seg["label"], "factor": seg["factor"],
                         "why": seg["why"]} if seg else None),
            # Nothing measured to recover: a wish is not a rating drop.
            "projected": {"stars": 0.0, "basis": "a request has no measured rating drop",
                          "confident": False},
            "defence": _request_defence(demand, effort, impact_factor if "impact" in ov else None,
                                        seg),
        })
    items.sort(key=lambda i: (-i["value_per_day"], i["tie_order"]))
    for rank, item in enumerate(items, start=1):
        item["rank"] = rank
    return items


def _request_defence(demand: dict, effort: dict, impact_factor: float | None,
                     segment: dict | None) -> str:
    bits = [f"{demand['requesters']} requesting review(s)"]
    if demand["happy"]:
        bits.append(f"+{HAPPY_WEIGHT:g} each for {demand['happy']} at 4-5★")
    bits.append(f"{effort['days']:g}d effort ({effort['basis']})")
    if impact_factor is not None:
        bits.append(f"impact x{impact_factor:g} (set by you)")
    if segment:
        bits.append(f"x{segment['factor']:g} {segment['label'].lower()} (set by you)")
    return " · ".join(bits)


def _rank_mixed(bugs: list[dict], requests: list[dict]) -> list[dict]:
    """One list from two scales. Bug value (severity x volume x age) and request
    demand (requesting reviews) are different units, so each is expressed as a
    share of its own kind's best item before they are interleaved. Ties go to
    the bug: a broken thing outranks an equally-wanted new one."""
    def rel(items):
        top = max((i["value_per_day"] for i in items), default=0.0) or 1.0
        return [{**i, "relative_value": _plan_round(i["value_per_day"] / top, 3)} for i in items]
    merged = sorted(rel(bugs) + rel(requests),
                    key=lambda i: (-i["relative_value"], i["kind"] != "bug",
                                   -i["value_per_day"], i["tie_order"]))
    for rank, item in enumerate(merged, start=1):
        item["rank"] = rank
    return merged


def quarter_plan(session: Session, product_id: int | None = None,
                 capacity_days: float | None = None,
                 as_of: datetime | None = None, kind: str = "bugs") -> dict:
    """A draft "what to fix next" that fits the capacity — the PM's to edit.

    Proposals fill capacity by value-per-day. Anything the PM has explicitly
    excluded stays out; anything they have explicitly included stays in even if
    the ranking would not have chosen it. That asymmetry is the point: the
    system proposes, the human disposes.

    `kind` picks what competes for the capacity: bug findings (the default and
    the original plan), request themes, or both. The saved picks are shared;
    a pick of the other kind is simply not in play in this view.
    """
    if kind not in PLAN_KINDS:
        kind = "bugs"
    board = backlog(session, product_id, as_of)
    saved = load_plan(session, product_id)
    capacity = float(capacity_days if capacity_days is not None else saved["capacity_days"])
    requests = request_items(session, product_id, saved["overrides"])

    if kind == "bugs":
        items = board["items"]
    elif kind == "requests":
        items = requests
    else:
        items = _rank_mixed(board["items"], requests)

    by_id = {i["key"]: i for i in items}
    excluded = set(saved["excluded"])
    # v15: a "fix now" product decision is an inclusion made on the case
    # itself; it goes in first, after the PM's own picks, unless excluded here.
    fix_now = [i["key"] for i in items
               if (i.get("decision") or {}).get("decision") == "fix_now"
               and i["key"] not in excluded]
    included_ids = [i for i in saved["included"] if i in by_id]
    included_ids += [i for i in fix_now if i not in included_ids]

    chosen = [by_id[i] for i in included_ids]
    used = sum(i["effort"]["days"] for i in chosen)

    for item in items:
        iid = item["key"]
        if iid in excluded or iid in included_ids:
            continue
        cost = item["effort"]["days"]
        if used + cost > capacity:
            continue
        chosen.append(item)
        used += cost

    chosen_ids = {i["key"] for i in chosen}
    deferred = [i for i in items if i["key"] not in chosen_ids]

    return {
        "kind": kind,
        "kinds": list(PLAN_KINDS),
        "counts": {"bugs": len(board["items"]), "requests": len(requests)},
        "proposed": chosen,
        "deferred": deferred,
        "set_aside": board["set_aside"] if kind != "requests" else [],
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
        "request_weight": {"happy": HAPPY_WEIGHT,
                           "why": f"Each requesting review counts 1, plus {HAPPY_WEIGHT:g} "
                                  "if it rates the app 4-5★."},
        "resolution_rate": board["resolution_rate"],
        "median_fix_days": board["median_fix_days"],
        "unknown_effort": len([i for i in items if not i["effort"]["known"]]),
        "generated": board["generated"],
    }


def export_plan(session: Session, product_id: int, tracker: str, *, kind: str = "bugs",
                repo: str | None = None, post_fn=None) -> dict:
    """File only the saved selection, journaling each write before remote IO.

    Successes survive later failures. Pending/uncertain writes are held for
    inspection because the trackers offer no shared idempotency API; a lost
    response is not permission to create the same issue twice.
    """
    from sqlalchemy import update
    from sqlalchemy.exc import IntegrityError
    from echolens.config import settings
    from echolens.db.models import PlanExport, Product
    from echolens.exporting import finding_ticket, request_ticket
    from echolens.integrations.trackers import TRACKERS, configured_trackers, create_ticket, TrackerError
    from echolens.prd import build_spec, find_request

    if tracker not in TRACKERS or kind not in PLAN_KINDS:
        raise ValueError("Choose github, linear or jira and bugs, requests or all")
    saved = load_plan(session, product_id)
    if not saved["owned"]:
        raise ValueError("Save the plan before sending it to a tracker")
    if saved["saved_kind"] is not None and saved["saved_kind"] != kind:
        raise ValueError("Save this plan view before sending it to a tracker")
    if not configured_trackers()[tracker]:
        raise ValueError(f"{tracker.capitalize()} is not configured on this deployment")
    if tracker == "github" and not repo:
        raise ValueError("No GitHub repo connected")
    product = session.get(Product, product_id)
    if product is None:
        raise ValueError("No such product")
    destination = (repo if tracker == "github" else settings.linear_team_id if tracker == "linear"
                   else f"{settings.jira_base_url.rstrip('/')}/{settings.jira_project_key}")
    results = []
    for key in saved["selected"]:
        is_request = isinstance(key, str)
        if (kind == "bugs" and is_request) or (kind == "requests" and not is_request):
            continue
        finding = None
        if is_request:
            theme = find_request(session, product_id, key)
            ticket = request_ticket(build_spec(theme, product.name)) if theme else None
        else:
            inv = session.scalar(select(Investigation).where(
                Investigation.id == key, Investigation.product_id == product_id))
            finding = session.scalar(select(Finding).where(Finding.investigation_id == key,
                Finding.product_id == product_id).order_by(Finding.id.desc())) if inv else None
            ticket = finding_ticket(session, finding, repo=repo) if finding else None
        result = {"key": key, "title": ticket["title"] if ticket else str(key),
                  "status": "failed", "url": None}
        results.append(result)
        if ticket is None:
            result["error"] = "This saved item is no longer available in this product"
            continue
        if tracker == "github" and finding is not None:
            watch = session.scalar(select(FixWatch).where(
                FixWatch.investigation_id == finding.investigation_id,
                FixWatch.product_id == product_id, FixWatch.repo == repo,
                FixWatch.issue_number > 0).order_by(FixWatch.id.desc()))
            if watch is not None:
                result.update(status="existing", url=watch.issue_url or None)
                continue
        query = select(PlanExport).where(PlanExport.product_id == product_id,
            PlanExport.tracker == tracker, PlanExport.destination == destination,
            PlanExport.item_key == str(key))
        record = session.scalar(query)
        if record is not None:
            if record.status == "created":
                result.update(status="existing", url=record.url)
                continue
            if record.status != "failed":
                result["error"] = "An earlier send may have created this issue. Check the tracker before retrying."
                continue
            claimed = session.execute(update(PlanExport).where(
                PlanExport.id == record.id, PlanExport.status == "failed")
                .values(status="pending"))
            if claimed.rowcount != 1:
                session.rollback()
                result["error"] = "Another send is already handling this item. Refresh and try again."
                continue
        else:
            record = PlanExport(product_id=product_id, tracker=tracker,
                                destination=destination, item_key=str(key))
            session.add(record)
        try:
            session.commit()  # durable claim, including uniqueness across workers
        except IntegrityError:
            session.rollback()
            result["error"] = "Another send is already handling this item. Refresh and try again."
            continue
        try:
            issue = create_ticket(tracker, ticket["title"], ticket["body"],
                                  repo=repo, post_fn=post_fn)
            if not issue.get("number") or not issue.get("url"):
                raise RuntimeError("Tracker response did not identify the created issue")
        except Exception as error:
            # Only explicit client rejections are known not to have written.
            # 5xx, transport failures and malformed success responses are ambiguous.
            definite = isinstance(error, TrackerError) and bool(re.search(
                r"API 4\d\d\b", str(error)))
            record.status = "failed" if definite else "uncertain"
            session.commit()
            result["error"] = ("The tracker rejected this item. Correct the tracker settings and retry."
                if definite else "The tracker response was interrupted. Check the tracker before retrying.")
            continue
        record.status, record.url, record.number = "created", issue["url"], str(issue["number"])
        session.commit()  # persist remote identity before optional fix-watch linking
        result.update(status="created", url=record.url)
        if tracker == "github" and finding is not None:
            from echolens.fixwatch import link_issue
            link_issue(session, finding, repo, int(issue["number"]), issue["url"])
            session.commit()
    return {"tracker": tracker, "kind": kind, "results": results}
