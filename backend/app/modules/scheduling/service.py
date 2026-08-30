"""Showtime queries.

The board query is the one that has to be fast: it is the screen every customer
hits between choosing a film and choosing seats. It is served by the composite
index ``ix_shows_city_id_movie_id_show_date``, which is the entire justification
for denormalising ``city_id`` onto ``shows``.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.core.errors import NotFoundError
from app.modules.catalog.models import Language, Movie
from app.modules.scheduling.models import Format, Show, ShowPrice
from app.modules.scheduling.schemas import (
    CinemaMovieOut,
    CinemaMoviesOut,
    CinemaPriceOut,
    CinemaShowsOut,
    MoviePriceComparisonOut,
    ShowCardOut,
    ShowDetailOut,
    ShowtimeBoardOut,
)
from app.modules.venues.models import Cinema, City, Screen


def availability_band(available: int, total: int) -> str:
    if total <= 0 or available <= 0:
        return "sold_out"
    ratio = available / total
    if ratio <= 0.1:
        return "almost_full"
    if ratio <= 0.35:
        return "filling_fast"
    return "available"


class SchedulingService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def board(
        self, *, movie_id: uuid.UUID, city_id: uuid.UUID, show_date: date | None
    ) -> ShowtimeBoardOut:
        movie = self.db.get(Movie, movie_id)
        if movie is None:
            raise NotFoundError("That movie does not exist.")
        city = self.db.get(City, city_id)
        if city is None:
            raise NotFoundError("That city does not exist.")

        available_dates = list(
            self.db.execute(
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
        )
        target = show_date or (available_dates[0] if available_dates else date.today())

        # Cheapest seat category per show, computed in one pass instead of N+1.
        min_price = (
            select(ShowPrice.show_id, func.min(ShowPrice.price_minor).label("min_price"))
            .group_by(ShowPrice.show_id)
            .subquery()
        )

        rows = self.db.execute(
            select(Show, Cinema, Screen, Format, Language, min_price.c.min_price)
            .join(Cinema, Cinema.id == Show.cinema_id)
            .join(Screen, Screen.id == Show.screen_id)
            .join(Format, Format.id == Show.format_id)
            .join(Language, Language.id == Show.audio_language_id)
            .outerjoin(min_price, min_price.c.show_id == Show.id)
            .where(
                Show.movie_id == movie_id,
                Show.city_id == city_id,
                Show.show_date == target,
                Show.status == "open",
                # Shows whose sales window has closed are past history to a
                # customer -- listing this morning's 10:15 at 3pm and then
                # rejecting the hold is the worst of both worlds. An operator
                # view that wants them uses the admin schedule endpoint.
                Show.sales_close_at > func.now(),
            )
            .order_by(Cinema.name, Show.starts_at)
        ).all()

        by_cinema: dict[uuid.UUID, CinemaShowsOut] = {}
        for show, cinema, screen, fmt, language, price in rows:
            entry = by_cinema.get(cinema.id)
            if entry is None:
                entry = CinemaShowsOut(
                    cinema_id=cinema.id,
                    cinema_name=cinema.name,
                    brand=cinema.brand,
                    locality=cinema.locality,
                    amenities=cinema.amenities or [],
                    shows=[],
                )
                by_cinema[cinema.id] = entry
            subtitle = (
                self.db.get(Language, show.subtitle_language_id)
                if show.subtitle_language_id
                else None
            )
            entry.shows.append(
                ShowCardOut(
                    id=show.id,
                    starts_at=show.starts_at,
                    ends_at=show.ends_at,
                    show_date=show.show_date,
                    format_code=fmt.code,
                    format_name=fmt.name,
                    audio_language=language.name,
                    subtitle_language=subtitle.name if subtitle else None,
                    screen_name=screen.name,
                    status=show.status.value,
                    available_seats=show.available_seats,
                    total_seats=show.total_seats,
                    min_price_minor=int(price or 0),
                    availability_band=availability_band(
                        show.available_seats, show.total_seats
                    ),
                    is_bookable=show.is_bookable,
                )
            )

        return ShowtimeBoardOut(
            movie_id=movie.id,
            movie_title=movie.title,
            city_id=city.id,
            city_name=city.name,
            show_date=target,
            available_dates=available_dates,
            cinemas=list(by_cinema.values()),
        )

    def movies_at_cinema(
        self, *, cinema_id: uuid.UUID, show_date: date | None
    ) -> CinemaMoviesOut:
        """Everything playing at one hall, with that hall's own prices.

        The cinema-first browse pivot. Prices come from `show_prices` for the
        shows at *this* cinema, so the range shown is what this hall charges --
        not a platform average and not a property of the film.
        """
        cinema = self.db.get(Cinema, cinema_id)
        if cinema is None:
            raise NotFoundError("That cinema does not exist.")
        city = self.db.get(City, cinema.city_id)

        available_dates = list(
            self.db.execute(
                select(Show.show_date)
                .where(
                    Show.cinema_id == cinema_id,
                    Show.status == "open",
                    Show.sales_close_at > func.now(),
                )
                .distinct()
                .order_by(Show.show_date)
            ).scalars()
        )
        target = show_date or (available_dates[0] if available_dates else None)

        rows: list[CinemaMovieOut] = []
        if target is not None:
            price_agg = (
                select(
                    ShowPrice.show_id,
                    func.min(ShowPrice.price_minor).label("lo"),
                    func.max(ShowPrice.price_minor).label("hi"),
                )
                .group_by(ShowPrice.show_id)
                .subquery()
            )
            result = self.db.execute(
                select(
                    Movie,
                    func.count(Show.id).label("show_count"),
                    func.min(Show.starts_at).label("next_show"),
                    func.min(price_agg.c.lo).label("min_price"),
                    func.max(price_agg.c.hi).label("max_price"),
                    func.array_agg(func.distinct(Format.code)).label("formats"),
                )
                .join(Show, Show.movie_id == Movie.id)
                .join(Format, Format.id == Show.format_id)
                .outerjoin(price_agg, price_agg.c.show_id == Show.id)
                .where(
                    Show.cinema_id == cinema_id,
                    Show.show_date == target,
                    Show.status == "open",
                    Show.sales_close_at > func.now(),
                )
                .group_by(Movie.id)
                .order_by(func.min(Show.starts_at))
            ).all()

            for movie, show_count, next_show, lo, hi, formats in result:
                movie_dates = list(
                    self.db.execute(
                        select(Show.show_date)
                        .where(
                            Show.cinema_id == cinema_id,
                            Show.movie_id == movie.id,
                            Show.status == "open",
                            Show.sales_close_at > func.now(),
                        )
                        .distinct()
                        .order_by(Show.show_date)
                    ).scalars()
                )
                rows.append(
                    CinemaMovieOut(
                        movie_id=movie.id,
                        title=movie.title,
                        slug=movie.slug,
                        poster_url=movie.poster_url,
                        certification=movie.certification,
                        runtime_minutes=movie.runtime_minutes,
                        rating_average=(
                            float(movie.rating_average)
                            if movie.rating_average is not None
                            else None
                        ),
                        genres=[g.name for g in movie.genres],
                        languages=[x.name for x in movie.languages],
                        formats=sorted(f for f in (formats or []) if f),
                        show_count=int(show_count),
                        next_show_at=next_show,
                        min_price_minor=int(lo or 0),
                        max_price_minor=int(hi or 0),
                        available_dates=movie_dates,
                    )
                )

        return CinemaMoviesOut(
            cinema_id=cinema.id,
            cinema_name=cinema.name,
            brand=cinema.brand,
            locality=cinema.locality,
            city_name=city.name if city else "",
            amenities=cinema.amenities or [],
            show_date=target,
            movies=rows,
        )

    def price_comparison(
        self, *, movie_id: uuid.UUID, city_id: uuid.UUID, show_date: date | None
    ) -> MoviePriceComparisonOut:
        """One film, every hall showing it, cheapest first.

        This is the view that makes the pricing model visible: the same movie at
        three cinemas at three prices, because price lives on
        cinema -> screen -> show -> seat category and nowhere else.
        """
        movie = self.db.get(Movie, movie_id)
        if movie is None:
            raise NotFoundError("That movie does not exist.")
        city = self.db.get(City, city_id)
        if city is None:
            raise NotFoundError("That city does not exist.")

        available_dates = list(
            self.db.execute(
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
        )
        target = show_date or (available_dates[0] if available_dates else date.today())

        price_agg = (
            select(
                ShowPrice.show_id,
                func.min(ShowPrice.price_minor).label("lo"),
                func.max(ShowPrice.price_minor).label("hi"),
            )
            .group_by(ShowPrice.show_id)
            .subquery()
        )
        rows = self.db.execute(
            select(
                Cinema,
                func.count(Show.id).label("show_count"),
                func.min(Show.starts_at).label("earliest"),
                func.max(Show.starts_at).label("latest"),
                func.min(price_agg.c.lo).label("min_price"),
                func.max(price_agg.c.hi).label("max_price"),
                func.array_agg(func.distinct(Format.code)).label("formats"),
                func.array_agg(func.distinct(Language.name)).label("languages"),
                func.sum(Show.available_seats).label("seats"),
            )
            .join(Show, Show.cinema_id == Cinema.id)
            .join(Format, Format.id == Show.format_id)
            .join(Language, Language.id == Show.audio_language_id)
            .outerjoin(price_agg, price_agg.c.show_id == Show.id)
            .where(
                Show.movie_id == movie_id,
                Show.city_id == city_id,
                Show.show_date == target,
                Show.status == "open",
                Show.sales_close_at > func.now(),
            )
            .group_by(Cinema.id)
            .order_by(func.min(price_agg.c.lo).nulls_last())
        ).all()

        cinemas = [
            CinemaPriceOut(
                cinema_id=cinema.id,
                cinema_name=cinema.name,
                brand=cinema.brand,
                locality=cinema.locality,
                amenities=cinema.amenities or [],
                distance_km=None,
                show_count=int(count),
                earliest_show_at=earliest,
                latest_show_at=latest,
                min_price_minor=int(lo or 0),
                max_price_minor=int(hi or 0),
                formats=sorted(f for f in (formats or []) if f),
                languages=sorted(x for x in (languages or []) if x),
                total_available_seats=int(seats or 0),
            )
            for cinema, count, earliest, latest, lo, hi, formats, languages, seats in rows
        ]

        return MoviePriceComparisonOut(
            movie_id=movie.id,
            movie_title=movie.title,
            poster_url=movie.poster_url,
            city_id=city.id,
            city_name=city.name,
            show_date=target,
            available_dates=available_dates,
            cheapest_minor=min((c.min_price_minor for c in cinemas), default=None),
            dearest_minor=max((c.max_price_minor for c in cinemas), default=None),
            cinemas=cinemas,
        )

    def get_show(self, show_id: uuid.UUID) -> ShowDetailOut:
        row = self.db.execute(
            select(Show, Movie, Cinema, Screen, Format, Language, City)
            .join(Movie, Movie.id == Show.movie_id)
            .join(Cinema, Cinema.id == Show.cinema_id)
            .join(Screen, Screen.id == Show.screen_id)
            .join(Format, Format.id == Show.format_id)
            .join(Language, Language.id == Show.audio_language_id)
            .join(City, City.id == Show.city_id)
            .where(Show.id == show_id)
        ).one_or_none()
        if row is None:
            raise NotFoundError("That show does not exist.")
        show, movie, cinema, screen, fmt, language, city = row
        subtitle = (
            self.db.get(Language, show.subtitle_language_id)
            if show.subtitle_language_id
            else None
        )
        return ShowDetailOut(
            id=show.id,
            movie_id=movie.id,
            movie_title=movie.title,
            movie_poster_url=movie.poster_url,
            certification=movie.certification,
            runtime_minutes=movie.runtime_minutes,
            cinema_id=cinema.id,
            cinema_name=cinema.name,
            screen_name=screen.name,
            city_name=city.name,
            format_code=fmt.code,
            audio_language=language.name,
            subtitle_language=subtitle.name if subtitle else None,
            starts_at=show.starts_at,
            ends_at=show.ends_at,
            status=show.status.value,
            is_bookable=show.is_bookable,
            sales_close_at=show.sales_close_at,
            available_seats=show.available_seats,
            total_seats=show.total_seats,
        )

    def list_formats(self) -> list[Format]:
        return list(
            self.db.execute(select(Format).order_by(Format.display_order)).scalars()
        )

    def cinema_schedule(
        self, *, cinema_id: uuid.UUID, show_date: date
    ) -> list[tuple[Show, Movie, Format]]:
        return list(
            self.db.execute(
                select(Show, Movie, Format)
                .join(Movie, Movie.id == Show.movie_id)
                .join(Format, Format.id == Show.format_id)
                .where(
                    Show.cinema_id == cinema_id,
                    Show.show_date == show_date,
                    Show.status == "open",
                )
                .order_by(Show.starts_at)
                .options(joinedload(Show.screen))
            ).all()
        )
