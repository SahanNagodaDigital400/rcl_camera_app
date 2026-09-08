"""How small can the upload get before matching suffers?

Upload bytes are the dominant cost on a weak mobile uplink — a 198 KB image can
exceed 30 s. This scores the same queries at several client-side settings
against the full-resolution answer.

Run from poc/:  .venv/bin/python experiments/upload_size.py
"""
import io, sys, time
from collections import Counter
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tilematch import vision
from tilematch.augment import synthesize_query
from tilematch.search import Matcher


def as_upload(img, max_edge, q):
    im = img.copy()
    if max_edge and max(im.size) > max_edge:
        k = max_edge / max(im.size)
        im = im.resize((round(im.width * k), round(im.height * k)), Image.Resampling.BICUBIC)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=q)
    return buf.getvalue()


def main():
    m = Matcher()
    tiles = Path("Tiles-prepared") if Path("Tiles-prepared").exists() else Path("Tiles")
    counts = Counter(r["product"] for r in m.references)
    targets = [r for r in m.references if counts[r["product"]] > 1][:60]

    settings = [(None, 95), (1024, 85), (896, 82), (768, 80), (640, 78), (512, 75)]
    agree = {s: 0 for s in settings}
    truth_hit = {s: 0 for s in settings}
    sizes = {s: [] for s in settings}

    print(f"scoring {len(targets)} queries at {len(settings)} settings...", flush=True)
    t0 = time.time()
    for n, r in enumerate(targets, 1):
        q = synthesize_query(vision.load_image(tiles / r["relpath"]), 4242 + n)
        base = None
        for s in settings:
            raw = as_upload(q, *s)
            sizes[s].append(len(raw))
            got = [c.product for c in m.search(vision.load_image(raw), k=3)]
            if s == settings[0]:
                base = got
            agree[s] += (got == base)
            truth_hit[s] += (r["product"] in got)
        if n % 20 == 0:
            print(f"  {n}/{len(targets)}  {time.time()-t0:.0f}s", flush=True)

    n = len(targets)
    print(f"\n  {'upload setting':<20} {'median KB':>10} {'agrees w/ full':>15} {'top-3 correct':>14}")
    print("  " + "-" * 64)
    for s in settings:
        med = sorted(sizes[s])[len(sizes[s]) // 2] / 1024
        label = f"{s[0] or 'full'}px q{s[1]}"
        print(f"  {label:<20} {med:10.0f} {agree[s]/n*100:14.0f}% {truth_hit[s]/n*100:13.0f}%")


if __name__ == "__main__":
    main()
