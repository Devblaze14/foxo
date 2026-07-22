"""FastAPI application entrypoint.

Creates the app, registers routers, and translates domain exceptions into a
consistent JSON error envelope:

    {"error": {"code": "insufficient_stock", "message": "..."}}
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse

from app import __version__
from app.database import Base, engine
from app.exceptions import AppError
from app.routers import alerts, movements, products


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Simple auto-create for the take-home. In production this is replaced by
    # Alembic migrations (see README "Future improvements").
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Inventory & Stock-Movement Service",
    version=__version__,
    summary="Track stock levels and an immutable ledger of every stock movement.",
    lifespan=lifespan,
)


@app.exception_handler(AppError)
async def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


@app.exception_handler(RequestValidationError)
async def handle_validation_error(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    # Keep only JSON-safe fields (the raw error 'ctx' can hold exception objects).
    details = [
        {"type": e.get("type"), "loc": list(e.get("loc", [])), "msg": e.get("msg")}
        for e in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": {
                "code": "validation_error",
                "message": "Request validation failed",
                "details": details,
            }
        },
    )


app.include_router(products.router)
app.include_router(movements.router)
app.include_router(alerts.router)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/docs")
