# Architecture

## 1. The shape: a modular monolith

One deployable, hard internal boundaries.

Microservices for a single-developer project buy distributed-systems problems
and pay for them with nothing — you cannot even hold a seat and record a booking
in one transaction. A monolith with **enforced module boundaries** gives the
same conceptual decomposition, keeps transactions local, and leaves every module
extractable later because the seams are already drawn.

```
                        ┌──────────────────────────┐
   Browser ── HTTP ────▶ │  FastAPI app             │
                        │                          │
                        │  routers  (HTTP only)    │
                        │     ↓                    │
                        │  services (all policy)   │
                        │     ↓                    │
                        │  repositories (all SQL)  │
                        │     ↓                    │
                        │  models   (ORM mapping)  │
                        └────────────┬─────────────┘
                                     │
                        ┌────────────▼─────────────┐
                        │  PostgreSQL 18           │
                        │  the only source of truth│
                        └──────────────────────────┘
   APScheduler (in-process) ── hold sweeper, booking expiry
```

### Layering rules

| Layer | May import | Must never |
|---|---|---|
| `router` | its own service, schemas, `core.deps` | SQL, another module's models |
| `service` | its own repository, other modules' **services** | another module's repository or models |
| `repository` | its own models, `core.db` | any service |
| `models` | `core.db`, `core.enums` | anything above |

The rule that actually keeps the codebase clean as it grows: **a service may
call another service, never another module's repository.** `BookingService`
calls `InventoryService.confirm_hold()`; it never writes to `show_seats`.

### Transaction ownership

The **router** owns the transaction. Services and repositories `flush()` but
never `commit()`. One request is one transaction, so a booking that fails
halfway leaves nothing behind — and the seat-hold logic gets to rely on that.

The single exception is the payment webhook handler, which commits deliberately
at three points so that a recorded-but-unprocessed event is never lost.

## 2. Modules

| Module | Owns | Key operations |
|---|---|---|
| `identity` | `users`, `refresh_tokens` | register, login, rotating refresh tokens |
| `venues` | `cities`, `cinemas`, `screens`, `seats`, `seat_categories` | the physical layout template |
| `catalog` | `movies`, `genres`, `languages`, `people`, `movie_credits`, `reviews` | browse, search, detail |
| `scheduling` | `shows`, `show_prices`, `formats` | the showtime calendar and per-show pricing |
| `inventory` | `show_seats`, `seat_holds` | **seat map, claim, release, confirm** |
| `pricing` | `offers`, `offer_redemptions` | offer validation, redemption, the price calculator |
| `booking` | `bookings`, `booking_seats`, `booking_fnb_items`, `idempotency_keys` | order orchestration |
| `payments` | `payments`, `payment_events`, `refunds` | gateway orders, webhooks, refunds |
| `fnb` | `fnb_items` | concession catalogue |
| `notifications` | `notifications` | queued outbound messages |
| `analytics` | `domain_events` | append-only audit trail |

## 3. The two flows that matter

### Holding seats

```
POST /holds {show_id, seat_ids[], session_key}
  │
  ├─ InventoryService.hold_seats
  │    ├─ load show, assert bookable (status, sales window)
  │    ├─ dedupe seat ids, assert ≤ max_seats_per_booking
  │    ├─ pg_advisory_xact_lock(show)        ← serialise per show
  │    ├─ read seat map, assert seats belong to show
  │    ├─ assert no orphan single seat       ← advisory UX rule
  │    ├─ INSERT seat_holds (TTL = now + 8m)
  │    │
  │    ├─ UPDATE show_seats                  ← THE ATOMIC CLAIM
  │    │     SET status='held', hold_id=…, hold_expires_at=…
  │    │   WHERE show_id=… AND seat_id = ANY(…)
  │    │     AND (status='available'
  │    │          OR (status='held' AND hold_expires_at <= now()))
  │    │   RETURNING …
  │    │
  │    ├─ if len(returned) != len(requested) → raise → ROLLBACK
  │    └─ recount shows.available_seats
  │
  └─ COMMIT → 201 {hold_id, seat_labels, expires_at}
```

### Confirming a booking

```
Customer completes checkout on the gateway
  │
  └─▶ POST /payments/webhook/{gateway}   (signed, unauthenticated by JWT)
        │
        ├─ verify HMAC over the RAW body      ← bad signature → 402, no effect
        ├─ SELECT payment_events (gateway, event_id)
        │     └─ already present → 200 "duplicate", no effect
        ├─ INSERT payment_events              ← record BEFORE acting
        │
        ├─ payment.captured:
        │     ├─ amount != order amount  → fail + flag auto-refund
        │     ├─ payments.status = captured
        │     ├─ BookingService.confirm_booking
        │     │     └─ UPDATE show_seats SET status='booked'
        │     │        WHERE hold_id=… AND status='held'
        │     │          AND hold_expires_at > now()
        │     │        → short count → HoldExpiredError
        │     ├─ on HoldExpiredError:  expire booking + CREATE REFUND
        │     └─ otherwise: issue signed QR, queue email
        │
        └─ COMMIT → 200
```

