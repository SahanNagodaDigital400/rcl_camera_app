# Tile matcher — POC

Answers one question: can a DINOv2 embedding of a phone photo retrieve the right
tile out of a catalogue of near-identical low-contrast textures? Everything else
in the product is ordinary work; this is the part that could fail.

Runs entirely locally. No auth, no cloud, no Postgres.

## The unit of identity is the file

`Tiles/<SIZE>/<CATEGORY>/<file>` — exactly three levels. **Every file inside a
category folder is a different tile, and each tile has exactly one reference
image.** 381 files = 381 tiles, in 76 category folders; 96% of them sit in
folders holding 2 to 26 siblings.

This corrects an earlier model in which `size + category` was the "product" and
the files inside were "faces" of it. Consequences, because they reach further
than they look:

- **Accuracy is scored against the exact file.** A candidate from the right
  folder but the wrong file is a miss. The old scoring counted it as a hit and
  overstated top-3 by about 9 points.
- **There is no leave-one-out eval.** A tile has one reference image, so
  removing it deletes the only correct answer rather than forcing
  generalisation. `make eval` is now a robustness upper bound, not a
  generalisation test — and that makes `make eval-real` the only number that
  decides anything.
- **Candidates are never deduplicated by category.** Three candidates from
  `45X90/POLISH` are three distinct tiles competing on merit. Collapsing them
  hides correct answers.

`tests/test_search_filters.py::TestTileIsTheUnitOfIdentity` is the regression
guard. Numbers recorded before this correction are not comparable to anything
below.

## Run it

```bash
make setup     # .venv on python 3.13 + deps  (~1 min)
make model     # DINOv2-base ONNX weights, 346 MB  (~1 min)
make index     # embed Tiles/ into vectors        (~20 min, once)
make serve     # http://localhost:8000
```

Tap any candidate to open its reference image full-screen — that is how staff
verify a match, so it is the point of the results screen, not a nicety.

Then either use the camera on the page, drop a photo onto it, or:

```bash
make match IMG=some-photo.jpg
make test          # unit tests, including the AD-1 symmetry check
make eval          # synthetic leave-one-out accuracy
make eval-real     # accuracy on real photos (see below)
```

### Testing from a phone

Use the LAN, not a dev tunnel. A tunnel routes over the internet, and a 198 KB
upload on a mobile uplink took long enough to trip the client timeout before the
request ever reached the server.

```bash
make lan          # http://<your-lan-ip>:8000
make lan-https    # https, self-signed — the live camera preview works
```

Both print the exact phone-reachable URL on startup.

`getUserMedia` requires a secure context, which `localhost` satisfies but a plain
`http://` LAN address does not — so over `make lan` the live preview will not
start, though **Choose / take photo** still works (a file input with
`capture="environment"` opens the native camera over plain HTTP).

`make lan-https` issues a self-signed certificate for the detected LAN IP into
`certs/` and serves TLS, which makes the live preview work too. The browser
warns once about the certificate; accept it and it is remembered. The
certificate is reissued automatically if the machine's LAN address changes.

**Type the plain `http://` address either way.** Under `--tls` the HTTPS
listener moves to port 8443 and the requested port keeps serving plain HTTP that
307-redirects to it. Without that, typing a bare IP — which every browser reads
as `http://` — hits a TLS socket with plaintext and returns
`ERR_EMPTY_RESPONSE`, which names neither the cause nor the fix.

### Upload failures are stalls, not timeouts

The client aborted on total elapsed time, which killed uploads that were
progressing perfectly well. Diagnosed from the server log: an abort was reported
by the browser at 20:24:34, and the first request the server ever saw was 30
seconds *later* — so the aborted request never arrived at all.

The client now aborts only when no bytes have moved for 25 s, shows real upload
progress (via `XMLHttpRequest`, since `fetch` reports none), and retries once on
a network failure. A stall and a slow link are no longer indistinguishable.

## How it works

```
index time:  reference scan → views + augmentation → preprocess → embed → vectors.npz
scan time:   phone photo    →   framing views      → preprocess → embed → cosine → top 3
                                                     └── identical code path ──┘
```

`tilematch/vision.py` is the whole invariant. It is the only module that turns
pixels into a vector, and both pipelines call `embed(preprocess(load_image(x)))`
with no wrapping or reimplementation. It is written to lift straight into
production's `shared/vision/`.

