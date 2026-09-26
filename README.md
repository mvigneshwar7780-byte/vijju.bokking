# CineAI

A movie ticket booking platform — BookMyShow-shaped — built as a reference
implementation. FastAPI + PostgreSQL 18 + React.

The **user-visible brand is `vijju.booking`** (header, tab title, footer).
Everything internal — this directory, the Python package, the database, the
`cineai.*` browser storage keys, the `@cineai.example` demo accounts — is still
CineAI. That split is deliberate; the storage keys in particular are load-bearing
and renaming them would sign out every existing session.

The interesting part is not the CRUD. It is that **two people can never be sold
the same seat**, and that is enforced by the database and proven by tests that
fail when the guarantee is removed.

---

## Quick start

Prerequisites: macOS or Linux with Homebrew, **Python 3.12+** (`numpy` pins
the floor at 3.12), and:

```bash
brew install postgresql@18 pgvector node
brew services start postgresql@18
```

Then:

```bash
git clone <this repo> && cd cineai
make setup     # database + role + extensions, deps, migrations, demo data
make dev       # API on :8000, web on :5173
```

Already pointing at a managed provider? Use `make setup-managed` instead — it
skips role and database creation, which a managed plan will not grant you.

Open <http://localhost:5173>. Sign in as `demo@cineai.example` / `demopass1`, or
register. Payments are simulated — the payment page has a
"simulate a declined payment" button so the unhappy path is one click away.

| What | Where |
|---|---|
| Web app | http://localhost:5173 |
| API docs (Swagger) | http://localhost:8000/docs |
| Health + extensions | http://localhost:8000/health |

Run `make` on its own to list every task.

**On Windows** there is no `make` (the Makefile is macOS/Linux only) — see
[`SETUP-WINDOWS.md`](SETUP-WINDOWS.md) for the PowerShell equivalents.

---

## What is built

**Customer** — city selection · now-showing browse with typo-tolerant search ·
**two browse directions** (movie → every hall showing it, cheapest first; or
cinema → everything playing there) · film detail with cast and crew ·
date/cinema showtime board with availability bands · seat map with categories,
aisles and accessibility markers · time-limited seat holds with a live
countdown · promo codes · F&B add-ons · payment covering all four gateway
outcomes · signed QR ticket · booking history · cancellation with a refund
quote.

**Cinema operator** — register a venue · define seat tiers and their default
prices · add screens · design seating plans (rows, aisles, wheelchair spaces) ·
add films to the shared catalogue · schedule showtimes singly or in bulk across
a date range · price each showtime per seat tier · cancel a show with automatic
full refunds · see bookings, occupancy and revenue for their own cinemas only.

**Platform administrator** — every cinema, assign or transfer operators, change
roles, platform-wide revenue.

**System** — guest checkout (no account required, by design) with
identifier-appropriate access control · JWT auth with rotating,
replay-detecting refresh tokens ·
`Idempotency-Key` on booking creation · a swappable payment-gateway interface ·
webhook signature verification and exactly-once processing · automatic refund
when seats cannot be delivered · background hold sweeper · structured logs with
request ids · a one-command reproducible demo dataset.

