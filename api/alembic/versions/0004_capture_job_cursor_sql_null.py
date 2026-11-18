"""CP-14 fix: "no cursor" is SQL NULL, never the JSON value ``null``.

Clearing ``capture_job.cursor`` through the ORM stored JSON ``null``, which the worker's
conditional update (``cursor IS NULL``) never matched, so after a settings change a job's cursor
was never written again (found in the web listing re-verification). The column now maps
``None`` to SQL NULL; this turns any stored JSON ``null`` into SQL NULL. No schema change.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-18
"""

from __future__ import annotations

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE capture_job SET cursor = NULL WHERE cursor = 'null'::jsonb")


def downgrade() -> None:
    pass  # SQL NULL and JSON null meant the same: nothing to undo
