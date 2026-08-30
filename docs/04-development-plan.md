# Development plan

Phases are ordered so that **something works end to end from Phase 1** and each
later phase adds one concern. Phases 1–5 are built and tested; 6 onward are the
roadmap.

Each phase names its acceptance test — the thing that proves it works, not the
thing that proves it compiles.

---

## ✅ Phase 1 — Foundations and a runnable slice

**Goal** — a request can reach the database and come back.

Config (`pydantic-settings`), SQLAlchemy engine and session policy, structured
logging with request ids, the error envelope, Argon2 + JWT security, Alembic
wired to the app's own settings.

**Acceptance** — `GET /health` returns the live PostgreSQL version and the
installed extensions.

---

## ✅ Phase 2 — Domain model and demo data

**Goal** — the whole domain exists as tables, with real data in them.

32 tables across 11 modules. Two migrations: extensions, then the schema.
An idempotent seed producing 3 cities, 6 cinemas, 12 screens, 1,680 seats,
10 films, 288 shows and 40,320 seat rows.

**Acceptance** — `make reset` rebuilds from nothing and seeds in under 5s;
`\d show_seats` shows the anti-double-booking constraint and all three state
CHECKs.

---

## ✅ Phase 3 — Inventory and the concurrency core

**Goal** — two people can never be sold the same seat.

The seat map read (with lazy expiry), the atomic conditional claim, hold
lifecycle (create / extend / release / confirm), the per-show advisory lock, the
counter recount, the expiry sweeper, and the seat-selection rules
(max per booking, seats belong to the show, no orphan single seat).

**Acceptance** —
[`tests/concurrency/`](../backend/tests/concurrency/): 20 threads racing for one
seat produce exactly one winner and 19 clean `SEAT_UNAVAILABLE`s; overlapping
seat sets never partially allocate; the cached counter matches reality under
contention. **Every test runs twice — once with the advisory lock disabled** —
and removing the `WHERE` predicate makes four of five fail.

---

## ✅ Phase 4 — Booking, pricing and payments

**Goal** — a seat hold becomes a paid, ticketed booking, and money is never
taken for a seat that cannot be delivered.

Pure-function price calculator (integer paise, banded GST, capped fee), offer
validation and redemption, booking orchestration with `Idempotency-Key`, a
swappable gateway interface, a mock PSP with signed webhooks and configurable
latency/failure, the confirm-or-refund path, cancellation with a refund quote,
and signed QR tickets.

**Acceptance** —
[`test_booking_flow.py`](../backend/tests/integration/test_booking_flow.py):
register → browse → showtimes → seat map → hold → quote with an offer → book →
pay → signed webhook → confirmed ticket → cancel → refund, with the seat count
returning to its original value. Plus: a replayed webhook is a no-op, a forged
signature is rejected, a declined payment releases the seats immediately, and a
retried POST with the same idempotency key returns the same booking.

---

## ✅ Phase 5 — Web client

**Goal** — the funnel is usable in a browser.

React 19 + TypeScript + Vite + Tailwind v4. City picker, now-showing grid with
search, film detail, date-and-cinema showtime board with availability bands, the
seat map (aisle-aware grid, category legend, live status), a server-anchored
hold countdown, checkout with offers and a live price breakdown, a simulated
payment page, the ticket, and booking history with cancellation.

**Acceptance** — `make dev`, then the whole journey completes in the browser;
the API is reached through the Vite proxy, so there is no CORS in development.

---

## Phase 6 — Operator console *(next)*

**Goal** — cinemas can be run without `psql`.

- Screen designer: define rows, seat numbering, aisles, categories.
- Show scheduler with conflict feedback (the `EXCLUDE` constraint already
  refuses overlaps — this surfaces it as a usable error).
- Per-show price cards; block seats for maintenance.
- Show cancellation triggering bulk refunds and seat release.
- Settlement view: bookings, refunds and net per cinema per day.

**Acceptance** — an operator creates a screen, schedules a week, and a customer
books into it without any SQL being written by hand. Scheduling an overlapping
show shows a clear message rather than a 500.

**Rough size** — one focused week. Mostly forms; the hard constraints exist.

---

## Phase 7 — Hardening

- **Guest checkout** with account claim (`bookings.user_id` is already nullable).
- **Gate scanning**: `POST /tickets/scan` verifying the HMAC and enforcing
  single use per seat.
- **Email delivery**: drain the `notifications` queue for real (currently rows
  are written and left).
- **Reconciliation job**: walk `stale_pending_payments()`, ask the gateway what
  actually happened, and settle the difference. Missing webhooks are normal in
  production.
- **Show cancellation** path end to end.
- **Move the scheduler out of process** — with N uvicorn workers you get N
  schedulers. The jobs are already idempotent and use `SKIP LOCKED`, so this is
  a deployment change, not a logic change.

**Acceptance** — kill the API mid-payment; reconciliation resolves the booking
to a correct terminal state without human intervention.

---

## Phase 8 — Real payments

Swap `MockGateway` for Razorpay or Stripe. The interface
([`payments/gateways/base.py`](../backend/app/modules/payments/gateways/base.py))
already models the real shape: server-side order creation, idempotency keys,
signature-verified webhooks, and refunds. This should be one new class plus a
settings change.

**Acceptance** — a sandbox transaction confirms a booking through the same
webhook handler the mock uses today.

---

## Phase 9 — Scale and observability

Metrics on the funnel (hold → book → pay conversion, hold expiry rate, seat
contention), tracing, a read replica for the catalogue, Redis for rate limiting
and seat-map caching, `bookings` partitioning.

---

## Extension points left deliberately open

The schema and module layout leave clean seams where they were most likely to be
wanted:

| Seam | Where |
|---|---|
| `pgvector` | Enabled in migration `0001`, unused. No `embeddings` table — that is a design decision to make, not inherit. |
| Descriptive facets | `movies.ai_attributes` (jsonb) already carries mood / themes / pace / ending, populated by the seed and used by the catalogue. |
| Generated text | `movies.ai_summary`, `reviews.ai_aspects`, `reviews.ai_sentiment` exist and are nullable — writable without a migration. |
| Dynamic pricing | `show_prices.ai_suggested_price_minor` sits beside the operator's price, so a model's suggestion can be compared against the rule-based baseline rather than replacing it silently. |
| Provider seams | `payments/gateways/base.py` is the worked example of how an external provider is isolated behind an interface. |

The rule-based pricing in
[`db/seed/loader.py::_price_show`](../backend/app/db/seed/loader.py) is the
honest baseline any smarter pricing has to beat.
