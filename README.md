# Inventory & Stock-Movement Service

**Live API:** <https://foxo-silk.vercel.app/docs> — deployed on Vercel against
Supabase Postgres, seeded with 50 products and 205 movements.

A backend service that tracks how much of each product is in stock and keeps a
permanent log of every stock movement (restocks, sales, and adjustments).

Built with Python and FastAPI, using SQLAlchemy for the database and Pydantic
for validation.

The core idea of the whole design is one rule:

> A product's `quantity_on_hand` is always equal to the sum of that product's
> movement log. Stock is never edited directly. It only changes by adding a
> movement, and the movement and the new quantity are saved together in one
> database transaction, so they can never disagree.

## Features

Core requirements:

- Products with a unique SKU, a name, and a quantity on hand.
- Three movement types: RESTOCK (adds stock), SALE (removes stock), and
  ADJUSTMENT (either direction, with a required reason).
- A SALE that would take stock below zero is rejected.
- Every movement records its type, amount, and timestamp, and is never changed
  or deleted afterward.
- Full CRUD for products.
- One endpoint records a movement and updates the quantity in the same
  transaction.
- One endpoint returns a product's full movement history in order.

Bonus requirements (also done):

- Products with history cannot be deleted. They are deactivated instead.
- Movement history is paginated.
- Concurrent updates are handled safely with a version column (optimistic
  locking).
- A low-stock alert endpoint lists products at or below their reorder point.

## Tech stack

Python 3.11+, FastAPI, SQLAlchemy 2.0, Pydantic v2, Uvicorn. The default
database is SQLite so the project runs with no setup. It also runs on PostgreSQL
by changing one environment variable.

## How the code is organized

The code is split into layers. A request goes from the router, to a service, to
the model, and back. Validation happens at the edge, and errors come back as
clean JSON.

```mermaid
flowchart TD
    Client["Client (Swagger UI or curl)"] --> Routers["Routers: HTTP layer"]
    Routers --> Services["Services: business logic and transactions"]
    Services --> Models["Models: database tables"]
    Models --> DB[("Database")]
```

| Layer | Folder | What it does |
| ----- | ------ | ------------ |
| Routers | `app/routers/` | Handle HTTP: read the request, call a service, return the result. |
| Schemas | `app/schemas.py` | Check the shape of requests and define the response format. |
| Services | `app/services/` | The real work: transactions, the never-negative rule, concurrency. |
| Models | `app/models.py` | The two database tables and their rules. |
| Exceptions | `app/exceptions.py` | Turn domain errors into an HTTP status and a short code. |

A simple way to remember the split: schemas check the shape of a request (is the
amount a number, does an ADJUSTMENT have a reason), and services check it against
the live database (would this sale take stock below zero right now).

## Data model

There are two tables, kept separate on purpose: the product catalogue and the
movement log. One product has many movements, and those movements are its
append-only history.

```mermaid
erDiagram
    PRODUCT ||--o{ STOCK_MOVEMENT : "has history of"

    PRODUCT {
        int id PK
        string sku "unique"
        string name
        int quantity_on_hand "equals the sum of its movements"
        int low_stock_threshold "optional reorder point"
        bool is_active
        int version "used for optimistic locking"
        datetime created_at
        datetime updated_at
    }

    STOCK_MOVEMENT {
        int id PK
        int product_id FK
        enum type "RESTOCK, SALE, or ADJUSTMENT"
        int quantity_delta "signed amount"
        string reason "required for ADJUSTMENT"
        int resulting_quantity "stock level after this movement"
        datetime created_at
    }
```

## Quick start

Requires Python 3.11 or newer.

```bash
pip install -r requirements.txt      # install dependencies
python -m scripts.seed               # optional: add some sample data
uvicorn app.main:app --reload        # run the server
```

Then open the interactive API docs at http://localhost:8000/docs. FastAPI builds
that page automatically, so you can try every endpoint from the browser.

By default the app stores data in a local SQLite file (`inventory.db`), so
nothing else needs to be installed.

### Using PostgreSQL

