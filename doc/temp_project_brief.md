# Project Brief — Rocell Tile Identification App

**Prepared:** 25 August 2026
**Status:** Draft v1 — for review
**Product type:** Progressive Web App (PWA), internal use

---

## 1. Summary

Rocell staff frequently encounter tiles whose product code is unknown — an unlabelled showroom sample, a returned box, a customer's leftover tile, a piece pulled from storage. Identifying it today means manually flipping through the catalogue or asking a colleague who happens to remember.

This project delivers a browser-based camera app that lets a staff member point their phone at a tile and receive the matching product code. Access is restricted to Rocell staff, provisioned by an administrator.

---

## 2. Objectives

1. Reduce tile identification from minutes of manual catalogue searching to seconds.
2. Reduce misidentification errors that lead to wrong orders and returns.
3. Make catalogue knowledge available to junior staff, not just long-serving employees.
4. Keep the system easy to maintain as new tile ranges are released.

---

## 3. Users and roles

| Role | Who | Capabilities |
|---|---|---|
| **Staff user** | Showroom, warehouse and sales staff | Log in, scan a tile, view the identified product code, view scan history |
| **Administrator** | Nominated Rocell IT / operations staff | Everything a staff user can do, plus create, edit, deactivate and delete user accounts; manage the reference image catalogue |

There is **no public sign-up**. Accounts exist only when an administrator creates them.

---

## 4. Scope

### In scope

**Authentication and access**
- Email and password login.
- Admin-created accounts only; no self-registration, no social login.
- Password reset for a signed-in user.
- Session persistence so staff aren't logging in repeatedly during a shift.

**Tile scanning**
- Live camera capture from the device browser, plus an option to upload an existing photo.
- On-screen framing guide so users capture the tile consistently.
- Image sent to the server for matching; result returned to the device.
- Result screen showing, for each candidate match: the **reference image**, the **file name / code** (cleaned of the "Copy of" prefix and extension), and the **size and design** derived from the folder path.
- Scan history for the logged-in user.

**Admin — user management (in-app)**
- List all users with status (active / deactivated) and last login.
- Add a new user: name, email, role, initial password.
- Edit a user's details or role.
- Deactivate or delete a user, revoking access immediately.
- After creating a user, the admin communicates the email and password to that person manually. The app does not send email.

**Admin — catalogue management**
- **Add a new tile product from within the app:** enter a product code, upload or capture one or more reference images, and save. The tile becomes identifiable immediately, without a developer or a data re-import.
- Edit an existing product: change the code, add, replace or remove its reference images.
- Remove a product from the index (for discontinued ranges).
- Bulk upload for the initial catalogue load and for large new ranges — a set of images plus a spreadsheet of codes.
- Search and filter the catalogue by product code to find an entry quickly.
- Automatic re-indexing after any change. The embedding approach in Section 5 makes this near-instant for a single tile, so an admin can add a product and test a scan against it in the same session.

### Out of scope for v1

- Native iOS and Android apps.
- Offline scanning.
- Identifying tiles already installed on floors and walls (grouted, angled, partially obscured).
- Price, stock levels, specifications, or any data beyond the product code.
- Customer-facing or dealer-facing access.
- Automated invitation or password-reset emails.
- Integration with ERP, POS or inventory systems.

---

## 5. Technical approach

**Front end:** A PWA served over HTTPS, installable to the phone home screen. Camera access via the browser's standard media APIs. Works on modern Chrome and Safari on iOS and Android.

**Matching:** Because the app is online-only, all recognition happens server-side. The recommended approach is **image embedding similarity search** rather than a trained classifier:

1. Each reference image is passed through a vision model to produce a numerical fingerprint (embedding).
2. All fingerprints are stored in a vector index.
3. A scanned photo is converted to a fingerprint the same way and compared against the index.
4. The closest matches are returned, ranked by similarity.