Augmentation and view selection sit *above* that boundary and hand plain PIL
images down. That is how index-only augmentation coexists with AD-1's demand
that the shared function be symmetric — a tension the planning docs never
resolve.

`tests/test_vision.py::test_index_and_query_paths_produce_identical_vectors` is
AD-1 as an executable assertion. Never let it fail. An asymmetry there destroys
accuracy silently and raises no error.

## Decisions taken here

The planning docs pin a backbone (DINOv2) and a runtime (ONNX Runtime, CPU) and
leave every number unset. AD-1 makes these expensive to change later — any
change to the shared module forces a full re-index plus an eval run — so these
POC choices are the de facto production spec until someone argues otherwise.

| Decision | Value | Why |
|---|---|---|
| Model | `Xenova/dinov2-base` ONNX, 86M params | Apache 2.0, ONNX-exported already, no export step of our own. DINOv3 is stronger but its licence was rejected upstream. |
| Input | shortest edge 256 bicubic → centre crop 224 | Straight from the model's own `preprocessor_config.json`. Not invented. |
| Normalization | ImageNet mean/std | Same source. |
| Embedding | `concat(L2(CLS), L2(mean patch))` → L2 → **1536-d** | DINOv2's own retrieval recipe. Beats CLS alone on fine-grained texture, which is exactly this problem. Fixes production's `vector(N)` at 1536. |
| Similarity | cosine, via unit-norm dot product | Vectors stored unit-norm, so cosine is one matmul. |
| Views per reference | 16 (4 clean rotations + 12 randomized crops) | See below. |
| Rotation invariance | baked into the **index** | Both places work; index cost is one-time and offline, query cost is per-scan and user-facing. |
| Query views | **1** (full frame) | A second centre-zoom view measured *worse* and doubled latency — see below. |
| Candidates shown | **3** (`server.DISPLAY_K`) that clear the match bar, 20 returned, rest above the bar behind an expander | Independent of `search.TOP_K`, which stays 3 — see below. |
| Match bar | **0.50** (`server.MATCH_FLOOR`, `TILEMATCH_FLOOR` to override) | Trims the tail off the results screen; inert at 0.50 on this catalogue. Not a confidence signal — the correct and wrong score distributions overlap almost entirely. See below. |
| Match percentage | **shown** (`server.SHOW_SCORE`, `TILEMATCH_SHOW_SCORE=0` to hide) | Display only; the score is always in the API and the log. See below. |
| Size filter | staff-selectable, default **All sizes** | The one attribute a photo cannot carry and the person holding the tile knows. Largest measured accuracy lever in the POC. |
| Reference view | 1280px q82, **pre-generated**, 300 KB budget | Building on demand meant decoding a 93 MB original — 1–3.5 s of spinner. |
| Decode cap | long edge 2048 | Deterministic, applied identically on both paths so it cannot become an asymmetry. |
| Pipeline stamp | `PIPELINE_VERSION` + config hash in `meta.json` | Search refuses an index built with different preprocessing. See open questions. |
| Grey-world | **off** | Measured at +1.6 top-3, inside the noise band. See findings §3. |

### Why multiple vectors per reference image

Reference scans are full-bleed textures up to 14457px. A phone photo captures a
fraction of one tile at a completely different scale. Squashing a whole scan
into 224px destroys the fine texture that separates these products, so each
reference contributes 16 views — 4 clean rotations of the full frame plus 12
randomized crops (scale 25–60%) carrying lighting, white-balance, blur,
perspective and JPEG augmentation.

Views are sampled randomly rather than as a full cross-product: a 6-crop ×
4-rotation × 3-augmentation grid is 72 embeddings per image, and at ~490 ms each
that is hours. The per-image seed keeps a build reproducible.

At search time, similarities are max-pooled per reference image.

### Preparing the reference tree

Reference scans reach 19276x9638, but the pipeline caps decode at
`DECODE_MAX_EDGE` (2048px), so none of that resolution ever reaches the model —
it is decoded and thrown away on every single rebuild.

`make prep` writes a parallel `Tiles-prepared/` tree of already-decoded,
already-colour-managed sRGB copies. The source tree is never modified.

| | per image |
|---|---|
| decode from source | 3590 ms |
| decode from prepared | **30 ms** |

Disk drops about 10x as well (3.6 GB -> 0.29 GB). It is incremental, so adding
tiles only prepares the new ones, and it prunes copies whose source has been
deleted — without that, removing a tile from `Tiles/` would leave it in the
index for ever. The cache carries `config_hash()`, so a change to colour
management or the decode cap invalidates it exactly as it invalidates the
vectors.

