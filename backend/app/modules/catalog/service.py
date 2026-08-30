"""Catalog reads: browse, search and movie detail."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import NotFoundError
from app.modules.catalog.models import (
    Genre,
    Language,
    Movie,
    MovieCredit,
    Review,
    movie_genres,
    movie_languages,
)
from app.modules.scheduling.models import Show


class CatalogService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_movies(
        self,
        *,
        status: str | None = None,
        city_id: uuid.UUID | None = None,
        genre_slug: str | None = None,
        language_code: str | None = None,
        search: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[Movie], int]:
        """Browse and search the catalogue.

        Genre and language are filtered with EXISTS subqueries rather than
        joins. That is not a style preference: joining a many-to-many multiplies
        rows, which forces SELECT DISTINCT, and PostgreSQL then rejects
        ``ORDER BY similarity(title, :q)`` because a DISTINCT query may only
        order by expressions in its select list. The result was a 500 on every
        keyword search. Filtering without joining removes the duplicate rows at
        source, so no DISTINCT is needed and the ranking works.
        """
        stmt: Select = select(Movie).where(Movie.is_active)

        if status:
            stmt = stmt.where(Movie.status == status)
        if genre_slug:
            stmt = stmt.where(
                select(Genre.id)
                .join(movie_genres, movie_genres.c.genre_id == Genre.id)
                .where(movie_genres.c.movie_id == Movie.id, Genre.slug == genre_slug)
                .exists()
            )
        if language_code:
            stmt = stmt.where(
                select(Language.id)
                .join(movie_languages, movie_languages.c.language_id == Language.id)
                .where(
                    movie_languages.c.movie_id == Movie.id,
                    Language.code == language_code,
                )
                .exists()
            )
        if city_id:
            # Only movies with an upcoming show in this city. Uses the
            # denormalised shows.city_id, which is exactly why that column
            # exists.
            stmt = stmt.where(
                select(Show.id)
                .where(
                    Show.movie_id == Movie.id,
                    Show.city_id == city_id,
                    Show.status == "open",
                    Show.sales_close_at > func.now(),
                )
                .exists()
            )

        ranking = None
        if search:
            term = search.strip()
            # Trigram similarity gives typo tolerance; ILIKE catches short
            # prefixes that similarity scores too low. Semantic search would be
            # a separate endpoint -- this one stays fast and literal.
            similarity = func.similarity(Movie.title, term)
            stmt = stmt.where(
                or_(Movie.title.ilike(f"%{term}%"), similarity > 0.25)
            )
            ranking = similarity.desc()

        # Count from the *unordered* statement. A count wrapped around an
        # ORDER BY is both wasteful and, with ranking expressions, invalid.
        total = self.db.execute(
            select(func.count()).select_from(stmt.subquery())
        ).scalar_one()

        stmt = stmt.order_by(
            ranking if ranking is not None else Movie.popularity_score.desc(),
            Movie.release_date.desc().nullslast(),
        )
        rows = list(self.db.execute(stmt.offset(offset).limit(limit)).unique().scalars())
        return rows, total

    def get_movie(self, movie_id: uuid.UUID) -> Movie:
        movie = self.db.execute(
            select(Movie)
            .where(Movie.id == movie_id)
            .options(selectinload(Movie.credits).selectinload(MovieCredit.person))
        ).scalar_one_or_none()
        if movie is None:
            raise NotFoundError("That movie does not exist.")
        return movie

    def get_movie_by_slug(self, slug: str) -> Movie:
        movie = self.db.execute(
            select(Movie)
            .where(Movie.slug == slug)
            .options(selectinload(Movie.credits).selectinload(MovieCredit.person))
        ).scalar_one_or_none()
        if movie is None:
            raise NotFoundError("That movie does not exist.")
        return movie

    def list_genres(self) -> list[Genre]:
        return list(self.db.execute(select(Genre).order_by(Genre.name)).scalars())

    def list_languages(self) -> list[Language]:
        return list(self.db.execute(select(Language).order_by(Language.name)).scalars())

    def list_reviews(
        self, movie_id: uuid.UUID, *, offset: int = 0, limit: int = 20
    ) -> tuple[list[Review], int]:
        base = select(Review).where(Review.movie_id == movie_id)
        total = self.db.execute(select(func.count()).select_from(base.subquery())).scalar_one()
        rows = list(
            self.db.execute(
                base.order_by(Review.helpful_count.desc(), Review.created_at.desc())
                .offset(offset)
                .limit(limit)
            ).scalars()
        )
        return rows, total

    def refresh_rating_aggregate(self, movie_id: uuid.UUID) -> None:
        """Recompute the cached rating. Called after a review is written.

        The cache exists so listing pages do not aggregate on every request; the
        `reviews` table stays the source of truth.
        """
        avg, count = self.db.execute(
            select(func.avg(Review.rating), func.count(Review.id)).where(
                Review.movie_id == movie_id
            )
        ).one()
        movie = self.db.get(Movie, movie_id)
        if movie is not None:
            movie.rating_average = round(float(avg), 1) if avg is not None else None
            movie.rating_count = int(count)
            self.db.flush()

    def now_showing_dates(self, movie_id: uuid.UUID, city_id: uuid.UUID) -> list[date]:
        rows = self.db.execute(
            select(Show.show_date)
            .where(
                Show.movie_id == movie_id,
                Show.city_id == city_id,
                Show.status == "open",
                Show.sales_close_at > func.now(),
            )
            .distinct()
            .order_by(Show.show_date)
        ).scalars()
        return list(rows)