This approach is chosen deliberately: with 2,000+ product codes and new ranges arriving regularly, a trained classifier would need retraining every time the catalogue changes. With embedding search, adding a new tile means adding one row to the index — a matter of seconds, not a retraining cycle.

**Back end:** API for authentication, user management, scan submission and catalogue administration. Relational database for users and product codes; vector index for image fingerprints. Object storage for reference and scanned images.

---

## 6. Security requirements

Access to this app means access to Rocell's full product catalogue and to a staff account list. Security is treated as a build requirement, not a hardening pass at the end.

### Authentication

- Passwords stored using Argon2id (or bcrypt with a work factor of 12+). Never plain text, never reversible encryption, never MD5 or SHA-1.
- Minimum 12-character passwords, checked against a breached-password list. No forced rotation or composition rules — these push users toward weaker, more predictable passwords.
- **Forced password change on first login.** The admin sets a temporary credential; the user cannot reach any other screen until they set their own. This closes the window where an admin-chosen password sits readable in a WhatsApp or email thread.
- Temporary credentials expire after 72 hours if unused. An unclaimed account is a standing open door.
- Rate limiting on login: progressive delays after 5 failed attempts, account lockout after 10, with the lockout logged and visible to admins.
- Session tokens in HTTP-only, Secure, SameSite=Strict cookies. Never in local storage, where any script on the page can read them.
- Sessions expire after 12 hours of inactivity, with absolute expiry at 7 days.
- Immediate session revocation when an admin deactivates a user — deactivation must kill live sessions, not just block the next login.

### Authorisation

- Role checks enforced server-side on every request. Hiding an admin button in the UI is not access control; the API must independently reject a staff user calling an admin endpoint.
- Two roles only in v1 (staff, admin) to keep the permission surface small and auditable.
- At least two admin accounts required, so a single lost account doesn't lock Rocell out of its own user management.

### Transport and infrastructure

- HTTPS everywhere, enforced by HSTS. Browsers will not grant camera access over plain HTTP anyway, so this is mandatory rather than optional.
- Security headers: strict Content-Security-Policy, X-Content-Type-Options, Referrer-Policy.
- Database and object storage on a private network, not publicly reachable. No public S3 buckets holding catalogue images.
- Secrets in a managed secret store or environment variables — never committed to the repository.
- Dependency scanning in CI, with a defined patching window for critical vulnerabilities.

### Input handling

- File uploads validated by content inspection, not file extension. An admin upload endpoint that accepts arbitrary files is a direct path to remote code execution.
- Enforced limits on upload size, image dimensions and request rate.
- Uploaded images stripped of EXIF metadata (which can carry GPS coordinates and device identifiers) and re-encoded before storage.
- Parameterised database queries throughout. All output escaped.

### Audit and monitoring

- Immutable audit log covering: logins and failed logins, user creation, role changes, deactivations, deletions, and all catalogue modifications. Each entry records who, what, when and source IP.
- Audit log viewable by admins in-app, and not editable or deletable from within the app.
- Alerting on anomalies: unusual login times, logins from unexpected locations, bulk scanning volume that suggests catalogue scraping.

### Data protection and retention

- Scanned images retained for a defined period (suggest 90 days) then automatically purged. Retaining them indefinitely creates a growing liability with no operational benefit.
- Staff personal data limited to name, email and role. No phone numbers, addresses or other data the app doesn't need.
- Defined handling for deactivated users' scan history — retain for audit or delete. See open questions.
- Encryption at rest for the database and object storage.

### Threat notes

- **Catalogue exfiltration** is the realistic commercial risk, not data theft. A departing employee or a compromised account could systematically scan and export the product catalogue, or an admin could bulk-download reference images. Mitigate with rate limits on scanning, audit logging of bulk catalogue access, and prompt deactivation on staff exit.
- **Credential sharing** is likely given manual distribution. Individual accounts with visible last-login data make sharing detectable; a shared "showroom" login makes the audit log worthless.
- **Lost or stolen devices** carrying live sessions — addressed by session expiry and admin-initiated revocation.

