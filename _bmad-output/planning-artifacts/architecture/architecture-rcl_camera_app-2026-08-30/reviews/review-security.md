---
review-of: ARCHITECTURE-SPINE.md
lens: security (pre-pentest architectural review)
reviewer: Claude (subagent)
date: 2026-08-30
---

# Security Review — Architecture Spine, Rocell Tile Identification App

## Verdict

**Conditional pass — sound skeleton, real gaps.** The spine gets the hard structural call right (AD-6's dependency direction, AD-4's DB-grant-level audit immutability, AD-3's live role re-read) and those are exactly the invariants that make server-side authz enforceable rather than aspirational. But it is not yet a foundation that survives an independent pentest. Six gaps below are the kind a pentest specifically hunts for: two (presigned-URL upload/download bypass, spoofable audit source_ip) are structural holes a competent implementer could fall into *without violating the letter of any stated AD*. The others are places where AGENTS.md states a requirement but the spine's ERD/Stack/AD set gives it no enforcement point, so it depends entirely on every future developer remembering, with nothing in the structure to catch a lapse — the same failure mode AD-1 and AD-4 were explicitly designed to close for their own concerns.

None of this blocks Foundation-build start; all of it should be resolved (as new ADs or ERD fields) before the pentest is scheduled, since several of these are exactly what an external tester's first hour would probe.

---

## Findings

### 1. [HIGH] AD-6 does not foreclose presigned direct-to-storage URLs — the most likely real-world violation of its own intent

**Where:** AD-6 ("Web talks only to the API"), AD-7 (shared upload-intake path), the dependency diagram.

**The gap:** AD-6's rule is written in terms of *credentials*: "`apps/web` holds no database or storage credential." A presigned upload URL is not a credential apps/web *holds* — it's a short-lived, single-object-scoped token *apps/api* mints per request and hands back. Nothing in AD-6's text, or in the diagram's `web -.x.-> obj forbidden` edge, actually rules this out — the diagram shows *credentialed* access as forbidden, not *token-authorized* access, and those are different things to anyone implementing against this doc literally.

This matters because presigned S3-style upload URLs are the standard PWA pattern for exactly the reason this app needs them: bandwidth. `apps/web` already downscales to ~1024px client-side (AD-2) precisely to shrink upload payload — a natural next optimization is "skip proxying the bytes through `apps/api`, upload straight to storage." If that pattern is adopted, the image bytes never pass through `apps/api`, which means they never pass through AD-7's shared upload-intake function — no content-type sniff, no re-encode, no EXIF strip. AD-7's own rule ("no code path writes an image to object storage without passing through it first") is phrased in terms of *code paths in the app*; a client PUT-ing directly to a presigned URL isn't a code path in the app at all, so AD-7 doesn't catch this either. Both AGENTS.md's "never accept uploads validated by extension — inspect content, strip EXIF, re-encode" and PRD §6's "every uploaded or scanned image is stripped of EXIF... before storage" would be silently violated by a change that looks, on its face, compliant with AD-6.

The same failure mode exists in reverse for **reads**: if `apps/api` issues presigned GET URLs so `apps/web` fetches reference images directly from storage (avoiding proxying studio-asset bytes through the API), then anyone who obtains that URL — leaked via referrer, browser history, shared link, long TTL — gets the proprietary catalogue image with no per-request role check at all, defeating the entire authenticated-session model for the asset that AGENTS.md identifies as the primary commercial threat (catalogue exfiltration).

**What a pentester does:** Inspects the upload/fetch network calls for any `PUT`/`GET` that doesn't target `apps/api`'s own origin; if found, tests whether the presigned URL/object key is guessable, long-lived, or reusable, and whether the uploaded bytes retain EXIF or bypass re-encoding.

**Fix:** Add an explicit rule — as strong as AD-6's existing wording — that closes the loophole by mechanism, not just by credential: *"No client ever receives a presigned or otherwise directly-usable object-storage URL, for read or write, at any tier. All image bytes flow synchronously through an `apps/api` request in both directions; `apps/api` is the only actor with network reachability to object storage."* This should be a rule addition to AD-6 or AD-7, not left implicit, precisely because the implicit reading currently permits the opposite.

---

### 2. [HIGH] No edge/trust-boundary component in the diagram — audit-log `source_ip` and anomaly-flagging location are likely spoofable

**Where:** The dependency diagram (no reverse proxy, TLS-termination point, or edge layer shown at all — `web` connects straight to `api`); ERD `AUDIT_LOG_ENTRY.source_ip`; AD-8 / FR-22 (anomaly flagging keyed partly on "logins from unexpected locations").

**The gap:** FR-20 requires every audit entry to carry a source IP, and FR-22's anomaly detection explicitly flags "logins from unexpected locations" — both load-bearing on `source_ip` being *authoritative*. But the architecture never states where the trust boundary for client IP sits. If `apps/api` runs behind any reverse proxy, load balancer, or CDN (which any real deployment will have, even if the provider itself is deferred per the spine's own "Deferred" section), the client's real IP arrives only via a header (`X-Forwarded-For`/`X-Real-IP`) that the client can also set directly on a request that reaches the proxy — unless the proxy is configured to strip and re-set it, and unless `apps/api` is told to trust only the proxy's socket peer, not arbitrary header content. Nothing in the spine assigns ownership of that trust decision anywhere — not to `infra`, not to `apps/api`'s auth module, not as an AD.

