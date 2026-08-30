"""Offer validation and redemption.

Two distinct jobs, deliberately separated:

* ``evaluate`` -- can this code be used, and what is it worth? Read-only, safe
  to call on every keystroke in the offers box.
* ``redeem``   -- burn one use of it against a booking. Writes, and is protected
  by a unique constraint so a double-submit cannot spend the same offer twice.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.modules.pricing.calculator import DiscountResult, pct
from app.modules.pricing.models import Offer, OfferRedemption
from app.modules.scheduling.models import Show

logger = get_logger(__name__)


class OfferService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_code(self, code: str) -> Offer:
        offer = self.db.execute(
            select(Offer).where(func.upper(Offer.code) == code.strip().upper())
        ).scalar_one_or_none()
        if offer is None:
            raise NotFoundError("That offer code is not valid.", code="OFFER_NOT_FOUND")
        return offer

    def list_active(self) -> list[Offer]:
        now = datetime.now(UTC)
        return list(
            self.db.execute(
                select(Offer)
                .where(Offer.is_active, Offer.valid_from <= now, Offer.valid_until >= now)
                .order_by(Offer.created_at.desc())
            ).scalars()
        )

    # ------------------------------------------------------------------
    def evaluate(
        self,
        *,
        code: str,
        ticket_subtotal_minor: int,
        show: Show,
        user_id: uuid.UUID | None,
        ticket_prices_minor: list[int],
    ) -> DiscountResult:
        """Validate the code and compute its value. Raises with a clear reason."""
        offer = self.get_by_code(code)
        now = datetime.now(UTC)

        if not offer.is_active:
            raise ValidationError("That offer is no longer active.", code="OFFER_INACTIVE")
        if now < offer.valid_from:
            raise ValidationError("That offer is not active yet.", code="OFFER_NOT_STARTED")
        if now > offer.valid_until:
            raise ValidationError("That offer has expired.", code="OFFER_EXPIRED")
        if ticket_subtotal_minor < offer.min_order_minor:
            raise ValidationError(
                f"This offer needs a ticket total of at least "
                f"Rs {offer.min_order_minor / 100:.0f}.",
                code="OFFER_MIN_ORDER",
                details={"min_order_minor": offer.min_order_minor},
            )
        if offer.usage_limit_total is not None and offer.redeemed_count >= offer.usage_limit_total:
            raise ValidationError("That offer has been fully claimed.", code="OFFER_EXHAUSTED")

        if user_id is not None:
            used = self.db.execute(
                select(func.count())
                .select_from(OfferRedemption)
                .where(
                    OfferRedemption.offer_id == offer.id,
                    OfferRedemption.user_id == user_id,
                )
            ).scalar_one()
            if used >= offer.usage_limit_per_user:
                raise ValidationError(
                    "You have already used this offer.", code="OFFER_USER_LIMIT"
                )

        self._check_conditions(offer, show)

        amount = self._compute_discount(offer, ticket_subtotal_minor, ticket_prices_minor)
        if amount <= 0:
            raise ValidationError(
                "That offer does not apply to this booking.", code="OFFER_NO_BENEFIT"
            )
        return DiscountResult(code=offer.code, amount_minor=amount, label=offer.name)

    def _check_conditions(self, offer: Offer, show: Show) -> None:
        cond = offer.conditions or {}

        if city_ids := cond.get("city_ids"):
            if str(show.city_id) not in {str(c) for c in city_ids}:
                raise ValidationError(
                    "That offer is not available in this city.", code="OFFER_CITY"
                )
        if cinema_ids := cond.get("cinema_ids"):
            if str(show.cinema_id) not in {str(c) for c in cinema_ids}:
                raise ValidationError(
                    "That offer is not valid at this cinema.", code="OFFER_CINEMA"
                )
        if movie_ids := cond.get("movie_ids"):
            if str(show.movie_id) not in {str(m) for m in movie_ids}:
                raise ValidationError(
                    "That offer is not valid for this movie.", code="OFFER_MOVIE"
                )
        if formats := cond.get("formats"):
            if show.format is None or show.format.code not in formats:
                raise ValidationError(
                    f"That offer applies only to {', '.join(formats)} shows.",
                    code="OFFER_FORMAT",
                )
        if days := cond.get("days_of_week"):
            # Weekday is evaluated in the *cinema's* local calendar date, which
            # is what show_date stores -- using UTC here would misapply weekday
            # offers to late-night shows.
            if show.show_date.weekday() not in days:
                raise ValidationError(
                    "That offer is not valid on this day.", code="OFFER_DAY"
                )

    @staticmethod
    def _compute_discount(
        offer: Offer, ticket_subtotal_minor: int, ticket_prices_minor: list[int]
    ) -> int:
        match offer.offer_type:
            case "percent":
                raw = pct(ticket_subtotal_minor, Decimal(offer.percent_off or 0))
            case "flat":
                raw = int(offer.flat_off_minor or 0)
            case "buy_n_get_m":
                buy = int(offer.buy_quantity or 0)
                get = int(offer.get_quantity or 0)
                if buy <= 0 or get <= 0 or len(ticket_prices_minor) < buy + get:
                    return 0
                # Free seats are always the cheapest ones in the order -- the
                # customer-friendly reading, and the one every cinema uses.
                group = buy + get
                free_count = (len(ticket_prices_minor) // group) * get
                raw = sum(sorted(ticket_prices_minor)[:free_count])
            case _:
                return 0

        if offer.max_discount_minor is not None:
            raw = min(raw, offer.max_discount_minor)
        return max(min(raw, ticket_subtotal_minor), 0)

    # ------------------------------------------------------------------
    def redeem(
        self,
        *,
        offer_code: str,
        booking_id: uuid.UUID,
        user_id: uuid.UUID | None,
        discount_minor: int,
    ) -> OfferRedemption:
        """Burn one use. Relies on the DB to stop a concurrent double-spend.

        ``uq_offer_redemptions_booking_id`` means a retried request cannot apply
        the same offer twice to one booking, and the counter update is inside
        the caller's transaction so it commits or rolls back with the booking.
        """
        offer = self.get_by_code(offer_code)
        redemption = OfferRedemption(
            offer_id=offer.id,
            booking_id=booking_id,
            user_id=user_id,
            discount_minor=discount_minor,
        )
        self.db.add(redemption)

        # Re-check the global cap while incrementing, under the row lock the
        # UPDATE takes. Checking in `evaluate` alone would be a TOCTOU bug.
        updated = self.db.execute(
            select(Offer)
            .where(Offer.id == offer.id)
            .with_for_update()
        ).scalar_one()
        if (
            updated.usage_limit_total is not None
            and updated.redeemed_count >= updated.usage_limit_total
        ):
            raise ConflictError("That offer was just fully claimed.", code="OFFER_EXHAUSTED")
        updated.redeemed_count += 1

        self.db.flush()
        logger.info(
            "offer_redeemed",
            offer_code=offer.code,
            booking_id=str(booking_id),
            discount_minor=discount_minor,
        )
        return redemption
