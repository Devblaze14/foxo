"""Database engine, session factory and the FastAPI DB dependency.

A SQLAlchemy ``Session`` is transactional by default: everything that happens
between two ``commit()`` calls is one transaction. That property is the
backbone of this service -- it is how we keep a product's quantity and its
movement log from ever drifting apart.
"""

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model."""


# SQLite needs check_same_thread=False because FastAPI runs sync endpoints in a
# threadpool, so a connection may be created on one thread and used on another.
# Each request still gets its own Session via get_db(), so this is safe.
_is_sqlite = settings.database_url.startswith("sqlite")
_connect_args = {"check_same_thread": False} if _is_sqlite else {}

engine = create_engine(
    settings.database_url,
    connect_args=_connect_args,
    echo=settings.sql_echo,
    future=True,
)


if _is_sqlite:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _connection_record):  # noqa: ANN001
        """Turn on foreign-key enforcement and a busy timeout for SQLite.

        Foreign keys are OFF by default in SQLite; without this the DB would
        happily let you delete a product that still has movements. The busy
        timeout lets concurrent writers wait for the write lock instead of
        immediately failing with 'database is locked'.
        """
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=True,
    future=True,
)


def get_db() -> Iterator[Session]:
    """Yield a request-scoped Session and always close it afterwards."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
