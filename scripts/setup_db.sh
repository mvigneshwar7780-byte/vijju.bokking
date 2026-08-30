#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Bootstrap the CineAI databases.
#
# Run this ONCE, as your macOS user (which Homebrew made a Postgres superuser).
# It creates the app role, the dev and test databases, and the extensions.
#
# The extensions have to be created by a superuser: pgvector is not a "trusted"
# extension in the Homebrew build, so the unprivileged `cineai` role cannot
# install it itself. Migrations then run happily as `cineai` because
# `CREATE EXTENSION IF NOT EXISTS` short-circuits when the extension is present.
# ---------------------------------------------------------------------------
set -euo pipefail

PG_BIN="${PG_BIN:-/opt/homebrew/opt/postgresql@18/bin}"
export PATH="$PG_BIN:$PATH"

DB_USER="${POSTGRES_USER:-cineai}"
DB_PASSWORD="${POSTGRES_PASSWORD:-cineai_dev_pw}"
DB_NAME="${POSTGRES_DB:-cineai}"
TEST_DB_NAME="${POSTGRES_TEST_DB:-cineai_test}"

if ! pg_isready -q; then
  echo "PostgreSQL is not running. Start it with:"
  echo "    brew services start postgresql@18"
  exit 1
fi

echo "==> Creating role '$DB_USER' (if absent)"
psql -d postgres -v ON_ERROR_STOP=1 <<SQL
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$DB_USER') THEN
    CREATE ROLE $DB_USER LOGIN PASSWORD '$DB_PASSWORD' CREATEDB;
  END IF;
END \$\$;
SQL

for db in "$DB_NAME" "$TEST_DB_NAME"; do
  if psql -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$db'" | grep -q 1; then
    echo "==> Database '$db' already exists"
  else
    echo "==> Creating database '$db'"
    createdb -O "$DB_USER" "$db"
  fi

  echo "==> Enabling extensions in '$db'"
  psql -d "$db" -v ON_ERROR_STOP=1 -q <<'SQL'
CREATE EXTENSION IF NOT EXISTS vector;      -- pgvector: semantic search & recs
CREATE EXTENSION IF NOT EXISTS pg_trgm;     -- fuzzy/typo-tolerant title search
CREATE EXTENSION IF NOT EXISTS pgcrypto;    -- gen_random_bytes for tokens
CREATE EXTENSION IF NOT EXISTS btree_gist;  -- EXCLUDE constraints on ranges
SQL
done

echo
echo "==> Done. Extensions installed:"
psql -d "$DB_NAME" -tAc "SELECT extname || ' ' || extversion FROM pg_extension ORDER BY extname" | sed 's/^/    /'
echo
echo "Next:  cd backend && make migrate && make seed"
