"""Pagination of movement history and the low-stock alert endpoint."""


def test_pagination_walks_the_whole_history(client, product):
    pid = product["id"]
    for _ in range(9):  # + 1 opening movement = 10 total
        client.post(
            f"/products/{pid}/movements", json={"type": "RESTOCK", "quantity_delta": 1}
        )

    seen = []
    offset = 0
    while True:
        page = client.get(f"/products/{pid}/movements?limit=4&offset={offset}").json()
        assert page["total"] == 10
        assert page["limit"] == 4
        seen.extend(m["id"] for m in page["items"])
        if not page["has_more"]:
            break
        offset += 4

    assert len(seen) == 10
    assert seen == sorted(seen)  # no duplicates, correct order


def test_low_stock_uses_per_product_threshold(client):
    low = client.post(
        "/products",
        json={
            "sku": "LOW",
            "name": "low",
            "initial_quantity": 2,
            "low_stock_threshold": 5,
        },
    ).json()
    client.post(
        "/products",
        json={
            "sku": "OK",
            "name": "ok",
            "initial_quantity": 50,
            "low_stock_threshold": 5,
        },
    )
    # No threshold set -> never alerts, even at zero stock.
    client.post("/products", json={"sku": "NONE", "name": "none", "initial_quantity": 0})

    skus = {p["sku"] for p in client.get("/alerts/low-stock").json()}
    assert skus == {"LOW"}
    assert low["quantity_on_hand"] == 2


def test_low_stock_threshold_override(client):
    client.post("/products", json={"sku": "P1", "name": "a", "initial_quantity": 3})
    client.post("/products", json={"sku": "P2", "name": "b", "initial_quantity": 30})

    skus = {p["sku"] for p in client.get("/alerts/low-stock?threshold=10").json()}
    assert skus == {"P1"}


def test_inactive_products_excluded_from_low_stock(client):
    pid = client.post(
        "/products",
        json={
            "sku": "INACT",
            "name": "x",
            "initial_quantity": 1,
            "low_stock_threshold": 5,
        },
    ).json()["id"]
    assert {p["sku"] for p in client.get("/alerts/low-stock").json()} == {"INACT"}
    client.post(f"/products/{pid}/deactivate")
    assert client.get("/alerts/low-stock").json() == []
