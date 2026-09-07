"""Scope the show slot uniqueness to non-cancelled shows.

``uq_shows_screen_id_starts_at`` was an unconditional UNIQUE on
``(screen_id, starts_at)``. A cancelled show therefore kept its slot reserved
for ever: an operator who cancelled Saturday 18:00 on Screen 2 could never
schedule that time again, and re-seeding after retiring a catalogue produced no
shows at all because every candidate slot collided with a dead row.

It also contradicted ``ex_shows_screen_no_overlap``, which is already scoped
``WHERE status <> 'cancelled'`` and whose comment claims a cancellation frees
the slot immediately. Now both agree.

This is the same defect, in a different table, as the plain UNIQUE on
``booking_seats(show_seat_id)`` that made a cancelled booking's seat
permanently unsellable.

Revision ID: 0006_partial_show_slot_unique
Revises: 0005_kept_holds
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_partial_show_slot_unique"
down_revision = "0005_kept_holds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Declared as a UniqueConstraint originally, so it exists as a constraint
    # rather than a bare index -- drop it as one.
    op.execute("ALTER TABLE shows DROP CONSTRAINT IF EXISTS uq_shows_screen_id_starts_at")
    op.execute("DROP INDEX IF EXISTS uq_shows_screen_id_starts_at")
    op.create_index(
        "uq_shows_screen_id_starts_at",
        "shows",
        ["screen_id", "starts_at"],
        unique=True,
        postgresql_where=sa.text("status <> 'cancelled'"),
    )


def downgrade() -> None:
    # Reverting can fail by design: if two shows now share a slot because one
    # was cancelled, an unconditional UNIQUE cannot be rebuilt without deleting
    # data. Fail loudly rather than silently discarding a row.
    op.drop_index("uq_shows_screen_id_starts_at", table_name="shows")
    op.create_unique_constraint(
        "uq_shows_screen_id_starts_at", "shows", ["screen_id", "starts_at"]
    )
