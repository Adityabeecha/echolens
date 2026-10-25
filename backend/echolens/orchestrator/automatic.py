"""Product eligibility shared by automatic investigation entry points."""
from sqlalchemy import select

from echolens.db.models import Product


def demo_product_ids(session) -> set[int]:
    return set(session.scalars(select(Product.id).where(Product.is_demo.is_(True))))
