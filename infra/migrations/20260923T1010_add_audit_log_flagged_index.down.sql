-- Reverts 20260923T1010_add_audit_log_flagged_index.up.sql: drops the
-- partial index and nothing else. `GET /admin/audit?flagged=true` still
-- answers correctly without it — the index is a performance aid over the
-- same rows `_SELECT_LATEST_FLAGGED_ENTRIES` would otherwise sequentially
-- scan — so this step is safe to apply even while the application is
-- running, in either order relative to a code rollback.

DROP INDEX IF EXISTS audit_log_flagged_idx;