The app runs on PostgreSQL without any code change. Set the `DATABASE_URL`
environment variable to your Postgres connection string and start the server as
usual. A `.env` file works too; see `.env.example`. The seed script populates a
50-product catalogue with a consistent movement ledger:

```bash
export DATABASE_URL='postgresql+psycopg://user:pass@host:5432/postgres'
python -m scripts.seed
```

It is deterministic and idempotent -- existing SKUs are skipped, so re-running
it is a no-op. `scripts/schema.sql` creates the same schema by hand if you would
rather not let the app do it.

### Deployment notes

The live instance runs as a Vercel serverless function against Supabase
Postgres. Three things that setup requires, all handled in `app/database.py` and
`app/config.py`:

- **Connect through the pooler, not the direct host.** Supabase's
  `db.<ref>.supabase.co` endpoint resolves to IPv6 only, and Vercel functions
  have no IPv6 egress, so a direct connection fails with an opaque
  `connection is bad` before Postgres ever replies. The Supavisor pooler
  hostname is dual-stack and works.
- **`NullPool` for Postgres.** A serverless function is frozen between
  invocations, so a client-side connection pool just accumulates sockets the
  runtime has already torn down. The external pooler does the pooling instead.
- **`prepare_threshold=0`.** Transaction-mode pooling hands each statement a
  different backend, so server-side prepared statements cannot survive between
  checkouts. Without this, psycopg fails intermittently with
  `DuplicatePreparedStatement`.

Table creation is gated behind `AUTO_CREATE_TABLES` (default `true`). It is set
to `false` in production so an unreachable database cannot take down the whole
function during startup, and so schema changes are a deliberate act rather than
a side effect of a cold start. Apply `scripts/schema.sql` once instead.

## API reference

| Method | Path | Description |
| ------ | ---- | ----------- |
| POST | `/products` | Create a product (with optional opening stock). |
| GET | `/products` | List products. |
| GET | `/products/{id}` | Get one product. |
| PATCH | `/products/{id}` | Update the name or low-stock threshold (not the quantity). |
| DELETE | `/products/{id}` | Delete a product. Returns 409 if it has history. |
| POST | `/products/{id}/deactivate` | Mark a product inactive. |
| POST | `/products/{id}/activate` | Reactivate a product. |
| POST | `/products/{id}/movements` | Record a movement and update the quantity. |
| GET | `/products/{id}/movements` | Movement history, in order, paginated. |
| GET | `/alerts/low-stock` | Products at or below their reorder point. |
| GET | `/health` | Simple health check. |

Errors come back in a consistent shape with a short code:

```json
{ "error": { "code": "insufficient_stock", "message": "Rejected: 3 on hand, change of -5 would result in -2" } }
```

## Example requests

Every response below is real output, captured from a run against a fresh
database. Timestamps are shortened for readability.

**Create a product with opening stock.** The opening quantity is not written
directly: it is recorded as an `ADJUSTMENT` movement, so the ledger balances
from the very first row.

```bash
curl -X POST localhost:8000/products \
  -H 'Content-Type: application/json' \
  -d '{"sku":"WIDGET-001","name":"Blue Widget","initial_quantity":100,"low_stock_threshold":20}'
```

```json
{
  "id": 1,
  "sku": "WIDGET-001",
  "name": "Blue Widget",
  "quantity_on_hand": 100,
  "low_stock_threshold": 20,
  "is_active": true,
  "version": 2,
  "created_at": "2026-07-23T09:14:02Z",
  "updated_at": "2026-07-23T09:14:02Z"
}
```

**Sell 30 units.** A sale is a negative delta. The response carries
`resulting_quantity`, the running balance after this movement was applied, so
the ledger can be audited row by row without replaying the whole history.

```bash
curl -X POST localhost:8000/products/1/movements \
  -H 'Content-Type: application/json' \
  -d '{"type":"SALE","quantity_delta":-30}'
```

```json
{
  "id": 2,
  "product_id": 1,
  "type": "SALE",
  "quantity_delta": -30,
  "reason": null,
  "resulting_quantity": 70,
  "created_at": "2026-07-23T11:47:35Z"
}
```

**Try to oversell.** Rejected with `409` before anything is written, so no
partial state is left behind and the quantity is untouched.

