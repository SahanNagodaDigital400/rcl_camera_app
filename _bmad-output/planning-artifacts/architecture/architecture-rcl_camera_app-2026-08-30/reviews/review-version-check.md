# Review — Version & Reality Check: ARCHITECTURE-SPINE.md

**Target:** `_bmad-output/planning-artifacts/architecture/architecture-rcl_camera_app-2026-08-30/ARCHITECTURE-SPINE.md`
**Method:** WebSearch against current (August 2026) sources for every pinned version in the Stack table, plus a reasonableness check on AD-3, AD-5, AD-8 at the stated scale (~10k vectors, internal staff, low traffic).
**Verdict:** CONDITIONAL PASS — core service stack (React, FastAPI, ONNX Runtime, Argon2id) checks out and is current. Two entries are stale by a full major version or more (Vite, TypeScript), one is one major behind current stable (PostgreSQL), and one has a load-bearing, silently-unaddressed security detail (pgvector CVE affecting the exact index type AD-5 mandates). None of these invalidate the architecture's shape, but the Stack table cannot be taken as verified-current until these are fixed.

---

## Stack table findings

| Entry | Spine says | Reality (Aug 2026, web-confirmed) | Status |
|---|---|---|---|
| React | 19.2.x | Current. Latest patch 19.2.8 (Jul 21, 2026); no React 20. | **OK** |
| TypeScript | 5.x | **Stale.** TypeScript 6.0 went GA Mar 23, 2026 (transition release for the Go-based rewrite). TypeScript 7.0 has *also* shipped — 7.0.2 in Aug 2026 — advertised as ~10x faster, native/Go-based compiler, distinct tooling/plugin model from 5.x/6.x. Spine is two majors behind current. | **FLAG — HIGH** |
| Vite | latest 6.x | **Stale.** Vite 8.0 went stable Mar 12, 2026 (8.0.9 by Apr 20, 2026), with Rolldown (Rust bundler) as the default bundler — a materially different architecture from Vite 6. Vite 7 shipped in between. Spine is two majors behind current. | **FLAG — HIGH** |
| Python | 3.12+ | Current stable is 3.14 (3.14.6, Jun 2026); 3.15 is in RC (rc1 Aug 4, 2026). Spine's constraint is an open floor ("3.12+"), so it isn't technically wrong, but it doesn't reflect that 3.13's free-threading and 3.14's improvements are available and worth deciding on explicitly rather than defaulting to the floor. | **OK (floor), worth a decision** |
| FastAPI | 0.141.x | Confirmed current. 0.141.0 released Jul 29, 2026, 0.141.1 same day (bugfix). | **OK — good match** |
| ONNX Runtime | 1.25.x | Confirmed current (1.25.0). Note for the record, not a blocker: ORT 1.25 requires C++20 to build *from source* and raises the CUDA floor to 12.0 — irrelevant here since the spine specifies CPU inference via prebuilt wheels, not a from-source CUDA build. | **OK** |
| DINOv2 | backbone, ONNX-exported | DINOv3 (Meta, Aug 2025) exists, outperforms DINOv2 on dense/segmentation tasks, and predates this project. **But** DINOv3 shipped under a new restrictive custom license (approval process, personal-data disclosure to Meta, mandatory "Built with DINOv3" attribution) replacing DINOv2's permissive Apache 2.0. DINOv2 remaining the pick is defensible on licensing grounds for an internal commercial tool — but the spine states it as if DINOv2 were simply "the" backbone, with no record that DINOv3 was considered and rejected for license-friction reasons. | **FLAG — MEDIUM (undocumented decision, not a wrong one)** |
| PostgreSQL | 17 | PostgreSQL 18 has been the current stable major since ~Sept 2025 (18.6 / 17.11 released Aug 13, 2026 alongside a PG19 beta). Pg 17 is still fully supported and a safe choice, but the spine pins one major behind current without saying why (e.g., ecosystem/driver maturity, hosting provider support) — that's a decision, not a default. | **FLAG — LOW/MEDIUM** |
| pgvector | 0.8.x (HNSW) | Version series is correct — 0.8.6 is latest. **But:** CVE-2026-3172 (CVSS 8.1, buffer overflow / integer underflow) hits pgvector 0.6.0–0.8.1 specifically in **parallel HNSW index build** — the exact index type AD-5 mandates. Fixed in 0.8.2+. The spine's unpinned "0.8.x" would silently permit a vulnerable patch version. | **FLAG — HIGH (security, directly touches AD-5)** |
| Argon2id | — | Confirmed still the current OWASP-recommended default for 2026 (beats bcrypt/scrypt/PBKDF2 in current guidance). No change needed. | **OK** |

