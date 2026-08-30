---
title: Rubric review of ARCHITECTURE-SPINE.md
reviewed_file: ../ARCHITECTURE-SPINE.md
reviewed_against:
  - good-spine checklist (6 items)
  - PRD: prd-rcl_camera_app-2026-08-25/prd.md
  - .memlog.md (this dir) — records 2 prior reconciliation passes already folded into current spine
date: 2026-08-30
---

# Review: ARCHITECTURE-SPINE.md vs. good-spine checklist

## Context / what was already fixed

Two reconciliation subagents already ran (vs. PRD, vs. AGENTS.md/CLAUDE.md) and their 8 fixes are confirmed present in the **current** file: AD-3 now carries live role/active re-read (FR-12/13) and cookie transport (`[ADOPTED, AGENTS.md Policy]`); AD-4 is split-tagged (`[ADOPTED rule / ASSUMPTION mechanism]`); AD-5 has the hard-delete rule for FR-15/16; AD-7 binds `scripts/ingest`; AD-8 exists for rate-limit/anomaly counters; the Stack table has a Camera row; Capability Map rows for FR-1–5, FR-10–13, FR-20–23 cite AD-3/AD-8. None of these are re-flagged below.

This review focuses on what survived those two passes or opened up as a consequence of their fixes.

## Verdict

**NEEDS REVISION.** The spine is close but has two connected high-severity gaps around `scripts/ingest`'s write path (audit-logging obligation, and a live self-contradiction about whether it goes through `apps/api`), plus a data-model interaction (hard-delete vs. scan history) and a silent operations dimension that the checklist explicitly asks to check for.

---

## 1. Real divergence points for epics/stories — fixed vs. missed

### Finding A (HIGH) — FR-20's catalogue-change audit obligation is architecturally unrouted for `scripts/ingest`, and even under-cited for `apps/api`

FR-20 requires **every** "user creation/modification/deactivation/deletion, and Catalogue change" to be logged with who/what/when/source IP. FR-17 (bulk upload) is explicitly a Catalogue change.

- AD-4's **Binds** line is `infra (Postgres roles), apps/api (audit-write path)` — `scripts/ingest` is not bound by it. Nothing in the spine says how a batch script (no HTTP request, no obvious "source IP", possibly no interactive "who") satisfies FR-20 for bulk-loaded products.
- The ERD reinforces this: `USER ||--o{ AUDIT_LOG_ENTRY` — every audit entry is attributed to a USER row. There's no stated identity a batch job writes audit entries as.
- Even setting `scripts/ingest` aside: the §4.4 Capability Map row (FR-14–19, the *apps/api*-mediated add/edit/remove path) cites only `AD-1, AD-5, AD-7` — **AD-4 is not cited**, unlike §4.1/§4.3/§4.5, which all correctly cite their audit-relevant AD. A builder reading only the map has no signal that FR-14/15/16 catalogue changes need to hit the audit-write path at all.

**Consequence:** two independently-built units (the FR-14–16 admin catalogue endpoints and the FR-17 bulk-ingest script) could each ship without audit entries for catalogue changes, directly undermining FR-20/21 and the stated primary control against catalogue exfiltration (§4.5 PRD description, AGENTS.md Policy).

**Fix direction:** add AD-4 to the §4.4 map row; extend AD-4's Binds/Rule to state how `scripts/ingest` writes audit entries (e.g., via the same shared audit-write function, attributed to an operator/service USER row, with `source_ip` null or a documented sentinel for offline runs).

### Finding B (HIGH) — Live self-contradiction: "all mutation flows through apps/api" vs. the diagram and Structural Seed

- Consistency Conventions table: *"All Postgres/object-storage mutation flows through `apps/api` (AD-6)."*
- AD-6's own Rule text: *"Every read or write — including image upload — goes through an authenticated `apps/api` endpoint."* (unscoped in that sentence; the web-only scoping is only in the next sentence and in the Binds line.)
- But the Design Paradigm mermaid diagram draws `ingest --> pg` and `ingest --> obj` as **direct** edges, and the Structural Seed says `scripts/ingest` "Calls shared/vision, shared/schema" — not `apps/api`.

