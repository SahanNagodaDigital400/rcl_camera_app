# Glossary

Domain terms used verbatim (PascalCase in code) across every capability. No synonyms.

> **Corrected 2026-09-17, from a working POC** (architecture spine AD-18). The earlier model — `Product = Size + Design`, with the files inside a folder as `Faces` of it — was wrong, confirmed against the real source tree and with Rocell. **Product** and **Face** are retired as domain terms and must not appear as type or entity names in new code.

- **Tile** — **One catalogue file; the unit of identity.** Every file inside a Category folder is a different Tile, and each has exactly one Reference Image. Identified by its **Code**, never by `Size + Category`.
- **Category** — The second-level folder; a range or pattern name (e.g. `CREMA MARMOL`, `ASTORIA`, `POLISH`). A **grouping, never an identity** — the 22 files in `45X90/POLISH` are 22 Tiles, not 22 variants of one. Previously called "Design"; the legacy `design`/`product` field names survive only inside the POC index's `meta.json`, for index compatibility.
- **Size** — A tile dimension (e.g. `45X90`, `60X60`); the top-level folder. A grouping attribute, and the one attribute a photo cannot carry but a person holding the tile knows.
- **Code** — The cleaned reference-image file name returned as the scan result (e.g. `RP.CMA.0001DJ.SM.0T`). This identifies the Tile and is the answer the app returns. Not a separately maintained SKU. Some Codes carry a trailing number; it is a display hint only, nullable, and never an identity.
- **Reference Image** — A catalogue photo of a Tile, indexed for matching. Distinct from a **Scan**. Every Tile in the real catalogue has exactly one; where an Administrator attaches several, they are views of one identity, not separate Tiles.
- **Scan** — The cropped photo a Staff or Administrator user submits to identify a Tile — the result of capturing or uploading (CAP-2), then cropping to the tile face. The pre-crop capture/upload is an input, not itself the Scan.
- **Candidate** — One of the (up to three) results returned for a Scan: a specific **Tile**, ranked by visual similarity. Candidates are **never** deduplicated, collapsed, or diversified by Category — three Candidates from `45X90/POLISH` are three distinct Tiles competing on merit, and collapsing them would hide correct answers.
- **Catalogue** — The full set of indexed Tiles and their Reference Images.

"Tile face" in capture guidance (FR-6, FR-24, the framing guide microcopy) means the physical surface of the tile in the frame — ordinary English, not the retired **Face** entity.
- **Staff** — A user role that can scan, view results, and view their own scan history.
- **Administrator** — A user role with Staff capabilities plus user management and Catalogue management.
- **Session** — An authenticated period of app use, bounded by inactivity and absolute expiry, and immediately revocable by an Administrator.