**What a pentester does:** Sends a login (or scan) request with a forged `X-Forwarded-For` header and checks whether the resulting audit-log entry or anomaly-flag location reflects the forged value. This is a five-minute check and, if it succeeds, it undermines the "who/what/when/source IP" accountability guarantee (FR-20) that AGENTS.md calls the primary control against credential sharing — an attacker using a shared/compromised account could make every audit trail entry point at a fabricated location, and evade FR-22's location-anomaly detection entirely by spoofing a "normal" IP.

**Fix:** Add an AD (or extend AD-8) stating the trust boundary explicitly: which layer terminates TLS, that `apps/api` derives `source_ip` only from the trusted proxy's immediate peer address (or a header populated exclusively by an internal, non-client-reachable proxy), and that this is deployment-invariant regardless of which hosting provider the "Deferred" section eventually names. This also closes a secondary gap: nothing in the Stack table states HTTPS/TLS is enforced end-to-end, which the `Secure` cookie flag (AD-3) silently depends on.

---

### 3. [HIGH] ERD's `USER` entity has no field for forced-password-change / temp-credential-expiry state — FR-2's server-side gate has no data model to enforce against

**Where:** ERD `USER { uuid id, string role, bool active }`; AD-3 (governs §4.1 per the capability map, but only addresses session storage/liveness, not credential state); AGENTS.md: *"Never skip the forced password change on an admin-issued temporary credential before granting further access; temporary credentials expire after 72 hours."*

**The gap:** FR-2 and AGENTS.md both require that a user issued a temporary credential (FR-11) can reach *only* the password-change screen until they replace it, and that the credential stops working after 72 hours unclaimed. That is a server-side authorization gate on every other endpoint, not a UI redirect — exactly the class of control AGENTS.md's own policy warns must never be UI-only. But the ERD, which is this spine's structural seed for the domain model, gives `USER` no `must_change_password` (or equivalent) flag and no `temp_credential_issued_at`/`expires_at` field. AD-3's per-request re-read pattern is the right *mechanism* for this (it already re-reads `role` and `active` every request to make FR-12/FR-13 take effect immediately) — but the spine never extends that same re-read to a password-change-pending flag, because the ERD doesn't carry one to re-read.

**What a pentester does:** Authenticates with a freshly issued temporary credential, then — instead of following the password-change redirect — calls another authenticated endpoint (e.g., the scan endpoint, or a catalogue read) directly. If it succeeds, the forced-password-change control was client-side only. Separately, tests whether a temp credential still authenticates after 72 hours.

**Fix:** Add `must_change_password: bool` and `credential_issued_at: timestamp` (or `temp_credential_expires_at`) to `USER` in the ERD, and extend AD-3's rule text to state that the session-lookup function also re-reads this flag every request and rejects any endpoint but the password-change one while it's set — mirroring exactly how AD-3 already treats `role`/`active`.

---

### 4. [MEDIUM-HIGH] `scripts/ingest`'s trust boundary and invocation model are unstated — it holds direct DB/storage credentials with no described authz gate

**Where:** Dependency diagram (`ingest --> pg`, `ingest --> obj`, direct, no intermediary); Design Paradigm text ("the offline batch adapter for bulk/initial load").

