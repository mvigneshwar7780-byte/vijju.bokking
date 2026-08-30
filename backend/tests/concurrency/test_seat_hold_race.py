"""The tests the whole system rests on: two people, one seat.

These deliberately do NOT use the transactional-rollback `db` fixture. They open
real connections, run real transactions concurrently in threads, and commit --
because the property under test (Postgres re-evaluating an UPDATE's WHERE clause
against a concurrently committed row version) only exists between real
transactions.

Each test runs twice: once with the per-show advisory lock enabled, and once
with it disabled. The second variant is the important one -- it proves the
conditional UPDATE is safe *on its own*, and that the advisory lock is a
latency/deadlock optimisation rather than the thing preventing double-booking.
"""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import pytest
from sqlalchemy import text

from app.core.db import SessionLocal
from app.core.errors import SeatUnavailableError
from app.modules.inventory.service import InventoryService

pytestmark = pytest.mark.concurrency


@dataclass
class Attempt:
    worker: int
    ok: bool
    hold_id: uuid.UUID | None
    error: str | None


def _fresh_show_and_seats(n_seats: int) -> tuple[uuid.UUID, list[uuid.UUID]]:
    """Pick an untouched show and n adjacent seats in one row.

    Adjacent-in-one-row matters: it keeps the no-orphan-seat rule satisfied so
    the test exercises concurrency rather than tripping a validation rule.
    """
    with SessionLocal() as db:
        show_id = db.execute(
            text(
                """
                SELECT s.id
                  FROM shows s
                 WHERE s.status = 'open'
                   AND s.sales_close_at > now()
                   AND s.available_seats = s.total_seats
                 ORDER BY s.starts_at
                 LIMIT 1
                """
            )
        ).scalar_one()
        seat_ids = [
            row[0]
            for row in db.execute(
                text(
                    """
                    SELECT ss.seat_id
                      FROM show_seats ss
                      JOIN seats se ON se.id = ss.seat_id
                     WHERE ss.show_id = :show_id
                       AND ss.status = 'available'
                       AND se.row_label = 'E'
                     ORDER BY se.seat_number
                     LIMIT :n
                    """
                ),
                {"show_id": show_id, "n": n_seats},
            )
        ]
    return show_id, seat_ids


def _try_hold(
    worker: int,
    show_id: uuid.UUID,
    seat_ids: list[uuid.UUID],
    *,
    use_advisory_lock: bool,
) -> Attempt:
    """One worker, one connection, one transaction, committed or rolled back."""
    with SessionLocal() as db:
        service = InventoryService(db, use_advisory_lock=use_advisory_lock)
        try:
            hold = service.hold_seats(
                show_id=show_id,
                seat_ids=seat_ids,
                session_key=f"worker-{worker}-{uuid.uuid4().hex[:8]}",
            )
            db.commit()
            return Attempt(worker, True, hold.hold_id, None)
        except SeatUnavailableError as exc:
            db.rollback()
            return Attempt(worker, False, None, exc.code)
        except Exception as exc:  # noqa: BLE001 - surface anything unexpected
            db.rollback()
            return Attempt(worker, False, None, f"{type(exc).__name__}: {exc}")


def _seat_state(show_id: uuid.UUID, seat_ids: list[uuid.UUID]) -> list[tuple]:
    with SessionLocal() as db:
        return list(
            db.execute(
                text(
                    """
                    SELECT ss.seat_id, ss.status::text, ss.hold_id
                      FROM show_seats ss
                     WHERE ss.show_id = :show_id
                       AND ss.seat_id = ANY(CAST(:seat_ids AS uuid[]))
                     ORDER BY ss.seat_id
                    """
                ),
                {"show_id": show_id, "seat_ids": [str(s) for s in seat_ids]},
            )
        )


def _cleanup(show_id: uuid.UUID) -> None:
    with SessionLocal() as db:
        db.execute(
            text(
                """
                UPDATE show_seats
                   SET status = 'available', hold_id = NULL,
                       hold_expires_at = NULL, booking_id = NULL
                 WHERE show_id = :show_id
                """
            ),
            {"show_id": show_id},
        )
        db.execute(text("DELETE FROM seat_holds WHERE show_id = :s"), {"s": show_id})
        db.execute(
            text(
                "UPDATE shows SET available_seats = total_seats WHERE id = :s"
            ),
            {"s": show_id},
        )
        db.commit()


# ---------------------------------------------------------------------------


