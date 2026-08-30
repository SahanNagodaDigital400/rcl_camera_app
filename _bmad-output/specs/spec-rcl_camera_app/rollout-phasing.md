# Rollout and Change Management

0. **Dataset consolidation** — migrate reference images to a Rocell-owned store, audit coverage and naming. Prerequisite for a realistic accuracy estimate, not a hard blocker on starting Phase 1.
1. **Foundation** — CAP-1 (auth), CAP-5 (audit), CAP-3 + CAP-4 (admin user/catalogue management), indexing pipeline.
2. **Scanning pilot** — CAP-2 against a 150–200 product pilot Catalogue. Internal accuracy testing sets the top-3/top-1 accuracy targets (`SPEC.md` Success signal).
3. **Full rollout** — full Catalogue ingestion, tuning from pilot findings, staff training. **Gated on an independent penetration test passing.**
4. **Refinement** — accuracy improvements from real scan data, reference-image backfill for weak products.
