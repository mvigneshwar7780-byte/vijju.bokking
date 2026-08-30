# Moving this project to a Windows PC

Start to finish. Every command below was checked against the actual repo; where
something could not be verified from macOS it says so explicitly.

**The database stays where it is.** It lives on Aiven (PostgreSQL 18.6), so the
Windows machine talks to the *same* database over the internet. There is no
database to install, migrate or seed on the far side — that is the whole reason
this is a short guide rather than a long one.

---

## Part A — On the Mac

### A1. Commit first

The repository has **zero commits**. Everything is untracked, so there is no
undo if anything goes wrong on either machine. Two minutes now:

```bash
cd "/Users/lakshmi.mudireddy/store/R&D/AI_Learning/cineai"
git add -A
git commit -m "Movie booking platform: baseline before Windows port"
```

`.env` and `certs/*.pem` are gitignored, so no secret is committed. Verify:

```bash
git show --stat HEAD | grep -E "\.env|\.pem"   # should print nothing
```

### A2. Build the archive

**Exclude `.venv` and `node_modules`.** Together they are 395 MB of macOS/arm64
binaries — a Python venv with absolute shebang paths, and native builds of
esbuild, rollup and oxlint. None of it can run on Windows; all of it is rebuilt
from the lockfiles on the far side.

```bash
cd "/Users/lakshmi.mudireddy/store/R&D/AI_Learning"
zip -r cineai.zip cineai \
  -x '*/.venv/*' '*/node_modules/*' '*/__pycache__/*' \
     '*/.pytest_cache/*' '*/.ruff_cache/*' '*/dist/*' '*/.DS_Store'
```

**Measured result: 394 KB, 244 files** (down from 398 MB).

### A3. Check what you are about to send

```bash
unzip -l cineai.zip | grep -E "\.env$|aiven-ca\.pem|package-lock\.json"
```

All three must be listed:

| File | Why it must travel | Sensitive? |
|---|---|---|
| `backend/.env` | Aiven host, user, **password** | **Yes — live DB password** |
| `backend/certs/aiven-ca.pem` | Required by `sslmode=verify-full` | No — public CA cert |
| `frontend/package-lock.json` | Exact dependency versions | No |

The first two are gitignored, so a `git clone` will **not** have them. A zip
ignores `.gitignore`, which is exactly why the zip route works — but it means
this file carries a live database password.

### A4. Transfer it

**Do not** put this zip in a shared drive, Slack, email or any chat. Use a USB
stick, AirDrop, or a direct machine-to-machine transfer.

If you would rather use a private GitHub repo (better — you get history and a
real undo), push the code there and move **only these two files** by USB:

```
backend/.env
backend/certs/aiven-ca.pem
```

---

## Part B — On the Windows PC

### B1. Install the prerequisites

| | Version | Notes |
|---|---|---|
| **Python** | **3.14** — do **not** use 3.11 | `numpy==2.5.2` declares `Requires-Python >=3.12`, so 3.11 fails the install part-way. Tick **"Add python.exe to PATH"** |
| **Node.js** | 22 LTS or newer | The Mac runs 26.8.1 |
| **PostgreSQL** | 16+ | **Only if you want to run the backend test suite.** Skip for now — see B7 |

Confirm both are on PATH:

```powershell
py -3.14 --version
node --version
npm --version
```

> **Dependency check, already done for you.** Every pinned package in
> `requirements.txt` has a prebuilt Windows wheel for CPython 3.14 — verified
> against PyPI: `psycopg-binary 3.3.4` (`cp314-win_amd64`), `orjson 3.12.0`,
> `numpy 2.5.2`, `argon2-cffi-bindings` (`cp310-abi3`, valid on 3.14), `cffi`,
> `Pillow`. **No Visual Studio Build Tools needed.** `uvloop`, which is
> POSIX-only, is correctly gated behind `sys_platform != "win32"` in
> `uvicorn[standard]`, so pip skips it silently on Windows.

### B2. Unpack

