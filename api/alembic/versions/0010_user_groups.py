"""CP-27 (ADR-0012, M11.4): groups of users, with members and roles.

A group's roles apply to its members alongside their own. A group may not carry a role with
``users.manage`` or ``roles.manage``: those stay granted to each user directly, so the
last-manager guard and the review of who administers the application are unchanged. A group's
interest profile (``interests``) is the default for members who have not set their own
(M11.4b).

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-20
"""

from __future__ import annotations

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE user_group ("
        " id uuid PRIMARY KEY DEFAULT uuidv7(),"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " updated_at timestamptz NOT NULL DEFAULT now(),"
        " key text NOT NULL UNIQUE,"
        " name text NOT NULL,"
        " description text,"
        " interests jsonb NOT NULL DEFAULT '{}'::jsonb)"
    )
    op.execute(
        "CREATE TABLE group_member ("
        " group_id uuid NOT NULL REFERENCES user_group(id) ON DELETE CASCADE,"
        ' user_id uuid NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,'
        " PRIMARY KEY (group_id, user_id))"
    )
    op.execute("CREATE INDEX group_member_user_idx ON group_member (user_id)")
    op.execute(
        "CREATE TABLE group_role ("
        " group_id uuid NOT NULL REFERENCES user_group(id) ON DELETE CASCADE,"
        " role_id uuid NOT NULL REFERENCES role(id) ON DELETE CASCADE,"
        " PRIMARY KEY (group_id, role_id))"
    )
    op.execute(
        "CREATE TRIGGER trg_user_group_updated BEFORE UPDATE ON user_group "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON user_group, group_member, group_role "
        "TO regwatch_app"
    )


def downgrade() -> None:
    op.execute("DROP TABLE group_role")
    op.execute("DROP TABLE group_member")
    op.execute("DROP TABLE user_group")
