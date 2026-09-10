"""Create the `users` table.

Columns per ARCHITECTURE-SPINE.md's USER ERD entity
(_bmad-output/planning-artifacts/architecture/architecture-rcl_camera_app-2026-08-30/ARCHITECTURE-SPINE.md:222-228)
plus the columns Story 1.3+ need (`name`, `email`, `password_hash`,
`created_at`). `role` is constrained to the two literal values
AGENTS.md Policy names -- never add a third.
"""

from __future__ import annotations

import psycopg


def up(cur: psycopg.Cursor) -> None:
    cur.execute(
        """
        CREATE TABLE users (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            name text NOT NULL,
            email text NOT NULL UNIQUE,
            password_hash text NOT NULL,
            role text NOT NULL CHECK (role IN ('staff', 'admin')),
            active boolean NOT NULL DEFAULT true,
            must_change_password boolean NOT NULL DEFAULT false,
            temp_credential_expires_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    # The column-level UNIQUE above is case-sensitive, so `Admin@x.com` and
    # `admin@x.com` could otherwise both be seeded/created as distinct rows.
    # Add a case-insensitive unique index on top of it.
    cur.execute(
        "CREATE UNIQUE INDEX users_email_lower_key ON users (lower(email))"
    )
