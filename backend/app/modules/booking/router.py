"""Booking endpoints."""

from __future__ import annotations

import hmac
import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession, IdempotencyKey, OptionalUser, Pagination
from app.core.errors import NotFoundError, PermissionDeniedError
from app.core.schemas import Page
from app.core.enums import BookingStatus
from app.modules.booking.schemas import (
    BookingFnbOut,
    BookingOut,
    BookingSeatOut,
    CancelBookingRequest,
    CancellationQuoteOut,
    CreateBookingRequest,
    PriceQuoteOut,
    QuoteRequest,
    RefundOut,
    ShowSummaryOut,
)
from app.modules.booking.service import BookingService
from app.modules.catalog.models import Language, Movie
from app.modules.scheduling.models import Format, Show
from app.modules.venues.models import Cinema, City, Screen

router = APIRouter(tags=["bookings"])


def _show_summary(db, show_id: uuid.UUID) -> ShowSummaryOut:  # noqa: ANN001
    show, movie, cinema, screen, city, fmt, language = db.execute(
        select(Show, Movie, Cinema, Screen, City, Format, Language)
        .join(Movie, Movie.id == Show.movie_id)
        .join(Cinema, Cinema.id == Show.cinema_id)
        .join(Screen, Screen.id == Show.screen_id)
        .join(City, City.id == Show.city_id)
        .join(Format, Format.id == Show.format_id)
        .join(Language, Language.id == Show.audio_language_id)
        .where(Show.id == show_id)
    ).one()
    return ShowSummaryOut(
        show_id=show.id,
        movie_title=movie.title,
        movie_poster_url=movie.poster_url,
        certification=movie.certification,
        cinema_name=cinema.name,
        screen_name=screen.name,
        city_name=city.name,
        format_code=fmt.code,
        language=language.name,
        starts_at=show.starts_at,
        ends_at=show.ends_at,
    )


def _to_out(db, booking) -> BookingOut:  # noqa: ANN001
    from app.modules.payments.models import Refund

    refunds = list(
        db.execute(
            select(Refund)
            .where(Refund.booking_id == booking.id)
            .order_by(Refund.created_at)
        ).scalars()
    )
    # Only settled money counts as refunded; a pending refund is an obligation,
    # not a returned payment, and showing it as complete would be a lie.
    refunded = sum(
        r.amount_minor for r in refunds if r.status.value == "succeeded"
    )

    cancellation = None
    if booking.status == BookingStatus.CONFIRMED:
        allowed, refund_minor, reason = BookingService(db).quote_cancellation(booking)
        cancellation = CancellationQuoteOut(
            refundable=allowed,
            refund_minor=refund_minor,
            forfeited_minor=booking.total_minor - refund_minor if allowed else 0,
            reason=reason,
        )

    return BookingOut(
        id=booking.id,
        booking_reference=booking.booking_reference,
        status=booking.status,
        seat_count=booking.seat_count,
        show=_show_summary(db, booking.show_id),
        seats=[BookingSeatOut.model_validate(s) for s in booking.seats],
        fnb_items=[BookingFnbOut.model_validate(f) for f in booking.fnb_items],
        ticket_subtotal_minor=booking.ticket_subtotal_minor,
        fnb_subtotal_minor=booking.fnb_subtotal_minor,
        discount_minor=booking.discount_minor,
        convenience_fee_minor=booking.convenience_fee_minor,
        tax_minor=booking.tax_minor,
        total_minor=booking.total_minor,
        currency=booking.currency,
        price_breakdown=booking.price_breakdown or {},
        offer_code=booking.offer_code,
        contact_email=booking.contact_email,
        contact_phone=booking.contact_phone,
        payment_deadline_at=booking.payment_deadline_at,
        confirmed_at=booking.confirmed_at,
        cancelled_at=booking.cancelled_at,
        qr_payload=booking.qr_payload,
        created_at=booking.created_at,
        refunds=[RefundOut.model_validate(r) for r in refunds],
        refunded_minor=refunded,
        cancellation=cancellation,
    )


@router.post("/bookings/quote", response_model=PriceQuoteOut)
def quote(payload: QuoteRequest, db: DbSession, user: OptionalUser) -> PriceQuoteOut:
    """Price a held selection without committing. Safe to call repeatedly.

    An invalid offer code returns the undiscounted price plus ``offer_error``
    rather than failing the request, so the checkout page can render both.
    """
    breakdown, discount, offer_error = BookingService(db).quote_hold(
        payload, user_id=user.id if user else None
    )
    return PriceQuoteOut(
        **breakdown.as_dict(),
        offer_code=discount.code if discount else None,
        offer_label=discount.label if discount else None,
        offer_error=offer_error,
    )


