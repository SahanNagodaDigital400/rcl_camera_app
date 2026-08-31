"""Is the second query view worth 50% of scan latency?

search.QUERY_ZOOMS embeds the full frame plus a 0.55 centre crop and max-pools.
That doubles inference, which is ~97% of server time. This scores both from one
pass so the comparison costs nothing extra.

Run from poc/:  .venv/bin/python experiments/query_views.py
"""
import sys, time
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tilematch import vision
from tilematch.augment import synthesize_query
from tilematch.search import Matcher


def main():
    m = Matcher()
    products = np.array([r["product"] for r in m.references])
    counts = Counter(products)
    targets = [(i, r) for i, r in enumerate(m.references) if counts[r["product"]] > 1]

    hits = {1: [0, 0], 2: [0, 0]}
    t0 = time.time()
    for n, (idx, r) in enumerate(targets, 1):
        q = synthesize_query(vision.load_image(Path("Tiles") / r["relpath"]), 1234 + idx)
        qv = m.embed_query(q)                       # (2, 1536): full frame, centre zoom

        for nviews in (1, 2):
            sims = qv[:nviews] @ m.vectors.T
            best = np.full(m.n_images, -np.inf, dtype=np.float32)
            np.maximum.at(best, m.owners, sims.max(axis=0))
            best[idx] = -np.inf
            top = np.argsort(-best)[:3]
            hits[nviews][0] += products[top[0]] == r["product"]
            hits[nviews][1] += r["product"] in products[top]
        if n % 40 == 0:
            print(f"  {n}/{len(targets)}  {time.time()-t0:.0f}s", flush=True)

    n = len(targets)
    print(f"\n  {'query views':<28} {'top-1':>8} {'top-3':>8}   scan cost")
    print("  " + "-" * 60)
    print(f"  {'1 (full frame only)':<28} {hits[1][0]/n*100:7.1f}% {hits[1][1]/n*100:7.1f}%   ~220 ms")
    print(f"  {'2 (+ 0.55 centre zoom)':<28} {hits[2][0]/n*100:7.1f}% {hits[2][1]/n*100:7.1f}%   ~440 ms")
    print(f"  {'gain from the 2nd view':<28} {(hits[2][0]-hits[1][0])/n*100:+7.1f}  "
          f"{(hits[2][1]-hits[1][1])/n*100:+7.1f}")


if __name__ == "__main__":
    main()
