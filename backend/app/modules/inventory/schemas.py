"""Seat map and hold contracts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.core.schemas import APIModel


class SeatOut(APIModel):
    show_seat_id: uuid.UUID
    seat_id: uuid.UUID
    label: str
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


class SeatRowOut(APIModel):
    row_label: str
    row_index: int
    seats: list[SeatOut]


class SeatCategorySummary(APIModel):
    category_id: uuid.UUID
    code: str
    name: str
    price_minor: int
    available: int
    total: int


class SeatMapOut(APIModel):
    show_id: uuid.UUID
    screen_name: str
    cinema_name: str
    movie_title: str
    starts_at: datetime
    rows: list[SeatRowOut]
    categories: list[SeatCategorySummary]
    available_seats: int
    total_seats: int
    max_seats_per_booking: int
    # Presentation hints (aisle positions, screen label) straight from the screen.
    layout_meta: dict


class HoldSeatsRequest(BaseModel):
    show_id: uuid.UUID
    seat_ids: Annotated[list[uuid.UUID], Field(min_length=1, max_length=20)]
    # Identifies an anonymous browser session so a guest can reclaim their own
    # hold after a refresh. Never used for authorisation of anything that costs
    # money -- that always goes through the authenticated user or the booking's
    # own contact details.
    session_key: Annotated[str, Field(min_length=8, max_length=64)]


class HoldOut(APIModel):
    hold_id: uuid.UUID
    show_id: uuid.UUID
    seat_ids: list[uuid.UUID]
    seat_labels: list[str]
    seat_count: int
    expires_at: datetime
    seconds_remaining: int
    subtotal_minor: int
    #: True once the customer explicitly asked to keep these seats, which stops
    #: navigating away from releasing them.
    is_kept: bool = False


class ReleaseHoldRequest(BaseModel):
    session_key: Annotated[str, Field(min_length=8, max_length=64)]
    #: "abandoned" is the browser reporting the customer left checkout; it is
    #: ignored for a hold they explicitly asked to keep. "explicit" always
    #: releases.
    reason: Literal["explicit", "abandoned"] = "explicit"


class KeepHoldRequest(BaseModel):
    session_key: Annotated[str, Field(min_length=8, max_length=64)]
