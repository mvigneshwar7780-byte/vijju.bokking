"""The price calculator.

Deliberately a **pure function** over plain data: no database, no session, no
clock. That makes every pricing rule unit-testable without fixtures, and means
the same code can quote a price for the UI, for the booking, and for the AI
assistant with zero risk of the three disagreeing.

Money rules
-----------
* Everything is an ``int`` of minor units (paise). No floats anywhere.
* Percentages are ``Decimal`` and every conversion back to paise rounds
  ROUND_HALF_UP exactly once, at the point of conversion. Rounding twice is how
  invoices end up one paisa out.
* The order of operations is fixed and documented below, because "20% off" means
  something different before and after a convenience fee.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from app.core.config import settings


def pct(amount_minor: int, percent: str | Decimal) -> int:
    """`percent` of `amount_minor`, rounded half-up to whole paise."""
    value = Decimal(amount_minor) * Decimal(str(percent)) / Decimal(100)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@dataclass(frozen=True, slots=True)
class TicketLine:
    seat_label: str
    category_name: str
    price_minor: int


@dataclass(frozen=True, slots=True)
class FnbLine:
    item_name: str
    quantity: int
    unit_price_minor: int

    @property
    def total_minor(self) -> int:
        return self.unit_price_minor * self.quantity


@dataclass(frozen=True, slots=True)
class DiscountResult:
    code: str | None
    amount_minor: int
    label: str | None = None


@dataclass(frozen=True, slots=True)
class PriceBreakdown:
    ticket_subtotal_minor: int
    fnb_subtotal_minor: int
    discount_minor: int
    convenience_fee_minor: int
    tax_minor: int
    total_minor: int
    currency: str
    lines: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "ticket_subtotal_minor": self.ticket_subtotal_minor,
            "fnb_subtotal_minor": self.fnb_subtotal_minor,
            "discount_minor": self.discount_minor,
            "convenience_fee_minor": self.convenience_fee_minor,
            "tax_minor": self.tax_minor,
            "total_minor": self.total_minor,
            "currency": self.currency,
            "lines": self.lines,
        }


def quote(
    *,
    tickets: list[TicketLine],
    fnb: list[FnbLine] | None = None,
    discount: DiscountResult | None = None,
) -> PriceBreakdown:
    """Compose the final amount payable.

    Order of application -- this is the part that matters:

    1. ``ticket_subtotal``  = sum of seat prices (each already includes the
       show's format surcharge, baked in at materialisation).
    2. ``fnb_subtotal``     = sum of food line totals.
    3. ``discount``         applies to the **ticket subtotal only**. Discounting
       food as well is a different product decision; making it explicit here
       stops it happening by accident.
    4. ``convenience_fee``  = a percentage of the *post-discount* ticket amount,
       capped. Charging the fee on the pre-discount amount would mean a coupon
       silently increases the fee's share -- customers notice.
    5. ``tax``              = GST on tickets at the slab rate (12% at or below
       Rs 100 per ticket, 18% above -- India's actual split), plus 18% GST on
       the convenience fee, plus 5% on food.
    6. ``total``            = tickets + food - discount + fee + tax.

    The database enforces step 6 with a CHECK constraint, so a future edit that
    breaks the arithmetic fails the insert instead of mischarging someone.
    """
    fnb = fnb or []
    ticket_subtotal = sum(t.price_minor for t in tickets)
    fnb_subtotal = sum(f.total_minor for f in fnb)

    discount_minor = min(discount.amount_minor, ticket_subtotal) if discount else 0
    net_tickets = ticket_subtotal - discount_minor

    convenience_fee = pct(net_tickets, settings.convenience_fee_percent)
    convenience_fee = min(convenience_fee, settings.convenience_fee_cap_minor)

    # GST on tickets is per-ticket-price banded, not on the order total, so a
    # single expensive recliner is taxed at 18% even in an otherwise cheap
    # order. Discount is apportioned across tickets to keep the band honest.
    ticket_tax = 0
    if ticket_subtotal > 0:
        for t in tickets:
            share = (
                pct(discount_minor, Decimal(t.price_minor * 100) / Decimal(ticket_subtotal))
                if discount_minor
                else 0
            )
            taxable = max(t.price_minor - share, 0)
            band = (
                settings.gst_percent_high
                if t.price_minor > settings.gst_threshold_minor
                else settings.gst_percent_low
            )
            ticket_tax += pct(taxable, band)

    fee_tax = pct(convenience_fee, "18.00")
    fnb_tax = pct(fnb_subtotal, "5.00")
    tax_minor = ticket_tax + fee_tax + fnb_tax

    total = ticket_subtotal + fnb_subtotal - discount_minor + convenience_fee + tax_minor

    lines: list[dict] = [
        {"label": f"Tickets x{len(tickets)}", "amount_minor": ticket_subtotal, "kind": "tickets"},
    ]
    if fnb_subtotal:
        lines.append({"label": "Food & beverages", "amount_minor": fnb_subtotal, "kind": "fnb"})
    if discount_minor:
        lines.append(
            {
                "label": discount.label or f"Offer {discount.code}" if discount else "Discount",
                "amount_minor": -discount_minor,
                "kind": "discount",
            }
        )
    lines.append(
        {"label": "Convenience fee", "amount_minor": convenience_fee, "kind": "fee"}
    )
    lines.append({"label": "GST", "amount_minor": tax_minor, "kind": "tax"})

    return PriceBreakdown(
        ticket_subtotal_minor=ticket_subtotal,
        fnb_subtotal_minor=fnb_subtotal,
        discount_minor=discount_minor,
        convenience_fee_minor=convenience_fee,
        tax_minor=tax_minor,
        total_minor=total,
        currency=settings.currency,
        lines=lines,
    )