Extract `cineai.zip` somewhere without spaces or OneDrive sync — e.g. `C:\dev\`:

```
C:\dev\cineai\
```

**Avoid `C:\Users\<you>\OneDrive\...`** — OneDrive's file-on-demand sync
interferes with Vite's file watcher and with `node_modules`.

### B3. Backend dependencies

```powershell
cd C:\dev\cineai\backend
py -3.14 -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\pip install -r requirements-dev.txt
```

Windows uses `.venv\Scripts\` where macOS uses `.venv/bin/`. That single
difference accounts for most of the divergence from the Makefile.

### B4. Confirm the database connection *before* anything else

This is the step that tells you whether the transfer worked. Run it from
`backend\` — the scripts insert `"."` on the import path, so the working
directory matters, and `POSTGRES_SSLROOTCERT=certs/aiven-ca.pem` is relative to
it.

```powershell
cd C:\dev\cineai\backend
.venv\Scripts\python scripts_dbcheck.py
```

Expected — this is the real output from the Mac, and Windows should match it
line for line:

```
  host       : avnadmin@pg-368ac8e6-...h.aivencloud.com:19798/defaultdb (sslmode=verify-full)
  postgres   : 18.6
  TLS        : yes
  extensions : btree_gist, pg_trgm, pgcrypto, plpgsql, vector
  uuidv7     : native
  pool max   : 10 connections
```

If **`TLS: yes`** and **`postgres: 18.6`** appear, you are done with the hard
part. Failures are almost always one of:

| Symptom | Cause |
|---|---|
| `could not open certificate file` | Not run from `backend\`, or `certs\aiven-ca.pem` did not come across |
| `certificate verify failed` | `aiven-ca.pem` corrupted in transfer (check it is 1,541 bytes) |
| `password authentication failed` | `.env` did not come across, or was truncated |
| `timeout` / `could not connect` | Corporate firewall blocking outbound port 19798 |

### B5. Do **not** migrate or seed

```
DO NOT RUN:  alembic upgrade head
DO NOT RUN:  python scripts_seed.py
```

Both machines point at the **same** Aiven database. Migrations `0001`–`0005` are
already applied, and the demo catalogue is already loaded. Seeding again is not
destructive — it is upsert-shaped, with no `TRUNCATE` or `DROP` — but it would
append another run of showtimes and muddle the data your Mac is using.

Run them only if you later give Windows its own database (B8).

### B6. Frontend dependencies, then run it

```powershell
cd C:\dev\cineai\frontend
npm ci
```

`npm ci` rather than `npm install` — the lockfile is in the zip, so you get the
exact versions the Mac has.

Now start both halves, in **two separate terminals** (there is no `make dev` on
Windows to run them together):

```powershell
# Terminal 1 — API
cd C:\dev\cineai\backend
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

```powershell
# Terminal 2 — web
cd C:\dev\cineai\frontend
npm run dev
```

Open <http://localhost:5173> and sign in as `demo@cineai.example` /
`demopass1`. Swagger is at <http://localhost:8000/docs>.

If the movie list loads, everything works: the browser reached Vite, Vite
proxied `/api` to uvicorn, and uvicorn reached Aiven over TLS.

### B7. Tests (optional, needs a local PostgreSQL)

Frontend tests need nothing extra:

```powershell
cd C:\dev\cineai\frontend
npm test          # 13 tests
```

**Backend tests require PostgreSQL installed locally on the Windows box.**
`tests/conftest.py` deliberately forces `localhost/cineai_test` no matter what
`.env` says, because the suite `TRUNCATE`s every table and the seat-race tests
open many concurrent connections — pointed at Aiven, it would destroy your data.
That guard is a feature; do not defeat it.

To enable them: install PostgreSQL 16+, then

```powershell
createdb -U postgres cineai_test
cd C:\dev\cineai\backend
.venv\Scripts\python -m pytest -q       # 102 tests
```

If you only want to *use* the app, skip this entirely.

### B8. Optional — give Windows its own database

If you plan to experiment freely and would rather not touch the data the Mac is
using, create a second database on the same Aiven instance (`avnadmin` has
permission):

