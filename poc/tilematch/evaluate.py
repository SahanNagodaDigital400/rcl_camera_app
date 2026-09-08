"""Accuracy harness.

Scoring follows the PRD exactly: a scan counts as correct if ANY of the three
candidates matches the true Product (size + design), even when another
candidate is a different Face of that same product. Both top-1 and top-3 are
reported; top-3 is the one that reflects real usefulness.

Three modes, in ascending order of how much the number means:

  sanity     The unmodified reference image, queried against an index that
             contains it. Proves the pipeline is wired up: every hit should
             score ~1.0 at rank 1. It is not an accuracy result and is never to
             be quoted as one.

  synthetic  Leave-one-image-out. The query image's vectors are removed from
             the index before searching, so a hit means a DIFFERENT face of the
             same product was retrieved. Honest about generalisation across
             faces, still dishonest about the studio-to-phone domain gap,
             because the query is a warped studio asset rather than a photo.

  real       Real staff phone photos from poc/queries/<SIZE>/<DESIGN>/. The
             only number that decides anything. CLAUDE.md is blunt that
             studio-to-studio accuracy "will flatter any change".
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image

from . import vision
from .augment import synthesize_query
from .catalog import IMAGE_SUFFIXES, normalize_folder
from .search import DEFAULT_INDEX, TOP_K, Matcher

POC_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_QUERIES = POC_ROOT / "queries"


def tiles_root(matcher: Matcher) -> Path:
    """The reference tree this index was built from — prepared or original."""
    return POC_ROOT / matcher.meta.get("tiles_dir", "Tiles")

CAVEAT = {
    "sanity": "PIPELINE CHECK ONLY — unmodified images already in the index. Not an accuracy result.",
    "synthetic": "SYNTHETIC — warped studio assets, not phone photos. Overstates real accuracy.",
    "real": "REAL staff photos.",
}


def _banner(mode: str, n: int) -> str:
    return "\n".join([
        "",
        "═" * 72,
        f"  {mode.upper()} EVAL   n={n}",
        f"  {CAVEAT[mode]}",
        "═" * 72,
    ])


def _summary(results: list[dict], mode: str) -> dict:
    n = len(results)
    if not n:
        return {"mode": mode, "n": 0}
    top1 = sum(r["top1"] for r in results) / n
    top3 = sum(r["top3"] for r in results) / n
    return {
        "mode": mode,
        "n": n,
        "top1": round(top1, 4),
        "top3": round(top3, 4),
        "caveat": CAVEAT[mode],
    }


def _print_summary(s: dict, results: list[dict]) -> None:
    if not s.get("n"):
        print("  no queries evaluated\n")
        return
    print(f"\n  top-1  {s['top1']*100:5.1f}%   ({sum(r['top1'] for r in results)}/{s['n']})")
    print(f"  top-3  {s['top3']*100:5.1f}%   ({sum(r['top3'] for r in results)}/{s['n']})   <- the metric that matters")

    misses = [r for r in results if not r["top3"]]
    if misses:
        print(f"\n  {len(misses)} miss(es):")
        for r in misses[:20]:
            got = ", ".join(f"{c['product']} ({c['score']:.3f})" for c in r["candidates"])
            print(f"    {r['truth']:<34} -> {got}")
        if len(misses) > 20:
            print(f"    ... and {len(misses)-20} more")

    by_product = defaultdict(list)
    for r in results:
        by_product[r["truth"]].append(r["top3"])
    worst = sorted(
        ((p, sum(v) / len(v), len(v)) for p, v in by_product.items()), key=lambda x: x[1]
    )[:8]
    weak = [w for w in worst if w[1] < 1.0]
    if weak:
        print("\n  weakest products (top-3):")
        for p, acc, cnt in weak:
            print(f"    {acc*100:5.1f}%  {p}  (n={cnt})")
    print()


def run_synthetic(matcher: Matcher, mode: str, seed: int, limit: int | None) -> list[dict]:
    """Leave-one-image-out (mode='synthetic') or same-image (mode='sanity')."""
    product_counts = Counter(r["product"] for r in matcher.references)
    results: list[dict] = []
    started = time.time()

    targets = list(enumerate(matcher.references))
    if mode == "synthetic":
        # A product with a single reference image has no other face to fall back
        # on, so leave-one-out makes it unreachable by construction. Scoring it
        # would just be measuring an impossibility.
        targets = [(i, r) for i, r in targets if product_counts[r["product"]] > 1]
    if limit:
        targets = targets[:limit]

    print(_banner(mode, len(targets)))
    if mode == "synthetic":
        skipped = len(matcher.references) - len(targets)
        print(f"  {skipped} image(s) excluded: only face of their product, "
              f"unreachable under leave-one-out.\n")

    for n, (idx, ref) in enumerate(targets, 1):
        src = tiles_root(matcher) / ref["relpath"]
        try:
            img = vision.load_image(src)
        except Exception as exc:
            print(f"  [{n}/{len(targets)}] SKIP {ref['relpath']} — {type(exc).__name__}")
            continue

        # Sanity mode queries the image unchanged: anything less than a rank-1
        # hit at ~1.0 means the pipeline itself is broken, which is the only
        # thing this mode is here to detect.
        query = synthesize_query(img, seed + idx) if mode == "synthetic" else img
        exclude = {idx} if mode == "synthetic" else None
        cands = matcher.search(query, k=TOP_K, exclude=exclude)

        truth = ref["product"]
        products = [c.product for c in cands]
        results.append({
            "truth": truth,
            "code": ref["code"],
            "relpath": ref["relpath"],
            "query_seed": (seed + idx) if mode == "synthetic" else None,
            "top1": int(bool(products) and products[0] == truth),
            "top3": int(truth in products),
            "candidates": [c.as_dict() for c in cands],
        })

        if n % 10 == 0 or n == len(targets):
            acc = sum(r["top3"] for r in results) / len(results)
            el = max(time.time() - started, 1e-6)
            eta = (len(targets) - n) * el / n
            print(f"  [{n}/{len(targets)}] running top-3 {acc*100:.1f}%  "
                  f"({el:.0f}s, ~{eta:.0f}s left)", flush=True)

    return results


def run_real(matcher: Matcher, queries_dir: Path) -> list[dict]:
    """Evaluate poc/queries/<SIZE>/<DESIGN>/*.jpg against the index."""
    queries_dir = Path(queries_dir)
    photos = [
        p for p in sorted(queries_dir.rglob("*"))
        if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES
        and len(p.relative_to(queries_dir).parts) == 3
    ]

    print(_banner("real", len(photos)))
    if not photos:
        print(f"  Nothing in {queries_dir}.")
        print("  Drop phone photos in as:  queries/<SIZE>/<DESIGN>/<anything>.jpg")
        print("  e.g. queries/45X90/CREMA MARMOL/IMG_0042.jpg\n")
        return []

    results = []
    for n, p in enumerate(photos, 1):
        size, design, _ = p.relative_to(queries_dir).parts
        truth = f"{normalize_folder(size)} / {normalize_folder(design)}"
        try:
            img = vision.load_image(p)
        except Exception as exc:
            print(f"  [{n}/{len(photos)}] SKIP {p.name} — {type(exc).__name__}")
            continue

        cands = matcher.search(img, k=TOP_K)
        products = [c.product for c in cands]
        hit = truth in products
        results.append({
            "truth": truth,
            "code": p.name,
            "relpath": str(p.relative_to(queries_dir)),
            "top1": int(bool(products) and products[0] == truth),
            "top3": int(hit),
            "candidates": [c.as_dict() for c in cands],
        })
        print(f"  [{n}/{len(photos)}] {'HIT ' if hit else 'MISS'}  {truth:<32} "
              f"-> {products[0] if products else '-'}", flush=True)

    if not any(r["truth"] in {ref['product'] for ref in matcher.references} for r in results):
        print("\n  ⚠ No query folder matched an indexed product. Check that your")
        print("    queries/<SIZE>/<DESIGN> names match the Tiles/ folder names.")
    return results


def write_failure_sheet(results: list[dict], out: Path, matcher: Matcher) -> Path | None:
    """Query beside its three candidates, one row per miss.

    These textures are subtle enough that a miss is only interpretable by eye —
    a product name in a table does not tell you whether the match was
    reasonable.
    """
    misses = [r for r in results if not r["top3"]][:25]
    if not misses:
        return None

    cell, pad = 190, 8
    cols = 1 + TOP_K
    sheet = Image.new("RGB", (cols * (cell + pad) + pad,
                              len(misses) * (cell + pad) + pad), (250, 250, 250))

    for row, r in enumerate(misses):
        y = pad + row * (cell + pad)
        # Show what the matcher actually saw, not the pristine reference: for a
        # synthetic run that means re-deriving the same warped query from its seed.
        src = tiles_root(matcher) / r["relpath"]
        qpath = POC_ROOT / "queries" / r["relpath"]
        for p, is_ref in ((qpath, False), (src, True)):
            if not p.exists():
                continue
            try:
                q = vision.load_image(p)
                if is_ref and r.get("query_seed") is not None:
                    q = synthesize_query(q, r["query_seed"])
                q.thumbnail((cell, cell))
                sheet.paste(q, (pad, y))
            except Exception:
                pass
            break
        for col, c in enumerate(r["candidates"], 1):
            tp = matcher.index_dir / c["thumb"]
            if tp.exists():
                t = Image.open(tp).convert("RGB")
                t.thumbnail((cell, cell))
                sheet.paste(t, (pad + col * (cell + pad), y))

    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, quality=85)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Tile matching accuracy harness.")
    p.add_argument("--mode", choices=["synthetic", "sanity", "real"], default="synthetic")
    p.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    p.add_argument("--queries", type=Path, default=DEFAULT_QUERIES)
    p.add_argument("--seed", type=int, default=1234)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--report", type=Path, default=None, help="write JSON results here")
    a = p.parse_args(argv)

    matcher = Matcher(a.index)
    results = (run_real(matcher, a.queries) if a.mode == "real"
               else run_synthetic(matcher, a.mode, a.seed, a.limit))

    summary = _summary(results, a.mode)
    print("\n" + "═" * 72)
    print(f"  {a.mode.upper()}  —  {CAVEAT[a.mode]}")
    print("═" * 72)
    _print_summary(summary, results)

    sheet = write_failure_sheet(results, POC_ROOT / "index" / f"failures-{a.mode}.jpg", matcher)
    if sheet:
        print(f"  failure sheet: {sheet}  (query | candidate 1 | 2 | 3)\n")

    if a.report:
        a.report.write_text(json.dumps({"summary": summary, "results": results}, indent=2))
        print(f"  report: {a.report}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
