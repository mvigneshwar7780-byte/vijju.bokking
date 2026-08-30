"""Venues: cities, cinemas, screens and the physical seat layout.

The seat layout is the *template*. Nothing here knows about a particular show --
that is `scheduling` (which shows run) and `inventory` (which seats are taken).
Keeping the template separate is what lets a 300-seat screen be reused by six
shows a day without duplicating the layout.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:  # pragma: no cover
    from app.modules.scheduling.models import Show


class City(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "cities"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    state: Mapped[str | None] = mapped_column(String(120))
    country_code: Mapped[str] = mapped_column(String(2), nullable=False, server_default="IN")
    # IANA zone. Every showtime is rendered in *its cinema's* zone, so this is
    # the anchor for "9:30 PM show" meaning what a human expects.
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default="Asia/Kolkata")
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="100")

    cinemas: Mapped[list["Cinema"]] = relationship(back_populates="city")

    __table_args__ = (Index("ix_cities_is_active_display_order", "is_active", "display_order"),)


class Cinema(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A physical multiplex. Owns screens, and is the unit an operator manages."""

    __tablename__ = "cinemas"

    city_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cities.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(220), nullable=False, unique=True)
    brand: Mapped[str | None] = mapped_column(String(120))  # PVR, INOX, Cinepolis
    address_line: Mapped[str] = mapped_column(Text, nullable=False)
    locality: Mapped[str | None] = mapped_column(String(160))
    pincode: Mapped[str | None] = mapped_column(String(12))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    # Denormalised from the city so a cinema in a different zone than its city
    # (rare, but real for border regions) stays correct.
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default="Asia/Kolkata")
    amenities: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    # The operator account allowed to schedule shows here.
    operator_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    city: Mapped[City] = relationship(back_populates="cinemas")
    screens: Mapped[list["Screen"]] = relationship(
        back_populates="cinema", cascade="all, delete-orphan"
    )
    seat_categories: Mapped[list["SeatCategory"]] = relationship(
        back_populates="cinema", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_cinemas_city_id_is_active", "city_id", "is_active"),
        Index("ix_cinemas_operator_user_id", "operator_user_id"),
    )


class SeatCategory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Recliner / Prime / Classic. A *table*, not an enum, because operators add
    and rename these at runtime and each carries its own default price."""

    __tablename__ = "seat_categories"

    cinema_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cinemas.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    # A *default*; the price actually charged comes from show_prices so an
    # operator can price a Friday night differently from a Tuesday matinee.
    default_price_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="100")
    color_hex: Mapped[str | None] = mapped_column(String(7))

    cinema: Mapped[Cinema] = relationship(back_populates="seat_categories")
    seats: Mapped[list["Seat"]] = relationship(back_populates="category")

    __table_args__ = (
        UniqueConstraint("cinema_id", "code", name="uq_seat_categories_cinema_id_code"),
        CheckConstraint("default_price_minor >= 0", name="default_price_non_negative"),
    )


class Screen(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One auditorium inside a cinema."""

    __tablename__ = "screens"

    cinema_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cinemas.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)      # "Audi 3"
    screen_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # What this room is *capable* of. The show picks one of these.
    supported_formats: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default='["2D"]'
    )
    sound_system: Mapped[str | None] = mapped_column(String(80))  # Dolby Atmos
    total_seats: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # Rendering hints for the seat map: aisle positions, screen curvature,
    # row-label overrides. Pure presentation -- no business rule reads this.
    layout_meta: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    # Bumped whenever seats are added/removed. Shows pin the version they were
    # created against, so an edited layout cannot silently corrupt live shows.
    layout_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    cinema: Mapped[Cinema] = relationship(back_populates="screens")
    seats: Mapped[list["Seat"]] = relationship(
        back_populates="screen", cascade="all, delete-orphan"
    )
    shows: Mapped[list["Show"]] = relationship(back_populates="screen")

    __table_args__ = (
        UniqueConstraint("cinema_id", "screen_number", name="uq_screens_cinema_id_screen_number"),
        Index("ix_screens_cinema_id_is_active", "cinema_id", "is_active"),
        CheckConstraint("total_seats >= 0", name="total_seats_non_negative"),
    )


class Seat(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One physical chair in one screen. Never per-show -- see `show_seats`."""

    __tablename__ = "seats"

    screen_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("screens.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("seat_categories.id", ondelete="RESTRICT"), nullable=False
    )
    row_label: Mapped[str] = mapped_column(String(4), nullable=False)   # "A", "AA"
    # Ordinal position of the row from the screen outward. Kept alongside the
    # label because "row 12" sorts correctly and "L" does not once you pass Z.
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    seat_number: Mapped[int] = mapped_column(Integer, nullable=False)   # 1..N
    # Grid column for rendering. Differs from seat_number when aisles create
    # gaps, and it is what "middle of the hall" and "aisle seat" reason over.
    column_index: Mapped[int] = mapped_column(Integer, nullable=False)
    is_aisle: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_wheelchair_accessible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    is_companion: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # Permanently out of service (broken chair). A *show-specific* block lives
    # on show_seats instead, so it can be lifted for the next show.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    screen: Mapped[Screen] = relationship(back_populates="seats")
    category: Mapped[SeatCategory] = relationship(back_populates="seats")

    __table_args__ = (
        UniqueConstraint(
            "screen_id", "row_label", "seat_number", name="uq_seats_screen_id_row_label_seat_number"
        ),
        Index("ix_seats_screen_id_row_index_column_index", "screen_id", "row_index", "column_index"),
        Index("ix_seats_category_id", "category_id"),
        CheckConstraint("seat_number > 0", name="seat_number_positive"),
        CheckConstraint("row_index >= 0", name="row_index_non_negative"),
    )

    @property
    def label(self) -> str:
        return f"{self.row_label}{self.seat_number}"
