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

# Scoring granularity for the eval harness, and the PRD's spec for production
# (FR-7, "up to three Candidates"). Keep this at 3: evaluate.py reports top-1 and
# top-3 against it, so raising it would silently relabel a top-10 number as
# top-3. How many the UI *displays* is a separate knob — server.DISPLAY_K.
TOP_K = 3

# Query-time views. Rotation invariance is already baked into the index, so this
# would only cover framing.
#
# A 0.55 centre zoom was tried as a second view and measured worse: top-1 65.6%
# vs 67.2%, top-3 79.5% vs 81.1%, for double the inference. Max-pooling over
# views means a spurious high match on the zoomed crop can outrank the correct
# full-frame one, and cropping into an already well-framed tile photo throws away
# context without adding information. One view it is — which also halves scan
# latency, and inference is ~97% of it. See experiments/query_views.py.
QUERY_ZOOMS = (1.0,)


class UnknownSize(ValueError):
    """A size filter that matches nothing in the index."""


class IndexMismatch(RuntimeError):
    pass


@dataclass
class Candidate:
    """One reference image, which is one tile.

    The file IS the unit of identity — `Tiles/<SIZE>/<CATEGORY>/<file>` holds one
    image per tile, and every file in a category folder is a different tile.
    `category` is therefore a grouping (`45X90 / POLISH`), not a product: the 22
    files in that folder are 22 tiles, not 22 faces of one.
    """

    rank: int
    ref_id: int
    score: float
    code: str
    size: str
    design: str
    face: str | None
    category: str
    thumb: str
    relpath: str
    design_unknown: bool

    def as_dict(self) -> dict:
        return {
            "rank": self.rank,
            "ref_id": self.ref_id,
            "score": round(self.score, 4),
            "code": self.code,
            "size": self.size,
            "design": self.design,
            "face": self.face,
            "category": self.category,
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

        # Size is the one attribute a photo cannot carry but a human in front of
        # the tile always knows, so it is the cheapest accuracy lever available:
        # declaring it removes every reference of another size from contention
        # before ranking. Held as an array so filtering is a mask, not a loop.
        self.ref_sizes = np.array([r["size"] for r in self.references])

    def sizes(self) -> list[dict]:
        """Sizes present in the index, largest catalogue first.

        Drives the picker in the UI — hard-coding a list would drift from the
        index the moment the catalogue changes.
        """
        counts: dict[str, dict] = {}
        for r in self.references:
            # meta.json's "product" key predates the correction that each file is
            # its own tile. The stored name is kept so existing indexes still
            # load; everything above this line calls it what it is, a category.
            e = counts.setdefault(r["size"], {"size": r["size"], "tiles": 0, "categories": set()})
            e["tiles"] += 1
            e["categories"].add(r["product"])
        out = [{"size": e["size"], "tiles": e["tiles"], "categories": len(e["categories"])}
               for e in counts.values()]
        return sorted(out, key=lambda e: (-e["tiles"], e["size"]))

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

    def score_images(
        self,
        img: Image.Image,
        exclude: set[int] | None = None,
        timings: dict[str, float] | None = None,
        size: str | None = None,
    ) -> np.ndarray:
        """Per-reference-image similarity, max-pooled over query views and the
        multiple stored vectors of each reference.

        Pass `timings` to have the embed and rank phases recorded in ms — the
        two costs are wildly different (embedding is ~99% of a scan) and a single
        total hides that.

        `size` restricts scoring to references of that size. It is a hard filter,
        not a re-rank: a 60X30 tile is never the answer to a scan the user has
        declared to be 45X90, and leaving those references in the running only
        gives them a chance to outrank the truth.
        """
        t = time.perf_counter()
        qv = self.embed_query(img)
        if timings is not None:
            timings["embed_ms"] = (time.perf_counter() - t) * 1000
            timings["views"] = float(len(qv))
        t = time.perf_counter()

        sims = qv @ self.vectors.T                      # (V, n_vectors)
        best_per_vector = sims.max(axis=0)              # (n_vectors,)

        scores = np.full(self.n_images, -np.inf, dtype=np.float32)
        np.maximum.at(scores, self.owners, best_per_vector)

        if size is not None:
            keep = self.ref_sizes == size
            if not keep.any():
                raise UnknownSize(f"no references of size {size!r} in this index")
            scores[~keep] = -np.inf
        if exclude:
            scores[list(exclude)] = -np.inf
        if timings is not None:
            timings["rank_ms"] = (time.perf_counter() - t) * 1000
        return scores

    def search(
        self,
        img: Image.Image,
        k: int = TOP_K,
        exclude: set[int] | None = None,
        timings: dict[str, float] | None = None,
        size: str | None = None,
    ) -> list[Candidate]:
        """Top k candidates, ranked purely by similarity.

        Never deduplicated by category. Each file in a category folder is a
        different tile, so three candidates from 45X90/POLISH are three distinct
        answers competing on merit — collapsing them would hide correct ones.

        Fewer than k come back when the index cannot supply k — a size filter
        that leaves only two references must return two, never two plus padding.
        """
        scores = self.score_images(img, exclude, timings, size)
        order = [i for i in np.argsort(-scores)[:k] if np.isfinite(scores[i])]
        out = []
        for rank, idx in enumerate(order, 1):
            r = self.references[int(idx)]
            out.append(
                Candidate(
                    rank=rank,
                    ref_id=int(idx),
                    score=float(scores[idx]),
                    code=r["code"],
                    size=r["size"],
                    design=r["design"],
                    face=r.get("face"),
                    category=r["product"],
                    thumb=r["thumb"],
                    relpath=r["relpath"],
                    design_unknown=r.get("design_unknown", False),
                )
            )
        return out

    def search_path(self, path: str | Path, k: int = TOP_K,
                    size: str | None = None) -> list[Candidate]:
        return self.search(vision.load_image(path), k, size=size)


def format_candidates(cands: list[Candidate], elapsed: float | None = None) -> str:
    lines = ["", f"  top {len(cands)} candidate(s)", "  " + "─" * 68]
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
    p.add_argument("--size", default=None,
                   help="restrict to one size, e.g. 45X90 — use when the tile is "
                        "in hand and the size is known")
    a = p.parse_args(argv)

    m = Matcher(a.index)
    if a.size:
        known = [e["size"] for e in m.sizes()]
        if a.size not in known:
            p.error(f"unknown size {a.size!r}; index has {', '.join(known)}")
    t = time.time()
    cands = m.search_path(a.image, size=a.size)
    elapsed = time.time() - t

    if a.json:
        print(json.dumps([c.as_dict() for c in cands], indent=2))
    else:
        print(format_candidates(cands, elapsed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
