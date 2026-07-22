"""ORM models.

Two tables, deliberately kept separate (a core evaluation point):

* ``products``        -- the catalogue + the *current* quantity on hand.
* ``stock_movements`` -- an append-only ledger of every change to that quantity.

The central invariant of the whole service is:

    product.quantity_on_hand == SUM(movement.quantity_delta) for that product

We never let those two drift. Quantity is only ever changed by appending a
movement, inside the same transaction that writes the movement row.
"""

import enum
from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    event,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.exceptions import ImmutableRecordError


def _utcnow() -> datetime:
    """Timezone-aware UTC now (microsecond precision, works on every DB)."""
    return datetime.now(UTC)


class MovementType(enum.StrEnum):
    """The three kinds of stock movement the business supports."""

    RESTOCK = "RESTOCK"  # stock coming in   (delta > 0)
    SALE = "SALE"  # stock going out   (delta < 0)
    ADJUSTMENT = "ADJUSTMENT"  # correction, either direction, reason required


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Current stock. This is a *projection* of the ledger -- it is only ever
    # written via record_movement(), never set directly through the API.
    quantity_on_hand: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Optional per-product reorder point used by the low-stock alert endpoint.
    low_stock_threshold: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Soft-delete flag. Products with history are deactivated, never deleted.
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)

    # Optimistic-locking version. SQLAlchemy bumps this on every UPDATE and adds
    # `WHERE version = <read value>`, so two concurrent writers can't both win.
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    movements: Mapped[list["StockMovement"]] = relationship(
        back_populates="product",
        order_by="StockMovement.id",
        # No delete cascade on purpose: the ledger must survive. The API blocks
        # deleting a product that has movements; the FK is a second line of
        # defence at the database level.
    )

    __mapper_args__ = {"version_id_col": version}
    __table_args__ = (
        CheckConstraint("quantity_on_hand >= 0", name="ck_product_qty_non_negative"),
    )


class StockMovement(Base):
    __tablename__ = "stock_movements"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id"), nullable=False, index=True
    )

    # Mapped attribute is `type`; the physical column is `movement_type`.
    type: Mapped[MovementType] = mapped_column(
        "movement_type",
        SAEnum(MovementType, name="movement_type_enum"),
        nullable=False,
    )

    # Signed change applied to quantity_on_hand. RESTOCK > 0, SALE < 0,
    # ADJUSTMENT != 0. Storing the signed delta makes reconciliation a plain
    # SUM() and keeps the "never go negative" check trivial.
    quantity_delta: Mapped[int] = mapped_column(Integer, nullable=False)

    # Required for ADJUSTMENT; optional otherwise.
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Running balance snapshot *after* this movement was applied. Lets you audit
    # / reconcile the ledger row-by-row without recomputing the whole history.
    resulting_quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )

    product: Mapped["Product"] = relationship(back_populates="movements")

    __table_args__ = (
        CheckConstraint("quantity_delta <> 0", name="ck_movement_delta_nonzero"),
        CheckConstraint(
            "resulting_quantity >= 0", name="ck_movement_resulting_non_negative"
        ),
    )


# --- Immutability guard -----------------------------------------------------
# There are no update/delete endpoints for movements, but this ORM-level guard
# makes the immutability guarantee explicit and catches accidental mutation in
# code too. (Bulk Core updates would bypass ORM events; in production a DB
# trigger or a restricted DB grant would enforce it at the storage layer.)


@event.listens_for(StockMovement, "before_update", propagate=True)
def _block_movement_update(_mapper, _connection, _target):  # noqa: ANN001
    raise ImmutableRecordError("Stock movements are immutable and cannot be modified.")


@event.listens_for(StockMovement, "before_delete", propagate=True)
def _block_movement_delete(_mapper, _connection, _target):  # noqa: ANN001
    raise ImmutableRecordError("Stock movements are immutable and cannot be deleted.")
