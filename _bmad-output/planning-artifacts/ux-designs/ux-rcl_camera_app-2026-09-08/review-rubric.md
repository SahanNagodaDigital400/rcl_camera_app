# Spine Pair Review — Rocell Tile Scanner

## Overall verdict

The spine pair is source-extractable with high fidelity: all three `sources:` paths resolve, all three PRD User Journeys are mirrored in Key Flows with named protagonists and climax beats, the PRD Glossary carries over verbatim, and both files match their canonical shapes exactly (DESIGN.md section order identical to the shadcn example; EXPERIENCE.md carries every required default plus a correctly-triggered Responsive & Platform section, correctly omits Inspiration & Anti-patterns). The prior reconciliation pass's 7 fixes all hold under re-check — none regressed. Remaining gaps are narrow but real: one IA surface (Force Password Change) has zero behavioral/state definition anywhere in EXPERIENCE.md despite gating every first login; two components carry different names in DESIGN.md vs. EXPERIENCE.md (a residual side-effect of the reconciliation pass that added the DESIGN.md tokens); three components are defined on only one side of the pair; and load-bearing contrast ratios remain explicitly unverified. None of these block a downstream consumer outright, but each should be closed before story-dev reaches the affected surface.

## 1. Flow coverage — strong
Checked all 3 PRD UJs against EXPERIENCE.md Key Flows (lines 105–136). All three present, each with a named protagonist, numbered steps, and an explicit **Climax:** beat, and each correctly tagged "mirrors PRD UJ-N."
### Findings
- **low** Flow 3 (Ruwan, lines 130–136) has no failure/edge-case path, unlike Flow 1 (line 118) and Flow 2 (line 128) — the FR-13 "last remaining Administrator can't be deactivated" refusal case would be a natural edge branch here and is currently undocumented at the flow level (it only exists as an FR consequence). Fix: add a one-line edge case to Flow 3 covering the last-admin refusal.

## 2. Token completeness — adequate
Checked every YAML frontmatter token (colors, typography, rounded, spacing, components) and every `{path.to.token}` reference in both files' prose. All resolve; no color token is missing a hex value.
### Findings
- **medium** No contrast ratio is stated for any load-bearing color combination (white-on-orange accent buttons, navy-on-cream chrome) in DESIGN.md §Colors (145–154). EXPERIENCE.md's Accessibility Floor (line 103) explicitly flags this as unverified rather than silently omitting it, which is the right move, but the gap is still open in the current file content. Fix: run the contrast check before Finalize and either update the tokens or record passing ratios inline.

## 3. Component coverage — adequate
Cross-checked every component name in DESIGN.md `Components` (frontmatter + prose, 68–188) against EXPERIENCE.md `Component Patterns` (55–70).
### Findings
- **medium** "Data table row" (EXPERIENCE.md line 65, used for User List and Catalogue) has no DESIGN.md visual entry. DESIGN.md's Card bullet (line 178) covers "a table row on mobile" but the primary desktop-admin case (dense multi-column tables per Responsive & Platform, line 141) has no defined row background/border/hover/selected treatment. Fix: add a `data-table-row` token or explicitly state it inherits Card styling on desktop too.
- **medium** "Audit log row" and "Flagged-activity row" (EXPERIENCE.md lines 69–70) have no DESIGN.md counterpart at all. This is sharper for the flagged row specifically: EXPERIENCE.md states it is "distinguished only by a visual flag indicator," but no token anywhere defines what that indicator looks like (color, icon, badge). Fix: add both rows to DESIGN.md, and give the flag indicator an explicit token (e.g. reuse `upload-report-row`'s `flagged-indicator: accent` pattern).
- **low** Role badge and Status badge (DESIGN.md `badge-role-admin`/`badge-role-staff`/`badge-status-deactivated`, lines 94–106, prose 180–181) have no corresponding row in EXPERIENCE.md's Component Patterns table. Likely trivial (non-interactive, display-only) but per the pairing contract it should still have a one-line behavioral row. Fix: add a row, even if the rule is simply "display-only, no interaction."

## 4. State coverage — adequate
Walked all 13 IA surfaces against EXPERIENCE.md's State Patterns table (74–85).
### Findings
- **high** "Force Password Change" (IA row, line 25) has zero coverage anywhere downstream of the IA table — no Voice and Tone entry, no Component Pattern, no State Pattern row, no Key Flow reference — despite gating every first-time user per FR-2/Story 1.2. This is the same class of gap the prior reconciliation pass already fixed once for Account Settings; it wasn't caught for this surface. Fix: add at minimum a validation-error state (weak/mismatched password) and a success-transition state.
- **medium** Scan History (IA row, line 29) has no "empty history" state (new user, zero scans yet) — the table covers "no confident match" and "empty catalogue search" as analogous empty-state patterns elsewhere but skips this one. Fix: add a row analogous to the Catalogue empty-search treatment.
- **medium** Results (IA row, line 28) has states for "Processing" and "No confident match" (77–78) but none for a submission/matching failure (network error, server error, timeout on the scan endpoint itself) — distinct from "no confident match," which assumes matching succeeded but scored low. Fix: add an explicit Results-surface error state with a retry path.

## Mechanical notes

- **Sources resolve.** All three EXPERIENCE.md `sources:` paths (prd.md, ARCHITECTURE-SPINE.md, epics.md) point to the exact files reviewed; no broken references.
- **UJ/Glossary inheritance is verbatim.** PRD UJ-1/2/3 protagonists, climaxes, and edge cases map cleanly onto Flows 1–3; Glossary terms (Product, Design, Size, Face, Code, Candidate, Scan, Catalogue) are used identically across PRD, architecture spine, and both UX files.
- **Component naming drift (inheritance discipline — adequate, not strong):**
  - **medium** DESIGN.md names the component `inline-message-retake` / "Inline message (retake)" (frontmatter 116–120, prose 185); EXPERIENCE.md's Component Patterns table calls the same thing "Retake prompt" (line 64). Same component, two names — a source-extracting consumer grepping by name won't find the DESIGN.md spec from the EXPERIENCE.md name.
  - **medium** DESIGN.md names the component `upload-report-row` / "Upload report row" (frontmatter 126–131, prose 187); EXPERIENCE.md calls it "Per-row upload report" (line 67). Same drift pattern.
  - Both mismatches trace to the prior reconciliation pass, which added the missing DESIGN.md tokens but didn't align their display names to what EXPERIENCE.md already called them (per `.memlog.md`'s fix-6 note). Fix: pick one name per component and use it verbatim in both files.
- **Token references resolve cleanly.** `{typography.code}`, `{spacing.2}`–`{spacing.3}`, and every `{colors.*}`/`{rounded.*}` reference checked resolves to a defined frontmatter token in both directions.
- **Shape fit — strong.** DESIGN.md section order (Brand & Style → Colors → Typography → Layout & Spacing → Elevation & Depth → Shapes → Components → Do's and Don'ts) matches the canonical example exactly. EXPERIENCE.md carries all required defaults, correctly includes a populated Responsive & Platform section (multi-surface product), and correctly omits Inspiration & Anti-patterns (not triggered — no reference products or rejected patterns in scope).
- **Visual reference coverage — not yet reached, as expected.** No mockups/wireframes exist yet; both files correctly note composition references are "produced at Finalize" and that the spine wins on conflict. This is scoped-for, not a defect.
- **Bloat — strong.** No padding found; every section in both files carries concrete, citation-backed decisions (FR/AD/UJ references throughout) rather than generic filler.
