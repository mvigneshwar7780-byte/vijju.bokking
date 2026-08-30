"""Catalog contracts."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from app.core.schemas import APIModel


class GenreOut(APIModel):
    id: uuid.UUID
    name: str
    slug: str


class LanguageOut(APIModel):
    id: uuid.UUID
    code: str
    name: str
    native_name: str | None


class PersonOut(APIModel):
    id: uuid.UUID
    name: str
    photo_url: str | None


class CreditOut(APIModel):
    person: PersonOut
    credit_type: str
    character_name: str | None
    job: str | None


class MovieCardOut(APIModel):
    """The compact shape used in listings and recommendation rails."""

    id: uuid.UUID
    title: str
    slug: str
    tagline: str | None
    runtime_minutes: int
    certification: str | None
    release_date: date | None
    status: str
    poster_url: str | None
    rating_average: float | None
    rating_count: int
    genres: list[GenreOut]
    languages: list[LanguageOut]


class MovieDetailOut(MovieCardOut):
    synopsis: str
    backdrop_url: str | None
    trailer_url: str | None
    popularity_score: float
    ai_summary: str | None
    ai_attributes: dict
    credits: list[CreditOut]


class ReviewOut(APIModel):
    id: uuid.UUID
    rating: int
    title: str | None
    body: str
    is_spoiler: bool
    helpful_count: int
    ai_aspects: dict
    created_at: datetime
    author_name: str | None = None


class CreateReviewRequest(APIModel):
    rating: int
    title: str | None = None
    body: str = ""
    is_spoiler: bool = False


class ReviewSummaryOut(APIModel):
    movie_id: uuid.UUID
    review_count: int
    rating_average: float | None
    aspect_averages: dict
    summary: str | None
