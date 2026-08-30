"""Venue contracts."""

from __future__ import annotations

import uuid

from app.core.schemas import APIModel


class CityOut(APIModel):
    id: uuid.UUID
    name: str
    slug: str
    state: str | None
    timezone: str
    latitude: float | None
    longitude: float | None


class CinemaOut(APIModel):
    id: uuid.UUID
    name: str
    slug: str
    brand: str | None
    address_line: str
    locality: str | None
    city_id: uuid.UUID
    amenities: list
    latitude: float | None
    longitude: float | None


class ScreenOut(APIModel):
    id: uuid.UUID
    name: str
    screen_number: int
    supported_formats: list
    sound_system: str | None
    total_seats: int


class FnbItemOut(APIModel):
    id: uuid.UUID
    name: str
    description: str | None
    category: str
    price_minor: int
    image_url: str | None
    is_vegetarian: bool
