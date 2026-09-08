---
status: final
created: 2026-09-08
updated: 2026-09-08
name: Rocell Tile Scanner
description: Internal staff PWA — camera-based tile identification plus admin catalogue/user management — for Rocell, a premium ceramic tile brand. Confident and brand-forward, but restrained enough for fast, repeated task completion.
colors:
  background: '#FAFAF8'
  surface: '#FFFFFF'
  primary: '#131B5E'
  primary-foreground: '#FFFFFF'
  accent: '#F58025'
  accent-foreground: '#131B5E'
  destructive: '#E30425'
  destructive-foreground: '#FFFFFF'
  border: '#ECE6DB'
  text: '#181830'
  muted-text: '#736F82'
typography:
  display:
    fontFamily: 'Plus Jakarta Sans'
    fontSize: 28px
    fontWeight: '800'
    lineHeight: '1.15'
    letterSpacing: -0.01em
  heading:
    fontFamily: 'Plus Jakarta Sans'
    fontSize: 18px
    fontWeight: '700'
    lineHeight: '1.3'
  body:
    fontFamily: 'Plus Jakarta Sans'
    fontSize: 16px
    fontWeight: '400'
    lineHeight: '1.5'
  label:
    fontFamily: 'Plus Jakarta Sans'
    fontSize: 14px
    fontWeight: '600'
    lineHeight: '1.4'
  caption:
    fontFamily: 'Plus Jakarta Sans'
    fontSize: 13px
    fontWeight: '500'
    lineHeight: '1.4'
  code:
    fontFamily: 'JetBrains Mono'
    fontSize: 14px
    fontWeight: '500'
    lineHeight: '1.4'
rounded:
  sm: 8px
  md: 12px
  lg: 16px
  full: 9999px
  DEFAULT: 12px
spacing:
  '1': 4px
  '2': 8px
  '3': 12px
  '4': 16px
  '5': 20px
  '6': 24px
  '8': 32px
  '10': 40px
  '12': 48px
  '16': 64px
components:
  button-primary:
    background: '{colors.accent}'
    foreground: '{colors.accent-foreground}'
    radius: '{rounded.sm}'
  button-secondary:
    background: 'transparent'
    foreground: '{colors.primary}'
    border: '{colors.primary}'
    radius: '{rounded.sm}'
  button-destructive:
    background: '{colors.destructive}'
    foreground: '{colors.destructive-foreground}'
    radius: '{rounded.sm}'
  card:
    background: '{colors.surface}'
    border: '{colors.border}'
    radius: '{rounded.md}'
  app-bar:
    background: '{colors.primary}'
    foreground: '{colors.primary-foreground}'
    accent-stripe: '{colors.accent}'
  candidate-card-best-match:
    background: '{colors.surface}'
    border: '{colors.accent}'
    radius: '{rounded.md}'
  badge-role-admin:
    background: '{colors.primary}'
    foreground: '{colors.primary-foreground}'
    radius: '{rounded.full}'
  badge-role-staff:
    background: 'transparent'
    foreground: '{colors.muted-text}'
    border: '{colors.border}'
    radius: '{rounded.full}'
  badge-status-deactivated:
    background: '{colors.destructive}'
    foreground: '{colors.destructive-foreground}'
    radius: '{rounded.full}'
  data-table-row:
    background: '{colors.surface}'
    background-hover: '{colors.background}'
    border: '{colors.border}'
    foreground: '{colors.text}'
  audit-log-row:
    background: '{colors.surface}'
    border: '{colors.border}'
    foreground: '{colors.muted-text}'
  flagged-activity-row:
    background: '{colors.surface}'
    border: '{colors.border}'
    flag-indicator: '{colors.accent}'
  framing-guide-overlay:
    border: '{colors.accent}'
    background: 'transparent'
    radius: '{rounded.md}'
  crop-selector:
    border: '{colors.accent}'
    handle-fill: '{colors.surface}'
    handle-border: '{colors.accent}'
    scrim: 'rgba(24, 24, 48, 0.55)'
  retake-prompt:
    background: '{colors.surface}'
    border: '{colors.border}'
    foreground: '{colors.text}'
    radius: '{rounded.sm}'
  force-password-change-form:
    background: '{colors.surface}'
    error-foreground: '{colors.destructive}'
    success-foreground: '{colors.primary}'
    submit-button: '{components.button-primary}'
  confirmation-dialog:
    background: '{colors.surface}'
    radius: '{rounded.lg}'
    scrim: 'rgba(24, 24, 48, 0.55)'
    confirm-button: '{components.button-destructive}'
  upload-report-row:
    background: '{colors.surface}'
    border: '{colors.border}'
    success-indicator: '{colors.primary}'
    failure-indicator: '{colors.destructive}'
    flagged-indicator: '{colors.accent}'
  save-indicator:
    foreground: '{colors.muted-text}'
    foreground-active: '{colors.primary}'
---

## Brand & Style

