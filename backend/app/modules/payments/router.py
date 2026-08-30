"""Payment endpoints.

Three groups, and the distinction matters:

* ``/bookings/{id}/pay``   -- the app's own API. Starts a payment.
* ``/payments/webhook/*``  -- what the gateway calls. The only route that is
  allowed to change money state, and it authenticates by signature, not by JWT.
* ``/payments/mock/*``     -- the fake PSP's "hosted checkout". Exists only in
  the mock gateway and is refused when a real gateway is configured.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Header, Request, status

from app.core.config import settings
from app.core.deps import DbSession, OptionalUser
from app.core.errors import NotFoundError, PermissionDeniedError
from app.core.logging import get_logger
from app.modules.booking.schemas import StartPaymentOut, StartPaymentRequest
from app.modules.booking.service import BookingService
from app.modules.payments.service import PaymentService, get_gateway

logger = get_logger(__name__)

router = APIRouter(tags=["payments"])

# Deliberately separate from `router`: webhooks are unauthenticated-by-JWT and
# must never accidentally inherit a router-level auth dependency.
webhook_router = APIRouter(tags=["payments:webhook"])


@router.post("/bookings/{booking_id}/pay", response_model=StartPaymentOut)
def start_payment(
    booking_id: uuid.UUID,
    payload: StartPaymentRequest,
    db: DbSession,
    user: OptionalUser,
) -> StartPaymentOut:
    """Create a gateway order for a draft booking and extend the seat hold."""
    bookings = BookingService(db)
    booking = bookings.get(booking_id)
    if booking.user_id is not None and (user is None or booking.user_id != user.id):
        raise PermissionDeniedError("That booking belongs to someone else.")

    payment = PaymentService(db).start_payment(booking, method=payload.method)
    db.commit()

    order = get_gateway().fetch_order(payment.gateway_order_id)
    return StartPaymentOut(
        payment_id=payment.id,
        booking_id=booking.id,
        gateway=payment.gateway,
        gateway_order_id=payment.gateway_order_id,
        checkout_url=order.checkout_url,
        amount_minor=payment.amount_minor,
        currency=payment.currency,
        expires_at=booking.payment_deadline_at,
    )


# ---------------------------------------------------------------------------
# The gateway -> us direction
# ---------------------------------------------------------------------------
@webhook_router.post("/payments/webhook/{gateway_name}", status_code=status.HTTP_200_OK)
async def payment_webhook(
    gateway_name: str,
    request: Request,
    db: DbSession,
    x_signature: str = Header(default="", alias="X-Signature"),
) -> dict:
    """Receive a settlement event.

    Reads the **raw** body, not the parsed JSON: the signature covers the exact
    bytes, and re-serialising would change them and break verification.

    Always returns 200 for a duplicate or an orphan. A gateway that gets a 500
    retries forever; telling it "received" while recording the anomaly for a
    human is the correct behaviour.
    """
    if gateway_name != settings.payment_gateway:
        raise NotFoundError("Unknown gateway.")
    raw = await request.body()
    return PaymentService(db).process_webhook(raw_body=raw, signature=x_signature)


# ---------------------------------------------------------------------------
# The fake hosted checkout (mock gateway only)
# ---------------------------------------------------------------------------
@router.post("/bookings/{booking_id}/payment/cancel")
def cancel_payment(
    booking_id: uuid.UUID, db: DbSession, user: OptionalUser
) -> dict:
    """Abandon an in-progress payment without losing the seats.

    The booking returns to `draft` with its hold intact, so the customer can
    retry with another method. If the hold has already lapsed the booking is
    expired instead -- and the response says which, so the UI can either offer
    "try again" or send them back to the seat map.
    """
    booking = BookingService(db).get(booking_id)
    if booking.user_id is not None and (user is None or booking.user_id != user.id):
        raise PermissionDeniedError("That booking belongs to someone else.")
    return PaymentService(db).cancel_payment(booking)


@router.post("/payments/mock/{order_id}/complete")
def mock_complete_checkout(
    order_id: str,
    db: DbSession,
    outcome: str = "success",
    method: str = "upi",
) -> dict:
    """Stand-in for the customer finishing on the PSP's hosted page.

    It does *not* confirm anything itself. It asks the fake gateway to settle,
    then feeds the resulting signed event through the very same
    ``process_webhook`` path a real gateway would hit -- so the code that
    confirms bookings is exercised identically in development and production.

    ``outcome`` selects which of the four real outcomes to simulate:
    ``success``, ``failure`` (declined), ``cancel`` (customer walked away) or
    ``pending`` (accepted, answer later) -- so every unhappy path is reachable
    on purpose rather than by luck.
    """
    if settings.payment_gateway != "mock":
        raise NotFoundError("The mock checkout is only available with the mock gateway.")

    gateway = get_gateway()
    event = gateway.authorize_and_capture(
        order_id,
        method=method,
        force_outcome=outcome if outcome in gateway.OUTCOMES else None,
    )
    raw_body, signature = gateway.encode_webhook(event)
    result = PaymentService(db).process_webhook(raw_body=raw_body, signature=signature)
    return {"outcome": event.event_type, **result}


@router.post("/payments/mock/{order_id}/settle")
def mock_settle_pending(order_id: str, db: DbSession, outcome: str = "success") -> dict:
    """Deliver the delayed webhook for an order left `pending`.

    Stands in for the customer finally approving (or rejecting) a UPI collect
    request minutes after checkout.
    """
    if settings.payment_gateway != "mock":
        raise NotFoundError("The mock checkout is only available with the mock gateway.")
    gateway = get_gateway()
    event = gateway.settle_pending(order_id, outcome=outcome)
    raw_body, signature = gateway.encode_webhook(event)
    result = PaymentService(db).process_webhook(raw_body=raw_body, signature=signature)
    return {"outcome": event.event_type, **result}


@router.get("/payments/mock/{order_id}")
def mock_order_status(order_id: str) -> dict:
    if settings.payment_gateway != "mock":
        raise NotFoundError("The mock checkout is only available with the mock gateway.")
    order = get_gateway().fetch_order(order_id)
    return {
        "order_id": order.order_id,
        "status": order.status,
        "amount_minor": order.amount_minor,
        "currency": order.currency,
        "payment_id": order.payment_id,
    }
