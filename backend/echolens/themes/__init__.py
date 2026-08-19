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
    fw = select(FixWatch).where(FixWatch.status == "confirmed")
    fstmt = select(Finding)
    if product_id is not None:
        fw = fw.where(FixWatch.product_id == product_id)
        fstmt = fstmt.where(Finding.product_id == product_id)
    confirmed = {w.investigation_id for w in session.scalars(fw).all()}

    groups: dict[str, dict] = {}
    for f in session.scalars(fstmt).all():
        inv = session.get(Investigation, f.investigation_id)
        if inv is None or inv.status != "resolved":
            continue
        anomaly = session.get(AnomalyEvent, inv.anomaly_id)
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
