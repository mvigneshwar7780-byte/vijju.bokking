"""Booking contracts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, EmailStr, Field

from app.core.enums import BookingStatus
from app.core.schemas import APIModel


class FnbSelection(BaseModel):
    fnb_item_id: uuid.UUID
    quantity: Annotated[int, Field(ge=1, le=20)]


class CreateBookingRequest(BaseModel):
    hold_id: uuid.UUID
    session_key: Annotated[str, Field(min_length=8, max_length=64)]
    contact_email: EmailStr
    contact_phone: Annotated[str | None, Field(max_length=20)] = None
    fnb: list[FnbSelection] = Field(default_factory=list)
    offer_code: Annotated[str | None, Field(max_length=40)] = None


class QuoteRequest(BaseModel):
    """Price a selection without committing to it -- used by the offers box."""

    hold_id: uuid.UUID
    session_key: Annotated[str, Field(min_length=8, max_length=64)]
    fnb: list[FnbSelection] = Field(default_factory=list)
    offer_code: Annotated[str | None, Field(max_length=40)] = None


class PriceLine(APIModel):
    label: str
    amount_minor: int
    kind: str


class PriceQuoteOut(APIModel):
    ticket_subtotal_minor: int
    fnb_subtotal_minor: int
    discount_minor: int
    convenience_fee_minor: int
    tax_minor: int
    total_minor: int
    currency: str
    lines: list[PriceLine]
    offer_code: str | None = None
    offer_label: str | None = None
    offer_error: str | None = None


class BookingSeatOut(APIModel):
    seat_label: str
    seat_category_name: str
    price_minor: int


class BookingFnbOut(APIModel):
    item_name: str
    quantity: int
    unit_price_minor: int
    total_minor: int


class ShowSummaryOut(APIModel):
    show_id: uuid.UUID
    movie_title: str
    movie_poster_url: str | None
    certification: str | None
    cinema_name: str
    screen_name: str
    city_name: str
    format_code: str
    language: str
    starts_at: datetime
    ends_at: datetime


class RefundOut(APIModel):
    """What was returned, why, and whether it has actually landed."""

    id: uuid.UUID
    amount_minor: int
    status: str
    reason: str
    created_at: datetime
    completed_at: datetime | None


class BookingOut(APIModel):
    id: uuid.UUID
    booking_reference: str
    status: BookingStatus
    seat_count: int
    show: ShowSummaryOut
    seats: list[BookingSeatOut]
    fnb_items: list[BookingFnbOut]
    ticket_subtotal_minor: int
    fnb_subtotal_minor: int
    discount_minor: int
    convenience_fee_minor: int
    tax_minor: int
    total_minor: int
    currency: str
    price_breakdown: dict
    offer_code: str | None
    contact_email: str
    contact_phone: str | None
    payment_deadline_at: datetime | None
    confirmed_at: datetime | None
    cancelled_at: datetime | None
    qr_payload: str | None
    created_at: datetime
    refunds: list[RefundOut] = []
    refunded_minor: int = 0
    #: Present for a confirmed booking: what cancelling right now would return.
    cancellation: "CancellationQuoteOut | None" = None


class StartPaymentRequest(BaseModel):
    method: Annotated[str, Field(max_length=40)] = "upi"


class StartPaymentOut(APIModel):
    payment_id: uuid.UUID
    booking_id: uuid.UUID
    gateway: str
    gateway_order_id: str
    checkout_url: str | None
    amount_minor: int
    currency: str
    expires_at: datetime | None


class CancelBookingRequest(BaseModel):
    reason: Annotated[str | None, Field(max_length=300)] = None


class CancellationQuoteOut(APIModel):
    refundable: bool
    refund_minor: int
    forfeited_minor: int
    reason: str
