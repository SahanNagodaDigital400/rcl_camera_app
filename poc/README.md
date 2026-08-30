# Tile matcher — POC

Answers one question: can a DINOv2 embedding of a phone photo retrieve the right
tile out of a catalogue of near-identical low-contrast textures? Everything else
in the product is ordinary work; this is the part that could fail.

Runs entirely locally. No auth, no cloud, no Postgres.

## Run it

```bash
make setup     # .venv on python 3.13 + deps  (~1 min)
make model     # DINOv2-base ONNX weights, 346 MB  (~1 min)
make index     # embed Tiles/ into vectors        (~20 min, once)
make serve     # http://localhost:8000
```

Then either use the camera on the page, drop a photo onto it, or:

```bash
make match IMG=some-photo.jpg
make test          # unit tests, including the AD-1 symmetry check
make eval          # synthetic leave-one-out accuracy
make eval-real     # accuracy on real photos (see below)
```

### Testing from a phone

`getUserMedia` needs a secure context. That is satisfied on `localhost`, but not
over plain HTTP from a phone, so the live camera preview will not start there.
Use `make lan`, open `http://<your-ip>:8000` on the phone and tap **Choose /
take photo** — a file input with `capture="environment"` opens the native camera
and works over plain HTTP.

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
| Query views | 2 (full frame + centre zoom) | Framing only — rotation is already covered. |
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
3. **`30X90/ARKE` has no usable image.** Both of its files are zero-byte, so the
   product does not exist in the index at all — 36 products, not 37. Someone
   needs to re-export it.
4. **`30X90/Untitled folder` has no design name.** Its 11 tiles are indexed with
   design `UNKNOWN` and flagged in the ingest report. Face numbers 279 and 281
   also appear in `ARKE`, which suggests a link, but that is an inference the
   data does not state — so nothing infers it.
5. **15 files have no recoverable face number** (the dash-delimited `FLUTE`
   convention, e.g. `RC-001-OHA-156-MA-J2`). The code is kept and returned; only
   the face field is null.

## What the source data actually is

Worth recording, because `CLAUDE.md` is wrong about some of it:

- 133 files, **131 usable**, 36 products across 3 size folders.
- 123 `.jpg` + **10 `.tif`**. TIFF is not mentioned anywhere in the planning docs.
- 384 KB to **96 MB**; 672×672 up to **14457×4819**. `CLAUDE.md` says
  "2–6.5 MB" — wrong by more than an order of magnitude.
- Flat full-bleed texture scans. No background, no perspective, no room scenes.
- **Orientation is not consistent** — `Untitled folder/279` is landscape while
  `FLUTE/*` are portrait at the same nominal size. This is why rotation
  invariance is not optional.
- **Five** filename conventions coexist, not the two `CLAUDE.md` describes.
  All five are pinned in `tests/test_catalog.py`.
- Face counts are lopsided: `45X90/POLISH` has 22, 11 products have exactly 1.

## Findings

Measured on this catalogue, not assumed. Numbers are top-3 at product
granularity on the synthetic leave-one-out eval (n=122).

### 1. Five reference images carry no retrievable texture

```
std= 0.00  40X40/MONO COLOUR GLOSSY/Copy of 11B.jpg     ← every pixel exactly 255,255,255
std= 0.82  40X40/MONO COLOUR MATT/Copy of 61M.jpg       ← near-pure black
std= 2.04  45X90/POLISH/Copy of RP.RSS.0013ST.PL.0T.jpg
std= 2.29  40X40/HIDRA/Copy of Hidra Ivory 2_2HJ.jpg
std= 2.66  40X40/CARRARA MARBLE/Copy of 18K).jpg
```

`MONO COLOUR GLOSSY 11B` embeds to a vector *identical* to `RUANDA 7CM` — a
cosine of exactly 1.0. A featureless reference matches any washed-out photo and
can never be reliably retrieved itself.

For a genuinely plain tile this is not a bug to fix; it is the ceiling of what
image retrieval can do. It is also the clearest possible argument for the
always-three-candidates-with-reference-images rule: for these products the
reference image is the only thing that lets staff resolve the answer.

`make index` now flags these in the ingest report.

### 2. White balance is the dominant error source

Removing white-balance jitter from the synthetic query — changing nothing else —
moves top-3 from **79.5% to 90.2%** and top-1 from 65.6% to 77.0%. That is a
larger effect than crop, perspective, blur and JPEG combined.

The studio-to-phone domain gap is, first and foremost, a colour-cast gap. Worth
attacking directly in production: colour constancy in preprocessing, capture
guidance, or a white reference in frame.

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
| **0.00** | **65.6%** | **79.5%** |
| 0.10 | 57.4% | 75.4% |
| 0.30 | 53.3% | 63.9% |
| 0.50 | 47.5% | 60.7% |

The obvious objection is that the query's own white-balance jitter destroyed the
colour signal by construction. It was re-run with that jitter removed, and
colour still hurt monotonically (90.2% → 84.4% → 78.7%). The result holds.

Colour is not carrying independent signal here; DINOv2's features already encode
what is usable, and the histogram mostly adds noise. **Do not re-litigate this
without real photos** — the experiment is in the git history of this POC.

## Reading the eval numbers

Three modes, in ascending order of how much they mean:

| Mode | What it proves |
|---|---|
| `make eval-sanity` | The pipeline is wired up. Query is in the index. Should be ~100%. **Never quote this as accuracy.** |
| `make eval` | Generalisation across faces — the query image's vectors are removed before searching, so a hit means a *different* face of the same product was retrieved. Still a warped studio asset, not a photo. |
| `make eval-real` | The only number that decides anything. |

Correctness is scored at **Product** (size + design) granularity, per the PRD: a
scan counts as correct if any of the three candidates matches the true product,
even when another candidate is a different face of it. Both top-1 and top-3 are
reported; top-3 is the one that reflects real usefulness.

To run the real eval, drop phone photos in as:

```
queries/<SIZE>/<DESIGN>/<anything>.jpg
queries/45X90/CREMA MARMOL/IMG_0042.jpg
```

Both eval modes also write `index/failures-<mode>.jpg` — each miss as a row of
query beside its three candidates. These textures are subtle enough that a miss
is only interpretable by eye.