@router.post("/bookings", response_model=BookingOut, status_code=status.HTTP_201_CREATED)
def create_booking(
    payload: CreateBookingRequest,
    db: DbSession,
    user: OptionalUser,
    idempotency_key: IdempotencyKey = None,
) -> BookingOut:
    """Create a draft booking from a live hold, at a server-computed price.

    Send an ``Idempotency-Key`` header: a retried request then returns the same
    booking instead of creating a second one.
    """
    booking = BookingService(db).create_booking(
        payload,
        user_id=user.id if user else None,
        idempotency_key=idempotency_key,
    )
    db.commit()
    return _to_out(db, booking)


@router.get("/bookings", response_model=Page[BookingOut])
def list_bookings(db: DbSession, user: CurrentUser, page: Pagination) -> Page[BookingOut]:
    bookings, total = BookingService(db).list_for_user(
        user.id, offset=page.offset, limit=page.limit
    )
    return Page[BookingOut](
        items=[_to_out(db, b) for b in bookings],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.get("/bookings/{booking_id}", response_model=BookingOut)
def get_booking(booking_id: uuid.UUID, db: DbSession, user: OptionalUser) -> BookingOut:
    service = BookingService(db)
    booking = service.get(booking_id)
    # A guest booking has no owner, so possession of the id is the credential.
    # An owned booking is only visible to its owner.
    if booking.user_id is not None:
        if user is None or booking.user_id != user.id:
            raise PermissionDeniedError("That booking belongs to someone else.")
    return _to_out(db, booking)


@router.get("/bookings/reference/{reference}", response_model=BookingOut)
def get_by_reference(
    reference: str,
    email: Annotated[str, Query(description="The contact email on the booking.")],
    db: DbSession,
) -> BookingOut:
    """Look up a booking by its printed reference.

    The reference alone is **not** a credential. It is eight characters from a
    30-character alphabet, it is printed on the ticket, quoted over the phone
    and visible over a shoulder -- and this response carries the customer's
    email and the signed QR payload, which *is* the ticket. Treating the
    reference as a bearer token would hand a working ticket to anyone who
    glanced at one.

    So it is reference **plus** the contact email, the same PNR-plus-surname
    pattern airlines use. The comparison is constant-time, and a mismatch
    returns the same 404 as a non-existent reference so the endpoint cannot be
    used to test whether a reference exists.

    (A booking *id* is a different matter: UUIDv7 leaves 74 random bits, so
    ``GET /bookings/{id}`` is safe to treat as an unguessable link -- which is
    what the guest-checkout flow relies on.)
    """
    booking = BookingService(db).get_by_reference(reference)
    supplied = email.strip().lower().encode()
    actual = (booking.contact_email or "").strip().lower().encode()
    if not hmac.compare_digest(supplied, actual):
        raise NotFoundError("No booking matches that reference and email.")
    return _to_out(db, booking)


@router.get("/bookings/{booking_id}/cancellation-quote", response_model=CancellationQuoteOut)
def cancellation_quote(
    booking_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> CancellationQuoteOut:
    service = BookingService(db)
    booking = service.get_for_user(booking_id, user.id)
    allowed, refund, reason = service.quote_cancellation(booking)
    return CancellationQuoteOut(
        refundable=allowed,
        refund_minor=refund,
        forfeited_minor=booking.total_minor - refund if allowed else 0,
        reason=reason,
    )


@router.post("/bookings/{booking_id}/cancel", response_model=BookingOut)
def cancel_booking(
    booking_id: uuid.UUID,
    payload: CancelBookingRequest,
    db: DbSession,
    user: CurrentUser,
) -> BookingOut:
    from app.modules.payments.service import PaymentService

    service = BookingService(db)
    booking = service.get_for_user(booking_id, user.id)
    booking, refund_minor = service.cancel_booking(
        booking, actor_user_id=user.id, reason=payload.reason
    )
    if refund_minor > 0:
        PaymentService(db).refund_for_cancellation(booking, refund_minor)
    db.commit()
    return _to_out(db, booking)
