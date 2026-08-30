"""Revenue and occupancy reporting.

Two decisions worth stating, because reports that quietly disagree with the
ledger are worse than no reports:

* **Only confirmed and later states count as revenue.** Draft and
  payment-pending bookings are not money. Cancelled and revoked ones *are*
  counted in gross, with their refunds subtracted, because pretending a
  refunded sale never happened hides the refund rate.
* **Everything is computed from the booking's price snapshot**, never
  recomputed from current prices. Repricing a show next week must not change
  what last week earned.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import ValidationError

GROUPINGS = {
    "day": "b.created_at AT TIME ZONE c.timezone",
    "movie": None,
    "screen": None,
    "show": None,
}

# Statuses that represent a completed sale. Refunds are netted off separately.
SOLD_STATUSES = "('confirmed', 'cancelled', 'refunded', 'revoked')"


class ReportService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def revenue(
        self,
        *,
        cinema_id: uuid.UUID | None,
        date_from: date,
        date_to: date,
        group_by: str = "day",
    ) -> dict:
        if group_by not in GROUPINGS:
            raise ValidationError(
                f"group_by must be one of: {', '.join(GROUPINGS)}.",
                code="BAD_GROUPING",
            )
        if date_to < date_from:
            raise ValidationError("date_to is before date_from.", code="BAD_RANGE")

        bucket = {
            "day": "to_char(s.show_date, 'YYYY-MM-DD')",
            "movie": "m.title",
            "screen": "sc.name",
            "show": "to_char(s.starts_at AT TIME ZONE c.timezone, 'YYYY-MM-DD HH24:MI') "
                    "|| ' · ' || m.title",
        }[group_by]

        sql = f"""
            WITH refunded AS (
                SELECT r.booking_id, sum(r.amount_minor) AS refunded_minor
                  FROM refunds r
                 WHERE r.status = 'succeeded'
                 GROUP BY r.booking_id
            )
            SELECT {bucket}                                   AS bucket,
                   count(DISTINCT b.id)                       AS bookings,
                   coalesce(sum(b.seat_count), 0)             AS tickets,
                   coalesce(sum(b.total_minor), 0)            AS gross_minor,
                   coalesce(sum(b.discount_minor), 0)         AS discount_minor,
                   coalesce(sum(b.convenience_fee_minor), 0)  AS fees_minor,
                   coalesce(sum(b.tax_minor), 0)              AS tax_minor,
                   coalesce(sum(rf.refunded_minor), 0)        AS refunded_minor
              FROM bookings b
              JOIN shows s    ON s.id = b.show_id
              JOIN cinemas c  ON c.id = s.cinema_id
              JOIN movies m   ON m.id = s.movie_id
              JOIN screens sc ON sc.id = s.screen_id
         LEFT JOIN refunded rf ON rf.booking_id = b.id
             WHERE b.status IN {SOLD_STATUSES}
               AND s.show_date BETWEEN :date_from AND :date_to
               AND (CAST(:cinema_id AS uuid) IS NULL
                    OR s.cinema_id = CAST(:cinema_id AS uuid))
             GROUP BY 1
             ORDER BY 1
        """
        rows = self.db.execute(
            text(sql),
            {
                "cinema_id": str(cinema_id) if cinema_id else None,
                "date_from": date_from,
                "date_to": date_to,
            },
        ).mappings().all()

        out = []
        totals = dict.fromkeys(
            ("bookings", "tickets", "gross_minor", "discount_minor",
             "fees_minor", "tax_minor", "refunded_minor"), 0
        )
        for row in rows:
            # Postgres SUM() over integers returns numeric, which arrives as a
            # Decimal. Coerce at the boundary so the response schema and any
            # arithmetic downstream deal in plain ints, like the rest of the
            # money handling does.
            entry = {
                k: (int(v) if k != "bucket" and v is not None else v)
                for k, v in dict(row).items()
            }
            entry["net_minor"] = entry["gross_minor"] - entry["refunded_minor"]
            out.append(entry)
            for key in totals:
                totals[key] += entry[key]
        totals["net_minor"] = totals["gross_minor"] - totals["refunded_minor"]
        totals["bucket"] = "TOTAL"

        return {"rows": out, "totals": totals, "group_by": group_by}

    def occupancy(
        self, *, cinema_id: uuid.UUID, date_from: date, date_to: date
    ) -> dict:
        rows = self.db.execute(
            text(
                """
                SELECT s.id                                     AS show_id,
                       m.title                                  AS movie_title,
                       sc.name                                  AS screen_name,
                       s.starts_at                              AS starts_at,
                       s.total_seats                            AS total_seats,
                       count(*) FILTER (WHERE ss.status = 'booked') AS booked_seats,
                       count(*) FILTER (WHERE ss.status = 'held'
                                        AND ss.hold_expires_at > now()) AS held_seats,
                       coalesce(sum(ss.price_minor)
                                FILTER (WHERE ss.status = 'booked'), 0) AS gross_minor
                  FROM shows s
                  JOIN movies m   ON m.id = s.movie_id
                  JOIN screens sc ON sc.id = s.screen_id
             LEFT JOIN show_seats ss ON ss.show_id = s.id
                 WHERE s.cinema_id = :cinema_id
                   AND s.show_date BETWEEN :date_from AND :date_to
                   AND s.status <> 'cancelled'
                 GROUP BY s.id, m.title, sc.name, s.starts_at, s.total_seats
                 ORDER BY s.starts_at
                """
            ),
            {"cinema_id": cinema_id, "date_from": date_from, "date_to": date_to},
        ).mappings().all()

        out = []
        total_seats = booked_seats = 0
        for row in rows:
            entry = {
                k: (int(v) if isinstance(v, (int, float)) or hasattr(v, "to_integral_value") else v)
                for k, v in dict(row).items()
            }
            capacity = entry["total_seats"] or 0
            entry["occupancy_percent"] = (
                round(100.0 * entry["booked_seats"] / capacity, 1) if capacity else 0.0
            )
            total_seats += capacity
            booked_seats += entry["booked_seats"]
            out.append(entry)

        return {
            "rows": out,
            "total_seats": total_seats,
            "booked_seats": booked_seats,
            "average_occupancy_percent": (
                round(100.0 * booked_seats / total_seats, 1) if total_seats else 0.0
            ),
        }
