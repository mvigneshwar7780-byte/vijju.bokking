"""Payment orchestration: create order -> settle via webhook -> confirm or refund.

The critical path is `process_webhook`. Read it as a set of guarantees:

1. **Signature first.** An event with a bad signature is recorded and rejected.
   Nothing else is allowed to look at its contents.
2. **Record before act.** The event row is inserted before any effect is
   applied. The unique index on ``(gateway, event_id)`` turns at-least-once
   delivery into exactly-once processing.
3. **Confirm or refund, never neither.** If the seats can no longer be
   delivered, the payment is flagged and a refund is created in the same
   transaction that expires the booking. There is no code path where money is
   captured and nothing happens.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import BookingStatus, PaymentStatus, RefundStatus
from app.core.errors import (
    BookingStateError,
    ConflictError,
    HoldExpiredError,
    NotFoundError,
    PaymentError,
)
from app.core.logging import get_logger
from app.modules.booking.models import Booking
from app.modules.booking.service import BookingService
from app.modules.inventory.models import SeatHold
from app.modules.payments.gateways.base import GatewayError, WebhookEvent
from app.modules.payments.gateways.mock import MockGateway, get_mock_gateway
from app.modules.payments.models import Payment, PaymentEvent, Refund

logger = get_logger(__name__)

# How much longer than the seat hold the customer gets once they reach the
# payment page. Keeping it *shorter* than the hold would guarantee the exact
# failure we are trying to avoid.
PAYMENT_WINDOW_SECONDS = 600


def get_gateway() -> MockGateway:
    """Resolve the configured gateway.

    Only the mock is implemented; a real one drops in here without any caller
    changing. The return type stays concrete on purpose so the mock-only helper
    ``authorize_and_capture`` is reachable from the simulation endpoint.
    """
    if settings.payment_gateway != "mock":
        raise PaymentError(
            f"Payment gateway '{settings.payment_gateway}' is not implemented yet. "
            "Set PAYMENT_GATEWAY=mock.",
            code="GATEWAY_NOT_CONFIGURED",
        )
    return get_mock_gateway()


class PaymentService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.gateway = get_gateway()
        self.bookings = BookingService(db)

    # ==================================================================
    # Starting a payment
    # ==================================================================
    def start_payment(self, booking: Booking, *, method: str = "upi") -> Payment:
        if booking.status == BookingStatus.CONFIRMED:
            raise BookingStateError("This booking is already paid for.")
        if booking.status not in (BookingStatus.DRAFT, BookingStatus.PAYMENT_PENDING,
                                  BookingStatus.PAYMENT_FAILED):
            raise BookingStateError(
                f"Cannot pay for a booking in state '{booking.status.value}'."
            )

        # Reuse an in-flight order rather than creating a second one -- two open
        # orders for one booking is how customers get charged twice.
        existing = self.db.execute(
            select(Payment).where(
                Payment.booking_id == booking.id,
                Payment.status.in_(
                    [PaymentStatus.CREATED, PaymentStatus.PROCESSING, PaymentStatus.AUTHORIZED]
                ),
            )
        ).scalar_one_or_none()
        if existing is not None:
            self._extend_hold_for_payment(booking)
            return existing

        # Push the hold out *before* handing the customer to the gateway. If the
        # hold would expire mid-checkout the customer gets a clear failure now
        # rather than a refund later.
        self._extend_hold_for_payment(booking)

        # The idempotency key is scoped to the *attempt*, not the booking.
        #
        # `booking:{id}` looks right and is wrong: after a cancelled or declined
        # payment the customer retries, the gateway recognises the key and hands
        # back the original -- now dead -- order, and inserting a second payment
        # row against that order id violates the unique constraint. The customer
        # sees a 409 and cannot pay at all.
        #
        # Counting prior attempts keeps genuine duplicate submissions of the
        # same request deduped, while letting a real retry open a new order.
        attempt = self.db.execute(
            select(func.count())
            .select_from(Payment)
            .where(Payment.booking_id == booking.id)
        ).scalar_one()

        try:
            order = self.gateway.create_order(
                amount_minor=booking.total_minor,
                currency=booking.currency,
                reference=booking.booking_reference,
                idempotency_key=f"booking:{booking.id}:attempt:{attempt}",
                metadata={
                    "booking_id": str(booking.id),
                    "show_id": str(booking.show_id),
                    "attempt": attempt,
                },
            )
        except GatewayError as exc:
            raise PaymentError(str(exc), code=exc.code) from exc

        payment = Payment(
            booking_id=booking.id,
            gateway=self.gateway.name,
            gateway_order_id=order.order_id,
            amount_minor=booking.total_minor,
            currency=booking.currency,
            status=PaymentStatus.CREATED,
            method=method,
            gateway_payload=order.raw,
        )
        self.db.add(payment)
        booking.status = BookingStatus.PAYMENT_PENDING
        self.db.flush()

        logger.info(
            "payment_started",
            booking_id=str(booking.id),
            payment_id=str(payment.id),
            order_id=order.order_id,
            amount_minor=payment.amount_minor,
        )
        return payment

    def _extend_hold_for_payment(self, booking: Booking) -> None:
        if booking.hold_id is None:
            raise BookingStateError("Booking has no seat hold.")
        try:
            new_expiry = self.bookings.inventory.extend_hold(
                booking.hold_id, seconds=PAYMENT_WINDOW_SECONDS
            )
        except HoldExpiredError:
            self.bookings.expire_booking(booking)
            raise
        booking.payment_deadline_at = new_expiry
        self.db.flush()

    # ==================================================================
    # Webhooks -- the only thing that moves money state
    # ==================================================================
    def process_webhook(self, *, raw_body: bytes, signature: str) -> dict:
        try:
            event = self.gateway.verify_webhook(raw_body=raw_body, signature=signature)
        except GatewayError as exc:
            raise PaymentError(str(exc), code=exc.code) from exc

        if not event.signature_valid:
            # Recorded so a signing-key mismatch or an attack is visible, but no
            # effect is applied and the payload is not trusted.
            self.db.add(
                PaymentEvent(
                    gateway=self.gateway.name,
                    event_id=event.event_id or f"unsigned_{uuid.uuid4().hex}",
                    event_type=event.event_type or "unknown",
                    signature_valid=False,
                    payload=event.payload,
                    processing_error="Invalid signature",
                )
            )
            self.db.commit()
            logger.warning("webhook_signature_invalid", event_id=event.event_id)
            raise PaymentError("Webhook signature verification failed.", code="BAD_SIGNATURE")

        # --- Step 2: record before acting -----------------------------
        already = self.db.execute(
            select(PaymentEvent).where(
                PaymentEvent.gateway == self.gateway.name,
                PaymentEvent.event_id == event.event_id,
            )
        ).scalar_one_or_none()
        if already is not None:
            logger.info("webhook_duplicate_ignored", event_id=event.event_id)
            return {"status": "duplicate", "event_id": event.event_id}

        payment = self.db.execute(
            select(Payment).where(
                Payment.gateway == self.gateway.name,
                Payment.gateway_order_id == event.order_id,
            )
        ).scalar_one_or_none()

        record = PaymentEvent(
            payment_id=payment.id if payment else None,
            gateway=self.gateway.name,
            event_id=event.event_id,
            event_type=event.event_type,
            signature_valid=True,
            payload=event.payload,
        )
        self.db.add(record)
        self.db.flush()

        if payment is None:
            record.processing_error = "No matching payment for order"
            self.db.commit()
            logger.warning("webhook_orphan_order", order_id=event.order_id)
            return {"status": "orphan", "event_id": event.event_id}

        # --- Step 3: apply the effect ---------------------------------
        try:
            result = self._apply_event(event, payment)
            record.processed_at = datetime.now(UTC)
            self.db.commit()
            return result
        except Exception as exc:  # noqa: BLE001
            self.db.rollback()
            # Re-record the failure on a clean transaction so the event is not
            # lost and can be retried or investigated.
            self.db.add(
                PaymentEvent(
                    payment_id=payment.id,
                    gateway=self.gateway.name,
                    event_id=f"{event.event_id}:error",
                    event_type=event.event_type,
                    signature_valid=True,
                    payload=event.payload,
                    processing_error=str(exc),
                )
            )
            self.db.commit()
            logger.error("webhook_processing_failed", event_id=event.event_id, error=str(exc))
            raise

    def _apply_event(self, event: WebhookEvent, payment: Payment) -> dict:
        booking = self.db.get(Booking, payment.booking_id)
        if booking is None:
            raise NotFoundError("Payment references a missing booking.")

        match event.event_type:
            case "payment.captured":
                return self._on_captured(event, payment, booking)
            case "payment.failed":
                return self._on_failed(event, payment, booking)
            case "payment.cancelled":
                return self._on_cancelled(event, payment, booking)
            case "payment.pending":
                return self._on_pending(event, payment, booking)
            case "refund.succeeded":
                return self._on_refund_succeeded(event, payment)
            case _:
                logger.info("webhook_unhandled_type", event_type=event.event_type)
                return {"status": "ignored", "event_type": event.event_type}

    def _on_captured(self, event: WebhookEvent, payment: Payment, booking: Booking) -> dict:
        # Amount check: never trust the event to agree with what we asked for.
        if event.amount_minor is not None and event.amount_minor != payment.amount_minor:
            payment.status = PaymentStatus.FAILED
            payment.failure_code = "amount_mismatch"
            payment.failure_message = (
                f"Gateway captured {event.amount_minor} but the order was {payment.amount_minor}."
            )
            payment.requires_auto_refund = True
            self.bookings.mark_payment_failed(booking, reason="Payment amount mismatch.")
            logger.error(
                "payment_amount_mismatch",
                payment_id=str(payment.id),
                expected=payment.amount_minor,
                got=event.amount_minor,
            )
            return {"status": "amount_mismatch"}

        payment.status = PaymentStatus.CAPTURED
        payment.gateway_payment_id = event.payment_id
        payment.captured_at = datetime.now(UTC)
        payment.authorized_at = payment.authorized_at or payment.captured_at
        payment.method = event.payload.get("data", {}).get("method") or payment.method
        self.db.flush()

        try:
            self.bookings.confirm_booking(booking)
        except HoldExpiredError:
            # THE case this whole design exists to handle: the money is ours but
            # the seats are not. Expire the booking and refund, in this same
            # transaction, so the two can never diverge.
            logger.error(
                "payment_captured_but_seats_lost",
                booking_id=str(booking.id),
                payment_id=str(payment.id),
            )
            self.bookings.expire_booking(booking)
            payment.requires_auto_refund = True
            self._create_refund(
                payment=payment,
                booking=booking,
                amount_minor=payment.amount_minor,
                reason="seats_unavailable",
            )
            return {"status": "refunded_seats_lost", "booking_id": str(booking.id)}

        return {"status": "confirmed", "booking_id": str(booking.id)}

    def _on_failed(self, event: WebhookEvent, payment: Payment, booking: Booking) -> dict:
        data = event.payload.get("data", {})
        payment.status = PaymentStatus.FAILED
        payment.failure_code = data.get("failure_code")
        payment.failure_message = data.get("failure_message")
        self.bookings.mark_payment_failed(
            booking, reason=data.get("failure_message") or "Payment failed."
        )
        return {"status": "failed", "booking_id": str(booking.id)}

    def _on_cancelled(self, event: WebhookEvent, payment: Payment, booking: Booking) -> dict:
        """The customer walked away from the checkout page.

        Deliberately *not* treated as a failure. Nothing was declined, so:

        * the payment is marked ``cancelled``, which keeps decline-rate
          reporting honest, and
        * the booking goes back to ``draft`` with its seat hold **intact**, so
          the customer can simply try again with a different method.

        Releasing the seats here would be the obvious move and the wrong one --
        it would punish a customer who hit "back" by giving their seats away
        mid-checkout. The hold's TTL already bounds how long they can sit on
        them, and the sweeper reclaims them if nobody comes back.
        """
        if booking.status == BookingStatus.CONFIRMED:
            logger.warning("late_cancel_for_confirmed_booking", booking_id=str(booking.id))
            return {"status": "ignored", "reason": "already_confirmed"}

        payment.status = PaymentStatus.CANCELLED
        payment.failure_code = "user_cancelled"
        payment.failure_message = (
            event.payload.get("data", {}).get("failure_message")
            or "Cancelled at the payment page."
        )

        hold_alive = False
        if booking.hold_id:
            hold = self.db.get(SeatHold, booking.hold_id)
            hold_alive = bool(hold and hold.is_live)

        booking.status = BookingStatus.DRAFT if hold_alive else BookingStatus.EXPIRED
        if not hold_alive:
            booking.cancellation_reason = (
                "Payment was cancelled and the seat hold had already expired."
            )
        self.db.flush()

        logger.info(
            "payment_cancelled",
            booking_id=str(booking.id),
            retryable=hold_alive,
        )
        return {
            "status": "cancelled",
            "booking_id": str(booking.id),
            "retryable": hold_alive,
        }

    def _on_pending(self, event: WebhookEvent, payment: Payment, booking: Booking) -> dict:
        """Accepted, outcome unknown -- a UPI collect request awaiting approval.

        Nothing is decided here. The payment sits in ``processing`` and the
        booking stays ``payment_pending``; the seats remain held. Either the
        terminal webhook arrives, or `reconcile_pending_payments` asks the
        gateway what actually happened. What must *not* happen is optimistically
        confirming a booking that was never paid for.
        """
        if payment.status in (PaymentStatus.CAPTURED, PaymentStatus.FAILED):
            return {"status": "ignored", "reason": "already_settled"}

        payment.status = PaymentStatus.PROCESSING
        booking.status = BookingStatus.PAYMENT_PENDING
        self.db.flush()
        logger.info("payment_pending", booking_id=str(booking.id), payment_id=str(payment.id))
        return {"status": "pending", "booking_id": str(booking.id)}

    def _on_refund_succeeded(self, event: WebhookEvent, payment: Payment) -> dict:
        refund_id = event.payload.get("data", {}).get("refund_id")
        refund = self.db.execute(
            select(Refund).where(Refund.gateway_refund_id == refund_id)
        ).scalar_one_or_none()
        if refund is None:
            return {"status": "unknown_refund"}
        refund.status = RefundStatus.SUCCEEDED
        refund.completed_at = datetime.now(UTC)
        payment.amount_refunded_minor += refund.amount_minor
        payment.status = (
            PaymentStatus.REFUNDED
            if payment.amount_refunded_minor >= payment.amount_minor
            else PaymentStatus.PARTIALLY_REFUNDED
        )
        return {"status": "refunded"}

    # ==================================================================
    # Refunds
    # ==================================================================
    def _create_refund(
        self, *, payment: Payment, booking: Booking, amount_minor: int, reason: str
    ) -> Refund:
        # One refund per (booking, reason). A retried webhook cannot create a
        # second one -- the unique index rejects it.
        key = f"refund:{booking.id}:{reason}"
        existing = self.db.execute(
            select(Refund).where(Refund.idempotency_key == key)
        ).scalar_one_or_none()
        if existing is not None:
            return existing

        refund = Refund(
            payment_id=payment.id,
            booking_id=booking.id,
            amount_minor=amount_minor,
            reason=reason,
            idempotency_key=key,
            status=RefundStatus.PENDING,
        )
        self.db.add(refund)
        self.db.flush()

        try:
            result = self.gateway.refund(
                payment_id=payment.gateway_payment_id or "",
                amount_minor=amount_minor,
                idempotency_key=key,
                reason=reason,
            )
            refund.gateway_refund_id = result.refund_id
            if result.status == "succeeded":
                refund.status = RefundStatus.SUCCEEDED
                refund.completed_at = datetime.now(UTC)
                payment.amount_refunded_minor += amount_minor
                payment.status = (
                    PaymentStatus.REFUNDED
                    if payment.amount_refunded_minor >= payment.amount_minor
                    else PaymentStatus.PARTIALLY_REFUNDED
                )
                payment.requires_auto_refund = False
        except GatewayError as exc:
            # Leave it PENDING. The reconciliation worker retries; losing the
            # gateway call must not lose the obligation to repay.
            refund.failure_message = str(exc)
            logger.error("refund_call_failed", refund_id=str(refund.id), error=str(exc))

        self.db.flush()
        logger.info(
            "refund_created",
            refund_id=str(refund.id),
            booking_id=str(booking.id),
            amount_minor=amount_minor,
            reason=reason,
            status=refund.status.value,
        )
        return refund

    def refund_for_cancellation(
        self, booking: Booking, amount_minor: int, *, reason: str = "user_cancellation"
    ) -> Refund | None:
        if amount_minor <= 0:
            return None
        payment = self.db.execute(
            select(Payment).where(
                Payment.booking_id == booking.id,
                Payment.status.in_(
                    [PaymentStatus.CAPTURED, PaymentStatus.PARTIALLY_REFUNDED]
                ),
            )
        ).scalar_one_or_none()
        if payment is None:
            raise ConflictError("No captured payment to refund for this booking.")
        return self._create_refund(
            payment=payment, booking=booking, amount_minor=amount_minor, reason=reason
        )

    # ==================================================================
    # Reconciliation
    # ==================================================================
    def pending_auto_refunds(self, limit: int = 50) -> list[Payment]:
        return list(
            self.db.execute(
                select(Payment)
                .where(Payment.requires_auto_refund.is_(True))
                .order_by(Payment.created_at)
                .limit(limit)
            ).scalars()
        )

    def reconcile_pending_payments(
        self, *, older_than_minutes: int = 5, limit: int = 50
    ) -> dict[str, int]:
        """Ask the gateway what happened to payments we never heard back about.

        Webhooks get dropped. Endpoints return 500, networks partition,
        providers retry with backoff and give up. A booking system that only
        learns outcomes by webhook will therefore strand customers: money taken
        and no ticket, or seats held against a payment that failed an hour ago.

        This closes the loop from the other direction -- for each payment still
        in a non-terminal state past the grace period, fetch the authoritative
        status and feed it through the *same* webhook handler, so there is
        exactly one code path that can confirm a booking.
        """
        stale = self.stale_pending_payments(
            older_than_minutes=older_than_minutes, limit=limit
        )
        counts = {"checked": len(stale), "resolved": 0, "still_pending": 0, "errors": 0}

        for payment in stale:
            try:
                order = self.gateway.fetch_order(payment.gateway_order_id)
            except GatewayError as exc:
                counts["errors"] += 1
                logger.warning(
                    "reconcile_fetch_failed",
                    payment_id=str(payment.id),
                    order_id=payment.gateway_order_id,
                    error=str(exc),
                )
                continue

            if order.status in ("created", "processing"):
                counts["still_pending"] += 1
                continue

            # Replay it as a signed webhook rather than mutating state here.
            # One path to confirmation means reconciliation cannot drift from
            # the webhook's behaviour -- including its idempotency.
            event = self.gateway.build_event_for(order.order_id)
            raw_body, signature = self.gateway.encode_webhook(event)
            try:
                self.process_webhook(raw_body=raw_body, signature=signature)
                counts["resolved"] += 1
                logger.info(
                    "reconcile_resolved",
                    payment_id=str(payment.id),
                    outcome=event.event_type,
                )
            except Exception as exc:  # noqa: BLE001
                counts["errors"] += 1
                logger.error(
                    "reconcile_apply_failed", payment_id=str(payment.id), error=str(exc)
                )

        if counts["resolved"] or counts["errors"]:
            logger.info("payment_reconciliation", **counts)
        return counts

    def cancel_payment(self, booking: Booking, *, reason: str = "user_cancelled") -> dict:
        """The customer explicitly abandoned checkout, from our own UI.

        Routed through the gateway and the webhook handler rather than flipping
        state directly, so an in-app cancel and a cancel at the hosted page end
        in exactly the same place.
        """
        payment = self.db.execute(
            select(Payment).where(
                Payment.booking_id == booking.id,
                Payment.status.in_(
                    [PaymentStatus.CREATED, PaymentStatus.PROCESSING]
                ),
            ).order_by(Payment.created_at.desc())
        ).scalars().first()
        if payment is None:
            raise ConflictError(
                "There is no payment in progress for this booking.",
                code="NO_PAYMENT_IN_PROGRESS",
            )

        event = self.gateway.authorize_and_capture(
            payment.gateway_order_id, force_outcome="cancel"
        )
        raw_body, signature = self.gateway.encode_webhook(event)
        return self.process_webhook(raw_body=raw_body, signature=signature)

    def stale_pending_payments(self, older_than_minutes: int = 30, limit: int = 100) -> list[Payment]:
        """Payments we never heard back about.

        A missing webhook is not a rare event in production -- networks drop,
        endpoints 500, providers retry with backoff. This is the list the
        reconciliation job walks, calling ``fetch_order`` on each to ask the
        gateway what actually happened rather than assuming.
        """
        cutoff = datetime.now(UTC) - timedelta(minutes=older_than_minutes)
        return list(
            self.db.execute(
                select(Payment)
                .where(
                    Payment.status.in_([PaymentStatus.CREATED, PaymentStatus.PROCESSING]),
                    Payment.created_at < cutoff,
                )
                .order_by(Payment.created_at)
                .limit(limit)
            ).scalars()
        )
