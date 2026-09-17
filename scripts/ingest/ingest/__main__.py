"""`python -m ingest` — deliberately unimplemented, and loud about it."""

from __future__ import annotations

import sys

NOT_IMPLEMENTED_MESSAGE = (
    "ingest is not implemented yet: catalogue ingestion arrives with Epic 2 "
    "(Catalogue & Ingestion). This entrypoint exits non-zero on purpose so a "
    "pipeline can never mistake an empty skeleton for a completed ingest run."
)


def main() -> int:
    """Print what is missing and fail. Returns the process exit code."""
    print(NOT_IMPLEMENTED_MESSAGE, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
