"""The weekly brief (v7.0) — the artifact that keeps EchoLens open on Monday.

Five cited lines: new problems by impact, fixes verified, regressions, and ONE
"what to fix next" ranked by severity × volume × persistence × (1 − resolution
rate). Every claim points at a case. Sent unprompted by the scheduled job.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import AnomalyEvent, Finding, FixWatch, Investigation
from echolens.impact import severity
from echolens.timeutil import aware_utc


def _n(count: int, noun: str, plural: str | None = None) -> str:
    """"1 fix" / "3 fixes" — never "3 fix(es)". The brief is read by people."""
    return f"{count} {noun}" if count == 1 else f"{count} {plural or noun + 's'}"


def _recent(dt, since) -> bool:
    dt = aware_utc(dt)
    return dt is not None and dt >= since


def _load(session: Session, product_ids: list[int] | None, now) -> dict:
    """Everything a brief reads, for one or many products, in a fixed number of
    queries. `None` means the whole workspace, filed under the key None.

    The brief used to re-query resolved cases three times and watches three
    times per product, and the portfolio brief ran all of that once per product
    on top, so the page grew by ~10 statements for every product added.
    """
    from echolens.themes import theme_lifecycle, theme_lifecycles

    keys = [None] if product_ids is None else list(product_ids)
    data = {k: {"invs": [], "latest": {}, "watches": [], "regressions": [], "chronic": []}
            for k in keys}

    def key(pid):
        return None if product_ids is None else pid

    inv_stmt = select(Investigation).where(Investigation.status == "resolved")
    w_stmt = select(FixWatch)
    reg_stmt = select(AnomalyEvent).where(AnomalyEvent.type == "regression")
    if product_ids is not None:
        inv_stmt = inv_stmt.where(Investigation.product_id.in_(product_ids))
        w_stmt = w_stmt.where(FixWatch.product_id.in_(product_ids))
        reg_stmt = reg_stmt.where(AnomalyEvent.product_id.in_(product_ids))
    invs = session.scalars(inv_stmt).all()
    by_id = {}
    for inv in invs:
        data[key(inv.product_id)]["invs"].append(inv)
        by_id[inv.id] = inv
    if by_id:
        for finding in session.scalars(select(Finding).where(
                Finding.investigation_id.in_(list(by_id))).order_by(Finding.id)).all():
            inv = by_id[finding.investigation_id]
            data[key(inv.product_id)]["latest"][inv.id] = finding
    for w in session.scalars(w_stmt).all():
        data[key(w.product_id)]["watches"].append(w)
    for a in session.scalars(reg_stmt).all():
        data[key(a.product_id)]["regressions"].append(a)

    lifecycles = ({None: theme_lifecycle(session, now, None)} if product_ids is None
                  else theme_lifecycles(session, list(product_ids), now))
    for k, themes in lifecycles.items():
        data[k]["chronic"] = [t for t in themes if t["status"] == "chronic"]
    return data


def _resolution_rate(d: dict) -> float:
    """Same rule as backlog.resolution_rate — DISTINCT resolved cases with a
    confirmed fix, clamped to [0, 1] — computed from the rows already loaded
    instead of re-querying both tables per product."""
    resolved_ids = {inv.id for inv in d["invs"]}
    if not resolved_ids:
        return 0.0
    confirmed_ids = {w.investigation_id for w in d["watches"]
                     if w.status == "confirmed" and w.investigation_id in resolved_ids}
    return round(min(1.0, len(confirmed_ids) / len(resolved_ids)), 3)


def _fix_next(d: dict, resolution_rate: float, now) -> dict | None:
    """Rank open problems by severity × volume × persistence × (1 − resolution)."""
    confirmed = {w.investigation_id for w in d["watches"] if w.status == "confirmed"}
    best, best_score = None, -1.0
    for inv in d["invs"]:
        if inv.id in confirmed:
            continue
        f = d["latest"].get(inv.id)
        if f is None:
            continue
        impact = (f.json or {}).get("impact", {})
        sev = severity(float(f.confidence or 0.0), impact)["score"]
        volume = impact.get("affected_volume", 0) or 0
        persistence = max(1, (now - (aware_utc(inv.created_at) or now)).days)
        score = sev * (volume + 1) * persistence * (1 - resolution_rate)
        if score > best_score:
            best, best_score = (f, inv), score
    if best is None:
        return None
    f, inv = best
    return {"investigation_id": inv.id, "summary": f.summary, "score": round(best_score, 2)}


def _compose(d: dict, now) -> dict:
    since = now - timedelta(days=7)

    new_problems = []
    for inv in d["invs"]:
        if not _recent(inv.created_at, since):
            continue
        f = d["latest"].get(inv.id)
        if f is not None:
            impact = (f.json or {}).get("impact", {})
            new_problems.append({"investigation_id": inv.id, "summary": f.summary,
                                 "impact_score": impact.get("impact_score", 0.0)})
    new_problems.sort(key=lambda p: -p["impact_score"])

    fixes_verified = [{"investigation_id": w.investigation_id, "metric": w.metric}
                      for w in d["watches"]
                      if w.status == "confirmed" and _recent(w.confirmed_at, since)]
    regressions = [{"slug": a.slug, "parent_case_id": a.parent_case_id}
                   for a in d["regressions"] if _recent(a.created_at, since)]

    rate = _resolution_rate(d)
    fix_next = _fix_next(d, rate, now)

    # chronic themes (context for the brief)
    chronic = d["chronic"]

    # A "0% resolution rate" computed from zero cases is not a measurement; it
    # reads as a failing grade the data cannot support. Say so instead.
    resolved_total = len(d["invs"])
    headline = (f"This week: {_n(len(new_problems), 'new problem')}, "
                f"{_n(len(fixes_verified), 'fix', 'fixes')} verified, "
                f"{_n(len(regressions), 'regression')}.")
    # Nor is "0% … verified" a week after the first case resolved: no fix
    # could have shipped and been measured yet, so the line read as failure.
    if rate > 0:
        headline += f" {int(rate * 100)}% of resolved cases have a verified fix."
    elif resolved_total >= 3:
        headline += f" None of {resolved_total} resolved cases has a verified fix yet."
    lines = [headline]
    for p in new_problems[:2]:
        lines.append(f"• New: {p['summary']} (case #{p['investigation_id']}).")
    if chronic:
        lines.append(f"• Chronic: “{chronic[0]['label']}” unresolved {chronic[0]['age_days']}d "
                     f"(case #{chronic[0]['cases'][0]}).")
    if fix_next:
        lines.append(f"→ Fix next: {fix_next['summary']} (case #{fix_next['investigation_id']}).")

    return {
        "generated": now.date().isoformat(),
        "resolution_rate": rate,
        "new_problems": new_problems,
        "fixes_verified": fixes_verified,
        "regressions": regressions,
        "chronic_themes": chronic,
        "fix_next": fix_next,
        "lines": lines[:5],
    }


def weekly_brief(session: Session, as_of: datetime | None = None,
                 product_id: int | None = None) -> dict:
    now = as_of or datetime.now(timezone.utc)
    data = _load(session, None if product_id is None else [product_id], now)
    return _compose(data[product_id], now)


def weekly_briefs(session: Session, product_ids: list[int],
                  as_of: datetime | None = None) -> dict[int, dict]:
    """`weekly_brief` for many products with the same, fixed number of queries."""
    now = as_of or datetime.now(timezone.utc)
    data = _load(session, list(product_ids), now)
    return {pid: _compose(data[pid], now) for pid in product_ids}
