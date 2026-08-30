"""Build the vector index from the reference tree.

Output (all under poc/index/):
    vectors.npz   unit-norm float32 (N, 1536) + parallel owner ids
    meta.json     per-reference metadata + the pipeline stamp
    thumbs/       512px JPEGs, so the UI never opens a 96 MB original

Multi-vector note: this stores ~16 vectors per reference image and max-pools at
search time. Production's ERD models REFERENCE_IMAGE as one row with one
embedding column, which cannot express this — it needs a child table, or the
vectors pooled into one (which gives back the scale invariance the crops buy).
That is an open production decision; see poc/README.md.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, UnidentifiedImageError

from . import augment, vision
from .catalog import format_report, scan_tree

POC_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TILES = POC_ROOT / "Tiles"
DEFAULT_INDEX = POC_ROOT / "index"
THUMB_SIZE = 512

# Pixel standard deviation below which a reference carries no retrievable
# texture. Such an image will match any washed-out photo and can never be
# reliably retrieved itself — a real property of plain tiles, not a bug, but the
# operator has to know which products are affected.
FEATURELESS_STD = 3.0


def build(
    tiles_dir: Path = DEFAULT_TILES,
    index_dir: Path = DEFAULT_INDEX,
    views: int = augment.VIEWS_PER_IMAGE,
    batch_size: int = 8,
    limit: int | None = None,
) -> dict:
    index_dir = Path(index_dir)
    thumbs = index_dir / "thumbs"
    thumbs.mkdir(parents=True, exist_ok=True)

    report = scan_tree(tiles_dir)
    print(format_report(report), flush=True)

    refs = report.references[:limit] if limit else report.references
    print(f"\nembedding {len(refs)} images x {views} views "
          f"= {len(refs) * views} vectors\n", flush=True)

    all_vecs: list[np.ndarray] = []
    owners: list[int] = []
    meta: list[dict] = []
    failed: list[tuple[str, str]] = []
    featureless: list[tuple[str, float]] = []
    started = time.time()

    for i, ref in enumerate(refs):
        try:
            img = vision.load_image(ref.path)
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            # A corrupt reference must never abort a build; report and continue.
            failed.append((ref.relpath, f"{type(exc).__name__}: {exc}"))
            print(f"  [{i+1}/{len(refs)}] SKIP {ref.relpath} — {type(exc).__name__}", flush=True)
            continue

        thumb_img = img.copy().resize(_thumb_size(img.size), Image.Resampling.BICUBIC)
        thumb_img.save(thumbs / f"{len(meta):04d}.jpg", quality=82)

        std = float(np.asarray(thumb_img, dtype=np.float32).std())
        if std < FEATURELESS_STD:
            featureless.append((ref.relpath, round(std, 2)))

        vecs = vision.embed_images(
            augment.generate_views(img, ref.relpath, views), batch_size=batch_size
        )

        owner = len(meta)
        all_vecs.append(vecs)
        owners.extend([owner] * len(vecs))
        entry = ref.as_dict()
        entry["thumb"] = f"thumbs/{owner:04d}.jpg"
        entry["pixel_std"] = round(std, 2)
        entry["featureless"] = std < FEATURELESS_STD
        meta.append(entry)

        elapsed = time.time() - started
        rate = (i + 1) / elapsed
        eta = (len(refs) - i - 1) / rate if rate else 0
        print(f"  [{i+1}/{len(refs)}] {ref.product} — {ref.code}  "
              f"({elapsed:.0f}s elapsed, ~{eta:.0f}s left)", flush=True)

    if not all_vecs:
        raise SystemExit(
            f"No reference image could be embedded ({len(failed)} failed). "
            f"Check that {tiles_dir} contains readable images."
        )

    matrix = np.concatenate(all_vecs).astype(np.float32)
    owner_arr = np.array(owners, dtype=np.int32)

    np.savez_compressed(index_dir / "vectors.npz", vectors=matrix, owners=owner_arr)
    (index_dir / "meta.json").write_text(
        json.dumps(
            {
                "pipeline_version": vision.PIPELINE_VERSION,
                "config_hash": vision.config_hash(),
                "embed_dim": vision.EMBED_DIM,
                "views_per_image": views,
                "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "build_seconds": round(time.time() - started, 1),
                "n_images": len(meta),
                "n_vectors": int(matrix.shape[0]),
                "n_products": len({m["product"] for m in meta}),
                "failed": failed,
                "featureless": featureless,
                "unnamed_design": report.unnamed_design,
                "skipped_unreadable": report.skipped_unreadable,
                "references": meta,
            },
            indent=2,
        )
    )

    summary = {
        "images": len(meta),
        "vectors": int(matrix.shape[0]),
        "products": len({m["product"] for m in meta}),
        "seconds": round(time.time() - started, 1),
        "failed": len(failed),
    }
    print(f"\nindex built: {summary['images']} images, {summary['vectors']} vectors, "
          f"{summary['products']} products in {summary['seconds']}s", flush=True)
    if failed:
        print(f"  {len(failed)} reference(s) failed to load:", flush=True)
        for rel, why in failed:
            print(f"    {rel} — {why}", flush=True)
    if featureless:
        print(f"\n  ⚠ {len(featureless)} reference(s) carry no retrievable texture.", flush=True)
        print("    These match any washed-out photo and cannot be reliably retrieved.", flush=True)
        for rel, std in sorted(featureless, key=lambda x: x[1]):
            print(f"    std={std:5.2f}  {rel}", flush=True)
    summary["featureless"] = len(featureless)
    return summary


def _thumb_size(size: tuple[int, int]) -> tuple[int, int]:
    w, h = size
    s = THUMB_SIZE / max(w, h)
    return (max(1, int(w * s)), max(1, int(h * s))) if s < 1 else (w, h)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Build the tile vector index.")
    p.add_argument("--tiles", type=Path, default=DEFAULT_TILES)
    p.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    p.add_argument("--views", type=int, default=augment.VIEWS_PER_IMAGE)
    p.add_argument("--batch-size", type=int, default=8)
    p.add_argument("--limit", type=int, default=None, help="index only the first N images (smoke test)")
    a = p.parse_args(argv)
    build(a.tiles, a.index, a.views, a.batch_size, a.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
