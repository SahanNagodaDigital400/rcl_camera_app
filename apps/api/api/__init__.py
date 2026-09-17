"""Rocell Tile Scanner API.

The FastAPI service: auth, scan submission, admin user/catalogue endpoints and
the audit log. All live Postgres and object-storage mutation flows through here
(AD-6, AD-9); `scripts/ingest` is the one explicitly pre-launch exception.

Today this is a skeleton with a single unauthenticated `/health` endpoint and
the shared error envelope already wired. Auth arrives in Story 1.3, the scan
path in Epic 2.
"""
