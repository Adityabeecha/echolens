"""Theme lifecycle (v7.0, minimal) — emergence → peak → resolved / chronic.

Groups verified findings by their primary theme and tracks how long each has
been alive. A theme with an open problem older than 60 days is CHRONIC — the
flag that tells a PM "this one keeps coming back." No taxonomy trees, no merge
ceremonies: lifecycle only. Powers the weekly brief and the health screen.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import AnomalyEvent, Finding, FixWatch, Investigation
from echolens.impact import theme_terms
from echolens.timeutil import aware_utc

CHRONIC_DAYS = 60


def theme_lifecycle(session: Session, as_of: datetime | None = None,
                    product_id: int | None = None) -> list[dict]:
    now = as_of or datetime.now(timezone.utc)
    fw = select(FixWatch.investigation_id).where(FixWatch.status == "confirmed")
    if product_id is not None:
        fw = fw.where(FixWatch.product_id == product_id)
    confirmed = set(session.scalars(fw).all())
    return _lifecycle(_resolved_rows(session, None if product_id is None else [product_id]),
                      confirmed, now)


def theme_lifecycles(session: Session, product_ids: list[int],
                     as_of: datetime | None = None) -> dict[int, list[dict]]:
    """`theme_lifecycle` for many products in two queries, not two per product.

    The portfolio board and brief called theme_lifecycle once per product, and
    each call fetched every finding's investigation and anomaly one row at a
    time, so those pages cost O(products x findings) round trips.
    """
    now = as_of or datetime.now(timezone.utc)
    if not product_ids:
        return {}
    confirmed: dict[int, set[int]] = {pid: set() for pid in product_ids}
    for pid, inv_id in session.execute(
            select(FixWatch.product_id, FixWatch.investigation_id).where(
                FixWatch.status == "confirmed", FixWatch.product_id.in_(product_ids))).all():
        confirmed[pid].add(inv_id)
    rows: dict[int, list] = {pid: [] for pid in product_ids}
    for row in _resolved_rows(session, product_ids):
        rows[row[0].product_id].append(row)
    return {pid: _lifecycle(rows[pid], confirmed[pid], now) for pid in product_ids}


def _resolved_rows(session: Session, product_ids: list[int] | None):
    """(finding, investigation, anomaly) for every finding on a resolved case,
    in ONE joined query. This was a session.get() per finding for the
    investigation and another for its anomaly."""
    stmt = (select(Finding, Investigation, AnomalyEvent)
            .join(Investigation, Investigation.id == Finding.investigation_id)
            .outerjoin(AnomalyEvent, AnomalyEvent.id == Investigation.anomaly_id)
            .where(Investigation.status == "resolved")
            .order_by(Finding.id))
    if product_ids is not None:
        stmt = stmt.where(Finding.product_id.in_(product_ids))
    return session.execute(stmt).all()


def _lifecycle(rows, confirmed: set[int], now: datetime) -> list[dict]:
    groups: dict[str, dict] = {}
    for f, inv, anomaly in rows:
        terms = theme_terms(anomaly, f.json or {})
        key = terms[0] if terms else "other"
        created = aware_utc(inv.created_at) or now
        g = groups.setdefault(key, {
            "theme": key, "cases": [], "open_cases": [],
            "first_seen": created, "last_seen": created, "label": f.summary,
        })
        g["cases"].append(inv.id)
        if inv.id not in confirmed:
            g["open_cases"].append(inv.id)
        g["first_seen"] = min(g["first_seen"], created)
        if created >= g["last_seen"]:
            g["last_seen"] = created
            g["label"] = f.summary  # most recent finding's headline

    out = []
    for g in groups.values():
        age = (now - g["first_seen"]).days
        open_n = len(g["open_cases"])
        if open_n == 0:
            status = "resolved"
        elif age > CHRONIC_DAYS:
            status = "chronic"
        else:
            status = "active"
        out.append({
            "theme": g["theme"], "label": g["label"], "status": status,
            "age_days": age, "cases": g["cases"], "open_cases": open_n,
            "first_seen": g["first_seen"].date().isoformat(),
            "last_seen": g["last_seen"].date().isoformat(),
        })
    order = {"chronic": 0, "active": 1, "resolved": 2}
    out.sort(key=lambda t: (order.get(t["status"], 3), -t["age_days"]))
    return out
