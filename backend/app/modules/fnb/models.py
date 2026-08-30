"""Food & beverage catalogue. Sold as an add-on to a booking."""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin, UUIDPrimaryKeyMixin


class FnbItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "fnb_items"

    cinema_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cinemas.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(60), nullable=False)  # popcorn, beverages, combos
    price_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    image_url: Mapped[str | None] = mapped_column(Text)
    is_vegetarian: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="100")

    __table_args__ = (
        UniqueConstraint("cinema_id", "name", name="uq_fnb_items_cinema_id_name"),
        Index("ix_fnb_items_cinema_id_is_available", "cinema_id", "is_available"),
        CheckConstraint("price_minor >= 0", name="price_non_negative"),
    )
