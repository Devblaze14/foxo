"""Operational alert endpoints."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import ProductRead
from app.services import product_service

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("/low-stock", response_model=list[ProductRead])
def low_stock(
    threshold: int | None = Query(
        None,
        ge=0,
        description=(
            "Optional. If given, returns every active product at or below this "
            "level. If omitted, each product is checked against its own "
            "low_stock_threshold."
        ),
    ),
    db: Session = Depends(get_db),
):
    return product_service.get_low_stock(db, threshold_override=threshold)
