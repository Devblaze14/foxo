"""HTTP layer for stock movements (nested under a product)."""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import MovementCreate, MovementRead, PaginatedMovements
from app.services import movement_service

router = APIRouter(prefix="/products/{product_id}/movements", tags=["movements"])


@router.post("", response_model=MovementRead, status_code=status.HTTP_201_CREATED)
def record_movement(
    product_id: int, payload: MovementCreate, db: Session = Depends(get_db)
):
    """Record a movement and update the product's quantity in one transaction."""
    return movement_service.record_movement(db, product_id, payload)


@router.get("", response_model=PaginatedMovements)
def get_movement_history(
    product_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Full movement history for a product, oldest first, paginated."""
    return movement_service.list_movements(db, product_id, limit=limit, offset=offset)
