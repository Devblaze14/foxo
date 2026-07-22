"""Business logic for stock movements -- the transactional core of the service.

record_movement() guarantees three things at once:

1.  Atomicity: the product's new quantity and the new ledger row are written in
    ONE transaction. Either both land or neither does -- they can never drift.
2.  The "never go negative" rule: a SALE (or negative ADJUSTMENT) that would
    push quantity below zero is rejected before anything is written.
3.  Safety under concurrency: optimistic locking (a version column) means two
    terminals selling the same unit at the same instant cannot both succeed.
    The loser gets a StaleDataError, we roll back, re-read fresh state and
    retry -- so the second attempt sees the real quantity and is rejected if
    stock is gone.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.config import settings
from app.exceptions import (
    ConcurrencyConflict,
    InsufficientStock,
    ProductInactive,
    ProductNotFound,
)
from app.models import Product, StockMovement
from app.schemas import MovementCreate, PaginatedMovements


def record_movement(
    db: Session, product_id: int, payload: MovementCreate
) -> StockMovement:
    last_error: StaleDataError | None = None

    for _attempt in range(settings.max_write_retries):
        # Start each attempt from fresh DB state so a retry re-reads the real,
        # possibly-updated quantity rather than a stale cached value.
        db.expire_all()

        product = db.get(Product, product_id)
        if product is None:
            raise ProductNotFound(f"Product {product_id} not found")
        if not product.is_active:
            raise ProductInactive(
                f"Product {product_id} is inactive; reactivate it before recording "
                f"movements"
            )

        new_quantity = product.quantity_on_hand + payload.quantity_delta
        if new_quantity < 0:
            # Business rule: reject BEFORE writing anything.
            raise InsufficientStock(
                f"Rejected: {product.quantity_on_hand} on hand, change of "
                f"{payload.quantity_delta} would result in {new_quantity}"
            )

        # Mutating the product bumps its version on flush; the UPDATE carries
        # `WHERE version = <value we read>`. If a concurrent commit already
        # changed the row, this UPDATE hits 0 rows -> StaleDataError.
        product.quantity_on_hand = new_quantity

        movement = StockMovement(
            product_id=product.id,
            type=payload.type,
            quantity_delta=payload.quantity_delta,
            reason=payload.reason,
            resulting_quantity=new_quantity,
        )
        db.add(movement)

        try:
            db.commit()  # atomic: product UPDATE (versioned) + movement INSERT
        except StaleDataError as exc:
            db.rollback()
            last_error = exc
            continue  # someone beat us to it -> retry with fresh state

        db.refresh(movement)
        return movement

    # Exhausted retries under sustained contention.
    raise ConcurrencyConflict(
        "Could not record movement due to concurrent updates; please retry"
    ) from last_error


def list_movements(
    db: Session, product_id: int, *, limit: int = 50, offset: int = 0
) -> PaginatedMovements:
    # Confirm the product exists so history-for-unknown-id is a clean 404.
    if db.get(Product, product_id) is None:
        raise ProductNotFound(f"Product {product_id} not found")

    total = (
        db.scalar(
            select(func.count())
            .select_from(StockMovement)
            .where(StockMovement.product_id == product_id)
        )
        or 0
    )

    # Chronological order. id is monotonic with creation, so it is both a
    # reliable tie-breaker for same-timestamp rows and a chronological sort.
    stmt = (
        select(StockMovement)
        .where(StockMovement.product_id == product_id)
        .order_by(StockMovement.created_at.asc(), StockMovement.id.asc())
        .limit(limit)
        .offset(offset)
    )
    rows = list(db.scalars(stmt).all())

    return PaginatedMovements(
        items=rows,  # type: ignore[arg-type]  # validated via from_attributes
        total=total,
        limit=limit,
        offset=offset,
        has_more=offset + len(rows) < total,
    )
