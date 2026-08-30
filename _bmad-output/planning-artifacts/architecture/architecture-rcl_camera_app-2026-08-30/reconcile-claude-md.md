# Reconcile: ARCHITECTURE-SPINE.md vs. AGENTS.md / CLAUDE.md

Scope: check the spine's Stack table, Structural Seed, Design Paradigm, and ADs for anything CLAUDE.md/AGENTS.md already settled that the spine got wrong, dropped, contradicted, mis-tagged, or silently substituted.

## 1. Items dropped or under-specified vs. an already-adopted policy

### Gap A — Session cookie transport requirement not encoded anywhere in the spine
- **Source of truth:** CLAUDE.md Stack table: `Auth | Argon2id, HTTP-only session cookies`. AGENTS.md Policy: "Never store session tokens outside HTTP-only, Secure, SameSite=Strict cookies — never localStorage/sessionStorage."
- **Spine:** Stack table's `Password hashing | Argon2id` row keeps only the hashing half of the CLAUDE.md Auth row; the cookie-transport half (HttpOnly/Secure/SameSite=Strict, never localStorage) is dropped entirely — no Stack row, and no AD.
- **Consequence:** AD-3 ("Session state lives in Postgres") is the natural home for this — it governs how sessions are validated but says nothing about how the token reaches the client or is stored there. This is exactly the kind of "security invariant with an architectural consequence" the spine's AD layer exists to carry forward, and it's currently unstated. A future implementer reading only the spine could legally satisfy AD-3 while storing the session token in localStorage.
- **Recommendation:** Add the cookie-attribute rule to AD-3 (or a new AD it binds), and restore the dropped half of the Auth stack row.

### Gap B — Camera capture stack entry (`getUserMedia` + canvas downscale) missing from the spine's Stack table
- **Source of truth:** CLAUDE.md Stack table has a dedicated row: `Camera | getUserMedia, canvas downscale to ~1024px before upload`.
- **Spine:** The spine's Stack table (Design Paradigm section) has no Camera/capture row at all. The ~1024px downscale only surfaces indirectly, in AD-2's prose ("client-side canvas downscale (~1024px)").
- **Consequence:** Minor but real — this is a decided (ADOPTED) stack element from CLAUDE.md, and the spine's Stack table is supposed to be the verified-technology inventory. Its absence there makes AD-2 look like it invented the technology choice rather than inheriting it.
- **Recommendation:** Add a Camera/Capture row to the Stack table, tagged consistent with CLAUDE.md (ADOPTED), separate from AD-2's [ASSUMPTION] framing of how that capture interacts with the preprocessing boundary.

### Gap C — Rate-limiting (login + scanning) has no dedicated AD despite being AGENTS.md-adopted policy
- **Source of truth:** AGENTS.md Policy: "Rate-limit login (progressive delay after 5 failures, lockout at 10) **and scanning** — catalogue exfiltration via a compromised account is the primary commercial threat."
- **Spine:** Never appears as an AD. It surfaces only as: (a) a Capability Map cell naming an "audit/rate-limit module" in `apps/api`, and (b) the Deferred section, which correctly defers only the *numeric threshold values* (PRD OQ-13) but doesn't first state, as an AD, the already-settled architectural facts — that rate limiting is mandatory on both login and scan submission, and lives in `apps/api`.
- **Consequence:** The Deferred section's phrasing ("This spine fixes which module owns each enforcement point... not the values") implies the ownership decision was made somewhere, but there's no AD a reader can point to. Given AGENTS.md calls this "the primary commercial threat," it reads as under-weighted relative to AD-4 (audit immutability), which gets a full AD for a comparably-scoped policy line.
- **Recommendation:** Add an AD (e.g. AD-8) stating rate-limiting is enforced in `apps/api` on both the login and scan-submission endpoints, tagged [ADOPTED] for the applicability/mechanism-shape and pointing at the Deferred section only for the numeric thresholds.

## 2. Tagging check — [ASSUMPTION] vs [ADOPTED]

### Mis-tag — AD-4 (audit-log immutability) is wholly [ASSUMPTION] but its core rule is already AGENTS.md policy
- AGENTS.md Policy: "Never add an update or delete path to the audit log, from code or the admin UI — append-only, covering logins, user changes, and catalogue changes with who/what/when/source IP."
- AD-4 as written conflates two distinct claims under one [ASSUMPTION] tag:
  1. **Already decided (should be [ADOPTED]):** the audit log is append-only — no UPDATE/DELETE path, corrections via new corrective entries.
  2. **A new architectural decision (correctly [ASSUMPTION]):** *how* that's enforced — specifically, at the database-role-grant layer (INSERT/SELECT only, no UPDATE/DELETE grant) rather than solely in application code.
