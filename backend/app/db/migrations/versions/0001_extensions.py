"""Extensions and the uuidv7() compatibility shim.

Kept first and separate because every later migration assumes both exist.

Two portability problems are solved here, and both only show up when you move
off a hand-rolled local PostgreSQL:

1. **Extensions.** A managed provider does not give you a superuser. Aiven, RDS
   and friends allow `CREATE EXTENSION` only from an allowlist, and the app role
   may or may not be permitted. `btree_gist` and `pg_trgm` are genuinely
   required (the show-overlap EXCLUDE constraint and the fuzzy title index), so
   failing to create those is fatal and says so. `pgcrypto` is needed only as a
   fallback for the shim below, and `vector` is unused today -- both are
   attempted and skipped with a notice if the provider refuses.

2. **`uuidv7()`.** PostgreSQL 18 ships it natively; 17 and earlier do not, and
   most managed plans are still on 16 or 17. Rather than change every primary
   key, this creates a SQL function with the same name and semantics when the
   server lacks one. It produces a real RFC 9562 v7 UUID -- 48-bit millisecond
   timestamp, version nibble 7, correct variant -- so rows stay time-ordered and
   keep their index locality.

Revision ID: 0001_extensions
Revises:
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0001_extensions"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

# (name, required, purpose)
EXTENSIONS = (
    ("btree_gist", True, "scalar columns inside the shows EXCLUDE constraint"),
    ("pg_trgm", True, "typo-tolerant title and person search"),
    ("pgcrypto", False, "gen_random_uuid() on servers older than PG 13"),
    ("vector", False, "pgvector -- unused today, enabled as an extension point"),
)

# An RFC 9562 v7 UUID built from gen_random_uuid():
#   bytes 0-5  <- the low 6 bytes of the epoch-milliseconds big-endian int64
#   byte  6    <- random low nibble with the version nibble forced to 0111 (7)
#   the rest   <- left as the v4 random bytes, which already carry a valid variant
UUIDV7_SHIM = """
CREATE FUNCTION public.uuidv7() RETURNS uuid
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


def upgrade() -> None:
    conn = op.get_bind()

    for name, required, purpose in EXTENSIONS:
        try:
            # Autocommit: a failed CREATE EXTENSION would otherwise poison the
            # migration's transaction and take the optional ones down with it.
            with conn.begin_nested():
                conn.execute(sa.text(f"CREATE EXTENSION IF NOT EXISTS {name}"))
        except Exception as exc:  # noqa: BLE001
            if required:
                raise RuntimeError(
                    f"Extension '{name}' is required ({purpose}) but could not be "
                    f"created: {exc}\n"
                    f"On a managed provider, enable it from the console or ask an "
                    f"administrator; locally, run scripts/setup_db.sh as a superuser."
                ) from exc
            print(f"  note: optional extension '{name}' unavailable, skipping ({purpose})")

    # uuidv7(): native on PostgreSQL 18+, shimmed below otherwise.
    version_num = int(conn.execute(sa.text("SHOW server_version_num")).scalar_one())
    has_native = conn.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n "
            "ON n.oid = p.pronamespace WHERE p.proname = 'uuidv7')"
        )
    ).scalar_one()

    if has_native:
        print(f"  uuidv7(): native (server_version_num={version_num})")
    else:
        conn.execute(sa.text(UUIDV7_SHIM))
        sample = conn.execute(sa.text("SELECT public.uuidv7()::text")).scalar_one()
        # Fail loudly rather than fill a primary key with malformed UUIDs.
        if sample[14] != "7" or sample[19] not in "89ab":
            raise RuntimeError(f"uuidv7() shim produced a malformed UUID: {sample}")
        print(f"  uuidv7(): shim installed (server_version_num={version_num}) -> {sample}")


def downgrade() -> None:
    # Dropping an extension would cascade away every column using its types, and
    # dropping uuidv7() would break every table default. Deliberately a no-op.
    pass
