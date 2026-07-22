"""Populate the database with a few sample products and movements.

Run with:  python -m scripts.seed
Uses the service layer directly (same rules as the API), so the seeded data is
guaranteed consistent.
"""

from app.database import Base, SessionLocal, engine
from app.schemas import MovementCreate, ProductCreate
from app.services import movement_service, product_service


def run() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        widget = product_service.create_product(
            db,
            ProductCreate(
                sku="WIDGET-001",
                name="Blue Widget",
                initial_quantity=100,
                low_stock_threshold=20,
            ),
        )
        gadget = product_service.create_product(
            db,
            ProductCreate(
                sku="GADGET-002",
                name="Red Gadget",
                initial_quantity=8,
                low_stock_threshold=10,  # already below threshold on purpose
            ),
        )
        product_service.create_product(
            db,
            ProductCreate(sku="GIZMO-003", name="Green Gizmo", initial_quantity=0),
        )

        # A little history for the widget.
        movement_service.record_movement(
            db, widget.id, MovementCreate(type="SALE", quantity_delta=-30)
        )
        movement_service.record_movement(
            db, widget.id, MovementCreate(type="RESTOCK", quantity_delta=50)
        )
        movement_service.record_movement(
            db,
            widget.id,
            MovementCreate(
                type="ADJUSTMENT", quantity_delta=-2, reason="Damaged during audit"
            ),
        )

        print("Seeded:")
        for p in (widget, gadget):
            db.refresh(p)
            print(f"  {p.sku}: qty={p.quantity_on_hand}")
        print("Done. Start the API and open http://localhost:8000/docs")
    finally:
        db.close()


if __name__ == "__main__":
    run()
