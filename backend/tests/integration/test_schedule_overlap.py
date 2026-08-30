"""A screen cannot run two overlapping shows.

The unique constraint on ``(screen_id, starts_at)`` only catches identical
start times. Overlap is the real hazard: a 168-minute film at 17:00 and another
at 18:00 are two different start times and one double-booked auditorium.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.core.enums import ShowStatus
from app.modules.scheduling.models import Show


def _template(db) -> Show:  # noqa: ANN001
    return db.execute(select(Show).order_by(Show.starts_at).limit(1)).scalar_one()


# The seed schedules six days out, so anything past that is guaranteed-empty
# calendar space. Building the fixtures there keeps these tests about the
# constraint rather than about whatever the seed happens to have booked.
FREE_WINDOW = timedelta(days=45)


def _clone(base: Show, *, offset_minutes: int, duration_minutes: int) -> Show:
    starts = base.starts_at + FREE_WINDOW + timedelta(minutes=offset_minutes)
    return Show(
        movie_id=base.movie_id,
        screen_id=base.screen_id,
        cinema_id=base.cinema_id,
        city_id=base.city_id,
        format_id=base.format_id,
        audio_language_id=base.audio_language_id,
        starts_at=starts,
        ends_at=starts + timedelta(minutes=duration_minutes),
        show_date=base.show_date,
        status=ShowStatus.OPEN,
        sales_close_at=starts - timedelta(minutes=20),
    )


def test_overlapping_show_on_same_screen_is_rejected(db) -> None:  # noqa: ANN001
    base = _template(db)
    db.add(_clone(base, offset_minutes=0, duration_minutes=180))
    db.flush()

    # Starts an hour into the show above -- squarely inside it.
    db.add(_clone(base, offset_minutes=60, duration_minutes=120))
    with pytest.raises(IntegrityError) as exc:
        db.flush()
    assert "ex_shows_screen_no_overlap" in str(exc.value)


def test_back_to_back_show_is_allowed(db) -> None:  # noqa: ANN001
    """Ranges are half-open, so a show may start exactly when the last ends."""
    base = _template(db)
    db.add(_clone(base, offset_minutes=0, duration_minutes=180))
    db.flush()

    # Starts at the exact minute the previous one ends.
    db.add(_clone(base, offset_minutes=180, duration_minutes=120))
    db.flush()  # must not raise


def test_same_time_on_a_different_screen_is_allowed(db) -> None:  # noqa: ANN001
    base = _template(db)
    other_screen = db.execute(
        text(
            "SELECT id FROM screens WHERE id <> CAST(:s AS uuid) "
            "AND cinema_id = CAST(:c AS uuid) LIMIT 1"
        ),
        {"s": base.screen_id, "c": base.cinema_id},
    ).scalar_one()
    db.add(_clone(base, offset_minutes=0, duration_minutes=180))
    db.flush()

    clone = _clone(base, offset_minutes=60, duration_minutes=120)
    clone.screen_id = other_screen
    db.add(clone)
    db.flush()  # different auditorium, no conflict


def test_cancelled_show_frees_its_slot(db) -> None:  # noqa: ANN001
    """Cancelling a show must make the slot immediately reschedulable."""
    base = _template(db)
    first = _clone(base, offset_minutes=0, duration_minutes=180)
    db.add(first)
    db.flush()

    first.status = ShowStatus.CANCELLED
    db.flush()

    # The slot is free again the moment the show is cancelled.
    db.add(_clone(base, offset_minutes=60, duration_minutes=120))
    db.flush()
