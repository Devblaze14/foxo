"""Product CRUD, SKU uniqueness, and the delete-vs-deactivate rule."""


def test_create_product_defaults_to_zero_stock(client):
    resp = client.post("/products", json={"sku": "A-1", "name": "Alpha"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["sku"] == "A-1"
    assert body["quantity_on_hand"] == 0
    assert body["is_active"] is True


def test_create_with_opening_stock_records_a_movement(client):
    resp = client.post(
        "/products", json={"sku": "A-2", "name": "Alpha", "initial_quantity": 7}
    )
    pid = resp.json()["id"]
    assert resp.json()["quantity_on_hand"] == 7

    history = client.get(f"/products/{pid}/movements").json()
    assert history["total"] == 1
    opening = history["items"][0]
    assert opening["type"] == "ADJUSTMENT"
    assert opening["quantity_delta"] == 7
    assert opening["reason"] == "Opening balance"


def test_duplicate_sku_rejected(client):
    client.post("/products", json={"sku": "DUP", "name": "One"})
    resp = client.post("/products", json={"sku": "DUP", "name": "Two"})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "duplicate_sku"


def test_get_missing_product_is_404(client):
    resp = client.get("/products/999999")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "product_not_found"


def test_update_changes_name_but_not_quantity(client, product):
    pid = product["id"]
    # The update schema has no quantity field; extra keys are ignored by FastAPI.
    resp = client.patch(
        f"/products/{pid}", json={"name": "Renamed", "quantity_on_hand": 9999}
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Renamed"
    assert resp.json()["quantity_on_hand"] == 20  # unchanged


def test_delete_product_without_movements_succeeds(client):
    pid = client.post("/products", json={"sku": "DEL", "name": "x"}).json()["id"]
    assert client.delete(f"/products/{pid}").status_code == 204
    assert client.get(f"/products/{pid}").status_code == 404


def test_delete_product_with_movements_is_blocked(client, product):
    pid = product["id"]
    resp = client.delete(f"/products/{pid}")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "product_has_movements"
    # Product still exists.
    assert client.get(f"/products/{pid}").status_code == 200


def test_deactivate_then_activate(client, product):
    pid = product["id"]
    assert client.post(f"/products/{pid}/deactivate").json()["is_active"] is False
    assert client.post(f"/products/{pid}/activate").json()["is_active"] is True


def test_list_can_exclude_inactive(client):
    a = client.post("/products", json={"sku": "L1", "name": "a"}).json()["id"]
    client.post("/products", json={"sku": "L2", "name": "b"})
    client.post(f"/products/{a}/deactivate")

    all_skus = {p["sku"] for p in client.get("/products").json()}
    active_skus = {
        p["sku"] for p in client.get("/products?include_inactive=false").json()
    }
    assert all_skus == {"L1", "L2"}
    assert active_skus == {"L2"}
