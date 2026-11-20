"""CP-26 (ADR-0012, M11.3): feed requests.

A user who reads items asks for a feed that is not in the catalogue, with an https URL and a
reason. The server never fetches the URL for a request; an editor checks it by creating the
source through the source editor (every check, DNS included), then approves the request with
that source, which joins the catalogue and is followed by the requester. Or the editor
declines it, with a note. The requester may withdraw it while it is pending.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-20
"""

from __future__ import annotations

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE feed_request ("
        " id uuid PRIMARY KEY DEFAULT uuidv7(),"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " updated_at timestamptz NOT NULL DEFAULT now(),"
        ' requested_by uuid NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,'
        " url text NOT NULL,"
        " reason text NOT NULL,"
        " status text NOT NULL DEFAULT 'pending'"
        "  CHECK (status IN ('pending','approved','declined','withdrawn')),"
        ' decided_by uuid REFERENCES "user"(id),'
        " decided_at timestamptz,"
        " decision_note text,"
        " source_id uuid REFERENCES source(id),"
        " CHECK (status <> 'approved' OR source_id IS NOT NULL))"
    )
    op.execute("CREATE INDEX feed_request_requester_idx ON feed_request (requested_by, status)")
    op.execute("CREATE INDEX feed_request_status_idx ON feed_request (status, created_at)")
    op.execute(
        "CREATE TRIGGER trg_feed_request_updated BEFORE UPDATE ON feed_request "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON feed_request TO regwatch_app")


def downgrade() -> None:
    op.execute("DROP TABLE feed_request")
