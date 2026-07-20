"""v8.0 product-scoping migration.

Everything used to be global. This creates Product rows from the existing source
bindings (and a "Lumo (demo)" product for the untagged synthetic corpus), then
assigns product_id to every scoped row. Idempotent — safe to run on every boot.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from echolens.db.models import (
    AnomalyEvent,
    CollectorState,
    Finding,
    FixWatch,
    Investigation,
    Issue,
    Post,
    Product,
    Release,
    Review,
)

DEMO_PRODUCT = "Lumo (demo)"
_CORPUS = (Review, Issue, Post, Release)


def backfill_products(session: Session) -> dict:
    created: list[str] = []

    # 1. a Product per distinct source binding (real, connected products)
    states = session.scalars(select(CollectorState)).all()
    for name in sorted({st.product for st in states if st.product}):
        if session.scalars(select(Product).where(Product.name == name)).first():
            continue
        mine = [s for s in states if s.product == name]
        session.add(Product(
            name=name,
            package_name=next((s.identifier for s in mine if s.source in ("play_store", "app_store")), None),
            github_repo=next((s.identifier for s in mine if s.source == "github"), None),
        ))
        created.append(name)
    session.flush()

    # 2. the untagged synthetic corpus becomes the demo product
    untagged = session.scalar(select(func.count(Review.id)).where(Review.product.is_(None))) or 0
    demo = session.scalars(select(Product).where(Product.is_demo.is_(True))).first()
    if untagged and demo is None:
        demo = Product(name=DEMO_PRODUCT, is_demo=True)
        session.add(demo)
        session.flush()
        created.append(DEMO_PRODUCT)
    if demo is not None:
        for model in _CORPUS:
            for row in session.scalars(select(model).where(model.product.is_(None))).all():
                row.product = demo.name
    session.flush()

    # 3. bind collector rows to their product
    by_name = {p.name: p.id for p in session.scalars(select(Product)).all()}
    for st in states:
        if st.product_id is None and st.product in by_name:
            st.product_id = by_name[st.product]

    # 4. legacy cases predate scoping — attribute them to the demo product when one
    # exists (that's where the pre-v8 data came from), else the first product.
    primary = demo or session.scalars(select(Product).order_by(Product.id)).first()
    if primary is not None:
        for model in (AnomalyEvent, Investigation, Finding, FixWatch):
            for row in session.scalars(select(model).where(model.product_id.is_(None))).all():
                row.product_id = primary.id
    session.flush()
    backfill_finding_products(session)
    dedupe_cases(session)
    return {"created": created, "products": len(by_name) or len(created)}


def dedupe_cases(session: Session) -> dict:
    """v8.0 cleanup: collapse duplicate investigations created for the same anomaly
    by the old re-triage bug. Keep the OLDEST case; mark the rest merged with a
    pointer so history isn't lost."""
    merged = 0
    by_anomaly: dict[int, list[Investigation]] = {}
    for inv in session.scalars(select(Investigation).order_by(Investigation.id)).all():
        if inv.anomaly_id is None:
            continue
        by_anomaly.setdefault(inv.anomaly_id, []).append(inv)
    for anomaly_id, invs in by_anomaly.items():
        if len(invs) < 2:
            continue
        keeper = invs[0]
        for dupe in invs[1:]:
            if dupe.status == "running":     # don't disturb an in-flight case
                continue
            notes = list(dupe.data_notes or [])
            notes.append(f"Merged duplicate of case #{keeper.id} (same anomaly).")
            dupe.data_notes = notes
            dupe.reopens_investigation_id = dupe.reopens_investigation_id or keeper.id
            dupe.status = "merged_duplicate"
            merged += 1
    session.flush()
    return {"merged_duplicates": merged}


def backfill_finding_products(session: Session) -> int:
    """Findings inherit their investigation's product."""
    n = 0
    for f in session.scalars(select(Finding).where(Finding.product_id.is_(None))).all():
        inv = session.get(Investigation, f.investigation_id)
        if inv is not None and inv.product_id is not None:
            f.product_id = inv.product_id
            n += 1
    session.flush()
    return n


def resolve_product(session: Session, product_id: int | None) -> Product | None:
    """The active product, or the only/first one when unspecified."""
    if product_id is not None:
        return session.get(Product, product_id)
    return session.scalars(select(Product).order_by(Product.id)).first()
