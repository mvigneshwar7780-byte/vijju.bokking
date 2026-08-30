"""Shared Pydantic building blocks: base model, pagination, money."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, computed_field

T = TypeVar("T")


class APIModel(BaseModel):
    """Base for every response schema.

    ``from_attributes`` lets a router return an ORM object directly, and
    ``populate_by_name`` keeps snake_case internally while allowing aliases.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class PageParams(BaseModel):
    page: Annotated[int, Field(ge=1)] = 1
    page_size: Annotated[int, Field(ge=1, le=100)] = 20

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


class Page(APIModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_pages(self) -> int:
        if self.page_size == 0:
            return 0
        return -(-self.total // self.page_size)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_next(self) -> bool:
        return self.page * self.page_size < self.total


class Money(APIModel):
    """Money crosses the wire in *both* forms.

    ``minor`` (paise) is the authoritative integer the server computes with;
    ``amount`` is the decimal the UI renders. Clients must never do arithmetic
    on ``amount`` and send it back -- every price is recomputed server-side.
    """

    minor: int
    currency: str = "INR"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def amount(self) -> Decimal:
        return (Decimal(self.minor) / Decimal(100)).quantize(Decimal("0.01"))

    @classmethod
    def of(cls, minor: int, currency: str = "INR") -> "Money":
        return cls(minor=minor, currency=currency)


class OkResponse(APIModel):
    ok: bool = True
    message: str | None = None
