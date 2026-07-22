"""Pydantic v2 schemas: the public request/response contract.

Validation that belongs to the *shape* of a request lives here (types, ranges,
"ADJUSTMENT needs a reason"). Validation that needs the current DB state
("would this SALE go negative?") lives in the service layer.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import MovementType

# --- Products ---------------------------------------------------------------


class ProductCreate(BaseModel):
    sku: str = Field(..., min_length=1, max_length=64, examples=["WIDGET-001"])
    name: str = Field(..., min_length=1, max_length=255, examples=["Blue Widget"])
    # Convenience: seed opening stock at creation. It is recorded as an opening
    # ADJUSTMENT movement so the ledger invariant holds from the very first row.
    initial_quantity: int = Field(0, ge=0)
    low_stock_threshold: int | None = Field(None, ge=0)


class ProductUpdate(BaseModel):
    # Note: quantity_on_hand is intentionally NOT updatable here. Stock only
    # ever changes by recording a movement.
    name: str | None = Field(None, min_length=1, max_length=255)
    low_stock_threshold: int | None = Field(None, ge=0)


class ProductRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sku: str
    name: str
    quantity_on_hand: int
    low_stock_threshold: int | None
    is_active: bool
    version: int
    created_at: datetime
    updated_at: datetime


# --- Movements --------------------------------------------------------------


class MovementCreate(BaseModel):
    model_config = ConfigDict(use_enum_values=False)

    type: MovementType
    # Signed change. RESTOCK must be > 0, SALE must be < 0, ADJUSTMENT != 0.
    # A SALE of 5 units is therefore recorded as quantity_delta = -5.
    quantity_delta: int = Field(
        ...,
        examples=[10, -5],
        description="Signed change to stock. RESTOCK>0, SALE<0, ADJUSTMENT!=0.",
    )
    reason: str | None = Field(None, max_length=500)

    @model_validator(mode="after")
    def _check_sign_and_reason(self) -> "MovementCreate":
        if self.quantity_delta == 0:
            raise ValueError("quantity_delta cannot be zero")

        if self.type == MovementType.RESTOCK and self.quantity_delta < 0:
            raise ValueError("RESTOCK requires a positive quantity_delta")

        if self.type == MovementType.SALE and self.quantity_delta > 0:
            raise ValueError("SALE requires a negative quantity_delta (stock is leaving)")

        if self.type == MovementType.ADJUSTMENT and not (
            self.reason and self.reason.strip()
        ):
            raise ValueError("ADJUSTMENT requires a non-empty reason")

        return self


class MovementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    type: MovementType
    quantity_delta: int
    reason: str | None
    resulting_quantity: int
    created_at: datetime


class PaginatedMovements(BaseModel):
    """Envelope for the paginated movement-history endpoint."""

    items: list[MovementRead]
    total: int
    limit: int
    offset: int
    has_more: bool
