"""Operator and platform-admin contracts."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

from app.core.schemas import APIModel


# ------------------------------------------------------------------ venues ---
class CinemaCreate(BaseModel):
    city_id: uuid.UUID
    name: Annotated[str, Field(min_length=2, max_length=200)]
    brand: Annotated[str | None, Field(max_length=120)] = None
    address_line: Annotated[str, Field(min_length=4)]
    locality: Annotated[str | None, Field(max_length=160)] = None
    pincode: Annotated[str | None, Field(max_length=12)] = None
    timezone: Annotated[str, Field(max_length=64)] = "Asia/Kolkata"
    amenities: list[str] = Field(default_factory=list)
    latitude: float | None = None
    longitude: float | None = None

    @field_validator("timezone")
    @classmethod
    def _known_zone(cls, v: str) -> str:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"'{v}' is not a known IANA time zone.") from exc
        return v


class CinemaUpdate(BaseModel):
    name: Annotated[str | None, Field(min_length=2, max_length=200)] = None
    brand: Annotated[str | None, Field(max_length=120)] = None
    address_line: str | None = None
    locality: Annotated[str | None, Field(max_length=160)] = None
    amenities: list[str] | None = None
    is_active: bool | None = None


class SeatCategoryCreate(BaseModel):
    code: Annotated[str, Field(min_length=1, max_length=32)]
    name: Annotated[str, Field(min_length=1, max_length=80)]
    description: str | None = None
    default_price_minor: Annotated[int, Field(ge=0, le=10_000_00)]
    display_order: int = 100
    color_hex: Annotated[str | None, Field(max_length=7)] = None

    @field_validator("code")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()


class SeatCategoryUpdate(BaseModel):
    name: Annotated[str | None, Field(min_length=1, max_length=80)] = None
    description: str | None = None
    default_price_minor: Annotated[int | None, Field(ge=0, le=10_000_00)] = None
    display_order: int | None = None
    color_hex: Annotated[str | None, Field(max_length=7)] = None


class ScreenCreate(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=80)]
    screen_number: Annotated[int, Field(ge=1, le=99)]
    supported_formats: Annotated[list[str], Field(min_length=1)] = ["2D"]
    sound_system: Annotated[str | None, Field(max_length=80)] = None


class ScreenUpdate(BaseModel):
    name: Annotated[str | None, Field(min_length=1, max_length=80)] = None
    supported_formats: list[str] | None = None
    sound_system: Annotated[str | None, Field(max_length=80)] = None
    is_active: bool | None = None


class LayoutRow(BaseModel):
    """One row of seats in a screen."""

    row_label: Annotated[str, Field(min_length=1, max_length=4)]
    seat_count: Annotated[int, Field(ge=1, le=60)]
    category_code: Annotated[str, Field(min_length=1, max_length=32)]
    #: Seat numbers after which a walkway appears. Aisles occupy grid columns
    #: without being seats, which is what lets the map render the gap.
    aisles_after: list[int] = Field(default_factory=list)
    wheelchair_seats: list[int] = Field(default_factory=list)

    @field_validator("row_label")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()


class LayoutCreate(BaseModel):
    """A complete seating plan. Replaces whatever the screen had."""

    rows: Annotated[list[LayoutRow], Field(min_length=1, max_length=40)]
    screen_label: str = "All eyes this way"


class LayoutPreview(APIModel):
    screen_id: uuid.UUID
    total_seats: int
    rows: list[dict]
    by_category: dict[str, int]


# ----------------------------------------------------------------- catalog ---
class MovieCreate(BaseModel):
    title: Annotated[str, Field(min_length=1, max_length=300)]
    synopsis: str = ""
    runtime_minutes: Annotated[int, Field(ge=1, le=600)]
    certification: Annotated[str | None, Field(max_length=16)] = None
    release_date: date | None = None
    status: Literal["coming_soon", "now_showing", "archived"] = "now_showing"
    tagline: Annotated[str | None, Field(max_length=400)] = None
    poster_url: str | None = None
    backdrop_url: str | None = None
    trailer_url: str | None = None
    original_language_code: Annotated[str | None, Field(max_length=8)] = None
    language_codes: list[str] = Field(default_factory=list)
    genre_names: list[str] = Field(default_factory=list)
    cast: list[str] = Field(default_factory=list)
    director: str | None = None
    attributes: dict = Field(default_factory=dict)


class MovieUpdate(BaseModel):
    title: Annotated[str | None, Field(min_length=1, max_length=300)] = None
    synopsis: str | None = None
    runtime_minutes: Annotated[int | None, Field(ge=1, le=600)] = None
    certification: Annotated[str | None, Field(max_length=16)] = None
    release_date: date | None = None
    status: Literal["coming_soon", "now_showing", "archived"] | None = None
    tagline: Annotated[str | None, Field(max_length=400)] = None
    poster_url: str | None = None
    backdrop_url: str | None = None
    trailer_url: str | None = None
    language_codes: list[str] | None = None
    genre_names: list[str] | None = None
    attributes: dict | None = None
    is_active: bool | None = None


# -------------------------------------------------------------- scheduling ---
class ShowPriceInput(BaseModel):
    seat_category_id: uuid.UUID
    price_minor: Annotated[int, Field(ge=0, le=10_000_00)]


class ShowCreate(BaseModel):
    """A showtime.

    The operator supplies a **local wall time** plus a date. The server attaches
    the cinema's zone and converts to an instant -- doing it the other way round
    is what makes every show an hour wrong twice a year.
    """

    screen_id: uuid.UUID
    movie_id: uuid.UUID
    format_code: Annotated[str, Field(min_length=1, max_length=16)] = "2D"
    audio_language_code: Annotated[str, Field(min_length=1, max_length=8)] = "en"
    subtitle_language_code: Annotated[str | None, Field(max_length=8)] = "en"
    show_date: date
    start_time: time
    #: Minutes of trailers and turnaround added after the runtime.
    turnaround_minutes: Annotated[int, Field(ge=0, le=120)] = 20
    prices: Annotated[list[ShowPriceInput], Field(min_length=1)]
    sales_open_at: datetime | None = None


class ShowUpdate(BaseModel):
    status: Literal["scheduled", "open", "closed"] | None = None
    sales_open_at: datetime | None = None


class BulkShowCreate(BaseModel):
    """The same slot repeated across a date range -- how schedules are really made."""

    screen_id: uuid.UUID
    movie_id: uuid.UUID
    format_code: str = "2D"
    audio_language_code: str = "en"
    subtitle_language_code: str | None = "en"
    start_date: date
    end_date: date
    start_times: Annotated[list[time], Field(min_length=1, max_length=8)]
    turnaround_minutes: Annotated[int, Field(ge=0, le=120)] = 20
    prices: Annotated[list[ShowPriceInput], Field(min_length=1)]


class ShowAdminOut(APIModel):
    id: uuid.UUID
    movie_id: uuid.UUID
    movie_title: str
    screen_id: uuid.UUID
    screen_name: str
    cinema_id: uuid.UUID
    format_code: str
    audio_language: str
    starts_at: datetime
    ends_at: datetime
    show_date: date
    status: str
    total_seats: int
    available_seats: int
    booked_seats: int
    occupancy_percent: float
    gross_minor: int
    prices: list[dict]


class BulkShowResult(APIModel):
    created: int
    skipped_conflicts: list[str]
    show_ids: list[uuid.UUID]


class CancelShowRequest(BaseModel):
    reason: Annotated[str, Field(min_length=3, max_length=300)]


class CancelShowResult(APIModel):
    show_id: uuid.UUID
    bookings_revoked: int
    refunds_created: int
    refund_total_minor: int
    seats_released: int


# ----------------------------------------------------------------- reports ---
class RevenueRow(APIModel):
    bucket: str
    bookings: int
    tickets: int
    gross_minor: int
    discount_minor: int
    fees_minor: int
    tax_minor: int
    net_minor: int
    refunded_minor: int


class RevenueReport(APIModel):
    cinema_id: uuid.UUID | None
    cinema_name: str | None
    date_from: date
    date_to: date
    group_by: str
    totals: RevenueRow
    rows: list[RevenueRow]


class OccupancyRow(APIModel):
    show_id: uuid.UUID
    movie_title: str
    screen_name: str
    starts_at: datetime
    total_seats: int
    booked_seats: int
    held_seats: int
    occupancy_percent: float
    gross_minor: int


class OccupancyReport(APIModel):
    cinema_id: uuid.UUID
    cinema_name: str
    date_from: date
    date_to: date
    average_occupancy_percent: float
    total_seats: int
    booked_seats: int
    rows: list[OccupancyRow]


class OperatorBookingOut(APIModel):
    id: uuid.UUID
    booking_reference: str
    status: str
    created_at: datetime
    contact_email: str
    seat_count: int
    seat_labels: list[str]
    total_minor: int
    movie_title: str
    screen_name: str
    starts_at: datetime
    checked_in_seats: int


# ------------------------------------------------------------------- admin ---
class AssignOperatorRequest(BaseModel):
    operator_user_id: uuid.UUID | None


class UserAdminOut(APIModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: datetime
    managed_cinemas: int


class ChangeRoleRequest(BaseModel):
    role: Literal["customer", "cinema_operator", "admin"]
