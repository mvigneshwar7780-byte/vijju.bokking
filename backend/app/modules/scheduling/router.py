"""Showtime endpoints."""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Query

from app.core.deps import DbSession
from app.modules.scheduling.schemas import (
    CinemaMoviesOut,
    FormatOut,
    MoviePriceComparisonOut,
    ShowDetailOut,
    ShowtimeBoardOut,
)
from app.modules.scheduling.service import SchedulingService

router = APIRouter(tags=["showtimes"])


@router.get("/showtimes", response_model=ShowtimeBoardOut)
def showtime_board(
    db: DbSession,
    movie_id: uuid.UUID = Query(...),
    city_id: uuid.UUID = Query(...),
    show_date: date | None = Query(None, alias="date"),
) -> ShowtimeBoardOut:
    """Every cinema and showtime for one movie, one city, one date."""
    return SchedulingService(db).board(
        movie_id=movie_id, city_id=city_id, show_date=show_date
    )


@router.get("/cinemas/{cinema_id}/movies", response_model=CinemaMoviesOut)
def movies_at_cinema(
    cinema_id: uuid.UUID,
    db: DbSession,
    show_date: date | None = Query(None, alias="date"),
) -> CinemaMoviesOut:
    """The cinema-first browse: everything playing at one hall.

    Prices in the response are *this hall's* prices, drawn from its own shows.
    """
    return SchedulingService(db).movies_at_cinema(
        cinema_id=cinema_id, show_date=show_date
    )


@router.get("/movies/{movie_id}/cinemas", response_model=MoviePriceComparisonOut)
def compare_cinemas_for_movie(
    movie_id: uuid.UUID,
    db: DbSession,
    city_id: uuid.UUID = Query(...),
    show_date: date | None = Query(None, alias="date"),
) -> MoviePriceComparisonOut:
    """The movie-first browse: every hall showing this film, cheapest first.

    Returns one row per cinema with its price range, formats, languages and
    remaining seats -- the comparison that only makes sense because price is a
    property of the show, not of the movie.
    """
    return SchedulingService(db).price_comparison(
        movie_id=movie_id, city_id=city_id, show_date=show_date
    )


@router.get("/shows/{show_id}", response_model=ShowDetailOut)
def get_show(show_id: uuid.UUID, db: DbSession) -> ShowDetailOut:
    return SchedulingService(db).get_show(show_id)


@router.get("/formats", response_model=list[FormatOut])
def list_formats(db: DbSession) -> list[FormatOut]:
    return [FormatOut.model_validate(f) for f in SchedulingService(db).list_formats()]
