"""Payments: gateway orders, webhook events and refunds.

The rule that shapes every table here: **the client is not a source of truth**.
A browser saying "payment succeeded" is a hint. The webhook, signature-verified
and replay-safe, is the fact. So `payment_events` is an append-only log, and
`payments.status` only ever moves because of something in that log.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.core.enums import PaymentStatus, RefundStatus, pg_enum

if TYPE_CHECKING:  # pragma: no cover
    from app.modules.booking.models import Booking


class Payment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "payments"

    booking_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bookings.id", ondelete="RESTRICT"), nullable=False
    )
    gateway: Mapped[str] = mapped_column(String(32), nullable=False)  # mock, stripe, razorpay
    # The gateway's own order/intent id. Unique per gateway so a webhook can be
    # matched back to exactly one payment row.
    gateway_order_id: Mapped[str] = mapped_column(String(128), nullable=False)
    gateway_payment_id: Mapped[str | None] = mapped_column(String(128))

    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="INR")
    amount_refunded_minor: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    status: Mapped[PaymentStatus] = mapped_column(
        pg_enum(PaymentStatus, "payment_status"),
        nullable=False,
        server_default=PaymentStatus.CREATED.value,
    )
    method: Mapped[str | None] = mapped_column(String(40))  # card, upi, netbanking, wallet
    failure_code: Mapped[str | None] = mapped_column(String(60))
    failure_message: Mapped[str | None] = mapped_column(Text)

    authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set when money was taken but the seats could not be delivered. The refund
    # worker looks for exactly this and makes the customer whole.
    requires_auto_refund: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )

    gateway_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    booking: Mapped["Booking"] = relationship(back_populates="payments")
    events: Mapped[list["PaymentEvent"]] = relationship(back_populates="payment")
    refunds: Mapped[list["Refund"]] = relationship(back_populates="payment")

    __table_args__ = (
        UniqueConstraint(
            "gateway", "gateway_order_id", name="uq_payments_gateway_gateway_order_id"
        ),
        Index("ix_payments_booking_id_status", "booking_id", "status"),
        Index("ix_payments_status_created_at", "status", "created_at"),
        Index("ix_payments_requires_auto_refund", "requires_auto_refund"),
        CheckConstraint("amount_minor > 0", name="amount_positive"),
        CheckConstraint(
            "amount_refunded_minor >= 0 AND amount_refunded_minor <= amount_minor",
            name="refunded_within_amount",
        ),
    )


class PaymentEvent(UUIDPrimaryKeyMixin, Base):
    """Every webhook the gateway sends, stored before it is acted on.

    ``(gateway, event_id)`` is unique, which is the whole idempotency story: a
    duplicate delivery hits the constraint, we recognise it, and we return 200
    without applying the effect twice. At-least-once delivery becomes
    exactly-once processing with one index.
    """

    __tablename__ = "payment_events"

    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("payments.id", ondelete="SET NULL")
    )
    gateway: Mapped[str] = mapped_column(String(32), nullable=False)
    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    signature_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_error: Mapped[str | None] = mapped_column(Text)

    payment: Mapped[Payment | None] = relationship(back_populates="events")

    __table_args__ = (
        UniqueConstraint("gateway", "event_id", name="uq_payment_events_gateway_event_id"),
        Index("ix_payment_events_payment_id_received_at", "payment_id", "received_at"),
        Index("ix_payment_events_processed_at", "processed_at"),
    )


class Refund(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "refunds"

    payment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("payments.id", ondelete="RESTRICT"), nullable=False
    )
    booking_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bookings.id", ondelete="RESTRICT"), nullable=False
    )
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[RefundStatus] = mapped_column(
        pg_enum(RefundStatus, "refund_status"),
        nullable=False,
        server_default=RefundStatus.PENDING.value,
    )
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    # user_cancellation | show_cancelled | seats_unavailable | operator_goodwill
    gateway_refund_id: Mapped[str | None] = mapped_column(String(128))
    # Idempotency for the outbound call: one refund per booking per reason.
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_message: Mapped[str | None] = mapped_column(Text)

    payment: Mapped[Payment] = relationship(back_populates="refunds")

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_refunds_idempotency_key"),
        Index("ix_refunds_booking_id", "booking_id"),
        Index("ix_refunds_status", "status"),
        CheckConstraint("amount_minor > 0", name="amount_positive"),
    )