**Help assistant** — a chat widget that collapses to an icon and answers
questions from a support knowledge base. See
[The help assistant](#the-help-assistant) — the retrieval engine is deliberately
left to the project owner, and the app degrades cleanly without it.

**Not built** — real payment gateway, email delivery, gate scanning. The
operator console *is* built (it was listed here as missing for a while).
See [`docs/04-development-plan.md`](docs/04-development-plan.md), and
[`CONTEXT.md`](CONTEXT.md) §8 for the audited list of endpoints that exist but
have no UI reaching them.

---

## The one thing worth reading

[`backend/app/modules/inventory/repository.py`](backend/app/modules/inventory/repository.py)
— the seat claim, and why it is safe:

```sql
UPDATE show_seats
   SET status = 'held', hold_id = :hold_id, hold_expires_at = :expires_at
 WHERE show_id = :show_id
   AND seat_id = ANY(:seat_ids)
   AND (status = 'available'
        OR (status = 'held' AND hold_expires_at <= now()))
RETURNING id, seat_id, seat_category_id, price_minor;
```

Under READ COMMITTED, when this statement meets a row another transaction has
locked, it blocks; when that transaction commits, Postgres re-fetches the new
row version and **re-evaluates this WHERE clause against it**. The loser's
`status = 'available'` test is now false, the row is skipped, and it updates
fewer rows than it asked for. The caller compares counts and rolls back.

No interleaving lets both win. The check happens inside the write, not in
application code holding a stale read.

```bash
make test-concurrency
```

20 threads, one seat, one winner — run once with the per-show advisory lock on
and once with it **off**, because the lock is a deadlock optimisation, not the
guarantee.

### The same mistake, twice, in two tables

Uniqueness has to be scoped to the rows that are still *live*, or a cancellation
poisons the slot for ever. Both of these started as unconditional constraints and
both had to be made partial:

| Index | Scope | What the unconditional version broke |
|---|---|---|
| `uq_booking_seats_active_show_seat` | `WHERE is_active` | A cancelled booking's seat could never be resold |
| `uq_shows_screen_id_starts_at` | `WHERE status <> 'cancelled'` | An operator who cancelled Saturday 18:00 could never schedule that slot again (migration `0006`) |

The second was worse than it sounds: it sat directly beneath an exclusion
constraint already scoped `WHERE status <> 'cancelled'`, whose own comment
claimed a cancellation frees the slot immediately. The schema contradicted its
documented intent, and re-seeding a retired catalogue silently produced no shows
at all — reusing dead rows while reporting success.

---

## Layout

```
cineai/
├── backend/
│   ├── app/
│   │   ├── core/            config, db, security, errors, logging, deps
│   │   ├── modules/         identity venues catalog scheduling inventory
│   │   │                    pricing booking payments admin assistant
│   │   │                    fnb notifications analytics
│   │   ├── db/              models registry, migrations, seed
│   │   ├── workers/         APScheduler jobs
│   │   └── main.py          app factory
│   └── tests/               unit · integration · concurrency
├── frontend/
│   ├── src/                 api · store · components · pages
│   └── public/posters/      real poster files, named <movie-slug>.<ext>
├── docs/                    analysis · architecture · schema · plan
├── scripts/setup_db.sh
└── Makefile
```

Each module is `models → repository → service → router`. A service may call
another module's **service**, never its repository. That single rule is what
keeps the codebase from turning into spaghetti.

---

## Docs

| | |
|---|---|
| [Platform analysis](docs/01-platform-analysis.md) | How BookMyShow/PVR/Fandango work, and what each observation implies for the schema |
| [Architecture](docs/02-architecture.md) | Modules, layering, the two critical flows, the concurrency argument |
| [Database schema](docs/03-database-schema.md) | All 32 tables, the constraints that matter, a worked pricing example |
| [Development plan](docs/04-development-plan.md) | What is done, what is next, and the acceptance test for each phase |
| [`CONTEXT.md`](CONTEXT.md) | Engineering hand-off: invariants, conventions, traps already paid for, open findings |
| [`SETUP-WINDOWS.md`](SETUP-WINDOWS.md) | Running it on Windows, and what genuinely differs |

---

## Testing

```bash
make test               # everything — 108 backend, 21 frontend
make test-concurrency   # the seat races, verbosely
make check              # lint + typecheck + test
```

Tests run against a **real PostgreSQL** database (`cineai_test`), never SQLite:
the whole design rests on Postgres row-locking semantics, and a different engine
would test something the production code does not do. The suite rebuilds and
reseeds that database at session start, so a run that dies mid-teardown cannot
poison the next one.

---

## Creating a cinema operator account

There is deliberately **no self-service route** to operator access — otherwise
anyone could sign up and start listing a hall they do not own. It takes two
steps:

1. **The owner registers normally** at `/login` → *Register*. Every new account
   is a customer.
2. **An administrator promotes them.** Sign in as an admin, open **Accounts** in
   the top nav, find the person, and set their role to *Cinema operator*.

The role is resolved from the database on every request, not from the access
token, so the change applies to the **very next request** — no signing out and
back in. (The same property means removing access is immediate too; a stale
token cannot keep working.)

The new operator then opens **Console** and works down the setup:

```
Add a theater         name, city, address, time zone
  └─ Seat tiers       e.g. Standard ₹180, Premium ₹300 — priced per cinema
      └─ Screen       an auditorium, and which formats it supports
          └─ Layout   rows, seat counts, aisles, wheelchair spaces
              └─ Film add to the shared catalogue (or reuse an existing title)
                  └─ Showtime   date, time, format, and a price per seat tier
```

Order matters: a show cannot be scheduled until the screen has a seating plan,
and every seat tier in that screen must be given a price — otherwise the
operator's intent silently falls back to the tier default.

From then on they see only their own cinemas, bookings, occupancy and revenue.
A platform administrator sees everything and can reassign a cinema to a
different operator from **Accounts**.

**Seeded accounts** (password in brackets):

| Account | Role |
|---|---|
| `admin@cineai.example` (`adminpass1`) | Administrator |
| `operator@cineai.example` (`operatorpass1`) | Operator of the 9 demo cinemas |
| `demo@cineai.example` (`demopass1`) | Customer |

---

## The help assistant

A chat widget sits bottom-right on every page: an icon when idle, a panel when
opened, with the transcript persisted so navigating away does not discard an
answer.

**The app half is finished and tested.** `POST /assistant/ask` returns four
fields, each driving something the widget already draws:

| Field | Renders as |
|---|---|
| `answer` | the chat bubble; newlines preserved |
| `sources` | an expandable "N sources" disclosure; `[]` hides it |
| `suggestions` | clickable chips that ask themselves |
| `grounded` | `false` puts a warning border on the bubble — a miss never looks like a fact |

**The answering half is deliberately the owner's.** Implementing
`AssistantService.ask()` is the whole job; nothing else needs to change.

### It must not be able to break the site

The retriever imports `lancedb` and `sentence-transformers`, which are **not in
`requirements.txt`** — they pull in PyTorch, and that is too heavy to force on
anyone who only wants the booking platform.

`main.py` imports every router at module level, so on a machine without those
packages a plain `import` raised `ModuleNotFoundError` while routers were still
loading and **no router mounted at all** — no `/movies`, no `/shows`, no login.
The site rendered (Vite serves it separately) with an empty movie grid, and the
cause was nowhere near the symptom.

The import is now attempted once and its failure remembered, so the API always
boots and only `/assistant/ask` degrades:

```json
{ "answer": "The help assistant is not available on this server yet…",
  "grounded": false,
  "detail": "ModuleNotFoundError: No module named 'lancedb'" }
```

Buying a ticket does not depend on the help centre being installed.

### Enabling it on a machine

```bash
cd backend
.venv/bin/pip install lancedb sentence-transformers pandas   # ~2 GB
.venv/bin/python -m app.db.seed.ingest_help                  # builds the index
```

Then **restart the API** — uvicorn does not retry an import that already failed,
so it keeps reporting "not available" until you do.

The index is a folder on local disk (`backend/lancedb_help/`), not in Postgres.
Your catalogue is shared between machines; the index is not, and must be built on
each one.

---

## Poster artwork

Artwork resolves in two tiers, so a film never shows a broken image:

1. **A real file** at `frontend/public/posters/<movie-slug>.<ext>` — `.avif`,
   `.webp`, `.jpg`, `.jpeg` or `.png`. Vite serves `public/` at the web root, so
   it is reachable at `/posters/…` with no route and no build step. Drop a file
   in, re-seed, done.
2. **Otherwise a generated SVG card** from `GET /api/v1/artwork/poster.svg`,
   drawn from the title with a colour hashed from it, so a film keeps the same
   card across restarts.

Serving that fallback ourselves rather than from a placeholder host was not
cosmetic: on a filtered network the third-party images were blocked and every
poster rendered blank while the API happily reported valid URLs.

Two things worth knowing. Backdrops stay generated even where a poster exists — a
2:3 poster stretched across a 16:9 hero looks worse than a plain card. And the
seed refreshes artwork for films that **already exist**, not just on insert;
without that, a film created before the artwork source changed would keep the old
URL for ever and no amount of re-seeding would fix it.

---

## Pricing model

A movie has **no price**. There is no price column on `movies`, and there never
should be — the same film plays at three halls on the same evening for three
different amounts:

```
Ramayana — Bengaluru
   Cinepolis: Nexus Mall     from ₹100
   INOX: Garuda Mall         from ₹135
   PVR: Forum Mall           from ₹185
```

(Read out of the live database, not illustrative.)

Price resolves down a chain, and each link is owned by someone different:

```
Movie          shared catalogue, not owned by any cinema
  └─ Cinema    owned by an operator; defines its own seat tiers
      └─ Screen        a physical auditorium and its seat layout
          └─ Show      one screening: movie + screen + format + time
              └─ Seat category → price_minor      (show_prices)
                  └─ + format surcharge           (formats)
```

`show_prices(show_id, seat_category_id, price_minor)` is the only place a
ticket price lives. `seat_categories` are scoped **per cinema**, so "Recliner"
at a value brand and "Recliner" at a premium brand are different rows with
different money. Format surcharges (IMAX, 4DX) are added on top at
materialisation.

Two consequences worth stating, because they are the point of the design:

- Two operators can show the same film at completely different prices with no
  coordination and no shared row to contend over.
- Repricing a show never changes what anyone already paid: `booking_seats`
  snapshots the price at purchase, and the repricing query touches only seats
  still `available` or `blocked`.

---

## Running against a managed database

The app talks to PostgreSQL through one settings block, so moving from a local
server to Aiven / Neon / RDS is configuration, not code. Point `backend/.env` at
the provider:

```dotenv
POSTGRES_HOST=pg-xxxxx.h.aivencloud.com
POSTGRES_PORT=19798
POSTGRES_USER=avnadmin
POSTGRES_PASSWORD=...
POSTGRES_DB=defaultdb
POSTGRES_SSLMODE=verify-full
POSTGRES_SSLROOTCERT=certs/aiven-ca.pem
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=5
```

Then:

```bash
make db-check        # host, server version, TLS, extensions, uuidv7 mode
make migrate seed
make dev
```

Four things differ from a local server, and each is handled:

| Concern | What changes |
|---|---|
| **TLS** | Managed providers refuse plaintext. `POSTGRES_SSLMODE` is passed per-connection. `require` encrypts but authenticates nothing — it does not stop a man-in-the-middle. `verify-full` plus `POSTGRES_SSLROOTCERT` pointing at the provider's CA also verifies the certificate chain **and** the hostname; that is the setting to use. `make db-check` reports whether the live connection is actually encrypted. |
| **Connection limit** | Small plans cap total connections (Aiven's entry plan: 20), shared with migrations and psql. `DB_POOL_SIZE + DB_MAX_OVERFLOW` is this process's ceiling — keep it well under the cap. `pool_pre_ping` and `pool_recycle` handle the proxy dropping idle connections. |
| **PostgreSQL version** | The schema uses `uuidv7()` for every primary key, which is native only in **PG 18**. Most managed plans still run 16 or 17, so migration `0001` installs a SQL shim with identical semantics when the server lacks one — real RFC 9562 v7 UUIDs, so rows keep their time-ordering and index locality. `make db-check` tells you which is in use. |
| **No superuser** | `CREATE EXTENSION` is allowlisted on managed plans. `btree_gist` and `pg_trgm` are genuinely required (the show-overlap constraint and the fuzzy title index) and fail loudly with a usable message; `pgcrypto` and `vector` are attempted and skipped with a notice. |

### Verifying TLS, rather than assuming it

`sslmode=require` is the setting people stop at, and it is the one that gives
false confidence: it encrypts the connection but validates nothing, so an
attacker who can redirect traffic can terminate the TLS themselves. Only
`verify-full` checks that the certificate chains to your provider's CA *and*
that the hostname matches.

Download the CA from the provider's console into `backend/certs/`, then:

```dotenv
POSTGRES_SSLMODE=verify-full
POSTGRES_SSLROOTCERT=certs/aiven-ca.pem
```

A setting that silently fails open is worse than none, so verify it rejects
what it should. Three probes, each isolating one property:

| Probe | Expected |
|---|---|
| Correct CA, correct hostname | connects |
| Untrusted CA | refused — `certificate verify failed` |
| Correct CA, hostname not on the certificate | refused — `server certificate for …` |

The third needs care. Aiven's leaf certificate lists the server's **IP address
as both an IP and a DNS SAN**, and carries a `*.h.aivencloud.com` wildcard — so
connecting by IP legitimately passes and is not a valid negative test. Use
libpq's `host` / `hostaddr` split instead: connect to the real address while
presenting a name that is genuinely absent from the certificate.

`.gitignore` carries `**/certs/*.pem` — note the leading `**`, because a
root-anchored `certs/*.pem` would not match `backend/certs/` and a private key
dropped there would be committed.

**Aiven's CA is nonetheless committed here**, force-added deliberately: it is a
public trust anchor with no private key (`subject == issuer`, valid to 2036), and
having it in the repo means a fresh clone gets working TLS without an out-of-band
file copy. The ignore rule still stands for anything else — and a **private key**
must never be added past it.

### Latency is round trips, not query time

The single biggest surprise when moving to a managed database is that code
which felt instant becomes minutes slow without a single query getting slower.
Against a local socket a round trip is ~0.05 ms; against a managed host it is
~30 ms — about 600× more. Anything shaped like "one statement per row" stops
being free.

The seed made that concrete: 4,652 statements × ~30 ms ≈ 139 s of pure network
wait, against a measured 153 s runtime. Batching it to 621 statements is the
whole fix — no query was optimised.

Two patterns caused nearly all of it, and both are worth recognising:

- **Server-side primary keys.** With only `server_default=uuidv7()`, SQLAlchemy
  must ask the database for each generated key, forcing a round trip per row.
  Generating the UUID client-side (`_new_uuid7` in `core/db.py`) lets it batch
  hundreds of rows into one statement. The server default stays for raw SQL.
- **Per-row work in a loop.** Check-then-insert-then-flush per show is six round
  trips × 288 shows. The seed now builds everything in memory and writes it in a
  handful of statements, and materialises every show's seats with one
  `INSERT … SELECT` instead of 288.

If you add a bulk operation later, count its statements before assuming it is
fast. `DB_ECHO=true` prints every one.

Passwords are escaped via SQLAlchemy's `URL.create`, so provider-generated
secrets containing `@ / ? # :` work without hand-encoding.

**Tests always run against a local database.** `tests/conftest.py` forces
`localhost/cineai_test` regardless of what `.env` says, because the suite
`TRUNCATE`s every table on each run and the seat-race tests open many
concurrent connections. Override only with `TEST_AGAINST_REMOTE=1`, and only
against a database you can afford to lose. `make reset` refuses to run at all
unless the host is local.

---

## Configuration

Copy `.env.example` to `backend/.env`. Every value has a working local default,
so an empty file is valid. The knobs most worth turning:

| Variable | Default | Effect |
|---|---|---|
| `SEAT_HOLD_TTL_SECONDS` | `480` | Set it to `20` to watch expiry and reclamation happen live |
| `MOCK_GATEWAY_FAILURE_RATE` | `0.0` | Set it to `0.3` to exercise the failure and refund paths |
| `MAX_SEATS_PER_BOOKING` | `10` | Per-transaction cap |
| `ENABLE_SCHEDULER` | `true` | Turn off to watch lazy expiry work without the sweeper |

### `.env` is not gitignored

`backend/.env` holds the database password and **is not covered by
`.gitignore`** — a `git add -A` will commit it, and it has been committed to this
repository's history. If that history has been pushed anywhere, treat the
password as disclosed: rotate it in the provider console, and add
`backend/.env` to `.gitignore` before the next commit. Removing it from past
commits needs a history rewrite; rotating is what actually protects you.

### Two dependency sets

`requirements.txt` covers the booking platform. The help assistant needs three
more — `lancedb`, `sentence-transformers`, `pandas` — kept out on purpose
because they pull in PyTorch (~2 GB) and nothing else in the app wants it.
Install them only on a machine where you want the assistant, and see
[The help assistant](#the-help-assistant).

---

## Notes

- **Demo showtimes expire.** The seed fills a rolling 6-day window from the day
  it runs, so roughly a week later the site looks broken — films listed, nothing
  bookable. It is not broken; re-run `make seed`. Worth knowing before debugging
  a phantom.
- **Retiring a film means `status = 'archived'`**, not deleting it. Deleting
  cascades away shows, bookings and payments; archiving hides the title from
  every customer listing and search while keeping the history. `?status=archived`
  still returns them for the operator console.
- `pgvector` is installed by the setup script and enabled in migration `0001`,
  but nothing uses it. The ground is prepared; the design is not pre-made.
- The payment gateway is a **mock**. It signs real HMAC webhooks, dedupes
  replays, simulates latency and declines, and delivers events through the same
  handler a real PSP would — so swapping in Razorpay or Stripe is one class.
- Money is integer paise everywhere. Rupees exist only at the formatting edge.