**The gap:** `scripts/ingest` is architecturally granted the same direct-to-Postgres and direct-to-object-storage access the diagram explicitly forbids `apps/web` from having (AD-6) — which is fine *if* it is genuinely an operator-run, network-unreachable CLI process, as the "batch adapter" framing implies. But the spine never states that as an invariant. It doesn't say `scripts/ingest` has no network listener, is never invoked by `apps/api`, and holds credentials distinct in scope from the API's runtime role. FR-17 ("Bulk upload," an in-app, Administrator-triggered, role-gated action) is separately assigned to `apps/api` in the Capability → Architecture Map — which is good — but the *coexistence* of an in-app bulk-upload path (properly gated by AD-3's per-request role check) and an out-of-band script with unmediated infra credentials, described in almost the same terms ("bulk/initial load"), is exactly the kind of ambiguity that invites someone to later wire the two together for convenience (e.g., "large bulk uploads dispatch to the ingest script asynchronously") — at which point a privileged write path exists that never passes through AD-3's authz check at all.

**What a pentester (or a build reviewer) does:** Asks "what triggers `scripts/ingest`, from where, and under what credential — and can any authenticated web request reach it directly or indirectly?" The spine currently has no answer.

**Fix:** Add a rule (an AD, or an explicit line under AD-6/AD-7's scope) stating `scripts/ingest` is operator-invoked only, is never triggered by `apps/api` or any network-reachable path, and its Postgres/object-storage credentials are provisioned separately from and are not obtainable via any `apps/api` code path or secret the API process can read.

---

### 5. [MEDIUM] Session-token storage at rest is unspecified — no equivalent of Argon2id for the session table

**Where:** AD-3 ("Sessions are rows in a Postgres table..."); ERD (no `SESSION` entity fields shown at all, only the relationship `USER ||--o{ SESSION : holds`); Stack table (Argon2id named explicitly for passwords, nothing named for session tokens).

**The gap:** The spine is admirably specific that passwords are Argon2id-hashed — but says nothing about whether the *session token value* stored in the `sessions` table is hashed (e.g., SHA-256 of the cookie value, with only the hash persisted and compared) or stored raw. If raw, then any read access to that table — a SQLi that gets past the parameterized-query policy, a leaked backup, an over-privileged read replica, an insider with SELECT access — yields directly usable session tokens for every currently-live user, i.e., full account takeover with no cracking cost, which is a materially worse outcome than a password-hash leak. AD-4 sets a precedent of enforcing sensitive-table integrity at the DB-grant layer for exactly this class of risk (audit log); the same rigor isn't extended to the session table.

**Fix:** Add a line to AD-3: the cookie carries an opaque token; only a salted hash of it is stored in the `sessions` table; the lookup function hashes the incoming cookie value before comparing. Add the hash column (and no raw-token column) to the ERD's `SESSION` entity once one exists — currently the ERD doesn't even model `SESSION`'s fields, only the edge to `USER`.

---

### 6. [MEDIUM] Embedding vectors are a catalogue-exfiltration surface the spine never names as sensitive

**Where:** ERD `REFERENCE_IMAGE { uuid id, string code, vector embedding }`; AGENTS.md's own framing ("catalogue exfiltration via a compromised account is the primary commercial threat").

**The gap:** AGENTS.md and AD-8 both treat *scan volume* as the exfiltration vector worth rate-limiting (FR-23) — but the embedding vectors themselves, sitting in `pgvector` and returned (at least internally) from every similarity search, are a second, quieter exfiltration path: a bulk SELECT against `REFERENCE_IMAGE.embedding` (or a debug/catalogue-search endpoint that echoes raw vectors in a response for "did it match" transparency) hands an attacker a compact, complete representation of the entire catalogue without ever touching object storage or tripping FR-23's per-scan throttle, since a single query can pull thousands of rows. The spine's data-protection story covers images (AD-7: re-encode, EXIF-strip) and credentials (Argon2id, AD-3) but has no equivalent statement for embeddings as an asset class.

**Fix:** Add a line — to AD-5 or the Consistency Conventions table — that no `apps/api` response ever includes raw embedding vectors (only rank-ordered `Candidate` metadata: code, size, design, image reference), and that any bulk export/admin tooling against `REFERENCE_IMAGE` requires the same audit-logged, role-gated path as catalogue management generally.

---

## Secondary / lower-priority notes

- **Password-spray evasion:** FR-4's lockout (AD-8) is scoped per-account (10 failed attempts on *one* account). A password-spray attack (one common password tried across many accounts) never trips it. This is arguably a PRD-level gap (FR-4 itself is written per-account) rather than an architectural one, but AD-8's "shared counter logic" could structurally support an IP-or-account composite key without redesign — worth raising alongside Finding 2, since a spoofable source IP (Finding 2) would undermine an IP-keyed control anyway if added later.
- **DB role scoping beyond the audit table:** AD-4 scopes the application's DB grants tightly (INSERT/SELECT only) for the audit table specifically. Nothing generalizes this to `apps/api`'s *overall* runtime Postgres role (vs. a separate, more-privileged migration role) — worth a follow-up AD once schema ownership is decided, so a SQLi's blast radius is bounded by grants, not just by parameterized queries.
- **Object storage bucket privacy:** The Stack table defers the S3-compatible provider choice but never states the bucket(s) must be private with no public-read ACL. Low urgency given Finding 1's fix (no client ever gets a direct storage URL) would make bucket ACL moot either way — but worth stating explicitly once a provider is picked, as defense in depth.
- **Image retention/purge has no architectural home:** PRD §6 flags scan-image retention (~90 days suggested, not finalized) as an open constraint, but the spine's "Deferred" list doesn't mention it at all — no module is described as owning a purge job. Not itself a pentest finding, but a data-protection gap worth adding to Deferred so it isn't lost.

## What the spine gets right (for balance)

AD-6's dependency-direction rule, AD-3's live per-request role/active re-read (closing the FR-12/FR-13 immediate-revocation requirement structurally rather than by convention), and AD-4's DB-grant-level audit immutability are all exactly the right shape of control — each takes an AGENTS.md policy line and gives it a mechanism that survives a bug, not just a code review. Findings 3 and 5 above are asking for that same treatment to be extended to two places (temp-credential state, session-token storage) where it's currently missing; the pattern to copy already exists in this document.
