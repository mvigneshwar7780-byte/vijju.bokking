"""Add the 'cancelled' payment status.

A customer who closes the checkout tab has not been *declined* -- nothing about
their card or bank said no. Collapsing that into `failed` loses the distinction
that matters both for what the UI tells them ("you cancelled" vs "your bank
declined") and for any read of decline rates.

Revision ID: 0003_payment_cancelled
Revises: 0002_initial_schema
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003_payment_cancelled"
down_revision: str | None = "0002_initial_schema"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block on its own
    # in older PostgreSQL; from 12 onward it can, as long as the new value is
    # not used in the same transaction. Adding it here and using it in later
    # migrations/queries is safe.
    op.execute("ALTER TYPE payment_status ADD VALUE IF NOT EXISTS 'cancelled'")


def downgrade() -> None:
    # PostgreSQL cannot remove a value from an enum. Reversing this would mean
    # recreating the type and rewriting every dependent column -- far more
    # destructive than the change itself.
    pass
