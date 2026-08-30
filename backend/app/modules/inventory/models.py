"""Inventory: the per-show seat ledger and the soft locks over it.

Why one row per (show, seat)
----------------------------
The alternative -- deriving availability by subtracting booked seats from the
screen layout on every read -- looks cheaper until you need to *hold* a seat.
A hold has state (who, until when) that has to live somewhere, and it has to be
lockable. A materialised row is that somewhere.

The cost is bounded and small: 5 screens x 250 seats x 6 shows/day = 7,500 rows
a day, ~2.7M a year. Postgres does not notice. In exchange every seat map is one
indexed read, and the anti-double-booking guarantee becomes a row lock rather
than an application-level invariant nobody can enforce.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.core.enums import HoldStatus, ShowSeatStatus, pg_enum

if TYPE_CHECKING:  # pragma: no cover
    from app.modules.scheduling.models import Show
    from app.modules.venues.models import Seat


class SeatHold(UUIDPrimaryKeyMixin, Base):
    """A soft lock over a *group* of seats, with a TTL.

    Grouping matters: a user selects four seats as one act, and they succeed or
    fail as one. The hold is the transaction boundary the UI countdown maps to.
    """

    __tablename__ = "seat_holds"

    show_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shows.id", ondelete="CASCADE"), nullable=False
    )
    # Null for a guest checkout; the anonymous session still owns the hold.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    # Opaque client session id, so an anonymous user can reclaim their own hold
    # after a page refresh but cannot touch anyone else's.
    session_key: Mapped[str] = mapped_column(String(64), nullable=False)

    status: Mapped[HoldStatus] = mapped_column(
        pg_enum(HoldStatus, "hold_status"),
        nullable=False,
        server_default=HoldStatus.ACTIVE.value,
    )
    seat_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # The authoritative deadline. Every availability check compares against this
    # column, never against a timestamp the client sent.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set when the customer explicitly asked to keep these seats. Once set, an
    # *abandon* release (the browser leaving checkout) becomes a no-op -- they
    # asked for the seats to survive, so navigating away must not drop them.
    # An explicit "release my seats" still works.
    keep_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # There is deliberately NO booking_id here. `bookings.hold_id` is the single
    # owning direction; adding the reverse pointer would create a circular
    # foreign key between the two tables (each needing the other to exist first)
    # and buy nothing -- "did this hold convert?" is one indexed lookup on
    # bookings.hold_id.

    show: Mapped["Show"] = relationship()
    show_seats: Mapped[list["ShowSeat"]] = relationship(back_populates="hold")

    __table_args__ = (
        Index("ix_seat_holds_show_id_status", "show_id", "status"),
        # The sweeper's query: active holds past their deadline.
        Index("ix_seat_holds_status_expires_at", "status", "expires_at"),
        Index("ix_seat_holds_session_key", "session_key"),
        Index("ix_seat_holds_user_id", "user_id"),
        CheckConstraint("seat_count > 0", name="seat_count_positive"),
    )

    @property
    def is_live(self) -> bool:
        from datetime import UTC

        return self.status == HoldStatus.ACTIVE and self.expires_at > datetime.now(UTC)


class ShowSeat(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One seat, for one show. The row that gets locked.

    Every transition of ``status`` happens through a single conditional UPDATE
    in ``InventoryService`` -- see that module for why the WHERE clause is the
    actual concurrency control, not the application code around it.
    """

    __tablename__ = "show_seats"

    show_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shows.id", ondelete="CASCADE"), nullable=False
    )
    seat_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("seats.id", ondelete="RESTRICT"), nullable=False
    )
    # Copied from the seat at materialisation time so pricing and the seat map
    # do not have to join back to `seats` -> `seat_categories`. Safe to
    # denormalise: a seat never changes category mid-show.
    seat_category_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("seat_categories.id", ondelete="RESTRICT"), nullable=False
    )
    # The price this seat currently sells for, resolved from show_prices at
    # materialisation. The booking snapshots it again into booking_items, so a
    # later price change cannot alter what somebody already paid.
    price_minor: Mapped[int] = mapped_column(Integer, nullable=False)

    status: Mapped[ShowSeatStatus] = mapped_column(
        pg_enum(ShowSeatStatus, "show_seat_status"),
        nullable=False,
        server_default=ShowSeatStatus.AVAILABLE.value,
    )

    hold_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("seat_holds.id", ondelete="SET NULL")
    )
    # Denormalised from the hold so the "is this hold still good?" test is a
    # single-table predicate. Without it, reclaiming an expired hold would need
    # a join inside the hot UPDATE, and joins in an UPDATE's WHERE are where
    # concurrency bugs hide.
    hold_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    booking_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bookings.id", ondelete="SET NULL")
    )
    blocked_reason: Mapped[str | None] = mapped_column(String(200))

    show: Mapped["Show"] = relationship(back_populates="seats")
    seat: Mapped["Seat"] = relationship(lazy="joined")
    hold: Mapped[SeatHold | None] = relationship(back_populates="show_seats")

    __table_args__ = (
        # ---------------------------------------------------------------
        # THE anti-double-booking constraint.
        #
        # One row per seat per show means "is this seat taken?" is a property of
        # a single row, and a single row can be locked. Two concurrent holds for
        # the same seat both target this row; Postgres serialises them, the
        # loser re-evaluates the WHERE clause against the winner's committed
        # version, fails the `status = 'available'` test, and updates nothing.
        # There is no window in which both succeed.
        # ---------------------------------------------------------------
        UniqueConstraint("show_id", "seat_id", name="uq_show_seats_show_id_seat_id"),
        # The seat-map read and the hold UPDATE both drive off this index, which
        # is also what gives both transactions the same row-locking order and so
        # keeps deadlocks away.
        Index("ix_show_seats_show_id_status", "show_id", "status"),
        Index("ix_show_seats_hold_id", "hold_id"),
        Index("ix_show_seats_booking_id", "booking_id"),
        # State integrity, enforced by the database rather than by hope.
        CheckConstraint(
            "(status <> 'booked') OR (booking_id IS NOT NULL)",
            name="booked_requires_booking",
        ),
        CheckConstraint(
            "(status <> 'held') OR (hold_id IS NOT NULL AND hold_expires_at IS NOT NULL)",
            name="held_requires_hold",
        ),
        CheckConstraint(
            "(status <> 'available') OR (hold_id IS NULL AND booking_id IS NULL)",
            name="available_is_clean",
        ),
        CheckConstraint("price_minor >= 0", name="price_non_negative"),
    )
