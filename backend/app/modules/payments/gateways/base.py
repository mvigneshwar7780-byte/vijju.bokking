"""The payment gateway seam.

Everything the app knows about taking money is this interface. Swapping the mock
for Razorpay or Stripe means writing one new class and changing one setting --
no booking, inventory or API code moves.

The interface is shaped after how real PSPs actually behave, not after what is
convenient:

* ``create_order`` happens **server-side** and returns an id the client cannot
  forge. The browser never tells us the amount.
* The client's return from the hosted page is a *hint*. ``verify_webhook`` is
  the only thing that changes money state.
* Every mutating call takes an idempotency key, because networks retry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class GatewayOrder:
    order_id: str
    amount_minor: int
    currency: str
    status: str                       # created | authorized | captured | failed
    checkout_url: str | None = None
    payment_id: str | None = None
    method: str | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GatewayRefund:
    refund_id: str
    amount_minor: int
    status: str                       # pending | succeeded | failed
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WebhookEvent:
    event_id: str
    event_type: str                   # payment.captured | payment.failed | refund.succeeded
    order_id: str | None
    payment_id: str | None
    amount_minor: int | None
    signature_valid: bool
    payload: dict = field(default_factory=dict)


class GatewayError(Exception):
    """The gateway refused or could not be reached."""

    def __init__(self, message: str, *, code: str = "GATEWAY_ERROR") -> None:
        self.code = code
        super().__init__(message)


@runtime_checkable
class PaymentGateway(Protocol):
    name: str

    def create_order(
        self,
        *,
        amount_minor: int,
        currency: str,
        reference: str,
        idempotency_key: str,
        metadata: dict | None = None,
    ) -> GatewayOrder:
        """Register the intent to charge. Returns an id the client checks out with."""

    def fetch_order(self, order_id: str) -> GatewayOrder:
        """Authoritative current state -- used for reconciliation and recovery."""

    def refund(
        self, *, payment_id: str, amount_minor: int, idempotency_key: str, reason: str
    ) -> GatewayRefund:
        """Return money. Must be safe to call twice with the same key."""

    def verify_webhook(self, *, raw_body: bytes, signature: str) -> WebhookEvent:
        """Check the signature and parse. Never trust an unverified event."""