### Where scan time actually goes

`make serve` logs a phase breakdown per scan, because "slow" has three unrelated
causes here and one total cannot separate them:

```
scan 206 ms  =  upload 13 KB | decode 1 ms | embed 205 ms (1 views, 205 ms/view) | rank 0.3 ms
```

Inference is ~97% of server time. Decode is ~1 ms warm, and the brute-force
cosine over 2,096 vectors is 0.3 ms — the thing production would replace with
pgvector is three orders of magnitude below the thing that actually costs.

Two changes came out of reading these:

- **A second query view was dropped.** A 0.55 centre zoom max-pooled with the
  full frame scored *worse* — top-1 67.2% → 65.6%, top-3 81.1% → 79.5% — for
  double the inference. Max-pooling lets a spurious high match on the zoomed
  crop outrank the correct full-frame one. Scan time went 440 ms → 206 ms.
  (`experiments/query_views.py`)
- **The server warms up at startup.** Creating the ONNX session for a 346 MB
  model and running the first forward pass costs ~900 ms. Paying that before the
  first user scan turns "the app is slow" back into "the app was cold".

If a scan feels slow beyond this, it is the network: a 206 ms server response
sat inside a 1526 ms round trip over a dev tunnel on mobile data.

### Overlapping scans

Tapping capture repeatedly used to look like a hang. Eight concurrent scans took
**2.6 s each instead of 206 ms** — a 12x collapse. Each scan takes 4 ONNX
threads, so eight of them put 32 threads on 4 performance cores and every one
crawled.

Nothing in the log showed it, because a scan was only logged once it *finished*.
A request that never finished produced no line at all.

Three fixes:

- **Logged on arrival, with a request id.** Every scan now traces
  `received -> upload complete -> queued -> started -> done`, so a stall is
  visible at the phase it stalls in.
- **Scans are serialised** (`_scan_slot`). Inference already saturates every
  core, so concurrency buys no throughput — it only thrashes. Eight stacked scans
  now finish in 0.22–1.93 s, each running at full speed, instead of all eight
  taking 2.6 s. Thumbnails still serve in 6 ms throughout.
- **The client sends one at a time.** Capture is disabled while a scan is in
  flight, a new scan aborts the one in flight rather than queueing behind it
  (the user wants the latest shot, not a backlog), and a 30 s timeout reports a
  dead server instead of spinning forever.

`_get_session()` also took a lock. Scans run in a threadpool, so two first-scans
could race and each build a session, loading the 346 MB model twice.

### The second scan in a session did nothing

Separate bug with the same shape as a hang, and a sharp signature: the first
scan worked, the second gave no response, and a reload bought exactly one more.

A reload fixing it means the state is in the page, not the server. It was:

```js
setBusy(true);                    // buttons disabled, inFlight set
blob = await shrink(blob);        // ...outside the try
try { fetch(...) } finally { setBusy(false); }
```

Anything that threw in `shrink()` went straight past the `finally`, so the
buttons stayed disabled and `inFlight` stayed set — the page was dead with no
error shown. `shrink()` throwing is not hypothetical: it draws a full-resolution
phone photo (~50 MB as raw canvas pixels) and mobile browsers cap total canvas
memory, so the second large photo is exactly where allocation fails.

Three fixes:

- **The whole body is inside the try.** State is restored no matter what fails.
- **Canvas memory is released explicitly** (`c.width = c.height = 0` after
  encoding, plus `bmp.close()` in a `finally`). Mobile browsers do not reclaim
  the backing store promptly on their own.
- **The file input clears its value** after each pick, so choosing the same file
  twice fires `change` again instead of looking dead.

And because none of this was visible while testing on a phone over a tunnel,
`/api/client-log` now beacons browser errors — including `window.onerror` and
unhandled rejections — into the server log:

```
14:49:24  WARNING [client] js error: simulated canvas failure
```

A client-side failure previously presented as "no response from server", which
sent the investigation to entirely the wrong side.

### Reference images

Tapping a candidate used to hang for seconds. `/reference/{id}` was building the
view on demand, which means decoding an original of up to 93 MB — measured at
1–3.5 s before a single byte was sent.

They are now pre-generated by `make index` / `make thumbs`:

| | before | after |
|---|---|---|
| worst case (93 MB source) | 2752 ms | **3 ms** |
| typical | ~500 ms | **2 ms** |

