"""The migration applier, and nothing else.

`infra` holds no business logic. This package reads the `.sql` files in
`infra/migrations/`, applies each unapplied one inside its own transaction
together with its ledger row, and can step one back. The single exception to
"plain SQL only" is the seeded Administrator: an Argon2id digest cannot be
computed in SQL, so that migration's `up` file is a marker the runner
recognises as "call `rocell_infra.seed` inside this transaction".

Nothing here is imported by `apps/api` or `apps/web`. It runs at the console,
from `make migrate`.
"""