This is the same document asserting both "all mutation goes through apps/api" and drawing/describing a mutation path that doesn't. This exact contradiction was flagged in `reconcile-prd.md` Gap 1 and partially addressed (AD-7 now binds `scripts/ingest` to the shared upload-intake function, which resolves the *validation* half) — but the Consistency Conventions row and AD-6's rule sentence were never reworded, so the contradiction itself is still live in the current file.

**Fix direction:** reword the Consistency Conventions row and AD-6's first Rule sentence to scope explicitly to `apps/web`-initiated mutation (e.g., "All `apps/web`-initiated Postgres/object-storage mutation flows through `apps/api` (AD-6); `scripts/ingest` writes directly, through the shared upload-intake path (AD-7)").

### Finding C (MEDIUM-HIGH) — AD-5's hard-delete rule has no stated interaction with FR-8 Scan History

AD-5: *"Removal is a hard delete from the embedding index, not a soft-delete flag... there is no filter to forget."* FR-8: a user can view past scans "each with the result shown at scan time," and per FR-15, a removed/replaced Reference Image must never resurface as a *new* Candidate — but says nothing about *historical* Candidates.

If a `REFERENCE_IMAGE` row a past `SCAN`'s Candidate points to is later hard-deleted (FR-15/16), nothing in the spine says what FR-8 renders for that old scan: cascade-delete the historical Candidate, snapshot code/size/design/image into the Scan/Candidate record at scan time, or block deletion while history references it. These are materially different data models. This is exactly the class of thing AD-5 exists to fix for the *forward* direction (insert/search) but leaves open for the *removal* direction against history.

**Fix direction:** extend AD-5 (or add a short rule) stating whether Candidate history is a live FK to `REFERENCE_IMAGE` (and what happens on delete) or a denormalized snapshot taken at scan time.

### Finding D (LOW-MEDIUM) — AD-7's shared upload-handling function has no stated home

AD-7 mandates "one shared upload-handling function" used by `apps/api`'s two endpoint families and `scripts/ingest`. The Structural Seed lists only `shared/vision/` and `shared/schema/` as shared modules — it doesn't say whether upload-handling (content-sniff → re-encode → EXIF-strip) lives inside `shared/vision`, alongside it as an unlisted module, or elsewhere. Low risk given AD-7's rule is otherwise clear, but worth a one-line fix so `scripts/ingest`'s actual import path isn't guessed independently by two builders.

## 2. AD Rule enforceability

AD-1, AD-2, AD-3, AD-4, AD-5 (forward direction), AD-6 (as scoped to web), AD-7, AD-8 all read as concretely enforceable (code review / DB grant / schema check each map to a specific rule). The only enforceability problem found is Finding B: AD-6's rule text, read plainly, is **not actually true** given the rest of the document — a rule that contradicts the diagram it sits next to isn't enforceable as written, only as re-interpreted.

## 3. Deferred — anything that could let two units diverge incompatibly?

The four existing Deferred items (hosting/provider/CI-CD, S3 provider, OQ-13 thresholds, embedding-model upgrade strategy) are all safe to defer as written — each either blocks on an explicit external owner or has its enforcement point already fixed elsewhere in the spine.

**What's missing from Deferred, not what's wrongly in it:** see §4.5/Finding E below — the scan-image retention/purge *mechanism* should be here (mirroring how OQ-13 handles thresholds: module ownership fixed now, value deferred) but isn't mentioned at all.

## 4. Named tech vs. memlog verification

Checked every Stack table row against `.memlog.md`'s verification line:

