"""Re-measure finding §2 (white balance dominates) on the colour-managed index.

The original measurement was taken before the ICC fix, when ~60% of references
were embedded from mis-converted CMYK pixels. Colour-space error and
white-balance error were confounded; this separates them.

Run from poc/:  .venv/bin/python experiments/wb_ablation.py
"""
import json, random, sys, time
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tilematch import augment, vision
from tilematch.search import Matcher


def query(img, seed, *, white_balance: bool):
    """The standard synthetic query, optionally without the WB/brightness jitter."""
    rng = random.Random(seed)
    short = min(img.size)
    side = int(short * rng.uniform(0.30, 0.60))
    l = rng.randint(0, max(0, img.width - side))
    t = rng.randint(0, max(0, img.height - side))
    q = img.crop((l, t, l + side, t + side))
    k = rng.randint(0, 3)
    if k:
        q = q.rotate(90 * k, expand=True)
    q = augment._perspective(q, rng)
    if white_balance:
        q = augment._lighting(q, rng)
        q = augment._white_balance(q, rng)
    q = augment._blur(q, rng)
    if max(q.size) > 1024:
        s = 1024 / max(q.size)
        q = q.resize((int(q.width * s), int(q.height * s)), Image.Resampling.BICUBIC)
    return augment._jpeg(q, rng)


def main():
    m = Matcher()
    products = np.array([r["product"] for r in m.references])
    counts = Counter(products)
    targets = [(i, r) for i, r in enumerate(m.references) if counts[r["product"]] > 1]
    print(f"leave-one-out over {len(targets)} images "
          f"(pipeline {m.meta['pipeline_version']})\n")

    out = {}
    for wb in (True, False):
        t1 = t3 = 0
        started = time.time()
        for n, (idx, r) in enumerate(targets, 1):
            img = vision.load_image(Path("Tiles") / r["relpath"])
            cands = m.search(query(img, 1234 + idx, white_balance=wb), k=3, exclude={idx})
            got = [c.product for c in cands]
            t1 += got[0] == r["product"]
            t3 += r["product"] in got
            if n % 40 == 0:
                print(f"  wb={wb}  {n}/{len(targets)}  {time.time()-started:.0f}s", flush=True)
        out[wb] = (t1 / len(targets), t3 / len(targets))

    print(f"\n  {'query':<34} {'top-1':>8} {'top-3':>8}")
    print("  " + "-" * 52)
    print(f"  {'with white-balance jitter':<34} {out[True][0]*100:7.1f}% {out[True][1]*100:7.1f}%")
    print(f"  {'without white-balance jitter':<34} {out[False][0]*100:7.1f}% {out[False][1]*100:7.1f}%")
    print(f"  {'gap attributable to WB':<34} {(out[False][0]-out[True][0])*100:+7.1f}  "
          f"{(out[False][1]-out[True][1])*100:+7.1f}")


if __name__ == "__main__":
    main()
