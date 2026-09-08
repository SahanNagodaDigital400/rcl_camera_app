"""Normalize reference images once, so every later build is cheap.

The pipeline caps decode at `vision.DECODE_MAX_EDGE` (2048px), so a 19276x9638
scan contributes nothing beyond what a 2048px copy would — but decoding it costs
2-6.4 s, and that cost is paid again on every re-index and every `make thumbs`.

This writes a parallel tree of already-decoded, already-colour-managed sRGB
copies. Indexing from those skips both the giant decode and the CMYK ICC
transform, which together were 25-40% of build time.

The source tree is never modified.

Cache validity is stamped with `vision.config_hash()`: a change to colour
management or the decode cap invalidates the prepared copies, exactly as it
invalidates the vector index.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from PIL.Image import DecompressionBombError

from . import vision
from .catalog import scan_tree

POC_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = POC_ROOT / "Tiles"
DEFAULT_OUTPUT = POC_ROOT / "Tiles-prepared"

# High enough that re-encoding is well below the noise the index-time
# augmentation already introduces, while still shrinking a 97 MB scan to ~1 MB.
PREP_QUALITY = 95
STAMP = "prepared.json"


def prepare(
    source: Path = DEFAULT_SOURCE,
    output: Path = DEFAULT_OUTPUT,
    force: bool = False,
) -> dict:
    source, output = Path(source), Path(output)
    output.mkdir(parents=True, exist_ok=True)

    stamp_path = output / STAMP
    stamp = {}
    if stamp_path.exists() and not force:
        try:
            stamp = json.loads(stamp_path.read_text())
        except (OSError, ValueError):
            stamp = {}
    if stamp.get("config_hash") != vision.config_hash():
        if stamp:
            print("preprocessing changed since these were prepared — rebuilding all", flush=True)
        stamp, force = {}, True

    report = scan_tree(source)
    refs = report.references
    print(f"preparing {len(refs)} references -> {output} "
          f"(max {vision.DECODE_MAX_EDGE}px, q{PREP_QUALITY})\n", flush=True)

    done = skipped = failed = 0
    src_bytes = out_bytes = 0
    started = time.time()

    for i, ref in enumerate(refs, 1):
        dst = output / ref.relpath
        dst = dst.with_suffix(".jpg")

        # Incremental: a prepared copy newer than its source is still good, so
        # `make prep` after adding a few tiles only touches the new ones.
        if not force and dst.exists() and dst.stat().st_mtime >= ref.path.stat().st_mtime:
            skipped += 1
            out_bytes += dst.stat().st_size
            src_bytes += ref.path.stat().st_size
            continue

        try:
            img = vision.load_image(ref.path)
        except (UnidentifiedImageError, OSError, ValueError, DecompressionBombError) as exc:
            print(f"  [{i}/{len(refs)}] SKIP {ref.relpath} — {type(exc).__name__}: {exc}", flush=True)
            failed += 1
            continue

        dst.parent.mkdir(parents=True, exist_ok=True)
        img.save(dst, "JPEG", quality=PREP_QUALITY, optimize=True)
        done += 1
        src_bytes += ref.path.stat().st_size
        out_bytes += dst.stat().st_size

        if done % 25 == 0:
            el = time.time() - started
            print(f"  [{i}/{len(refs)}] {el:.0f}s elapsed, "
                  f"~{(len(refs) - i) * el / max(done, 1):.0f}s left", flush=True)

    # Prune copies whose source is gone. Without this, deleting a tile from
    # Tiles/ leaves its prepared copy behind and the index keeps returning a
    # product that no longer exists in the catalogue.
    expected = {(output / Path(r.relpath).with_suffix(".jpg")).resolve() for r in refs}
    pruned = 0
    for existing in output.rglob("*.jpg"):
        if existing.resolve() not in expected:
            existing.unlink()
            pruned += 1
    if pruned:
        print(f"  pruned {pruned} prepared copies whose source no longer exists", flush=True)
        for d in sorted((p for p in output.rglob("*") if p.is_dir()),
                        key=lambda p: len(p.parts), reverse=True):
            if not any(d.iterdir()):
                d.rmdir()

    stamp_path.write_text(json.dumps({
        "config_hash": vision.config_hash(),
        "pipeline_version": vision.PIPELINE_VERSION,
        "max_edge": vision.DECODE_MAX_EDGE,
        "quality": PREP_QUALITY,
        "prepared_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "count": done + skipped,
    }, indent=2))

    print(f"\nprepared {done}, reused {skipped}, pruned {pruned}, failed {failed} "
          f"in {time.time()-started:.0f}s")
    if src_bytes:
        print(f"  {src_bytes/1e9:.2f} GB source -> {out_bytes/1e9:.2f} GB prepared "
              f"({src_bytes/max(out_bytes,1):.0f}x smaller)")
    return {"prepared": done, "reused": skipped, "failed": failed}


def resolve_tiles(explicit: Path | None = None) -> Path:
    """Prefer the prepared tree when it is present and current."""
    if explicit is not None:
        return explicit
    stamp = DEFAULT_OUTPUT / STAMP
    if stamp.exists():
        try:
            if json.loads(stamp.read_text()).get("config_hash") == vision.config_hash():
                return DEFAULT_OUTPUT
            print(f"⚠ {DEFAULT_OUTPUT.name} was prepared with different preprocessing; "
                  f"using {DEFAULT_SOURCE.name}. Run `make prep`.", flush=True)
        except (OSError, ValueError):
            pass
    return DEFAULT_SOURCE


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Normalize reference images for fast indexing.")
    p.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    p.add_argument("--force", action="store_true", help="re-prepare everything")
    a = p.parse_args(argv)
    prepare(a.source, a.output, a.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