Three further changes attack the transfer rather than the generation:

- **Prefetched on render.** The visible candidates' references start downloading
  while the user is still reading the list, so a tap usually paints from cache.
- **The thumbnail stands in instantly.** It is already cached, so a blurred copy
  is on screen in the same frame as the tap and is swapped for the full image
  when it lands. Nothing ever shows an empty box.
- **A 300 KB byte budget.** Detailed textures encoded up to 540 KB against a
  112 KB median; quality steps down only for those. Worst case 1.4 s → 0.9 s on
  4G, with ~90% of the set untouched at full quality.

The server logs a warning if it ever has to build one on demand, since that path
costs seconds and should never be hit in normal use.

### Why not a score threshold

"Show everything above 0.4" is the natural request, and it does not work here.
Cosine similarity on these features has no meaningful absolute zero. Measured
against this catalogue of 131 references:

| query | above 0.4 | above 0.6 | above 0.7 |
|---|---|---|---|
| true match (Crema Marmol) | 86 | 74 | 49 |
| true match (Quarry Stone) | 101 | 60 | 32 |
| random noise, not a tile | 28 | 4 | 2 |

0.4 is close to the *median* similarity between any two tiles, so it selects
most of the catalogue and buries the answer. The scores are ranking signals, not
calibrated probabilities, and the absolute value drifts with the query.

So the API returns the top 20, the UI shows up to three that clear the match
bar, and an expander reveals the rest above it — the tail gets trimmed, the
ranking still decides. If a calibrated threshold is ever wanted, it has to be
fitted against real photos and expressed relative to the top score, not as an
absolute.

### What the match bar does

`server.MATCH_FLOOR` hides candidates below it from the results screen. **The
default is currently 0.50**, which on this catalogue trims nothing at all — every
scan still shows three. Read the bar as a tail trim, not as confidence, because
on the 381-tile synthetic eval the two score distributions are almost
indistinguishable:

| top-1 candidate | p10 | median | p90 |
|---|---|---|---|
| correct (n=212) | 0.806 | **0.918** | 0.966 |
| wrong (n=169) | 0.814 | **0.907** | 0.988 |

The wrong answers' p10 is *higher* than the correct ones', and their p90 is
higher too. What the bar costs and buys at each setting:

| bar | correct answers kept | wrong answers still shown | scans left with nothing |
|---|---|---|---|
| **0.50** (default) | **100%** | **100%** | **0%** |
| 0.70 | 98% | 99% | 1% |
| 0.80 | 91% | 92% | 9% |
| 0.90 | 64% | 54% | 40% |

At 0.50 the bar is inert on this catalogue — nothing scores below it, so the
screen always shows three. At 0.80 it keeps 91% of correct answers and 92% of
wrong ones, which is still very nearly a no-op on the ranking. That is what a bar
does here: it shortens the list and keeps obviously-unrelated tiles off the
screen, but it does **not** make what remains more likely to be right, and it
must never be presented to staff as though it did. Raising it begins to
discriminate — at 0.90 the wrong-answer rate finally drops faster than the
correct one — but it costs 36% of all correct answers to get there.

Set `TILEMATCH_FLOOR` to move it without a code edit — `TILEMATCH_FLOOR=0.9 make
serve` — which is also how to try a setting before changing the default. It is a display decision, not a pipeline one, so changing it does **not**
invalidate the index the way anything in `vision.py` would.

The sharpest demonstration that the bar is not a confidence signal: a JPEG of
pure random noise, which is not a tile at all, still returns two candidates above
0.80 (best 0.826). The bar cannot tell "wrong tile" from "not a tile".

The same caveat applies to the percentage on each candidate card, which is the
cosine similarity rounded — 92% and 91% are the medians of the *correct* and
*wrong* distributions above, so the number separates candidates from each other
and says nothing about whether any of them is right. The note under the results
says so on screen, because a bare percentage next to a tile code will otherwise
be read as confidence.

**The percentage is a toggle**, `server.SHOW_SCORE`, on by default:

```bash
TILEMATCH_SHOW_SCORE=0 make serve     # hide it
TILEMATCH_SHOW_SCORE=1 make serve     # show it (default)
```

It is a setting rather than a decision because the number cuts both ways — useful
for comparing the three candidates against each other, misleading as confidence
in any one of them — and which risk dominates depends on who is holding the
phone. Turning it off also hides the explanatory sentence under the results,
since that sentence only exists to qualify the number.

