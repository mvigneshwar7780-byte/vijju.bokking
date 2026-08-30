"""Operator operations: venues, layouts, catalogue and scheduling.

Authorization is *not* done here -- the router resolves it through
``admin.authorization`` and passes down an already-authorised entity. Keeping
the check at the edge means there is one place to audit, rather than a
permission test scattered through every method.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import _new_uuid7
from app.core.enums import BookingStatus, ShowStatus
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.modules.admin.schemas import (
    BulkShowCreate,
    LayoutCreate,
    MovieCreate,
    MovieUpdate,
    ShowCreate,
)
from app.modules.catalog.models import Genre, Language, Movie, MovieCredit, Person
from app.modules.scheduling.models import Format, Show, ShowPrice
from app.modules.venues.models import Cinema, Screen, Seat, SeatCategory

logger = get_logger(__name__)


def _slug(value: str) -> str:
    out = "".join(c.lower() if c.isalnum() else "-" for c in value)
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")


class OperatorService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ================================================================ venue ==
    def unique_slug(self, model, base: str) -> str:  # noqa: ANN001
        slug = _slug(base)
        candidate, n = slug, 2
        while self.db.execute(select(model.id).where(model.slug == candidate)).first():
            candidate = f"{slug}-{n}"
            n += 1
        return candidate

    # =============================================================== layout ==
    def apply_layout(self, screen: Screen, payload: LayoutCreate) -> Screen:
        """Replace a screen's seating plan.

        Refuses outright if any show on this screen has sold or held a seat.
        Re-lettering seats under a live booking would leave a customer holding a
        ticket for a seat that no longer exists -- the sort of thing that is
        obvious in hindsight and invisible until someone tries it.
        """
        sold = self.db.execute(
            select(func.count())
            .select_from(Show)
            .where(
                Show.screen_id == screen.id,
                Show.status != ShowStatus.CANCELLED,
                Show.total_seats > Show.available_seats,
            )
        ).scalar_one()
        if sold:
            raise ConflictError(
                "This screen has shows with sold or held seats. Cancel or let "
                "those shows finish before changing the seating plan.",
                code="LAYOUT_LOCKED",
                details={"shows_with_activity": int(sold)},
            )
        # No seat is sold or held anywhere on this screen, so any existing shows
        # can be rebuilt against the new plan. Removing them (rather than
        # silently leaving stale seat rows) keeps show_seats consistent with the
        # layout it was generated from.
        self.db.execute(
            delete(Show).where(
                Show.screen_id == screen.id, Show.status != ShowStatus.CANCELLED
            )
        )

        categories = {
            c.code: c
            for c in self.db.execute(
                select(SeatCategory).where(SeatCategory.cinema_id == screen.cinema_id)
            ).scalars()
        }
        missing = sorted({r.category_code.upper() for r in payload.rows} - set(categories))
        if missing:
            raise ValidationError(
                f"Unknown seat categories for this cinema: {', '.join(missing)}. "
                "Create them first.",
                code="UNKNOWN_SEAT_CATEGORY",
                details={"missing": missing},
            )

        duplicate = [
            label
            for label, count in _counts(r.row_label for r in payload.rows).items()
            if count > 1
        ]
        if duplicate:
            raise ValidationError(
                f"Duplicate row labels: {', '.join(duplicate)}.", code="DUPLICATE_ROW"
            )

        self.db.execute(delete(Seat).where(Seat.screen_id == screen.id))

        rows: list[dict] = []
        for row_index, row in enumerate(payload.rows):
            category = categories[row.category_code.upper()]
            column = 0
            for seat_number in range(1, row.seat_count + 1):
                rows.append(
                    {
                        "id": _new_uuid7(),
                        "screen_id": screen.id,
                        "category_id": category.id,
                        "row_label": row.row_label,
                        "row_index": row_index,
                        "seat_number": seat_number,
                        "column_index": column,
                        "is_aisle": seat_number in (1, row.seat_count, *row.aisles_after)
                        or seat_number - 1 in row.aisles_after,
                        "is_wheelchair_accessible": seat_number in row.wheelchair_seats,
                        "is_companion": False,
                    }
                )
                column += 2 if seat_number in row.aisles_after else 1

        self.db.execute(insert(Seat), rows)
        screen.total_seats = len(rows)
        screen.layout_version += 1
        screen.layout_meta = {
            **(screen.layout_meta or {}),
            "screen_label": payload.screen_label,
            "aisles_after_columns": sorted(
                {a for r in payload.rows for a in r.aisles_after}
            ),
        }
        self.db.flush()
        logger.info(
            "layout_applied",
            screen_id=str(screen.id),
            seats=len(rows),
            version=screen.layout_version,
        )
        return screen

    # ============================================================== catalog ==
    def create_movie(self, payload: MovieCreate, *, author_id: uuid.UUID) -> Movie:
        movie = Movie(
            title=payload.title.strip(),
            slug=self.unique_slug(Movie, payload.title),
            synopsis=payload.synopsis,
            runtime_minutes=payload.runtime_minutes,
            certification=payload.certification,
            release_date=payload.release_date,
            status=payload.status,
            tagline=payload.tagline,
            poster_url=payload.poster_url,
            backdrop_url=payload.backdrop_url,
            trailer_url=payload.trailer_url,
            ai_attributes=payload.attributes or {},
            created_by_user_id=author_id,
        )
        if payload.original_language_code:
            movie.original_language_id = self._language(payload.original_language_code).id
        movie.languages = [self._language(c) for c in payload.language_codes]
        movie.genres = [self._genre(n) for n in payload.genre_names]
        self.db.add(movie)
        self.db.flush()

        for order, name in enumerate(payload.cast[:10]):
            self.db.add(
                MovieCredit(
                    movie_id=movie.id,
                    person_id=self._person(name).id,
                    credit_type="cast",
                    billing_order=order,
                )
            )
        if payload.director:
            self.db.add(
                MovieCredit(
                    movie_id=movie.id,
                    person_id=self._person(payload.director).id,
                    credit_type="crew",
                    job="Director",
                    billing_order=0,
                )
            )
        self.db.flush()
        logger.info("movie_created", movie_id=str(movie.id), title=movie.title)
        return movie

    def update_movie(self, movie: Movie, payload: MovieUpdate) -> Movie:
        data = payload.model_dump(exclude_unset=True)
        for field in (
            "title", "synopsis", "runtime_minutes", "certification", "release_date",
            "status", "tagline", "poster_url", "backdrop_url", "trailer_url", "is_active",
        ):
            if field in data and data[field] is not None:
                setattr(movie, field, data[field])
        if data.get("language_codes") is not None:
            movie.languages = [self._language(c) for c in data["language_codes"]]
        if data.get("genre_names") is not None:
            movie.genres = [self._genre(n) for n in data["genre_names"]]
        if data.get("attributes") is not None:
            movie.ai_attributes = {**(movie.ai_attributes or {}), **data["attributes"]}
        self.db.flush()
        return movie

    def _language(self, code: str) -> Language:
        lang = self.db.execute(
            select(Language).where(Language.code == code.strip().lower())
        ).scalar_one_or_none()
        if lang is None:
            raise ValidationError(
                f"Unknown language code '{code}'.", code="UNKNOWN_LANGUAGE"
            )
        return lang

    def _genre(self, name: str) -> Genre:
        genre = self.db.execute(
            select(Genre).where(func.lower(Genre.name) == name.strip().lower())
        ).scalar_one_or_none()
        if genre is None:
            genre = Genre(name=name.strip().title(), slug=_slug(name))
            self.db.add(genre)
            self.db.flush()
        return genre

    def _person(self, name: str) -> Person:
        slug = _slug(name)
        person = self.db.execute(
            select(Person).where(Person.slug == slug)
        ).scalar_one_or_none()
        if person is None:
            person = Person(name=name.strip(), slug=slug)
            self.db.add(person)
            self.db.flush()
        return person

    # =========================================================== scheduling ==
    def create_show(self, cinema: Cinema, payload: ShowCreate) -> Show:
        screen = self.db.get(Screen, payload.screen_id)
        if screen is None or screen.cinema_id != cinema.id:
            raise ValidationError(
                "That screen does not belong to this cinema.", code="SCREEN_MISMATCH"
            )
        if not screen.is_active:
            raise ValidationError("That screen is not active.", code="SCREEN_INACTIVE")
        if screen.total_seats == 0:
            raise ValidationError(
                "This screen has no seating plan yet. Configure the layout first.",
                code="NO_LAYOUT",
            )

        movie = self.db.get(Movie, payload.movie_id)
        if movie is None:
            raise NotFoundError("That movie does not exist.")

        fmt = self.db.execute(
            select(Format).where(Format.code == payload.format_code.upper())
        ).scalar_one_or_none()
        if fmt is None:
            raise ValidationError(
                f"Unknown format '{payload.format_code}'.", code="UNKNOWN_FORMAT"
            )
        supported = {f.upper() for f in (screen.supported_formats or [])}
        if fmt.code.upper() not in supported:
            raise ValidationError(
                f"{screen.name} does not support {fmt.code}. It supports: "
                f"{', '.join(sorted(supported))}.",
                code="FORMAT_UNSUPPORTED",
            )

        # Local wall time -> the cinema's zone -> an absolute instant.
        tz = ZoneInfo(cinema.timezone)
        local_start = datetime.combine(payload.show_date, payload.start_time, tzinfo=tz)
        starts_at = local_start.astimezone(UTC)
        ends_at = starts_at + timedelta(
            minutes=movie.runtime_minutes + payload.turnaround_minutes
        )
        if starts_at <= datetime.now(UTC):
            raise ValidationError(
                "That showtime is in the past.", code="SHOWTIME_IN_PAST"
            )

        self._assert_prices_cover_screen(screen, payload.prices)

        show = Show(
            id=_new_uuid7(),
            movie_id=movie.id,
            screen_id=screen.id,
            cinema_id=cinema.id,
            city_id=cinema.city_id,
            format_id=fmt.id,
            audio_language_id=self._language(payload.audio_language_code).id,
            subtitle_language_id=(
                self._language(payload.subtitle_language_code).id
                if payload.subtitle_language_code
                else None
            ),
            starts_at=starts_at,
            ends_at=ends_at,
            show_date=payload.show_date,
            status=ShowStatus.OPEN,
            sales_open_at=payload.sales_open_at,
            sales_close_at=starts_at
            - timedelta(minutes=settings.booking_cutoff_minutes),
            screen_layout_version=screen.layout_version,
        )
        # Read what the error message needs *before* the flush. A failed flush
        # expires the session's instances, so touching `screen.name` afterwards
        # triggers a lazy reload on a poisoned session and raises
        # PendingRollbackError -- which surfaces as a 500 and hides the real,
        # actionable conflict.
        screen_name = screen.name

        # The insert runs inside a SAVEPOINT so a constraint violation rolls
        # back only this statement. Without it the whole transaction is
        # unusable, which also breaks `create_shows_bulk`, where one clashing
        # slot must not abort the rest of the week.
        savepoint = self.db.begin_nested()
        self.db.add(show)
        try:
            self.db.flush()
            savepoint.commit()
        except IntegrityError as exc:
            savepoint.rollback()
            # The EXCLUDE constraint on (screen_id, time range) rejects overlaps
            # in the database. Translate it into something an operator can act
            # on rather than a 500.
            if "ex_shows_screen_no_overlap" in str(exc.orig):
                raise ConflictError(
                    f"{screen_name} already has a show running at that time. "
                    "Pick a different time or screen.",
                    code="SHOW_OVERLAP",
                ) from exc
            if "uq_shows_screen_id_starts_at" in str(exc.orig):
                raise ConflictError(
                    f"{screen_name} already has a show starting at exactly that time.",
                    code="SHOW_DUPLICATE",
                ) from exc
            raise

        self.db.execute(
            insert(ShowPrice),
            [
                {
                    "id": _new_uuid7(),
                    "show_id": show.id,
                    "seat_category_id": p.seat_category_id,
                    "price_minor": p.price_minor,
                }
                for p in payload.prices
            ],
        )
        self.db.flush()

        from app.modules.inventory.service import InventoryService

        self.db.refresh(show)
        InventoryService(self.db).materialize_seats(show)
        logger.info(
            "show_created",
            show_id=str(show.id),
            cinema_id=str(cinema.id),
            starts_at=starts_at.isoformat(),
        )
        return show

    def create_shows_bulk(self, cinema: Cinema, payload: BulkShowCreate) -> dict:
        """The same slots repeated across a date range.

        Conflicts are collected rather than fatal: an operator filling a week
        should not lose the whole request because one slot clashes with an
        existing booking-carrying show.
        """
        if payload.end_date < payload.start_date:
            raise ValidationError("end_date is before start_date.", code="BAD_RANGE")
        span = (payload.end_date - payload.start_date).days
        if span > 60:
            raise ValidationError(
                "Schedule at most 60 days at a time.", code="RANGE_TOO_LONG"
            )

        created: list[uuid.UUID] = []
        skipped: list[str] = []
        for offset in range(span + 1):
            day = payload.start_date + timedelta(days=offset)
            for start_time in payload.start_times:
                single = ShowCreate(
                    screen_id=payload.screen_id,
                    movie_id=payload.movie_id,
                    format_code=payload.format_code,
                    audio_language_code=payload.audio_language_code,
                    subtitle_language_code=payload.subtitle_language_code,
                    show_date=day,
                    start_time=start_time,
                    turnaround_minutes=payload.turnaround_minutes,
                    prices=payload.prices,
                )
                savepoint = self.db.begin_nested()
                try:
                    show = self.create_show(cinema, single)
                    savepoint.commit()
                    created.append(show.id)
                except (ConflictError, ValidationError) as exc:
                    savepoint.rollback()
                    skipped.append(f"{day} {start_time:%H:%M} — {exc.message}")
        return {
            "created": len(created),
            "skipped_conflicts": skipped,
            "show_ids": created,
        }

    def set_prices(self, show: Show, prices: list) -> Show:  # noqa: ANN001
        """Reprice a show.

        Only affects seats not yet sold: ``booking_seats`` snapshots the price a
        customer paid, so a later change cannot alter an existing invoice.
        """
        screen = self.db.get(Screen, show.screen_id)
        assert screen is not None
        self._assert_prices_cover_screen(screen, prices)

        self.db.execute(delete(ShowPrice).where(ShowPrice.show_id == show.id))
        self.db.execute(
            insert(ShowPrice),
            [
                {
                    "id": _new_uuid7(),
                    "show_id": show.id,
                    "seat_category_id": p.seat_category_id,
                    "price_minor": p.price_minor,
                }
                for p in prices
            ],
        )
        self.db.flush()

        fmt = self.db.get(Format, show.format_id)
        surcharge = fmt.surcharge_minor if fmt else 0
        from sqlalchemy import text

        updated = self.db.execute(
            text(
                """
                UPDATE show_seats ss
                   SET price_minor = sp.price_minor + :surcharge,
                       updated_at = now()
                  FROM show_prices sp
                 WHERE sp.show_id = ss.show_id
                   AND sp.seat_category_id = ss.seat_category_id
                   AND ss.show_id = :show_id
                   AND ss.status IN ('available', 'blocked')
                """
            ),
            {"show_id": show.id, "surcharge": surcharge},
        ).rowcount
        self.db.flush()
        logger.info("show_repriced", show_id=str(show.id), seats_updated=updated)
        return show

    def _assert_prices_cover_screen(self, screen: Screen, prices: list) -> None:  # noqa: ANN001
        """Every seat category present in the screen must be priced.

        Otherwise materialisation silently falls back to the category default
        and the operator's intent is quietly ignored.
        """
        needed = {
            row[0]
            for row in self.db.execute(
                select(Seat.category_id).where(Seat.screen_id == screen.id).distinct()
            )
        }
        given = {p.seat_category_id for p in prices}
        missing = needed - given
        if missing:
            names = [
                row[0]
                for row in self.db.execute(
                    select(SeatCategory.name).where(SeatCategory.id.in_(missing))
                )
            ]
            raise ValidationError(
                f"Set a price for every seat category in this screen. Missing: "
                f"{', '.join(sorted(names))}.",
                code="INCOMPLETE_PRICING",
                details={"missing_category_ids": [str(m) for m in missing]},
            )
        stray = given - needed
        if stray:
            raise ValidationError(
                "Prices were given for seat categories that do not exist in this "
                "screen.",
                code="STRAY_PRICING",
                details={"unexpected_category_ids": [str(s) for s in stray]},
            )

    def cancel_show(self, show: Show, *, reason: str, actor_id: uuid.UUID) -> dict:
        """Cancel a show and make every affected customer whole.

        The order matters: refunds are created for confirmed bookings *before*
        the seats are released, so a failure part-way leaves an obligation
        recorded rather than seats silently resold under a paid ticket.
        """
        from app.modules.booking.models import Booking
        from app.modules.booking.service import BookingService
        from app.modules.inventory.repository import InventoryRepository
        from app.modules.payments.service import PaymentService

        if show.status == ShowStatus.CANCELLED:
            raise ConflictError("That show is already cancelled.")

        bookings = list(
            self.db.execute(
                select(Booking).where(
                    Booking.show_id == show.id,
                    Booking.status.in_(
                        [
                            BookingStatus.CONFIRMED,
                            BookingStatus.DRAFT,
                            BookingStatus.PAYMENT_PENDING,
                        ]
                    ),
                )
            ).scalars()
        )

        payments = PaymentService(self.db)
        booking_service = BookingService(self.db)
        refunds = 0
        refund_total = 0

        for booking in bookings:
            if booking.status == BookingStatus.CONFIRMED:
                # A show cancellation is the operator's fault, so the customer
                # gets everything back -- including the convenience fee that a
                # voluntary cancellation would forfeit.
                refund = payments.refund_for_cancellation(
                    booking, booking.total_minor, reason="show_cancelled"
                )
                if refund is not None:
                    refunds += 1
                    refund_total += refund.amount_minor
            booking.status = BookingStatus.REVOKED
            booking.cancelled_at = datetime.now(UTC)
            booking.cancellation_reason = f"Show cancelled: {reason}"
            booking_service._deactivate_seats(booking)

        repo = InventoryRepository(self.db)
        from sqlalchemy import text

        released = self.db.execute(
            text(
                """
                UPDATE show_seats
                   SET status = 'available', booking_id = NULL,
                       hold_id = NULL, hold_expires_at = NULL, updated_at = now()
                 WHERE show_id = :show_id AND status <> 'available'
                """
            ),
            {"show_id": show.id},
        ).rowcount

        show.status = ShowStatus.CANCELLED
        show.cancellation_reason = reason
        self.db.flush()
        repo.refresh_available_count(show.id)

        logger.info(
            "show_cancelled",
            show_id=str(show.id),
            bookings_revoked=len(bookings),
            refunds=refunds,
            refund_total_minor=refund_total,
        )
        return {
            "show_id": show.id,
            "bookings_revoked": len(bookings),
            "refunds_created": refunds,
            "refund_total_minor": refund_total,
            "seats_released": int(released or 0),
        }


def _counts(values) -> dict:  # noqa: ANN001
    out: dict = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return out
