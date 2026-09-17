# Rocell Tile Scanner — one entry point for every workflow in the monorepo.
#
# Python lives in a single uv workspace (apps/api, shared/vision, shared/schema,
# scripts/ingest); the front end is npm in apps/web. `poc/` is a standalone
# proof of concept with its own Makefile and venv and is never touched here.

UV  := uv
WEB := npm --prefix apps/web
API_PORT ?= 8000

# apps/web/vite.config.ts reads this for its dev proxy target, so overriding
# API_PORT moves both halves together or neither.
export API_PORT

.DEFAULT_GOAL := help

help:
	@echo "  make setup       create the uv workspace venv and install apps/web deps"
	@echo "  make dev         run apps/api (:$(API_PORT)) and apps/web (:5173) with hot reload"
	@echo "  make lint        ruff check + ruff format --check, oxlint, tsc --noEmit"
	@echo "  make test        the pytest workspace suite and the apps/web vitest suite"
	@echo "  make build       production build of apps/web"
	@echo "  make format      apply ruff's formatting and import fixes"
	@echo ""
	@echo "  not implemented yet (each exits non-zero rather than reporting success):"
	@echo "  make migrate     apply migrations            -- Story 1.2"
	@echo "  make ingest      run catalogue ingestion     -- Epic 2"
	@echo "  make eval        accuracy harness            -- Epic 2"

setup:
	$(UV) sync
	$(WEB) install

# Starts the API in the background and the web dev server in the foreground.
# Only the API's own pid is signalled on exit: `kill 0` would signal the whole
# process group, taking a parent make or CI shell down with it.
dev:
	@echo "api -> http://127.0.0.1:$(API_PORT)   web -> http://localhost:5173 (Ctrl-C stops both)"
	@$(UV) run uvicorn api.main:app --reload --port $(API_PORT) & \
	api_pid=$$!; \
	trap 'pkill -P $$api_pid 2>/dev/null; kill $$api_pid 2>/dev/null; true' EXIT INT TERM; \
	for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do \
	  kill -0 $$api_pid 2>/dev/null || { echo "apps/api exited during startup (port $(API_PORT) busy, or an import error) -- see the output above"; exit 1; }; \
	  curl -fsS -o /dev/null http://127.0.0.1:$(API_PORT)/health && break; \
	  sleep 1; \
	done; \
	curl -fsS -o /dev/null http://127.0.0.1:$(API_PORT)/health || { echo "apps/api did not answer /health -- not starting the web dev server against a dead backend"; exit 1; }; \
	$(WEB) run dev

lint:
	$(UV) run ruff check .
	$(UV) run ruff format --check .
	$(WEB) run lint
	$(WEB) run typecheck

format:
	$(UV) run ruff check --fix .
	$(UV) run ruff format .

test:
	$(UV) run pytest
	$(WEB) run test

build:
	$(WEB) run build

# --- Not implemented yet -----------------------------------------------------
# These fail loudly on purpose. A target that printed nothing and exited 0 would
# let a later story mistake "did nothing" for "already done".

migrate:
	@echo "make migrate is not implemented yet: migrations arrive with Story 1.2"
	@echo "(User Schema & Seeded Administrator). infra/migrations/ is empty by design."
	@exit 1

ingest:
	@echo "make ingest is not implemented yet: catalogue ingestion arrives with Epic 2"
	@echo "(Catalogue & Ingestion). scripts/ingest is a skeleton."
	@exit 1

eval:
	@echo "make eval is not implemented yet: the accuracy harness arrives with Epic 2,"
	@echo "once shared/vision holds the ported pipeline and an index exists to score."
	@echo "Until then, poc/ has the working harness (see poc/Makefile)."
	@exit 1

.PHONY: help setup dev lint format test build migrate ingest eval
