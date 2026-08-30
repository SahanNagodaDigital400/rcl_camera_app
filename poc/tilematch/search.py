"""Query the index: photo -> top 3 candidates.

Brute-force cosine over ~2k unit-norm vectors is one dot product against a
(N, 1536) matrix — sub-millisecond, and orders of magnitude below the embedding
cost that dominates a scan. Production uses pgvector + HNSW; at this scale any
vector store would be theatre, and CLAUDE.md's "measure first" rule says so.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from . import vision

POC_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INDEX = POC_ROOT / "index"

TOP_K = 3  # product rule: always three, never one. Not configurable by design.

# Query-time views. Rotation invariance is already baked into the index, so this
# only covers framing: the whole frame, and a centre zoom for when the tile
# fills less of the shot.
QUERY_ZOOMS = (1.0, 0.55)


class IndexMismatch(RuntimeError):
    pass


@dataclass
class Candidate:
    rank: int
    score: float
    code: str
    size: str
    design: str
    face: str | None
    product: str
    thumb: str
    relpath: str
    design_unknown: bool

    def as_dict(self) -> dict:
        return {
            "rank": self.rank,
            "score": round(self.score, 4),
            "code": self.code,
            "size": self.size,
            "design": self.design,
            "face": self.face,
            "product": self.product,
            "thumb": self.thumb,
            "design_unknown": self.design_unknown,
        }


class Matcher:
    def __init__(self, index_dir: Path = DEFAULT_INDEX):
        index_dir = Path(index_dir)
        meta_path = index_dir / "meta.json"
        vec_path = index_dir / "vectors.npz"
        if not meta_path.exists() or not vec_path.exists():
            raise FileNotFoundError(f"No index at {index_dir}. Run `make index` first.")

        self.index_dir = index_dir
        self.meta = json.loads(meta_path.read_text())
        self.references: list[dict] = self.meta["references"]

        # AD-1 guard. An index built with different preprocessing is silently
        # wrong rather than broken, so refuse it loudly instead of scoring
        # against vectors that mean something else.
        stamp = self.meta.get("config_hash")
        if stamp != vision.config_hash():
            raise IndexMismatch(
                f"Preprocessing has changed since this index was built "
                f"(index {stamp} vs current {vision.config_hash()}"
                f", grey_world={vision.GREY_WORLD}). Every stored vector now "
                f"means something different. Re-run `make index`."
            )

        data = np.load(vec_path)
        self.vectors: np.ndarray = data["vectors"]
        self.owners: np.ndarray = data["owners"]
        self.n_images = len(self.references)

    def embed_query(self, img: Image.Image) -> np.ndarray:
        """Photo -> (V, 1536). Same preprocess+embed as indexing; only the
        framing differs, which is TTA, not a second pipeline."""
        views = [img]
        for z in QUERY_ZOOMS[1:]:
            w, h = img.size
            cw, ch = int(w * z), int(h * z)
            left, top = (w - cw) // 2, (h - ch) // 2
            views.append(img.crop((left, top, left + cw, top + ch)))
        return vision.embed_images(views, batch_size=len(views))

    def score_images(self, img: Image.Image, exclude: set[int] | None = None) -> np.ndarray:
        """Per-reference-image similarity, max-pooled over query views and the
        multiple stored vectors of each reference."""
        qv = self.embed_query(img)
        sims = qv @ self.vectors.T                      # (V, n_vectors)
        best_per_vector = sims.max(axis=0)              # (n_vectors,)

        scores = np.full(self.n_images, -np.inf, dtype=np.float32)
        np.maximum.at(scores, self.owners, best_per_vector)

        if exclude:
            scores[list(exclude)] = -np.inf
        return scores

    def search(
        self, img: Image.Image, k: int = TOP_K, exclude: set[int] | None = None
    ) -> list[Candidate]:
        """Top k candidates, ranked purely by similarity.

        Not deduplicated by product (PRD OQ-12): two or three candidates may be
        different faces of the same product, and for a shade-varying range like
        45X90/POLISH that is the useful answer, not a bug.
        """
        scores = self.score_images(img, exclude)
        order = np.argsort(-scores)[:k]
        out = []
        for rank, idx in enumerate(order, 1):
            r = self.references[int(idx)]
            out.append(
                Candidate(
                    rank=rank,
                    score=float(scores[idx]),
                    code=r["code"],
                    size=r["size"],
                    design=r["design"],
                    face=r.get("face"),
                    product=r["product"],
                    thumb=r["thumb"],
                    relpath=r["relpath"],
                    design_unknown=r.get("design_unknown", False),
                )
            )
        return out

    def search_path(self, path: str | Path, k: int = TOP_K) -> list[Candidate]:
        return self.search(vision.load_image(path), k)


def format_candidates(cands: list[Candidate], elapsed: float | None = None) -> str:
    lines = ["", "  top 3 candidates", "  " + "─" * 68]
    for c in cands:
        design = c.design + ("  ⚠ unclassified" if c.design_unknown else "")
        lines.append(f"   {c.rank}.  {c.score:.4f}   {c.size:<7} {design}")
        lines.append(f"            {c.code}")
    lines.append("  " + "─" * 68)
    if elapsed is not None:
        lines.append(f"  {elapsed*1000:.0f} ms")
    lines.append("  Size and finish are not recoverable from a photo — verify against")
    lines.append("  the reference image before quoting a code.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Match a photo against the tile index.")
    p.add_argument("image", type=Path)
    p.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)

    m = Matcher(a.index)
    t = time.time()
    cands = m.search_path(a.image)
    elapsed = time.time() - t

    if a.json:
        print(json.dumps([c.as_dict() for c in cands], indent=2))
    else:
        print(format_candidates(cands, elapsed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
