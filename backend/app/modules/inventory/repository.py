"""Seat inventory persistence -- the concurrency-critical SQL.

Read this file before changing anything about seat state. The safety of the
whole product rests on a handful of statements here, and every one of them is
written the way it is for a reason that is spelled out inline.

The one rule
------------
**Seat state changes only ever happen inside a single conditional UPDATE whose
WHERE clause re-checks the precondition.** Never "SELECT to check, then UPDATE":
between those two statements another transaction can and will take the seat.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID as PGUUID
from sqlalchemy.orm import Session



@dataclass(frozen=True, slots=True)
class ClaimedSeat:
    """A seat this transaction successfully took."""

    show_seat_id: uuid.UUID
    seat_id: uuid.UUID
    seat_category_id: uuid.UUID
    price_minor: int


@dataclass(frozen=True, slots=True)
class SeatMapRow:
    show_seat_id: uuid.UUID
    seat_id: uuid.UUID
    row_label: str
    row_index: int
    seat_number: int
    column_index: int
    category_id: uuid.UUID
    category_code: str
    category_name: str
    price_minor: int
    status: str
    is_aisle: bool
    is_wheelchair_accessible: bool


_UUID_ARRAY = ARRAY(PGUUID(as_uuid=True))


class InventoryRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------
    def lock_show(self, show_id: uuid.UUID) -> None:
        """Take a transaction-scoped advisory lock keyed on the show.

        Strictly speaking this is *not* required for correctness -- the
        conditional UPDATE below is safe on its own, and
        ``tests/concurrency/`` proves it by running with this disabled.

        It is here for two practical reasons:

        1. **Deadlock elimination.** Two transactions holding overlapping seat
           sets can lock rows in different orders and deadlock. Postgres detects
           it and kills one, which surfaces to a customer as a random failure.
           Serialising per show removes the possibility entirely.
        2. **Predictable latency.** Contention becomes a short queue instead of
           a retry storm.

        The cost is that holds for one show serialise. A hold takes ~1ms, so a
        single show can still absorb hundreds of concurrent attempts per second,
        and *different* shows never contend -- which is the shape of real
        traffic.
        """
        self.db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"show:{show_id}"},
        )

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def get_seat_map(self, show_id: uuid.UUID) -> list[SeatMapRow]:
        """The seat map, with expired holds already reported as available.

        The CASE expression is the *lazy expiry* half of the design: a hold that
        has timed out becomes bookable the instant it lapses, without waiting
        for the sweeper to run. If this were left to the background job, users
        would stare at seats that are free but shown as taken for up to a
        minute -- and would then fail when they tried to book them.
        """
        rows = self.db.execute(
            text(
                """
                SELECT ss.id              AS show_seat_id,
                       ss.seat_id         AS seat_id,
                       s.row_label        AS row_label,
                       s.row_index        AS row_index,
                       s.seat_number      AS seat_number,
                       s.column_index     AS column_index,
                       s.is_aisle         AS is_aisle,
                       s.is_wheelchair_accessible AS is_wheelchair_accessible,
                       sc.id              AS category_id,
                       sc.code            AS category_code,
                       sc.name            AS category_name,
                       ss.price_minor     AS price_minor,
                       CASE
                         WHEN ss.status = 'held' AND ss.hold_expires_at <= now()
                           THEN 'available'
                         ELSE ss.status::text
                       END                AS status
                  FROM show_seats ss
                  JOIN seats s            ON s.id = ss.seat_id
                  JOIN seat_categories sc ON sc.id = ss.seat_category_id
                 WHERE ss.show_id = :show_id
                 ORDER BY s.row_index, s.column_index
                """
            ),
            {"show_id": show_id},
        ).mappings()
        return [SeatMapRow(**row) for row in rows]

    def count_available(self, show_id: uuid.UUID) -> int:
        return int(
            self.db.execute(
                text(
                    """
                    SELECT count(*)
                      FROM show_seats
                     WHERE show_id = :show_id
                       AND (status = 'available'
                            OR (status = 'held' AND hold_expires_at <= now()))
                    """
                ),
                {"show_id": show_id},
            ).scalar_one()
        )

    # ------------------------------------------------------------------
    # The claim
    # ------------------------------------------------------------------
    def claim_seats(
        self,
        *,
        show_id: uuid.UUID,
        seat_ids: Sequence[uuid.UUID],
        hold_id: uuid.UUID,
        expires_at: datetime,
    ) -> list[ClaimedSeat]:
        """Atomically take the requested seats. Returns only what was won.

        Why this is safe under Postgres' default READ COMMITTED
        ------------------------------------------------------
        When this UPDATE reaches a row that a concurrent transaction has locked,
        it blocks. When that transaction commits, Postgres does not simply
        proceed -- it re-fetches the row's new version and **re-evaluates this
        statement's WHERE clause against it** (EvalPlanQual). The other
        transaction set ``status = 'held'`` with a future ``hold_expires_at``,
        so ``status = 'available'`` is now false and
        ``hold_expires_at <= now()`` is false too. The row fails the qual and is
        silently skipped.

        The consequence: the loser updates *fewer rows than it asked for*, which
        the caller detects by comparing lengths. There is no interleaving in
        which both transactions claim the same seat. The check is done by the
        database, atomically, as part of the write -- not by application code
        looking at a stale read.

        Expired holds are reclaimed in the same predicate rather than by a prior
        cleanup pass, so there is no window where a lapsed seat is unbookable.

        Note the caller must treat a partial result as total failure and roll
        back: a half-claimed seat set is not an order.
        """
        if not seat_ids:
            return []

        stmt = text(
            """
            UPDATE show_seats
               SET status          = 'held',
                   hold_id         = :hold_id,
                   hold_expires_at = :expires_at,
                   updated_at      = now()
             WHERE show_id = :show_id
               AND seat_id = ANY(:seat_ids)
               AND (
                     status = 'available'
                     OR (status = 'held' AND hold_expires_at <= now())
                   )
         RETURNING id AS show_seat_id,
                   seat_id,
                   seat_category_id,
                   price_minor
            """
        ).bindparams(bindparam("seat_ids", type_=_UUID_ARRAY))

        rows = self.db.execute(
            stmt,
            {
                "show_id": show_id,
                "seat_ids": list(seat_ids),
                "hold_id": hold_id,
                "expires_at": expires_at,
            },
        ).mappings()
        return [ClaimedSeat(**row) for row in rows]

    # ------------------------------------------------------------------
    # Hold lifecycle
    # ------------------------------------------------------------------
    def release_hold_seats(self, hold_id: uuid.UUID) -> int:
        """Return every seat still held by this hold to the pool.

        Scoped by ``status = 'held'`` so it can never claw back a seat that has
        already been confirmed into a booking.
        """
        result = self.db.execute(
            text(
                """
                UPDATE show_seats
                   SET status          = 'available',
                       hold_id         = NULL,
                       hold_expires_at = NULL,
                       updated_at      = now()
                 WHERE hold_id = :hold_id
                   AND status  = 'held'
                """
            ),
            {"hold_id": hold_id},
        )
        return int(result.rowcount or 0)

    def extend_hold(self, hold_id: uuid.UUID, new_expiry: datetime) -> int:
        """Push a live hold's deadline out. Never revives a dead one.

        ``hold_expires_at > now()`` is the important half: extending an expired
        hold would resurrect a claim on seats another customer may already have
        taken.
        """
        seats = self.db.execute(
            text(
                """
                UPDATE show_seats
                   SET hold_expires_at = :new_expiry,
                       updated_at      = now()
                 WHERE hold_id = :hold_id
                   AND status  = 'held'
                   AND hold_expires_at > now()
                """
            ),
            {"hold_id": hold_id, "new_expiry": new_expiry},
        )
        self.db.execute(
            text(
                """
                UPDATE seat_holds
                   SET expires_at = :new_expiry
                 WHERE id = :hold_id
                   AND status = 'active'
                   AND expires_at > now()
                """
            ),
            {"hold_id": hold_id, "new_expiry": new_expiry},
        )
        return int(seats.rowcount or 0)

    def confirm_hold_seats(
        self, *, hold_id: uuid.UUID, booking_id: uuid.UUID
    ) -> list[ClaimedSeat]:
        """Flip held seats to booked. The last moment the hold can fail.

        ``hold_expires_at > now()`` means a hold that lapsed while the customer
        was on the payment page confirms *nothing*. The caller compares the
        returned count against the expected seat count and, if it is short,
        refuses to confirm the booking and triggers a refund of any captured
        payment. Taking money for a seat we cannot deliver is the one outcome
        this system must never produce.
        """
        rows = self.db.execute(
            text(
                """
                UPDATE show_seats
                   SET status     = 'booked',
                       booking_id = :booking_id,
                       updated_at = now()
                 WHERE hold_id = :hold_id
                   AND status  = 'held'
                   AND hold_expires_at > now()
             RETURNING id AS show_seat_id,
                       seat_id,
                       seat_category_id,
                       price_minor
                """
            ),
            {"hold_id": hold_id, "booking_id": booking_id},
        ).mappings()
        return [ClaimedSeat(**row) for row in rows]

    def release_booking_seats(self, booking_id: uuid.UUID) -> int:
        """Cancellation / refund path: booked seats go back on sale."""
        result = self.db.execute(
            text(
                """
                UPDATE show_seats
                   SET status          = 'available',
                       booking_id      = NULL,
                       hold_id         = NULL,
                       hold_expires_at = NULL,
                       updated_at      = now()
                 WHERE booking_id = :booking_id
                   AND status     = 'booked'
                """
            ),
            {"booking_id": booking_id},
        )
        return int(result.rowcount or 0)

    # ------------------------------------------------------------------
    # Counters
    # ------------------------------------------------------------------
    def refresh_available_count(self, show_id: uuid.UUID) -> int:
        """Recompute ``shows.available_seats`` from the seat rows.

        A full recount, not an increment. With a few hundred seats per show this
        costs microseconds on an indexed scan, and in exchange the counter can
        never drift -- no matter how holds expired, got reclaimed, or were
        released. Incremental counters are the classic source of "the listing
        says 3 seats left but the map is empty" bugs, and they are only worth
        the risk at a scale this app will never see. At 10k+ seats per event you
        would switch to deltas plus a nightly reconciliation job.
        """
        return int(
            self.db.execute(
                text(
                    """
                    UPDATE shows s
                       SET available_seats = sub.n
                      FROM (
                            SELECT count(*) AS n
                              FROM show_seats
                             WHERE show_id = :show_id
                               AND (status = 'available'
                                    OR (status = 'held' AND hold_expires_at <= now()))
                           ) sub
                     WHERE s.id = :show_id
                 RETURNING s.available_seats
                    """
                ),
                {"show_id": show_id},
            ).scalar_one()
        )

    # ------------------------------------------------------------------
    # Sweeper
    # ------------------------------------------------------------------
    def sweep_expired_holds(self, limit: int = 500) -> dict[str, int]:
        """Tidy up after lapsed holds.

        This is *housekeeping*, not correctness: the read path and the claim
        path both already treat a lapsed hold as available, so a seat is never
        stranded even if this never runs. What the sweep does is put rows back
        into a clean state so the tables reflect reality, statuses are truthful
        in reports, and the seat-map CASE expression stops doing work.

        It deliberately releases seats even when a booking against that hold is
        still ``payment_pending``. The alternative -- holding the seats
        indefinitely -- would let one stalled payment block a seat forever. The
        booking is marked ``expired`` instead, and if a late "captured" webhook
        arrives for it, the payments module flags the payment for automatic
        refund. Losing a sale is recoverable; taking money for a seat somebody
        else is sitting in is not.
        """
        released = self.db.execute(
            text(
                """
                WITH lapsed AS (
                    SELECT id
                      FROM seat_holds
                     WHERE status = 'active'
                       AND expires_at <= now()
                     ORDER BY expires_at
                     LIMIT :limit
                     FOR UPDATE SKIP LOCKED
                ),
                seats AS (
                    UPDATE show_seats ss
                       SET status          = 'available',
                           hold_id         = NULL,
                           hold_expires_at = NULL,
                           updated_at      = now()
                      FROM lapsed l
                     WHERE ss.hold_id = l.id
                       AND ss.status  = 'held'
                 RETURNING ss.show_id
                ),
                holds AS (
                    UPDATE seat_holds sh
                       SET status      = 'expired',
                           released_at = now()
                      FROM lapsed l
                     WHERE sh.id = l.id
                 RETURNING sh.id
                )
                SELECT (SELECT count(*) FROM seats) AS seats_released,
                       (SELECT count(*) FROM holds) AS holds_expired
                """
            ),
            {"limit": limit},
        ).mappings().one()

        # FOR UPDATE SKIP LOCKED above means two sweeper instances never fight
        # over the same hold -- they just take different ones.
        return {
            "seats_released": int(released["seats_released"]),
            "holds_expired": int(released["holds_expired"]),
        }

    def shows_needing_recount(self, limit: int = 200) -> list[uuid.UUID]:
        """Shows whose cached counter disagrees with the seat rows."""
        rows = self.db.execute(
            text(
                """
                SELECT s.id
                  FROM shows s
                  JOIN LATERAL (
                        SELECT count(*) AS n
                          FROM show_seats ss
                         WHERE ss.show_id = s.id
                           AND (ss.status = 'available'
                                OR (ss.status = 'held' AND ss.hold_expires_at <= now()))
                       ) actual ON TRUE
                 WHERE s.status IN ('scheduled', 'open')
                   AND s.available_seats <> actual.n
                 LIMIT :limit
                """
            ),
            {"limit": limit},
        )
        return [row[0] for row in rows]
