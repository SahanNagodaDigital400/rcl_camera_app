---
title: PRD Input Reconciliation — Brief/Addendum vs. PRD
created: 2026-08-25
scope: Qualitative substance check only (tone, reasoning, emphasis, risk framing, motivating scenarios) — NOT a missing-FR audit.
---

# Reconciliation: brief.md + addendum.md → prd.md

Sources read in full:
- `_bmad-output/planning-artifacts/briefs/brief-rcl_camera_app-2026-08-25/brief.md`
- `_bmad-output/planning-artifacts/briefs/brief-rcl_camera_app-2026-08-25/addendum.md`
- `_bmad-output/planning-artifacts/prds/prd-rcl_camera_app-2026-08-25/prd.md`

Per the reconciliation brief, items the PRD explicitly and deliberately defers to the brief/addendum by reference — the full 14-item risk register, full security requirement detail, and technology-choice reasoning (the PRD's own §0 states "technology choices live there, not here," which covers the brief's embedding-vs-classifier rationale) — are **not** flagged below even where the underlying reasoning is rich. Only content that appears to have been silently dropped, flattened, or stripped of its "why" is flagged.

---

## Findings

### 1. The brief's long-range "Vision" is dropped, not confirmed or struck — despite an explicit instruction to do one or the other

**Brief (`brief.md` §Vision, line 111):**
> [ASSUMPTION] As the reference index matures and accuracy data comes in from real showroom use, the same matching capability is a natural fit for adjacent internal problems beyond showroom identification — warehouse stock checks, returns processing, training new staff on the catalogue — without material rework, since the core (embedding index + admin-managed catalogue) doesn't change, only who's using it and where. **Confirm or strike this** — the source material doesn't state a multi-year vision explicitly.

This is a flagged assumption with an explicit call to action: a downstream reader (i.e., whoever writes the PRD) is supposed to either confirm this extensibility vision or explicitly strike it.

**PRD (`prd.md` §1 Vision):** The PRD has its own "Vision" section under the same heading, but it is an entirely different piece of content — a restatement of the core problem/solution narrative (staff pocket-knowledge, admin catalogue currency, penetration-test gate). It does not mention warehouse stock checks, returns processing, staff training, or the "adjacent problems" extensibility idea at all. It neither confirms nor strikes the brief's proposed vision.

Critically, the PRD's own §13 Assumptions Index — which is supposed to catalogue every `[ASSUMPTION]` tag for confirmation — does **not** list this one. The brief flagged an assumption for explicit resolution, and the PRD silently overwrote the section it lived in rather than carrying the open question forward. This isn't a stylistic rewrite; it's a disposition the brief asked for that never happened.

**Why this matters:** if Rocell stakeholders read only the PRD, they will never see that "should this extend to warehouse/returns/training" was ever on the table, and no one will ever formally strike it either — it just vanishes.

---

### 2. Top-1 accuracy is quietly dropped as a tracked success metric, along with the reasoning for tracking both

**Brief (`brief.md` §Success Criteria, line 84):**
> **Top-1 accuracy** and **top-3 accuracy** (the latter reflects real-world usefulness) — numeric targets set after the pilot.

The brief explicitly names two distinct metrics and explains *why both matter*: top-3 reflects what the user actually experiences (they see three candidates and pick), but top-1 is named too — presumably because it's the more direct signal of underlying match quality/model tuning, independent of the UX safety net that top-3 provides.

**PRD (`prd.md` §11 Success Metrics, SM-1):**
> **SM-1**: Top-3 accuracy — the correct Product appears among the returned candidates. Target set after the Phase 2 pilot (§8). Validates FR-7.