Display only: the score stays in the API response and the server log either way,
so hiding it from staff does not blind anyone debugging a scan. Like
`MATCH_FLOOR`, the toggle is folded into `build_stamp()` — a stamp that missed it
would report "current" while the page showed something else.

Because a bar can legitimately leave nothing on screen, the empty state offers
**Show the closest matches anyway** as an explicit tap. It is opt-in rather than
automatic: CLAUDE.md's rule is *never one confident answer*, and silently
back-filling three would turn "nothing was close" into "here are three", which
is the failure mode the rule exists to prevent.

### Choosing the size before the scan

The scan screen has a size picker, defaulting to All sizes and remembered in
`localStorage` between scans. Choosing one restricts scoring to references of
that size before ranking — a hard filter in `Matcher.score_images`, not a
re-rank, because a 60X30 tile is never the answer to a scan declared 45X90.

This is the largest accuracy lever in the POC, and it is not a model change: it
is the one attribute a photo cannot carry and the person holding the tile always
knows. See "Accuracy" below for the measured effect.

The cost is symmetrical. A *mis*-declared size makes the true product
unreachable — no amount of ranking recovers from it — which is why the hint text
tells staff to set it back to All sizes when unsure, and why the eval flag
`--size-filter` is documented as an upper bound rather than a prediction.

**`server.DISPLAY_K` and `search.TOP_K` are deliberately separate.** `TOP_K`
stays at 3 because `evaluate.py` scores against it; raising it to match the
display would silently relabel a top-10 accuracy number as top-3. The PRD's
"up to three Candidates" (FR-7) is also written against `TOP_K`. Showing more
than three is safe — the rule it protects is *never one*, and more candidates
only strengthens that — but the two numbers must not be collapsed into one.

## Divergences from the production design

Deliberate, and each one is a POC-scope call rather than a disagreement:

- **numpy brute force, not pgvector + HNSW.** ~2k vectors is one matmul,
  sub-millisecond, and dominated by embedding cost anyway. Production should
  still use pgvector; `CLAUDE.md`'s measure-first rule points the same way.
- **No auth, sessions, audit log or rate limiting.** None of it is stubbed,
  because a half-built auth layer is worse than an obviously absent one.
- **Local files, not S3.**
- **Multiple vectors per reference image** — see the open question below.

## Open questions this POC hands back to production

1. **The ERD cannot express multi-vector.** `REFERENCE_IMAGE` is modelled as one
   row with one `embedding` column. 16 vectors per image needs a child table, or
   pooling them into one — which gives back the scale invariance the crops buy.
   This needs deciding before `shared/vision/` is written.
2. **There is no pipeline version column.** The only stated mechanism is
   procedural ("state the re-index in the PR"). This POC stamps
   `PIPELINE_VERSION` and a config hash into the index and refuses to search a
   mismatched one; production should carry the same stamp on the row.
3. **`30X90/ARKE` has no usable image.** Both of its files are zero-byte, so
   those tiles do not exist in the index at all — 36 categories, not 37. Someone
   needs to re-export it.
4. **`30X90/Untitled folder` has no category name.** Its 11 tiles are indexed
   with category `UNKNOWN` and flagged in the ingest report. Codes 279 and 281
   also appear in `ARKE`, which suggests a link, but that is an inference the
   data does not state — so nothing infers it.
5. **15 files have no recoverable trailing number** (the dash-delimited `FLUTE`
   convention, e.g. `RC-001-OHA-156-MA-J2`). The code is kept and returned, and
   the code alone identifies the tile, so nothing is lost — only the `face`
   display hint is null.
6. **Are any two files ever the same physical tile?** Rocell confirmed each file
   is a different tile, which is what this POC now implements. If that ever turns
   out to have exceptions — the same tile scanned twice, say — the eval will
   score those as misses when the app was right. Nothing in the file names would
   reveal it; it needs a person who knows the catalogue.

## What the source data actually is

Worth recording, because `CLAUDE.md` is wrong about some of it:

- 133 files, **131 usable** — i.e. 131 tiles — in 36 category folders across 3
  size folders. (The current index is a later, larger export: 381 tiles in 76
  category folders across 4 sizes.)
- 123 `.jpg` + **10 `.tif`**. TIFF is not mentioned anywhere in the planning docs.
- 384 KB to **96 MB**; 672×672 up to **14457×4819**. `CLAUDE.md` says
  "2–6.5 MB" — wrong by more than an order of magnitude.
