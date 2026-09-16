"""Accuracy harness.

**The unit of identity is the file.** `Tiles/<SIZE>/<CATEGORY>/<file>` holds one
image per tile, and every file inside a category folder is a DIFFERENT tile —
the 22 files in `45X90/POLISH` are 22 tiles, not 22 faces of one. So a scan is
correct only when the exact reference image is retrieved. Retrieving a different
tile from the same folder is a miss, and is reported separately as
`same-folder` — a diagnostic, never the headline.

That correction matters: the earlier harness scored `size + design` as the truth
and reported 70.0% top-3 where strict scoring gives 78.7% on a different and
much easier question. Numbers from before the correction are not comparable.

Both top-1 and top-3 are reported; top-3 is the one that reflects real
usefulness, since staff verify against the reference image.

Three modes, in ascending order of how much the number means:

  sanity     The unmodified reference image, queried against an index that
             contains it. Proves the pipeline is wired up: every hit should
             score ~1.0 at rank 1. It is not an accuracy result and is never to
             be quoted as one.

  synthetic  The reference image degraded by `augment.synthesize_query` —
             lighting, white balance, blur, perspective, JPEG — then queried
             against an index that still contains it.

             There is no leave-one-out option any more, and this is the whole
             point of the correction: a tile has exactly ONE reference image, so
             removing it removes the only correct answer. What remains is a
             robustness test — can the pipeline re-find an image it already
             holds after that image is degraded? — and it is a LOOSE UPPER
             BOUND, because a synthetic warp of image X is far closer to X than
             any phone photo of the physical tile will be.

  real       Real staff phone photos from
             poc/queries/<SIZE>/<CATEGORY>/<CODE>/*.jpg. The only number that
             decides anything. CLAUDE.md is blunt that studio-to-studio
             accuracy "will flatter any change", and with no held-out reference
             left to test against, that warning now carries all the weight.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
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
    "synthetic": "SYNTHETIC — a warped copy of an image the index already holds. "
                 "A loose upper bound, not an accuracy result.",
    "real": "REAL staff photos.",
}


def _banner(mode: str, n: int, size_filter: bool = False) -> str:
    return "\n".join([
        "",
        "═" * 72,
        f"  {mode.upper()} EVAL   n={n}"
        + ("   [size filter: queries restricted to their own size]" if size_filter else ""),
        f"  {CAVEAT[mode]}",
        "  Correct = the exact tile. A different tile from the same folder is a miss.",
        "═" * 72,
    ])


def _summary(results: list[dict], mode: str, size_filter: bool = False) -> dict:
    n = len(results)
    if not n:
        return {"mode": mode, "n": 0}
    return {
        "mode": mode,
        "n": n,
        "top1": round(sum(r["top1"] for r in results) / n, 4),
        "top3": round(sum(r["top3"] for r in results) / n, 4),
        # Kept only to show how much looser the old scoring was. Never quote it.
        "same_folder_top3": round(sum(r["same_folder_top3"] for r in results) / n, 4),
        "size_filter": size_filter,
        "scoring": "exact tile (one reference image per tile)",
        "caveat": CAVEAT[mode] + (" Size filter ON — an upper bound on the size picker."
                                  if size_filter else ""),
    }


def _print_summary(s: dict, results: list[dict]) -> None:
    if not s.get("n"):
        print("  no queries evaluated\n")
        return
    n = s["n"]
    print(f"\n  top-1  {s['top1']*100:5.1f}%   ({sum(r['top1'] for r in results)}/{n})")
    print(f"  top-3  {s['top3']*100:5.1f}%   ({sum(r['top3'] for r in results)}/{n})"
          f"   <- the metric that matters")
    print(f"\n  for contrast, the old and wrong scoring — ANY tile from the right folder:")
    print(f"  top-3  {s['same_folder_top3']*100:5.1f}%   "
          f"({sum(r['same_folder_top3'] for r in results)}/{n})   <- do not quote this")

    misses = [r for r in results if not r["top3"]]
    if misses:
        print(f"\n  {len(misses)} miss(es):")
        for r in misses[:20]:
            got = ", ".join(f"{c['code']} ({c['score']:.3f})" for c in r["candidates"])
            near = "  [right folder, wrong tile]" if r["same_folder_top3"] else ""
            print(f"    {r['truth_code']:<30} -> {got}{near}")
        if len(misses) > 20:
            print(f"    ... and {len(misses)-20} more")

    by_folder = defaultdict(list)
    for r in results:
        by_folder[r["folder"]].append(r["top3"])
    worst = sorted(
        ((p, sum(v) / len(v), len(v)) for p, v in by_folder.items()), key=lambda x: x[1]
    )[:8]
    weak = [w for w in worst if w[1] < 1.0]
    if weak:
        print("\n  weakest folders (top-3, exact tile):")
        for p, acc, cnt in weak:
            print(f"    {acc*100:5.1f}%  {p}  (n={cnt})")
    print()


def _score(cands, truth_id: int, truth_folder: str) -> dict:
    """Exact-tile scoring, with the loose folder number kept as a diagnostic."""
    ids = [c.ref_id for c in cands]
    folders = [c.category for c in cands]
    return {
        "top1": int(bool(ids) and ids[0] == truth_id),
        "top3": int(truth_id in ids),
        "same_folder_top3": int(truth_folder in folders),
        "candidates": [c.as_dict() for c in cands],
    }


def run_synthetic(matcher: Matcher, mode: str, seed: int, limit: int | None,
                  size_filter: bool = False) -> list[dict]:
    """Query every reference, degraded (`synthetic`) or unmodified (`sanity`).

    Nothing is excluded from the index. A tile has one reference image, so
    excluding it would delete the only correct answer rather than force
    generalisation — see the module docstring.
    """
    results: list[dict] = []
    started = time.time()

    targets = list(enumerate(matcher.references))
    if limit:
        targets = targets[:limit]

    print(_banner(mode, len(targets), size_filter))

    for n, (idx, ref) in enumerate(targets, 1):
        src = tiles_root(matcher) / ref["relpath"]
        try:
            img = vision.load_image(src)
        except Exception as exc:
            print(f"  [{n}/{len(targets)}] SKIP {ref['relpath']} — {type(exc).__name__}")
            continue

        query = synthesize_query(img, seed + idx) if mode == "synthetic" else img
        # `--size-filter` models the best case for the size picker: the person
        # holding the tile reads its size off the back and gets it right. It is
        # an upper bound on the feature, not a prediction — a mis-declared size
        # makes the true tile unreachable, which this cannot measure.
        cands = matcher.search(query, k=TOP_K,
                               size=ref["size"] if size_filter else None)

        results.append({
            "truth_id": idx,
            "truth_code": ref["code"],
            "folder": ref["product"],
            "relpath": ref["relpath"],
            "query_seed": (seed + idx) if mode == "synthetic" else None,
            **_score(cands, idx, ref["product"]),
        })

        if n % 10 == 0 or n == len(targets):
            acc = sum(r["top3"] for r in results) / len(results)
            el = max(time.time() - started, 1e-6)
            eta = (len(targets) - n) * el / n
            print(f"  [{n}/{len(targets)}] running top-3 {acc*100:.1f}%  "
                  f"({el:.0f}s, ~{eta:.0f}s left)", flush=True)

    return results


def _resolve_truth(matcher: Matcher, size: str, category: str, code: str) -> int | None:
    """Find the reference id for one tile, by folder plus cleaned file name."""
    want = (normalize_folder(size), normalize_folder(category), code.strip().lower())
    for i, r in enumerate(matcher.references):
        if (r["size"], r["product"].split(" / ", 1)[-1]) == want[:2] \
                and r["code"].strip().lower() == want[2]:
            return i
    return None


def run_real(matcher: Matcher, queries_dir: Path, size_filter: bool = False) -> list[dict]:
    """Evaluate poc/queries/<SIZE>/<CATEGORY>/<CODE>/*.jpg against the index.

    The extra <CODE> level is what makes strict scoring possible: without it a
    photo only says which folder it came from, and the harness cannot tell a
    correct answer from a different tile of the same range.
    """
    queries_dir = Path(queries_dir)
    photos = [
        p for p in sorted(queries_dir.rglob("*"))
        if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES
        and len(p.relative_to(queries_dir).parts) == 4
    ]
    shallow = [
        p for p in sorted(queries_dir.rglob("*"))
        if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES
        and len(p.relative_to(queries_dir).parts) == 3
    ]

    print(_banner("real", len(photos), size_filter))
    if shallow:
        print(f"  ⚠ {len(shallow)} photo(s) are one level too shallow and were skipped.")
        print("    The tile code is now required, because each file in a category")
        print("    folder is a different tile:")
        print("      queries/<SIZE>/<CATEGORY>/<CODE>/<anything>.jpg")
        print("      e.g. queries/45X90/CREMA MARMOL/RP.CMA.0001DJ.SM.0T/IMG_0042.jpg\n")
    if not photos:
        print(f"  Nothing usable in {queries_dir}.")
        print("  Drop phone photos in as:  queries/<SIZE>/<CATEGORY>/<CODE>/<anything>.jpg")
        print("  <CODE> is the reference file name with 'Copy of ' and the extension")
        print("  stripped — exactly what the scan screen shows as the answer.\n")
        return []

    results, unresolved = [], []
    for n, p in enumerate(photos, 1):
        size, category, code, _ = p.relative_to(queries_dir).parts
        truth_id = _resolve_truth(matcher, size, category, code)
        if truth_id is None:
            unresolved.append(f"{size}/{category}/{code}")
            continue
        try:
            img = vision.load_image(p)
        except Exception as exc:
            print(f"  [{n}/{len(photos)}] SKIP {p.name} — {type(exc).__name__}")
            continue

        ref = matcher.references[truth_id]
        cands = matcher.search(img, k=TOP_K,
                               size=ref["size"] if size_filter else None)
        scored = _score(cands, truth_id, ref["product"])
        results.append({
            "truth_id": truth_id,
            "truth_code": ref["code"],
            "folder": ref["product"],
            "relpath": str(p.relative_to(queries_dir)),
            **scored,
        })
        print(f"  [{n}/{len(photos)}] {'HIT ' if scored['top3'] else 'MISS'}  "
              f"{ref['code']:<30} -> {cands[0].code if cands else '-'}", flush=True)

    if unresolved:
        print(f"\n  ⚠ {len(unresolved)} folder(s) name a tile that is not in the index:")
        for u in unresolved[:10]:
            print(f"      {u}")
        print("    Check the <CODE> level matches the reference file name exactly.")
    return results


def write_failure_sheet(results: list[dict], out: Path, matcher: Matcher) -> Path | None:
    """Query beside its three candidates, one row per miss.

    These textures are subtle enough that a miss is only interpretable by eye —
    a tile code in a table does not tell you whether the match was reasonable.
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
    p.add_argument("--size-filter", action="store_true",
                   help="restrict each query to its own size, as the size picker "
                        "does when staff declare it correctly")
    a = p.parse_args(argv)

    matcher = Matcher(a.index)
    results = (run_real(matcher, a.queries, a.size_filter) if a.mode == "real"
               else run_synthetic(matcher, a.mode, a.seed, a.limit, a.size_filter))

    summary = _summary(results, a.mode, a.size_filter)
    print("\n" + "═" * 72)
    print(f"  {a.mode.upper()}  —  {CAVEAT[a.mode]}")
    print("═" * 72)
    _print_summary(summary, results)

    # The filter changes which scans miss, so it must not overwrite the
    # unfiltered run's sheet — comparing the two by eye is the point of having
    # them at all.
    suffix = "-size" if a.size_filter else ""
    sheet = write_failure_sheet(
        results, POC_ROOT / "index" / f"failures-{a.mode}{suffix}.jpg", matcher)
    if sheet:
        print(f"  failure sheet: {sheet}  (query | candidate 1 | 2 | 3)\n")

    if a.report:
        a.report.write_text(json.dumps({"summary": summary, "results": results}, indent=2))
        print(f"  report: {a.report}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