```powershell
# from the Aiven console, or:
.venv\Scripts\python -c "import psycopg,os; c=psycopg.connect(os.environ['ADMIN_URL'],autocommit=True); c.execute('CREATE DATABASE cineai_lab')"
```

Then point `backend\.env` at it with `POSTGRES_DB=cineai_lab`, and **now** run
`alembic upgrade head` and `python scripts_seed.py` to build it out.

Note the connection budget: the Aiven plan caps **20 connections total**, and
each running API process takes up to 10 (`DB_POOL_SIZE 5` + `DB_MAX_OVERFLOW 5`).
Two machines running the API at once is fine; three starts to crowd it.

---

## Makefile → PowerShell

There is no `make` on Windows, and the Makefile hard-codes `SHELL := /bin/bash`
plus a Homebrew Postgres path. Equivalents:

| `make` target | PowerShell, from the stated directory |
|---|---|
| `make install` | `backend`: `py -3.14 -m venv .venv; .venv\Scripts\pip install -r requirements-dev.txt`<br>`frontend`: `npm ci` |
| `make db-check` | `backend`: `.venv\Scripts\python scripts_dbcheck.py` |
| `make api` | `backend`: `.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000` |
| `make web` | `frontend`: `npm run dev` |
| `make dev` | No equivalent — use two terminals |
| `make migrate` | `backend`: `.venv\Scripts\alembic upgrade head` |
| `make seed` | `backend`: `.venv\Scripts\python scripts_seed.py` |
| `make test-api` | `backend`: `.venv\Scripts\python -m pytest -q` *(needs local Postgres)* |
| `make test-web` | `frontend`: `npm test` |
| `make lint` | `backend`: `.venv\Scripts\ruff check app tests`<br>`frontend`: `npx tsc -b --pretty false; npx oxlint src` |
| `make fmt` | `backend`: `.venv\Scripts\ruff check app tests --fix; .venv\Scripts\ruff format app tests` |
| `make reset` | **Do not run.** It drops databases and refuses non-local hosts anyway |

**WSL2 is the smoother path** if you have it: `make` and every target above work
as written, and only `PG_BIN` in the Makefile needs changing.

---

## Fixed for Windows in advance

Two real blockers were found by auditing the repo for this move, and both are
already fixed — you will not hit either.

### The backend test suite could not run at all

`backend/tests/conftest.py` invoked Alembic through a hardcoded POSIX path,
`BACKEND_ROOT / ".venv/bin/alembic"`. Windows puts console scripts in
`.venv\Scripts\` as `alembic.exe`, so that path does not exist. Because the
fixture is `scope="session", autouse=True`, **every one of the 102 tests would
have errored** before a single test body ran:

```
FileNotFoundError: [WinError 2] The system cannot find the file specified
```

It now runs `[sys.executable, "-m", "alembic", "upgrade", "head"]`, which is
correct on every platform and does not assume the venv is at `backend/.venv`.
Verified on macOS after the change: **102 passed**.

### The `@` import alias


`vite.config.ts` and `vitest.config.ts` resolved the `@` import alias with
`new URL('./src', import.meta.url).pathname`. On Windows that returns
`/C:/dev/cineai/frontend/src` — a **leading slash before the drive letter** —
which Vite cannot resolve, so **every `@/…` import in the app would have failed**
with `Failed to resolve import "@/api/client"`. Both files now use
`fileURLToPath(new URL(...))`, which is correct on all platforms.

Verified on macOS after the change: `vite build` transforms 159 modules and all
13 frontend tests pass, so the fix is portable rather than a Windows special case.

---

## What is genuinely different on Windows

| | macOS | Windows |
|---|---|---|
| Venv binaries | `.venv/bin/` | `.venv\Scripts\` |
| Task runner | `make` | none — run commands directly, or use WSL2 |
| Running both servers | `make dev` | two terminals |
| `uvloop` | installed | skipped (POSIX-only, correctly gated) |
| Backend tests | local Postgres via Homebrew | local Postgres install required |
| Running the app | needs no local database | needs no local database |

Everything else — the API, the frontend, the Aiven connection, TLS verification,
migrations — behaves identically, because none of it touches the filesystem in a
platform-specific way.
