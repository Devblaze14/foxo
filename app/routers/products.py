"""HTTP layer for products. Thin: parse -> call service -> serialize."""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import ProductCreate, ProductRead, ProductUpdate
from app.services import product_service

router = APIRouter(prefix="/products", tags=["products"])


@router.post("", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
def create_product(payload: ProductCreate, db: Session = Depends(get_db)):
    return product_service.create_product(db, payload)


@router.get("", response_model=list[ProductRead])
def list_products(
    include_inactive: bool = True,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    items, _total = product_service.list_products(
        db, include_inactive=include_inactive, limit=limit, offset=offset
    )
    return items


@router.get("/{product_id}", response_model=ProductRead)
def get_product(product_id: int, db: Session = Depends(get_db)):
    return product_service.get_product(db, product_id)


@router.patch("/{product_id}", response_model=ProductRead)
def update_product(
    product_id: int, payload: ProductUpdate, db: Session = Depends(get_db)
):
    return product_service.update_product(db, product_id, payload)


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(product_id: int, db: Session = Depends(get_db)):
    # Blocked with a 409 if the product has movements (deactivate instead).
    product_service.delete_product(db, product_id)


@router.post("/{product_id}/deactivate", response_model=ProductRead)
def deactivate_product(product_id: int, db: Session = Depends(get_db)):
    return product_service.set_active(db, product_id, active=False)


@router.post("/{product_id}/activate", response_model=ProductRead)
def activate_product(product_id: int, db: Session = Depends(get_db)):
    return product_service.set_active(db, product_id, active=True)
