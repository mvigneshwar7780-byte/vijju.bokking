# Project Context — CineAI (UI brand: **vijju.booking**)

> **Purpose of this file.** Hand this to a fresh Claude session (or a new
> teammate) and it should be able to work on this codebase without re-deriving
> anything. It is written to be read top to bottom once, then used as a
> reference. It records not just *what* the code does but *why* it is shaped
> that way, and — importantly — **which mistakes have already been made and
> paid for**, so they are not made again.
>
> Companion docs live in [`docs/`](docs/) and go deeper on analysis, schema and
> plan. [`README.md`](README.md) is the user-facing front door. This file is the
> engineering hand-off.

---

## 1. What this is

A **movie-ticket booking platform**, BookMyShow-shaped, built as a learning /
reference implementation. Customers browse films, pick a cinema and showtime,
select seats, pay, and get a ticket. Cinema operators run their own venues.
Platform admins run everything.

**It is a booking platform only.** An earlier draft had AI features scaffolded
in; the owner explicitly removed that scope in order to add and learn AI
independently. **Do not add AI features unless asked.** Section 11 records where
the ground happens to be prepared, as information, not as an invitation.

### Status

| | |
|---|---|
| Backend | FastAPI · Python 3.14 · SQLAlchemy 2.0 · Alembic · PostgreSQL |
| Frontend | React 19 · TypeScript · Vite 8 · TanStack Query · Zustand · Tailwind 4 |
| Database | **Aiven managed PostgreSQL** (remote, TLS `verify-full`) |
| Size | ~17,100 lines across `backend/app` + `frontend/src` |
| Tests | **102 backend** (pytest, real Postgres) + **13 frontend** (Vitest) — all green |
| Migrations | `0001` … `0005`, all applied |
| Git | **Repository initialised but has ZERO commits.** Everything is untracked. |

That last row matters: there is no history, no diff to review against, and no
undo. Committing is the single highest-value housekeeping act available.

### Naming: two names, both correct

The **user-visible brand is `vijju.booking`** — the header wordmark, the browser
tab title and the footer. Everything *internal* is still **CineAI**: the
directory, the Python package, the database name, `app_name` in config, the
`cineai.*` localStorage keys, and the seeded `@cineai.example` accounts.

This split is deliberate and should be left alone. The `cineai.*` storage keys
in particular are load-bearing — see the collision bug in section 7 — and
renaming them would sign out every existing session.

---

## 2. Running it

### The database is remote

`backend/.env` points at **Aiven**, not localhost. There is no local Postgres to
start for normal development; the app connects over the internet with
`sslmode=verify-full` against `backend/certs/aiven-ca.pem`.

Two consequences:

- The app runs from **any machine with network access** — no local DB setup.
- **Round trips cost ~30 ms instead of ~0.05 ms.** See section 6.

Both `backend/.env` and `backend/certs/aiven-ca.pem` are **gitignored** and so
are absent from any clone. They must be copied across out of band. The `.env`
contains a live database password; the `.pem` is a public CA certificate and is
not secret.

### Commands

```bash
make            # list every task
make dev        # API on :8000 + web on :5173, together
make api        # backend only
make web        # frontend only
make db-check   # what am I actually connected to? host, version, TLS, extensions
make migrate    # alembic upgrade head
make seed       # load the demo catalogue
make test       # 102 backend + 13 frontend
make check      # lint + typecheck + test  ← run before declaring done
```

Open <http://localhost:5173>. Swagger is at <http://localhost:8000/docs>.

Vite **proxies** `/api` and `/health` to `127.0.0.1:8000`, so the browser sees a
single origin and CORS never applies in development.

### Seeded accounts

| Account | Password | Role |
|---|---|---|
| `admin@cineai.example` | `adminpass1` | Platform administrator |
| `operator@cineai.example` | `operatorpass1` | Operator of the 9 demo cinemas |
| `demo@cineai.example` | `demopass1` | Customer |

The `.example` TLD is required — `email-validator` rejects `.local`, and a test
asserts every seeded account can actually log in.