```bash
curl -X POST localhost:8000/products/1/movements \
  -H 'Content-Type: application/json' \
  -d '{"type":"SALE","quantity_delta":-9999}'
```

```json
{
  "error": {
    "code": "insufficient_stock",
    "message": "Rejected: 70 on hand, change of -9999 would result in -9929"
  }
}
```

**Record a correction.** An `ADJUSTMENT` moves stock in either direction, but a
reason is mandatory; omitting it fails validation with `422`.

```bash
curl -X POST localhost:8000/products/1/movements \
  -H 'Content-Type: application/json' \
  -d '{"type":"ADJUSTMENT","quantity_delta":-2,"reason":"Damaged during audit"}'
```

```json
{
  "id": 3,
  "product_id": 1,
  "type": "ADJUSTMENT",
  "quantity_delta": -2,
  "reason": "Damaged during audit",
  "resulting_quantity": 68,
  "created_at": "2026-07-23T14:02:19Z"
}
```

**View the history**, oldest first, in a paginated envelope. Note that the
deltas sum to `100 - 30 - 2 = 68`, which is exactly the product's current
`quantity_on_hand`. That equality is the invariant the whole service exists to
protect.

```bash
curl 'localhost:8000/products/1/movements?limit=20&offset=0'
```

```json
{
  "items": [
    {
      "id": 1,
      "product_id": 1,
      "type": "ADJUSTMENT",
      "quantity_delta": 100,
      "reason": "Opening balance",
      "resulting_quantity": 100,
      "created_at": "2026-07-23T09:14:02Z"
    },
    {
      "id": 2,
      "product_id": 1,
      "type": "SALE",
      "quantity_delta": -30,
      "reason": null,
      "resulting_quantity": 70,
      "created_at": "2026-07-23T11:47:35Z"
    },
    {
      "id": 3,
      "product_id": 1,
      "type": "ADJUSTMENT",
      "quantity_delta": -2,
      "reason": "Damaged during audit",
      "resulting_quantity": 68,
      "created_at": "2026-07-23T14:02:19Z"
    }
  ],
  "total": 3,
  "limit": 20,
  "offset": 0,
  "has_more": false
}
```

**See what is running low.** Results are ordered most urgent first. Each product
is compared against its *own* reorder point, which is why a product holding 25
units appears while others holding far more do not. Products with no threshold
set, and deactivated products, are excluded entirely. Only the relevant fields
are shown below; the real response returns full product objects.

```bash
curl localhost:8000/alerts/low-stock
```

```json
[
  { "sku": "WGT-004", "quantity_on_hand": 0,  "low_stock_threshold": 20 },
  { "sku": "SEA-004", "quantity_on_hand": 3,  "low_stock_threshold": 25 },
  { "sku": "WGT-002", "quantity_on_hand": 25, "low_stock_threshold": 50 }
]
```

## Design decisions

**The log is the source of truth.** The quantity can never be set directly
through the API, because the update schema has no quantity field. Stock only
changes by adding a movement. This makes "quantity equals the sum of movements" a
rule that always holds. Even opening stock is recorded as a movement, so the rule
is true from the very first row.

**One transaction.** Recording a movement updates the product quantity and
inserts the movement row in a single commit. Either both are saved or neither is,
so the quantity and the log cannot drift apart.

**Never negative, checked before writing.** The service works out the new
quantity and rejects the sale with `409 insufficient_stock` before touching the
database if it would go below zero. A database CHECK constraint
(`quantity_on_hand >= 0`) is a second line of defence.

**History cannot be changed.** There are no update or delete routes for
movements. On top of that, a database-layer guard raises an error if any code
ever tries to edit or delete a saved movement.

**Safe under concurrent updates.** Each product has a `version` number. An update
runs as "change this row only if the version still matches", and bumps the
version. If another update got there first, ours changes zero rows, and we roll
back, re-read the current stock, and try again. This is what stops two
simultaneous sales from overselling.

**Signed amounts.** A sale of 5 is stored as -5 and a restock of 5 as +5. This
keeps the never-negative check simple (`quantity + amount >= 0`), makes the total
a plain sum, and lets an ADJUSTMENT go either way without special handling.

