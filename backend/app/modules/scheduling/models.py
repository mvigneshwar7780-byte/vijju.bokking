"""Scheduling: which movie plays on which screen, when, in what format, and at
what price.

A `Show` is the single most important row in the system: it is the unit of
inventory, the unit of pricing, and the thing a booking points at.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.core.enums import ShowStatus, pg_enum

if TYPE_CHECKING:  # pragma: no cover
    from app.modules.catalog.models import Movie
    from app.modules.inventory.models import ShowSeat
    from app.modules.venues.models import Screen


class Format(UUIDPrimaryKeyMixin, Base):
    """2D / 3D / IMAX / 4DX / ICE.

    A table rather than an enum: operators add formats, and each carries a
    surcharge that pricing reads. Enums cannot hold a price.
    """

    __tablename__ = "formats"

    code: Mapped[str] = mapped_column(String(16), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    # Added on top of the seat-category price. Absolute, not a multiplier, so the
    # arithmetic stays integer and exact.
    surcharge_minor: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="100")

    __table_args__ = (CheckConstraint("surcharge_minor >= 0", name="surcharge_non_negative"),)


class Show(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "shows"

    movie_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("movies.id", ondelete="RESTRICT"), nullable=False
    )
    screen_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("screens.id", ondelete="RESTRICT"), nullable=False
    )
    format_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("formats.id", ondelete="RESTRICT"), nullable=False
    )
    audio_language_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("languages.id", ondelete="RESTRICT"), nullable=False
    )
    subtitle_language_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("languages.id", ondelete="SET NULL")
    )

    # --- deliberate denormalisation -------------------------------------
    # cinema_id and city_id are derivable via screens -> cinemas -> cities, but
    # the single hottest query in the product is
    #   "shows for movie M, in city C, on date D"
    # and a three-table join cannot use one composite index. These two columns
    # are written by the scheduling service (never by hand) and are covered by
    # a consistency test. This is the one place the schema trades purity for a
    # query plan, and it is worth it.
    cinema_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cinemas.id", ondelete="RESTRICT"), nullable=False
    )
    city_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cities.id", ondelete="RESTRICT"), nullable=False
    )

    # --- time -----------------------------------------------------------
    # Stored as timestamptz (an absolute instant). The operator enters a local
    # wall time ("21:30") plus the cinema's IANA zone, and the service converts.
    # That is the only correct way to survive DST and multi-zone catalogues.
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # The calendar date *in the cinema's zone*. A 00:45 "midnight show" belongs
    # to the previous day's listing, which is exactly why this cannot be derived
    # with a plain date(starts_at).
    show_date: Mapped[date] = mapped_column(Date, nullable=False)

    status: Mapped[ShowStatus] = mapped_column(
        pg_enum(ShowStatus, "show_status"),
        nullable=False,
        server_default=ShowStatus.SCHEDULED.value,
    )
    # Sales window. Defaults are derived from settings but stored per show so an
    # operator can open advance booking early for a blockbuster.
    sales_open_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sales_close_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Pinned at creation. If the screen layout is edited afterwards the version
    # no longer matches and the show is flagged rather than silently corrupted.
    screen_layout_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")

    # Cached counters maintained by the inventory service inside the same
    # transaction that changes seat state, so they cannot drift.
    total_seats: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    available_seats: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    cancellation_reason: Mapped[str | None] = mapped_column(Text)

    movie: Mapped["Movie"] = relationship(back_populates="shows")
    screen: Mapped["Screen"] = relationship(back_populates="shows")
    format: Mapped[Format] = relationship()
    prices: Mapped[list["ShowPrice"]] = relationship(
        back_populates="show", cascade="all, delete-orphan", lazy="selectin"
    )
    seats: Mapped[list["ShowSeat"]] = relationship(
        back_populates="show", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # A screen cannot run two shows starting at the same instant...
        UniqueConstraint("screen_id", "starts_at", name="uq_shows_screen_id_starts_at"),
        # ...and, more importantly, cannot run two shows whose *runtimes*
        # overlap. The unique constraint above only catches identical start
        # times; a 168-minute film scheduled at 17:00 and another at 18:00 would
        # sail past it and double-book the auditorium.
        #
        # This is enforced in the database rather than in the scheduling service
        # because a check-then-insert in application code has the same race as
        # a check-then-insert for seats. GiST + btree_gist lets one constraint
        # express "same screen AND overlapping time range".
        #
        # Ranges are half-open, so a show ending exactly when the next begins is
        # allowed -- which is what back-to-back scheduling means. Cancelled
        # shows are excluded so a cancellation frees the slot immediately.
        ExcludeConstraint(
            ("screen_id", "="),
            (text("tstzrange(starts_at, ends_at)"), "&&"),
            name="ex_shows_screen_no_overlap",
            using="gist",
            where=text("status <> 'cancelled'"),
        ),
        # The listing query: city + movie + date, newest first.
        Index("ix_shows_city_id_movie_id_show_date", "city_id", "movie_id", "show_date"),
        # The cinema detail page: all shows at one cinema on one date.
        Index("ix_shows_cinema_id_show_date_starts_at", "cinema_id", "show_date", "starts_at"),
        # The sweeper and "what is on now" queries.
        Index("ix_shows_status_starts_at", "status", "starts_at"),
        Index("ix_shows_screen_id_starts_at", "screen_id", "starts_at"),
        CheckConstraint("ends_at > starts_at", name="ends_after_starts"),
        CheckConstraint("available_seats >= 0", name="available_seats_non_negative"),
        CheckConstraint("available_seats <= total_seats", name="available_within_total"),
    )

    @property
    def is_bookable(self) -> bool:
        from datetime import UTC

        now = datetime.now(UTC)
        return (
            self.status == ShowStatus.OPEN
            and now < self.sales_close_at
            and (self.sales_open_at is None or now >= self.sales_open_at)
        )


class ShowPrice(UUIDPrimaryKeyMixin, Base):
    """The price of one seat category for one show.

    Prices live per show, not per screen, because that is what makes weekend
    pricing, matinee discounts and (later) dynamic pricing possible without
    touching the seat layout.
    """

    __tablename__ = "show_prices"

    show_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shows.id", ondelete="CASCADE"), nullable=False
    )
    seat_category_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("seat_categories.id", ondelete="RESTRICT"), nullable=False
    )
    price_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    # Set by the dynamic-pricing experiment; null means "operator set this".
    ai_suggested_price_minor: Mapped[int | None] = mapped_column(Integer)

    show: Mapped[Show] = relationship(back_populates="prices")

    __table_args__ = (
        UniqueConstraint(
            "show_id", "seat_category_id", name="uq_show_prices_show_id_seat_category_id"
        ),
        CheckConstraint("price_minor >= 0", name="price_non_negative"),
    )
