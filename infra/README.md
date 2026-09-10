# infra

IaC, database migrations, and deployment config. No business logic
lives here (ARCHITECTURE-SPINE.md Design Paradigm).

## Migrations

`infra/migrations/` holds forward-only, reversible, tracked Postgres
migrations (AGENTS.md Conventions) -- plain Python modules run via `psycopg`,
not `.sql` files and not an ORM (SQLAlchemy/Alembic are deliberately
not used here -- see Story 1.2's Design Notes: seeding needs Argon2id
hashing, which plain SQL can't do). Never edit an applied migration;
add a new one instead.

Each migration file (`infra/migrations/NNNN_description.py`) defines
`up(cur)`. `infra/migrate.py` discovers pending migrations in
filename order, applies each inside its own transaction, and records
it in a `schema_migrations` table -- a second run is a no-op.

### Running migrations

```bash
make migrate
```

Required environment variables:

- `DATABASE_URL` -- Postgres connection string.
- `SEED_ADMIN_EMAIL`, `SEED_ADMIN_NAME`, `SEED_ADMIN_PASSWORD` -- the
  one Administrator account seeded by `0002_seed_administrator.py`.
  Never hardcode these (AGENTS.md; addendum.md) -- the migration
  aborts before writing anything if any of the three is unset. The
  seeded account is created with `must_change_password = true` and a
  72-hour temporary-credential window, so even the first sign-in is
  gated by Story 1.4.

### Testing

`infra/tests/test_migrate.py` runs against a real, disposable local
Postgres database -- `DATABASE_URL` must point at one. This is a new
prerequisite for `make test` project-wide now that DB-backed schema
exists.

## Not yet in scope

The following are explicitly out of scope for this story and are
tracked as Deferred in `ARCHITECTURE-SPINE.md`, not decided here:

- Hosting/deployment provider, environments (dev/staging/prod),
  CI/CD pipeline.
- S3-compatible object storage provider choice.
- Secrets management approach.
- Backup/DR strategy (including the audit log's own durability).
- Monitoring and observability stack.
- Retention-purge job mechanism.
- The Postgres role/grant setup backing AD-4 (audit-log table has
  INSERT/SELECT only, no UPDATE/DELETE grant at the database level).