---

## 3. Architecture

### The one rule

```
models → repository → service → router
```

**A service may call another module's service. It may never touch another
module's repository.** That single rule is what keeps a modular monolith from
degenerating into a shared-database ball of mud. If you find yourself importing
`other_module.repository`, the design is telling you the call belongs in a
service.

### Module map — `backend/app/modules/`

| Module | Owns |
|---|---|
| `identity` | users, registration, login, JWT, refresh-token rotation |
| `venues` | cities, cinemas, screens, seats, seat categories, seating layouts |
| `catalog` | movies, people, credits, genres, languages, formats, reviews |
| `scheduling` | shows (screenings), the show-overlap constraint |
| `inventory` | **`show_seats`, seat holds — the concurrency core** |
| `pricing` | `show_prices`, the fee/tax calculator |
| `booking` | bookings, `booking_seats`, cancellation and refund quoting |
| `payments` | payment attempts, gateway interface, webhooks, refunds |
| `admin` | operator console + platform admin; ownership authorisation; reports |
| `fnb` | food & beverage add-ons |
| `notifications` | notification records (no delivery implemented) |
| `analytics` | domain events |

`backend/app/core/` holds config, db/engine, security, errors, logging,
middleware, shared schemas and dependencies. **Nothing outside `core/config.py`
is allowed to read `os.environ`** — that keeps configuration auditable.

### Frontend map — `frontend/src/`