### Process

- Offboarding must include revoking app access. Assign a named owner for this.
- Independent penetration test before general staff rollout.
- Defined incident response: who is notified, how sessions are mass-revoked, how a breach is communicated.

---

## 7. Source dataset — current state

The reference images live in a shared Google Drive folder (`Shared with me › Tiles`). The observed structure is:

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

### What this tells us

**Product identity is `size + design`, expressed as folder path.** `45X90 / CREMA MARMOL` is the unit of identity. The ingestion pipeline derives this directly from the path.

**Some file names carry the product code; others do not.** Two naming conventions are present in the same Drive:

| Folder | File name | Contains a code? |
|---|---|---|
| `40X40 / ASTORIA` | `Copy of 1Jk.jpg` | No — appears to be a face number only |
| `45X90 / CREMA MARMOL` | `Copy of RP.CMA.0001DJ.SM.0T.jpg` | Yes — structured code |

The structured form appears to decompose as `RP` (prefix) · `CMA` (design abbreviation, matching CREMA MARMOL) · `0001DJ` (face or variant number) · `SM` · `0T`. The meaning of the last two segments needs confirming from Rocell. Face numbers are non-contiguous (0001, 0002, 0008), which is consistent with the earlier observation that only a subset of manufactured faces has been photographed.

**Decision: the file name is the answer.** Rather than building a `size + design → product code` mapping, the app returns the matched file name directly, alongside the reference image and the folder-derived size and design. This removes what was previously the project's blocking dependency. Where the file name is a proper code (`RP.CMA.0001DJ.SM.0T`), staff get exactly what they need. Where it is only a face number (`1Jk`), the size and design shown alongside still identify the product — which is why the folder path must always be displayed, not just the file name.

**Showing the reference image is what makes the top-3 approach work.** A staff member cannot verify a code they don't recognise, but they can instantly verify a picture. Three candidates with images is a better interaction than one code without one — and it resolves the size and finish ambiguity that no model can resolve on its own.

**Roughly two images per product.** ASTORIA 40X40 has two files. If `1Jk` and `9JK` are face numbers, the design likely has around nine manufactured faces and only two are captured. For a shade-varying range, a staff member has a meaningful chance of scanning a face the system has never seen.

**These are catalogue images, not scan-like images.** At 5–6.5 MB they are high-resolution studio or press assets — evenly lit, square-on, colour-corrected. A phone photo under showroom lighting is a different visual domain. This gap is the main thing preventing the model from performing as well in the showroom as it will in testing.

**The taxonomy is not uniform.** The top level mixes size folders with category folders (Cement, Earthen, Fashion, Mono Colour, Randomness, Speckled). Ingestion cannot assume a fixed depth. The contents of the category folders need to be confirmed — do they contain size subfolders, design folders, or loose images?

**Design names recur across sizes and finishes.** `MONO COLOUR GLOSSY` and `MONO COLOUR MATT` sit side by side in the same size folder, and `Mono Colour` also exists as a top-level category. Same design across `40X40` and `60X60` will be visually identical in a photo. This is the structural confirmation of the top-3 recommendation in Section 9 — it is not a model quality issue, it is an information-theoretic limit.

**Counting discrepancy.** The observed structure suggests a few hundred size-plus-design combinations, not the 2,000+ SKUs previously indicated. Either colourways are counted as separate product codes without separate folders, or the Drive holds only part of the catalogue. This needs resolving — it changes both the scope and the accuracy expectations.

### Governance and security concerns with the current source

- **Product assets are owned by personal Gmail accounts.** Folders are owned variously by `rocell.marketingteam` and by two individual `@gmail.com` accounts. If either individual leaves Rocell or deletes their Drive, those folders and their contents go with them. This is a business continuity risk independent of this project.
- **Access is via "Shared with me"**, meaning Rocell does not own or control the canonical copy.
- **Files are prefixed "Copy of"**, indicating ad-hoc duplication rather than a managed asset pipeline. Duplicates and version drift are likely.
- **Modification dates are scattered** across Feb, May, July and August, with no evident release process.