- **Recommendation:** Split AD-4's rule statement so the append-only requirement is marked [ADOPTED] (citing AGENTS.md Policy) and only the DB-grant enforcement mechanism carries [ASSUMPTION].

### Checked and correctly tagged
- **AD-1** [ADOPTED] — verbatim match to CLAUDE.md's "single most important invariant" paragraph. Correct.
- **AD-2** [ASSUMPTION] — CLAUDE.md states the ~1024px client downscale exists (Stack table) but never states the inference that it is *not* part of the AD-1 symmetry boundary; that's a genuine new architectural judgment call, correctly an assumption.
- **AD-3** [ASSUMPTION] — CLAUDE.md/AGENTS.md say sessions are HTTP-only cookies with server-side validation but never say *where* session state is persisted (Postgres vs. Redis vs. JWT). Correctly an assumption (though see Gap A for what's missing from it).
- **AD-5** [ASSUMPTION] — pgvector is ADOPTED (CLAUDE.md Stack table), but HNSW-vs-IVFFlat and "no manual reindex" are not stated anywhere in CLAUDE.md/AGENTS.md. Correctly an assumption.
- **AD-6** [ADOPTED] — reasonable: it's the direct architectural restatement of AGENTS.md's server-side-authz-on-every-endpoint policy plus the repo layout's clean web/api separation (web has no DB/storage credential). Correct.
- **AD-7** [ASSUMPTION] — AGENTS.md mandates content inspection + EXIF-strip + re-encode as policy, but the decision that Scan-submission and catalogue-image endpoints share *one* code path (vs. two independently-compliant implementations) is a new architectural choice. Correctly an assumption.

## 3. Stack table version/technology consistency check

Checked every spine Stack row against the CLAUDE.md Stack table for silent technology substitution (CLAUDE.md names no versions, so only technology identity was checked):

| Spine row | CLAUDE.md row | Match? |
|---|---|---|
| React 19.2.x | React PWA | Same tech, ok |
| TypeScript 5.x strict | TypeScript | Same tech, ok |
| Vite latest 6.x | Vite | Same tech, ok |
| Python 3.12+ | Python | Same tech, ok |
| FastAPI 0.141.x | FastAPI | Same tech, ok |
| ONNX Runtime 1.25.x (CPU) | ONNX Runtime (CPU inference) | Same tech, ok |
| DINOv2 backbone, ONNX-exported | DINOv2 backbone | Same tech, ok |
| PostgreSQL 17 | Postgres | Same tech, ok |
| pgvector 0.8.x | pgvector | Same tech, ok |
| Object storage: S3-compatible, provider deferred | S3-compatible | Same tech, correctly left open, ok |
| Password hashing: Argon2id | Argon2id | Same tech, ok (but see Gap A — the cookie half of this CLAUDE.md row is dropped) |

No silent substitutions found — every named technology in the spine matches CLAUDE.md's Stack table. The only stack-table discrepancies are omissions (Gap A's cookie clause, Gap B's Camera row), not substitutions.

## 4. Design Paradigm / Structural Seed / repo layout check

- Design Paradigm text and the mermaid diagram correctly enumerate `apps/web`, `apps/api`, `shared/vision`, `shared/schema`, `infra`, `scripts/ingest` — matches CLAUDE.md's Repo layout exactly, no missing or invented directories.
- Structural Seed's directory comments correctly reflect CLAUDE.md's domain vocabulary and known pitfalls (AD-1 binding called out inline for `shared/vision`).
- No contradiction found between the Design Paradigm's hexagonal-flavored framing and CLAUDE.md/AGENTS.md (CLAUDE.md doesn't mandate a paradigm, so this is a legitimate new architectural decision, not a contradiction).

## Summary of concrete gaps

1. **Gap A (session cookie transport):** AGENTS.md's HttpOnly/Secure/SameSite=Strict/never-localStorage rule and CLAUDE.md's "HTTP-only session cookies" stack element are dropped from both the spine's Stack table and its ADs (AD-3 covers only session storage *location*, not transport).
2. **Gap B (Camera stack row):** CLAUDE.md's `Camera | getUserMedia, canvas downscale ~1024px` Stack row has no equivalent row in the spine's Stack table.
3. **Gap C (rate-limiting AD):** AGENTS.md's login-and-scan rate-limiting policy has no dedicated AD; it's only implied by a Capability Map cell and a Deferred-section aside about threshold values.
4. **Mis-tag (AD-4):** AD-4 is tagged wholly [ASSUMPTION], but its core rule (audit log is append-only, no update/delete path) is already AGENTS.md policy and should be [ADOPTED]; only the DB-role-grant enforcement mechanism is a genuine new assumption.
5. Stack table technology identities all check out against CLAUDE.md — no silent substitutions.
