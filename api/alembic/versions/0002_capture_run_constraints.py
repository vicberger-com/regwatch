"""CP-11: one job per source, one unfinished run per job, an index on unfinished runs.

The scheduler already keeps both rules under the job's row lock (ADR-0006 amendment 1); these
let the database enforce them too, so a future bug cannot start a source twice at once. The
partial index serves the per-minute sweep of abandoned runs and the hand-over of lost ones.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-17
"""

from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE capture_job ADD CONSTRAINT uq_capture_job_source UNIQUE (source_id)")
    op.execute(
        "CREATE UNIQUE INDEX uq_capture_run_unfinished ON capture_run(job_id) "
        "WHERE finished_at IS NULL"
    )
    op.execute(
        "CREATE INDEX ix_capture_run_open ON capture_run(created_at) WHERE finished_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_capture_run_open")
    op.execute("DROP INDEX IF EXISTS uq_capture_run_unfinished")
    op.execute("ALTER TABLE capture_job DROP CONSTRAINT IF EXISTS uq_capture_job_source")
