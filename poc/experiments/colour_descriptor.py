"""Re-measure finding §4 (a colour descriptor hurts) on the colour-managed index.

The original sweep ran when ~60% of references were embedded from mis-converted
CMYK pixels, so "colour adds noise" was partly measuring the bug rather than the
idea. This re-runs it against correct colours.

Run from poc/:  .venv/bin/python experiments/colour_descriptor.py
"""
import json, sys, time
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tilematch import augment, vision
from tilematch.augment import synthesize_query
from tilematch.search import Matcher

LAB_BINS = 8


def colour_desc(img: Image.Image) -> np.ndarray:
    """Lab a/b joint histogram + L histogram, from the same 224 centre crop."""
    w, h = img.size
    s = vision.RESIZE_SHORTEST_EDGE / min(w, h)
    im = img.resize((max(1, round(w * s)), max(1, round(h * s))), vision.RESAMPLE)
    w, h = im.size
    l, t = (w - vision.CROP_SIZE) // 2, (h - vision.CROP_SIZE) // 2
    im = im.crop((l, t, l + vision.CROP_SIZE, t + vision.CROP_SIZE))
    lab = np.asarray(im.convert("LAB"), dtype=np.float32).reshape(-1, 3)
    ab, _, _ = np.histogram2d(lab[:, 1], lab[:, 2], bins=LAB_BINS, range=[[0, 255], [0, 255]])
    Lh, _ = np.histogram(lab[:, 0], bins=LAB_BINS, range=(0, 255))
    v = np.concatenate([ab.ravel(), Lh]).astype(np.float32)
    return v / max(v.sum(), 1e-6)


def unit(x):
    return x / np.clip(np.linalg.norm(x, axis=-1, keepdims=True), 1e-12, None)


def main():
    m = Matcher()
    refs, D, owners = m.references, m.vectors, m.owners
    views = m.meta["views_per_image"]
    products = np.array([r["product"] for r in refs])

    print(f"colour descriptors for {len(refs)*views} views (pipeline "
          f"{m.meta['pipeline_version']})...", flush=True)
    t0 = time.time()
    C = []
    for i, r in enumerate(refs):
        img = vision.load_image(Path("Tiles") / r["relpath"])
        C.extend(colour_desc(v) for v in augment.generate_views(img, r["relpath"], views))
        if (i + 1) % 40 == 0:
            print(f"  {i+1}/{len(refs)}  {time.time()-t0:.0f}s", flush=True)
    C = unit(np.stack(C))

    counts = Counter(products)
    targets = [(i, r) for i, r in enumerate(refs) if counts[r["product"]] > 1]
    print(f"\nembedding {len(targets)} leave-one-out queries...", flush=True)
    QD, QC, truth, idxs = [], [], [], []
    t0 = time.time()
    for n, (i, r) in enumerate(targets, 1):
        q = synthesize_query(vision.load_image(Path("Tiles") / r["relpath"]), 1234 + i)
        QD.append(m.embed_query(q)[0])
        QC.append(colour_desc(q))
        truth.append(r["product"]); idxs.append(i)
        if n % 40 == 0:
            print(f"  {n}/{len(targets)}  {time.time()-t0:.0f}s", flush=True)
    QD, QC = np.stack(QD), unit(np.stack(QC))

    def score(alpha):
        t1 = t3 = 0
        for k in range(len(QD)):
            sim = (1 - alpha) * (QD[k] @ D.T) + alpha * (QC[k] @ C.T)
            best = np.full(len(refs), -np.inf, dtype=np.float32)
            np.maximum.at(best, owners, sim)
            best[idxs[k]] = -np.inf
            top = np.argsort(-best)[:3]
            t1 += products[top[0]] == truth[k]
            t3 += truth[k] in products[top]
        return t1 / len(QD), t3 / len(QD)

    print("\n  colour weight   top-1    top-3")
    print("  " + "-" * 34)
    for a in (0.0, 0.05, 0.10, 0.20, 0.30, 0.50):
        o, t = score(a)
        print(f"  {a:11.2f}   {o*100:6.1f}%  {t*100:6.1f}%")


if __name__ == "__main__":
    main()
