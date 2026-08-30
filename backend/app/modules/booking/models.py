"""Bookings: the order a customer places, and what it contains.

A booking is a *financial record*. Once created it is append-only in spirit:
prices are snapshotted, never recomputed from live data, so a report run next
year reproduces exactly what the customer paid.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    func,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.core.enums import BookingStatus, pg_enum

if TYPE_CHECKING:  # pragma: no cover
    from app.modules.identity.models import User
    from app.modules.payments.models import Payment
    from app.modules.scheduling.models import Show


class Booking(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "bookings"

    # Short, unambiguous, quotable at the box office. Indexed unique because it
    # is the natural lookup key for support and for the QR scanner.
    booking_reference: Mapped[str] = mapped_column(String(16), nullable=False, unique=True)

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    show_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shows.id", ondelete="RESTRICT"), nullable=False
    )
    hold_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("seat_holds.id", ondelete="SET NULL")
    )

    status: Mapped[BookingStatus] = mapped_column(
        pg_enum(BookingStatus, "booking_status"),
        nullable=False,
        server_default=BookingStatus.DRAFT.value,
    )

    seat_count: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    # ---- price snapshot, all integer minor units (paise) -------------------
    # Integers, not floats and not Decimal-in-Python-only: money arithmetic that
    # can round is money arithmetic that will eventually be wrong. Every one of
    # these is computed server-side; the client sends none of them.
    ticket_subtotal_minor: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    fnb_subtotal_minor: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    discount_minor: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    convenience_fee_minor: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    tax_minor: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    total_minor: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="INR")

    # A full, human-readable breakdown of how total_minor was reached, kept for
    # display and for disputes. Derived data -- the columns above are the truth.
    price_breakdown: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    offer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("offers.id", ondelete="SET NULL")
    )
    offer_code: Mapped[str | None] = mapped_column(String(40))

    # Guests can book without an account; these are also where the ticket is sent.
    contact_email: Mapped[str] = mapped_column(String(320), nullable=False)
    contact_phone: Mapped[str | None] = mapped_column(String(20))

    # The deadline for completing payment. Mirrors the hold TTL and is extended
    # once when the payment session starts, so the customer is never charged for
    # a seat that lapsed while the gateway page was open.
    payment_deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_reason: Mapped[str | None] = mapped_column(Text)

    # ---- ticket ------------------------------------------------------------
    qr_payload: Mapped[str | None] = mapped_column(Text)
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checked_in_seats: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")

    booking_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    user: Mapped["User | None"] = relationship(back_populates="bookings")
    show: Mapped["Show"] = relationship()
    seats: Mapped[list["BookingSeat"]] = relationship(
        back_populates="booking", cascade="all, delete-orphan", lazy="selectin"
    )
    fnb_items: Mapped[list["BookingFnbItem"]] = relationship(
        back_populates="booking", cascade="all, delete-orphan", lazy="selectin"
    )
    payments: Mapped[list["Payment"]] = relationship(back_populates="booking")

    __table_args__ = (
        Index("ix_bookings_user_id_created_at", "user_id", "created_at"),
        # The hold -> booking lookup. The expiry sweeper needs it on every pass:
        # before releasing a lapsed hold it must check whether a booking against
        # that hold is mid-payment, and releasing those would take money for
        # seats we just gave away.
        Index("ix_bookings_hold_id", "hold_id"),
        Index("ix_bookings_show_id_status", "show_id", "status"),
        # Drives the expiry sweeper: unconfirmed bookings past their deadline.
        Index("ix_bookings_status_payment_deadline_at", "status", "payment_deadline_at"),
        CheckConstraint("seat_count > 0", name="seat_count_positive"),
        CheckConstraint("total_minor >= 0", name="total_non_negative"),
        CheckConstraint("discount_minor >= 0", name="discount_non_negative"),
        # The invoice must add up. If a pricing change ever breaks this the
        # insert fails loudly instead of quietly mis-charging someone.
        CheckConstraint(
            "total_minor = ticket_subtotal_minor + fnb_subtotal_minor "
            "- discount_minor + convenience_fee_minor + tax_minor",
            name="total_is_sum_of_parts",
        ),
        CheckConstraint(
            "checked_in_seats >= 0 AND checked_in_seats <= seat_count",
            name="checked_in_within_seat_count",
        ),
    )


class BookingSeat(UUIDPrimaryKeyMixin, Base):
    """One ticket. Snapshots the seat label and price at purchase time."""

    __tablename__ = "booking_seats"

    booking_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False
    )
    show_seat_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("show_seats.id", ondelete="RESTRICT"), nullable=False
    )
    seat_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("seats.id", ondelete="RESTRICT"), nullable=False
    )
    # Snapshots -- the screen can be re-lettered next year; this ticket cannot.
    seat_label: Mapped[str] = mapped_column(String(12), nullable=False)
    seat_category_name: Mapped[str] = mapped_column(String(80), nullable=False)
    price_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # False once the parent booking dies (cancelled, expired, payment failed).
    # The row is kept -- it is a financial record -- but it stops competing for
    # the seat. Denormalised from the booking's status rather than joined,
    # because a partial index cannot reference another table.
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )

    booking: Mapped[Booking] = relationship(back_populates="seats")

    __table_args__ = (
        # One *live* ticket per seat. The second line of defence behind the
        # show_seats status machine: even a bug in the service layer cannot
        # produce two valid tickets for one seat.
        #
        # It has to be a PARTIAL index. A plain UNIQUE(show_seat_id) looks
        # equivalent and is not: after a cancellation the seat goes back on
        # sale, and the next buyer's INSERT collides with the *cancelled*
        # booking's row. The seat would be silently unsellable forever, and
        # only seats that had once been cancelled would be affected -- which is
        # exactly the kind of bug that survives a happy-path test suite.
        Index(
            "uq_booking_seats_active_show_seat",
            "show_seat_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
        Index("ix_booking_seats_booking_id", "booking_id"),
        CheckConstraint("price_minor >= 0", name="price_non_negative"),
    )


class BookingFnbItem(UUIDPrimaryKeyMixin, Base):
    """Popcorn. Also a price snapshot."""

    __tablename__ = "booking_fnb_items"

    booking_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False
    )
    fnb_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fnb_items.id", ondelete="RESTRICT"), nullable=False
    )
    item_name: Mapped[str] = mapped_column(String(160), nullable=False)
    quantity: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    unit_price_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    total_minor: Mapped[int] = mapped_column(Integer, nullable=False)

    booking: Mapped[Booking] = relationship(back_populates="fnb_items")

    __table_args__ = (
        UniqueConstraint("booking_id", "fnb_item_id", name="uq_booking_fnb_items_booking_id_fnb_item_id"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("total_minor = unit_price_minor * quantity", name="line_total_consistent"),
    )


class IdempotencyKey(UUIDPrimaryKeyMixin, Base):
    """Makes retried POSTs safe.

    The client sends ``Idempotency-Key``. The first request stores the key with
    a hash of its body and its eventual response; a replay with the same key and
    the same body replays the stored response instead of creating a second
    booking. A replay with a *different* body is a client bug and is rejected.
    """

    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(String(128), nullable=False)
    # Null for guests, who are scoped by session key instead.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    scope: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g. "create_booking"
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int | None] = mapped_column(SmallInteger)
    response_body: Mapped[dict | None] = mapped_column(JSONB)
    booking_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bookings.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("scope", "key", name="uq_idempotency_keys_scope_key"),
        Index("ix_idempotency_keys_created_at", "created_at"),
    )
