"""Test fixtures.

Tests run against a **real PostgreSQL database**, never SQLite. The whole point
of the seat-hold design is Postgres' row-locking and EvalPlanQual semantics; a
different engine would test something the production code does not do.

Safety: every fixture asserts the target database name ends in ``_test`` so a
misconfigured environment cannot truncate the development data.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from datetime import UTC
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

# Must be set before app.core.config is imported anywhere.
#
# The suite truncates and reseeds its database on every run, so it must never be
# pointed at a real one. Once the app is configured against a managed provider,
# `.env` holds that host -- and inheriting it here would wipe it. So unless the
# developer explicitly opts in with TEST_AGAINST_REMOTE=1, the connection is
# forced back to a local PostgreSQL regardless of what `.env` says.
#
# Keeping tests local is also the right default for a managed plan: the suite
# opens concurrent connections in the seat-race tests, and a small plan's
# connection cap is a shared budget.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("ENABLE_SCHEDULER", "false")

if os.environ.get("TEST_AGAINST_REMOTE") != "1":
    os.environ["POSTGRES_HOST"] = os.environ.get("TEST_POSTGRES_HOST", "localhost")
    os.environ["POSTGRES_PORT"] = os.environ.get("TEST_POSTGRES_PORT", "5432")
    os.environ["POSTGRES_USER"] = os.environ.get("TEST_POSTGRES_USER", "cineai")
    os.environ["POSTGRES_PASSWORD"] = os.environ.get(
        "TEST_POSTGRES_PASSWORD", "cineai_dev_pw"
    )
    os.environ["POSTGRES_SSLMODE"] = os.environ.get("TEST_POSTGRES_SSLMODE", "prefer")
os.environ.setdefault("POSTGRES_DB", "cineai_test")

from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.db import SessionLocal, engine  # noqa: E402
import app.db.models  # noqa: E402,F401  -- registers every mapper


def _assert_test_database() -> None:
    """Two independent guards, because this suite TRUNCATEs every table."""
    if not settings.postgres_db.endswith("_test"):
        raise RuntimeError(
            f"Refusing to run tests against database '{settings.postgres_db}'. "
            "The test database name must end with '_test'."
        )
    local_hosts = {"localhost", "127.0.0.1", "::1"}
    if settings.postgres_host not in local_hosts and os.environ.get(
        "TEST_AGAINST_REMOTE"
    ) != "1":
        raise RuntimeError(
            f"Refusing to run tests against remote host '{settings.postgres_host}'. "
            "The suite truncates and reseeds every table. Set TEST_AGAINST_REMOTE=1 "
            "only if you are certain that database is disposable."
        )


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> Iterator[None]:
    """Bring the test database to head once per test session."""
    _assert_test_database()
    # `sys.executable -m alembic`, not `.venv/bin/alembic`: the console-script
    # path is POSIX-only (Windows puts it in `.venv\Scripts\alembic.exe`), and
    # hardcoding `.venv` assumes the suite is always run by that one venv. Going
    # through the running interpreter is correct on every platform and for any
    # venv, tox environment or CI runner.
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "POSTGRES_DB": settings.postgres_db},
    )
    if result.returncode != 0:
        raise RuntimeError(f"alembic upgrade failed:\n{result.stdout}\n{result.stderr}")
    yield


@pytest.fixture(scope="session")
def seeded(migrated_database: None) -> Iterator[None]:
    """Load the seed catalogue once, committed, for the whole session."""
    from app.db.seed import run_seed

    with SessionLocal() as db:
        # A full rebuild, every session. Two reasons:
        #  * A previous run that died mid-teardown leaves holds and bookings
        #    behind, and the next run then fails for reasons unrelated to the
        #    code under test.
        #  * `TRUNCATE ... CASCADE` on `bookings` reaches `show_seats` through
        #    its FK, so a partial wipe silently destroys the seat inventory.
        #    Rebuilding from scratch is unambiguous, and the seed takes ~2s.
        tables = [
            row[0]
            for row in db.execute(
                text(
                    """
                    SELECT tablename FROM pg_tables
                     WHERE schemaname = 'public'
                       AND tablename <> 'alembic_version'
                    """
                )
            )
        ]
        if tables:
            db.execute(
                text(
                    "TRUNCATE "
                    + ", ".join(f'"{t}"' for t in tables)
                    + " RESTART IDENTITY CASCADE"
                )
            )
        run_seed(db, days=2)
        db.commit()
    yield


@pytest.fixture
def db(seeded: None) -> Iterator[Session]:
    """A session wrapped in a transaction that is always rolled back.

    Gives each test a pristine view of the seeded data without re-seeding, and
    makes writes invisible to the next test. Not usable for concurrency tests --
    those need real commits across real connections, so they manage their own
    sessions.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def open_show_id(db: Session) -> uuid.UUID:
    """An open, bookable show that still has its full seat map."""
    return db.execute(
        text(
            """
            SELECT s.id
              FROM shows s
             WHERE s.status = 'open'
               AND s.sales_close_at > now()
               AND s.available_seats = s.total_seats
             ORDER BY s.starts_at
             LIMIT 1
            """
        )
    ).scalar_one()


@pytest.fixture
def session_key() -> str:
    return uuid.uuid4().hex


