"""Entry point: python -m scripts_seed  (wired to `make seed`)."""
from __future__ import annotations

import sys
import time

sys.path.insert(0, ".")

from app.core.db import SessionLocal          # noqa: E402
from app.core.logging import configure_logging  # noqa: E402
from app.db.seed import run_seed              # noqa: E402


def main() -> int:
    configure_logging(level="INFO")
    started = time.perf_counter()
    with SessionLocal() as db:
        stats = run_seed(db)
        db.commit()
    elapsed = time.perf_counter() - started
    print(f"\nSeed complete in {elapsed:.1f}s")
    for key in sorted(stats):
        print(f"  {key:>12}: {stats[key]:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
