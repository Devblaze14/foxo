"""Concurrency safety: the never-go-negative rule must hold under parallel load.

This is the scenario the take-home's System Design question #1 asks about: two
(here, many) terminals recording a SALE for the same product at nearly the same
instant. We fire N concurrent SALE requests at a product that has exactly M
units and assert that:

  * exactly M sales succeed (201),
  * every other sale is cleanly rejected (409),
  * the final quantity is exactly 0 and never went negative,
  * the ledger invariant still holds.

Note on the database: under SQLite, writes serialise on a single write lock, so
each transaction already sees fresh state -- this proves the business rule holds
under concurrent access. Against Postgres, true row-level concurrency also
exercises the optimistic-lock retry path (a losing writer gets StaleDataError,
rolls back, re-reads and is then correctly rejected). Both paths converge on the
same guarantee: you can never sell stock you do not have.
"""

import threading

import pytest


@pytest.mark.parametrize("units,attempts", [(5, 25), (20, 40)])
def test_no_oversell_under_concurrent_sales(client, units, attempts):
    pid = client.post(
        "/products",
        json={"sku": f"RACE-{units}", "name": "Race", "initial_quantity": units},
    ).json()["id"]

    statuses: list[int] = []
    lock = threading.Lock()
    barrier = threading.Barrier(attempts)  # release all threads at once

    def sell():
        barrier.wait()  # maximise contention: everyone starts together
        resp = client.post(
            f"/products/{pid}/movements", json={"type": "SALE", "quantity_delta": -1}
        )
        with lock:
            statuses.append(resp.status_code)

    threads = [threading.Thread(target=sell) for _ in range(attempts)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    successes = sum(1 for s in statuses if s == 201)
    rejections = sum(1 for s in statuses if s == 409)

    assert successes == units, f"expected {units} successful sales, got {successes}"
    assert successes + rejections == attempts  # every request got a clean answer

    product = client.get(f"/products/{pid}").json()
    assert product["quantity_on_hand"] == 0  # never negative, never oversold

    history = client.get(f"/products/{pid}/movements?limit=200").json()
    assert product["quantity_on_hand"] == sum(
        m["quantity_delta"] for m in history["items"]
    )