- Flat full-bleed texture scans. No background, no perspective, no room scenes.
- **Orientation is not consistent** — `Untitled folder/279` is landscape while
  `FLUTE/*` are portrait at the same nominal size. This is why rotation
  invariance is not optional.
- **Five** filename conventions coexist, not the two `CLAUDE.md` describes.
  All five are pinned in `tests/test_catalog.py`.
- Folder sizes are lopsided: `45X90/POLISH` holds 22 tiles, 11 categories hold
  exactly 1. This is why "one image per tile" was easy to mistake for "many faces
  per product" — a 22-file folder looks like a range until you check the codes.

### Accuracy falls as the catalogue grows

The clearest scaling signal so far, measured on the same pipeline as the
catalogue roughly doubled:

| catalogue | categories | top-1 | top-3 |
|---|---|---|---|
| 131 images | 36 | 65.6% | **79.5%** |
| 381 images | 76 | 56.3% | **70.0%** |

⚠ **Both rows were produced by the old leave-one-out harness with loose
`size + category` scoring, and cannot be reproduced.** The trend is probably
real — nothing about the pipeline changed between them, only the number of
things it has to tell apart — but the magnitude is not trustworthy, and there is
no honest way to recompute the 131-image row without rebuilding that catalogue.
Treat this as a flag to re-measure at scale, not as a result.

Production targets a far larger catalogue, so this is the number to watch, and
it is an argument for measuring against real photos at realistic scale before
committing to the approach. A 224px global embedding may simply not have the
capacity to separate thousands of near-identical textures; if that holds, the
answer is higher input resolution or local-feature re-ranking on the top-N, not
more augmentation.

### Declaring the size recovers most of that loss

`make eval-size` runs the same 381 queries with each one restricted to its own
size, which is what the size picker does when staff get it right. Exact-tile
scoring:

| | top-1 | top-3 |
|---|---|---|
| all sizes | 55.6% | 78.7% |
| size declared | **59.1%** | **81.9%** |

**+3.2 points of top-3.** Worth having — it is free at scan time, costs no model
change, no re-index and no extra inference — but it is a modest gain, not the
transformation an earlier draft of this file claimed. That draft reported +9.8,
and almost all of the difference was the loose `size + category` scoring, not the
filter.

The gain tracks how much of the catalogue the filter removes from contention:

| size | tiles | top-3 all sizes | top-3 size declared | delta |
|---|---|---|---|---|
| 60X30 | 250 | 80.0% | 81.2% | +1.2 |
| 45X90 | 75 | 78.7% | 86.7% | **+8.0** |
| 40X40 | 36 | 77.8% | 83.3% | +5.6 |
| 30X90 | 20 | 65.0% | 70.0% | +5.0 |

60X30 is two thirds of this catalogue, so declaring it rules out almost nothing
and buys almost nothing — which is the thing to carry into production. **The
lever is catalogue narrowing, not size as such.** Any attribute staff can supply
at scan time and the photo cannot carry pays out in proportion to how much of the
catalogue it eliminates: size first, then finish (matt/gloss/polished), then room
or collection. Once 60X30 alone runs to thousands of tiles, size will buy as
little there as it does here, and a second filter will be needed.

This is an upper bound on the feature, not a prediction. It assumes the declared
size is correct; a mis-declaration makes the true tile unreachable rather than
merely lower-ranked, and no re-ranking recovers from it. That asymmetry is why
the picker defaults to All sizes and says so on screen.

### Why candidates are never deduplicated (OQ-12, settled)

An earlier draft measured "fill the three slots with three distinct products
instead of three top-ranked images" and reported +5.4 points. **That measurement
was an artefact of the wrong identity model and has been removed.** Under the
correct model those "products" are category folders, and collapsing candidates
by folder would merge distinct tiles — discarding correct answers, not
duplicates. Three candidates from `45X90/POLISH` are three different tiles, and
all three deserve a slot.

This settles PRD OQ-12 in the POC: do not deduplicate. `search.Matcher.search`
says so, and `TestTileIsTheUnitOfIdentity` enforces it.

## Findings

Measured on this catalogue, not assumed. Numbers are top-3 at product
granularity on the synthetic leave-one-out eval (n=122).

### 0. Most reference images are CMYK press assets, not photographs

Found late, by eye, when a preview looked green. It was the most consequential
bug in the POC.