The invariant the whole design exists to protect:
**money is never captured for a seat that cannot be delivered.** Either the
seats are confirmed, or a refund row exists — in the same transaction.

## 4. Concurrency: why the claim is safe

Under PostgreSQL's default READ COMMITTED, when an `UPDATE` reaches a row locked
by a concurrent transaction it blocks; when that transaction commits, Postgres
**re-fetches the new row version and re-evaluates the statement's `WHERE` clause
against it** (EvalPlanQual). The loser's `status = 'available'` test is now false,
so the row is skipped and the loser updates fewer rows than it asked for. The
caller compares counts and rolls back.

There is no interleaving in which both transactions claim the same seat. The
check is performed by the database, atomically, *as part of the write* — not by
application code reading a stale snapshot.

Three defences, layered:

1. **The conditional `UPDATE`** — the actual guarantee.
2. **A per-show advisory lock** — not needed for correctness; it eliminates
   deadlocks from inconsistent lock ordering across overlapping seat sets, and
   turns contention into a short queue instead of a retry storm.
3. **`UNIQUE (show_id, seat_id)` on `show_seats`** and a **partial unique index
   on live `booking_seats`** — structural backstops that a service-layer bug
   cannot get around.

`tests/concurrency/` proves layer 1 on its own: every test runs twice, once with
the advisory lock **disabled**. Removing the `WHERE` predicate makes four of
five tests fail — the guarantee is tested, not asserted.

### Hold expiry, in two layers

- **Lazy** — the read path and the claim predicate both treat a lapsed hold as
  available (`status='held' AND hold_expires_at <= now()`). A seat is bookable
  the instant it expires, with no sweeper in the loop.
- **Housekeeping** — a background sweep resets the rows and marks the holds
  expired, using `FOR UPDATE SKIP LOCKED` so multiple workers never fight.

The sweeper is *tidying*, not correctness. If it never ran, no seat would be
stranded.

## 5. Caching, background work, scaling

**No Redis.** Not because it wouldn't help, but because at this scale Postgres
is enough and every mechanism above teaches database-level concurrency, which is
the transferable part. Where Redis would slot in later: the rate limiter (today
in-process), the seat-map read cache, and the hold sweeper's queue.

**Background jobs** run in-process via APScheduler: the hold sweeper and the
stale-booking expirer. Both are idempotent and use `SKIP LOCKED`, so running
several instances is safe — which matters, because with N uvicorn workers you
get N schedulers. At that point move them to a dedicated worker process; nothing
in the job bodies changes.

**Scaling path**

| Load | Change |
|---|---|
| 10× | More uvicorn workers; move the scheduler to its own process; add a read replica for the catalogue |
| 100× | Redis for rate limiting and seat-map caching; extract `payments` (it is already behind an interface); partition `bookings` by month |
| 1000× | Split inventory per region; queue-based webhook processing; the advisory lock becomes the bottleneck and gets replaced by sharded per-show locks |

## 6. Cross-cutting

- **Errors** — one `AppError` hierarchy, one envelope
  (`{error: {code, message, details}, request_id}`), handlers registered once.
  Routers raise domain errors and never build responses by hand.
- **Logging** — `structlog`, with a request id bound to a `ContextVar` so a
  booking attempt is traceable across router → service → repository → gateway.
- **Auth** — short-lived JWT access tokens plus opaque, DB-backed refresh tokens
  stored only as SHA-256 hashes. Rotation is tracked; presenting an
  already-rotated token revokes the whole chain as a suspected theft.
- **Guest checkout and access control** — booking without an account is a
  deliberate, supported flow (`bookings.user_id` is nullable), matching every
  major ticketing platform: requiring registration before payment costs sales.
  What that *entitles* you to depends on how guessable the identifier is:

  | Identifier | Space | Treated as |
  |---|---|---|
  | Booking **id** (UUIDv7) | 48-bit timestamp + **74 random bits** | An unguessable link. Possession is sufficient — this is what the guest flow relies on. |
  | Booking **reference** (`CN` + 8 chars, 30-char alphabet) | ~2^39, and it is *printed on the ticket* | An identifier, never a credential. |

  So `GET /bookings/reference/{ref}` requires the contact **email** as well —
  the PNR-plus-surname pattern airlines use — compared in constant time, with a
  mismatch returning the same 404 as a non-existent reference so the endpoint
  cannot be used to test whether a reference exists. This matters because the
  response carries the signed QR payload, which *is* the ticket.

  A booking that *does* have an owner is visible only to that owner, whether the
  caller is anonymous or a different signed-in user.
  ([`test_guest_access_control.py`](../backend/tests/integration/test_guest_access_control.py))
- **Idempotency** — `Idempotency-Key` on booking creation, stored with a hash of
  the request body. Same key + same body replays the stored response; same key +
  different body is a 409.
