"""CP-25 (ADR-0012, M11.2): the curated feed catalogue and who follows it.

- ``source.catalogue_key``: the stable key of a source that came from ``seed/catalogue.yaml``;
  NULL for a source an admin added. The seed matches on it, so a re-run adds new entries and
  leaves admins' edits alone.
- ``source.summary``: one line on what the source covers, shown in the catalogue.
- ``source_follower``: users who follow a catalogue source. A source is captured while it is
  enabled, or while it is a catalogue source with at least one follower, and in both cases
  only while its job is enabled: an admin stops a followed source by disabling it
  (``DELETE /sources/{id}`` turns its job off). One fetch serves every follower.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-20
"""

from __future__ import annotations

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE source ADD COLUMN catalogue_key text UNIQUE")
    op.execute("ALTER TABLE source ADD COLUMN summary text")
    op.execute(
        "CREATE TABLE source_follower ("
        " source_id uuid NOT NULL REFERENCES source(id) ON DELETE CASCADE,"
        ' user_id uuid NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,'
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " PRIMARY KEY (source_id, user_id))"
    )
    op.execute("CREATE INDEX source_follower_user_idx ON source_follower (user_id)")
    # The grant every table but the audit log has (0001_baseline; checked against schema.sql).
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON source_follower TO regwatch_app")


def downgrade() -> None:
    op.execute("DROP TABLE source_follower")
    op.execute("ALTER TABLE source DROP COLUMN summary")
    op.execute("ALTER TABLE source DROP COLUMN catalogue_key")
