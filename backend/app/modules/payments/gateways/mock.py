"""A fake PSP that behaves like a real one.

This exists so the *entire* payment flow -- server-side order creation, a hosted
checkout step, asynchronous signed webhooks, replayed deliveries, failures,
latency and refunds -- can be exercised with no PSP account and no internet.

What it faithfully reproduces:

* Orders live server-side; the amount is fixed at creation and the client cannot
  alter it.
* The outcome arrives **asynchronously via a signed webhook**, not from the
  browser's redirect. The redirect only tells the UI where to look.
* Webhooks carry an HMAC signature over the raw body, verified before parsing.
* Events have stable ids and may be delivered more than once.
* Configurable artificial latency and failure rate, so the unhappy paths can be
  tested on purpose rather than hoped about.

What it does not do: real network calls, 3-D Secure, or partial captures.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
import uuid
from datetime import UTC, datetime

from app.core.config import settings
from app.core.logging import get_logger
from app.modules.payments.gateways.base import (
    GatewayError,
    GatewayOrder,
    GatewayRefund,
    WebhookEvent,
)

logger = get_logger(__name__)


class MockGateway:
    """In-process PSP. State lives in the `payments` table, not here."""

    name = "mock"

    def __init__(self) -> None:
        self._orders: dict[str, dict] = {}
        self._idempotency: dict[str, str] = {}

    # ------------------------------------------------------------------
    def _latency(self) -> None:
        if settings.mock_gateway_latency_ms:
            time.sleep(settings.mock_gateway_latency_ms / 1000.0)

    def create_order(
        self,
        *,
        amount_minor: int,
        currency: str,
        reference: str,
        idempotency_key: str,
        metadata: dict | None = None,
    ) -> GatewayOrder:
        if amount_minor <= 0:
            raise GatewayError("Amount must be positive.", code="INVALID_AMOUNT")

        # Real gateways dedupe on the idempotency key; so do we, so retry logic
        # in the caller can be tested honestly.
        if existing_id := self._idempotency.get(idempotency_key):
            return self._to_order(self._orders[existing_id])

        self._latency()
        order_id = f"mock_ord_{secrets.token_hex(10)}"
        record = {
            "order_id": order_id,
            "amount_minor": amount_minor,
            "currency": currency,
            "reference": reference,
            "status": "created",
            "payment_id": None,
            "method": None,
            "failure_code": None,
            "failure_message": None,
            "metadata": metadata or {},
            "created_at": datetime.now(UTC).isoformat(),
        }
        self._orders[order_id] = record
        self._idempotency[idempotency_key] = order_id
        logger.info("mock_gateway_order_created", order_id=order_id, amount_minor=amount_minor)
        return self._to_order(record)

    def fetch_order(self, order_id: str) -> GatewayOrder:
        record = self._orders.get(order_id)
        if record is None:
            raise GatewayError("Unknown order.", code="ORDER_NOT_FOUND")
        return self._to_order(record)

    # ------------------------------------------------------------------
    #: Every outcome a real hosted checkout can produce.
    OUTCOMES = ("success", "failure", "cancel", "pending")

    def authorize_and_capture(
        self, order_id: str, *, method: str = "upi", force_outcome: str | None = None
    ) -> WebhookEvent:
        """Simulate the customer finishing at the hosted checkout.

        Returns the webhook event the PSP *would* send. The caller delivers it
        to the webhook handler, so the production path (verify signature ->
        record event -> apply effect) is identical whether the event came from
        here or from a real PSP over HTTP.

        Four outcomes, because a real gateway has four:

        ``success``  captured.
        ``failure``  declined by the bank -- a statement about the payment
                     method.
        ``cancel``   the customer closed the tab or pressed back. Nothing was
                     declined; conflating this with ``failure`` misreports both
                     the error shown to the customer and any decline-rate read.
        ``pending``  accepted, outcome unknown. Genuinely common for UPI collect
                     and netbanking, where approval can take minutes. The
                     terminal event arrives later -- or never, which is what
                     reconciliation exists for.
        """
        record = self._orders.get(order_id)
        if record is None:
            raise GatewayError("Unknown order.", code="ORDER_NOT_FOUND")
        if record["status"] in ("captured", "failed", "cancelled"):
            # Already settled: re-emit the same event so a retry is a no-op.
            return self._build_event(record)

        self._latency()

        outcome = force_outcome
        if outcome not in self.OUTCOMES:
            outcome = (
                "failure"
                if secrets.randbelow(10_000)
                < int(settings.mock_gateway_failure_rate * 10_000)
                else "success"
            )

        match outcome:
            case "failure":
                record.update(
                    status="failed",
                    failure_code="card_declined",
                    failure_message="The bank declined this transaction.",
                    method=method,
                )
            case "cancel":
                record.update(
                    status="cancelled",
                    failure_code="user_cancelled",
                    failure_message="The customer cancelled at the payment page.",
                    method=method,
                )
            case "pending":
                # No terminal state yet: the order stays open so a later
                # settle_pending() -- or reconciliation -- can resolve it.
                record.update(status="processing", method=method)
            case _:
                record.update(
                    status="captured",
                    payment_id=f"mock_pay_{secrets.token_hex(10)}",
                    method=method,
                )

        record["settled_at"] = datetime.now(UTC).isoformat()
        return self._build_event(record)

    def settle_pending(self, order_id: str, *, outcome: str = "success") -> WebhookEvent:
        """Resolve an order left in `processing`, as a delayed webhook would."""
        record = self._orders.get(order_id)
        if record is None:
            raise GatewayError("Unknown order.", code="ORDER_NOT_FOUND")
        if record["status"] != "processing":
            return self._build_event(record)
        record["status"] = "created"  # allow the state machine to move again
        return self.authorize_and_capture(
            order_id, method=record.get("method") or "upi", force_outcome=outcome
        )

    def build_event_for(self, order_id: str) -> WebhookEvent:
        """The event this order's current state would produce.

        Used by reconciliation to replay an outcome we never received.
        """
        record = self._orders.get(order_id)
        if record is None:
            raise GatewayError("Unknown order.", code="ORDER_NOT_FOUND")
        return self._build_event(record)

    def refund(
        self, *, payment_id: str, amount_minor: int, idempotency_key: str, reason: str
    ) -> GatewayRefund:
        self._latency()
        record = next(
            (r for r in self._orders.values() if r.get("payment_id") == payment_id), None
        )
        if record is None:
            raise GatewayError("Unknown payment.", code="PAYMENT_NOT_FOUND")
        if amount_minor > record["amount_minor"]:
            raise GatewayError("Refund exceeds captured amount.", code="REFUND_TOO_LARGE")
        logger.info(
            "mock_gateway_refund", payment_id=payment_id, amount_minor=amount_minor, reason=reason
        )
        return GatewayRefund(
            refund_id=f"mock_rfnd_{secrets.token_hex(8)}",
            amount_minor=amount_minor,
            status="succeeded",
            raw={"reason": reason, "idempotency_key": idempotency_key},
        )

    # ------------------------------------------------------------------
    # Webhook signing / verification
    # ------------------------------------------------------------------
    @staticmethod
    def sign(raw_body: bytes) -> str:
        return hmac.new(
            settings.payment_webhook_secret.encode(), raw_body, hashlib.sha256
        ).hexdigest()

    def verify_webhook(self, *, raw_body: bytes, signature: str) -> WebhookEvent:
        expected = self.sign(raw_body)
        # compare_digest, not ==: a timing-safe comparison is the whole point of
        # signing in the first place.
        valid = hmac.compare_digest(expected, signature or "")
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise GatewayError("Webhook body is not valid JSON.", code="BAD_PAYLOAD") from exc

        data = payload.get("data", {})
        return WebhookEvent(
            event_id=payload.get("id", ""),
            event_type=payload.get("type", ""),
            order_id=data.get("order_id"),
            payment_id=data.get("payment_id"),
            amount_minor=data.get("amount_minor"),
            signature_valid=valid,
            payload=payload,
        )

    def encode_webhook(self, event: WebhookEvent) -> tuple[bytes, str]:
        """Serialise an event the way the PSP would, and sign it."""
        body = json.dumps(event.payload, separators=(",", ":"), sort_keys=True).encode()
        return body, self.sign(body)

    # ------------------------------------------------------------------
    #: Internal order state -> the webhook event type a PSP would emit.
    EVENT_TYPE_FOR_STATUS = {
        "captured": "payment.captured",
        "failed": "payment.failed",
        "cancelled": "payment.cancelled",
        "processing": "payment.pending",
    }

    def _build_event(self, record: dict) -> WebhookEvent:
        # Event id is derived from the order and outcome, so a re-delivery of
        # the same settlement carries the same id and the receiver dedupes it.
        event_id = f"mock_evt_{uuid.uuid5(uuid.NAMESPACE_OID, record['order_id'] + record['status']).hex[:20]}"
        payload = {
            "id": event_id,
            "type": self.EVENT_TYPE_FOR_STATUS.get(record["status"], "payment.failed"),
            "created_at": record.get("settled_at"),
            "data": {
                "order_id": record["order_id"],
                "payment_id": record.get("payment_id"),
                "amount_minor": record["amount_minor"],
                "currency": record["currency"],
                "method": record.get("method"),
                "reference": record["reference"],
                "failure_code": record.get("failure_code"),
                "failure_message": record.get("failure_message"),
            },
        }
        return WebhookEvent(
            event_id=event_id,
            event_type=payload["type"],
            order_id=record["order_id"],
            payment_id=record.get("payment_id"),
            amount_minor=record["amount_minor"],
            signature_valid=True,
            payload=payload,
        )

    @staticmethod
    def _to_order(record: dict) -> GatewayOrder:
        return GatewayOrder(
            order_id=record["order_id"],
            amount_minor=record["amount_minor"],
            currency=record["currency"],
            status=record["status"],
            checkout_url=f"/checkout/mock/{record['order_id']}",
            payment_id=record.get("payment_id"),
            method=record.get("method"),
            failure_code=record.get("failure_code"),
            failure_message=record.get("failure_message"),
            raw=dict(record),
        )


# One instance per process. State is intentionally in-memory: it is a *fake*
# external system, and a restart losing pending fake orders is the same as a
# real PSD outage, which the reconciliation path already has to handle.
_gateway = MockGateway()


def get_mock_gateway() -> MockGateway:
    return _gateway
