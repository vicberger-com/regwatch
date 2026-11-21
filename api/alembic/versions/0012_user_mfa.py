"""BL-148 (ADR-0007 G0 Q4): two-factor sign-in with TOTP for local accounts.

``user_mfa`` holds one authenticator per user: its secret encrypted with a key derived from the
application's secret key (``secret_enc``), when it was confirmed, the last time step used (a
code is never accepted twice), and the SHA-256 digests of the unused recovery codes.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-21
"""

from __future__ import annotations

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE user_mfa ("
        ' user_id uuid PRIMARY KEY REFERENCES "user"(id) ON DELETE CASCADE,'
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " secret_enc text NOT NULL,"
        " confirmed_at timestamptz,"
        " last_step bigint NOT NULL DEFAULT 0,"
        " recovery_hashes text[] NOT NULL DEFAULT '{}'"
        " CHECK (cardinality(recovery_hashes) <= 10))"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON user_mfa TO regwatch_app")


def downgrade() -> None:
    op.execute("DROP TABLE user_mfa")