---

## Findings requiring action

1. **[HIGH] pgvector must be pinned to ≥0.8.2 (ideally 0.8.6, the current latest), not open-ended "0.8.x."** CVE-2026-3172 is a buffer overflow in parallel HNSW index builds — CVSS 8.1, allows leaking data from other relations or crashing the server — present in every 0.8.x release before 0.8.2. AD-5 explicitly chooses HNSW, so this isn't a generic footnote; an unpinned "0.8.x" in the Stack table is a live foot-gun for whoever provisions the database. Add the floor to the Stack table and to AD-5's rule.

2. **[HIGH] TypeScript "5.x" is two majors behind current (6.0 GA, 7.0 already shipping with a different compiler architecture).** Worth an explicit call: pin to a current 5.9/6.x release deliberately (e.g., ecosystem/plugin compatibility isn't there yet for 7.0), rather than have "5.x" read as simply not-yet-updated. If 7.0's native compiler changes tooling assumptions (ESLint integration, ts-node, ts-jest, etc.), that's worth a line since it affects `apps/web` and `shared/schema` tooling.

3. **[HIGH] Vite "latest 6.x" is two majors behind current (8.0 stable, Rolldown-based).** Same treatment as TypeScript: either state a deliberate reason to stay on 6.x (plugin ecosystem maturity, PWA plugin compatibility) or move the floor up. As written it reads as an assumption from training data rather than a verified current pin.

4. **[MEDIUM] DINOv2's continued use over DINOv3 should be stated as a reasoned decision, not left implicit.** DINOv3 outperforms DINOv2 and existed well before this spine was written (Aug 2025 vs Aug 2026), so its absence from the "Deferred" section reads as unconsidered rather than rejected. The likely correct call is to stay on DINOv2 (Apache 2.0, no approval workflow, no mandatory attribution UI change, no PII disclosure to Meta) — but that reasoning belongs in the spine (either as a rule note under the Stack table or a line in "Deferred"), not left for a reader to reconstruct.

5. **[LOW] PostgreSQL 17 vs 18 — no stated reason to be one major behind current stable.** Not urgent (17 is fully supported, receiving patches through Aug 2026), but should be a one-line deliberate call (e.g., "17 for broader managed-hosting support until the provider decision lands" — which is itself still Deferred in this spine) rather than silence.

## Architectural judgment checks (AD-3, AD-5, AD-8)

- **AD-3 — Postgres-backed sessions, no Redis.** Still a reasonable, well-established pattern at this scale (internal staff, low concurrent session volume). Nothing found in current material suggests this tradeoff has shifted. The spine already carries its own revisit clause ("`[ASSUMPTION — revisit only if concurrent session volume becomes a measured bottleneck]`"), which is the right hedge. No change recommended.

- **AD-5 — HNSW over IVFFlat, hard delete not soft.** Still the right call at ~10k vectors: HNSW build/insert cost is trivial at this volume (sub-second inserts, full index build in seconds, not the minutes/hours territory where HNSW build time becomes a real tradeoff), and pgvector 0.8.0's iterative index scan (`hnsw.iterative_scan`) has since fixed the old failure mode where a filtered HNSW query could silently under-return or return zero rows — which further *supports* AD-5's reasoning, since even if a future filtered query were added, 0.8.x handles it correctly (with `hnsw.max_scan_tuples`/`ef_search` tuning) rather than requiring app-level workarounds. The one real gap is the version-floor issue in Finding 1 above — the design choice is sound, the version pin isn't.

- **AD-8 — Postgres-backed rate-limit/anomaly counters.** Reasonable at this traffic level; no counter-store consensus shift found. One suggestion: AD-3 explicitly carries a "revisit if X is measured" escape hatch — AD-8 doesn't. Given login-lockout and scan-rate counters are higher-write-frequency than session rows, consider adding the same explicit revisit trigger (e.g., "revisit if per-second counter writes cause measurable row-lock contention") so this doesn't quietly ossify into dogma if traffic assumptions change.

## Not flagged (checked, confirmed current)

React 19.2.x, FastAPI 0.141.x, ONNX Runtime 1.25.x (CPU path), Argon2id as the password-hashing choice, pgvector's 0.8 series as the right major version (only the minor floor needs fixing).
