# ---------------------------------------------------------------------------
# CineAI — common tasks. Run `make` for the list.
# ---------------------------------------------------------------------------
SHELL := /bin/bash
PG_BIN := /opt/homebrew/opt/postgresql@18/bin
PY     := backend/.venv/bin/python
PIP    := backend/.venv/bin/pip
export PATH := $(PG_BIN):$(PATH)

.DEFAULT_GOAL := help
.PHONY: help setup setup-managed db-setup db-check install migrate migration seed reset api web dev test test-api test-web test-concurrency lint fmt check clean

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS=":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

setup: db-setup install migrate seed ## One-shot LOCAL setup: database, deps, schema, demo data
	@echo ""
	@echo "Ready. Run 'make dev' (or 'make api' and 'make web' in two shells)."

setup-managed: install db-check migrate seed ## Setup against a managed database (no role/db creation)
	@echo ""
	@echo "Ready. Run 'make dev'."

db-check: ## Show what the app is actually connected to (host, version, TLS)
	@cd backend && .venv/bin/python scripts_dbcheck.py

db-setup: ## Create the role, databases and extensions (needs a running Postgres)
	@bash scripts/setup_db.sh

install: ## Create the venv and install backend + frontend dependencies
	@test -d backend/.venv || python3 -m venv backend/.venv
	@$(PIP) install -q --upgrade pip
	@$(PIP) install -q -r backend/requirements-dev.txt
	@cd frontend && npm install --silent
	@echo "dependencies installed"

migrate: ## Apply database migrations
	@cd backend && .venv/bin/alembic upgrade head

migration: ## Autogenerate a migration:  make migration m="add x"
	@cd backend && .venv/bin/alembic revision --autogenerate -m "$(m)"

seed: ## Load the demo catalogue (cities, cinemas, films, shows, seats)
	@cd backend && .venv/bin/python scripts_seed.py

reset: ## Drop and rebuild the LOCAL databases from scratch, then reseed
	@cd backend && .venv/bin/python scripts_dbcheck.py --assert-local
	@psql -q -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname IN ('cineai','cineai_test') AND pid <> pg_backend_pid();" >/dev/null 2>&1 || true
	@dropdb --if-exists cineai && dropdb --if-exists cineai_test
	@$(MAKE) db-setup migrate seed

api: ## Run the API with reload on :8000
	@cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000

web: ## Run the frontend dev server on :5173
	@cd frontend && npm run dev

dev: ## Run API and frontend together
	@trap 'kill 0' EXIT; \
	(cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000) & \
	(cd frontend && npm run dev) & \
	wait

test: test-api test-web ## Run every test suite

test-api: ## Backend suite (always against a LOCAL cineai_test database)
	@cd backend && .venv/bin/python -m pytest -q

test-web: ## Frontend component tests
	@cd frontend && npm test --silent

test-concurrency: ## Run only the seat-race tests, verbosely
	@cd backend && .venv/bin/python -m pytest tests/concurrency -v

lint: ## Lint backend, typecheck and lint frontend
	@cd backend && .venv/bin/ruff check app tests
	@cd frontend && npx tsc -b --pretty false && npx oxlint src

fmt: ## Auto-format and auto-fix the backend
	@cd backend && .venv/bin/ruff check app tests --fix && .venv/bin/ruff format app tests

check: lint test ## Lint + test

clean: ## Remove build artefacts
	@find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
	@rm -rf frontend/dist backend/.pytest_cache
