"""CP-14: ``capture_job.cursor``, where an incremental job got to.

For ``api_feed`` jobs it holds the newest publication date the job has stored, so a run cut
short by its item limit or page cap continues there next time (API feed review R1, BL-94 (c)).
Written by the worker only; cleared when the source's settings change.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-17
"""

from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE capture_job ADD COLUMN cursor jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE capture_job DROP COLUMN IF EXISTS cursor")
