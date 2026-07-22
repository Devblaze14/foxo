"""Domain exceptions.

Each maps to an HTTP status and a stable machine-readable ``code`` so API
consumers can branch on failures without string-matching messages. They are
translated into a consistent JSON envelope by handlers in ``main.py``.
"""


class AppError(Exception):
    """Base class for all expected, handled application errors."""

    status_code: int = 400
    code: str = "app_error"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class ProductNotFound(AppError):
    status_code = 404
    code = "product_not_found"


class DuplicateSKU(AppError):
    status_code = 409
    code = "duplicate_sku"


class ProductInactive(AppError):
    status_code = 409
    code = "product_inactive"


class ProductHasMovements(AppError):
    status_code = 409
    code = "product_has_movements"


class InsufficientStock(AppError):
    status_code = 409
    code = "insufficient_stock"


class ConcurrencyConflict(AppError):
    status_code = 409
    code = "concurrent_update_conflict"


class ImmutableRecordError(AppError):
    status_code = 409
    code = "immutable_record"
