"""Local demo server.

POC ONLY. No authentication, no sessions, no audit log, no rate limiting — the
production service requires all four, and none of it is stubbed here because a
half-built auth layer is worse than an obviously absent one. Binds to 127.0.0.1
by default; see --host before putting it on a network.
"""

from __future__ import annotations

import argparse
import io
import time
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from PIL import UnidentifiedImageError

from . import vision
from .search import DEFAULT_INDEX, TOP_K, IndexMismatch, Matcher

POC_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = Path(__file__).resolve().parent / "web"
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

app = FastAPI(title="Rocell Tile Scanner — POC")
_matcher: Matcher | None = None


def get_matcher() -> Matcher:
    global _matcher
    if _matcher is None:
        _matcher = Matcher(DEFAULT_INDEX)
    return _matcher


@app.get("/")
def home() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/info")
def info() -> dict:
    try:
        m = get_matcher()
    except (FileNotFoundError, IndexMismatch) as exc:
        return {"ready": False, "error": str(exc)}
    return {
        "ready": True,
        "images": m.n_images,
        "vectors": int(m.vectors.shape[0]),
        "products": len({r["product"] for r in m.references}),
        "pipeline_version": m.meta.get("pipeline_version"),
        "built_at": m.meta.get("built_at"),
    }


@app.get("/thumbs/{name}")
def thumb(name: str) -> FileResponse:
    # Resolve and confine to the thumbs directory: never let a path component
    # walk out of it, even in a POC.
    path = (DEFAULT_INDEX / "thumbs" / name).resolve()
    if not path.is_file() or (DEFAULT_INDEX / "thumbs").resolve() not in path.parents:
        raise HTTPException(404, "not found")
    return FileResponse(path)


@app.post("/api/scan")
async def scan(file: UploadFile = File(...)) -> JSONResponse:
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "empty upload")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "image too large")

    try:
        m = get_matcher()
    except (FileNotFoundError, IndexMismatch) as exc:
        raise HTTPException(503, str(exc)) from exc

    started = time.time()
    try:
        # Content is sniffed by the shared intake path, never trusted from the
        # filename or the declared content-type.
        img = vision.load_image(io.BytesIO(raw))
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(400, f"not a readable image: {type(exc).__name__}") from exc

    cands = m.search(img, k=TOP_K)
    return JSONResponse({
        "elapsed_ms": round((time.time() - started) * 1000),
        "candidates": [c.as_dict() for c in cands],
    })


def main(argv: list[str] | None = None) -> int:
    import uvicorn

    p = argparse.ArgumentParser(description="Run the POC demo server.")
    p.add_argument("--host", default="127.0.0.1",
                   help="use 0.0.0.0 to reach it from a phone on the same LAN")
    p.add_argument("--port", type=int, default=8000)
    a = p.parse_args(argv)

    try:
        i = info()
        if i.get("ready"):
            print(f"index: {i['images']} images / {i['vectors']} vectors / {i['products']} products")
        else:
            print(f"⚠ index not ready: {i.get('error')}")
    except Exception as exc:
        print(f"⚠ {exc}")

    print(f"\n  http://{'localhost' if a.host == '127.0.0.1' else a.host}:{a.port}\n")
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
