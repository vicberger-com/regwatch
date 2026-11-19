"""CP-20: two indexes (owner approved 2026-11-19; BL-114 (a), BL-107 (a)).

- ``change_event(item_id, severity)``: every search page reads its items' events, and the
  severity filter tests them (M5 search review finding 6).
- ``item(source_id, content_hash)``: ingest's same-source duplicate check (M4 pipeline review
  finding 11).

Indexes only; no data changes.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-19
"""

from __future__ import annotations

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE INDEX ix_change_event_item ON change_event(item_id, severity)")
    op.execute("CREATE INDEX ix_item_source_content ON item(source_id, content_hash)")


def downgrade() -> None:
    op.execute("DROP INDEX ix_item_source_content")
    op.execute("DROP INDEX ix_change_event_item")
