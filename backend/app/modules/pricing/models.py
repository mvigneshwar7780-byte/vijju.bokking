"""Pricing: promotional offers and their redemptions."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    func,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.core.enums import OfferType, pg_enum


class Offer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "offers"

    code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    offer_type: Mapped[OfferType] = mapped_column(
        pg_enum(OfferType, "offer_type"),
        nullable=False,
    )

    # Exactly one of these carries the value, depending on offer_type; the check
    # constraint below makes an inconsistent row impossible.
    percent_off: Mapped[float | None] = mapped_column(Numeric(5, 2))
    flat_off_minor: Mapped[int | None] = mapped_column(Integer)
    buy_quantity: Mapped[int | None] = mapped_column(Integer)
    get_quantity: Mapped[int | None] = mapped_column(Integer)

    max_discount_minor: Mapped[int | None] = mapped_column(Integer)
    min_order_minor: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    usage_limit_total: Mapped[int | None] = mapped_column(Integer)
    usage_limit_per_user: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    # Maintained inside the redemption transaction, so the cap cannot be raced.
    redeemed_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    # Eligibility filters: {"city_ids": [...], "cinema_ids": [...],
    #  "movie_ids": [...], "formats": ["IMAX"], "days_of_week": [1,2],
    #  "payment_methods": ["upi"]}. JSONB because the set of dimensions an
    # operator wants to slice on grows constantly.
    conditions: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    is_stackable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    redemptions: Mapped[list["OfferRedemption"]] = relationship(back_populates="offer")

    __table_args__ = (
        Index("ix_offers_is_active_valid_until", "is_active", "valid_until"),
        CheckConstraint("valid_until > valid_from", name="valid_window_ordered"),
        CheckConstraint(
            "(offer_type <> 'percent' OR (percent_off IS NOT NULL AND percent_off > 0 AND percent_off <= 100)) "
            "AND (offer_type <> 'flat' OR (flat_off_minor IS NOT NULL AND flat_off_minor > 0)) "
            "AND (offer_type <> 'buy_n_get_m' OR (buy_quantity IS NOT NULL AND get_quantity IS NOT NULL))",
            name="offer_value_matches_type",
        ),
        CheckConstraint("redeemed_count >= 0", name="redeemed_count_non_negative"),
    )


class OfferRedemption(UUIDPrimaryKeyMixin, Base):
    """One offer applied to one booking.

    The unique constraint on ``booking_id`` is what enforces "one offer per
    booking" -- and it does so in the database, where a concurrent double-apply
    cannot slip past it.
    """

    __tablename__ = "offer_redemptions"

    offer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("offers.id", ondelete="RESTRICT"), nullable=False
    )
    booking_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    discount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    offer: Mapped[Offer] = relationship(back_populates="redemptions")

    __table_args__ = (
        UniqueConstraint("booking_id", name="uq_offer_redemptions_booking_id"),
        Index("ix_offer_redemptions_offer_id_user_id", "offer_id", "user_id"),
        CheckConstraint("discount_minor >= 0", name="discount_non_negative"),
    )