**Recommendation:** before ingestion, move the canonical image set into a Rocell-owned Shared Drive with proper access control. Ingest from there, not from personal accounts.

### Target state for the reference set

- **Coverage:** every product code that should be identifiable needs at least one reference image.
- **Recommended:** 3–5 images per product, and for shade-varying ranges, at least one image per manufactured face.
- **Domain match:** supplement studio assets with phone photographs taken in a real showroom under real lighting. This matters more than any modelling decision.
- **Framing:** the tile face fills the frame, shot square-on, no packaging or background clutter.
- **Labelling:** an authoritative `size + design + finish + colourway → product code` mapping, maintained as a spreadsheet or database export.

**Action required from Rocell:** provide the product code mapping, confirm the structure of the six category folders, and confirm whether the Drive represents the full catalogue.

---

## 8. Key risks

| Risk | Impact | Mitigation |
|---|---|---|
| **Visually identical products** — the same tile design sold in multiple sizes or finishes looks the same in a photo | High. The system may be physically unable to distinguish them from an image alone | Return the **top 3 candidate codes** with confidence scores rather than a single answer, and let the user confirm. Recommended change to the "just the product code" requirement |
| **Inconsistent file naming** — some files carry structured codes (`RP.CMA.0001DJ.SM.0T`), others only face numbers (`1Jk`) | Medium. Result usefulness varies by product | Always display folder-derived size and design alongside the file name; normalise names at ingestion; backfill proper codes over time |
| **Sparse reference data** — approximately two images per product, likely covering two of ~nine manufactured faces | High. A staff member may scan a face the system has never seen | Capture additional faces for high-variation and high-volume ranges before launch |
| **Domain gap** — reference set is 5–6 MB studio assets; queries are phone photos under showroom lighting | High. Accuracy in testing will overstate accuracy in the showroom | Supplement with phone-captured reference images; heavy augmentation at index time |
| **Assets owned by personal Gmail accounts** — folders owned by individuals, accessed via "Shared with me" | High business continuity risk | Migrate the canonical set to a Rocell-owned Shared Drive before ingestion |
| **Non-uniform folder taxonomy** — top level mixes size folders with category folders | Medium. Ingestion cannot assume fixed depth | Confirm category folder structure; write ingestion to validate rather than assume |
| **Catalogue size uncertainty** — observed structure suggests hundreds of combinations, not 2,000+ SKUs | Medium. Affects scope and accuracy expectations | Reconcile the Drive against the master product list before estimating |
| **Lookalike ranges** — same design across multiple sizes; glossy and matt variants of the same design | Medium–high | Validate accuracy on a pilot subset before committing to full catalogue rollout |
| **Poor capture quality** — blurry, angled, badly lit photos | Medium | On-screen framing guide, blur detection, prompt to retake |
| **Weak reference images added in-app** — a tile added via a quick phone snap under showroom lighting matches less reliably than a studio shot | Medium | Apply the same framing guide and quality checks when admins add reference images; flag products whose reference images fall below a quality threshold for later re-shooting |
| **Manual password distribution** — credentials sent by email or messaging app persist in readable threads | High | Forced password change on first login; 72-hour expiry on unclaimed temporary credentials. See Section 6 |
| **Catalogue exfiltration** — a compromised or departing staff account used to scrape the product catalogue | Medium–high commercial | Scan rate limits, audit logging of bulk access, offboarding process with a named owner |
| **Credential sharing** — one login used by a whole showroom | Medium | Individual accounts, visible last-login data, admin review of anomalous usage |
| **Catalogue drift** — new ranges not added to the index | Medium | Assign a named owner for catalogue maintenance |