@pytest.fixture
def client(seeded: None) -> Iterator["TestClient"]:  # noqa: F821
    """A TestClient against the real app and the real test database.

    Deliberately NOT wired to the rollback `db` fixture: the booking flow spans
    several requests and several committed transactions, and a test that cannot
    commit cannot exercise it. Cleanup is by explicit teardown instead.
    """
    from fastapi.testclient import TestClient

    from app.main import create_app

    # The scheduler would race the test's own expiry assertions.
    os.environ["ENABLE_SCHEDULER"] = "false"
    application = create_app()
    with TestClient(application) as test_client:
        yield test_client


@pytest.fixture
def cleanup_bookings() -> Iterator[list[str]]:
    """Collect show ids to reset once the test is done."""
    show_ids: list[str] = []
    yield show_ids
    if not show_ids:
        return
    with SessionLocal() as db:
        params = {"ids": show_ids}
        # Order matters: refunds and payments hold ON DELETE RESTRICT foreign
        # keys to bookings, which is exactly the protection you want in
        # production (a financial record must not vanish because a booking was
        # deleted) and exactly what teardown has to unwind by hand.
        db.execute(
            text(
                """
                DELETE FROM refunds
                 WHERE booking_id IN (
                       SELECT id FROM bookings
                        WHERE show_id = ANY(CAST(:ids AS uuid[])))
                """
            ),
            params,
        )
        db.execute(
            text(
                """
                DELETE FROM payment_events
                 WHERE payment_id IN (
                       SELECT p.id FROM payments p
                        JOIN bookings b ON b.id = p.booking_id
                       WHERE b.show_id = ANY(CAST(:ids AS uuid[])))
                """
            ),
            params,
        )
        db.execute(
            text(
                """
                DELETE FROM payments
                 WHERE booking_id IN (
                       SELECT id FROM bookings
                        WHERE show_id = ANY(CAST(:ids AS uuid[])))
                """
            ),
            params,
        )
        # Reset the seats to a *coherent* state, not just a null booking_id:
        # ck_show_seats_booked_requires_booking rejects a row that is still
        # 'booked' with no booking, so status and the links have to move
        # together. (The constraint catching this in a test fixture is the
        # constraint doing exactly its job.)
        db.execute(
            text(
                """
                UPDATE show_seats
                   SET status = 'available', booking_id = NULL,
                       hold_id = NULL, hold_expires_at = NULL
                 WHERE show_id = ANY(CAST(:ids AS uuid[]))
                """
            ),
            params,
        )
        db.execute(
            text(
                """
                DELETE FROM bookings
                 WHERE show_id = ANY(CAST(:ids AS uuid[]))
                """
            ),
            params,
        )
        db.execute(
            text(
                """
                UPDATE show_seats
                   SET status='available', hold_id=NULL,
                       hold_expires_at=NULL, booking_id=NULL
                 WHERE show_id = ANY(CAST(:ids AS uuid[]))
                """
            ),
            {"ids": show_ids},
        )
        db.execute(
            text("DELETE FROM seat_holds WHERE show_id = ANY(CAST(:ids AS uuid[]))"),
            {"ids": show_ids},
        )
        db.execute(
            text(
                "UPDATE shows SET available_seats = total_seats "
                "WHERE id = ANY(CAST(:ids AS uuid[]))"
            ),
            {"ids": show_ids},
        )
        db.commit()


@pytest.fixture
def pick_show():
    """Choose a show from the API, with explicit time and capacity requirements.

    Tests must not just take "the first bookable show". The seed schedules from
    *today*, so as the wall clock advances the early slots fall inside the
    booking and cancellation cutoffs -- a test that cancels would pass in the
    morning and fail in the evening. Making the requirement explicit turns a
    time-of-day flake into a stated precondition.
    """
    import datetime

    def _pick(
        client,  # noqa: ANN001
        *,
        min_minutes_ahead: int = 0,
        min_available: int = 20,
        cancellable: bool = False,
    ) -> dict:
        # Derive the requirement from the configured cutoff rather than a magic
        # number, so the test stays correct if the setting changes.
        if cancellable:
            min_minutes_ahead = max(
                min_minutes_ahead, settings.cancellation_cutoff_minutes + 60
            )
        cities = client.get("/api/v1/cities").json()
        movies = client.get(
            "/api/v1/movies",
            params={"city_id": cities[0]["id"], "status": "now_showing"},
        ).json()
        movie_id = movies["items"][0]["id"]

        def _ok(show: dict) -> bool:
            if not show["is_bookable"] or show["available_seats"] < min_available:
                return False
            starts = datetime.datetime.fromisoformat(show["starts_at"])
            ahead = (starts - datetime.datetime.now(UTC)).total_seconds() / 60
            return ahead >= min_minutes_ahead

        board = client.get(
            "/api/v1/showtimes",
            params={"movie_id": movie_id, "city_id": cities[0]["id"]},
        ).json()

        # Today first, then walk forward through the schedule.
        dates = [board["show_date"], *[d for d in board["available_dates"] if d > board["show_date"]]]
        for day in dates:
            if day != board["show_date"]:
                board = client.get(
                    "/api/v1/showtimes",
                    params={"movie_id": movie_id, "city_id": cities[0]["id"], "date": day},
                ).json()
            for cinema in board["cinemas"]:
                for show in cinema["shows"]:
                    if _ok(show):
                        return show

        pytest.skip(
            f"no show at least {min_minutes_ahead} min ahead with "
            f"{min_available}+ seats in the seeded schedule"
        )

    return _pick
