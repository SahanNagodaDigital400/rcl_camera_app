# Addendum: Rocell Tile Identification App

Detail that belongs to downstream work (PRD, architecture, solution design) rather than the executive brief. Sourced from `doc/temp_project_brief.md`.

## Full Security Requirements

### Authentication
- Passwords stored using Argon2id (or bcrypt, work factor 12+). Never plain text, never reversible encryption, never MD5/SHA-1.
- Minimum 12-character passwords, checked against a breached-password list. No forced rotation or composition rules.
- Forced password change on first login — the admin sets a temporary credential; the user cannot reach any other screen until they set their own.
- Temporary credentials expire after 72 hours if unused.
- Rate limiting on login: progressive delays after 5 failed attempts, lockout after 10, logged and visible to admins.
- Session tokens in HTTP-only, Secure, SameSite=Strict cookies — never local storage.
- Sessions expire after 12 hours inactivity, absolute expiry at 7 days.
- Immediate session revocation when an admin deactivates a user.

### Authorization
- Role checks enforced server-side on every request — the UI hiding a button is not access control.
- Two roles only in v1 (staff, admin), to keep the permission surface small and auditable.
- At least two admin accounts required, so one lost account can't lock Rocell out of its own user management.

### Transport and infrastructure
- HTTPS everywhere, enforced by HSTS (browsers won't grant camera access over plain HTTP anyway).
- Security headers: strict Content-Security-Policy, X-Content-Type-Options, Referrer-Policy.
- Database and object storage on a private network, not publicly reachable.
- Secrets in a managed secret store or environment variables — never committed to the repo.
- Dependency scanning in CI, with a defined patching window for critical vulnerabilities.

### Input handling
- File uploads validated by content inspection, not file extension.
- Enforced limits on upload size, image dimensions, and request rate.
- Uploaded images stripped of EXIF metadata (GPS, device identifiers) and re-encoded before storage.
- Parameterized database queries throughout; all output escaped.

### Audit and monitoring
- Immutable audit log: logins/failed logins, user creation, role changes, deactivations, deletions, all catalogue modifications. Each entry: who, what, when, source IP.
- Audit log viewable by admins in-app; not editable or deletable from within the app.
- Alerting on anomalies: unusual login times, unexpected-location logins, bulk scanning volume suggesting catalogue scraping.

### Data protection and retention
- Scanned images retained for a defined period (suggested: 90 days), then automatically purged.
- Staff personal data limited to name, email, role — nothing else.
- Deactivated users' scan history: retain for audit, or delete — open question, see below.
- Encryption at rest for database and object storage.

### Threat notes
- **Catalogue exfiltration** is the realistic commercial risk, not data theft — a departing employee or compromised account systematically scanning/exporting the catalogue, or an admin bulk-downloading reference images. Mitigate with scan rate limits, audit logging of bulk access, prompt deactivation on staff exit.
- **Credential sharing** is likely given manual distribution. Individual accounts with visible last-login data make sharing detectable; a shared "showroom" login makes the audit log worthless.
- **Lost/stolen devices** carrying live sessions — addressed by session expiry and admin-initiated revocation.

### Process
- Offboarding must include revoking app access — assign a named owner.
- Independent penetration test before general staff rollout.
- Defined incident response: who is notified, how sessions are mass-revoked, how a breach is communicated.

## Source Dataset — Current State

Reference images live in a shared Google Drive folder (`Shared with me › Tiles`):

```
Tiles/
├── 30X90/, 40X40/, 45X90/, 60X30/, 60X60/,
│   60X120/, 80X80/, 80X120/, 100X100/        ← size folders
│     └── ASTORIA/, ATENAS GLOSSY/,
│         CARRARA MARBLE/, MARMO SIERRA/, …   ← design folders
│           └── Copy of 1Jk.jpg (6.5 MB)
│               Copy of 9JK.jpg (5.6 MB)      ← face images
└── Cement/, Earthen/, Fashion/,
    Mono Colour/, Randomness/, Speckled/       ← category folders (structure unconfirmed)
```

**Product identity is `size + design`**, expressed as the folder path (e.g. `45X90 / CREMA MARMOL`). The ingestion pipeline derives this directly from the path.

**Two file-naming conventions coexist.** Some files carry a structured code (`Copy of RP.CMA.0001DJ.SM.0T.jpg`, decomposing as `RP` prefix · `CMA` design abbreviation · `0001DJ` face/variant number · `SM` · `0T` — meaning of the last two segments unconfirmed). Others carry only a bare face number (`Copy of 1Jk.jpg`). Face numbers are non-contiguous (0001, 0002, 0008), consistent with only a subset of manufactured faces having been photographed.

**Decision already made:** the app returns the matched file name directly rather than building a `size + design → product code` mapping. This removed what was previously the project's blocking dependency. Where the file name is a proper code, staff get exactly what they need; where it's only a face number, the folder-derived size and design shown alongside still identify the product.

**Roughly two images per product** (ASTORIA 40X40 has two files, `1Jk` and `9JK`), against an estimated ~9 manufactured faces per design — a meaningful chance a staff member scans a face the system has never seen.

**These are catalogue images, not scan-like images** — 5–6.5 MB studio/press assets, evenly lit, square-on, colour-corrected. A phone photo under showroom lighting is a different visual domain; this gap is the main thing likely to separate testing accuracy from showroom accuracy.

**Taxonomy is not uniform.** Top level mixes size folders with category folders (Cement, Earthen, Fashion, Mono Colour, Randomness, Speckled) — ingestion cannot assume a fixed depth, and the contents of the category folders are unconfirmed.

**Design names recur across sizes and finishes** (`MONO COLOUR GLOSSY` / `MONO COLOUR MATT` side by side; `Mono Colour` also exists as a top-level category). Same design across `40X40` and `60X60` will be visually identical in a photo — this is the structural confirmation behind the top-3 recommendation, not a model-quality issue.

**Counting discrepancy.** Observed structure suggests a few hundred size+design combinations, not the 2,000+ SKUs previously indicated. Either colourways are counted as separate codes without separate folders, or the Drive holds only part of the catalogue.

### Governance and security concerns with the current source
- **Product assets are owned by personal Gmail accounts** — folders owned variously by `rocell.marketingteam` and two individual `@gmail.com` accounts. If either individual leaves or deletes their Drive, those folders go with them — a business continuity risk independent of this project.
- **Access is via "Shared with me"** — Rocell does not own or control the canonical copy.
- **Files prefixed "Copy of"** — ad-hoc duplication, not a managed asset pipeline; duplicates and version drift likely.
- **Modification dates scattered** across Feb, May, July, August, with no evident release process.

**Recommendation:** move the canonical image set into a Rocell-owned Shared Drive with proper access control before ingestion.

### Target state for the reference set
- **Coverage:** every product code that should be identifiable needs at least one reference image.
- **Recommended:** 3–5 images per product; for shade-varying ranges, at least one per manufactured face.
- **Domain match:** supplement studio assets with phone photographs taken in a real showroom under real lighting — matters more than any modelling decision.
- **Framing:** tile face fills the frame, shot square-on, no packaging/background clutter.
- **Labelling:** an authoritative `size + design + finish + colourway → product code` mapping, maintained as a spreadsheet or database export.

**Action required from Rocell:** provide the product code mapping, confirm the structure of the six category folders, confirm whether the Drive represents the full catalogue.

## Full Risk Register

| Risk | Impact | Mitigation |
|---|---|---|
| Visually identical products across sizes/finishes | High — may be physically unresolvable from an image alone | Top-3 candidate codes with confidence scores; user confirms |
| Inconsistent file naming (structured codes vs. bare face numbers) | Medium — result usefulness varies by product | Always show folder-derived size/design alongside file name; normalize at ingestion; backfill proper codes over time |
| Sparse reference data (~2 images/product, ~9 faces) | High — staff may scan an unseen face | Capture additional faces for high-variation, high-volume ranges before launch |
| Domain gap (studio assets vs. phone photos) | High — testing accuracy overstates showroom accuracy | Supplement with phone-captured reference images; heavy augmentation at index time |
| Assets owned by personal Gmail accounts | High business continuity risk | Migrate to a Rocell-owned Shared Drive before ingestion |
| Non-uniform folder taxonomy | Medium — ingestion can't assume fixed depth | Confirm category folder structure; ingestion validates rather than assumes |
| Catalogue size uncertainty (hundreds of combos observed vs. 2,000+ SKUs assumed) | Medium — affects scope and accuracy expectations | Reconcile Drive against master product list before estimating |
| Lookalike ranges (same design, multiple sizes; glossy/matt variants) | Medium–high | Validate accuracy on a pilot subset before full catalogue rollout |
| Poor capture quality (blurry, angled, badly lit) | Medium | On-screen framing guide, blur detection, prompt to retake |
| Weak reference images added in-app (quick phone snap vs. studio shot) | Medium | Same framing guide and quality checks for admin-added references; flag below-threshold products for re-shooting |
| Manual password distribution (credentials in email/chat threads) | High | Forced first-login password change; 72-hour expiry on unclaimed temp credentials |
| Catalogue exfiltration (compromised/departing account scraping the catalogue) | Medium–high commercial | Scan rate limits, audit logging of bulk access, offboarding process with a named owner |
| Credential sharing (one login for a whole showroom) | Medium | Individual accounts, visible last-login data, admin review of anomalous usage |
| Catalogue drift (new ranges not indexed) | Medium | Named owner for catalogue maintenance |

## Full Open Questions List

1. What do the `SM` and `0T` segments of `RP.CMA.0001DJ.SM.0T` mean? Confirming this may let the app parse and display finish or size from the code itself.
2. What proportion of the catalogue uses structured naming vs. bare face numbers like `1Jk`?
3. Do the category folders (Cement, Earthen, Fashion, Mono Colour, Randomness, Speckled) contain size subfolders, design folders, or loose images?
4. Does the Drive represent the full catalogue, or a subset?
5. Are colourways separate product codes? If so, where are their images?
6. How many manufactured faces exist per design? (Face numbers are non-contiguous — 0001, 0002, 0008 — suggesting gaps.)
7. Can the canonical image set move to a Rocell-owned Shared Drive before ingestion?
8. Should deactivated users' scan history be retained or deleted?
9. Who owns catalogue maintenance when new ranges launch?
10. Expected number of staff users, and peak concurrent usage?
11. Are there device constraints — company phones with a known camera spec, or staff personal devices of varying quality?
12. Target launch date and budget envelope?
13. Does Rocell have an existing IT security policy or compliance obligation this must align with?
14. Is there an existing identity provider (Microsoft 365, Google Workspace) staff already use? SSO would remove the manual password problem entirely.
15. Who owns offboarding, and is there an existing process the app can hook into?
16. How long should scanned images be retained?
