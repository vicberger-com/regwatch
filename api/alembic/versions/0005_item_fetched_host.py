"""CP-19: ``item.fetched_host``, the host the item's content was really fetched from.

An item's owner was decided by whichever source listed its URL first, so a feed's summary
could hold a regulator's page (M4 pipeline re-verification, finding N4). The column is set only
from a manifest row whose final URL is on the item's own host; an item whose content was never
fetched passes to the first source that fetches it. Existing items are treated as fetched from
their own host (re-verification 3): otherwise any source could take an unchanged one, since M3
hands a page over only when it changed.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-18
"""

from __future__ import annotations

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE item ADD COLUMN fetched_host text")
    op.execute(
        "UPDATE item SET fetched_host = regexp_replace(lower(rtrim(substring(canonical_url "
        "FROM '^https?://(?:[^@/]*@)?([^/:?#]+)'), '.')), '^www\\.', '') "
        "WHERE canonical_url ~ '^https?://'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE item DROP COLUMN fetched_host")