@pytest.mark.parametrize("use_advisory_lock", [True, False], ids=["with_lock", "no_lock"])
def test_only_one_worker_wins_the_same_seat(seeded: None, use_advisory_lock: bool) -> None:
    """20 workers race for the identical single seat. Exactly one may win."""
    show_id, seat_ids = _fresh_show_and_seats(1)
    assert len(seat_ids) == 1
    workers = 20

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            attempts = list(
                pool.map(
                    lambda i: _try_hold(
                        i, show_id, seat_ids, use_advisory_lock=use_advisory_lock
                    ),
                    range(workers),
                )
            )

        winners = [a for a in attempts if a.ok]
        losers = [a for a in attempts if not a.ok]

        assert len(winners) == 1, (
            f"expected exactly 1 winner, got {len(winners)}: "
            f"{[(a.worker, a.hold_id) for a in winners]}"
        )
        assert len(losers) == workers - 1
        # Every loser must fail for the *right* reason, not a crash.
        assert {a.error for a in losers} == {"SEAT_UNAVAILABLE"}, {a.error for a in losers}

        state = _seat_state(show_id, seat_ids)
        assert len(state) == 1
        _seat, status, hold_id = state[0]
        assert status == "held"
        assert hold_id == winners[0].hold_id
    finally:
        _cleanup(show_id)


@pytest.mark.parametrize("use_advisory_lock", [True, False], ids=["with_lock", "no_lock"])
def test_overlapping_seat_sets_never_double_allocate(
    seeded: None, use_advisory_lock: bool
) -> None:
    """Workers request overlapping runs of seats. No seat may end up in two holds.

    This is the case that breaks naive implementations: a partial win must not
    be committed. Worker A asking for seats 1-3 and worker B asking for 2-4 must
    resolve to exactly one of them holding its full set, with the other holding
    nothing at all -- never A holding {1,3} and B holding {2,4}.
    """
    show_id, seat_ids = _fresh_show_and_seats(6)
    assert len(seat_ids) == 6

    # Overlapping windows of 3 adjacent seats: [0:3], [1:4], [2:5], [3:6]
    requests = [seat_ids[i : i + 3] for i in range(4)]

    try:
        with ThreadPoolExecutor(max_workers=len(requests)) as pool:
            attempts = list(
                pool.map(
                    lambda pair: _try_hold(
                        pair[0], show_id, pair[1], use_advisory_lock=use_advisory_lock
                    ),
                    list(enumerate(requests)),
                )
            )

        winners = [a for a in attempts if a.ok]
        assert winners, "at least one worker should have succeeded"

        state = _seat_state(show_id, seat_ids)
        held = [(s, st, h) for s, st, h in state if st == "held"]

        # No seat may be attributed to more than one hold, and every held seat
        # must belong to a hold that actually reported success.
        winning_hold_ids = {a.hold_id for a in winners}
        for _seat, _status, hold_id in held:
            assert hold_id in winning_hold_ids, "seat held by a hold that did not win"

        # Each winner must hold its complete set -- no partial allocations.
        with SessionLocal() as db:
            for winner in winners:
                count = db.execute(
                    text("SELECT count(*) FROM show_seats WHERE hold_id = :h AND status='held'"),
                    {"h": winner.hold_id},
                ).scalar_one()
                assert count == 3, f"winner {winner.worker} holds {count} seats, expected 3"

        # And the losers must hold nothing whatsoever.
        with SessionLocal() as db:
            orphaned = db.execute(
                text(
                    """
                    SELECT count(*)
                      FROM show_seats ss
                      JOIN seat_holds sh ON sh.id = ss.hold_id
                     WHERE ss.show_id = :show_id
                       AND sh.id <> ALL(CAST(:winners AS uuid[]))
                    """
                ),
                {"show_id": show_id, "winners": [str(w) for w in winning_hold_ids]},
            ).scalar_one()
            assert orphaned == 0, "a losing transaction left seats allocated"
    finally:
        _cleanup(show_id)


def test_available_counter_matches_reality_under_contention(seeded: None) -> None:
    """After a storm of concurrent holds, the cached counter must be exact."""
    show_id, seat_ids = _fresh_show_and_seats(8)
    workers = 16

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(
                pool.map(
                    lambda i: _try_hold(
                        i, show_id, [seat_ids[i % len(seat_ids)]], use_advisory_lock=True
                    ),
                    range(workers),
                )
            )

        with SessionLocal() as db:
            cached, actual = db.execute(
                text(
                    """
                    SELECT s.available_seats,
                           (SELECT count(*) FROM show_seats ss
                             WHERE ss.show_id = s.id
                               AND (ss.status = 'available'
                                    OR (ss.status='held' AND ss.hold_expires_at <= now())))
                      FROM shows s WHERE s.id = :s
                    """
                ),
                {"s": show_id},
            ).one()
        assert cached == actual, f"counter drifted: cached={cached} actual={actual}"
    finally:
        _cleanup(show_id)
