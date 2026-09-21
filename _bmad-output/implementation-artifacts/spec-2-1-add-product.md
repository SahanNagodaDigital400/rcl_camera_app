---
title: 'Story 2.1 — Add Tile'
type: 'feature'
created: '2026-09-21'
status: 'done'
baseline_revision: '2b807c12f1951ba844cadff0a62cdd1f7666a95d'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-2-context.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-rcl_camera_app-2026-08-30/ARCHITECTURE-SPINE.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/DESIGN.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/EXPERIENCE.md'
warnings: ['oversized']
deferred:
  - summary: >-
      The whole multipart body is spooled to disk before `require_administrator` runs, so an
      unauthenticated caller can consume disk with an oversized upload.
    evidence: |-
      FastAPI awaits `request.form()` before solving dependencies, so up to
      MAX_IMAGES_PER_REQUEST x MAX_IMAGE_BYTES is written to the spool file before any authz
      check. Fixing it needs a body-size limit at the reverse proxy or a Starlette middleware,
      and this spec's Never list forbids middleware.
    location: >-
      apps/api/api/catalogue.py add_tile
    severity: medium
  - summary: >-
      `make test` is green on a machine that has never run `make model`, so AD-1's symmetry
      assertion and the entire catalogue write path can silently never execute.
    evidence: |-
      34 tests are gated on `pipeline.MODEL_PATH.exists()`, including
      test_the_write_path_and_the_query_path_produce_identical_vectors. Nothing in `make test`
      depends on the model target or asserts the gated tests ran. There is no CI workflow in the
      repository (see DW-2), so a developer's `make test` is the only gate.
    location: >-
      Makefile test target
    severity: medium
  - summary: >-
      The HNSW index is built and maintained on every insert but no statement in the codebase
      queries through it.
    evidence: |-
      `_SELECT_CANDIDATES` is a grouped min() scan over reference_embedding, chosen for exact
      max-over-views semantics. At catalogue scale that is correct and fast, but every insert
      pays HNSW graph maintenance for an index nothing uses, and nothing asserts a query plan.
      An index-friendly two-stage probe is the measurable follow-up.
    location: >-
      apps/api/api/catalogue.py _SELECT_CANDIDATES
    severity: low
  - summary: >-
      AD-16's inference serialization and startup warm-up are absent, so concurrent catalogue
      adds oversubscribe the CPU exactly as the POC measured.
    evidence: |-
      The ported session lock prevents a double model load but not concurrent forward passes.
      An add holds a threadpool worker for 16 passes per image; the POC measured 8 concurrent
      scans collapsing to 2.6s each. AD-16 binds the scan endpoint (Epic 3), which is where the
      shared serialization slot and the ~900ms cold start belong.
    location: >-
      shared/vision/shared_vision/pipeline.py
    severity: medium
  - summary: >-
      `pixel_std` is measured on the 2048px-capped image over the whole RGB array, so the
      featureless flag differs from the POC and never fires on a flat coloured tile.
    evidence: |-
      The POC computes the deviation on a thumbnail; the port computes it on the full capped
      image, and FEATURELESS_STD = 3.0 carried over unchanged. Because the deviation is taken
      across all three channels, a flat coloured reference measures around 6 and is not flagged
      while a flat neutral one measures 0 and is. MONO COLOUR ranges are exactly the case FR-19
      names, and the POC found MONO COLOUR GLOSSY 11B embedding to cosine 1.0 with RUANDA 7CM.
    location: >-
      shared/vision/shared_vision/intake.py
    severity: medium
  - summary: >-
      `find_candidates` takes an already-decoded PIL image, so a caller can reach the embedder
      without passing through AD-7 intake and AD-15 colour management.
    evidence: |-
      The signature mirrors the POC's Matcher.embed_query and AD-1 still holds (both paths call
      the same preprocess/embed pair), but the load_image step is the caller's responsibility.
      Epic 3's scan endpoint is the caller that must not get this wrong; taking bytes instead
      would make the invariant unskippable.
    location: >-
      apps/api/api/catalogue.py find_candidates
    severity: low
  - summary: >-
      The endpoint-level AD-15 assertion hardcodes a macOS ColorSync profile path, so it never
      runs on Linux.
    evidence: |-
      test_a_cmyk_press_file_is_stored_and_embedded_in_srgb skips unless
      /System/Library/ColorSync/Profiles/Generic CMYK Profile.icc exists, while
      shared/vision/tests/test_colour_management.py solves the same problem with a candidate
      list that includes Linux paths. On Linux only the library-level test remains.
    location: >-
      apps/api/tests/test_add_tile.py
    severity: low
  - summary: >-
      A reference image whose short edge is under 64px produces twelve black-padded crop views
      rather than crops.
    evidence: |-
      `side = max(64, min(side, short))` in the ported view generator exceeds the frame on a
      tiny reference, so img.crop pads. Inherited verbatim from the POC, and no real catalogue
      image is that small, but nothing in the intake path refuses one either.
    location: >-
      shared/vision/shared_vision/views.py
    severity: low
  - summary: >-
      There is a per-file byte ceiling but no aggregate bound on a request, and every source
      and derivative is held in memory at once.
    evidence: |-
      MAX_IMAGE_BYTES is per file and MAX_IMAGES_PER_REQUEST is 8, so one accepted request is
      up to ~1GB of spooled body, and _Prepared retains every source and derivative byte string
      plus every decoded image for the duration of the add.
    location: >-
      apps/api/api/catalogue.py add_tile
    severity: medium
  - summary: >-
      `add_tile` holds a pooled Postgres connection for the whole embedding run, so a handful
      of concurrent adds can starve every other request in the product of a connection.
    evidence: |-
      `conn` is a `Depends(get_connection)` parameter, so the connection is checked out before
      the handler body and returned after it — across `_prepare`, which the module's own
      docstring calls "tens of seconds per image". `api/db.py` sets POOL_MAX_SIZE = 10 and
      POOL_TIMEOUT_SECONDS = 10.0 while FastAPI's threadpool admits more concurrent sync
      handlers than that, so ten simultaneous adds park the pool and `/auth/login` starts
      failing on a pool timeout. The connection is only needed for the cheap pre-flights and
      the final transaction. Distinct from the AD-16 entry above: that one is about CPU
      oversubscription, this one is about connection starvation in unrelated requests.
    location: >-
      apps/api/api/catalogue.py add_tile
    severity: medium
  - summary: >-
      A failed ICC transform silently falls back to the naive RGB conversion AD-15 exists to
      prevent, with nothing logged, recorded or surfaced.
    evidence: |-
      `_to_srgb` catches `(PyCMSError, OSError, ValueError)` and falls through to
      `img.convert("RGB")`. On the CMYK press files that are ~60% of the catalogue that is the
      ink inversion the POC measured at an 84-level channel shift — the tile is indexed and
      displayed with corrupt colour and the add still answers 201. The module has no logger,
      the `reference_image` row has no column for it, and
      `test_a_broken_profile_does_not_refuse_the_image` builds its fixture from an RGB image,
      so the dangerous combination (unreadable profile on a CMYK source) is untested. Inherited
      verbatim from `poc/tilematch/vision.py`, which the spec requires be copied unchanged, so
      this is a decision about the port rather than a defect in the porting.
    location: >-
      shared/vision/shared_vision/pipeline.py _to_srgb
    severity: medium
  - summary: >-
      EXIF orientation is silently not applied to any image carrying an ICC profile, because
      the colour transform runs first and returns an image with no EXIF.
    evidence: |-
      `load_image` calls `_to_srgb(img)` and then `ImageOps.exif_transpose(img)`. Verified
      empirically with Pillow in this workspace: `ImageCms.profileToProfile` returns a fresh
      image whose `info` holds only `icc_profile`, so `exif_transpose` is a no-op afterwards
      and a rotated phone photo or press file is indexed sideways. The I/O matrix row promises
      "Orientation applied, then all metadata dropped"; the metadata half holds, the
      orientation half holds only for profile-less images, and both orientation tests
      (`shared/vision/tests/test_pipeline.py`, `apps/api/tests/test_add_tile.py`) use fixtures
      with EXIF and no profile. Inherited verbatim from the POC, and the four clean rotations
      of AD-13 partly mask it at index time. Not patched here because the fix is a change to
      `shared/vision`, which CLAUDE.md binds to an eval run and a re-index, and because the
      spec's Always list requires the file be copied unchanged — that tension is a decision,
      not an edit.
    location: >-
      shared/vision/shared_vision/pipeline.py load_image
    severity: medium
  - summary: >-
      `config_hash()` does not cover the identity of the ONNX artifact, so two deployments
      running different weights carry an identical AD-14 stamp.
    evidence: |-
      The hash is over the preprocessing constants. `_verify_stamp` therefore passes while
      vectors from two different models are compared against each other — the silent accuracy
      failure the stamp exists to prevent. The only guard today is the pinned revision and
      sha256 in `scripts/fetch_model.py`, which a developer can bypass by placing a file at
      `ROCELL_MODEL_PATH` directly. Hashing the artifact once at session build would close it.
    location: >-
      shared/vision/shared_vision/pipeline.py config_hash
    severity: medium
  - summary: >-
      Nothing in the product can cut a new generation over, so the first `shared/vision` change
      refuses every add and every search with no documented recovery.
    evidence: |-
      `ensure_active_generation` only inserts when no active row exists; no code anywhere
      issues an `UPDATE ... SET is_active` or opens a second generation. `_verify_stamp` then
      answers `503 pipeline_stamp_mismatch` on both the write and the read path, and the only
      way out is hand-written SQL. AD-14's "cut over by a single pointer" has no operator
      surface and `infra/README.md` has no runbook for it. `make ingest` (Epic 2) is the
      natural home for the rebuild half.
    location: >-
      apps/api/api/catalogue.py ensure_active_generation
    severity: medium
  - summary: >-
      AD-15's rendering intent is only distinguishable by tests that skip on any checkout
      without the gitignored `poc/Tiles` reference tree.
    evidence: |-
      `test_the_rendering_intent_matches_colorsync` and its two siblings are gated on
      `poc/Tiles/45X90/POLISH/Copy of RP.RSS.0062ST.PL.0T.jpg`, which `.gitignore` excludes.
      The portable half of the file states in its own comment that a generic CMYK profile
      carries identical tables for the two intents and would pass either way, and the
      remaining assertion reads the constant and the source text rather than the transform. So
      deleting `renderingIntent=RENDERING_INTENT` from `_to_srgb` is green on a fresh clone
      while every CMYK reference indexes near-black. A committed synthetic profile whose
      perceptual and relative-colorimetric tables differ would make the Block-If condition
      checkable anywhere.
    location: >-
      shared/vision/tests/test_colour_management.py
    severity: medium
  - summary: >-
      A present-but-unloadable `model.onnx` surfaces as an opaque 500, while only an absent one
      gets the named 503 that says how to fix it.
    evidence: |-
      `_prepare` catches `FileNotFoundError`. ONNX Runtime's own failures for a truncated or
      incompatible export (`Fail`, `InvalidProtobuf`, `NoSuchFile`) derive from `Exception`
      directly, so they pass straight through after the request has already spent its CPU.
      Naming them needs either an exception contract in `shared/vision` — which the spec
      requires be a verbatim copy — or an `onnxruntime` import in `apps/api`, which is a new
      declared dependency. Both are decisions rather than edits.
    location: >-
      apps/api/api/catalogue.py _prepare
    severity: low
  - summary: >-
      An unset `OBJECT_STORAGE_ROOT` fails during dependency resolution, so it reaches the
      caller as an unhandled 500 rather than as a named refusal.
    evidence: |-
      `get_object_store()` raises `ObjectStorageNotConfigured(RuntimeError)`, which no handler
      converts. `api.db` validates `DATABASE_URL` at startup and this could do the same; the
      Makefile's advisory `echo` and its comment ("a missing value is a 500 on the first
      `POST /admin/tiles`") acknowledge the gap instead of closing it. `test_object_storage.py`
      asserts the exception, never what a caller sees.
    location: >-
      apps/api/api/storage.py get_object_store
    severity: low
  - summary: >-
      A client timeout after the server has already committed leaves the Administrator with no
      remedy but a `code_already_exists` on retry.
    evidence: |-
      `client.ts` documents the failure precisely and answers it by widening the bound to
      `UPLOAD_TIMEOUT_MS`. An aborted browser request still runs to completion on the server,
      and there is no idempotency key, no server-side deadline matching the client's, and no
      way for the screen to tell "timed out, tile exists" from "timed out, nothing written".
      An idempotency key on the add is the shape of the fix and is a contract decision.
    location: >-
      apps/web/src/api/client.ts
    severity: low
  - summary: >-
      The only route serving a reference image is Administrator-only, but Epic 3 must show one
      beside every Candidate to a Staff caller.
    evidence: |-
      `GET /admin/tiles/{tile_id}/images/{image_id}` sits under `require_administrator` and
      `test_a_staff_caller_is_refused_the_image_read` pins that. CLAUDE.md's product rules
      require the reference image beside each candidate for the staff who scan. Epic 3 will
      either add a second image route — the asymmetry this module's docstring warns about — or
      move this one out from under `/admin/`, which
      `test_every_route_declaring_the_role_check_is_under_admin` will then contest. Worth
      deciding before Epic 3 writes the scan endpoint rather than after.
    location: >-
      apps/api/api/catalogue.py read_tile_image
    severity: low
  - summary: >-
      `session-expiry.test.tsx` failed once under a full `make test` run and passed on every
      run since, including in isolation.
    evidence: |-
      One `make test` invocation during this review pass failed at
      `src/__tests__/session-expiry.test.tsx:321` waiting for the signed-out notice; the file
      is untouched by Story 2.1 and the same suite passed on the next two full runs and on a
      targeted run. A test that fails under load and passes alone is a real defect in the test,
      not noise, and is worth pinning before it is dismissed as a fluke.
    location: >-
      apps/web/src/__tests__/session-expiry.test.tsx:321
    severity: low
  - summary: >-
      `config_hash()` covers the preprocessing constants but not the augmentation constants,
      so changing how views are generated produces a different index under an identical AD-14
      stamp.
    evidence: |-
      The hash is built from `RESIZE_SHORTEST_EDGE`, `CROP_SIZE`, the normalization constants
      and `PIPELINE_VERSION`. Every stored vector also depends on `views.py` —
      `VIEWS_PER_IMAGE`, `CANONICAL_VIEWS`, `CROP_SCALE_MIN/MAX` and the five augmentation
      ranges — and none of those reach the stamp. Edit a crop range and `_verify_stamp` passes
      while the generation holds vectors from two different view recipes, which is precisely
      the silent mixing AD-14 exists to prevent. Distinct from the ONNX-artifact gap already
      recorded: that one is about the weights, this one is about the views. Not fixed here
      because widening the hash changes every stamp, which CLAUDE.md binds to an eval run and
      a full re-index.
    location: >-
      shared/vision/shared_vision/pipeline.py config_hash
    severity: medium
  - summary: >-
      `_get_session` publishes the ONNX session before the input and output names, so a second
      thread can take the fast path and embed with an empty feed name.
    evidence: |-
      `_build_session` assigns `_session` first and `_input_name`/`_output_name` after. The
      fast path in `_get_session` reads `_session` without the lock, by design, so a thread
      arriving in that window returns a usable session while `embed` reads `_output_name` as
      `""` and ONNX Runtime raises `Invalid Feed Input Name`. It needs two concurrent
      first-embeds in one process, so it is rare and non-deterministic — an intermittent 500
      on the first concurrent add after a restart. Carried verbatim from
      `poc/tilematch/vision.py`, which the spec's Always list requires be copied unchanged, so
      the fix is a decision about the port rather than an edit to it.
    location: >-
      shared/vision/shared_vision/pipeline.py _get_session
    severity: low
  - summary: >-
      An accepted image with an extreme aspect ratio expands rather than shrinks in
      `preprocess`, so a few-KB upload can cost hundreds of megabytes per view.
    evidence: |-
      `DECODE_MAX_EDGE` caps the long edge at 2048 but nothing bounds the ratio. A 2048x8
      image passes every gate — small file, few pixels — and `preprocess` resizes the
      *shortest* edge to 256, scaling it back up to 65536x256, about 17 megapixels of float32
      per view and sixteen views per image. The pixel gate reads header dimensions, which for
      this shape are honest and small. Inherited from the POC's `preprocess`, where the inputs
      were a curated catalogue rather than an upload.
    location: >-
      shared/vision/shared_vision/pipeline.py preprocess
    severity: low
  - summary: >-
      The Code, Size and Category hints are bound to no input, and no control sets `aria-busy`
      while a minute-long save is in flight.
    evidence: |-
      The Reference images hint is now bound through `aria-describedby` because it carries the
      count and byte limits, which are stated nowhere else. The other three `.hint`
      paragraphs — including the one explaining that a blank Category files the tile under
      `UNKNOWN` — are still visual-only. Separately, `disabled={submitting}` removes the just
      pressed Save from the tab order for the length of the request; `aria-busy` on the form
      would say why. Both are DESIGN.md/EXPERIENCE.md questions about the screen's pattern
      rather than defects in this endpoint, and the same pattern is about to be copied by
      Stories 2.2 and 2.4.
    location: >-
      apps/web/src/screens/AddTileScreen.tsx
    severity: low
