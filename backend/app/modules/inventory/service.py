"""Seat inventory policy.

The repository owns *how* seats change state safely. This module owns *whether
they are allowed to*: the booking window, the per-transaction seat cap, the
no-orphan-seat rule, and the hold lifecycle.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import HoldStatus, ShowStatus
from app.core.errors import (
    HoldExpiredError,
    NotFoundError,
    PermissionDeniedError,
    SeatRuleViolationError,
    SeatUnavailableError,
    ShowNotBookableError,
)
from app.core.logging import get_logger
from app.modules.inventory.models import SeatHold, ShowSeat
from app.modules.inventory.repository import ClaimedSeat, InventoryRepository, SeatMapRow
from app.modules.inventory.schemas import (
    HoldOut,
    SeatCategorySummary,
    SeatMapOut,
    SeatOut,
    SeatRowOut,
)
from app.modules.scheduling.models import Show

logger = get_logger(__name__)


class InventoryService:
    def __init__(self, db: Session, *, use_advisory_lock: bool = True) -> None:
        self.db = db
        self.repo = InventoryRepository(db)
        # Switchable so the concurrency test suite can prove the conditional
        # UPDATE is safe entirely on its own, with the lock out of the picture.
        self.use_advisory_lock = use_advisory_lock

    # ------------------------------------------------------------------
    # Materialisation
    # ------------------------------------------------------------------
    def materialize_seats(self, show: Show) -> int:
        """Create one ``show_seats`` row per active seat in the screen.

        Done once, when the show is created, inside the same transaction. The
        price is resolved per seat category from ``show_prices`` and copied in,
        so the seat map needs no join to price itself.
        """
        from sqlalchemy import text

        inserted = self.db.execute(
            text(
                """
                INSERT INTO show_seats
                       (id, show_id, seat_id, seat_category_id, price_minor,
                        status, created_at, updated_at)
                SELECT uuidv7(), :show_id, s.id, s.category_id,
                       COALESCE(sp.price_minor, sc.default_price_minor) + :format_surcharge,
                       'available', now(), now()
                  FROM seats s
                  JOIN seat_categories sc ON sc.id = s.category_id
             LEFT JOIN show_prices sp
                    ON sp.show_id = :show_id
                   AND sp.seat_category_id = s.category_id
                 WHERE s.screen_id = :screen_id
                   AND s.is_active
             ON CONFLICT (show_id, seat_id) DO NOTHING
                """
            ),
            {
                "show_id": show.id,
                "screen_id": show.screen_id,
                "format_surcharge": show.format.surcharge_minor if show.format else 0,
            },
        )
        count = int(inserted.rowcount or 0)
        show.total_seats = count
        show.available_seats = count
        self.db.flush()
        logger.info("show_seats_materialized", show_id=str(show.id), seats=count)
        return count

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def get_seat_map(self, show_id: uuid.UUID) -> SeatMapOut:
        show = self._load_show(show_id)
        rows = self.repo.get_seat_map(show_id)
        if not rows:
            raise NotFoundError("No seat map exists for this show yet.")

        by_row: dict[int, list[SeatOut]] = {}
        row_labels: dict[int, str] = {}
        cat_totals: dict[uuid.UUID, dict] = {}

        for r in rows:
            seat = SeatOut(
                show_seat_id=r.show_seat_id,
                seat_id=r.seat_id,
                label=f"{r.row_label}{r.seat_number}",
                row_label=r.row_label,
                row_index=r.row_index,
                seat_number=r.seat_number,
                column_index=r.column_index,
                category_id=r.category_id,
                category_code=r.category_code,
                category_name=r.category_name,
                price_minor=r.price_minor,
                status=r.status,
                is_aisle=r.is_aisle,
                is_wheelchair_accessible=r.is_wheelchair_accessible,
            )
            by_row.setdefault(r.row_index, []).append(seat)
            row_labels[r.row_index] = r.row_label

            bucket = cat_totals.setdefault(
                r.category_id,
                {"code": r.category_code, "name": r.category_name,
                 "price_minor": r.price_minor, "available": 0, "total": 0},
            )
            bucket["total"] += 1
            if r.status == "available":
                bucket["available"] += 1

        rows_out = [
            SeatRowOut(row_label=row_labels[idx], row_index=idx, seats=by_row[idx])
            for idx in sorted(by_row)
        ]
        categories = [
            SeatCategorySummary(category_id=cid, **vals)
            for cid, vals in sorted(cat_totals.items(), key=lambda kv: kv[1]["price_minor"])
        ]
        available = sum(c.available for c in categories)

        return SeatMapOut(
            show_id=show.id,
            screen_name=show.screen.name,
            cinema_name=show.screen.cinema.name,
            movie_title=show.movie.title,
            starts_at=show.starts_at,
            rows=rows_out,
            categories=categories,
            available_seats=available,
            total_seats=len(rows),
            max_seats_per_booking=settings.max_seats_per_booking,
            layout_meta=show.screen.layout_meta or {},
        )

    # ------------------------------------------------------------------
    # Holds
    # ------------------------------------------------------------------
    def hold_seats(
        self,
        *,
        show_id: uuid.UUID,
        seat_ids: list[uuid.UUID],
        session_key: str,
        user_id: uuid.UUID | None = None,
        ttl_seconds: int | None = None,
    ) -> HoldOut:
        """Take a soft lock on a set of seats. All or nothing.

        Defaults to the *selection* window -- long enough to fill in checkout,
        short enough that abandoning does not strand the seats. The customer can
        extend it deliberately (`keep_hold`), and starting a payment extends it
        again.
        """
        show = self._load_show(show_id)
        self._assert_bookable(show)

        # Deduplicate before anything else: a client that sends the same seat
        # twice would otherwise get a seat_count that does not match reality.
        unique_ids = list(dict.fromkeys(seat_ids))
        if len(unique_ids) > settings.max_seats_per_booking:
            raise SeatRuleViolationError(
                f"You can book at most {settings.max_seats_per_booking} seats in one transaction.",
                details={"requested": len(unique_ids), "max": settings.max_seats_per_booking},
            )

        if self.use_advisory_lock:
            self.repo.lock_show(show_id)

        # Checked against the map before claiming, purely for a good error
        # message. Advisory only: the conditional UPDATE below is what actually
        # decides, and it re-validates availability atomically.
        seat_map = self.repo.get_seat_map(show_id)
        self._assert_seats_belong_to_show(unique_ids, seat_map)

        ttl = ttl_seconds or settings.seat_selection_ttl_seconds
        expires_at = datetime.now(UTC) + timedelta(seconds=ttl)
        hold = SeatHold(
            show_id=show_id,
            user_id=user_id,
            session_key=session_key,
            seat_count=len(unique_ids),
            expires_at=expires_at,
            status=HoldStatus.ACTIVE,
        )
        self.db.add(hold)
        self.db.flush()  # need hold.id for the claim

        claimed = self.repo.claim_seats(
            show_id=show_id, seat_ids=unique_ids, hold_id=hold.id, expires_at=expires_at
        )

        if len(claimed) != len(unique_ids):
            # Someone else got there first. Raising rolls the whole transaction
            # back, which un-claims the partial set -- there is no compensating
            # cleanup to write, and no window in which those seats are stranded.
            taken = {c.seat_id for c in claimed}
            lost = [str(s) for s in unique_ids if s not in taken]
            logger.info(
                "seat_claim_lost_race",
                show_id=str(show_id),
                requested=len(unique_ids),
                won=len(claimed),
            )
            raise SeatUnavailableError(
                "Some of those seats were just taken. Please pick again.",
                details={"unavailable_seat_ids": lost},
            )

        self.repo.refresh_available_count(show_id)

        labels = self._labels_for(claimed, seat_map)
        subtotal = sum(c.price_minor for c in claimed)
        logger.info(
            "seats_held",
            hold_id=str(hold.id),
            show_id=str(show_id),
            seats=len(claimed),
            expires_at=expires_at.isoformat(),
        )
        return HoldOut(
            hold_id=hold.id,
            show_id=show_id,
            seat_ids=[c.seat_id for c in claimed],
            seat_labels=labels,
            seat_count=len(claimed),
            expires_at=expires_at,
            seconds_remaining=ttl,
            subtotal_minor=subtotal,
        )

    def get_hold(self, hold_id: uuid.UUID, *, session_key: str) -> SeatHold:
        hold = self.db.get(SeatHold, hold_id)
        if hold is None:
            raise NotFoundError("That seat hold does not exist.")
        if hold.session_key != session_key:
            # Do not leak whether the hold exists to a different session.
            raise PermissionDeniedError("That seat hold belongs to another session.")
        return hold

    def release_hold(
        self, hold_id: uuid.UUID, *, session_key: str, reason: str = "explicit"
    ) -> int:
        """Give the seats back.

        ``reason="abandoned"`` is the browser reporting that the customer left
        checkout. That must not override an explicit "keep these seats" -- the
        customer asked for them to survive, and navigating away is not a change
        of mind. An explicit release always wins.
        """
        hold = self.get_hold(hold_id, session_key=session_key)
        if hold.status != HoldStatus.ACTIVE:
            return 0
        if reason == "abandoned" and hold.keep_requested_at is not None:
            logger.info("hold_abandon_ignored_kept", hold_id=str(hold_id))
            return 0
        released = self.repo.release_hold_seats(hold_id)
        hold.status = HoldStatus.RELEASED
        hold.released_at = datetime.now(UTC)
        self.db.flush()
        self.repo.refresh_available_count(hold.show_id)
        logger.info("hold_released", hold_id=str(hold_id), seats=released)
        return released

    def keep_hold(self, hold_id: uuid.UUID, *, session_key: str) -> HoldOut:
        """The customer asks to hold these seats for the full window.

        This is the deliberate act that turns a short selection hold into a long
        one, and it is what makes the default safe: seats are only tied up for
        eight minutes because somebody said so, not because they opened a page
        and wandered off.
        """
        hold = self.get_hold(hold_id, session_key=session_key)
        if not hold.is_live:
            raise HoldExpiredError()

        new_expiry = datetime.now(UTC) + timedelta(
            seconds=settings.seat_hold_ttl_seconds
        )
        if new_expiry > hold.expires_at:
            self.repo.extend_hold(hold_id, new_expiry)
        hold.keep_requested_at = datetime.now(UTC)
        self.db.flush()
        self.db.refresh(hold)

        logger.info(
            "hold_kept", hold_id=str(hold_id), expires_at=hold.expires_at.isoformat()
        )
        return self.describe_hold(hold)

    def describe_hold(self, hold: SeatHold) -> HoldOut:
        """The public view of a hold, with its seats and remaining time."""
        from app.modules.venues.models import Seat

        rows = self.db.execute(
            select(ShowSeat, Seat)
            .join(Seat, Seat.id == ShowSeat.seat_id)
            .where(ShowSeat.hold_id == hold.id)
            .order_by(Seat.row_index, Seat.seat_number)
        ).all()
        remaining = max(int((hold.expires_at - datetime.now(UTC)).total_seconds()), 0)
        return HoldOut(
            hold_id=hold.id,
            show_id=hold.show_id,
            seat_ids=[ss.seat_id for ss, _ in rows],
            seat_labels=[f"{seat.row_label}{seat.seat_number}" for _, seat in rows],
            seat_count=len(rows),
            expires_at=hold.expires_at,
            seconds_remaining=remaining,
            subtotal_minor=sum(ss.price_minor for ss, _ in rows),
            is_kept=hold.keep_requested_at is not None,
        )

    def extend_hold(self, hold_id: uuid.UUID, *, seconds: int) -> datetime:
        """Push out a hold's deadline, e.g. when the payment page opens."""
        hold = self.db.get(SeatHold, hold_id)
        if hold is None:
            raise NotFoundError("That seat hold does not exist.")
        if not hold.is_live:
            raise HoldExpiredError()
        new_expiry = datetime.now(UTC) + timedelta(seconds=seconds)
        if new_expiry <= hold.expires_at:
            return hold.expires_at
        updated = self.repo.extend_hold(hold_id, new_expiry)
        if updated == 0:
            raise HoldExpiredError()
        self.db.flush()
        self.db.refresh(hold)
        logger.info("hold_extended", hold_id=str(hold_id), new_expiry=new_expiry.isoformat())
        return new_expiry

    def confirm_hold(
        self, *, hold_id: uuid.UUID, booking_id: uuid.UUID, expected_seats: int
    ) -> list[ClaimedSeat]:
        """Turn a live hold into booked seats. Raises if it lapsed."""
        confirmed = self.repo.confirm_hold_seats(hold_id=hold_id, booking_id=booking_id)
        if len(confirmed) != expected_seats:
            logger.warning(
                "hold_confirm_short",
                hold_id=str(hold_id),
                expected=expected_seats,
                got=len(confirmed),
            )
            raise HoldExpiredError(
                "Your seat hold expired before the payment completed.",
                details={"expected_seats": expected_seats, "confirmed_seats": len(confirmed)},
            )
        hold = self.db.get(SeatHold, hold_id)
        if hold is not None:
            hold.status = HoldStatus.CONVERTED
        self.db.flush()
        return confirmed

    def release_booking(self, booking_id: uuid.UUID, show_id: uuid.UUID) -> int:
        released = self.repo.release_booking_seats(booking_id)
        self.repo.refresh_available_count(show_id)
        return released

    # ------------------------------------------------------------------
    # Rules
    # ------------------------------------------------------------------
    def _assert_bookable(self, show: Show) -> None:
        now = datetime.now(UTC)
        if show.status == ShowStatus.CANCELLED:
            raise ShowNotBookableError("This show has been cancelled.")
        if show.status not in (ShowStatus.OPEN, ShowStatus.SCHEDULED):
            raise ShowNotBookableError("This show is not open for booking.")
        if show.sales_open_at and now < show.sales_open_at:
            raise ShowNotBookableError(
                "Booking for this show has not opened yet.",
                details={"opens_at": show.sales_open_at.isoformat()},
            )
        if now >= show.sales_close_at:
            raise ShowNotBookableError("Booking for this show has closed.")

    @staticmethod
    def _assert_seats_belong_to_show(
        seat_ids: list[uuid.UUID], seat_map: list[SeatMapRow]
    ) -> None:
        known = {r.seat_id for r in seat_map}
        unknown = [str(s) for s in seat_ids if s not in known]
        if unknown:
            raise SeatRuleViolationError(
                "Some of those seats do not belong to this show.",
                details={"unknown_seat_ids": unknown},
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _load_show(self, show_id: uuid.UUID) -> Show:
        show = self.db.execute(
            select(Show).where(Show.id == show_id)
        ).scalar_one_or_none()
        if show is None:
            raise NotFoundError("That show does not exist.")
        return show

    @staticmethod
    def _labels_for(claimed: list[ClaimedSeat], seat_map: list[SeatMapRow]) -> list[str]:
        by_id = {r.seat_id: r for r in seat_map}
        labels = []
        for c in claimed:
            r = by_id.get(c.seat_id)
            labels.append(f"{r.row_label}{r.seat_number}" if r else str(c.seat_id))
        return sorted(labels)
