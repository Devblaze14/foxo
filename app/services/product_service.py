"""Business logic for products (catalogue operations).

Kept separate from the HTTP layer so the rules can be tested directly and
reused (e.g. by the seed script) without going through FastAPI.
"""

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.exceptions import DuplicateSKU, ProductHasMovements, ProductNotFound
from app.models import MovementType, Product, StockMovement
from app.schemas import ProductCreate, ProductUpdate


def get_product(db: Session, product_id: int) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise ProductNotFound(f"Product {product_id} not found")
    return product


def list_products(
    db: Session, *, include_inactive: bool = True, limit: int = 50, offset: int = 0
) -> tuple[list[Product], int]:
    base = select(Product)
    count_q = select(func.count()).select_from(Product)
    if not include_inactive:
        base = base.where(Product.is_active.is_(True))
        count_q = count_q.where(Product.is_active.is_(True))

    total = db.scalar(count_q) or 0
    items = list(db.scalars(base.order_by(Product.id).limit(limit).offset(offset)).all())
    return items, total


def create_product(db: Session, payload: ProductCreate) -> Product:
    # Pre-check for a friendly 409; the unique constraint below is the real
    # guarantee and also protects against a create/create race.
    if db.scalar(select(Product).where(Product.sku == payload.sku)) is not None:
        raise DuplicateSKU(f"A product with SKU '{payload.sku}' already exists")

    product = Product(
        sku=payload.sku,
        name=payload.name,
        quantity_on_hand=0,
        low_stock_threshold=payload.low_stock_threshold,
    )
    db.add(product)

    try:
        db.flush()  # assigns product.id and enforces the unique SKU constraint
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateSKU(f"A product with SKU '{payload.sku}' already exists") from exc

    # Record opening stock as an ADJUSTMENT so quantity == SUM(deltas) from row 1.
    if payload.initial_quantity > 0:
        product.quantity_on_hand = payload.initial_quantity
        db.add(
            StockMovement(
                product_id=product.id,
                type=MovementType.ADJUSTMENT,
                quantity_delta=payload.initial_quantity,
                reason="Opening balance",
                resulting_quantity=payload.initial_quantity,
            )
        )

    db.commit()
    db.refresh(product)
    return product


def update_product(db: Session, product_id: int, payload: ProductUpdate) -> Product:
    product = get_product(db, product_id)

    data = payload.model_dump(exclude_unset=True)
    if "name" in data:
        product.name = data["name"]
    if "low_stock_threshold" in data:
        product.low_stock_threshold = data["low_stock_threshold"]

    db.commit()
    db.refresh(product)
    return product


def set_active(db: Session, product_id: int, *, active: bool) -> Product:
    product = get_product(db, product_id)
    product.is_active = active
    db.commit()
    db.refresh(product)
    return product


def delete_product(db: Session, product_id: int) -> None:
    """Hard-delete only when the product has no history.

    Products that have movements are never deleted (the ledger must survive) --
    callers are told to deactivate instead.
    """
    product = get_product(db, product_id)

    has_movements = (
        db.scalar(
            select(func.count())
            .select_from(StockMovement)
            .where(StockMovement.product_id == product_id)
        )
        or 0
    )
    if has_movements:
        raise ProductHasMovements(
            f"Product {product_id} has {has_movements} movement(s) and cannot be "
            f"deleted. Deactivate it instead (POST /products/{product_id}/deactivate)."
        )

    db.delete(product)
    db.commit()


def get_low_stock(db: Session, *, threshold_override: int | None = None) -> list[Product]:
    """Active products at or below their reorder point.

    If ``threshold_override`` is given it applies to every active product;
    otherwise each product is compared against its own low_stock_threshold
    (products without a threshold are ignored).
    """
    stmt = select(Product).where(Product.is_active.is_(True))
    if threshold_override is not None:
        stmt = stmt.where(Product.quantity_on_hand <= threshold_override)
    else:
        stmt = stmt.where(
            Product.low_stock_threshold.is_not(None),
            Product.quantity_on_hand <= Product.low_stock_threshold,
        )
    return list(db.scalars(stmt.order_by(Product.quantity_on_hand)).all())
