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
    return {"created": created, "products": len(by_name) or len(created)}


def resolve_product(session: Session, product_id: int | None) -> Product | None:
    """The active product, or the only/first one when unspecified."""
    if product_id is not None:
        return session.get(Product, product_id)
    return session.scalars(select(Product).order_by(Product.id)).first()
