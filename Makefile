# Rocell Tile Scanner — one entry point for every workflow in the monorepo.
#
# Python lives in a single uv workspace (apps/api, infra, shared/vision,
# shared/schema, scripts/ingest); the front end is npm in apps/web. `poc/` is a
# standalone proof of concept with its own Makefile and venv and is never
# touched here.

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
	@echo "                   -- needs DATABASE_URL and OBJECT_STORAGE_ROOT; the first is"
	@echo "                      read at startup, the second at the first catalogue write"
	@echo "  make lint        ruff check + ruff format --check, oxlint, tsc --noEmit"
	@echo "  make test        the pytest workspace suite and the apps/web vitest suite"
	@echo "  make build       production build of apps/web"
	@echo "  make model       download the ONNX backbone shared/vision embeds with"
	@echo "                   -- ~346 MB, once per machine, pinned revision +"
	@echo "                      sha256 check; pass FROM=path to adopt an existing copy"
	@echo "  make format      apply ruff's formatting and import fixes"
	@echo "  make certs       self-signed cert so make dev serves the web app over"
	@echo "                   HTTPS -- required by Safari, which drops the Secure"
	@echo "                      session cookie over plain http://localhost, and by"
	@echo "                      any handset (getUserMedia needs a secure context)"
	@echo ""
	@echo "  database (needs DATABASE_URL; see infra/README.md):"
	@echo "  make migrate     apply every unapplied migration"
	@echo "                   -- also SEED_ADMIN_* on the first run, and the role"
	@echo "                      needs CREATEROLE (see infra/README.md)"
	@echo "  make reseed-admin"
	@echo "                   reissue the seeded Administrator's temporary credential"
	@echo ""
	@echo "  no make target; run the runner directly:"
	@echo "    uv run python -m rocell_infra.migrate status"
	@echo "    uv run python -m rocell_infra.migrate down --yes"
	@echo ""
	@echo "  not implemented yet (each exits non-zero rather than reporting success):"
	@echo "  make ingest      run catalogue ingestion     -- Epic 2"
	@echo "  make eval        accuracy harness            -- Epic 2"

setup:
	$(UV) sync
	$(WEB) install

# Starts the API in the background and the web dev server in the foreground.
# Only the API's own pid is signalled on exit: `kill 0` would signal the whole
# process group, taking a parent make or CI shell down with it.
#
# Since Story 1.3, apps/api opens a connection pool at startup and reads
# DATABASE_URL to do it — never defaulted, for the reason the database targets
# below give. That is now the commonest way the API exits during startup, so
# the health gate names it first.
#
# Since Story 2.1 it also needs OBJECT_STORAGE_ROOT, which is *not* read at
# startup: `api.storage` builds the store per request, so a missing value is a
# 500 on the first `POST /admin/tiles` rather than a service that will not
# boot. Deliberate — the scan and admin-user surfaces work without it — but it
# means the failure arrives at the worst moment unless it is set up front, so
# `make dev` says so rather than waiting for it.
dev:
	@scheme=http; [ -f $(CERT_DIR)/server.crt ] && scheme=https; \
	echo "api -> http://127.0.0.1:$(API_PORT)   web -> $$scheme://localhost:5173 (Ctrl-C stops both)"; \
	if [ "$$scheme" = http ]; then \
	  echo "note: no dev cert -- run \`make certs\` if sign-in drops straight back to the login screen (Safari)."; \
	fi
	@if [ -z "$$OBJECT_STORAGE_ROOT" ]; then \
	  echo "note: OBJECT_STORAGE_ROOT is unset — adding a tile will fail. See README.md."; \
	fi
	@$(UV) run uvicorn api.main:app --reload --port $(API_PORT) & \
	api_pid=$$!; \
	trap 'pkill -P $$api_pid 2>/dev/null; kill $$api_pid 2>/dev/null; true' EXIT INT TERM; \
	for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do \
	  kill -0 $$api_pid 2>/dev/null || { echo "apps/api exited during startup (DATABASE_URL unset, port $(API_PORT) busy, or an import error) -- see the output above"; exit 1; }; \
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

