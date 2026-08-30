"""The uuidv7() shim must be a real RFC 9562 v7 UUID.

PostgreSQL 18 ships `uuidv7()`; 17 and earlier do not, and most managed plans
are still on 16 or 17. The schema uses it as the default for every primary key,
so on an older server the shim in migration 0001 *is* the id generator.

These tests exercise the shim SQL directly rather than whatever the local
server happens to provide, so they are meaningful on PG 18 (where the shim is
not installed) as well as on older servers.
"""

from __future__ import annotations

import re
import time

from sqlalchemy import text

from app.db.migrations.versions import __name__ as _versions_pkg  # noqa: F401

# The same body the migration installs, created in a temp schema so the test
# never shadows a native implementation.
SHIM_SQL = """
CREATE FUNCTION pg_temp.uuidv7_under_test() RETURNS uuid
LANGUAGE sql VOLATILE PARALLEL SAFE AS $fn$
  SELECT encode(
    overlay(
      overlay(uuid_send(gen_random_uuid())
              PLACING substring(
                  int8send((extract(epoch FROM clock_timestamp()) * 1000)::bigint)
                  FROM 3)
              FROM 1 FOR 6)
      PLACING set_byte('\\x00'::bytea, 0,
                       (get_byte(uuid_send(gen_random_uuid()), 6) & 15) | 112)
      FROM 7 FOR 1),
    'hex')::uuid;
$fn$;
"""

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


def _body(sql: str) -> str:
    """The SQL between the $fn$ markers, whitespace-normalised."""
    inner = sql.split("$fn$")[1]
    return " ".join(inner.split())


def test_shim_matches_the_migration_source() -> None:
    """Guard against the tested copy and the shipped copy drifting apart.

    Only the function *body* is compared -- the migration installs it as
    `public.uuidv7` and the test as `pg_temp.uuidv7_under_test`, which is the
    point: the test must not shadow a native implementation.
    """
    import importlib.util
    import pathlib as _pathlib

    from app.db.migrations.versions import __path__ as versions_path

    # Import the migration module and read the constant, rather than diffing
    # file text: the source contains an escaped `\\x00` that becomes `\x00`
    # at runtime, so a text-vs-value comparison would always disagree.
    path = _pathlib.Path(versions_path[0], "0001_extensions.py")
    spec = importlib.util.spec_from_file_location("_mig_0001", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]

    assert _body(module.UUIDV7_SHIM) == _body(SHIM_SQL), (
        "the shim in the migration and the shim under test have diverged"
    )


def test_shim_produces_wellformed_v7_uuids(db) -> None:  # noqa: ANN001
    db.execute(text(SHIM_SQL))
    values = [
        db.execute(text("SELECT pg_temp.uuidv7_under_test()::text")).scalar_one()
        for _ in range(200)
    ]
    assert len(set(values)) == len(values), "the shim produced a duplicate"
    bad = [v for v in values if not UUID_RE.match(v)]
    assert not bad, f"malformed v7 UUIDs (version or variant nibble wrong): {bad[:3]}"


def test_shim_is_time_ordered_across_milliseconds(db) -> None:  # noqa: ANN001
    """Index locality is the whole reason for v7 over v4.

    Ordering is only guaranteed *between* milliseconds -- inside a single
    millisecond the low bits are random, which is by design.
    """
    db.execute(text(SHIM_SQL))
    values = []
    for _ in range(12):
        values.append(db.execute(text("SELECT pg_temp.uuidv7_under_test()::text")).scalar_one())
        time.sleep(0.004)
    assert values == sorted(values), "shim UUIDs are not time-ordered"


def test_shim_timestamp_tracks_wall_clock(db) -> None:  # noqa: ANN001
    """The first 48 bits must actually be epoch milliseconds, not noise."""
    db.execute(text(SHIM_SQL))
    before = time.time() * 1000
    value = db.execute(text("SELECT pg_temp.uuidv7_under_test()::text")).scalar_one()
    after = time.time() * 1000

    encoded_ms = int(value[:8] + value[9:13], 16)
    # Generous window: the DB clock and the client clock are not the same clock.
    assert before - 60_000 <= encoded_ms <= after + 60_000, (
        f"embedded timestamp {encoded_ms} is not near wall clock "
        f"[{before:.0f}, {after:.0f}]"
    )
