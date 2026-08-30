"""Venue reads."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.modules.fnb.models import FnbItem
from app.modules.venues.models import Cinema, City, Screen


class VenueService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_cities(self) -> list[City]:
        return list(
            self.db.execute(
                select(City)
                .where(City.is_active)
                .order_by(City.display_order, City.name)
            ).scalars()
        )

    def get_city_by_slug(self, slug: str) -> City:
        city = self.db.execute(select(City).where(City.slug == slug)).scalar_one_or_none()
        if city is None:
            raise NotFoundError("That city does not exist.")
        return city

    def list_cinemas(self, city_id: uuid.UUID | None = None) -> list[Cinema]:
        stmt = select(Cinema).where(Cinema.is_active)
        if city_id:
            stmt = stmt.where(Cinema.city_id == city_id)
        return list(self.db.execute(stmt.order_by(Cinema.name)).scalars())

    def get_cinema(self, cinema_id: uuid.UUID) -> Cinema:
        cinema = self.db.get(Cinema, cinema_id)
        if cinema is None:
            raise NotFoundError("That cinema does not exist.")
        return cinema

    def list_screens(self, cinema_id: uuid.UUID) -> list[Screen]:
        return list(
            self.db.execute(
                select(Screen)
                .where(Screen.cinema_id == cinema_id, Screen.is_active)
                .order_by(Screen.screen_number)
            ).scalars()
        )

    def list_fnb(self, cinema_id: uuid.UUID) -> list[FnbItem]:
        return list(
            self.db.execute(
                select(FnbItem)
                .where(FnbItem.cinema_id == cinema_id, FnbItem.is_available)
                .order_by(FnbItem.display_order, FnbItem.name)
            ).scalars()
        )