# --- Model ------------------------------------------------------------------
# shared/vision cannot embed anything without the DINOv2-base ONNX export, and
# 346 MB of weights never enter git. Fetched once per machine at a pinned
# revision with a sha256 check (scripts/fetch_model.py says why both matter).
# Re-running it is cheap: a matching file is left alone.
#
# FROM=poc/models/model.onnx adopts a copy already on the machine — the POC
# pulls the same artifact at the same revision — and verifies it against the
# same digest rather than trusting the path.
model:
	$(UV) run python scripts/fetch_model.py $(FROM)

# --- Dev TLS -----------------------------------------------------------------
# The session cookie is `Secure` with no development exemption (AGENTS.md
# Policy). Chrome and Firefox exempt `http://localhost` from that requirement,
# so plain HTTP worked there; Safari does not, and drops the cookie silently --
# sign-in succeeds and every authenticated request after it answers 401. Rather
# than weaken the flag for one browser, `make dev` serves the front end over
# HTTPS as soon as this target has run.
#
# Also the prerequisite for testing on a real handset, twice over: a LAN IP is
# not a trustworthy origin in any browser, and `getUserMedia` refuses to run
# outside a secure context -- so without this there is no camera to test with.
#
# Self-signed and per-machine: the key is gitignored and never shared. macOS
# ships LibreSSL, whose `req` has no `-addext`, so Homebrew's OpenSSL 3 is used
# when it is present -- a certificate without a subjectAltName is rejected
# outright by every current browser.
CERT_DIR := apps/web/certs
OPENSSL   = $(shell [ -x /opt/homebrew/opt/openssl@3/bin/openssl ] && \
                    echo /opt/homebrew/opt/openssl@3/bin/openssl || echo openssl)

certs:
	@mkdir -p $(CERT_DIR)
	@lan=$$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null); \
	san="DNS:localhost,IP:127.0.0.1,IP:::1"; \
	if [ -n "$$lan" ]; then san="$$san,IP:$$lan"; echo "$$lan" > $(CERT_DIR)/issued-for.txt; fi; \
	$(OPENSSL) req -x509 -newkey rsa:2048 -nodes \
	  -keyout $(CERT_DIR)/server.key -out $(CERT_DIR)/server.crt \
	  -days 825 -subj "/CN=localhost" \
	  -addext "subjectAltName=$$san" \
	  -addext "basicConstraints=critical,CA:FALSE" \
	  -addext "keyUsage=critical,digitalSignature,keyEncipherment" \
	  -addext "extendedKeyUsage=serverAuth" 2>/dev/null; \
	chmod 600 $(CERT_DIR)/server.key; \
	echo "wrote $(CERT_DIR)/server.{key,crt} for $$san"
	@echo "the cert is self-signed: accept it once per browser, or trust it with"
	@echo "  security add-trusted-cert -r trustRoot -k ~/Library/Keychains/login.keychain-db $(CERT_DIR)/server.crt"

# --- Database ----------------------------------------------------------------
# DATABASE_URL is required by both and is never defaulted here: a migration
# runner that guesses a connection string can migrate the wrong database.
# Seeding the first Administrator additionally needs SEED_ADMIN_EMAIL and
# SEED_ADMIN_PASSWORD (and optionally SEED_ADMIN_NAME) — see infra/README.md.
#
# Since 20260921T1000_create_audit_log the migrating role additionally needs
# CREATEROLE (or superuser): that migration creates `rocell_app`, the role
# apps/api runs as, and grants it. Write access to the database is no longer
# enough, and the failure is a permission error from the CREATE ROLE rather
# than anything this Makefile can explain.

migrate:
	$(UV) run python -m rocell_infra.migrate up

reseed-admin:
	$(UV) run python -m rocell_infra.migrate reseed-admin

# --- Not implemented yet -----------------------------------------------------
# These fail loudly on purpose. A target that printed nothing and exited 0 would
# let a later story mistake "did nothing" for "already done".

ingest:
	@echo "make ingest is not implemented yet: catalogue ingestion arrives with Epic 2"
	@echo "(Catalogue & Ingestion). scripts/ingest is a skeleton."
	@exit 1

eval:
	@echo "make eval is not implemented yet: the accuracy harness arrives with Epic 2."
	@echo "shared/vision now holds the ported pipeline (Story 2.1) and apps/api writes"
	@echo "the index, but the held-out set of real staff photos it scores against does"
	@echo "not exist in this repository yet."
	@echo "Until then, poc/ has the working harness (see poc/Makefile)."
	@exit 1

.PHONY: help setup dev lint format test build model certs migrate reseed-admin ingest eval
