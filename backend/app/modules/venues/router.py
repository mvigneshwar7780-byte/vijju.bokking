"""City, cinema and F&B endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.core.deps import DbSession
from app.modules.venues.schemas import CinemaOut, CityOut, FnbItemOut, ScreenOut
from app.modules.venues.service import VenueService

router = APIRouter(tags=["venues"])


@router.get("/cities", response_model=list[CityOut])
def list_cities(db: DbSession) -> list[CityOut]:
    return [CityOut.model_validate(c) for c in VenueService(db).list_cities()]


@router.get("/cities/{slug}", response_model=CityOut)
def get_city(slug: str, db: DbSession) -> CityOut:
    return CityOut.model_validate(VenueService(db).get_city_by_slug(slug))


@router.get("/cinemas", response_model=list[CinemaOut])
def list_cinemas(db: DbSession, city_id: uuid.UUID | None = None) -> list[CinemaOut]:
    return [CinemaOut.model_validate(c) for c in VenueService(db).list_cinemas(city_id)]


@router.get("/cinemas/{cinema_id}", response_model=CinemaOut)
def get_cinema(cinema_id: uuid.UUID, db: DbSession) -> CinemaOut:
    return CinemaOut.model_validate(VenueService(db).get_cinema(cinema_id))


@router.get("/cinemas/{cinema_id}/screens", response_model=list[ScreenOut])
def list_screens(cinema_id: uuid.UUID, db: DbSession) -> list[ScreenOut]:
    return [ScreenOut.model_validate(s) for s in VenueService(db).list_screens(cinema_id)]


@router.get("/cinemas/{cinema_id}/fnb", response_model=list[FnbItemOut])
def list_fnb(cinema_id: uuid.UUID, db: DbSession) -> list[FnbItemOut]:
    return [FnbItemOut.model_validate(i) for i in VenueService(db).list_fnb(cinema_id)]
