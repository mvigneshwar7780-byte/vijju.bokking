"""Operator and platform-administrator endpoints.

Every route here goes through `admin.authorization`. An operator sees and
changes only their own cinemas; an administrator sees everything. The split is
enforced by the dependency on each route plus an explicit ownership check on the
entity -- role alone is not enough, because two operators share a role.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Query, status
from sqlalchemy import func, select

from app.core.deps import AdminUser, DbSession, OperatorUser, Pagination
from app.core.enums import UserRole
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.schemas import OkResponse, Page
from app.modules.admin import authorization as authz
from app.modules.admin.reports import ReportService
from app.modules.admin.schemas import (
    AssignOperatorRequest,
    BulkShowCreate,
    BulkShowResult,
    CancelShowRequest,
    CancelShowResult,
    ChangeRoleRequest,
    CinemaCreate,
    CinemaUpdate,
    LayoutCreate,
    LayoutPreview,
    MovieCreate,
    MovieUpdate,
    OccupancyReport,
    OperatorBookingOut,
    RevenueReport,
    ScreenCreate,
    ScreenUpdate,
    SeatCategoryCreate,
    SeatCategoryUpdate,
    ShowAdminOut,
    ShowCreate,
    ShowPriceInput,
    ShowUpdate,
)
from app.modules.admin.service import OperatorService
from app.modules.catalog.models import Movie
from app.modules.catalog.schemas import MovieDetailOut
from app.modules.identity.models import User
from app.modules.scheduling.models import Format, Show, ShowPrice
from app.modules.venues.models import Cinema, Screen, Seat, SeatCategory
from app.modules.venues.schemas import CinemaOut, ScreenOut

router = APIRouter(prefix="/operator", tags=["operator"])
admin_router = APIRouter(prefix="/admin", tags=["admin"])


# ============================================================== my cinemas ==
@router.get("/cinemas", response_model=list[CinemaOut])
def my_cinemas(db: DbSession, user: OperatorUser) -> list[CinemaOut]:
    """Cinemas this account manages. An administrator sees all of them."""
    stmt = select(Cinema).order_by(Cinema.name)
    allowed = authz.visible_cinema_ids(db, user)
    if allowed is not None:
        stmt = stmt.where(Cinema.id.in_(allowed))
    return [CinemaOut.model_validate(c) for c in db.execute(stmt).scalars()]


@router.post("/cinemas", response_model=CinemaOut, status_code=status.HTTP_201_CREATED)
def create_cinema(payload: CinemaCreate, db: DbSession, user: OperatorUser) -> CinemaOut:
    """Register a cinema. The creator becomes its operator."""
    service = OperatorService(db)
    cinema = Cinema(
        city_id=payload.city_id,
        name=payload.name.strip(),
        slug=service.unique_slug(Cinema, payload.name),
        brand=payload.brand,
        address_line=payload.address_line,
        locality=payload.locality,
        pincode=payload.pincode,
        timezone=payload.timezone,
        amenities=payload.amenities,
        latitude=payload.latitude,
        longitude=payload.longitude,
        operator_user_id=user.id,
    )
    db.add(cinema)
    db.commit()
    return CinemaOut.model_validate(cinema)


@router.patch("/cinemas/{cinema_id}", response_model=CinemaOut)
def update_cinema(
    cinema_id: uuid.UUID, payload: CinemaUpdate, db: DbSession, user: OperatorUser
) -> CinemaOut:
    cinema = authz.assert_can_manage_cinema(db, user, cinema_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(cinema, field, value)
    db.commit()
    return CinemaOut.model_validate(cinema)


# ======================================================== seat categories ==
@router.get("/cinemas/{cinema_id}/seat-categories")
def list_seat_categories(
    cinema_id: uuid.UUID, db: DbSession, user: OperatorUser
) -> list[dict]:
    authz.assert_can_manage_cinema(db, user, cinema_id)
    rows = db.execute(
        select(SeatCategory)
        .where(SeatCategory.cinema_id == cinema_id)
        .order_by(SeatCategory.display_order)
    ).scalars()
    return [
        {
            "id": c.id, "code": c.code, "name": c.name, "description": c.description,
            "default_price_minor": c.default_price_minor,
            "display_order": c.display_order, "color_hex": c.color_hex,
        }
        for c in rows
    ]


@router.post(
    "/cinemas/{cinema_id}/seat-categories", status_code=status.HTTP_201_CREATED
)
def create_seat_category(
    cinema_id: uuid.UUID,
    payload: SeatCategoryCreate,
    db: DbSession,
    user: OperatorUser,
) -> dict:
    """Seat tiers are per cinema, which is what lets two halls price the same
    film differently under the same tier name."""
    authz.assert_can_manage_cinema(db, user, cinema_id)
    exists = db.execute(
        select(SeatCategory.id).where(
            SeatCategory.cinema_id == cinema_id, SeatCategory.code == payload.code
        )
    ).first()
    if exists:
        raise ConflictError(
            f"This cinema already has a '{payload.code}' category.",
            code="CATEGORY_EXISTS",
        )
    category = SeatCategory(cinema_id=cinema_id, **payload.model_dump())
    db.add(category)
    db.commit()
    return {"id": category.id, "code": category.code, "name": category.name}


@router.patch("/seat-categories/{category_id}")
def update_seat_category(
    category_id: uuid.UUID,
    payload: SeatCategoryUpdate,
    db: DbSession,
    user: OperatorUser,
) -> dict:
    category = authz.assert_can_manage_seat_category(db, user, category_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(category, field, value)
    db.commit()
    return {"id": category.id, "code": category.code, "name": category.name}


# ================================================================= screens ==
@router.get("/cinemas/{cinema_id}/screens", response_model=list[ScreenOut])
def list_screens(
    cinema_id: uuid.UUID, db: DbSession, user: OperatorUser
) -> list[ScreenOut]:
    authz.assert_can_manage_cinema(db, user, cinema_id)
    rows = db.execute(
        select(Screen).where(Screen.cinema_id == cinema_id).order_by(Screen.screen_number)
    ).scalars()
    return [ScreenOut.model_validate(s) for s in rows]


@router.post(
    "/cinemas/{cinema_id}/screens",
    response_model=ScreenOut,
    status_code=status.HTTP_201_CREATED,
)
def create_screen(
    cinema_id: uuid.UUID, payload: ScreenCreate, db: DbSession, user: OperatorUser
) -> ScreenOut:
    authz.assert_can_manage_cinema(db, user, cinema_id)
    exists = db.execute(
        select(Screen.id).where(
            Screen.cinema_id == cinema_id, Screen.screen_number == payload.screen_number
        )
    ).first()
    if exists:
        raise ConflictError(
            f"Screen number {payload.screen_number} already exists here.",
            code="SCREEN_EXISTS",
        )
    screen = Screen(
        cinema_id=cinema_id,
        name=payload.name,
        screen_number=payload.screen_number,
        supported_formats=[f.upper() for f in payload.supported_formats],
        sound_system=payload.sound_system,
    )
    db.add(screen)
    db.commit()
    return ScreenOut.model_validate(screen)


@router.patch("/screens/{screen_id}", response_model=ScreenOut)
def update_screen(
    screen_id: uuid.UUID, payload: ScreenUpdate, db: DbSession, user: OperatorUser
) -> ScreenOut:
    screen = authz.assert_can_manage_screen(db, user, screen_id)
    data = payload.model_dump(exclude_unset=True)
    if data.get("supported_formats") is not None:
        screen.supported_formats = [f.upper() for f in data.pop("supported_formats")]
    for field, value in data.items():
        if value is not None:
            setattr(screen, field, value)
    db.commit()
    return ScreenOut.model_validate(screen)


@router.put("/screens/{screen_id}/layout", response_model=LayoutPreview)
def set_layout(
    screen_id: uuid.UUID, payload: LayoutCreate, db: DbSession, user: OperatorUser
) -> LayoutPreview:
    """Define the seating plan: rows, seat counts, tiers, aisles, accessibility.

    Refused while any show on this screen has sold or held a seat -- re-lettering
    under a live booking would leave a customer holding a ticket for a seat that
    no longer exists.
    """
    screen = authz.assert_can_manage_screen(db, user, screen_id)
    OperatorService(db).apply_layout(screen, payload)
    db.commit()

    rows = db.execute(
        select(
            Seat.row_label,
            func.count().label("seats"),
            SeatCategory.name,
        )
        .join(SeatCategory, SeatCategory.id == Seat.category_id)
        .where(Seat.screen_id == screen.id)
        .group_by(Seat.row_label, Seat.row_index, SeatCategory.name)
        .order_by(Seat.row_index)
    ).all()
    by_category: dict[str, int] = {}
    for _label, seats, category in rows:
        by_category[category] = by_category.get(category, 0) + int(seats)
    return LayoutPreview(
        screen_id=screen.id,
        total_seats=screen.total_seats,
        rows=[
            {"row_label": r[0], "seats": int(r[1]), "category": r[2]} for r in rows
        ],
        by_category=by_category,
    )


# ================================================================== movies ==
@router.post("/movies", response_model=MovieDetailOut, status_code=status.HTTP_201_CREATED)
def create_movie(payload: MovieCreate, db: DbSession, user: OperatorUser) -> MovieDetailOut:
    """Add a title to the shared catalogue.

    Movies are deliberately *not* owned by a cinema -- the same film plays at
    many halls at different prices, and per-cinema copies would fragment the
    catalogue and break "where else is this playing?". Provenance is recorded so
    you can edit what you added.
    """
    movie = OperatorService(db).create_movie(payload, author_id=user.id)
    db.commit()
    from app.modules.catalog.router import _detail
    from app.modules.catalog.service import CatalogService

    return _detail(CatalogService(db).get_movie(movie.id))


@router.get("/movies", response_model=Page[MovieDetailOut])
def my_movies(db: DbSession, user: OperatorUser, page: Pagination) -> Page[MovieDetailOut]:
    """Titles this account added (an administrator sees the whole catalogue)."""
    from app.modules.catalog.router import _detail
    from app.modules.catalog.service import CatalogService

    stmt = select(Movie).order_by(Movie.created_at.desc())
    if not authz.is_platform_admin(user):
        stmt = stmt.where(Movie.created_by_user_id == user.id)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.offset(page.offset).limit(page.limit)).unique().scalars()
    service = CatalogService(db)
    return Page[MovieDetailOut](
        items=[_detail(service.get_movie(m.id)) for m in rows],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.patch("/movies/{movie_id}", response_model=MovieDetailOut)
def update_movie(
    movie_id: uuid.UUID, payload: MovieUpdate, db: DbSession, user: OperatorUser
) -> MovieDetailOut:
    movie = authz.assert_can_edit_movie(db, user, movie_id)
    OperatorService(db).update_movie(movie, payload)
    db.commit()
    from app.modules.catalog.router import _detail
    from app.modules.catalog.service import CatalogService

    return _detail(CatalogService(db).get_movie(movie.id))


# =================================================================== shows ==
def _show_admin_out(db, show: Show) -> ShowAdminOut:  # noqa: ANN001
    from sqlalchemy import text

    stats = db.execute(
        text(
            """
            SELECT count(*) FILTER (WHERE status = 'booked')            AS booked,
                   coalesce(sum(price_minor) FILTER (WHERE status='booked'), 0) AS gross
              FROM show_seats WHERE show_id = :s
            """
        ),
        {"s": show.id},
    ).one()
    prices = db.execute(
        select(ShowPrice, SeatCategory)
        .join(SeatCategory, SeatCategory.id == ShowPrice.seat_category_id)
        .where(ShowPrice.show_id == show.id)
        .order_by(SeatCategory.display_order)
    ).all()
    movie = db.get(Movie, show.movie_id)
    screen = db.get(Screen, show.screen_id)
    fmt = db.get(Format, show.format_id)
    from app.modules.catalog.models import Language

    lang = db.get(Language, show.audio_language_id)
    booked = int(stats[0])
    return ShowAdminOut(
        id=show.id,
        movie_id=show.movie_id,
        movie_title=movie.title if movie else "",
        screen_id=show.screen_id,
        screen_name=screen.name if screen else "",
        cinema_id=show.cinema_id,
        format_code=fmt.code if fmt else "",
        audio_language=lang.name if lang else "",
        starts_at=show.starts_at,
        ends_at=show.ends_at,
        show_date=show.show_date,
        status=show.status.value,
        total_seats=show.total_seats,
        available_seats=show.available_seats,
        booked_seats=booked,
        occupancy_percent=(
            round(100.0 * booked / show.total_seats, 1) if show.total_seats else 0.0
        ),
        gross_minor=int(stats[1]),
        prices=[
            {
                "seat_category_id": p.seat_category_id,
                "category": c.name,
                "price_minor": p.price_minor,
            }
            for p, c in prices
        ],
    )


@router.get("/cinemas/{cinema_id}/shows", response_model=list[ShowAdminOut])
def list_shows(
    cinema_id: uuid.UUID,
    db: DbSession,
    user: OperatorUser,
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
) -> list[ShowAdminOut]:
    authz.assert_can_manage_cinema(db, user, cinema_id)
    start = date_from or date.today()
    end = date_to or (start + timedelta(days=7))
    rows = db.execute(
        select(Show)
        .where(
            Show.cinema_id == cinema_id,
            Show.show_date >= start,
            Show.show_date <= end,
        )
        .order_by(Show.starts_at)
    ).scalars()
    return [_show_admin_out(db, s) for s in rows]


@router.post(
    "/cinemas/{cinema_id}/shows",
    response_model=ShowAdminOut,
    status_code=status.HTTP_201_CREATED,
)
def create_show(
    cinema_id: uuid.UUID, payload: ShowCreate, db: DbSession, user: OperatorUser
) -> ShowAdminOut:
    """Schedule one showtime, with a price for every seat tier in that screen."""
    cinema = authz.assert_can_manage_cinema(db, user, cinema_id)
    show = OperatorService(db).create_show(cinema, payload)
    db.commit()
    return _show_admin_out(db, show)


@router.post(
    "/cinemas/{cinema_id}/shows/bulk",
    response_model=BulkShowResult,
    status_code=status.HTTP_201_CREATED,
)
def create_shows_bulk(
    cinema_id: uuid.UUID, payload: BulkShowCreate, db: DbSession, user: OperatorUser
) -> BulkShowResult:
    """Repeat a set of daily slots across a date range.

    Slots that clash with an existing show are reported rather than aborting the
    whole request -- filling a week should not fail because one evening is taken.
    """
    cinema = authz.assert_can_manage_cinema(db, user, cinema_id)
    result = OperatorService(db).create_shows_bulk(cinema, payload)
    db.commit()
    return BulkShowResult(**result)


@router.patch("/shows/{show_id}", response_model=ShowAdminOut)
def update_show(
    show_id: uuid.UUID, payload: ShowUpdate, db: DbSession, user: OperatorUser
) -> ShowAdminOut:
    show = authz.assert_can_manage_show(db, user, show_id)
    data = payload.model_dump(exclude_unset=True)
    if (new_status := data.get("status")) is not None:
        from app.core.enums import ShowStatus

        show.status = ShowStatus(new_status)
    if "sales_open_at" in data:
        show.sales_open_at = data["sales_open_at"]
    db.commit()
    return _show_admin_out(db, show)


@router.put("/shows/{show_id}/prices", response_model=ShowAdminOut)
def set_show_prices(
    show_id: uuid.UUID,
    prices: list[ShowPriceInput],
    db: DbSession,
    user: OperatorUser,
) -> ShowAdminOut:
    """Reprice a show. Seats already sold keep the price the customer paid."""
    show = authz.assert_can_manage_show(db, user, show_id)
    OperatorService(db).set_prices(show, prices)
    db.commit()
    return _show_admin_out(db, show)


@router.post("/shows/{show_id}/cancel", response_model=CancelShowResult)
def cancel_show(
    show_id: uuid.UUID,
    payload: CancelShowRequest,
    db: DbSession,
    user: OperatorUser,
) -> CancelShowResult:
    """Cancel a show, refunding every confirmed booking in full.

    A cancellation is the operator's fault, so the convenience fee a voluntary
    customer cancellation would forfeit is refunded too.
    """
    show = authz.assert_can_manage_show(db, user, show_id)
    result = OperatorService(db).cancel_show(
        show, reason=payload.reason, actor_id=user.id
    )
    db.commit()
    return CancelShowResult(**result)


# ================================================================ bookings ==
@router.get("/cinemas/{cinema_id}/bookings", response_model=Page[OperatorBookingOut])
def cinema_bookings(
    cinema_id: uuid.UUID,
    db: DbSession,
    user: OperatorUser,
    page: Pagination,
    show_id: uuid.UUID | None = None,
    booking_status: str | None = Query(None, alias="status"),
) -> Page[OperatorBookingOut]:
    authz.assert_can_manage_cinema(db, user, cinema_id)
    from app.modules.booking.models import Booking, BookingSeat

    stmt = (
        select(Booking, Show, Movie, Screen)
        .join(Show, Show.id == Booking.show_id)
        .join(Movie, Movie.id == Show.movie_id)
        .join(Screen, Screen.id == Show.screen_id)
        .where(Show.cinema_id == cinema_id)
    )
    if show_id:
        stmt = stmt.where(Booking.show_id == show_id)
    if booking_status:
        stmt = stmt.where(Booking.status == booking_status)

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(
        stmt.order_by(Booking.created_at.desc()).offset(page.offset).limit(page.limit)
    ).all()

    items = []
    for booking, show, movie, screen in rows:
        labels = [
            r[0]
            for r in db.execute(
                select(BookingSeat.seat_label)
                .where(BookingSeat.booking_id == booking.id)
                .order_by(BookingSeat.seat_label)
            )
        ]
        items.append(
            OperatorBookingOut(
                id=booking.id,
                booking_reference=booking.booking_reference,
                status=booking.status.value,
                created_at=booking.created_at,
                contact_email=booking.contact_email,
                seat_count=booking.seat_count,
                seat_labels=labels,
                total_minor=booking.total_minor,
                movie_title=movie.title,
                screen_name=screen.name,
                starts_at=show.starts_at,
                checked_in_seats=booking.checked_in_seats,
            )
        )
    return Page[OperatorBookingOut](
        items=items, total=total, page=page.page, page_size=page.page_size
    )


# ================================================================= reports ==
@router.get("/cinemas/{cinema_id}/reports/revenue", response_model=RevenueReport)
def revenue_report(
    cinema_id: uuid.UUID,
    db: DbSession,
    user: OperatorUser,
    date_from: date = Query(default_factory=lambda: date.today() - timedelta(days=30)),
    date_to: date = Query(default_factory=date.today),
    group_by: str = Query("day"),
) -> RevenueReport:
    cinema = authz.assert_can_manage_cinema(db, user, cinema_id)
    data = ReportService(db).revenue(
        cinema_id=cinema_id, date_from=date_from, date_to=date_to, group_by=group_by
    )
    return RevenueReport(
        cinema_id=cinema.id,
        cinema_name=cinema.name,
        date_from=date_from,
        date_to=date_to,
        group_by=data["group_by"],
        totals=data["totals"],
        rows=data["rows"],
    )


@router.get("/cinemas/{cinema_id}/reports/occupancy", response_model=OccupancyReport)
def occupancy_report(
    cinema_id: uuid.UUID,
    db: DbSession,
    user: OperatorUser,
    date_from: date = Query(default_factory=date.today),
    date_to: date = Query(default_factory=lambda: date.today() + timedelta(days=7)),
) -> OccupancyReport:
    cinema = authz.assert_can_manage_cinema(db, user, cinema_id)
    data = ReportService(db).occupancy(
        cinema_id=cinema_id, date_from=date_from, date_to=date_to
    )
    return OccupancyReport(
        cinema_id=cinema.id,
        cinema_name=cinema.name,
        date_from=date_from,
        date_to=date_to,
        average_occupancy_percent=data["average_occupancy_percent"],
        total_seats=data["total_seats"],
        booked_seats=data["booked_seats"],
        rows=data["rows"],
    )


# ====================================================== platform administration ==
@admin_router.get("/cinemas", response_model=list[CinemaOut])
def all_cinemas(db: DbSession, user: AdminUser) -> list[CinemaOut]:
    rows = db.execute(select(Cinema).order_by(Cinema.name)).scalars()
    return [CinemaOut.model_validate(c) for c in rows]


@admin_router.put("/cinemas/{cinema_id}/operator", response_model=CinemaOut)
def assign_operator(
    cinema_id: uuid.UUID,
    payload: AssignOperatorRequest,
    db: DbSession,
    user: AdminUser,
) -> CinemaOut:
    """Hand a cinema to an operator, or detach it.

    Ownership lives in this one column, so a transfer is a single update rather
    than a migration across screens, shows and seats.
    """
    cinema = db.get(Cinema, cinema_id)
    if cinema is None:
        raise NotFoundError("That cinema does not exist.")
    if payload.operator_user_id is not None:
        operator = db.get(User, payload.operator_user_id)
        if operator is None:
            raise NotFoundError("That user does not exist.")
        if operator.role not in (UserRole.CINEMA_OPERATOR, UserRole.ADMIN):
            raise ValidationError(
                "That user is not a cinema operator. Change their role first.",
                code="NOT_AN_OPERATOR",
            )
    cinema.operator_user_id = payload.operator_user_id
    db.commit()
    return CinemaOut.model_validate(cinema)


@admin_router.get("/users")
def list_users(
    db: DbSession, user: AdminUser, page: Pagination, role: str | None = None
) -> dict:
    stmt = select(User).order_by(User.created_at.desc())
    if role:
        stmt = stmt.where(User.role == role)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.offset(page.offset).limit(page.limit)).scalars().all()
    counts = dict(
        db.execute(
            select(Cinema.operator_user_id, func.count())
            .where(Cinema.operator_user_id.in_([u.id for u in rows] or [None]))
            .group_by(Cinema.operator_user_id)
        ).all()
    )
    return {
        "items": [
            {
                "id": u.id, "email": u.email, "full_name": u.full_name,
                "role": u.role.value, "is_active": u.is_active,
                "created_at": u.created_at,
                "managed_cinemas": int(counts.get(u.id, 0)),
            }
            for u in rows
        ],
        "total": total,
        "page": page.page,
        "page_size": page.page_size,
    }


@admin_router.put("/users/{user_id}/role", response_model=OkResponse)
def change_role(
    user_id: uuid.UUID, payload: ChangeRoleRequest, db: DbSession, user: AdminUser
) -> OkResponse:
    target = db.get(User, user_id)
    if target is None:
        raise NotFoundError("That user does not exist.")
    if target.id == user.id and payload.role != UserRole.ADMIN.value:
        # Removing your own last admin right locks everyone out of the console.
        remaining = db.execute(
            select(func.count())
            .select_from(User)
            .where(User.role == UserRole.ADMIN, User.id != user.id, User.is_active)
        ).scalar_one()
        if remaining == 0:
            raise ConflictError(
                "You are the only administrator. Promote someone else first.",
                code="LAST_ADMIN",
            )
    target.role = UserRole(payload.role)
    db.commit()
    return OkResponse(message=f"{target.email} is now {payload.role}.")


@admin_router.get("/reports/revenue", response_model=RevenueReport)
def platform_revenue(
    db: DbSession,
    user: AdminUser,
    date_from: date = Query(default_factory=lambda: date.today() - timedelta(days=30)),
    date_to: date = Query(default_factory=date.today),
    group_by: str = Query("day"),
) -> RevenueReport:
    """Revenue across every cinema on the platform."""
    data = ReportService(db).revenue(
        cinema_id=None, date_from=date_from, date_to=date_to, group_by=group_by
    )
    return RevenueReport(
        cinema_id=None,
        cinema_name=None,
        date_from=date_from,
        date_to=date_to,
        group_by=data["group_by"],
        totals=data["totals"],
        rows=data["rows"],
    )
