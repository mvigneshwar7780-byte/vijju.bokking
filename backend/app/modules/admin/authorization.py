"""Who may manage what.

The rule, stated once so it cannot drift between endpoints:

* A **platform administrator** may manage anything.
* A **cinema operator** may manage a cinema they own, and everything reachable
  *through* it -- screens, seat categories, seats, shows, prices, bookings.
* Nobody else may manage anything.

Ownership lives in exactly one place: ``cinemas.operator_user_id``. Screens,
shows and seats deliberately carry no owner column of their own; they resolve
upward to a cinema. That is what keeps the entities related without being
tightly coupled -- transferring a cinema to a new operator is one UPDATE, not a
migration across five tables.

Every operator endpoint routes through one of these helpers. An endpoint that
loads a row without calling one is a bug, and
``tests/integration/test_operator_authorization.py`` enumerates the routes to
catch it.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import UserRole
from app.core.errors import NotFoundError, PermissionDeniedError
from app.modules.identity.models import User
from app.modules.scheduling.models import Show
from app.modules.venues.models import Cinema, Screen, SeatCategory


def is_platform_admin(user: User) -> bool:
    return user.role == UserRole.ADMIN


def visible_cinema_ids(db: Session, user: User) -> list[uuid.UUID] | None:
    """Cinema ids this user may manage. ``None`` means "no restriction"."""
    if is_platform_admin(user):
        return None
    return list(
        db.execute(
            select(Cinema.id).where(Cinema.operator_user_id == user.id)
        ).scalars()
    )


def assert_can_manage_cinema(db: Session, user: User, cinema_id: uuid.UUID) -> Cinema:
    cinema = db.get(Cinema, cinema_id)
    if cinema is None:
        raise NotFoundError("That cinema does not exist.")
    if is_platform_admin(user):
        return cinema
    if cinema.operator_user_id != user.id:
        # Deliberately the same message whether the cinema exists or belongs to
        # someone else, so this cannot be used to enumerate other operators'
        # cinemas.
        raise PermissionDeniedError("You do not manage that cinema.")
    return cinema


def assert_can_manage_screen(db: Session, user: User, screen_id: uuid.UUID) -> Screen:
    screen = db.get(Screen, screen_id)
    if screen is None:
        raise NotFoundError("That screen does not exist.")
    assert_can_manage_cinema(db, user, screen.cinema_id)
    return screen


def assert_can_manage_show(db: Session, user: User, show_id: uuid.UUID) -> Show:
    show = db.get(Show, show_id)
    if show is None:
        raise NotFoundError("That show does not exist.")
    assert_can_manage_cinema(db, user, show.cinema_id)
    return show


def assert_can_manage_seat_category(
    db: Session, user: User, category_id: uuid.UUID
) -> SeatCategory:
    category = db.get(SeatCategory, category_id)
    if category is None:
        raise NotFoundError("That seat category does not exist.")
    assert_can_manage_cinema(db, user, category.cinema_id)
    return category


def assert_can_edit_movie(db: Session, user: User, movie_id: uuid.UUID):  # noqa: ANN201
    """Movies are a shared catalogue, so editing rights are narrower.

    An administrator may edit any title. An operator may edit only titles they
    added -- otherwise one operator could rewrite the synopsis, certification or
    runtime of a film every other cinema is also showing.
    """
    from app.modules.catalog.models import Movie

    movie = db.get(Movie, movie_id)
    if movie is None:
        raise NotFoundError("That movie does not exist.")
    if is_platform_admin(user):
        return movie
    if movie.created_by_user_id != user.id:
        raise PermissionDeniedError(
            "That title was added by someone else. Ask an administrator to "
            "change it, or add your own entry."
        )
    return movie
