"""A/B two indexes on the same synthetic leave-one-out queries.

Each index is scored with the preprocessing it was built with — grey-world has
to be applied to the query too, or the comparison measures an asymmetry rather
than the idea.
"""
import json, os, subprocess, sys

def run(index_dir, greyworld):
    env = dict(os.environ, TILEMATCH_GREYWORLD="1" if greyworld else "0")
    out = subprocess.run(
        [".venv/bin/python", "-m", "tilematch.evaluate", "--mode", "synthetic",
         "--index", index_dir, "--report", f"/tmp/eval-{'gw' if greyworld else 'base'}.json"],
        env=env, capture_output=True, text=True)
    if out.returncode != 0:
        print(out.stdout[-2000:]); print(out.stderr[-2000:]); sys.exit(1)
    return json.load(open(f"/tmp/eval-{'gw' if greyworld else 'base'}.json"))["summary"]

print("scoring baseline (no grey-world)...", flush=True)
base = run("index", False)
print("scoring grey-world...", flush=True)
gw = run("index-gw", True)

print(f"\n  {'variant':<24} {'top-1':>8} {'top-3':>8}   n")
print("  " + "-"*52)
print(f"  {'baseline (DINOv2 only)':<24} {base['top1']*100:7.1f}% {base['top3']*100:7.1f}%   {base['n']}")
print(f"  {'+ grey-world':<24} {gw['top1']*100:7.1f}% {gw['top3']*100:7.1f}%   {gw['n']}")
d1, d3 = (gw['top1']-base['top1'])*100, (gw['top3']-base['top3'])*100
print(f"  {'delta':<24} {d1:+7.1f}  {d3:+7.1f}")
print(f"\n  => grey-world {'WINS' if d3 > 0 else 'LOSES'} on top-3")
