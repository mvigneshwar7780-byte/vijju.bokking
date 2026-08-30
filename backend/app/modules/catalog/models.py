"""Catalog: movies and everything that describes them.

Read-heavy and write-rare: a movie's descriptive text changes maybe once, then
is queried forever. That profile is why the ``ai_*`` JSONB columns below are
left as extension points -- generated summaries, extracted attributes and
per-review aspect scores can be written here later without a migration.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Table,
    Text,
    UniqueConstraint,
    Column,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:  # pragma: no cover
    from app.modules.scheduling.models import Show


# Pure join tables: no payload of their own, so they stay Core tables rather
# than mapped classes. Anything that later needs a column (e.g. "is primary
# language") gets promoted to a real model.
movie_genres = Table(
    "movie_genres",
    Base.metadata,
    Column("movie_id", ForeignKey("movies.id", ondelete="CASCADE"), primary_key=True),
    Column("genre_id", ForeignKey("genres.id", ondelete="CASCADE"), primary_key=True),
)

movie_languages = Table(
    "movie_languages",
    Base.metadata,
    Column("movie_id", ForeignKey("movies.id", ondelete="CASCADE"), primary_key=True),
    Column("language_id", ForeignKey("languages.id", ondelete="CASCADE"), primary_key=True),
)


class Genre(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "genres"

    name: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)

    movies: Mapped[list["Movie"]] = relationship(
        secondary=movie_genres, back_populates="genres"
    )


class Language(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "languages"

    code: Mapped[str] = mapped_column(String(8), nullable=False, unique=True)  # hi, ta, en
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    native_name: Mapped[str | None] = mapped_column(String(60))

    movies: Mapped[list["Movie"]] = relationship(
        secondary=movie_languages, back_populates="languages"
    )


class Person(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Cast and crew share one table -- the *role* lives on the credit."""

    __tablename__ = "people"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(180), nullable=False, unique=True)
    photo_url: Mapped[str | None] = mapped_column(Text)
    bio: Mapped[str | None] = mapped_column(Text)

    credits: Mapped[list["MovieCredit"]] = relationship(back_populates="person")

    __table_args__ = (
        Index(
            "ix_people_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )


class Movie(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "movies"

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    original_title: Mapped[str | None] = mapped_column(String(300))
    slug: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    tagline: Mapped[str | None] = mapped_column(String(400))
    synopsis: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    runtime_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    # UA13+, A, U ... a plain string: certification bodies differ by country and
    # this is display data, not logic.
    certification: Mapped[str | None] = mapped_column(String(16))
    release_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(
        Enum(
            "coming_soon",
            "now_showing",
            "archived",
            name="movie_status",
            native_enum=True,
        ),
        nullable=False,
        server_default="coming_soon",
    )
    original_language_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("languages.id", ondelete="SET NULL")
    )
    poster_url: Mapped[str | None] = mapped_column(Text)
    backdrop_url: Mapped[str | None] = mapped_column(Text)
    trailer_url: Mapped[str | None] = mapped_column(Text)

    # Cached aggregates. Recomputed by a job, never trusted as the source of
    # truth -- `reviews` is. Denormalised because every listing page needs them
    # and a live AVG() over reviews on each card is wasteful.
    rating_average: Mapped[float | None] = mapped_column(Numeric(3, 1))
    rating_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    popularity_score: Mapped[float] = mapped_column(
        Numeric(8, 3), nullable=False, server_default="0"
    )

    # Reserved for a generated review summary. Nullable -- it may never exist.
    ai_summary: Mapped[str | None] = mapped_column(Text)
    ai_summary_generated_at: Mapped[date | None] = mapped_column(Date)
    # Curated descriptive facets: mood, pace, themes, content warnings. Used by
    # the catalogue filters today; JSONB so new facets need no migration.
    ai_attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    # Who added this title. Movies are a *shared* catalogue -- the same film
    # plays at many cinemas, and giving each operator their own copy would
    # fragment it and break "show me every hall playing this film". So a movie
    # is not owned by a cinema; this column only records provenance, so an
    # operator may edit what they contributed while an administrator may edit
    # anything.
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    genres: Mapped[list[Genre]] = relationship(
        secondary=movie_genres, back_populates="movies", lazy="selectin"
    )
    languages: Mapped[list[Language]] = relationship(
        secondary=movie_languages, back_populates="movies", lazy="selectin"
    )
    credits: Mapped[list["MovieCredit"]] = relationship(
        back_populates="movie", cascade="all, delete-orphan"
    )
    reviews: Mapped[list["Review"]] = relationship(
        back_populates="movie", cascade="all, delete-orphan"
    )
    shows: Mapped[list["Show"]] = relationship(back_populates="movie")

    __table_args__ = (
        Index("ix_movies_status_release_date", "status", "release_date"),
        Index("ix_movies_created_by_user_id", "created_by_user_id"),
        Index("ix_movies_popularity_score", "popularity_score"),
        # Trigram index powers fuzzy keyword search ("intersteller" -> Interstellar).
        # The *semantic* search path uses pgvector instead; the two complement
        # each other and are blended at query time.
        Index(
            "ix_movies_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
        CheckConstraint("runtime_minutes > 0", name="runtime_positive"),
        CheckConstraint(
            "rating_average is null or (rating_average >= 0 and rating_average <= 10)",
            name="rating_average_range",
        ),
    )


class MovieCredit(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "movie_credits"

    movie_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("movies.id", ondelete="CASCADE"), nullable=False
    )
    person_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("people.id", ondelete="CASCADE"), nullable=False
    )
    credit_type: Mapped[str] = mapped_column(
        Enum("cast", "crew", name="credit_type", native_enum=True), nullable=False
    )
    character_name: Mapped[str | None] = mapped_column(String(200))
    job: Mapped[str | None] = mapped_column(String(120))  # Director, Composer
    billing_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="99")

    movie: Mapped[Movie] = relationship(back_populates="credits")
    person: Mapped[Person] = relationship(back_populates="credits")

    __table_args__ = (
        # NULLS NOT DISTINCT (PostgreSQL 15+) is essential here: `job` and
        # `character_name` are nullable, and under the default NULLS DISTINCT
        # rule two crew rows with a NULL job would *both* be allowed, so the
        # constraint would silently permit the duplicates it exists to stop.
        UniqueConstraint(
            "movie_id",
            "person_id",
            "credit_type",
            "job",
            "character_name",
            name="uq_movie_credits_identity",
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_movie_credits_movie_id_billing_order", "movie_id", "billing_order"),
        Index("ix_movie_credits_person_id", "person_id"),
    )


class Review(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A user's rating and written review.

    Reviews are the richest free text in the system. Treat the body as
    untrusted, attacker-controlled input wherever it is processed.
    """

    __tablename__ = "reviews"

    movie_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("movies.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Only someone who actually attended can review -- set when created from a
    # confirmed booking. Nullable so seeded/imported reviews are still possible.
    booking_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bookings.id", ondelete="SET NULL")
    )
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 1..10
    title: Mapped[str | None] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    is_spoiler: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    helpful_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    # Reserved for downstream enrichment, e.g. {"story": 8, "acting": 9, ...}
    ai_aspects: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    ai_sentiment: Mapped[float | None] = mapped_column(Numeric(4, 3))  # -1.000..1.000
    ai_processed_at: Mapped[date | None] = mapped_column(Date)

    movie: Mapped[Movie] = relationship(back_populates="reviews")

    __table_args__ = (
        UniqueConstraint("movie_id", "user_id", name="uq_reviews_movie_id_user_id"),
        Index("ix_reviews_movie_id_created_at", "movie_id", "created_at"),
        Index("ix_reviews_user_id", "user_id"),
        CheckConstraint("rating between 1 and 10", name="rating_range"),
    )
