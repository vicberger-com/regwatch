"""BL-148 (CP-40, review finding 2): how each session was signed in.

``auth.mfa_required`` exempts sessions signed in through the organisation's provider, which
holds their second factor; a password session is covered whether or not the account is
linked. Existing sessions count as password sessions.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-21
"""

from __future__ import annotations

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE session ADD COLUMN method text NOT NULL DEFAULT 'password' "
               "CHECK (method IN ('password', 'sso'))")  # fmt: skip


def downgrade() -> None:
    op.execute("ALTER TABLE session DROP COLUMN method")
