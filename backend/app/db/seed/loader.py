"""Seed loader.

Idempotent: safe to run repeatedly. Every insert is guarded by a lookup, so a
second run tops up what is missing rather than duplicating what is there.

The interesting part is `_create_shows`, which is also the reference
implementation of "how a showtime gets created": local wall time plus the
cinema's IANA zone, converted to an absolute instant, with `show_date` recorded
separately so a 00:30 show still lists under the previous evening.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, insert, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import ShowStatus, UserRole
from app.core.logging import get_logger
from app.core.db import _new_uuid7
from app.core.security import hash_password
# Importing the registry (not just the handful of models used below) is required:
# SQLAlchemy resolves string-based relationship targets like "Booking" only once
# every mapped class has been imported. Any entry point that touches the ORM
# needs this line.
import app.db.models  # noqa: F401
from app.db.seed import data as D
from app.modules.catalog.models import Genre, Language, Movie, MovieCredit, Person
from app.modules.fnb.models import FnbItem
from app.modules.identity.models import User
from app.modules.pricing.models import Offer
from app.modules.scheduling.models import Format, Show, ShowPrice
from app.modules.venues.models import Cinema, City, Screen, Seat, SeatCategory

logger = get_logger(__name__)

# Fixed seed: the same catalogue every run, so screenshots, tests and demos are
# reproducible. Randomness here is for texture, not for realism of outcome.
RNG = random.Random(20240817)

ROWS = "ABCDEFGHIJ"
SEATS_PER_ROW = 14
AISLES_AFTER_SEAT = (3, 11)
CATEGORY_BY_ROW = {
    **{r: "CLASSIC" for r in "ABCD"},
    **{r: "PRIME" for r in "EFGH"},
    **{r: "RECLINER" for r in "IJ"},
}
SHOW_TIMES = (time(10, 15), time(13, 30), time(17, 0), time(20, 45))
SHOW_DAYS = 6

# (email, full name, role, password)
#
# The domain must be one `email-validator` accepts. `.local` and `.test` are
# reserved special-use TLDs and are rejected outright, which would let these
# users be seeded but never sign in -- the row exists, every login 422s.
# `tests/integration/test_seed_accounts.py` asserts each of these can log in.
SEED_USERS: tuple[tuple[str, str, UserRole, str], ...] = (
    ("admin@cineai.example", "Admin User", UserRole.ADMIN, "adminpass1"),
    ("operator@cineai.example", "Cinema Operator", UserRole.CINEMA_OPERATOR, "operatorpass1"),
    ("demo@cineai.example", "Demo Customer", UserRole.CUSTOMER, "demopass1"),
    ("asha@example.com", "Asha Menon", UserRole.CUSTOMER, "ashapass1"),
    ("rohit@example.com", "Rohit Shetty", UserRole.CUSTOMER, "rohitpass1"),
)


def _slug(value: str) -> str:
    out = "".join(c.lower() if c.isalnum() else "-" for c in value)
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")


def run_seed(db: Session, *, days: int = SHOW_DAYS) -> dict[str, int]:
    stats: dict[str, int] = {}

    languages = _seed_languages(db)
    genres = _seed_genres(db)
    formats = _seed_formats(db)
    cities = _seed_cities(db)
    users = _seed_users(db, cities)
    cinemas = _seed_cinemas(db, cities, users)
    categories = _seed_seat_categories(db, cinemas)
    screens = _seed_screens(db, cinemas, categories)
    movies = _seed_movies(db, languages, genres)
    _seed_people_and_credits(db, movies)
    _seed_fnb(db, cinemas)
    _seed_offers(db)
    db.flush()

    shows = _create_shows(db, screens, movies, formats, languages, categories, days=days)

    stats.update(
        languages=len(languages), genres=len(genres), formats=len(formats),
        cities=len(cities), users=len(users), cinemas=len(cinemas),
        screens=len(screens), movies=len(movies), shows=len(shows),
    )
    stats["seats"] = db.execute(select(func.count()).select_from(Seat)).scalar_one()
    stats["show_seats"] = db.execute(
        select(func.count()).select_from(Show).join(Show.seats)
    ).scalar_one()
    return stats


# ---------------------------------------------------------------- reference ---
def _seed_languages(db: Session) -> dict[str, Language]:
    out: dict[str, Language] = {}
    for item in D.LANGUAGES:
        lang = db.execute(
            select(Language).where(Language.code == item["code"])
        ).scalar_one_or_none()
        if lang is None:
            lang = Language(code=item["code"], name=item["name"], native_name=item["native"])
            db.add(lang)
        out[item["code"]] = lang
    db.flush()
    return out


def _seed_genres(db: Session) -> dict[str, Genre]:
    out: dict[str, Genre] = {}
    for name in D.GENRES:
        g = db.execute(select(Genre).where(Genre.name == name)).scalar_one_or_none()
        if g is None:
            g = Genre(name=name, slug=_slug(name))
            db.add(g)
        out[name] = g
    db.flush()
    return out


def _seed_formats(db: Session) -> dict[str, Format]:
    out: dict[str, Format] = {}
    for item in D.FORMATS:
        f = db.execute(select(Format).where(Format.code == item["code"])).scalar_one_or_none()
        if f is None:
            f = Format(
                code=item["code"], name=item["name"],
                surcharge_minor=item["surcharge_minor"], display_order=item["order"],
            )
            db.add(f)
        out[item["code"]] = f
    db.flush()
    return out


def _seed_cities(db: Session) -> dict[str, City]:
    out: dict[str, City] = {}
    for item in D.CITIES:
        c = db.execute(select(City).where(City.slug == item["slug"])).scalar_one_or_none()
        if c is None:
            c = City(
                name=item["name"], slug=item["slug"], state=item["state"],
                latitude=item["lat"], longitude=item["lon"], display_order=item["order"],
                timezone="Asia/Kolkata",
            )
            db.add(c)
        out[item["slug"]] = c
    db.flush()
    return out


# --------------------------------------------------------------------- users ---
def _seed_users(db: Session, cities: dict[str, City]) -> list[User]:
    out: list[User] = []
    for email, name, role, password in SEED_USERS:
        u = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if u is None:
            u = User(
                email=email, full_name=name, role=role,
                password_hash=hash_password(password),
                default_city_id=cities["bengaluru"].id,
                email_verified_at=datetime.now(UTC),
            )
            db.add(u)
        out.append(u)
    db.flush()
    return out


# ------------------------------------------------------------------- venues ---
def _seed_cinemas(db: Session, cities: dict[str, City], users: list[User]) -> list[Cinema]:
    operator = next(u for u in users if u.role == UserRole.CINEMA_OPERATOR)
    out: list[Cinema] = []
    for city in cities.values():
        for bp in D.CINEMA_BLUEPRINTS:
            name = f"{bp['brand']}: {bp['suffix']}, {city.name}"
            slug = _slug(name)
            c = db.execute(select(Cinema).where(Cinema.slug == slug)).scalar_one_or_none()
            if c is None:
                c = Cinema(
                    city_id=city.id, name=name, slug=slug, brand=bp["brand"],
                    address_line=f"{bp['suffix']}, {bp['locality']}, {city.name}",
                    locality=bp["locality"], timezone=city.timezone,
                    amenities=bp["amenities"], operator_user_id=operator.id,
                    latitude=city.latitude, longitude=city.longitude,
                )
                db.add(c)
            out.append(c)
    db.flush()
    return out


def _seed_seat_categories(
    db: Session, cinemas: list[Cinema]
) -> dict[uuid.UUID, dict[str, SeatCategory]]:
    out: dict[uuid.UUID, dict[str, SeatCategory]] = {}
    for cinema in cinemas:
        per_cinema: dict[str, SeatCategory] = {}
        # Each brand positions itself differently. Seat categories are per
        # cinema, so this is where a hall's price level actually lives -- there
        # is no movie price to override.
        factor = D.BRAND_PRICE_FACTOR.get(cinema.brand or "", 1.0)
        for code, name, price, order, colour in D.SEAT_CATEGORIES:
            cat = db.execute(
                select(SeatCategory).where(
                    SeatCategory.cinema_id == cinema.id, SeatCategory.code == code
                )
            ).scalar_one_or_none()
            if cat is None:
                positioned = int(round(price * factor / 500.0)) * 500
                cat = SeatCategory(
                    cinema_id=cinema.id, code=code, name=name,
                    default_price_minor=positioned, display_order=order,
                    color_hex=colour,
                )
                db.add(cat)
            per_cinema[code] = cat
        out[cinema.id] = per_cinema
    db.flush()
    return out


def _seed_screens(
    db: Session,
    cinemas: list[Cinema],
    categories: dict[uuid.UUID, dict[str, SeatCategory]],
) -> list[Screen]:
    out: list[Screen] = []
    for cinema in cinemas:
        for number in (1, 2):
            screen = db.execute(
                select(Screen).where(
                    Screen.cinema_id == cinema.id, Screen.screen_number == number
                )
            ).scalar_one_or_none()
            if screen is None:
                supported = ["2D", "3D"] if number == 1 else ["2D", "IMAX", "IMAX3D"]
                screen = Screen(
                    cinema_id=cinema.id,
                    name=f"Audi {number}",
                    screen_number=number,
                    supported_formats=supported,
                    sound_system="Dolby Atmos" if number == 2 else "Dolby 7.1",
                    layout_meta={
                        "aisles_after_columns": [2, 11],
                        "screen_label": "All eyes this way",
                        "curved": True,
                    },
                )
                db.add(screen)
                db.flush()
                _create_seats(db, screen, categories[cinema.id])
            out.append(screen)
    db.flush()
    return out


def _create_seats(
    db: Session, screen: Screen, categories: dict[str, SeatCategory]
) -> None:
    """Lay out one auditorium.

    ``column_index`` is not ``seat_number``: aisles occupy grid columns without
    being seats. Keeping them distinct is what lets the UI render the gap, and
    lets "give me an aisle seat" mean something precise later on.
    """
    rows: list[dict] = []
    for row_index, row_label in enumerate(ROWS):
        category = categories[CATEGORY_BY_ROW[row_label]]
        column = 0
        for seat_number in range(1, SEATS_PER_ROW + 1):
            rows.append(
                {
                    "id": _new_uuid7(),
                    "screen_id": screen.id,
                    "category_id": category.id,
                    "row_label": row_label,
                    "row_index": row_index,
                    "seat_number": seat_number,
                    "column_index": column,
                    "is_aisle": seat_number in (1, SEATS_PER_ROW, *AISLES_AFTER_SEAT)
                    or seat_number - 1 in AISLES_AFTER_SEAT,
                    "is_wheelchair_accessible": (row_label == "A" and seat_number in (1, 2)),
                    "is_companion": (row_label == "A" and seat_number == 3),
                }
            )
            column += 2 if seat_number in AISLES_AFTER_SEAT else 1

    # A Core executemany rather than 140 ORM adds. psycopg turns this into a
    # handful of multi-row INSERTs instead of one statement per seat, which over
    # a network is the whole difference: round trips, not query time, are what
    # a remote seed spends its life on.
    db.execute(insert(Seat), rows)
    screen.total_seats = len(rows)
    db.flush()


# ------------------------------------------------------------------ catalog ---
def _seed_movies(
    db: Session, languages: dict[str, Language], genres: dict[str, Genre]
) -> list[Movie]:
    out: list[Movie] = []
    today = date.today()
    for i, spec in enumerate(D.MOVIES):
        slug = _slug(spec["title"])
        m = db.execute(select(Movie).where(Movie.slug == slug)).scalar_one_or_none()
        if m is None:
            release = (
                today - timedelta(days=RNG.randint(3, 60))
                if spec["status"] == "now_showing"
                else today + timedelta(days=RNG.randint(10, 90))
            )
            m = Movie(
                title=spec["title"], slug=slug, tagline=spec["tagline"],
                synopsis=spec["synopsis"], runtime_minutes=spec["runtime"],
                certification=spec["certification"], release_date=release,
                status=spec["status"],
                original_language_id=languages[spec["language"]].id,
                rating_average=spec["rating"],
                rating_count=RNG.randint(120, 4800) if spec["rating"] else 0,
                popularity_score=round(RNG.uniform(20, 100), 3),
                ai_attributes=spec["attributes"],
                poster_url=f"https://placehold.co/400x600/1e293b/f8fafc?text={spec['title'].replace(' ', '+')}",
                backdrop_url=f"https://placehold.co/1280x720/0f172a/f8fafc?text={spec['title'].replace(' ', '+')}",
            )
            m.genres = [genres[g] for g in spec["genres"]]
            m.languages = [languages[spec["language"]]]
            # Bigger titles get dubbed; gives the language filter something to do.
            if i % 3 == 0:
                m.languages.append(languages["hi"])
            db.add(m)
        out.append(m)
    db.flush()
    return out


def _seed_people_and_credits(db: Session, movies: list[Movie]) -> None:
    people: list[Person] = []
    for name, _kind in D.PEOPLE:
        p = db.execute(select(Person).where(Person.slug == _slug(name))).scalar_one_or_none()
        if p is None:
            p = Person(name=name, slug=_slug(name))
            db.add(p)
        people.append(p)
    db.flush()

    cast_pool = [p for p, (_, k) in zip(people, D.PEOPLE, strict=True) if k == "cast"]
    crew_pool = [p for p, (_, k) in zip(people, D.PEOPLE, strict=True) if k == "crew"]

    for movie in movies:
        existing = db.execute(
            select(func.count()).select_from(MovieCredit).where(MovieCredit.movie_id == movie.id)
        ).scalar_one()
        if existing:
            continue
        for order, person in enumerate(RNG.sample(cast_pool, k=3)):
            db.add(
                MovieCredit(
                    movie_id=movie.id, person_id=person.id, credit_type="cast",
                    character_name=f"Role {order + 1}", billing_order=order,
                )
            )
        director = RNG.choice(crew_pool)
        db.add(
            MovieCredit(
                movie_id=movie.id, person_id=director.id, credit_type="crew",
                job="Director", billing_order=0,
            )
        )
    db.flush()


def _seed_fnb(db: Session, cinemas: list[Cinema]) -> None:
    for cinema in cinemas:
        for order, (name, category, price, is_veg) in enumerate(D.FNB_ITEMS):
            exists = db.execute(
                select(FnbItem).where(FnbItem.cinema_id == cinema.id, FnbItem.name == name)
            ).scalar_one_or_none()
            if exists is None:
                db.add(
                    FnbItem(
                        cinema_id=cinema.id, name=name, category=category,
                        price_minor=price, is_vegetarian=is_veg, display_order=order,
                    )
                )
    db.flush()


def _seed_offers(db: Session) -> None:
    now = datetime.now(UTC)
    for spec in D.OFFERS:
        o = db.execute(select(Offer).where(Offer.code == spec["code"])).scalar_one_or_none()
        if o is not None:
            continue
        db.add(
            Offer(
                code=spec["code"], name=spec["name"], description=spec["description"],
                offer_type=spec["type"],
                percent_off=spec.get("percent"),
                flat_off_minor=spec.get("flat_off_minor"),
                max_discount_minor=spec.get("max_discount_minor"),
                min_order_minor=spec["min_order_minor"],
                usage_limit_per_user=spec["per_user"],
                usage_limit_total=spec["total"],
                valid_from=now - timedelta(days=1),
                valid_until=now + timedelta(days=180),
                conditions=spec["conditions"],
            )
        )
    db.flush()


# -------------------------------------------------------------------- shows ---
def _create_shows(
    db: Session,
    screens: list[Screen],
    movies: list[Movie],
    formats: dict[str, Format],
    languages: dict[str, Language],
    categories: dict[uuid.UUID, dict[str, SeatCategory]],
    *,
    days: int,
) -> list[Show]:
    """Schedule shows for the next `days` days.

    Note how the instant is built: a naive local wall time is attached to the
    cinema's zone and only then converted to UTC. Doing it the other way round
    (UTC first, shift later) is the bug that makes every show an hour wrong
    twice a year in DST regions.

    Everything is built in memory first and written in a handful of statements.
    The obvious per-show shape -- check, insert, flush, price, refresh,
    materialise -- costs six round trips per show, which is invisible against a
    local socket and takes minutes against a managed database.
    """
    showable = [m for m in movies if m.status == "now_showing"]
    today = date.today()

    # One query for what already exists, instead of one per candidate show.
    existing: dict[tuple[uuid.UUID, datetime], Show] = {
        (show.screen_id, show.starts_at): show
        for show in db.execute(select(Show)).scalars()
    }

    cinemas = {c.id: c for c in db.execute(select(Cinema)).scalars()}

    created: list[Show] = []
    new_shows: list[Show] = []
    price_rows: list[dict] = []

    for screen in screens:
        cinema = cinemas[screen.cinema_id]
        tz = ZoneInfo(cinema.timezone)
        cats = categories[cinema.id]

        for day_offset in range(days):
            show_date = today + timedelta(days=day_offset)
            is_weekend = show_date.weekday() >= 5

            for slot_index, slot in enumerate(SHOW_TIMES):
                # Deliberately keyed on (day, slot, screen number) and NOT on
                # the screen's id: every cinema has a screen 1 and a screen 2,
                # so the same film lands in the same slot everywhere. That is
                # what gives the price-comparison view something to compare --
                # one title, many halls, different prices.
                movie = showable[
                    (day_offset * len(SHOW_TIMES) + slot_index + screen.screen_number)
                    % len(showable)
                ]

                # Local wall time -> zoned datetime -> absolute instant.
                local_start = datetime.combine(show_date, slot, tzinfo=tz)
                starts_at = local_start.astimezone(UTC)

                if (prior := existing.get((screen.id, starts_at))) is not None:
                    created.append(prior)
                    continue

                fmt = formats[_pick_format(screen.supported_formats, slot_index)]
                # Runtime + 20 minutes of trailers and turnaround.
                ends_at = starts_at + timedelta(minutes=movie.runtime_minutes + 20)

                show = Show(
                    id=_new_uuid7(),
                    movie_id=movie.id,
                    screen_id=screen.id,
                    cinema_id=cinema.id,
                    city_id=cinema.city_id,
                    format_id=fmt.id,
                    audio_language_id=movie.languages[0].id,
                    subtitle_language_id=languages["en"].id,
                    starts_at=starts_at,
                    ends_at=ends_at,
                    show_date=show_date,   # local calendar date, not UTC's
                    status=ShowStatus.OPEN,
                    sales_close_at=starts_at
                    - timedelta(minutes=settings.booking_cutoff_minutes),
                    screen_layout_version=screen.layout_version,
                )
                new_shows.append(show)
                price_rows.extend(
                    _price_rows(show, cats, is_weekend=is_weekend, slot_index=slot_index)
                )
                created.append(show)

    if not new_shows:
        return created

    db.add_all(new_shows)
    db.flush()
    db.execute(insert(ShowPrice), price_rows)
    db.flush()

    _materialize_seats_bulk(db, [s.id for s in new_shows])
    return created


def _materialize_seats_bulk(db: Session, show_ids: list[uuid.UUID]) -> None:
    """Create every show_seat row for a batch of shows in two statements.

    The same logic as ``InventoryService.materialize_seats`` -- price resolved
    from show_prices with the category default as a fallback, plus the format
    surcharge -- but joined across many shows at once. The service keeps its
    per-show version because that is what the operator flow needs; this exists
    because seeding 288 shows one at a time over a network is unusable.
    """
    db.execute(
        text(
            """
            INSERT INTO show_seats
                   (id, show_id, seat_id, seat_category_id, price_minor,
                    status, created_at, updated_at)
            SELECT uuidv7(), sh.id, s.id, s.category_id,
                   COALESCE(sp.price_minor, sc.default_price_minor) + f.surcharge_minor,
                   'available', now(), now()
              FROM shows sh
              JOIN formats f            ON f.id = sh.format_id
              JOIN seats s              ON s.screen_id = sh.screen_id AND s.is_active
              JOIN seat_categories sc   ON sc.id = s.category_id
         LEFT JOIN show_prices sp       ON sp.show_id = sh.id
                                       AND sp.seat_category_id = s.category_id
             WHERE sh.id = ANY(CAST(:show_ids AS uuid[]))
            ON CONFLICT (show_id, seat_id) DO NOTHING
            """
        ),
        {"show_ids": [str(i) for i in show_ids]},
    )
    db.execute(
        text(
            """
            UPDATE shows sh
               SET total_seats = c.n, available_seats = c.n
              FROM (SELECT show_id, count(*) AS n
                      FROM show_seats
                     WHERE show_id = ANY(CAST(:show_ids AS uuid[]))
                     GROUP BY show_id) c
             WHERE sh.id = c.show_id
            """
        ),
        {"show_ids": [str(i) for i in show_ids]},
    )
    db.flush()
    logger.info("show_seats_materialized", shows=len(show_ids))


def _pick_format(supported: list[str], slot_index: int) -> str:
    if "IMAX" in supported and slot_index in (2, 3):
        return "IMAX"
    if "3D" in supported and slot_index == 1:
        return "3D"
    return "2D"


def _price_rows(
    show: Show,
    categories: dict[str, SeatCategory],
    *,
    is_weekend: bool,
    slot_index: int,
) -> list[dict]:
    """Simple rule-based pricing -- the baseline any smarter pricing must beat.

    Morning shows are discounted, evenings and weekends carry a premium.
    Returns plain dicts so the caller can insert every show's prices in one
    statement instead of three per show.
    """
    multiplier = 1.0
    if slot_index == 0:
        multiplier -= 0.25          # matinee
    if slot_index == 3:
        multiplier += 0.15          # prime evening
    if is_weekend:
        multiplier += 0.20

    rows = []
    for category in categories.values():
        price = int(round(category.default_price_minor * multiplier / 500.0)) * 500
        rows.append(
            {
                "id": _new_uuid7(),
                "show_id": show.id,
                "seat_category_id": category.id,
                "price_minor": max(price, 5000),
            }
        )
    return rows
