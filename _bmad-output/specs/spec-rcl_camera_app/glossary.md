# Glossary

Domain terms used verbatim (PascalCase in code) across every capability. No synonyms.

- **Product** — A `Size` + `Design` pair; the unit of identity for the Catalogue (e.g. `45X90 / CREMA MARMOL`). Distinct from a **Face**.
- **Design** — A pattern name (e.g. `CREMA MARMOL`, `ASTORIA`).
- **Size** — A tile dimension (e.g. `45X90`, `60X60`).
- **Face** — One manufactured surface variation within a Product. Shade-varying ranges have several Faces; not all are necessarily photographed.
- **Code** — The cleaned reference-image file name returned as the scan result (e.g. `RP.CMA.0001DJ.SM.0T`). Not a separately maintained SKU.
- **Reference Image** — A catalogue photo of a Product/Face, indexed for matching. Distinct from a **Scan**.
- **Scan** — The cropped photo a Staff or Administrator user submits to identify a Product — the result of capturing or uploading (CAP-2), then cropping to the tile face. The pre-crop capture/upload is an input, not itself the Scan.
- **Candidate** — One of the (up to three) results returned for a Scan: a specific Reference Image — and therefore a specific Product and Face — ranked by visual similarity. Candidates are not deduplicated by Product: two or three Candidates may represent different Faces of the same Product.
- **Catalogue** — The full set of indexed Products and their Reference Images.
- **Staff** — A user role that can scan, view results, and view their own scan history.
- **Administrator** — A user role with Staff capabilities plus user management and Catalogue management.
- **Session** — An authenticated period of app use, bounded by inactivity and absolute expiry, and immediately revocable by an Administrator.
