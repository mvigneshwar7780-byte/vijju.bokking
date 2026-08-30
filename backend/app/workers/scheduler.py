"""Background jobs.

APScheduler in-process rather than Celery: no broker, no extra container, and
for a single-node learning app the jobs are all short and idempotent. The
boundary is kept clean -- each job is a plain function taking a Session -- so
moving to a real worker later means changing the trigger, not the logic.

Every job must be safe to run concurrently with itself and with live traffic.
That is why the hold sweeper uses ``FOR UPDATE SKIP LOCKED``.
"""

from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.logging import get_logger

logger = get_logger(__name__)


def sweep_expired_holds() -> None:
    from app.modules.inventory.repository import InventoryRepository

    with SessionLocal() as db:
        repo = InventoryRepository(db)
        result = repo.sweep_expired_holds()
        show_ids = repo.shows_needing_recount()
        for show_id in show_ids:
            repo.refresh_available_count(show_id)
        db.commit()
    if result["holds_expired"] or show_ids:
        logger.info(
            "hold_sweep",
            holds_expired=result["holds_expired"],
            seats_released=result["seats_released"],
            counters_fixed=len(show_ids),
        )


def expire_stale_bookings() -> None:
    """Move drafts whose hold has lapsed into a terminal state."""
    from datetime import UTC, datetime

    from sqlalchemy import select

    from app.core.enums import BookingStatus
    from app.modules.booking.models import Booking
    from app.modules.booking.service import BookingService

    with SessionLocal() as db:
        stale = list(
            db.execute(
                select(Booking)
                .where(
                    Booking.status.in_([BookingStatus.DRAFT, BookingStatus.PAYMENT_PENDING]),
                    Booking.payment_deadline_at.is_not(None),
                    Booking.payment_deadline_at < datetime.now(UTC),
                )
                .limit(200)
            ).scalars()
        )
        if not stale:
            return
        service = BookingService(db)
        for booking in stale:
            service.expire_booking(booking)
        db.commit()
    logger.info("stale_bookings_expired", count=len(stale))


def reconcile_payments() -> None:
    """Resolve payments whose outcome never reached us.

    Missing webhooks are normal in production, not exceptional. Without this
    job a dropped delivery leaves a customer holding seats against a payment
    that settled -- or failed -- some time ago.
    """
    from app.modules.payments.service import PaymentService

    with SessionLocal() as db:
        try:
            counts = PaymentService(db).reconcile_pending_payments()
        except Exception as exc:  # noqa: BLE001
            logger.error("reconciliation_job_failed", error=str(exc))
            return
        db.commit()
    if counts["checked"]:
        logger.info("payment_reconciliation_sweep", **counts)


def start_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        sweep_expired_holds,
        "interval",
        seconds=settings.hold_sweeper_interval_seconds,
        id="sweep_expired_holds",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        expire_stale_bookings,
        "interval",
        seconds=max(settings.hold_sweeper_interval_seconds * 2, 120),
        id="expire_stale_bookings",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        reconcile_payments,
        "interval",
        seconds=max(settings.hold_sweeper_interval_seconds * 5, 300),
        id="reconcile_payments",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    logger.info("scheduler_started", jobs=[j.id for j in scheduler.get_jobs()])
    return scheduler