Rocell Tile Scanner is an internal tool with one job done twice a day, every day: point a phone at a tile, trust the answer fast; or sit at a desk and keep the catalogue honest. It is not the Rocell marketing site — that site is deliberately quiet, editorial, spacious, letting product photography carry the brand. This tool inverts that: the *brand* carries confidence up front (the navy chrome, the orange accent stripe — "Rocell Bold," picked from four rendered directions), and everything downstream of that first impression is fast, legible, and gets out of the way. Staff scanning in a showroom and admins working a dense user table are both moving quickly; nothing here should ask them to slow down and admire it.

Brand color discipline carries directly from the Rocell logo mark: **navy** is chrome (it frames the product, it doesn't compete with it), **orange** is the single call to action per screen, **red** means destructive and nothing else. This is the same two-colors-and-a-warning discipline good B2B tools use — Rocell's version just happens to start from a real, already-existing brand mark instead of an invented one.

No UI kit is inherited (the architecture spine pins React/Vite/TypeScript with no component library) — this is a from-scratch system. `[ASSUMPTION]` Implementing against Tailwind utility classes is a reasonable pairing for this token set given the stack, but that's an implementation choice, not a constraint this file imposes.

## Colors

- **Primary Navy (`#131B5E`)** — chrome only: the app bar, primary nav, the Administrator role badge. Never a call-to-action fill; navy asks for authority, not action.
- **Accent Orange (`#F58025`)** — the one action per screen that matters most: "Scan," "Add Product," "Save," "Confirm Crop." If a screen has two orange elements, one of them is wrong. Its foreground is **navy**, not white — see the contrast note below.
- **Destructive Red (`#E30425`)** — deactivate, delete, remove, reject. Never decorative, never a data-viz color, never reused for "urgent" or "attention" in a non-destructive sense. This is the one brand color with a hard behavioral contract.
- **Background (`#FAFAF8`) / Surface (`#FFFFFF`)** — warm off-white page, pure-white cards. Echoes the warmth of Rocell's own beige-toned product photography without literally using beige (which would read too close to "on brand for tiles" and compete with actual tile reference photos on screen).
- **Border (`#ECE6DB`)** and **Muted Text (`#736F82`)** — warm-neutral, never cool gray; keeps the whole system in one temperature.
- **Text (`#181830`)** — near-navy-black rather than pure black; ties body copy back to the brand without being colorful about it.

**Verified contrast (WCAG 2.x relative-luminance formula, computed against these exact hexes):**

| Pair | Ratio | Passes |
|---|---|---|
| White on Accent Orange | 2.63:1 | ✗ fails 4.5:1 — this is *why* `accent-foreground` is navy, not white |
| **Navy on Accent Orange** (`accent-foreground`) | **5.94:1** | ✓ passes 4.5:1 — also puts the logo's two dominant colors together on the primary button |
| White on Destructive Red | 4.87:1 | ✓ passes 4.5:1 |
| Navy Text on Background | 14.93:1 | ✓ passes with large margin |
| Muted Text on Background | 4.65:1 | ✓ passes 4.5:1, narrowly — don't darken the background or lighten muted-text without re-checking this pair |

Avoid: introducing a second accent hue, using orange for more than one action per screen, using red for anything short of an irreversible or access-revoking action, white text directly on `{colors.accent}`.

## Typography

Single family, **Plus Jakarta Sans**, across every role — chosen because it's explicitly suited to both ends of this product's split (B2B admin density and mobile field use), so staff on a phone and admins on a desktop read the same typographic voice. `display` is reserved for the single most important number or word on a screen (a scan result's top match, a screen title) — not used for body copy or table cells. `code` (`JetBrains Mono`) is `[ASSUMPTION]`, proposed specifically for product Codes (`RP.CMA.0001DJ.SM.0T`) so a staff member visually verifying a code against a physical tile has unambiguous character shapes (no 0/O or 1/I confusion) — not yet confirmed with a real user, flag if unwanted.

## Layout & Spacing

4px-based scale (`{spacing.1}` through `{spacing.16}`). Mobile-first: the scan flow is single-column, full-bleed on the camera/crop steps, comfortable thumb-reach spacing (`{spacing.4}`–`{spacing.6}`) elsewhere. Admin screens (user list, catalogue table) use denser spacing (`{spacing.2}`–`{spacing.3}` within table rows) since they're desktop-first and value scanability over generous whitespace — the one deliberate density split in the system, matched to who's using which surface.

## Elevation & Depth

One level of elevation, used sparingly: cards sit on the page with a soft, navy-tinted shadow (`0 2px 8px rgba(19, 27, 94, 0.08)`) rather than a gray one — a small, consistent way the brand shows up in depth, not just in color fills. No second elevation tier; a modal/sheet uses a scrim instead of a heavier shadow.

## Shapes

`{rounded.sm}` (8px) for buttons and inputs, `{rounded.md}` (12px) for cards, `{rounded.lg}` (16px) reserved for full-screen sheets (the crop tool, a mobile bottom sheet). `{rounded.full}` for badges and status pills only — never for buttons, which would read too consumer/playful for this register. This keeps "Bold" from tipping into "friendly consumer app."

## Components

Rendered reference for the components below: [`mockups/key-scan.html`](mockups/key-scan.html), [`mockups/key-crop.html`](mockups/key-crop.html), [`mockups/key-results.html`](mockups/key-results.html), [`mockups/key-user-list.html`](mockups/key-user-list.html). Those mocks illustrate; the tokens and rules in this file win on conflict.

- **Button (primary)** — `{colors.accent}` fill, **navy** text (`accent-foreground`, verified 5.94:1 — white fails at 2.63:1), `{rounded.sm}`. Exactly one per screen.
- **Button (secondary)** — navy outline, navy text, transparent fill. The default for every non-primary action (Edit, Cancel, Back).
- **Button (destructive)** — `{colors.destructive}` fill, white text. Requires a confirmation step before firing (see `EXPERIENCE.md` State Patterns) — the color alone isn't the safeguard.
- **App bar** — navy fill, white text/icons, a 3–4px `{colors.accent}` stripe along the bottom edge (the "Bold" variant's signature move). Present on every authenticated screen.
- **Card** — white surface, `{colors.border}` hairline, `{rounded.md}`, navy-tinted shadow. The base container for a scan candidate, a catalogue product, a table row on mobile.
- **Candidate card (best match)** — the top-ranked Candidate gets `{colors.accent}` as a 2px border instead of the neutral border, so the eye lands on it first without needing a "confidence score" label the PRD explicitly avoids.
- **Role badge** — Administrator: navy fill, white text, pill. Staff: outline only, muted text, pill. Deliberately asymmetric — Administrator should read as the heavier-weight role at a glance in a user list. Display-only, no interaction (see `EXPERIENCE.md` Component Patterns).
- **Status badge** — Active: outline, muted text. Deactivated: `{colors.destructive}` fill, white text, pill. Display-only, no interaction.
- **Data table row** — the desktop-admin case (User List, Catalogue at `md`+ breakpoints): `{colors.surface}` background, `{colors.background}` on hover, hairline `{colors.border}` between rows, no card wrapper or shadow — a table, not a stack of cards. Below that breakpoint it inherits Card styling per `EXPERIENCE.md`'s Responsive & Platform section.
- **Audit log row** — visually identical to a data table row, deliberately unremarkable — the read-only behavioral rule (no row-end menu, ever) lives in `EXPERIENCE.md`, not in how it looks.
- **Flagged-activity row** — an audit log row plus one addition: a small `{colors.accent}` dot/flag glyph in the leading cell. Orange here is a signal, not an action — the one exception to "orange means the primary action," justified because nothing on this row is clickable to begin with.
- **Icons** — Phosphor, `regular` (outline) weight throughout, 20–24px. No filled/duotone icons, no emoji.
- **Framing guide overlay** — `{colors.accent}` outline rectangle over the live camera viewfinder, `{rounded.md}` corners, transparent fill so the viewfinder stays visible underneath.
- **Crop selector** — `{colors.accent}` border on the active selection, white corner/edge handles with an accent border (large enough to satisfy the 44px touch-target floor), a dark scrim over the deselected area so the kept region reads unambiguously.
- **Retake prompt** — a quiet surface-colored banner, not a modal — sits directly above the primary action so "Retake" is one thumb-reach away.
- **Force password change form** — a single-field form (new password) using standard input styling; error text in `{colors.destructive}`, the "your password is set" success transition in `{colors.primary}`; submit button is `button-primary`. No navigation chrome around it — it's the only thing on screen until it's done.
- **Confirmation dialog** — `{rounded.lg}` sheet over a scrim, states the object and consequence in its body text, confirm action always uses `button-destructive` styling when confirming a destructive action (never the neutral primary button for a "yes, delete").
- **Per-row upload report** — one row per bulk-upload item; success uses a navy check, failure a red mark, flagged-for-review an orange marker — the only place all three brand colors appear as status indicators together, since it's the one screen genuinely reporting three distinct outcomes.
- **Save indicator** — muted-text label at rest, shifts to `{colors.primary}` on the "Saved." state — deliberately not orange (orange stays reserved for the action that hasn't fired yet, not the confirmation that it did).

## Do's and Don'ts

| Do | Don't |
|---|---|
| One orange action per screen | Two or more orange elements competing for attention |
| Red only for destructive/irreversible actions | Red as a generic "important" or "urgent" color |
| Navy for chrome and authority (app bar, admin badge) | Navy as a button fill for a primary action |
| Navy-tinted shadows on cards | Default gray box-shadow |
| Sharp-ish corners (8/12/16px) — reads "tool" | Pill-shaped buttons (reads "consumer app") |
| Phosphor outline icons at consistent weight | Mixed icon styles, filled icons, emoji as icons |
| Dense admin tables, spacious mobile scan flow | The same spacing scale forced onto both surfaces |
