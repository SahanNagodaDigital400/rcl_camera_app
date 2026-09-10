"""FastAPI service entrypoint.

Story 1.1 scope: a runnable skeleton only. Auth, scan submission, admin
endpoints, and the audit log land in later stories (see AGENTS.md Policy
and ARCHITECTURE-SPINE.md's Capability -> Architecture Map).
"""

from fastapi import FastAPI

app = FastAPI(title="Rocell Tile Identification API")


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe -- proves the adapter boots."""
    return {"status": "ok"}
