"""Local demo server.

POC ONLY. No authentication, no sessions, no audit log, no rate limiting — the
production service requires all four, and none of it is stubbed here because a
half-built auth layer is worse than an obviously absent one. Binds to 127.0.0.1
by default; see --host before putting it on a network.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import itertools
import logging
import subprocess
import time
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image, UnidentifiedImageError

from . import vision
from .search import DEFAULT_INDEX, TOP_K, IndexMismatch, Matcher

POC_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = Path(__file__).resolve().parent / "web"
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

# Full-size reference views for on-screen verification. The originals run to
# 96 MB, so they are downscaled on first request and cached — staff need enough
# detail to confirm a match, not the print master.
# 1280/q82 progressive is 85 KB against 205 KB at 1600/q88, and 37 dB PSNR
# between them — indistinguishable by eye, and less than half the wait on 4G.
REFERENCE_MAX_EDGE = 1280
REFERENCE_QUALITY = 82
REFERENCE_CACHE = DEFAULT_INDEX / "refs"

# A rebuilt index writes new bytes to the same names, but within a session these
# never change, and re-fetching them is what made thumbnails flaky over a tunnel.
IMMUTABLE = {"Cache-Control": "public, max-age=86400"}

# How many candidates the page shows outright, and how many the API returns.
# Deliberately independent of search.TOP_K, which stays at 3 because the eval
# harness scores against it — displaying more must not quietly turn a top-3
# accuracy number into a top-10 one.
DISPLAY_K = 3
MAX_CANDIDATES = 20

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-5s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("tilematch")

# Scans are serialised. Inference already saturates every performance core, so
# running two at once shortens neither — it just thrashes. Measured with 8
# concurrent requests: 206 ms each became 2.6 s each, a 12x collapse that reads
# as "stuck" on the phone. Queueing keeps each scan fast and the wait visible.
_scan_slot = asyncio.Semaphore(1)
_request_ids = itertools.count(1)

app = FastAPI(title="Rocell Tile Scanner — POC")
_matcher: Matcher | None = None


def get_matcher() -> Matcher:
    global _matcher
    if _matcher is None:
        _matcher = Matcher(DEFAULT_INDEX)
    return _matcher


def build_stamp() -> str:
    """Short hash of everything that decides what the page shows.

    Covers the display config as well as the markup: a change to DISPLAY_K
    alters the results screen without touching index.html, and a stamp that
    missed it would report "current" while the user looked at something else.
    """
    h = hashlib.sha256((WEB_DIR / "index.html").read_bytes())
    h.update(f"|display_k={DISPLAY_K}|max={MAX_CANDIDATES}".encode())
    return h.hexdigest()[:7]


@app.get("/")
def home() -> FileResponse:
    # no-store, not just no-cache: a phone holding a stale copy of this page is
    # indistinguishable from a broken feature, and this is a dev server where
    # freshness beats a saved round trip every time.
    return FileResponse(
        WEB_DIR / "index.html",
        headers={"Cache-Control": "no-store, must-revalidate", "Pragma": "no-cache"},
    )


@app.get("/api/info")
def info() -> dict:
    try:
        m = get_matcher()
    except (FileNotFoundError, IndexMismatch) as exc:
        return {"ready": False, "build": build_stamp(), "error": str(exc)}
    return {
        "ready": True,
        "build": build_stamp(),
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
    return FileResponse(path, headers=IMMUTABLE)


@app.post("/api/client-log")
async def client_log(payload: dict) -> dict:
    """Surface browser-side failures in the server log.

    A phone testing over a tunnel has no reachable console, so a client error is
    otherwise completely invisible — which is how a canvas allocation failure
    passed for "no response from server".
    """
    kind = str(payload.get("kind", "?"))[:60]
    detail = str(payload.get("detail", ""))[:500]
    log.warning("[client] %s: %s", kind, detail)
    return {"ok": True}


@app.get("/reference/{ref_id}")
def reference(ref_id: int) -> FileResponse:
    """A verification-sized view of one reference image, generated on demand."""
    try:
        m = get_matcher()
    except (FileNotFoundError, IndexMismatch) as exc:
        raise HTTPException(503, str(exc)) from exc
    if not 0 <= ref_id < m.n_images:
        raise HTTPException(404, "no such reference")

    REFERENCE_CACHE.mkdir(parents=True, exist_ok=True)
    cached = REFERENCE_CACHE / f"{ref_id:04d}.jpg"
    if not cached.exists():
        # `make index` / `make thumbs` pre-generate these. Reaching here means one
        # is missing, so build it now rather than 404 — but log it, because
        # decoding an original can take seconds and the user is watching.
        log.warning("reference %d not pre-generated; building on demand", ref_id)
        t = time.perf_counter()
        ref = m.references[ref_id]
        src = POC_ROOT / m.meta.get("tiles_dir", "Tiles") / ref["relpath"]
        if not src.is_file():
            raise HTTPException(404, "reference file missing")
        img = vision.load_image(src)
        if max(img.size) > REFERENCE_MAX_EDGE:
            k = REFERENCE_MAX_EDGE / max(img.size)
            img = img.resize((round(img.width * k), round(img.height * k)), Image.Resampling.LANCZOS)
        img.save(cached, "JPEG", quality=REFERENCE_QUALITY, optimize=True, progressive=True)
        log.warning("  built reference %d in %.0f ms", ref_id, (time.perf_counter() - t) * 1000)
    return FileResponse(cached, headers=IMMUTABLE)


@app.post("/api/scan")
async def scan(file: UploadFile = File(...)) -> JSONResponse:
    rid = next(_request_ids)
    arrived = time.perf_counter()
    # Logged on arrival, not on completion. A request that never finished used to
    # produce no log line at all — precisely the case worth being able to see.
    log.info("[%04d] scan received", rid)

    raw = await file.read()
    if not raw:
        log.warning("[%04d] rejected: empty upload", rid)
        raise HTTPException(400, "empty upload")
    if len(raw) > MAX_UPLOAD_BYTES:
        log.warning("[%04d] rejected: %.1f MB over the %.0f MB limit",
                    rid, len(raw) / 1e6, MAX_UPLOAD_BYTES / 1e6)
        raise HTTPException(413, "image too large")
    log.info("[%04d] upload complete: %.0f KB in %.0f ms",
             rid, len(raw) / 1024, (time.perf_counter() - arrived) * 1000)

    try:
        m = get_matcher()
    except (FileNotFoundError, IndexMismatch) as exc:
        log.error("[%04d] index unavailable: %s", rid, exc)
        raise HTTPException(503, str(exc)) from exc

    queued = time.perf_counter()
    if _scan_slot.locked():
        log.info("[%04d] queued behind a running scan", rid)
    async with _scan_slot:
        wait_ms = (time.perf_counter() - queued) * 1000
        if wait_ms > 50:
            log.info("[%04d] started after %.0f ms in the queue", rid, wait_ms)
        return await _run_scan(rid, m, raw, wait_ms)


async def _run_scan(rid: int, m: Matcher, raw: bytes, wait_ms: float) -> JSONResponse:
    started = time.perf_counter()
    try:
        # Content is sniffed by the shared intake path, never trusted from the
        # filename or the declared content-type.
        img = await run_in_threadpool(
            vision.load_image, io.BytesIO(raw), vision.UPLOAD_MAX_PIXELS
        )
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        log.warning("[%04d] rejected: unreadable image (%s, %.0f KB)",
                    rid, type(exc).__name__, len(raw) / 1024)
        raise HTTPException(400, f"not a readable image: {type(exc).__name__}") from exc
    decode_ms = (time.perf_counter() - started) * 1000

    # Inference is ~650 ms of blocking CPU. Run it in a threadpool: on the event
    # loop it stalls every other request for that whole window, which showed up
    # as thumbnails intermittently failing to load while a scan was in flight.
    timings: dict[str, float] = {}
    cands = await run_in_threadpool(m.search, img, MAX_CANDIDATES, None, timings)
    total_ms = (time.perf_counter() - started) * 1000

    # Phase breakdown, because "slow" has three very different causes here and a
    # single total cannot tell them apart: a big upload, a heavyweight decode
    # (some references are CMYK and need an ICC transform), or inference.
    log.info(
        "[%04d] done %.0f ms  =  queue %.0f ms | decode %.0f ms | embed %.0f ms "
        "(%d views, %.0f ms/view) | rank %.1f ms  ->  %s %s (%.3f)",
        rid, total_ms + wait_ms, wait_ms, decode_ms,
        timings.get("embed_ms", 0), int(timings.get("views", 0)),
        timings.get("embed_ms", 0) / max(timings.get("views", 1), 1),
        timings.get("rank_ms", 0),
        cands[0].size if cands else "-", cands[0].design if cands else "-",
        cands[0].score if cands else 0.0,
    )
    if total_ms + wait_ms > 3000:
        log.warning("[%04d] exceeded the 3 s capture-to-result budget (%.0f ms)",
                    rid, total_ms + wait_ms)

    return JSONResponse({
        "elapsed_ms": round(total_ms),
        "queue_ms": round(wait_ms),
        "timings": {k: round(v, 1) for k, v in timings.items()},
        "decode_ms": round(decode_ms, 1),
        "top_k": DISPLAY_K,
        "candidates": [c.as_dict() for c in cands],
    })


def warm_up() -> None:
    """Load the index and run one inference before any user waits on it.

    Creating the ONNX session for a 346 MB model and running the first forward
    pass costs seconds. Without this the first scan after a restart pays that,
    which reads as "the app is slow" when it is really "the app is cold".
    """
    import numpy as np
    from PIL import Image as _Image

    t = time.perf_counter()
    try:
        m = get_matcher()
    except (FileNotFoundError, IndexMismatch) as exc:
        log.error("index unavailable: %s", exc)
        return
    log.info("index loaded: %d images, %d vectors, %d products, pipeline %s (%.0f ms)",
             m.n_images, int(m.vectors.shape[0]),
             len({r["product"] for r in m.references}),
             m.meta.get("pipeline_version"), (time.perf_counter() - t) * 1000)

    t = time.perf_counter()
    rng = np.random.default_rng(0)
    dummy = _Image.fromarray(rng.integers(0, 255, (640, 480, 3), dtype=np.uint8), "RGB")
    m.search(dummy, k=1)
    log.info("model warm: first inference %.0f ms (providers=%s, threads=%s)",
             (time.perf_counter() - t) * 1000,
             vision._get_session().get_providers(),
             vision._get_session().get_session_options().intra_op_num_threads)


def lan_ip() -> str | None:
    """Best-guess LAN address of this machine, for printing a reachable URL."""
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.0.2.1", 1))          # TEST-NET-1: routed, never answers
        return sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()


def ensure_cert(host: str) -> tuple[Path, Path]:
    """Self-signed cert for LAN HTTPS, so the live camera works off localhost.

    getUserMedia requires a secure context. localhost qualifies; a plain-http LAN
    address does not, which is why the camera preview refuses to start there. The
    file input with capture="environment" still works over http, so TLS is only
    needed for the live preview.
    """
    cert_dir = POC_ROOT / "certs"
    cert_dir.mkdir(exist_ok=True)
    cert, key = cert_dir / "server.crt", cert_dir / "server.key"

    ip = lan_ip() or "127.0.0.1"
    marker = cert_dir / "issued-for.txt"
    if cert.exists() and key.exists() and marker.exists() and marker.read_text().strip() == ip:
        return cert, key

    log.info("issuing a self-signed certificate for %s", ip)
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
         "-keyout", str(key), "-out", str(cert), "-days", "365",
         "-subj", f"/CN={ip}", "-addext", f"subjectAltName=IP:{ip},IP:127.0.0.1,DNS:localhost"],
        check=True, capture_output=True,
    )
    marker.write_text(ip)
    return cert, key


def start_redirector(http_port: int, https_port: int) -> None:
    """Serve plain HTTP on `http_port` that redirects to HTTPS on `https_port`.

    A phone given a bare IP defaults to http://. Sending that to a TLS socket
    produces ERR_EMPTY_RESPONSE with no hint of the cause, so the plain port is
    kept alive purely to bounce people to the right scheme.
    """
    import threading

    import uvicorn
    from fastapi.responses import RedirectResponse

    redirect_app = FastAPI()

    @redirect_app.get("/{path:path}")
    def to_https(path: str, request: Request) -> RedirectResponse:
        host = (request.headers.get("host") or "").split(":")[0]
        return RedirectResponse(f"https://{host}:{https_port}/{path}", status_code=307)

    def run() -> None:
        uvicorn.run(redirect_app, host="0.0.0.0", port=http_port, log_level="critical")

    threading.Thread(target=run, daemon=True).start()


def main(argv: list[str] | None = None) -> int:
    import uvicorn

    p = argparse.ArgumentParser(description="Run the POC demo server.")
    p.add_argument("--host", default="127.0.0.1",
                   help="use 0.0.0.0 to reach it from a phone on the same LAN")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--tls", action="store_true",
                   help="serve HTTPS with a self-signed cert so the live camera "
                        "works from a phone on the LAN")
    p.add_argument("--access-log", action="store_true",
                   help="also log every HTTP request (thumbnails included; noisy)")
    a = p.parse_args(argv)

    warm_up()

    ssl_args = {}
    scheme = "http"
    if a.tls:
        cert, key = ensure_cert(a.host)
        ssl_args = {"ssl_certfile": str(cert), "ssl_keyfile": str(key)}
        scheme = "https"
        # TLS moves to 8443 and the requested port keeps serving plain HTTP as a
        # redirector, so typing the bare IP still lands somewhere that works.
        https_port, a.port = a.port + 443, a.port
        start_redirector(a.port, https_port)

    listen_port = https_port if a.tls else a.port
    ip = lan_ip()

    if a.tls:
        log.info("open this on the phone:  http://%s:%d", ip or "localhost", a.port)
        log.info("  it redirects to        https://%s:%d", ip or "localhost", listen_port)
        log.info("  the certificate is self-signed — accept the warning once")
    elif a.host in ("0.0.0.0", "::"):
        log.info("open this on the phone:  http://%s:%d", ip or "localhost", a.port)
        log.info("  live camera preview needs HTTPS off localhost — use `make lan-https`,")
        log.info("  or tap \"Choose / take photo\", which opens the native camera over http")
    else:
        log.info("serving on http://localhost:%d", a.port)

    uvicorn.run(app, host=a.host, port=listen_port,
                log_level="info" if a.access_log else "warning",
                access_log=a.access_log, **ssl_args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
