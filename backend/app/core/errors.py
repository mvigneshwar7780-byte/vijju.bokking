"""A single error vocabulary for the whole API.

Every failure the client can see is an ``AppError`` subclass, and every one of
them serialises to the same envelope:

    {"error": {"code": "SEAT_UNAVAILABLE", "message": "...", "details": {...}},
     "request_id": "..."}

Handlers are registered once in ``app.main``. Routers raise domain errors and
never build error responses by hand.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.core.logging import get_logger, request_id_ctx

logger = get_logger(__name__)


class AppError(Exception):
    """Base class for every error the API deliberately surfaces."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "APP_ERROR"
    message: str = "Something went wrong."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
        code: str | None = None,
        status_code: int | None = None,
    ) -> None:
        self.message = message or self.message
        self.details = details or {}
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        super().__init__(self.message)

    def to_payload(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            },
            "request_id": request_id_ctx.get(),
        }


# --------------------------------------------------------------- generic ---
class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "NOT_FOUND"
    message = "The requested resource does not exist."


class ValidationError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "VALIDATION_ERROR"
    message = "The request payload is invalid."


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "CONFLICT"
    message = "The request conflicts with the current state."


class RateLimitedError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "RATE_LIMITED"
    message = "Too many requests. Slow down."


# ------------------------------------------------------------------ auth ---
class AuthenticationError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "UNAUTHENTICATED"
    message = "Authentication is required."


class PermissionDeniedError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "FORBIDDEN"
    message = "You do not have permission to perform this action."


# --------------------------------------------------------------- booking ---
class SeatUnavailableError(ConflictError):
    code = "SEAT_UNAVAILABLE"
    message = "One or more of the selected seats is no longer available."


class HoldExpiredError(ConflictError):
    code = "HOLD_EXPIRED"
    message = "Your seat hold expired. Please select your seats again."


class SeatRuleViolationError(ValidationError):
    code = "SEAT_RULE_VIOLATION"
    message = "The seat selection violates a booking rule."


class ShowNotBookableError(ConflictError):
    code = "SHOW_NOT_BOOKABLE"
    message = "This show is no longer open for booking."


class BookingStateError(ConflictError):
    code = "BOOKING_STATE_INVALID"
    message = "The booking is not in a state that allows this operation."


# -------------------------------------------------------------- payments ---
class PaymentError(AppError):
    status_code = status.HTTP_402_PAYMENT_REQUIRED
    code = "PAYMENT_FAILED"
    message = "The payment could not be completed."


class IdempotencyConflictError(ConflictError):
    code = "IDEMPOTENCY_CONFLICT"
    message = "This idempotency key was already used with a different payload."


# -------------------------------------------------------------------- ai ---
class AIUnavailableError(AppError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "AI_UNAVAILABLE"
    message = "The AI service is not available right now."


class AIBudgetExceededError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "AI_BUDGET_EXCEEDED"
    message = "The AI token budget for today has been exhausted."


# ----------------------------------------------------------- registration ---
def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        logger.info("app_error", code=exc.code, message=exc.message, details=exc.details)
        return JSONResponse(status_code=exc.status_code, content=exc.to_payload())

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        err = ValidationError(details={"errors": _clean_validation_errors(exc.errors())})
        return JSONResponse(status_code=err.status_code, content=err.to_payload())

    @app.exception_handler(IntegrityError)
    async def _integrity(_: Request, exc: IntegrityError) -> JSONResponse:
        # A constraint we did not translate into a domain error. Surface it as a
        # conflict rather than a 500 -- but log loudly, it usually means a
        # missing guard in a service.
        logger.warning("integrity_error", error=str(exc.orig))
        err = ConflictError("The operation violated a database constraint.")
        return JSONResponse(status_code=err.status_code, content=err.to_payload())

    @app.exception_handler(SQLAlchemyError)
    async def _sqlalchemy(_: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.error("database_error", error=str(exc), exc_info=True)
        err = AppError(
            "A database error occurred.",
            code="DATABASE_ERROR",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
        return JSONResponse(status_code=err.status_code, content=err.to_payload())

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled_error", error=str(exc), exc_info=True)
        err = AppError(
            "Internal server error.",
            code="INTERNAL_ERROR",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
        return JSONResponse(status_code=err.status_code, content=err.to_payload())


def _clean_validation_errors(errors: list[Any]) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for err in errors:
        cleaned.append(
            {
                "field": ".".join(str(p) for p in err.get("loc", ())),
                "message": err.get("msg", ""),
                "type": err.get("type", ""),
            }
        )
    return cleaned