Only top-3 accuracy survives as a tracked metric. Top-1 accuracy is not mentioned anywhere in §11, nor in §12 Open Questions (open question #1 only says "Top-1/top-3 accuracy targets for SM-1" in passing, but SM-1 itself is defined as top-3 only — so top-1 has no metric ID and no owner). The reasoning for tracking both — top-3 for user-facing usefulness, top-1 presumably for engineering/tuning signal — is lost along with the metric itself.

**Why this matters:** whoever builds the pilot measurement harness will build only what SM-1 asks for. If top-1 accuracy quietly disappears, a real signal for how good the raw embedding match actually is (before the "does the user tolerate 3 tries" UX buffer) will not be systematically collected.

---

### 3. The "blocking dependency" reasoning behind the code/file-name decision is stripped down to a bare non-goal

**Addendum (`addendum.md` §Source Dataset — Current State, line 76):**
> **Decision already made:** the app returns the matched file name directly rather than building a `size + design → product code` mapping. **This removed what was previously the project's blocking dependency.** Where the file name is a proper code, staff get exactly what they need; where it's only a face number, the folder-derived size and design shown alongside still identify the product.

This is a significant piece of project history: a data-mapping requirement that used to block the whole project was resolved by *not* building it — a product-scope decision, not a technical one, and the addendum frames it as the thing that got the project unstuck.

**PRD (`prd.md` §9 Non-Goals, line 293):**
> Not a maintained `size + design → product code` mapping table — the returned Code is the cleaned Reference Image file name (§3).

The PRD states the resulting rule correctly but presents it as an ordinary scope exclusion, indistinguishable from any other non-goal in that list (no email sending, no ERP integration, etc.). The framing that this was **the** previously-blocking dependency, and that removing the requirement is what let the project proceed at all, is gone. A reader of the PRD alone would have no reason to know this line item was ever contentious or load-bearing for the project's viability — it reads as a routine design choice rather than the resolution of an existential scope risk.

---

### 4. The "at least two admin accounts" safeguard — and its reasoning — is absent from the User Management feature

**Addendum (`addendum.md` §Authorization, line 20):**
> At least two admin accounts required, so one lost account can't lock Rocell out of its own user management.

This is a specific, testable operational rule with a clear rationale: a single-admin system is a single point of failure for account recovery itself.

**PRD (`prd.md` §4.3 Admin — User Management, FR-10–FR-13):** No FR, consequence, or note anywhere in this feature addresses a minimum-admin-count safeguard. FR-13 ("Deactivate or delete user") lists a consequence about session revocation timing but says nothing about what happens if an admin attempts to deactivate or delete the last remaining Administrator account. Because this rule sits in the addendum's "Full Security Requirements" section, it's arguably covered by the PRD's general reference to `AGENTS.md` / addendum for "the complete standing rule set" (§5 Security) — but unlike password hashing or session-cookie flags (which are genuinely implementation detail), this is a product-behavior rule with a directly observable consequence in the admin UI (can FR-13 be executed against the second-to-last admin, or is it blocked?). As written, FR-13 is silent on it, and the reasoning ("can't lock Rocell out of its own user management") never surfaces in the PRD at all.

---

### 5. The self-corrective framing behind "top-3 with images" — that the original ask undersold what the tool needed to be — is lost

**Brief (`brief.md` §Why This Approach, line 35):**
> **Top 3 with images, not one bare code.** This is a direct response to a hard limit in the data, not a hedge: some products are visually identical from a photo alone... A staff member can verify a photo they don't recognize in under a second; they can't verify a code the same way. **This also means the "just return a code" framing in the original ask undersells what actually makes the tool usable.**

This passage does two things: (1) it grounds the top-3-with-images decision in a physical, unresolvable data limitation (not a modeling weakness — a plainer FR could make it sound like a "we couldn't get it more accurate" hedge), and (2) it explicitly notes that this design pushes back on the *original stakeholder request*, which apparently asked for a single code.

**PRD:** §1 Vision and FR-7 both capture the *what* well — "not as an opaque code to trust blind," "never displays fewer than the available candidates or a single 'confidence-gated' answer" — and §9 even has a dedicated non-goal for it. This is one of the better-preserved threads in the PRD. What's missing is narrower but real: the explicit callback to the original ask being insufficient. Without it, a reader can't tell that "return one code" was ever the starting brief for this feature, or that showing top-3 was a deliberate, reasoned override of that starting point rather than the default design. That's useful context for anyone (e.g., a stakeholder revisiting scope later) who might otherwise ask "why not just show one result to keep the UI simpler."

---

## Secondary / lower-confidence observations

These are weaker signals — worth a mention, not worth escalating to the top findings above.

- **"Security is a build requirement from day one, not a hardening pass at the end"** (`brief.md` line 64) — a statement about *when in the build* security must be treated as first-class, not just what the requirements are. The PRD's Vision (§1) captures the *stakes* ("gatekeeper to Rocell's full product catalogue and staff account list") but not this specific instruction about build sequencing/culture. Likely fine as an engineering-culture note rather than a product requirement, but it's the kind of line a security-conscious PM would want preserved verbatim for the architecture handoff.
- **"As new tile ranges launch, the burden of 'knowing the catalogue by memory' only grows"** (`brief.md` §Problem, line 23) — a forward-looking, worsening-over-time framing of the core problem. The PRD's Vision restates the present-tense problem but drops the "this only gets worse" trajectory, which was part of the original urgency argument.
- **"Domain match... matters more than any modelling decision"** (`addendum.md` §Target state for the reference set, line 99) — the addendum explicitly ranks the studio-vs-showroom photo domain gap above any matching-algorithm improvement. The PRD's risk table (§7) carries the risk itself ("pilot accuracy will overstate real-world accuracy") but not this explicit prioritization signal, which is exactly the kind of thing an engineering team might deprioritize in favor of tuning the matcher if it isn't stated plainly.
- **Lost/stolen device threat scenario** (`addendum.md` §Threat notes, line 49) — named explicitly as a scenario motivating session expiry/revocation. The PRD keeps the mechanism (FR-3, FR-13) but not the concrete threat scenario that motivated it.

---

## Contradictions

None found. Numeric and policy details that appear in both documents (12h inactivity / 7-day absolute session expiry, 72-hour temporary credential expiry, 90-day suggested image retention, <3s capture-to-result, 150–200 product pilot size, penetration-test gate before general rollout) are consistent between the brief/addendum and the PRD.

One near-miss worth noting: the brief's Executive Summary asserts the catalogue is "large (2,000+ codes)" as the stated justification for the embedding-search approach, while the brief's own Key Risks and the addendum's Open Questions cast real doubt on that figure (folder audit suggests only "hundreds" of size+design combinations). The PRD handles this well — it never restates "2,000+" as settled fact anywhere, and its own Open Questions (§12, item 2) preserves the uncertainty. Flagged here only as a documented non-issue, not a gap.