- `api/client.ts` — axios instance; **single-flight token refresh** (concurrent
  401s share one refresh promise, otherwise four parallel requests burn four
  refresh tokens and the server's replay detection revokes the session); error
  normalisation into `ApiClientError`.
- `api/endpoints.ts`, `api/types.ts` — the typed API surface.
- `store/session.ts` — zustand, persisted under `cineai.app`.
- `lib/holdRelease.ts` — deferred, cancellable seat-hold release (see section 7).
- `pages/` — customer flow; `pages/operator/` — console; `pages/admin/` — accounts.
- `components/` — `SeatMap`, `HoldTimer`, `MoviePicker`, `PriceComparison`,
  `CancelBooking`, shared `ui.tsx`.

---

## 4. Domain model

~32 tables; the full treatment is [`docs/03-database-schema.md`](docs/03-database-schema.md).

### The pricing chain — the most important design decision

**A movie has no price.** There is no price column on `movies` and there must
never be one. The same film plays at three halls on the same evening for three
different amounts:

```
Movie              shared catalogue, owned by nobody
  └─ Cinema        owned by an operator; defines its OWN seat tiers
      └─ Screen    a physical auditorium and its seat layout
          └─ Show  one screening: movie + screen + format + time
              └─ Seat category → price_minor       (show_prices)
                  └─ + format surcharge            (formats)
```

`show_prices(show_id, seat_category_id, price_minor)` is **the only place a
ticket price lives**. `seat_categories` are scoped **per cinema**, so "Recliner"
at a value brand and "Recliner" at a premium brand are different rows holding
different money.

Two properties this buys, and they are the point:

- Two operators price the same film independently, with no shared row to
  contend over and no coordination.
- **Repricing never changes what someone already paid.** `booking_seats`
  snapshots the price at purchase, and the repricing query touches only seats
  still `available` or `blocked`.

If a change would introduce a price that is not reachable through that chain,
the change is wrong.

### Seat lifecycle

```
show_seats.status:  available → held → booked
                         ↑        │
                         └────────┘   hold expires, or is released
                    blocked   (operator-blocked, never sellable)
```

`show_seats` rows are **materialised when the show is created** — one row per
physical seat per show — which is what makes the atomic claim in section 5
possible.

---

## 5. Invariants — do not break these

These are the guarantees the system actually makes. Each is enforced by the
database, not by application code, and each has a test that fails when the
enforcement is removed.

### 5.1 Two people can never be sold the same seat

`backend/app/modules/inventory/repository.py`:

```sql
UPDATE show_seats
   SET status = 'held', hold_id = :hold_id, hold_expires_at = :expires_at
 WHERE show_id = :show_id
   AND seat_id = ANY(:seat_ids)
   AND (status = 'available'
        OR (status = 'held' AND hold_expires_at <= now()))
RETURNING id, seat_id, seat_category_id, price_minor;
```

**Why it is safe.** Under READ COMMITTED, when this statement meets a row
another transaction has locked, it blocks. When that transaction commits,
PostgreSQL re-fetches the new row version and **re-evaluates this WHERE clause
against it** (EvalPlanQual). The loser's `status = 'available'` test is now
false, the row is skipped, and the statement updates fewer rows than requested.
The caller compares counts and rolls back.

No interleaving lets both win, because the check happens **inside the write**,
never in application code holding a stale read.

The per-show `pg_advisory_xact_lock` is a **deadlock-ordering optimisation, not
the guarantee**. `make test-concurrency` runs 20 threads against one seat with
the advisory lock deliberately **disabled**, and still gets exactly one winner.
Deleting the `WHERE` predicate fails 4 of 5 tests — the tests have been
mutation-checked and genuinely discriminate.

### 5.2 A cancelled booking's seat must become sellable again

Enforced by a **partial** unique index:

```sql
uq_booking_seats_active_show_seat ON booking_seats(show_seat_id) WHERE is_active
```

A plain `UNIQUE(show_seat_id)` collided with the cancelled booking's surviving
row and made the seat permanently unsellable. The `WHERE is_active` is the fix.

### 5.3 Two shows cannot overlap on one screen

```sql
EXCLUDE USING gist (
  screen_id WITH =,
  tstzrange(starts_at, ends_at) WITH &&
) WHERE (status <> 'cancelled')
```

Requires the `btree_gist` extension. Violations surface as **409 `SHOW_OVERLAP`**
with a human-readable message naming the screen.

### 5.4 A webhook is processed exactly once

`UNIQUE (gateway, event_id)` on `payment_events`. Signatures are HMAC-verified.
A reconciliation path covers webhooks that never arrive.

### 5.5 Holds expire even if nothing sweeps them

Expiry is **lazy** — enforced in the read path *and* in the claim predicate
above — so correctness never depends on the background sweeper running. The
sweeper (`workers/scheduler.py`, `FOR UPDATE SKIP LOCKED`) is housekeeping that
tidies rows and refreshes counters.

### 5.6 An operator can only touch their own cinemas

Ownership is a single column, `cinemas.operator_user_id`. Authorisation lives in
`modules/admin/authorization.py`.

**The role is read from the database on every request, never from a JWT claim.**
So a promotion takes effect on the *very next request* with no re-login — and,
symmetrically, revocation is immediate and a stale token cannot keep working.

---

## 6. Conventions

**Money is integer minor units (paise) everywhere.** Rupees exist only at the
formatting edge. Percentages go through `pct()`, which applies ROUND_HALF_UP
exactly once. Never introduce a float for money.

**Every primary key is a UUIDv7**, generated **client-side** by `_new_uuid7()`
in `core/db.py` (`uuid.uuid7` on Python 3.14, hand-rolled RFC 9562 fallback
below that). `server_default=text("uuidv7()")` is kept only for raw SQL that
bypasses the ORM. This is not stylistic — see below.

**PostgreSQL enums use `values_callable`** via the shared `pg_enum()` helper.
Without it, SQLAlchemy persists Python enum *names* rather than *values*.

**Errors** are the shape `{error: {code, message, details}}` end to end. Raise
the typed errors in `core/errors.py`; the frontend surfaces `.code` and
`.message` directly, so the message is customer-facing text — write it that way.

**Identifiers must be ≤ 63 characters.** PostgreSQL truncates silently past
that, which turns a unique constraint into a different constraint than the one
you wrote.

### Latency is round trips, not query time

The single biggest surprise on a managed database: code that felt instant
becomes minutes slow **without any query getting slower**. Local socket ≈
0.05 ms per round trip; Aiven ≈ 30 ms — roughly 600×. Anything shaped like "one
statement per row" stops being free.

Measured on the seed: 4,652 statements × ~30 ms ≈ 139 s of pure network wait,
against 153 s observed. Batching to **621 statements** took it to **34.5 s with
50% more data**. No query was optimised.

Two patterns caused nearly all of it:

- **Server-generated primary keys** force one round trip per row. Client-side
  UUIDv7 lets SQLAlchemy batch hundreds of rows into one statement — that is
  *why* the convention above exists.
- **Per-row check-then-insert-then-flush** in a loop. Build in memory, write in
  a handful of statements, materialise seats with one `INSERT … SELECT`.

If you add a bulk operation, **count its statements** before assuming it is
fast. `DB_ECHO=true` prints every one.

---

## 7. Traps already hit — do not reintroduce

Each of these cost real debugging time. They are listed because the same shapes
recur.

| Trap | What happened | The lesson |
|---|---|---|
| **Silencing a lint warning broke a feature** | A `useEffect` was replaced with `useState(user?.email ?? '')` to quiet oxlint. The session hydrates *asynchronously*, so it captured `''` and permanently disabled "Proceed to payment". | The warning was cosmetic; the fix was not. Contact fields are now **derived** (`emailEdit ?? user?.email ?? ''`), not seeded. **Never trade behaviour for a lint warning.** |
| **React StrictMode released holds on page load** | Release-on-unmount fired during StrictMode's mount → unmount → remount. The server showed `status=released` while the countdown still ticked. | `lib/holdRelease.ts` defers release by 500 ms and cancels it on remount. **Any destructive effect cleanup must be cancellable.** |
| **Two worthless tests** | One mutation used `.replace()` without asserting it matched — a vacuous check. Another passed *with the bug present*, because StrictMode's double-invoke does not reproduce through the test wrapper. | **Mutation-check every test**: break the code deliberately and confirm the test fails. A test that cannot fail is worse than no test. |
| **localStorage key collision** | zustand persist and `sessionKey()` both used `cineai.session`; `session_key` became a 230-character JSON blob → 422. | Split into `cineai.app` / `cineai.guest` with a format guard. **Do not rename these.** |
| **Unauthenticated booking lookup leaked data** | `GET /bookings/reference/{ref}` returned the contact email and a signed QR payload to anyone with a reference. | Now requires a matching email, compared in constant time, with an **identical 404** for wrong-email and missing-reference so the endpoint is not an oracle. |
| **Idempotency key blocked legitimate retry** | Keyed `booking:{id}`, so retrying after a cancelled payment was rejected as a duplicate. | Scoped per attempt: `booking:{id}:attempt:{n}`. |
| **`Decimal.normalize()` printed `1E+2`** | Customer-facing refund text showed `₹1E+2`. | `f"{d.quantize(Decimal('0.01')):f}"`, then strip trailing zeros. |
| **500 instead of 409 on overlapping shows** | The error message read `screen.name` — an ORM attribute the failed flush had expired — reloading it on a poisoned session raised `PendingRollbackError`. | Read attributes **before** the flush; wrap the insert in a `SAVEPOINT`. |
| **`GET /movies?q=` always returned 500** | `SELECT DISTINCT` with `ORDER BY similarity(...)` is invalid in PostgreSQL. The search box had never worked. | Filters are `EXISTS` subqueries now, so no `DISTINCT` is needed. Count comes from the *unordered* statement. |
| **Empty movie dropdown when scheduling** | The form read `GET /operator/movies`, which returns only titles *that operator created*. A new operator sees zero, and `POST /operator/movies` had no UI at all. | `MoviePicker` searches the **shared catalogue**. Ask "what does a brand-new account see?" of every operator screen. |
| **Time-dependent flaky tests** | Tests picked the "first bookable show" and began failing after ~5 pm, when it fell inside the cancellation cutoff. | `pick_show(cancellable=True)` derives the requirement from `settings`. **Never hard-code a time assumption.** |
| **Circular foreign key** | `seat_holds.booking_id` ↔ `bookings.hold_id` could not be created in either order. | Dropped the reverse pointer; added `ix_bookings_hold_id`. |

**The meta-lesson.** Most of these were found by the project owner using the
app, not by the test suite. Before calling anything done: exercise the actual
flow in the browser, from the state a **new** user or operator would be in.

---

## 8. Known open issues

A systematic audit (63 parallel agents, each finding independently verified,
11 claims rejected as not-real) returned **48 confirmed findings — 25 blocking,
22 confusing, 1 cosmetic**. **None are fixed.** They are overwhelmingly
*endpoint exists, no UI reaches it*.

The blocking ones, worst first:

1. **Scheduling is impossible when a screen does not use every tier the cinema
   defines.** `ShowForm` sends all cinema tiers; the API rejects stray
   categories. Unfixable from the UI.
2. **Saving a seating plan silently deletes every scheduled show on that
   screen.** No warning, no confirmation.
3. **A show's prices can never be changed.** `PUT /operator/shows/{id}/prices`
   has no UI, so a mispriced show can only be fixed by cancelling it —
   refunding every buyer.
4. **Screens, seat tiers, cinemas and films can never be edited.** All four
   `PATCH` endpoints exist and are unreachable; a typo is permanent.
5. **Admin cannot assign an existing cinema to an operator.**
   `PUT /admin/cinemas/{id}/operator` has an API wrapper but no page.
6. **Admin Accounts loads only the first 50 users and filters client-side**, so
   it reports "No accounts match" for people who exist — blocking the only
   route to promoting an operator.
7. **`Admin Users` gates on the cached session role** — the identical bug
   already fixed in `OperatorLayout`. Cheap fix, known-good pattern to copy.
8. **Header nav is hidden below the `sm` breakpoint**, so the console is
   unreachable on a phone.
9. **Show audio/subtitle language has no control** and silently defaults to
   English.
10. **Format fields are free text** even though `GET /formats` lists the valid
    values.
11. **The operator bookings table shows a total it cannot page through.**

Recommended order: **7** (trivial, pattern already exists), then **1** and **2**
(they block or destroy real work), then **3**–**5**.

---

## 9. Testing

```bash
make test               # 102 backend + 13 frontend
make test-concurrency   # the seat races, verbosely
make check              # lint + typecheck + test
```

**Backend tests run against a real PostgreSQL** (`cineai_test`), never SQLite —
the entire design rests on Postgres row-locking semantics, and another engine
would be testing something the production code does not do.

**`tests/conftest.py` forces `localhost/cineai_test` regardless of what `.env`
says.** The suite `TRUNCATE`s every table and the race tests open many
concurrent connections; pointing that at the shared Aiven database would be
destructive. Override only with `TEST_AGAINST_REMOTE=1`, and only against a
database you can afford to lose. `make reset` refuses to run unless the host is
local.

**This is the one thing that needs a local PostgreSQL.** Running the *app*
needs no local database; running the *backend tests* does.

Test layout: `tests/unit` · `tests/integration` · `tests/concurrency`.

**Before adding a test, mutation-check it**: break the code it covers and
confirm it fails. Two tests in this repo's history passed against broken code.

---

## 10. Moving this to another machine

### Zip: exclude the two big directories

They are **398 MB together and completely non-portable** — `backend/.venv` is
macOS/arm64 binaries with absolute shebang paths, and `frontend/node_modules`
contains native binaries (esbuild, rollup, oxlint). Both **must** be rebuilt on
the target machine.

```bash
cd "AI_Learning"
zip -r cineai.zip cineai \
  -x '*/.venv/*' '*/node_modules/*' '*/__pycache__/*' \
     '*/.pytest_cache/*' '*/.ruff_cache/*' '*/dist/*' '*/.DS_Store'
```

**Verified**: this produces a **394 KB, 244-file** archive from a 398 MB
directory. `frontend/package-lock.json` is included, so use `npm ci` on the
far side for the exact same dependency versions.

**A zip ignores `.gitignore`**, so it *will* include `backend/.env` and
`backend/certs/aiven-ca.pem` — which is what makes it work on arrival. But
`.env` holds a **live database password**: do not put that zip in a shared
drive, chat, or email. Transfer it directly, or strip `.env` and retype the
password on the far side.

Prefer `git init && git commit` and a **private** GitHub repo if you can — the
repo currently has zero commits, so there is no history to lose and no undo if
something goes wrong. `.env` and the `.pem` stay out of git by design and get
copied separately.

### Rebuilding on Windows

The Aiven database is remote, so **it works from Windows with no database
setup** — that is the easy part. Three things do differ:

**1. There is no `make`.** The `Makefile` hard-codes `SHELL := /bin/bash` and a
Homebrew Postgres path. Run the steps directly in PowerShell:

```powershell
# backend
cd backend
py -3.14 -m venv .venv                  # 3.12+ required; 3.14 matches this machine
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python scripts_dbcheck.py     # confirm the Aiven connection first
.venv\Scripts\alembic upgrade head
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000

# frontend, in a second terminal
cd frontend
npm ci                                  # lockfile is in the zip; exact versions
npm run dev
```

Note `.venv\Scripts\` on Windows where macOS uses `.venv/bin/`.

**Do not run `make seed` / `scripts_seed.py`** unless you intend to wipe and
reload the shared Aiven database — the other machine is pointed at the same
one.

**2. Python version.** **3.12 or newer** — `numpy==2.5.2` declares
`Requires-Python >=3.12`, so 3.11 fails the install. This machine runs 3.14, which has native
`uuid.uuid7`; `_new_uuid7()` falls back to a hand-rolled RFC 9562 implementation
on older interpreters, so both work — but match 3.14 if convenient and the
behaviour is identical.

**3. Running the backend tests needs a local PostgreSQL on the Windows box**
(section 9). Install PostgreSQL 16+ and create a `cineai_test` database. If you
only want to *use* the app, skip this entirely — the app itself needs no local
database.

**WSL2 is the smoother path** if it is available: `make`, bash and the Homebrew-
shaped tooling all work as written, and only the Postgres path in the `Makefile`
needs adjusting.

### One shared database, two machines

Both machines will point at the **same Aiven instance**, so they share data and
share the plan's **20-connection cap**. `DB_POOL_SIZE + DB_MAX_OVERFLOW` is 10
per process — two machines running the API simultaneously is fine, three starts
to crowd it. Watch out for one machine reseeding while the other is mid-booking.

---

## 11. Ground that happens to be prepared

Recorded as fact, **not as a suggestion to build on it.** The owner removed AI
scope deliberately and intends to add it themselves.

- `pgvector` is installed by the setup script and enabled in migration `0001`.
  **Nothing uses it.** No embedding tables, no similarity queries.
- `anthropic` and `numpy` are in `requirements.txt`; `config.py` carries
  `anthropic_api_key` and `llm_provider` (default `"echo"`). **No code imports
  the SDK.** These are leftovers from the removed scope and could be deleted.
- `domain_events` and the `EmbeddingOwnerType` / `ChatRole` enums exist and are
  unused.

The natural seams, if the owner chooses to use them, are the module boundary
(a new module under `modules/`, following `models → repository → service →
router`) and the fact that catalogue search already uses `pg_trgm`, so a
semantic path would sit beside an existing lexical one rather than replacing it.

---

## 12. Working agreements

- **`make check` must pass before anything is called done.**
- **Exercise the real flow in the browser** from a new user's or new operator's
  starting state. Most bugs here were found that way, not by tests.
- **Mutation-check new tests.** Break the code; confirm the test fails.
- **Never break behaviour to satisfy a linter.**
- **Count round trips** in anything bulk before assuming it is fast.
- **Money stays in integer paise.** No floats.
- **Price must resolve through the chain** in section 4. If it does not, the
  change is wrong.
- Report honestly: if something is untested, unverified or skipped, say so.