---

<intent-contract>

## Intent

**Problem:** The Catalogue does not exist. There is no Tile table, no pgvector index, no object storage, and `shared/vision` is a skeleton whose two entry points raise `NotImplementedError` — so an Administrator cannot add a Tile, and nothing in the product can turn pixels into a searchable vector.

**Approach:** Port `poc/tilematch/vision.py` into `shared/vision` unchanged (AD-1 symmetry, AD-15 colour management), add the catalogue schema with a pgvector HNSW index, and ship one admin-only `POST /admin/tiles` endpoint that takes a Code, a Size and one or more reference images, runs every byte through the single shared intake path, writes 16 embeddings per image into the active generation, and is immediately findable by a vector query with no re-index step.

## Boundaries & Constraints

**Always:**
- `shared/vision` is **copied** from `poc/tilematch/vision.py`, not paraphrased. Constants, ICC handling, the `Image.frombytes` metadata strip, the ONNX session lock and the `atexit` release all carry across verbatim. The one permitted change is making the model path configurable.
- Colour management runs **first**: embedded ICC → sRGB at **relative colorimetric** intent, no black point compensation, missing profile assumed sRGB (AD-15).
- One intake path (AD-7) for every image byte: sniff content (never the extension or the client's `content-type`), reject unreadable/zero-byte, EXIF-strip, re-encode. `apps/api` writes nothing to storage that has not passed through it.
- 16 embeddings per Reference Image — 4 clean rotations + 12 randomized augmented crops — as separate `reference_embedding` rows, never pooled at write time (AD-13). Unit-norm `vector(1536)`, HNSW, inner-product ops class (AD-5).
- Every embedding row belongs to a generation row carrying the pipeline version + config hash; exactly one generation is active (AD-14).
- A capped display derivative (≤1280px long edge, ≤300KB) is generated once at write time; the original is never served (AD-17).
- No presigned or direct-to-storage URL in either direction — bytes are proxied through an authenticated endpoint (AD-9).
- `require_administrator` on every new route; the add and its audit entry share one `with conn.transaction():`.
- Domain vocabulary only: `Tile`, `Code`, `Size`, `Category`, `ReferenceImage`. `Product`, `Face` and `Design` must not appear as type, table, column, field or UI names.
- Every new table gets an explicit `GRANT SELECT, INSERT, UPDATE, DELETE ... TO rocell_app` in its own migration.
- New dependencies are flagged in the PR notes section of this spec before use (AGENTS.md).

**Block If:**
- Porting `shared/vision` cannot reproduce the POC's measured colour-management behaviour (CMYK reference mean brightness 78–90, green not more than 8 above red) — that is an accuracy regression, not a detail.
- `CREATE EXTENSION vector` fails in the test cluster after the documented install step, i.e. pgvector < 0.8.2 or absent and not installable.

**Never:**
- Do not build a `Size + Category → Code` map, do not deduplicate or group Tiles by `Size + Category`, and do not add a uniqueness constraint that makes two Codes in one category collide.
- Do not implement edit (2.2), remove (2.3), bulk upload (2.4), catalogue search/list UI (2.5), the scan endpoint or the crop step (Epic 3), `make ingest`, or `make eval`.
- Do not add a crop step to the admin upload path (AD-11, resolved: no).
- Do not add a vector database, an ORM, a second HTTP client, a form library, or a router to `apps/web`.
- Do not surface a similarity score, bar or derived word anywhere in the UI (AD-20).
- Do not enable the OpenAPI/docs routes, add CORS, or introduce middleware.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Add a Tile | Admin session; `code=RP.CMA.0001DJ.SM.0T`, `size=45X90`, `category=CREMA MARMOL`, one JPEG | `201` with the Tile (id, code, size, category, face_number, reference_images); 1 `reference_image` row, 16 `reference_embedding` rows in the active generation; one `catalogue_tile_added` audit entry | No error expected |
| Category omitted | Same, `category` absent or blank | `201`; Tile resolves to the `UNKNOWN` category sentinel, never dropped (AD-18) | No error expected |
| CMYK press file | Reference image with an embedded CMYK ICC profile | Stored derivative and embedded pixels are sRGB via relative colorimetric intent; hue and brightness match the POC's measured reference | No error expected |
| Immediately findable | A Tile added in this session, then a vector query with a perturbed copy of its own reference image | The new Tile is among the top-3 candidates with no re-index step run | No error expected |
| Size/Category casing drift | `size=" 45x90 "`, `category="Crema  Marmol"` | Resolved against the same normalized (trim, collapse whitespace, upper) create-if-missing lookup — one row, not a near-duplicate | No error expected |
| Duplicate Code | A Tile with that Code already exists | `409` `code_already_exists`; nothing written, no audit entry | Transaction rolled back |
| Blank or overlong Code | `code=""` or > 200 chars | `422` `invalid_code` | Refusal names the field |
| Missing Size | `size` absent or blank | `422` `invalid_size` | Refusal names the field |
| No image | No `images` part | `422` `invalid_image` | Refusal names the field |
| Zero-byte / corrupt / non-image bytes | A `.jpg` whose bytes are text, or 0 bytes | `422` `unreadable_image`; nothing stored, no partial Tile | Transaction rolled back; storage objects written before the failure are removed |
| Extension lies about content | A PNG named `.jpg`, or an `.exe` renamed `.jpg` | Decided by content only: the PNG is accepted, the non-image is `422` `unreadable_image` | Never trust the extension or the client `content-type` |
| Oversized image | File > 128MB, or decoded pixels > 400,000,000 | `413` `image_too_large`, refused before a full decode | Header-only pixel gate before decode |
| Too many images | More than 8 files in one request | `422` `too_many_images` | Refusal names the limit |
| EXIF-bearing upload | JPEG with GPS/orientation EXIF | Orientation applied, then all metadata dropped — stored bytes carry no EXIF | No error expected |
| Staff caller | Valid non-admin session | `403` `administrator_required`, no row written, no storage write | Existing dependency |
| Signed-out caller | No session cookie | `401` `unauthorized` | Existing dependency |
| Fetch a derivative | `GET /admin/tiles/{tile_id}/images/{image_id}` as admin | `200` `image/jpeg`, the capped derivative bytes, `Cache-Control: no-store` | `404` `image_not_found` for an unknown or mismatched pair |
| Model artifact absent | `shared/vision` model file not present | Add fails with `503` `matching_unavailable`; message names the setup step, never a partial Tile | Tests that need the model skip rather than fail |

</intent-contract>

## Code Map

**Port source (read, copy, do not paraphrase)**
- `poc/tilematch/vision.py` -- the whole invariant. Constants (`RESIZE_SHORTEST_EDGE=256`, `CROP_SIZE=224`, `DECODE_MAX_EDGE=2048`, `REFERENCE_MAX_PIXELS=400_000_000`, `UPLOAD_MAX_PIXELS=60_000_000`, `EMBED_DIM=1536`, `PIPELINE_VERSION="dinov2b-224-cls+meanpatch-icc-v3"`), `config_hash()`, `load_image()`, `preprocess()`, `embed()`, `embed_images()`, `_to_srgb()`, the locked lazy ONNX session and the `atexit` release. Note `img.draft(None, (2048,2048))` — passing `"RGB"` silently discards the ICC profile.
- `poc/tilematch/augment.py` -- `generate_views(img, key, n=16)`, `_seed_for()`, `VIEWS_PER_IMAGE=16`, `CANONICAL_VIEWS=4`, `CROP_SCALE_MIN/MAX`, the five augmentations. Port these; **do not** port `synthesize_query` (eval-only).
- `poc/tilematch/index.py` -- `_save_reference()` is the AD-17 derivative recipe: 1280px long edge, JPEG quality stepped down by 6 from 82 until ≤300KB or quality < 68. `FEATURELESS_STD = 3.0` is the quality flag.
- `poc/tilematch/search.py` -- `Matcher.score_images` lines are the max-over-views semantics to reproduce in SQL. `TOP_K=3`, `QUERY_ZOOMS=(1.0,)`.
- `poc/tests/test_vision.py` -- the invariants the ported tests must keep, including the AD-1 symmetry assertion and `TestColourManagement`'s numeric bounds.
- `poc/models/model.onnx` -- the 346MB `Xenova/dinov2-base` ONNX export, present locally, gitignored, obtained by `poc/Makefile`'s `model` target.

**Target — vision**
- `shared/vision/shared_vision/__init__.py` -- today a charter + two stubs that raise. Keep the docstring (its test asserts it contains `AD-1`, `identical`, and `PORT_SOURCE`); re-export the real surface; bump `PIPELINE_VERSION` to the ported value.
- `shared/vision/pyproject.toml` -- `dependencies = []` today; add pillow/numpy/onnxruntime.
- `shared/vision/tests/test_skeleton.py` -- asserts both entry points raise `NotImplementedError`. Must be replaced, not deleted: the docstring and `PORT_SOURCE` assertions still hold.

**Target — data**
- `infra/migrations/20260921T1000_create_audit_log.up.sql` -- the structural template: rationale header, `IF NOT EXISTS`, role `DO $$` block, explicit per-table grants, no `ALTER DEFAULT PRIVILEGES`.
- `infra/rocell_infra/migrate.py:56` `VERSION_PATTERN`, `:148` `discover_migrations` -- naming rule `^\d{8}T\d{4}_[a-z0-9]+(_[a-z0-9]+)*$`, every `.up.sql` needs a `.down.sql`.
- `apps/api/tests/test_audit_immutability.py:213` -- fails the build if any new table lacks full DML for `rocell_app`.
- `infra/README.md:20` -- pgvector ≥ 0.8.2 floor. 0.8.6 is now built and installed against the local postgresql@16.

**Target — API**
- `apps/api/api/main.py:27,170-181` -- import + `include_router` is the only registration step; `STATUS_CODES` at `:33` already maps 413/415/409/429.
- `apps/api/api/db.py` -- psycopg 3 sync, `dict_row`, autocommit pool, `get_connection` dependency, `with conn.transaction():` for multi-statement writes. Handlers are `def`, not `async def`.
- `apps/api/api/dependencies.py:193` `require_administrator` -- the authz dependency and the audit actor in one.
- `apps/api/api/audit.py:230` `record(...)`, `:149` `source_ip` dependency, `:107` re-exported `AuditAction`. `audit.py` must stay the only file containing the string `audit_log`.
- `apps/api/api/users.py:560-598` -- the exact create + audit-in-one-transaction call shape to copy; `:470,:485` the error-factory idiom.
- `apps/api/tests/conftest.py` -- `client`, `conn`, `app_role_conn`, `make_user`, `audit_rows`; real Postgres, skips when `initdb` is absent.
- `apps/api/tests/test_admin_authorization.py:56-84` -- new `/admin/` paths must be added to its constants (it checks both directions).
- `apps/api/pyproject.toml` -- needs `shared-vision` in `dependencies` **and** `[tool.uv.sources]`, plus `python-multipart` (absent; `UploadFile` does not work without it).

**Target — shared schema**
- `shared/schema/shared_schema/audit.py:87` `AuditAction` + `ts/audit.ts` (`AuditAction` union **and** `AUDIT_ACTIONS` array) + `shared/schema/tests/test_audit.py:130` (hardcoded 13-value set, and its name says "thirteen") -- all four change together or tests fail.
- `shared/schema/shared_schema/user.py` + `ts/user.ts` -- the twin-contract template for the new `Tile` pair; wire format is snake_case.
- `apps/web/src/__tests__/error-code-parity.test.ts:106-153` -- every error code exported from `client.ts` must appear in its `PYTHON` map; `BOUNDS` at `:261` mirrors request bounds.

**Target — web**
- `apps/web/src/App.tsx:35,48,70,105-107,361-376,487-502` -- the six mechanical edits to add a screen: `Section`, `Screen`, `reachableBy`, `currentScreen`, the render branch, the home-panel door.
- `apps/web/src/api/client.ts:293-315` -- `apiRequest` hardcodes `content-type: application/json` and `JSON.stringify`; must learn `FormData` (pass through, omit the header).
- `apps/web/src/screens/CreateUserScreen.tsx` -- the form template: `useId`, `Field` union, `fieldFor`, `submitting` guard, single `role="alert"` node, one accent action.
- `apps/web/src/screens/AccountSettingsScreen.tsx:58-60,194-196,307-312` -- the `Saving…` → `Saved.` indicator, muted at rest and `--color-primary` when saved. Reuse it.
- `apps/web/src/__tests__/styling-wiring.test.ts:154-188` -- every `.module.css` class must be referenced and every `styles.x` declared, both directions; each screen has its own `describe`.
- `apps/web/src/__tests__/no-raw-values.test.ts` -- no dimension literal anywhere outside `tokens.css`; a thumbnail size must become a token.
- `apps/web/src/screens/AuditLogScreen.tsx` -- the action label map needs the new audit action.

**Read-only evidence**
- Object storage: nothing exists anywhere in the repo — no SDK, no config, no env var. `infra/README.md:441` says the S3-compatible API is fixed but the provider is not, and to pin it before infra work starts.
- `apps/web` has zero file-upload or image-display code today.
- No `CREATE EXTENSION` exists in any migration; `gen_random_uuid()` is built in on PG13+.

## Tasks & Acceptance

**Execution:**
- `shared/vision/shared_vision/pipeline.py` -- new; copy `poc/tilematch/vision.py` verbatim, changing only the model location: `MODEL_PATH` defaults to `shared_vision/models/model.onnx` and is overridable with `ROCELL_MODEL_PATH`. Keep every constant, the ICC path, the session lock and the `atexit` release -- AD-1 forbids a reimplementation.
- `shared/vision/shared_vision/views.py` -- new; port `generate_views`, `_seed_for` and the five augmentations from `poc/tilematch/augment.py`. Omit `synthesize_query` -- it is eval-only and must not reach production.
- `shared/vision/shared_vision/intake.py` -- new; AD-7's single intake (`intake_image(data: bytes, *, max_pixels) -> IntakeResult`) doing content sniff, pixel gate, EXIF strip, re-encode, sha256, plus AD-17's `display_derivative(img) -> bytes` (≤1280px long edge, ≤300KB) and the featureless-quality flag. Every writer calls this and nothing else.
- `shared/vision/shared_vision/__init__.py` -- re-export the public surface, set `PIPELINE_VERSION` to the ported value, keep the charter docstring -- its own test reads it.
- `shared/vision/pyproject.toml` -- add `pillow>=11.0`, `numpy>=2.0`, `onnxruntime>=1.23` -- the port cannot run without them.
- `scripts/fetch_model.py` + `Makefile` `model` target -- new; download `Xenova/dinov2-base` `onnx/model.onnx` at a **pinned revision** with a sha256 check, using stdlib `urllib` -- no new dependency for a once-per-machine fetch.
- `.gitignore` -- ignore `shared/vision/shared_vision/models/` -- a 346MB artifact never enters git.
- `shared/vision/tests/test_pipeline.py` -- replace `test_skeleton.py`'s two "raises" assertions with the POC's contract: shape/dtype, unit norm, bit-exact determinism, resolution independence, EXIF stripped, zero-byte rejected, `config_hash` sensitivity, and the AD-1 symmetry assertion. Skip the module when the model file is absent.
- `shared/vision/tests/test_colour_management.py` -- new; AD-15's numeric bounds on a CMYK fixture (green not more than 8 above red; mean brightness 78–90) and sRGB round-trip identity -- hue *and* brightness, as AD-15 requires.
- `shared/vision/tests/test_views.py` -- new; 16 views, first 4 are the clean rotations, same key gives the same views -- AD-13's shape, pinned.
- `infra/migrations/20260921T1500_create_catalogue.up.sql` / `.down.sql` -- new; `CREATE EXTENSION IF NOT EXISTS vector`, then `tile_size`, `tile_category` (both normalized-name unique, with the `UNKNOWN` category sentinel), `tile` (unique `code`, nullable `category_id`, nullable `face_number`), `reference_image` (`tile_id` FK cascade, original + derivative keys, sha256, dims, bytes, quality flag), `embedding_generation` (pipeline version, config hash, partial unique index on the one active row), `reference_embedding` (`vector(1536)`, `view_kind`, `view_index`, generation FK, HNSW index with `vector_ip_ops`), and an explicit grant for every one of them.
- `apps/api/api/storage.py` -- new; an `ObjectStore` protocol (`put`, `get`, `delete`) plus a filesystem-backed implementation configured by `OBJECT_STORAGE_ROOT`, raising a named error rather than defaulting -- the S3 provider is unpinned, so the seam ships and the driver follows.
- `apps/api/api/catalogue.py` -- new; `POST /admin/tiles` (multipart: `code`, `size`, optional `category`, 1–8 `images`), `GET /admin/tiles/{tile_id}/images/{image_id}` (derivative bytes only), the normalized create-if-missing Size/Category resolvers, the active-generation resolver, and `find_candidates(conn, image, limit=3)` -- the max-over-views query Epic 3's scan endpoint will call, here so "searchable immediately" is observable now.
- `apps/api/api/main.py` -- import and `include_router(catalogue.router)` -- the only registration step.
- `apps/api/pyproject.toml` -- add `shared-vision` (dependency + workspace source) and `python-multipart>=0.0.20` -- `UploadFile` is inert without it.
- `shared/schema/shared_schema/tile.py` + `ts/tile.ts` -- new twin contract for `Tile`, `ReferenceImage` and the wire shapes; snake_case on the wire, `Product`/`Face` nowhere.
- `shared/schema/shared_schema/audit.py` + `ts/audit.ts` + `shared/schema/tests/test_audit.py` -- add `catalogue_tile_added`; update the union, the `AUDIT_ACTIONS` array, and the hardcoded vocabulary test (including its name) -- four places or the suite fails.
- `apps/api/tests/test_add_tile.py` -- new; every row of the I/O matrix through the real endpoint, including the extension-lies and EXIF cases, plus that a failed add leaves no orphan row or stored object.
- `apps/api/tests/test_catalogue_authorization.py` -- new; staff `403` and signed-out `401` on both new routes, and the new paths registered in `test_admin_authorization.py`'s constants.
- `apps/api/tests/test_tile_searchable.py` -- new; add a Tile, then `find_candidates` with a perturbed copy of its reference image returns it in the top 3, with no re-index step -- this is FR-19's acceptance, folded in.
- `apps/api/tests/test_catalogue_audit.py` -- new; a successful add writes exactly one `catalogue_tile_added` entry with actor, source IP and the Code in `details`; a refused add writes none.
- `apps/web/src/api/client.ts` -- teach `apiRequest` to pass a `FormData` body through unstringified with no `content-type` header, and export the new error codes -- the browser must set the multipart boundary.
- `apps/web/src/screens/AddTileScreen.tsx` + `.module.css` -- new; Code, Size, optional Category, a file input for one or more reference images, one accent `Save` action, navy outline `Back`, the shared `Saving…`/`Saved.` indicator, a single `role="alert"` refusal node bound to the field at fault. Copy `CreateUserScreen`'s structure.
- `apps/web/src/App.tsx` + `App.module.css` -- add the `add-tile` section/screen, the admin reachability entry, the render branch and the home-panel door -- six mechanical edits, one place each.
- `apps/web/src/screens/AuditLogScreen.tsx` -- add the label for the new action -- the viewer must not render a raw enum value.
- `apps/web/src/styles/tokens.css` -- add any derived token the new screen needs (e.g. a thumbnail size) -- `no-raw-values` forbids a dimension literal anywhere else.
- `apps/web/src/__tests__/add-tile.test.tsx` -- new; submit shape (a `FormData` with exactly the named parts), blank-field refusals, the saved indicator, and the door's role-conditionality -- following `create-user.test.tsx`'s local `stubFetch`.
- `apps/web/src/__tests__/styling-wiring.test.ts` + `error-code-parity.test.ts` -- add the Add Tile `describe` (one accent control, destructive-coloured errors, primary-coloured saved indicator) and the new codes/bounds -- both tests fail otherwise.
- `README.md` / `infra/README.md` -- record the pgvector ≥ 0.8.2 install step, `make model`, `OBJECT_STORAGE_ROOT`, and that a `shared/vision` change invalidates the index and requires a re-index -- AD-1's standing obligation.

**Acceptance Criteria:**
- Given an authenticated Administrator, when they submit a Code, a Size and one or more reference images, then a Tile is created, every image passes content validation, re-encoding, EXIF-stripping and ICC→sRGB relative-colorimetric colour management before storage, and neither the extension nor the client-declared content type is trusted at any point.
- Given a Reference Image is accepted, when the add completes, then 16 embedding rows exist for it — 4 clean rotations and 12 augmented crops — each unit-norm `vector(1536)` in the single active generation, and a capped display derivative (≤1280px long edge, ≤300KB) has been generated and stored; the original is never served to `apps/web`.
- Given a Tile added in the current session, when a vector query runs against the catalogue, then that Tile is returned among the candidates with no manual re-index step having been run, and candidates are scored as the max across a Tile's views, never averaged, never collapsed by Size or Category.
- Given `shared/vision` is the only module that turns pixels into a vector, when both the write path and the query path embed an image, then they call the same function and produce bit-identical vectors, proven by a test that fails if either side forks.
- Given any non-Administrator or signed-out caller, when they call either catalogue route, then the server refuses with `403` or `401` regardless of what the UI renders, and nothing is written to the database or object storage.
- Given a successful add, when the transaction commits, then exactly one `catalogue_tile_added` audit entry records actor, timestamp, source IP and the Code, written in the same transaction as the Tile; given a refused add, then no audit entry and no orphaned row or stored object remain.
- Given the Add Tile screen, when an Administrator saves, then the inline indicator cycles `Saving…` → `Saved.` near the action that triggered it, with exactly one accent control on the screen, no similarity value anywhere, and every interactive element keyboard-reachable with a visible focus state.
- Given `make lint` and `make test`, when run from a clean tree, then both pass, with the vision tests exercised (not skipped) when the model artifact is present.

## Spec Change Log

## Review Triage Log

### 2026-09-21 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 16: (high 1, medium 7, low 8)
- defer: 9: (high 0, medium 5, low 4)
- reject: 6
- addressed_findings:
  - `[high]` `[patch]` The web client's 15s request timeout aborted a legitimate add while the server was still committing — a one-image add is ~16 forward passes. Added an optional `timeoutMs` to the request options and an `UPLOAD_TIMEOUT_MS` the Add Tile submit passes, with tests observing the timer the upload schedules.
  - `[medium]` `[patch]` The stamp-mismatch test lacked `@needs_model` and would fail, not skip, on a machine without the ONNX artifact, because `_prepare` runs before the generation check. Marker added.
  - `[medium]` `[patch]` `find_candidates` created and activated a generation row on an empty catalogue — a search that writes. Split into a read-only `active_generation` plus an `ensure_active_generation` only the add path calls; a search of an empty catalogue now writes nothing and is tested.
  - `[medium]` `[patch]` Sixteen forward passes and two object writes ran before the stamp and duplicate-Code refusals. Both cheap checks moved ahead of `_prepare`, with the `UniqueViolation` catch kept as the decider and a test proving a concurrent duplicate is still refused there.
  - `[medium]` `[patch]` `read_tile` and its two statements shipped with no caller and no test. Removed.
  - `[medium]` `[patch]` `test_the_refusal_precedes_the_body_entirely` claimed a Staff caller's image is never decoded while posting an empty body. Rewritten to post a real image part and fail if intake is reached.
  - `[medium]` `[patch]` `featureless`/`pixel_std` were computed, stored and rendered but never observed by a test — inverting the comparison kept the suite green. Added assertions over real pixels at the source and end to end.
  - `[medium]` `[patch]` A unique index on (pipeline_version, config_hash) made a same-pipeline re-index impossible, which AD-14 never asks for. Dropped; the partial unique on the active row remains, with tests pinning both directions.
  - `[low]` `[patch]` The screen sent oversized and over-count selections before the server could refuse them. Both bounds now refuse client-side and are mirrored with parity rows.
  - `[low]` `[patch]` The derivative's quality step-down returned q64 though the constant and docstring promise a q68 floor. Clamped, with a test that fails on the old behaviour.
  - `[low]` `[patch]` `_discard` caught only `OSError`, so any other failure during cleanup replaced the caller's real error. Widened, still per key, still logged.
  - `[low]` `[patch]` `scripts/fetch_model.py` had no network timeout and hashed a `FROM=` path before checking it exists. Both fixed.
  - `[low]` `[patch]` Nothing tested that object storage refuses an unset or blank `OBJECT_STORAGE_ROOT`. Added the failure-case tests plus the driver's key-traversal refusals.
  - `[low]` `[patch]` The row-present/object-absent branch of the image read had no test. Added.
  - `[low]` `[patch]` The one route returning non-JSON bytes sent no `X-Content-Type-Options`. Added `nosniff` and asserted it.
  - `[low]` `[patch]` `make dev`'s help still named only `DATABASE_URL`. Both variables listed, with a warning when object storage is unconfigured.

### 2026-09-21 — Review pass (follow-up)

- intent_gap: 0
- bad_spec: 0
- patch: 11: (high 0, medium 5, low 6)
- defer: 11: (high 0, medium 6, low 5)
- reject: 12
- addressed_findings:
  - `[medium]` `[patch]` `make model FROM=<the installed path>` unlinked the target before
    linking the source onto it, destroying the only copy of the 346MB artifact and then failing
    on both the link and the copy. Identity guard added, with a test that fails on the old
    behaviour.
  - `[medium]` `[patch]` `isTile` and `isReferenceImage` — the only structural guard on the add
    response, and the thing that turns a leaked `score` (AD-20) or storage key (AD-9) into a
    loud failure — were never executed by a test: every body they saw was well-formed. Added
    `apps/web/src/__tests__/tile-contract.test.ts` alongside the User and Audit contract tests,
    covering extra keys, missing keys, malformed ids, naive timestamps and bad members.
  - `[medium]` `[patch]` `scripts/fetch_model.py` had no tests at all, so the pinned-revision
    and sha256 gate — the only thing stopping an arbitrary set of weights from being adopted
    under an identical AD-14 stamp — was an unexercised branch. Added `tests/test_fetch_model.py`
    covering the digest refusal, the adoption path, the missing source and the pin itself.
  - `[medium]` `[patch]` The `UniqueViolation` recovery in `ensure_active_generation` — the
    savepoint that lets the loser of two concurrent first-adds join the winner's generation —
    had no test; two sequential adds take the early return above it. Added a test that drives a
    committed second writer into exactly that window, verified by mutation: removing the
    recovery branch now fails it.
  - `[medium]` `[patch]` The envelope-code parity guard only checked one direction (every code
    the client exports has a Python twin), so a code added on the API side with no client twin
    was unchecked. Added the other direction, which immediately found three: `pipeline_stamp_mismatch`,
    `image_not_found` and the pre-existing `administrator_required`. All three now have a named
    export and a parity row.
  - `[low]` `[patch]` `FilesystemObjectStore.put` left a `.partial` staging file behind when a
    write failed, under a name `valid_key` refuses — so neither `delete` nor the add path's
    compensating `_discard` could ever remove it. Cleaned up on failure.
  - `[low]` `[patch]` Nothing asserted `Cache-Control: no-store` on the add's `201`, though every
    sibling write asserts it on its own success response and the body carries catalogue data.
    Assertion added.
  - `[low]` `[patch]` The Add tile screen carried two competing `role="status"` live regions, so a
    successful save announced twice and the test read `getAllByRole('status')[0]` — an
    order-dependent assertion that would pass if the two swapped. The result panel is now a
    heading-labelled region, and the test asserts one live region and one region by name.
  - `[low]` `[patch]` `find_candidates` let a missing model artifact escape as a raw
    `FileNotFoundError` where the add path answers with the named `503` that says how to fix it.
    Epic 3's scan endpoint would have inherited the unexplained 500.
  - `[low]` `[patch]` `test_the_admin_route_table_is_the_seven_routes_the_product_serves` asserted
    nine routes, and its comment still said a seventh joins them. Renamed and rewritten; this
    repo treats counts-in-names as load-bearing, as the same change's rename of the audit
    vocabulary test to "fourteen" shows.
  - `[low]` `[patch]` The per-image embedding insert created a cursor it never closed, alone among
    this module's statements. Now a context manager.

**Why the two spec-level tensions were deferred rather than escalated.** Two findings have their
root cause inside `<intent-contract>` rather than in the code: the ICC transform's silent fallback
to a naive RGB conversion, and EXIF orientation being dropped for any image carrying a profile
(verified empirically — `profileToProfile` returns an image with no EXIF, so the `exif_transpose`
that follows it is a no-op). Both are inherited verbatim from `poc/tilematch/vision.py`, which the
Always list requires be copied unchanged, and both would need a `shared/vision` edit that CLAUDE.md
binds to an eval run and a full re-index. Reverting a story that is complete and green over an
ordering detail the AD-13 rotations partly mask would cost more than it buys, so they are recorded
in the ledger with the evidence and the decision left where it belongs.

### 2026-09-21 — Review pass (second follow-up)

- intent_gap: 0
- bad_spec: 0
- patch: 10: (high 0, medium 3, low 7)
- defer: 4: (high 0, medium 1, low 3)
- reject: 25
- addressed_findings:
  - `[medium]` `[patch]` Every file was read, decoded **and embedded** one at a time, so a
    request whose second image was oversized or corrupt paid sixteen forward passes on the
    first one before the refusal. `_prepare` split into `_accept` (read + AD-7 intake) and
    `_prepare` (derivative + embeddings); `add_tile` now runs the cheap half over every upload
    before the expensive half runs over any. The existing multi-image test was rewritten to
    fail if the embedder is reached at all, and mutation-checked against the old ordering.
  - `[medium]` `[patch]` AD-5's HNSW index was created by the migration and asserted by
    nothing — `find_candidates` is a grouped scan that returns identical rows with no index,
    and mis-ranked ones under `vector_l2_ops`. Added the `pg_index` assertion `infra/tests`
    already uses for the sessions and audit indexes, naming the access method and the operator
    class.
  - `[medium]` `[patch]` The read-only stamp pre-flight — the thing that makes a
    stamp-mismatched deployment refuse in milliseconds instead of after a minute of embedding
    — had no test: deleting it left `ensure_active_generation` raising the same `503` inside
    the transaction and the existing test green. Added the sibling of the duplicate-Code
    ordering test, mutation-checked.
  - `[low]` `[patch]` `test_a_partial_write_is_never_visible_under_its_key` only exercised a
    *successful* `put`, so the staging-file cleanup added last pass was unpinned — replacing
    the whole staged write with `write_bytes` left the file green. Added the failure case: the
    key still reads the old bytes and no `.partial` litter remains.
  - `[low]` `[patch]` `_discard`'s two deliberate properties — never raise, and continue past
    a bad key — were unreachable from any test, because the only driver's `delete` cannot
    fail. Asserted directly against a store that raises a non-`OSError`, which is what the S3
    driver this module is a seam for will do.
  - `[low]` `[patch]` `_SELECT_CANDIDATES` ordered by distance alone, so two Tiles at an equal
    distance came back in whatever order the scan produced and "the top 3" was not reproducible
    between runs. Added `t.code` as the tiebreaker.
  - `[low]` `[patch]` `category` is nullable on the wire and the result panel rendered it
    straight, so a null would have produced an empty `<dd>` under `<dt>Category</dt>`. Falls
    back to the AD-18 sentinel, with a test.
  - `[low]` `[patch]` `make model FROM=...` unlinked the target and then copied over it, so an
    interrupted `copyfile` left an unverified artifact under the name every embedding is
    produced from — the source's digest says nothing about the bytes that landed. Now staged,
    re-verified after the copy fallback and renamed into place, with a test.
  - `[low]` `[patch]` The eight-image bound was tested only at nine, where `>` and `>=` are
    indistinguishable. Pinned from the accepting side too.
  - `[low]` `[patch]` The Reference images hint carries the count and the byte ceiling and is
    stated nowhere else, but was bound to no input — a screen-reader user met both as a
    refusal. Bound through `aria-describedby`, with the refusal appended to the description
    rather than replacing it, and a test on both states.

**What was rejected, and the one pattern in it.** Twenty-five findings were dropped. Most were
re-discoveries of entries already in the ledger from the two earlier passes (the model-gated
suite, the unused HNSW probe, the macOS-only colour assertion, the unbounded request, the
`pixel_std` measure, the connection held across the embedding run, the absent generation
cutover). Of the genuinely new ones: the retained "source" being the colour-managed 2048px
re-encode rather than the literal upload is the documented decision in `intake.py`'s docstring,
not a divergence from it — AD-1 caps both pipelines at 2048px, so a re-index has everything it
needs; `128 MB` for 2^27 bytes is ordinary usage; a commit that fails after the server durably
committed is a property of any two-phase write, not of this one; and `sprint-status.yaml` and
this file's own frontmatter are the orchestrator's bookkeeping, not a defect in the story.

## Design Notes

**Resolutions the architecture left open, recorded here so 2.2–2.5 and `scripts/ingest` inherit them rather than re-deciding:**

1. **Size and Category are reference tables**, not free text. The spine's ERD types them `string`, but the Consistency Conventions row is the later and more specific statement ("normalized into their own reference tables… the same create-if-missing, case/whitespace-normalized lookup"). Normalization is trim → collapse internal whitespace → uppercase, matching the POC's `normalize_folder`. Category is nullable in the ERD; the sentinel is a real `UNKNOWN` row so a query never has to special-case null.
2. **The pipeline stamp lives on the generation row, not on each embedding.** AD-14 says the check is "global, not per-row" and that a re-index is a whole new generation cut over by a single pointer. A `generation_id` FK on `reference_embedding` plus `embedding_generation(pipeline_version, config_hash, is_active)` with a partial unique index on the active row gives exactly that; the ERD's per-row `pipeline_version` column would give per-row semantics AD-14 rejects.
3. **The original is retained, not just the derivative.** AD-17 says the original is never *served*; it is silent on storage. AD-1 invalidates the index on any `shared/vision` change and AD-14 requires rebuilding a complete new generation — which needs source pixels. Discarding the original would make a re-index impossible.
4. **Object storage ships as a seam, not a provider.** `infra/README.md` says to pin the provider before infra work starts and it is not pinned. An `ObjectStore` protocol with a filesystem implementation satisfies AD-6/AD-7/AD-9 (the API still proxies every byte and still holds the only credential) and lets the S3 driver drop in behind it. Adding an SDK against an unchosen provider would be an untestable guess and an unflagged dependency.
5. **Candidate search lands here, not in Epic 3.** The AC says the Tile is "returned as a Candidate for a Scan submitted later in the same session," and the Scan surface does not exist until Epic 3. The testable form of that claim is the query itself, so `find_candidates` ships with the write path it validates; Epic 3 wraps it in the endpoint rather than writing a second one.
6. **The max-over-views query is a grouped scan, not a k-NN probe.** Correctness first: `GROUP BY tile ... MIN(embedding <#> q)` reproduces the POC's `np.maximum.at` semantics exactly. At the catalogue's real size (381 tiles × 1 image × 16 views ≈ 6k vectors) this is milliseconds. The HNSW index still earns its place per AD-5 — inserts join the searchable graph with no reindex — and an index-friendly two-stage probe is a measurable optimization for later, not a guess now.
7. **Query vectors cross the wire as a text literal cast in SQL** (`%s::vector`), parameterized. That avoids the `pgvector` Python package while keeping the query free of string concatenation.

**Flagged new dependencies** (AGENTS.md requires these be raised, not slipped in): `pillow`, `numpy`, `onnxruntime` in `shared/vision`; `python-multipart` and the `shared-vision` workspace link in `apps/api`. Nothing new in `apps/web`. No S3 SDK, deliberately.

**Environment prerequisites** (already satisfied on this machine, documented for the next one): pgvector 0.8.6 built and installed against postgresql@16; the ONNX model fetched by `make model`.

**The porting rule, restated because it is the one thing that cannot be recovered later:** an asymmetry between index-time and query-time preprocessing does not raise an error. It silently costs accuracy, and only an eval run finds it. Copy the file.

## Verification

**Commands:**
- `make lint` -- expected: ruff check, ruff format --check, oxlint and tsc all clean.
- `make test` -- expected: the full pytest workspace and the web vitest suite pass, including the new vision, catalogue, audit and web tests, with the vision suites running rather than skipping.
- `uv run pytest shared/vision/tests -q` -- expected: AD-1 symmetry and AD-15 colour-management assertions pass against the real model.
- `uv run pytest apps/api/tests/test_add_tile.py apps/api/tests/test_tile_searchable.py -q` -- expected: every I/O matrix row passes, including that an added Tile is found with no re-index.
- `uv run python -m rocell_infra.migrate up` then `down --yes` against a scratch database -- expected: the catalogue migration applies and reverts cleanly.

**Manual checks:**
- `psql -c "\d reference_embedding"` -- expected: `embedding vector(1536)` and an HNSW index using an inner-product ops class.
- Stored derivative bytes -- expected: no EXIF, ≤1280px long edge, ≤300KB, and visibly correct colour on a CMYK source (not the green cast a naive RGB conversion produces).



## Auto Run Result

Status: done (second follow-up review pass)

**Summary of the change reviewed.** Story 2.1 in full, as it stands against
`2b807c12f1951ba844cadff0a62cdd1f7666a95d`: the ported `shared/vision` (pipeline, views,
intake), the pgvector catalogue migration, the object-storage seam, `POST /admin/tiles` with
its derivative read route and `find_candidates`, the `Tile` twin contract, and the Add tile
screen. This pass ran because the previous one set `followup_review_recommended: true`. No
implementation loopback was needed: nothing was routed `intent_gap` or `bad_spec`.

**Files changed in this pass** (ten patches, no revert):

- `apps/api/api/catalogue.py` — `_accept` split out of `_prepare`, so every file is read and
  taken through intake before any file is embedded; `t.code` added as the candidate ordering's
  tiebreaker.
- `apps/api/tests/test_add_tile.py` — the multi-image refusal now fails if the embedder is
  reached; the stamp pre-flight's position asserted; the eight-image bound pinned from the
  accepting side; `_discard` driven against a store whose `delete` raises.
- `apps/api/tests/test_object_storage.py` — the failure branch of the staged write.
- `infra/tests/test_migrate.py` — the HNSW index, its access method and its operator class.
- `scripts/fetch_model.py` + `tests/test_fetch_model.py` — `FROM=` adoption staged and
  re-verified after a copy fallback, rather than unlinking the target first.
- `apps/web/src/screens/AddTileScreen.tsx` + `apps/web/src/__tests__/add-tile.test.tsx` — the
  category sentinel rendered rather than an empty row; the file-input hint bound through
  `aria-describedby`.

**Review findings breakdown.** 10 patched, 4 deferred, 25 rejected. The rejected set is
dominated by re-discoveries of entries the two earlier passes already recorded; the new-and-
rejected ones are listed in the triage entry above with the reason each was dropped.

**Follow-up review recommendation: true.** Patched this pass: high 0, medium 3, low 7. Score =
3 x 3 + 1 x 7 = 16, which is at or above 5. The substance of the pass, though, is verification
rather than behaviour: three of the ten were tests for code that could be deleted with the
suite staying green, and two of those were mutation-checked against the exact deletion.

**Verification performed.**

- `make lint` — clean: ruff check, ruff format --check, oxlint `--deny-warnings`, `tsc --noEmit`.
  Run again after the last web edit.
- `make test` — green: 1238 pytest, 1174 vitest, single run, no flake this time. The two web
  tests added after that run were covered by a further `npm run test` (1175 passed).
- `uv run pytest apps/api/tests/test_add_tile.py apps/api/tests/test_object_storage.py
  tests/test_fetch_model.py infra/tests/test_migrate.py -q` — 157 passed, with the model
  artifact present.
- Mutation-checked: restoring the old one-file-at-a-time ordering fails
  `test_a_second_image_that_fails_leaves_no_partial_tile`, and removing the read-only
  `active_generation(conn)` pre-flight fails
  `test_a_foreign_stamp_is_refused_before_anything_is_embedded`. Both pass with the code as
  shipped.
- Not re-run: the scratch-database `migrate up` / `down --yes` pair. No migration file was
  touched in this pass, and `infra/tests` — which applies and reverts the shipped migrations —
  is part of the green `make test`.

**Residual risks.**

- Unchanged from the previous pass, and still the top of the ledger: the silent colour-
  management fallback and the EXIF orientation dropped for profile-bearing images. Both are
  inherited verbatim from the POC, both need a `shared/vision` edit, and CLAUDE.md binds that
  to an eval run and a re-index. `make eval` does not exist until Epic 2 delivers it.
- This pass added a third item of the same shape: `config_hash` does not cover the augmentation
  constants, so a view-recipe change mixes two generations under one stamp. Widening the hash
  is itself a re-index.
- The story's own acceptance says the vision tests run "not skipped" when the model is present.
  They do here. On a checkout without the artifact almost every behavioural claim in this story
  is skipped and `make test` is still green — recorded, not closed.