**Delete or deactivate.** Deleting a product that has history would throw away
the audit trail, so it is blocked. Deactivating keeps the record and the history.
A product with no history can be deleted normally.

## Running the tests

```bash
pytest
```

The tests cover product CRUD, all three movement types, the never-negative rule,
immutability of history, pagination, low-stock alerts, and a concurrency test
that fires many simultaneous sales at one product and checks that stock is never
oversold and never goes negative.

## System design questions

These are the two written questions from the brief.

### 1. Two terminals record a SALE for the same product at almost the same time. What could go wrong, and how would you fix it?

Without protection this is a lost-update race. Both terminals read
`quantity_on_hand = 1`, both check that 1 minus 1 is not below zero, and both
save `quantity = 0` while inserting a SALE. Two units are sold when only one
existed. The cause is that read, check, and write are not atomic across the two
transactions.

The fix used here is optimistic locking. Each product has a `version` column, and
the update only succeeds if the version still matches what we read, at which point
the version is incremented. If the other terminal committed first, our update
changes zero rows and SQLAlchemy raises an error. We roll back, read the current
quantity again, and retry. Because the whole thing runs in one transaction, the
movement and the quantity update commit together. One sale wins, and the other is
correctly rejected once the stock is gone. The concurrency test proves this
holds.

Two other approaches would also work:

- Pessimistic locking with `SELECT ... FOR UPDATE` locks the product row so the
  second terminal waits for the first to finish, then reads fresh state. It is
  simple to reason about but holds locks and can slow down under heavy load.
- An atomic conditional update pushes the rule into the database directly:
  `UPDATE products SET quantity_on_hand = quantity_on_hand + :amount WHERE id = :id AND quantity_on_hand + :amount >= 0`,
  and treats "zero rows updated" as insufficient stock. This is fully atomic and
  is a good next step at very high volume.

Optimistic locking is a good default here because it is low overhead, holds no
long locks, and works the same way on SQLite and PostgreSQL.

### 2. How would the design change from one warehouse to 50 warehouses, each with its own stock?

The main change is that stock is no longer a single number per product. It
becomes a number per product and warehouse.

- Add a `warehouses` table, and move the quantity into a `stock_levels` table
  keyed by product and warehouse, each row with its own quantity and version. The
  `products` table becomes a shared catalogue of SKU and name. The SKU stays
  globally unique, but the stock row is per warehouse.
- Every movement gets a `warehouse_id`, so the log is naturally split by
  warehouse. The never-negative rule and the version lock now apply to the
  per-warehouse row, which actually lowers contention, since different warehouses
  no longer compete for the same row.
- Moving stock between warehouses becomes its own operation: a paired
  out-and-in movement that must be atomic across two stock rows in one
  transaction.
- Reporting changes a little: quantity on hand is now per warehouse, with a
  combined view for company-wide totals, and low-stock thresholds become per
  warehouse.

At this size, 50 warehouses still fit comfortably in one relational database with
good indexes. The schema change above is the real work. Sharding, separate
services per warehouse, read replicas, and caching are all options later if the
volume grows, but reaching for them now would be adding complexity that is not
needed yet.

## Possible improvements

Left out on purpose to keep the project focused:

- Authentication and users.
- Alembic migrations. The app creates tables on startup for an easy run;
  a real deployment would use versioned migrations.
- Multi-warehouse support, as described in question 2 above.
- A background job or webhook for low-stock alerts instead of a pull endpoint.

## Project structure

```
app/
  main.py              FastAPI app, routers, error handlers, health check
  config.py            settings read from the environment
  database.py          engine, session, and Base
  models.py            Product and StockMovement tables, version and immutability rules
  schemas.py           request and response validation
  exceptions.py        domain errors mapped to HTTP status and code
  services/
    product_service.py   product CRUD, delete or deactivate, low-stock
    movement_service.py  the transaction that records a movement safely
  routers/
    products.py          product endpoints
    movements.py         movement and history endpoints
    alerts.py            low-stock endpoint
tests/                 tests, including immutability and concurrency
scripts/seed.py        adds sample data
```
