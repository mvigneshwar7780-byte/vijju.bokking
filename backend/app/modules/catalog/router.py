"""Movie browse, detail and review endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from app.core.deps import CurrentUser, DbSession, Pagination
from app.core.errors import ConflictError
from app.core.schemas import Page
from app.modules.catalog.models import Review
from app.modules.catalog.schemas import (
    CreateReviewRequest,
    CreditOut,
    GenreOut,
    LanguageOut,
    MovieCardOut,
    MovieDetailOut,
    PersonOut,
    ReviewOut,
)
from app.modules.catalog.service import CatalogService

router = APIRouter(tags=["catalog"])


def _detail(movie) -> MovieDetailOut:  # noqa: ANN001
    return MovieDetailOut(
        **MovieCardOut.model_validate(movie).model_dump(),
        synopsis=movie.synopsis,
        backdrop_url=movie.backdrop_url,
        trailer_url=movie.trailer_url,
        popularity_score=float(movie.popularity_score),
        ai_summary=movie.ai_summary,
        ai_attributes=movie.ai_attributes or {},
        credits=[
            CreditOut(
                person=PersonOut.model_validate(c.person),
                credit_type=c.credit_type,
                character_name=c.character_name,
                job=c.job,
            )
            for c in sorted(movie.credits, key=lambda c: (c.credit_type, c.billing_order))
        ],
    )


@router.get("/movies", response_model=Page[MovieCardOut])
def list_movies(
    db: DbSession,
    page: Pagination,
    status_filter: str | None = Query(None, alias="status"),
    city_id: uuid.UUID | None = None,
    genre: str | None = None,
    language: str | None = None,
    q: str | None = Query(None, description="Keyword/fuzzy title search"),
) -> Page[MovieCardOut]:
    movies, total = CatalogService(db).list_movies(
        status=status_filter,
        city_id=city_id,
        genre_slug=genre,
        language_code=language,
        search=q,
        offset=page.offset,
        limit=page.limit,
    )
    return Page[MovieCardOut](
        items=[MovieCardOut.model_validate(m) for m in movies],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.get("/movies/{movie_id}", response_model=MovieDetailOut)
def get_movie(movie_id: uuid.UUID, db: DbSession) -> MovieDetailOut:
    return _detail(CatalogService(db).get_movie(movie_id))


@router.get("/movies/slug/{slug}", response_model=MovieDetailOut)
def get_movie_by_slug(slug: str, db: DbSession) -> MovieDetailOut:
    return _detail(CatalogService(db).get_movie_by_slug(slug))


@router.get("/genres", response_model=list[GenreOut])
def list_genres(db: DbSession) -> list[GenreOut]:
    return [GenreOut.model_validate(g) for g in CatalogService(db).list_genres()]


@router.get("/languages", response_model=list[LanguageOut])
def list_languages(db: DbSession) -> list[LanguageOut]:
    return [LanguageOut.model_validate(x) for x in CatalogService(db).list_languages()]


@router.get("/movies/{movie_id}/reviews", response_model=Page[ReviewOut])
def list_reviews(movie_id: uuid.UUID, db: DbSession, page: Pagination) -> Page[ReviewOut]:
    reviews, total = CatalogService(db).list_reviews(
        movie_id, offset=page.offset, limit=page.limit
    )
    return Page[ReviewOut](
        items=[ReviewOut.model_validate(r) for r in reviews],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.post(
    "/movies/{movie_id}/reviews",
    response_model=ReviewOut,
    status_code=status.HTTP_201_CREATED,
)
def create_review(
    movie_id: uuid.UUID,
    payload: CreateReviewRequest,
    db: DbSession,
    user: CurrentUser,
) -> ReviewOut:
    service = CatalogService(db)
    service.get_movie(movie_id)  # 404 if it does not exist
    if not 1 <= payload.rating <= 10:
        raise ConflictError("Rating must be between 1 and 10.")
    review = Review(
        movie_id=movie_id,
        user_id=user.id,
        rating=payload.rating,
        title=payload.title,
        body=payload.body,
        is_spoiler=payload.is_spoiler,
    )
    db.add(review)
    db.flush()
    service.refresh_rating_aggregate(movie_id)
    db.commit()
    out = ReviewOut.model_validate(review)
    out.author_name = user.full_name
    return out
