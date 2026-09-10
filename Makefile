.DEFAULT_GOAL := help

help:
	@echo "  make dev      run apps/api (uvicorn) and apps/web (vite) with hot reload"
	@echo "  make lint     ruff (Python) + eslint/tsc (apps/web)"
	@echo "  make test     pytest (Python workspace) + vitest (apps/web)"

dev:
	@trap 'kill 0' EXIT; \
	uv run --project apps/api uvicorn app.main:app --reload --app-dir apps/api & \
	(cd apps/web && npm run dev) & \
	wait

PY_DIRS := apps/api shared/vision shared/schema scripts/ingest

lint:
	uv run ruff check $(PY_DIRS)
	cd apps/web && npm run lint

test:
	uv run pytest
	cd apps/web && npm test

.PHONY: help dev lint test