```
  63  U.S. Web Coated (SWOP) v2        ← CMYK print profile
  31  sRGB IEC61966-2.1
  18  RPL_SYSTEM_LINE3_POLISH_CMBK_21012024.icc
  13  (none)
   6  other custom press profiles (CMYK)
```

Only **31 of 131** references are sRGB. The rest are printing-press files, most
of them CMYK. A plain `.convert("RGB")` ignores the embedded profile, and on
`RP.RSS.0062ST.PL.0T` that put the green channel 30 levels high on average and
68 at worst — rendering a dark brown-black marble as bright green.

Across a 28-image sample, **17 shifted by more than 2 levels, averaging 12.6 and
peaking at 84.6**.

Two consequences, the second much worse than the first:

1. Staff saw wrong colours, and would reject a correct match on sight.
2. **Every affected vector was embedded from wrong pixels.** Phone queries are
   sRGB, so roughly 60% of the catalogue was being compared across colour
   spaces — a systematic domain gap introduced by the pipeline itself.

**There were two bugs here, not one.** Fixing the profile got the hue right but
left Pillow's default *perceptual* rendering intent in place, and these press
profiles carry perceptual tables that LittleCMS renders far darker than the file
is. Validated against macOS ColorSync on the same tile:

| conversion | mean brightness |
|---|---|
| macOS ColorSync (reference) | **84.2** |
| naive `.convert("RGB")` | 33, plus the green cast |
| ICC + perceptual intent | **25.0** — near-black |
| **ICC + relative colorimetric** | **84.3** ✓ |

Relative colorimetric matches ColorSync within ~1 level on every profile type in
this tree; perceptual was off by up to 59. Black-point compensation makes it
worse again (41), so it stays off. The tile is a medium grey-brown marble — it
was rendered green, then near-black, before it was rendered correctly.

`vision.load_image` now transforms through the embedded profile into sRGB at
relative colorimetric, and `draft()` no longer requests RGB (asking for it
discarded the profile silently, which is what hid the first bug). Pinned by
`TestColourManagement`, which guards **brightness as well as hue** — the
first fix passed its own green-cast test while still being badly wrong.

### What the synthetic eval can and cannot see

Correcting the colour moved synthetic accuracy *down* slightly, from 82.0% to
79.5% top-3 — three queries, inside the noise band. (Both figures predate the
identity correction and the harness that produced them is gone; the reasoning
below is unaffected, since it turns on what the eval can see, not on the value.)

That is not evidence against the fix, because **the synthetic eval is structurally
blind to colour correctness**. Query and reference are derived from the same
studio file through the same colour pipeline, so any colour error applies
identically to both sides and cancels. The eval measures texture
discriminability, nothing more.

The benefit of correct colour appears only where the two sides come from
different places: a real phone photo of a real tile against a reference image.
That is `make eval-real`, and it is another reason the synthetic numbers cannot
settle anything on their own.

### 1. Five reference images carry no retrievable texture

```
std= 0.00  40X40/MONO COLOUR GLOSSY/Copy of 11B.jpg     ← every pixel exactly 255,255,255
std= 0.00  40X40/MONO COLOUR MATT/Copy of 61M.jpg       ← now also exactly flat
std= 2.79  40X40/HIDRA/Copy of Hidra Ivory 2_2HJ.jpg
std= 2.97  40X40/CARRARA MARBLE/Copy of 18K).jpg
```

(Four, not five: `45X90/POLISH/RP.RSS.0013ST` cleared the threshold once colour
management stopped flattening it.)

`MONO COLOUR GLOSSY 11B` embeds to a vector *identical* to `RUANDA 7CM` — a
cosine of exactly 1.0. A featureless reference matches any washed-out photo and
can never be reliably retrieved itself.

For a genuinely plain tile this is not a bug to fix; it is the ceiling of what
image retrieval can do. It is also the clearest possible argument for the
always-three-candidates-with-reference-images rule: for these products the
reference image is the only thing that lets staff resolve the answer.

`make index` now flags these in the ingest report.

### 2. White balance is the dominant error source

Removing white-balance jitter from the synthetic query — changing nothing else:

| query | top-1 | top-3 |
|---|---|---|
| with white-balance jitter | 65.6% | 79.5% |
| without | 73.8% | 86.1% |
| **gap attributable to WB** | **+8.2** | **+6.6** |

Still the single largest lever measured, ahead of crop, perspective, blur and
JPEG. Worth attacking in production: capture guidance, or a white reference in
frame.

