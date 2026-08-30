"""Report what the app is actually connected to, and gate destructive commands.

    python scripts_dbcheck.py                 # print connection facts
    python scripts_dbcheck.py --assert-local  # exit 1 unless the host is local

The second form guards `make reset`, which drops databases. Once `.env` points
at a managed provider, a reset aimed at the wrong host is unrecoverable.
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")

from app.core.config import settings  # noqa: E402

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def assert_local() -> int:
    if settings.postgres_host in LOCAL_HOSTS:
        return 0
    print(
        f"REFUSING: POSTGRES_HOST is {settings.postgres_host!r}. "
        "This command drops databases and is local-only.",
        file=sys.stderr,
    )
    return 1


def report() -> int:
    from sqlalchemy.exc import SQLAlchemyError

    from app.core.db import healthcheck

    try:
        info = healthcheck()
    except SQLAlchemyError as exc:
        print(f"  host       : {settings.database_host_summary}")
        print(f"  status     : UNREACHABLE\n\n  {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    native = info["server_version_num"] >= 180_000
    required = {"btree_gist", "pg_trgm"}
    missing = sorted(required - set(info["extensions"]))

    print(f"  host       : {info['host']}")
    print(f"  postgres   : {info['server_version']}")
    print(f"  TLS        : {'yes' if info['ssl'] else 'no'}")
    print(f"  extensions : {', '.join(info['extensions']) or '(none)'}")
    print(f"  uuidv7     : {'native' if native else 'shim from migration 0001'}")
    print(f"  pool max   : {settings.db_pool_size + settings.db_max_overflow} connections")

    if missing:
        print(f"\n  MISSING required extensions: {', '.join(missing)}", file=sys.stderr)
        return 1
    if not info["ssl"] and settings.postgres_host not in LOCAL_HOSTS:
        print("\n  WARNING: connected to a remote host without TLS.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(assert_local() if "--assert-local" in sys.argv else report())
