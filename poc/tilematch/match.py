"""CLI entry point: `python -m tilematch.match photo.jpg`."""

from .search import main

if __name__ == "__main__":
    raise SystemExit(main())
