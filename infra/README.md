# infra

IaC, database migrations, and deployment config. No business logic
lives here (ARCHITECTURE-SPINE.md Design Paradigm).

This directory is intentionally empty as of Story 1.1 (project
scaffold). Future contents:

- `migrations/` -- forward-only, reversible Postgres migrations
  (AGENTS.md Conventions), starting with Story 1.2's schema. Never
  edit an applied migration.
- Deploy config for `apps/web` and `apps/api`, once a hosting
  provider is chosen.
- The Postgres role/grant setup backing AD-4 (audit-log table has
  INSERT/SELECT only, no UPDATE/DELETE grant at the database level).

The following are explicitly out of scope for this story and are
tracked as Deferred in `ARCHITECTURE-SPINE.md`, not decided here:

- Hosting/deployment provider, environments (dev/staging/prod),
  CI/CD pipeline.
- S3-compatible object storage provider choice.
- Secrets management approach.
- Backup/DR strategy (including the audit log's own durability).
- Monitoring and observability stack.
- Retention-purge job mechanism.

No `make migrate` target exists yet -- it is added when Story 1.2
introduces the first migration.
