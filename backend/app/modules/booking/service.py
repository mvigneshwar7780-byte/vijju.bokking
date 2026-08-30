"""Booking orchestration.

This is the only module allowed to compose inventory + pricing + payments. Each
of those knows nothing about the others; the sequencing, the money, and the
compensating actions when something goes wrong all live here.

The one invariant to hold in your head while reading:

    **Money may never be captured for a seat that cannot be delivered.**

Every branch below either upholds that directly, or records a compensating
refund so it is upheld eventually.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.enums import BookingStatus, HoldStatus
from app.core.errors import (
    BookingStateError,
    ConflictError,
    HoldExpiredError,
    IdempotencyConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from app.core.logging import get_logger
from app.core.security import generate_booking_reference, sign_ticket_payload
from app.modules.analytics.models import DomainEvent
from app.modules.booking.models import (
    Booking,
    BookingFnbItem,
    BookingSeat,
    IdempotencyKey,
)
from app.modules.booking.schemas import (
    CreateBookingRequest,
    FnbSelection,
    QuoteRequest,
)
from app.modules.fnb.models import FnbItem
from app.modules.inventory.models import SeatHold, ShowSeat
from app.modules.inventory.service import InventoryService
from decimal import Decimal

from app.modules.pricing.calculator import (
    DiscountResult,
    FnbLine,
    PriceBreakdown,
    TicketLine,
    pct,
    quote,
)
from app.modules.pricing.service import OfferService
from app.modules.scheduling.models import Show
from app.modules.venues.models import Seat, SeatCategory

logger = get_logger(__name__)


class BookingService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.inventory = InventoryService(db)
        self.offers = OfferService(db)

    # ==================================================================
    # Quoting
    # ==================================================================
    def quote_hold(self, payload: QuoteRequest, *, user_id: uuid.UUID | None) -> tuple[PriceBreakdown, DiscountResult | None, str | None]:
        """Price a held selection. Never mutates anything.

        An invalid offer code is *not* an error here -- it comes back as
        ``offer_error`` alongside the undiscounted price, so the checkout page
        can show both the message and the real total without a failed request.
        """
        hold = self._load_live_hold(payload.hold_id, payload.session_key)
        show = self._load_show(hold.show_id)
        tickets = self._ticket_lines(hold.id)
        fnb_lines = self._fnb_lines(show, payload.fnb)

        discount: DiscountResult | None = None
        offer_error: str | None = None
        if payload.offer_code:
            try:
                discount = self.offers.evaluate(
                    code=payload.offer_code,
                    ticket_subtotal_minor=sum(t.price_minor for t in tickets),
                    show=show,
                    user_id=user_id,
                    ticket_prices_minor=[t.price_minor for t in tickets],
                )
            except (ValidationError, NotFoundError) as exc:
                offer_error = exc.message

        return quote(tickets=tickets, fnb=fnb_lines, discount=discount), discount, offer_error

    # ==================================================================
    # Creation
    # ==================================================================
    def create_booking(
        self,
        payload: CreateBookingRequest,
        *,
        user_id: uuid.UUID | None,
        idempotency_key: str | None = None,
    ) -> Booking:
        """Turn a live hold into a draft booking with a fixed, final price.

        The price is computed here, server-side, from the held seats -- never
        from anything the client sent. The client cannot choose its own total.
        """
        if idempotency_key:
            if replay := self._replay_booking(idempotency_key, payload):
                return replay

        hold = self._load_live_hold(payload.hold_id, payload.session_key)
        if hold.status != HoldStatus.ACTIVE:
            raise HoldExpiredError("That seat hold is no longer active.")

        existing = self.db.execute(
            select(Booking).where(Booking.hold_id == hold.id)
        ).scalar_one_or_none()
        if existing is not None:
            # A second POST for the same hold without an idempotency key. The
            # honest answer is the booking that already exists, not a duplicate.
            return existing

        show = self._load_show(hold.show_id)
        self.inventory._assert_bookable(show)

        tickets = self._ticket_lines(hold.id)
        if len(tickets) != hold.seat_count:
            raise HoldExpiredError(
                "Some of your held seats were released. Please select seats again."
            )

        fnb_lines = self._fnb_lines(show, payload.fnb)
        discount: DiscountResult | None = None
        if payload.offer_code:
            discount = self.offers.evaluate(
                code=payload.offer_code,
                ticket_subtotal_minor=sum(t.price_minor for t in tickets),
                show=show,
                user_id=user_id,
                ticket_prices_minor=[t.price_minor for t in tickets],
            )

        breakdown = quote(tickets=tickets, fnb=fnb_lines, discount=discount)

        booking = Booking(
            booking_reference=self._unique_reference(),
            user_id=user_id,
            show_id=show.id,
            hold_id=hold.id,
            status=BookingStatus.DRAFT,
            seat_count=len(tickets),
            ticket_subtotal_minor=breakdown.ticket_subtotal_minor,
            fnb_subtotal_minor=breakdown.fnb_subtotal_minor,
            discount_minor=breakdown.discount_minor,
            convenience_fee_minor=breakdown.convenience_fee_minor,
            tax_minor=breakdown.tax_minor,
            total_minor=breakdown.total_minor,
            currency=breakdown.currency,
            price_breakdown=breakdown.as_dict(),
            offer_code=discount.code if discount else None,
            contact_email=str(payload.contact_email).lower(),
            contact_phone=payload.contact_phone,
            payment_deadline_at=hold.expires_at,
        )
        self.db.add(booking)
        self.db.flush()

        self._attach_seats(booking, hold.id)
        self._attach_fnb(booking, show, payload.fnb)

        if discount:
            redemption = self.offers.redeem(
                offer_code=discount.code or "",
                booking_id=booking.id,
                user_id=user_id,
                discount_minor=discount.amount_minor,
            )
            booking.offer_id = redemption.offer_id

        self._record_event(booking, "booking.created", {"seat_count": booking.seat_count})
        self.db.flush()

        if idempotency_key:
            self._store_idempotency(idempotency_key, payload, booking)

        logger.info(
            "booking_created",
            booking_id=str(booking.id),
            reference=booking.booking_reference,
            total_minor=booking.total_minor,
        )
        return booking

    # ==================================================================
    # Confirmation / failure
    # ==================================================================
    def confirm_booking(self, booking: Booking) -> Booking:
        """Flip held seats to booked and issue the ticket.

        Raises ``HoldExpiredError`` if the hold lapsed. The caller (the payment
        webhook handler) turns that into a refund -- it must never swallow it.
        """
        if booking.status == BookingStatus.CONFIRMED:
            return booking  # idempotent: a replayed webhook changes nothing
        if booking.status not in (BookingStatus.DRAFT, BookingStatus.PAYMENT_PENDING):
            raise BookingStateError(
                f"Cannot confirm a booking in state '{booking.status.value}'."
            )
        if booking.hold_id is None:
            raise BookingStateError("Booking has no seat hold to confirm.")

        self.inventory.confirm_hold(
            hold_id=booking.hold_id,
            booking_id=booking.id,
            expected_seats=booking.seat_count,
        )

        booking.status = BookingStatus.CONFIRMED
        booking.confirmed_at = datetime.now(UTC)
        booking.qr_payload = sign_ticket_payload(booking.booking_reference, booking.id)
        self.db.flush()

        self.inventory.repo.refresh_available_count(booking.show_id)
        self._record_event(booking, "booking.confirmed", {"total_minor": booking.total_minor})
        self._queue_confirmation_notification(booking)

        logger.info(
            "booking_confirmed",
            booking_id=str(booking.id),
            reference=booking.booking_reference,
        )
        return booking

    def mark_payment_failed(self, booking: Booking, *, reason: str | None = None) -> Booking:
        if booking.status == BookingStatus.CONFIRMED:
            # A late failure event for an already-confirmed booking is noise.
            logger.warning("late_failure_for_confirmed_booking", booking_id=str(booking.id))
            return booking
        booking.status = BookingStatus.PAYMENT_FAILED
        booking.cancellation_reason = reason
        self._deactivate_seats(booking)
        if booking.hold_id:
            # Give the seats back immediately rather than making the next
            # customer wait out the remaining TTL.
            self.inventory.repo.release_hold_seats(booking.hold_id)
            hold = self.db.get(SeatHold, booking.hold_id)
            if hold and hold.status == HoldStatus.ACTIVE:
                hold.status = HoldStatus.RELEASED
                hold.released_at = datetime.now(UTC)
            self.inventory.repo.refresh_available_count(booking.show_id)
        self._record_event(booking, "booking.payment_failed", {"reason": reason})
        self.db.flush()
        return booking

    def expire_booking(self, booking: Booking) -> Booking:
        """The hold lapsed before payment settled."""
        if booking.status in (BookingStatus.CONFIRMED, BookingStatus.EXPIRED):
            return booking
        booking.status = BookingStatus.EXPIRED
        booking.cancellation_reason = "Seat hold expired before payment completed."
        self._deactivate_seats(booking)
        self._record_event(booking, "booking.expired", {})
        self.db.flush()
        return booking

    # ==================================================================
    # Cancellation
    # ==================================================================
    def quote_cancellation(self, booking: Booking) -> tuple[bool, int, str]:
        """How much comes back if this is cancelled right now.

        Tiered on time-to-showtime, because that is what the refund is really
        about: the further out you cancel, the more likely the seat resells.

        =========================  ==========================================
        More than 24h before       full ticket value (and food) returned
        4h to 24h before           a percentage of it returned
        Inside the 2h cutoff       cannot be cancelled -- the seat will not resell
        =========================  ==========================================

        The convenience fee and the tax on that fee are never returned on a
        voluntary cancellation. That is the standard policy, and it is reported
        in the message so the customer sees it *before* confirming rather than
        discovering it on their statement. A show cancelled by the operator is
        a different case entirely and refunds everything.
        """
        if booking.status != BookingStatus.CONFIRMED:
            return False, 0, "Only confirmed bookings can be cancelled."

        show = self._load_show(booking.show_id)
        now = datetime.now(UTC)
        minutes_to_show = (show.starts_at - now).total_seconds() / 60

        if minutes_to_show <= settings.cancellation_cutoff_minutes:
            return (
                False,
                0,
                f"Cancellation closes {settings.cancellation_cutoff_minutes} minutes "
                "before showtime.",
            )

        # What the customer paid for the goods, before fees.
        goods = (
            booking.ticket_subtotal_minor
            + booking.fnb_subtotal_minor
            - booking.discount_minor
        )
        # GST on the goods comes back; GST on the fee does not, because the fee
        # does not.
        fee_tax = pct(booking.convenience_fee_minor, settings.gst_percent_high)
        goods_tax = max(booking.tax_minor - fee_tax, 0)

        if minutes_to_show >= settings.cancellation_full_refund_minutes:
            share = Decimal("100")
            band = "more than 24 hours before showtime"
        else:
            share = Decimal(settings.cancellation_partial_refund_percent)
            band = "less than 24 hours before showtime"

        refundable = pct(goods + goods_tax, share)
        forfeited = booking.total_minor - refundable
        # `Decimal.normalize()` renders 100 as "1E+2" -- fine for a ledger,
        # unreadable in a sentence a customer sees. The 'f' presentation type
        # forces plain notation, and stripping the trailing zeros keeps "50"
        # from becoming "50.00".
        share_label = f"{share.quantize(Decimal('0.01')):f}".rstrip("0").rstrip(".")
        return (
            True,
            refundable,
            f"Cancelling {band}: {share_label}% of the ticket value is "
            f"refunded. Rs {forfeited / 100:.2f} is retained, including the "
            f"non-refundable convenience fee.",
        )

    def cancel_booking(
        self, booking: Booking, *, actor_user_id: uuid.UUID | None, reason: str | None
    ) -> tuple[Booking, int]:
        allowed, refund_minor, message = self.quote_cancellation(booking)
        if not allowed:
            raise ConflictError(message, code="CANCELLATION_NOT_ALLOWED")

        released = self.inventory.release_booking(booking.id, booking.show_id)
        self._deactivate_seats(booking)
        booking.status = BookingStatus.CANCELLED
        booking.cancelled_at = datetime.now(UTC)
        booking.cancellation_reason = reason or "Cancelled by customer."
        self.db.flush()

        self._record_event(
            booking,
            "booking.cancelled",
            {"refund_minor": refund_minor, "seats_released": released},
            actor_user_id=actor_user_id,
        )
        logger.info(
            "booking_cancelled",
            booking_id=str(booking.id),
            refund_minor=refund_minor,
            seats_released=released,
        )
        return booking, refund_minor

    # ==================================================================
    # Reads
    # ==================================================================
    def get(self, booking_id: uuid.UUID) -> Booking:
        booking = self.db.execute(
            select(Booking)
            .where(Booking.id == booking_id)
            .options(selectinload(Booking.seats), selectinload(Booking.fnb_items))
        ).scalar_one_or_none()
        if booking is None:
            raise NotFoundError("That booking does not exist.")
        return booking

    def get_for_user(self, booking_id: uuid.UUID, user_id: uuid.UUID) -> Booking:
        booking = self.get(booking_id)
        if booking.user_id != user_id:
            raise PermissionDeniedError("That booking belongs to someone else.")
        return booking

    def get_by_reference(self, reference: str) -> Booking:
        booking = self.db.execute(
            select(Booking).where(Booking.booking_reference == reference.strip().upper())
        ).scalar_one_or_none()
        if booking is None:
            raise NotFoundError("No booking with that reference.")
        return booking

    def list_for_user(
        self, user_id: uuid.UUID, *, offset: int, limit: int
    ) -> tuple[list[Booking], int]:
        from sqlalchemy import func

        base = select(Booking).where(Booking.user_id == user_id)
        total = self.db.execute(
            select(func.count()).select_from(base.subquery())
        ).scalar_one()
        rows = list(
            self.db.execute(
                base.order_by(Booking.created_at.desc())
                .offset(offset)
                .limit(limit)
                .options(selectinload(Booking.seats), selectinload(Booking.fnb_items))
            ).scalars()
        )
        return rows, total

    # ==================================================================
    # Internals
    # ==================================================================
    def _load_live_hold(self, hold_id: uuid.UUID, session_key: str) -> SeatHold:
        hold = self.db.get(SeatHold, hold_id)
        if hold is None:
            raise NotFoundError("That seat hold does not exist.")
        if hold.session_key != session_key:
            raise PermissionDeniedError("That seat hold belongs to another session.")
        if hold.status == HoldStatus.CONVERTED:
            return hold
        if not hold.is_live:
            raise HoldExpiredError()
        return hold

    def _load_show(self, show_id: uuid.UUID) -> Show:
        show = self.db.get(Show, show_id)
        if show is None:
            raise NotFoundError("That show does not exist.")
        return show

    def _ticket_lines(self, hold_id: uuid.UUID) -> list[TicketLine]:
        """Prices come from the held ``show_seats`` rows, not from the client."""
        rows = self.db.execute(
            select(ShowSeat, Seat, SeatCategory)
            .join(Seat, Seat.id == ShowSeat.seat_id)
            .join(SeatCategory, SeatCategory.id == ShowSeat.seat_category_id)
            .where(ShowSeat.hold_id == hold_id)
            .order_by(Seat.row_index, Seat.seat_number)
        ).all()
        return [
            TicketLine(
                seat_label=f"{seat.row_label}{seat.seat_number}",
                category_name=category.name,
                price_minor=show_seat.price_minor,
            )
            for show_seat, seat, category in rows
        ]

    def _fnb_lines(self, show: Show, selections: list[FnbSelection]) -> list[FnbLine]:
        if not selections:
            return []
        items = {
            item.id: item
            for item in self.db.execute(
                select(FnbItem).where(
                    FnbItem.id.in_([s.fnb_item_id for s in selections]),
                    FnbItem.cinema_id == show.cinema_id,
                    FnbItem.is_available,
                )
            ).scalars()
        }
        lines: list[FnbLine] = []
        for sel in selections:
            item = items.get(sel.fnb_item_id)
            if item is None:
                raise ValidationError(
                    "One of the selected food items is not available at this cinema.",
                    code="FNB_UNAVAILABLE",
                    details={"fnb_item_id": str(sel.fnb_item_id)},
                )
            lines.append(
                FnbLine(
                    item_name=item.name,
                    quantity=sel.quantity,
                    unit_price_minor=item.price_minor,
                )
            )
        return lines

    def _attach_seats(self, booking: Booking, hold_id: uuid.UUID) -> None:
        rows = self.db.execute(
            select(ShowSeat, Seat, SeatCategory)
            .join(Seat, Seat.id == ShowSeat.seat_id)
            .join(SeatCategory, SeatCategory.id == ShowSeat.seat_category_id)
            .where(ShowSeat.hold_id == hold_id)
            .order_by(Seat.row_index, Seat.seat_number)
        ).all()
        for show_seat, seat, category in rows:
            self.db.add(
                BookingSeat(
                    booking_id=booking.id,
                    show_seat_id=show_seat.id,
                    seat_id=seat.id,
                    seat_label=f"{seat.row_label}{seat.seat_number}",
                    seat_category_name=category.name,
                    price_minor=show_seat.price_minor,
                )
            )
        self.db.flush()

    def _attach_fnb(
        self, booking: Booking, show: Show, selections: list[FnbSelection]
    ) -> None:
        if not selections:
            return
        items = {
            item.id: item
            for item in self.db.execute(
                select(FnbItem).where(FnbItem.id.in_([s.fnb_item_id for s in selections]))
            ).scalars()
        }
        for sel in selections:
            item = items[sel.fnb_item_id]
            self.db.add(
                BookingFnbItem(
                    booking_id=booking.id,
                    fnb_item_id=item.id,
                    item_name=item.name,
                    quantity=sel.quantity,
                    unit_price_minor=item.price_minor,
                    total_minor=item.price_minor * sel.quantity,
                )
            )
        self.db.flush()

    def _unique_reference(self) -> str:
        for _ in range(10):
            ref = generate_booking_reference()
            exists = self.db.execute(
                select(Booking.id).where(Booking.booking_reference == ref)
            ).first()
            if exists is None:
                return ref
        raise ConflictError("Could not allocate a booking reference. Try again.")

    def _deactivate_seats(self, booking: Booking) -> int:
        """Retire a dead booking's tickets so the seats can be resold.

        Called on every terminal transition. The rows stay -- they are the
        financial record of what was sold -- but ``is_active = false`` releases
        them from the partial unique index, which is what lets the next customer
        buy the same seat.
        """
        from sqlalchemy import update

        result = self.db.execute(
            update(BookingSeat)
            .where(BookingSeat.booking_id == booking.id, BookingSeat.is_active.is_(True))
            .values(is_active=False)
        )
        self.db.flush()
        return int(result.rowcount or 0)

    def _record_event(
        self,
        booking: Booking,
        event_type: str,
        payload: dict,
        *,
        actor_user_id: uuid.UUID | None = None,
    ) -> None:
        from app.core.logging import request_id_ctx

        self.db.add(
            DomainEvent(
                aggregate_type="booking",
                aggregate_id=booking.id,
                event_type=event_type,
                actor_user_id=actor_user_id or booking.user_id,
                request_id=request_id_ctx.get(),
                payload={"reference": booking.booking_reference, **payload},
            )
        )

    def _queue_confirmation_notification(self, booking: Booking) -> None:
        from app.core.enums import NotificationChannel
        from app.modules.notifications.models import Notification

        self.db.add(
            Notification(
                user_id=booking.user_id,
                booking_id=booking.id,
                channel=NotificationChannel.EMAIL,
                template="booking_confirmed",
                recipient=booking.contact_email,
                subject=f"Your tickets are confirmed - {booking.booking_reference}",
                payload={
                    "reference": booking.booking_reference,
                    "seat_count": booking.seat_count,
                    "total_minor": booking.total_minor,
                },
            )
        )

    # ---------------------------------------------------------------
    # Idempotency
    # ---------------------------------------------------------------
    @staticmethod
    def _hash_payload(payload: CreateBookingRequest) -> str:
        body = payload.model_dump(mode="json")
        return hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def _replay_booking(
        self, key: str, payload: CreateBookingRequest
    ) -> Booking | None:
        record = self.db.execute(
            select(IdempotencyKey).where(
                IdempotencyKey.scope == "create_booking", IdempotencyKey.key == key
            )
        ).scalar_one_or_none()
        if record is None:
            return None
        if record.request_hash != self._hash_payload(payload):
            raise IdempotencyConflictError(
                "This Idempotency-Key was already used with a different request body."
            )
        if record.booking_id is None:
            raise ConflictError(
                "A booking with this Idempotency-Key is still being processed.",
                code="IDEMPOTENCY_IN_PROGRESS",
            )
        logger.info("booking_idempotent_replay", key=key, booking_id=str(record.booking_id))
        return self.get(record.booking_id)

    def _store_idempotency(
        self, key: str, payload: CreateBookingRequest, booking: Booking
    ) -> None:
        self.db.add(
            IdempotencyKey(
                key=key,
                scope="create_booking",
                user_id=booking.user_id,
                request_hash=self._hash_payload(payload),
                booking_id=booking.id,
                response_status=201,
                completed_at=datetime.now(UTC),
            )
        )
        self.db.flush()
