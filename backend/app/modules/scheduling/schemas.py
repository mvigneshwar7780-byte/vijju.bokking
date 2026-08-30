"""Showtime contracts."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from app.core.schemas import APIModel


class FormatOut(APIModel):
    id: uuid.UUID
    code: str
    name: str
    surcharge_minor: int


class ShowCardOut(APIModel):
    id: uuid.UUID
    starts_at: datetime
    ends_at: datetime
    show_date: date
    format_code: str
    format_name: str
    audio_language: str
    subtitle_language: str | None
    screen_name: str
    status: str
    available_seats: int
    total_seats: int
    min_price_minor: int
    # "filling_fast" / "almost_full" / "available" -- the badge BookMyShow shows.
    availability_band: str
    is_bookable: bool


class CinemaShowsOut(APIModel):
    cinema_id: uuid.UUID
    cinema_name: str
    brand: str | None
    locality: str | None
    amenities: list
    distance_km: float | None = None
    shows: list[ShowCardOut]


class ShowtimeBoardOut(APIModel):
    """Everything the 'pick a showtime' screen needs, in one response."""

    movie_id: uuid.UUID
    movie_title: str
    city_id: uuid.UUID
    city_name: str
    show_date: date
    available_dates: list[date]
    cinemas: list[CinemaShowsOut]


class ShowDetailOut(APIModel):
    id: uuid.UUID
    movie_id: uuid.UUID
    movie_title: str
    movie_poster_url: str | None
    certification: str | None
    runtime_minutes: int
    cinema_id: uuid.UUID
    cinema_name: str
    screen_name: str
    city_name: str
    format_code: str
    audio_language: str
    subtitle_language: str | None
    starts_at: datetime
    ends_at: datetime
    status: str
    is_bookable: bool
    sales_close_at: datetime
    available_seats: int
    total_seats: int


class CinemaMovieOut(APIModel):
    """A film playing at one cinema, with that cinema's own price range."""

    movie_id: uuid.UUID
    title: str
    slug: str
    poster_url: str | None
    certification: str | None
    runtime_minutes: int
    rating_average: float | None
    genres: list[str]
    languages: list[str]
    formats: list[str]
    show_count: int
    next_show_at: datetime | None
    min_price_minor: int
    max_price_minor: int
    available_dates: list[date]


class CinemaMoviesOut(APIModel):
    cinema_id: uuid.UUID
    cinema_name: str
    brand: str | None
    locality: str | None
    city_name: str
    amenities: list
    show_date: date | None
    movies: list[CinemaMovieOut]


class CinemaPriceOut(APIModel):
    """One cinema's offer for a given film -- the row in a price comparison."""

    cinema_id: uuid.UUID
    cinema_name: str
    brand: str | None
    locality: str | None
    amenities: list
    distance_km: float | None
    show_count: int
    earliest_show_at: datetime
    latest_show_at: datetime
    min_price_minor: int
    max_price_minor: int
    formats: list[str]
    languages: list[str]
    total_available_seats: int


class MoviePriceComparisonOut(APIModel):
    """The same film across every hall showing it, cheapest first."""

    movie_id: uuid.UUID
    movie_title: str
    poster_url: str | None
    city_id: uuid.UUID
    city_name: str
    show_date: date
    available_dates: list[date]
    cheapest_minor: int | None
    dearest_minor: int | None
    cinemas: list[CinemaPriceOut]
