.DEFAULT_GOAL := help

help:
	@echo "  make dev      run apps/api (uvicorn) and apps/web (vite) with hot reload"
	@echo "  make lint     ruff (Python) + eslint/tsc (apps/web)"
	@echo "  make test     pytest (Python workspace) + vitest (apps/web)"
	@echo "  make migrate  apply pending Postgres migrations (requires DATABASE_URL, SEED_ADMIN_EMAIL, SEED_ADMIN_NAME, SEED_ADMIN_PASSWORD)"

dev:
	@trap 'kill 0' EXIT; \
	uv run --project apps/api uvicorn app.main:app --reload --app-dir apps/api & \
	(cd apps/web && npm run dev) & \
	wait

PY_DIRS := apps/api shared/vision shared/schema scripts/ingest infra

lint:
	uv run ruff check $(PY_DIRS)
	cd apps/web && npm run lint

test:
	@status=0; \
	uv run pytest || status=1; \
	(cd apps/web && npm test) || status=1; \
	exit $$status

migrate:
	uv run --project infra python infra/migrate.py

.PHONY: help dev lint test migrate
