"""Shared test fixtures.

Each test gets its own isolated, file-based SQLite database (a fresh temp file)
so tests never interfere with each other or with the real inventory.db. A file
(rather than in-memory) DB is used so the concurrency test can open multiple
connections from multiple threads.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app


@pytest.fixture
def client(tmp_path):
    db_file = tmp_path / "test.db"
    engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
        future=True,
    )

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_connection, _record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, future=True
    )

    def _override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    # No context manager => the app lifespan does not touch the real DB; tables
    # are created above on the test engine instead.
    yield TestClient(app)

    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture
def product(client):
    """A product starting with 20 units on hand and a low-stock threshold of 5."""
    resp = client.post(
        "/products",
        json={
            "sku": "TEST-SKU",
            "name": "Test Product",
            "initial_quantity": 20,
            "low_stock_threshold": 5,
        },
    )
    assert resp.status_code == 201
    return resp.json()
