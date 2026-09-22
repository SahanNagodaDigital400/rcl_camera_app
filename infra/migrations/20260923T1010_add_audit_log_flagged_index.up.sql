-- Story 3.7 — answers DW-135's "FR-22's anomaly work filters `action`":
-- `audit_log_created_at_idx` (`20260921T1000_create_audit_log.up.sql`) serves
-- the unfiltered chronological read, and `GET /admin/audit?flagged=true`
-- (`api/audit.py`) adds a second `WHERE` this migration gives its own index
-- rather than leaving it to scan the whole table.
--
-- **A partial index, not a second copy of the full one.** `WHERE action IN
-- (...)` only ever indexes the two flag actions — expected to stay a small
-- fraction of a table that only grows — so this index stays cheap for the
-- lifetime of a table nothing may prune (AD-4 grants no DELETE). The two
-- literal action strings are `AuditAction.LOGIN_ANOMALY_FLAGGED` and
-- `AuditAction.SCAN_VOLUME_ANOMALY_FLAGGED` (`shared_schema/audit.py`,
-- mirrored as `FLAGGED_AUDIT_ACTIONS`) — the column itself carries no CHECK
-- (`audit_log`'s own reason: the vocabulary grows every epic), so this
-- migration's own filter and the application's are two independent
-- spellings of the same two strings, which is why they are pinned in prose
-- here as well as in code.
--
-- Same `(created_at DESC, id DESC)` ordering as the full index, so a filtered
-- read gets an ordered index scan rather than a sort step.
--
-- No `GRANT` change: `audit_log`'s existing `SELECT, INSERT` grant
-- (`20260921T1000_create_audit_log.up.sql`) already covers a read through
-- any index on the table — an index is not a privilege boundary.
--
-- `IF NOT EXISTS`, matching every migration before it: a truncated ledger
-- must be able to replay the whole set.
--
-- Safe to apply and revert independently of `20260923T1000_create_
-- anomaly_baseline`: this index is read-side only and names no table this
-- story adds.

CREATE INDEX IF NOT EXISTS audit_log_flagged_idx
    ON audit_log (created_at DESC, id DESC)
    WHERE action IN ('login_anomaly_flagged', 'scan_volume_anomaly_flagged');
