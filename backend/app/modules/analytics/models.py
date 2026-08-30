"""Analytics & audit.

``domain_events`` is an append-only log of things that happened. It is not the
source of truth (the tables are), but it is what makes "why is this booking in
this state?" answerable six months later, and it is the substrate the AI
analytics assistant reads.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UUIDPrimaryKeyMixin


class DomainEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "domain_events"

    aggregate_type: Mapped[str] = mapped_column(String(40), nullable=False)  # booking, show
    aggregate_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)  # booking.confirmed
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False, server_default="user")
    request_id: Mapped[str | None] = mapped_column(String(64))
    ip_address: Mapped[str | None] = mapped_column(INET)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_domain_events_aggregate_type_aggregate_id", "aggregate_type", "aggregate_id"),
        Index("ix_domain_events_event_type_created_at", "event_type", "created_at"),
        Index("ix_domain_events_created_at", "created_at"),
    )