*Re-measured on the colour-managed index (§0). The original number was +10.7 on
top-3 — roughly four of those points were the colour bug, not white balance.
Reproduce with `experiments/wb_ablation.py`.*

### 3. Grey-world colour constancy does not fix it either

The natural response to §2 is colour constancy in the shared preprocessing. It
was built (`TILEMATCH_GREYWORLD=1`, applied symmetrically inside `preprocess`)
and A/B'd on a full re-index:

| variant | top-1 | top-3 |
|---|---|---|
| baseline | 63.1% | 78.7% |
| + grey-world | 63.1% | 80.3% |

**+1.6 points on top-3 is two queries out of 122 — inside the noise band** (the
95% interval at this sample size is roughly ±7). Treat it as no measurable
effect.

*These numbers predate the ICC fix (§0) and have not been re-measured — doing so
costs two full index builds. The conclusion is unlikely to move, for the reason
below, but treat the figures as stale rather than current.*

There is a principled reason it cannot work here. Grey-world assumes the scene
averages to grey, so a channel imbalance must be the illuminant. A reference
image in this catalogue is one full-bleed single-colour surface — a pink marble
genuinely *is* pink. The assumption is violated by construction, so the
correction strips the tile's real colour along with the cast.

Separating illuminant from surface needs information grey-world does not have: a
white reference in frame, capture guidance, or learned colour constancy. The
toggle is left in place, defaulted off, for re-testing against real photos.

### 4. Adding a colour descriptor makes it worse

The other response to §2 is to weight colour more heavily. It was tried — a
Lab a/b + L histogram concatenated to the DINOv2 vector, weight swept 0.0–0.7 —
and accuracy fell monotonically:

| weight | top-1 | top-3 |
|---|---|---|
| **0.00** | **69.7%** | **81.1%** |
| 0.05 | 63.1% | 78.7% |
| 0.10 | 59.0% | 76.2% |
| 0.20 | 55.7% | 70.5% |
| 0.50 | 45.9% | 62.3% |

Two objections were tested and neither rescued it. That the query's own WB jitter
destroys the colour signal by construction — re-run without it, colour still hurt
monotonically. And that §0's colour bug was poisoning the descriptor — this table
is the post-fix re-run, and it hurts *more* steeply than before.

Colour carries no independent signal here; DINOv2's features already encode what
is usable and the histogram adds noise. **Do not re-litigate this without real
photos.** Reproduce with `experiments/colour_descriptor.py`.

## Reading the eval numbers

Three modes, in ascending order of how much they mean:

| Mode | What it proves |
|---|---|
| `make eval-sanity` | The pipeline is wired up. Query is the unmodified reference. Should be ~100%. **Never quote this as accuracy.** |
| `make eval` | Robustness: the reference image degraded by `synthesize_query` — lighting, white balance, blur, perspective, JPEG — then matched against an index that still holds it. A **loose upper bound**, because a warp of image X is far closer to X than any photo of the physical tile. |
| `make eval-size` | The same, with each query restricted to its own size. |
| `make eval-real` | The only number that decides anything. |

**There is no leave-one-out mode, and its absence is the point.** A tile has
exactly one reference image, so excluding it removes the only correct answer
rather than forcing generalisation. Nothing in the synthetic modes tests
generalisation to an unseen view of a tile any more — only `make eval-real` can.

Correctness is scored against **the exact tile — the file**. A candidate from the
right category folder but the wrong file is a miss. The harness also prints a
`same-folder` number for contrast; it is a diagnostic showing how much looser the
old scoring was, and must never be quoted as accuracy. Both top-1 and top-3 are
reported; top-3 is the one that reflects real usefulness, since staff verify
against the reference image.

To run the real eval, drop phone photos in as:

```
queries/<SIZE>/<CATEGORY>/<CODE>/<anything>.jpg
queries/45X90/CREMA MARMOL/RP.CMA.0001DJ.SM.0T/IMG_0042.jpg
```

The `<CODE>` level is required, and is what makes strict scoring possible —
without it a photo only says which folder it came from. It is the reference file
name with `Copy of ` and the extension stripped: exactly what the scan screen
shows as the answer. Photos left at the old three-level depth are skipped with a
warning rather than silently mis-scored.

Both eval modes also write `index/failures-<mode>.jpg` — each miss as a row of
query beside its three candidates. These textures are subtle enough that a miss
is only interpretable by eye.