| Spine row | memlog verification | Match |
|---|---|---|
| React 19.2.x | "19.2.x (latest patch 19.2.8, Aug 2026)" | Match |
| FastAPI 0.141.x | "0.141.1 (Jul 2026, pre-1.0 by design)" | Match |
| pgvector 0.8.x | "0.8.1/0.8.2, tested on Postgres 16 and 17" | Match |
| PostgreSQL 17 | "Pinning Postgres 17 (pgvector-tested current major)" | Match |
| ONNX Runtime 1.25.x | "1.25.0 (Apr 2026, 1.26 scheduled after)" | Match |

No mismatches or silent substitutions. **Note (low severity, not a top finding):** TypeScript 5.x, Vite 6.x, Python 3.12+, DINOv2/ONNX-export, Argon2id, S3-compatible have no corresponding memlog verification line at all — either they were judged not to need a web check (plausible for unversioned/stack-identity rows) or they were simply skipped. The table doesn't distinguish "web-verified" rows from "carried over from CLAUDE.md, unversioned" rows, so a future reader can't tell which is which from the document alone.

## 5. PRD capability coverage

§4.1–§4.5 → FR-1–23 mapping is complete and accurate (confirmed correct in `reconcile-prd.md`, still correct now). Cross-cutting NFRs (§5 Performance/Security/Auditability/Availability/Accessibility) are substantively covered through the ADs, except the audit-log NFR gap in Finding A above.

## 6. Whole-dimension silence check (operational/environmental envelope)

The checklist specifically asks to check this. Deferred explicitly covers **deployment & environments** (hosting provider, dev/staging/prod, CI/CD) and **part of infra/provider strategy** (S3-compatible provider choice). It says nothing — not decided, not deferred, not flagged as an open question — about:

### Finding E (MEDIUM) — "Operations" is entirely silent, including a required (not just unsized) capability

- **Secrets management strategy** — AGENTS.md: "Never commit or hardcode secrets... environment or secret store only." Which, is undecided at the level a spine would normally at least name as deferred.
- **Postgres backup/DR** — Postgres holds the append-only audit log, which the PRD treats as the primary control against catalogue exfiltration and credential sharing (§4.5). A store with no stated backup/DR posture for a compliance-load-bearing table is a real operational gap, not just a "measure later" item.
- **Monitoring/observability/alerting** — not mentioned at all, even as deferred.
- **Scan-image retention/purge mechanism** (§6 Privacy: "retained for a bounded period, then purged automatically"). PRD OQ-7 correctly leaves the *duration* open — but the *mechanism* (a scheduled job? object-storage lifecycle rule? who runs it, where does it live?) is a real architectural component (potentially a new stack element — a job scheduler) that nothing in the spine assigns, unlike OQ-13's thresholds, which got their enforcement point fixed even though the values stayed open. This is the same pattern the spine already knows how to apply (module-owns-mechanism, value-stays-open) but didn't apply here.

None of these needs a full decision at this altitude, but per the checklist, a whole dimension left completely silent — rather than at minimum entered in Deferred/Open Questions — is itself the finding.

---

## Summary table

| # | Finding | Severity | Checklist item |
|---|---|---|---|
| A | FR-20 catalogue-change audit obligation unrouted for `scripts/ingest`; §4.4 map omits AD-4 entirely | HIGH | 1, 5 |
| B | "All mutation flows through apps/api" (Consistency Conventions + AD-6 text) contradicts the diagram/Structural Seed for `scripts/ingest` | HIGH | 1, 2 |
| C | AD-5 hard-delete has no stated interaction with FR-8 scan-history references to removed Reference Images | MEDIUM-HIGH | 1 |
| D | AD-7's shared upload-handling function has no stated module home | LOW-MEDIUM | 1 |
| E | Operations dimension (secrets, backup/DR, monitoring, retention-purge mechanism) entirely silent — not even in Deferred | MEDIUM | 6 |
| — | Stack table doesn't mark which rows were web-verified vs. carried over unversioned | LOW (note only) | 4 |
