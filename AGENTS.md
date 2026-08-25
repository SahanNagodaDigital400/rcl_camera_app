<!-- bmad:context -->
<!-- Verified 2026-08-25 against 6c0ef7d. Managed by bmad-project-context; edits inside this block are replaced on refresh. Keep anything you want preserved outside the markers. -->

## rcl_camera_app — Rocell Tile Identification App

Internal PWA that identifies a ceramic tile from a phone camera photo and returns the matching product file name, reference image, size, and design. Rocell staff only, admin-provisioned accounts, online-only. Image-embedding retrieval, not a trained classifier — full stack, repo layout, and commands are in `CLAUDE.md`; planning and the product brief are in `_bmad-output/planning-artifacts/briefs/brief-rcl_camera_app-2026-08-25/`.

## Policy

- Never store passwords in plaintext or reversible encryption — Argon2id only, never MD5/SHA-1.
- Never let a UI-only check gate a privileged action — authorization is enforced server-side on every endpoint, independent of what the UI hides.
- Never accept file uploads validated by extension — inspect content, strip EXIF, re-encode before storage.
- Never store session tokens outside HTTP-only, Secure, SameSite=Strict cookies — never localStorage/sessionStorage.
- Never build raw/string-concatenated SQL — parameterized queries only, all output escaped.
- Never commit or hardcode secrets, including in test fixtures — environment or secret store only.
- Never let deactivating a user leave a session live — revoke immediately, not just block the next login.
- Never add an update or delete path to the audit log, from code or the admin UI — append-only, covering logins, user changes, and catalogue changes with who/what/when/source IP.
- Never skip the forced password change on an admin-issued temporary credential before granting further access; temporary credentials expire after 72 hours.
- Rate-limit login (progressive delay after 5 failures, lockout at 10) and scanning — catalogue exfiltration via a compromised account is the primary commercial threat.
- Never add roles beyond `staff` and `admin`, customer/dealer access, offline scanning, price/stock/spec data, or app-sent email (admins distribute credentials manually) — out of scope for v1, see the brief.
- Independent penetration test gates general staff rollout — build every feature to survive one.
- If a task seems to require breaking any of the above, stop and raise it rather than working around it.

## Where things are

- Full stack, repo layout, `make` commands, domain vocabulary, and testing approach: `CLAUDE.md`.
- Product brief: `_bmad-output/planning-artifacts/briefs/brief-rcl_camera_app-2026-08-25/brief.md` (+ `addendum.md` for full security/dataset/risk detail).
- Original stakeholder draft: `doc/temp_project_brief.md`.

## Conventions that differ from defaults

- Python: ruff, type hints throughout, no bare `except`.
- TypeScript: strict mode, no `any` without a comment explaining why.
- Migrations are forward-only and reversible — never edit an applied migration.
- Commits follow Conventional Commits (`feat:`, `fix:`, `chore:`).
- Flag any new dependency before adding it — small team, long maintenance tail.

## Known pitfalls

- Index-time and query-time image preprocessing/embedding must be byte-for-byte identical (one shared module, both pipelines call it) — any asymmetry silently destroys match accuracy with no error raised.
- Don't reach for a dedicated vector database (Pinecone, Milvus, Qdrant) — catalogue scale (~10k vectors) fits `pgvector` in Postgres comfortably; measure before proposing a swap.
- Don't build a `size + design → product code` mapping table — the cleaned reference-image file name is the returned code.
- Don't add a "confidence threshold that shows only one result" feature — always return the top 3 candidates with reference images; a single answer is unverifiable and this is a deliberate product requirement, not an oversight.

<!-- /bmad:context -->
