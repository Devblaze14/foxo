"""Movements are append-only: no mutating endpoints, and the ORM guard fires."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.exceptions import ImmutableRecordError
from app.models import MovementType, Product, StockMovement


def test_no_update_or_delete_route_for_movements(client, product):
    pid = product["id"]
    mv = client.get(f"/products/{pid}/movements").json()["items"][0]
    mid = mv["id"]

    # No route exists to update or delete a movement. 404 (no such path) and
    # 405 (method not allowed on the collection) both confirm immutability.
    assert client.put(f"/products/{pid}/movements/{mid}", json={}).status_code in (
        404,
        405,
    )
    assert client.delete(f"/products/{pid}/movements/{mid}").status_code in (404, 405)
    assert client.patch(f"/products/{pid}/movements/{mid}", json={}).status_code in (
        404,
        405,
    )
    # The collection endpoint rejects write verbs other than POST.
    assert client.put(f"/products/{pid}/movements", json={}).status_code == 405
    assert client.delete(f"/products/{pid}/movements").status_code == 405


def test_orm_guard_blocks_movement_update(tmp_path):
    """Even in code, mutating a persisted movement raises ImmutableRecordError."""
    engine = create_engine(f"sqlite:///{tmp_path / 'g.db'}", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)

    with Session() as s:
        p = Product(sku="G", name="g", quantity_on_hand=5, low_stock_threshold=None)
        s.add(p)
        s.flush()
        m = StockMovement(
            product_id=p.id,
            type=MovementType.RESTOCK,
            quantity_delta=5,
            resulting_quantity=5,
        )
        s.add(m)
        s.commit()

        m.quantity_delta = 999  # attempt to tamper
        with pytest.raises(ImmutableRecordError):
            s.commit()
        s.rollback()

        with pytest.raises(ImmutableRecordError):
            s.delete(m)
            s.commit()


def test_history_is_chronological(client, product):
    pid = product["id"]
    client.post(
        f"/products/{pid}/movements", json={"type": "RESTOCK", "quantity_delta": 1}
    )
    client.post(f"/products/{pid}/movements", json={"type": "SALE", "quantity_delta": -1})
    client.post(
        f"/products/{pid}/movements", json={"type": "RESTOCK", "quantity_delta": 2}
    )

    items = client.get(f"/products/{pid}/movements").json()["items"]
    ids = [m["id"] for m in items]
    timestamps = [m["created_at"] for m in items]
    assert ids == sorted(ids)
    assert timestamps == sorted(timestamps)
