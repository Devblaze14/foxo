"""Stock-movement rules: the three types, never-go-negative, atomicity."""


def _record(client, pid, **body):
    return client.post(f"/products/{pid}/movements", json=body)


def test_restock_increases_quantity(client, product):
    pid = product["id"]
    resp = _record(client, pid, type="RESTOCK", quantity_delta=15)
    assert resp.status_code == 201
    assert resp.json()["resulting_quantity"] == 35
    assert client.get(f"/products/{pid}").json()["quantity_on_hand"] == 35


def test_sale_decreases_quantity(client, product):
    pid = product["id"]
    resp = _record(client, pid, type="SALE", quantity_delta=-5)
    assert resp.status_code == 201
    assert resp.json()["resulting_quantity"] == 15
    assert client.get(f"/products/{pid}").json()["quantity_on_hand"] == 15


def test_sale_below_zero_is_rejected(client, product):
    pid = product["id"]
    resp = _record(client, pid, type="SALE", quantity_delta=-21)  # only 20 on hand
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "insufficient_stock"
    # Quantity untouched -> the rejected movement wrote nothing.
    assert client.get(f"/products/{pid}").json()["quantity_on_hand"] == 20
    assert client.get(f"/products/{pid}/movements").json()["total"] == 1  # opening only


def test_sale_to_exactly_zero_is_allowed(client, product):
    pid = product["id"]
    assert _record(client, pid, type="SALE", quantity_delta=-20).status_code == 201
    assert client.get(f"/products/{pid}").json()["quantity_on_hand"] == 0


def test_adjustment_requires_reason(client, product):
    pid = product["id"]
    resp = _record(client, pid, type="ADJUSTMENT", quantity_delta=-2)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


def test_adjustment_can_decrease_with_reason(client, product):
    pid = product["id"]
    resp = _record(
        client, pid, type="ADJUSTMENT", quantity_delta=-3, reason="Broken in transit"
    )
    assert resp.status_code == 201
    assert client.get(f"/products/{pid}").json()["quantity_on_hand"] == 17


def test_wrong_sign_is_rejected(client, product):
    pid = product["id"]
    assert _record(client, pid, type="RESTOCK", quantity_delta=-5).status_code == 422
    assert _record(client, pid, type="SALE", quantity_delta=5).status_code == 422
    assert _record(client, pid, type="RESTOCK", quantity_delta=0).status_code == 422


def test_movement_on_missing_product_is_404(client):
    assert _record(client, 999999, type="RESTOCK", quantity_delta=1).status_code == 404


def test_ledger_invariant_holds_after_many_movements(client, product):
    """quantity_on_hand must always equal SUM(all quantity_delta)."""
    pid = product["id"]
    _record(client, pid, type="RESTOCK", quantity_delta=10)
    _record(client, pid, type="SALE", quantity_delta=-4)
    _record(client, pid, type="ADJUSTMENT", quantity_delta=2, reason="found extra")
    _record(client, pid, type="SALE", quantity_delta=-8)

    history = client.get(f"/products/{pid}/movements?limit=200").json()
    qty = client.get(f"/products/{pid}").json()["quantity_on_hand"]
    assert qty == sum(m["quantity_delta"] for m in history["items"])
    # And every resulting_quantity snapshot is a valid running total.
    running = 0
    for m in history["items"]:
        running += m["quantity_delta"]
        assert m["resulting_quantity"] == running