---

## 9. Recommendations

**Return top 3 matches with images, not one code.** Showing the reference image alongside each candidate turns an unverifiable answer into a verifiable one. A staff member cannot check a code they don't recognise, but they can check a picture in under a second. This also resolves the size and finish ambiguity that no model can resolve from a photo — `MONO COLOUR GLOSSY` and `MONO COLOUR MATT` are indistinguishable to the camera but obvious to a person holding the tile. Show the top match prominently with two alternatives beneath it.

**Force a password change on first login.** The requirement is for admins to send credentials manually, which is fine as a process. But an admin-chosen password sitting in an email thread is a standing risk. Forcing the user to set their own password on first login closes that gap at very low build cost, and doesn't change the admin's workflow at all.

**Run a pilot before full catalogue ingestion.** Index 150–200 product codes covering your most common ranges, then have showroom staff test against real samples for two weeks. This tells you the true accuracy ceiling before you invest in photographing 2,000+ products.

---

## 10. Suggested phasing

**Phase 0 — Dataset consolidation**
Migrate the canonical image set to a Rocell-owned Shared Drive. Audit coverage: how many products, how many images each, which faces are missing, and which folders use which naming convention. Confirm the meaning of the code segments. No longer blocking on a product code mapping, but still the prerequisite for a realistic estimate.

**Phase 1 — Foundation**
Authentication (including forced first-login password change), server-side authorisation, audit logging, admin user management, catalogue management (add, edit and remove individual tiles, plus bulk upload) and the indexing pipeline.

**Phase 2 — Scanning pilot**
Camera capture, matching against a 150–200 product pilot index, results screen. Internal accuracy testing.

**Phase 3 — Full rollout**
Full catalogue ingestion, scan history, accuracy tuning based on pilot findings, staff rollout and training. **Gate: independent penetration test passed before general staff access is granted.**

**Phase 4 — Refinement**
Improve accuracy using real scan data, add reference images for problem products, review misidentification reports.

---

## 11. Success metrics

- **Top-1 accuracy** — correct code is the first result. Target to be set after pilot.
- **Top-3 accuracy** — correct code appears in the returned candidates. This is the metric that reflects real-world usefulness.
- **Time to result** — from capture to displayed code. Target under 3 seconds.
- **Adoption** — proportion of showroom staff scanning at least weekly.
- **Fallback rate** — how often staff abandon a scan and revert to manual lookup.

---

## 12. Open questions

1. What do the `SM` and `0T` segments of `RP.CMA.0001DJ.SM.0T` mean? Confirming this may let the app parse and display finish or size from the code itself.
2. What proportion of the catalogue uses the structured naming versus bare face numbers like `1Jk`?
3. Do the category folders (Cement, Earthen, Fashion, Mono Colour, Randomness, Speckled) contain size subfolders, design folders, or loose images?
4. Does the Drive represent the full catalogue, or a subset? The observed structure suggests hundreds of size-plus-design combinations rather than 2,000+ codes.
5. Are colourways separate product codes? If so, where are their images?
6. How many manufactured faces exist per design? Face numbers are non-contiguous (0001, 0002, 0008), suggesting gaps.
7. Can the canonical image set be moved to a Rocell-owned Shared Drive before ingestion?
8. Should deactivated users' scan history be retained or deleted?
9. Who owns catalogue maintenance when new ranges launch?
10. Expected number of staff users, and peak concurrent usage?
11. Are there device constraints — company phones with a known camera spec, or staff personal devices of varying quality?
12. Target launch date and budget envelope?
13. Does Rocell have an existing IT security policy or compliance obligation this must align with?
14. Is there an existing identity provider (Microsoft 365, Google Workspace) staff already use? Single sign-on would remove the manual password problem entirely — worth evaluating before building separate credentials.
15. Who owns offboarding, and is there an existing process the app can hook into?
16. How long should scanned images be retained?