"""Database engine, session factory and the declarative base.

Session policy
--------------
* One SQLAlchemy ``Session`` per HTTP request, supplied by the ``get_db``
  dependency. The request handler owns the transaction boundary.
* Services never create their own sessions -- they receive one. That keeps a
  whole request atomic and makes the seat-hold logic testable.
* ``expire_on_commit=False`` so response serialisation after a commit does not
  trigger a surprise re-SELECT.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, MetaData, create_engine, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.core.config import settings

# Deterministic constraint naming: Alembic autogenerate can then produce stable,
# reversible migrations instead of relying on Postgres-assigned names.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

engine = create_engine(
    settings.database_url,
    echo=settings.db_echo,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    # A managed database sits behind a proxy that closes idle connections and a
    # network that can drop them. pool_pre_ping costs one round-trip per
    # checkout and turns "server closed the connection unexpectedly" into a
    # transparent reconnect; pool_recycle retires connections before the
    # provider does.
    pool_pre_ping=True,
    pool_recycle=settings.db_pool_recycle_seconds,
    connect_args=settings.db_connect_args,
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    future=True,
)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _new_uuid7() -> uuid.UUID:
    """A time-ordered UUIDv7, generated client-side.

    Python 3.14 added ``uuid.uuid7``; the fallback keeps older interpreters
    working by assembling one by hand -- 48-bit millisecond timestamp, version
    7, RFC 9562 variant.
    """
    generator = getattr(uuid, "uuid7", None)
    if generator is not None:
        return generator()

    import os
    import time

    ms = int(time.time() * 1000) & ((1 << 48) - 1)
    rand = int.from_bytes(os.urandom(10), "big")
    value = (ms << 80) | (0x7 << 76) | ((rand >> 6) & ((1 << 74) - 1))
    value = (value & ~(0b11 << 62)) | (0b10 << 62)  # RFC 9562 variant
    return uuid.UUID(int=value)


class UUIDPrimaryKeyMixin:
    """Time-ordered UUID primary key.

    UUIDv7 keeps the index locality of a bigint sequence -- values sort by
    creation time, so inserts land at the right edge of the B-tree -- while
    staying globally unique and non-guessable, which is what makes booking ids
    safe to expose in URLs.

    The value is generated **client-side**, with the server default kept only
    for raw-SQL inserts that bypass the ORM. That split matters over a network:
    with only a server default, SQLAlchemy has to ask the database for each
    generated key, which forces one round trip per row. Generating it here lets
    it batch hundreds of rows into a single statement -- the difference between
    a seed that takes seconds and one that takes minutes against a managed
    database.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=_new_uuid7,
        server_default=text("uuidv7()"),
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def healthcheck() -> dict[str, Any]:
    with engine.connect() as conn:
        version = conn.execute(text("show server_version")).scalar_one()
        version_num = int(conn.execute(text("show server_version_num")).scalar_one())
        extensions = [
            row[0]
            for row in conn.execute(
                text("select extname from pg_extension order by extname")
            )
        ]
        # Whether the server encrypted this connection -- the one fact that
        # tells you a managed-database migration actually took effect.
        ssl = conn.execute(
            text(
                "select coalesce((select ssl from pg_stat_ssl "
                "where pid = pg_backend_pid()), false)"
            )
        ).scalar_one()
    return {
        "server_version": version,
        "server_version_num": version_num,
        "extensions": extensions,
        "ssl": bool(ssl),
        "host": settings.database_host_summary,
    }
