"""Seat map and seat-hold endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.core.deps import DbSession, OptionalUser
from app.core.schemas import OkResponse
from app.modules.inventory.schemas import (
    HoldOut,
    HoldSeatsRequest,
    KeepHoldRequest,
    ReleaseHoldRequest,
    SeatMapOut,
)
from app.modules.inventory.service import InventoryService

router = APIRouter(tags=["seats"])


@router.get("/shows/{show_id}/seatmap", response_model=SeatMapOut)
def get_seat_map(show_id: uuid.UUID, db: DbSession) -> SeatMapOut:
    """The seat grid. Expired holds are already reported as available."""
    return InventoryService(db).get_seat_map(show_id)


@router.post("/holds", response_model=HoldOut, status_code=status.HTTP_201_CREATED)
def hold_seats(
    payload: HoldSeatsRequest, db: DbSession, user: OptionalUser
) -> HoldOut:
    """Soft-lock a set of seats. All or nothing; expires after the TTL."""
    hold = InventoryService(db).hold_seats(
        show_id=payload.show_id,
        seat_ids=payload.seat_ids,
        session_key=payload.session_key,
        user_id=user.id if user else None,
    )
    db.commit()
    return hold


@router.get("/holds/{hold_id}", response_model=HoldOut)
def get_hold(hold_id: uuid.UUID, session_key: str, db: DbSession) -> HoldOut:
    service = InventoryService(db)
    return service.describe_hold(service.get_hold(hold_id, session_key=session_key))


@router.post("/holds/{hold_id}/keep", response_model=HoldOut)
def keep_hold(
    hold_id: uuid.UUID, payload: KeepHoldRequest, db: DbSession
) -> HoldOut:
    """Hold these seats for the full window.

    Selecting seats only reserves them briefly -- long enough to reach payment.
    This is the customer deliberately asking for longer, and it also stops the
    hold being dropped if they navigate away from checkout.
    """
    hold = InventoryService(db).keep_hold(hold_id, session_key=payload.session_key)
    db.commit()
    return hold


@router.delete("/holds/{hold_id}", response_model=OkResponse)
def release_hold(
    hold_id: uuid.UUID, payload: ReleaseHoldRequest, db: DbSession
) -> OkResponse:
    """Give the seats back.

    The client sends ``reason="abandoned"`` when the customer simply left the
    checkout page. That is ignored for seats they explicitly asked to keep.
    """
    released = InventoryService(db).release_hold(
        hold_id, session_key=payload.session_key, reason=payload.reason
    )
    db.commit()
    return OkResponse(message=f"Released {released} seat(s).")
