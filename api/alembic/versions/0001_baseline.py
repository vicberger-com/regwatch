"""Baseline: everything in docs/contracts/schema.sql.

``0001_baseline.sql`` beside this file is a byte-for-byte copy of the contract at the time of
this revision. Two statements the contract describes only in comments are written out here:

* ``CREATE EXTENSION citext`` ("requires CREATE EXTENSION citext" on ``"user".email``);
* the ``set_updated_at()`` trigger on every table marked ``-- std`` ("Every table below gets
  ... a BEFORE UPDATE trigger calling set_updated_at()").

The application role ``regwatch_app`` gets read and write access to every table except
``audit_log``, where it gets INSERT and SELECT only (contract comment under ``audit_log``).
Roles are cluster-wide, so the downgrade revokes its grants but keeps the role.

Revision ID: 0001
Revises:
Create Date: 2026-11-02
"""

from __future__ import annotations

from pathlib import Path

from alembic import op
from sqlalchemy.util import await_only

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

APP_ROLE = "regwatch_app"

# Tables marked "-- std" in schema.sql; jurisdiction's trigger is written out in the file.
STD_TABLES = (
    '"user"', "role", "facet", "term", "source", "capture_job", "item", "regulation",
    "saved_view", "report_template", "report_layout", "printer", "output_job",
)  # fmt: skip

# Every table in schema.sql, in creation order (the downgrade drops them in reverse).
TABLES = (
    "jurisdiction", '"user"', "role", "permission", "role_permission", "user_role", "session",
    "facet", "term", "source", "capture_job", "capture_run", "item", "item_version",
    "regulation", "regulation_jurisdiction", "item_term", "item_jurisdiction", "change_event",
    "saved_view", "report_template", "report_layout", "printer", "output_job", "setting",
    "feature_flag", "audit_log",
)  # fmt: skip


def _trigger_name(table: str) -> str:
    return f"trg_{table.strip(chr(34))}_updated"


def _run_script(sql: str) -> None:
    """Run a multi-statement script through asyncpg's simple-query protocol.

    SQLAlchemy prepares every statement it sends, and a prepared statement holds one command,
    so the script goes to the driver connection directly, inside Alembic's transaction.
    """
    driver_connection = op.get_bind().connection.driver_connection
    await_only(driver_connection.execute(sql))


def upgrade() -> None:
    contract = (Path(__file__).with_name("0001_baseline.sql")).read_text(encoding="utf-8")
    triggers = "\n".join(
        f"CREATE TRIGGER {_trigger_name(t)} BEFORE UPDATE ON {t} "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
        for t in STD_TABLES
    )
    grants = f"""
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
    CREATE ROLE {APP_ROLE} NOLOGIN;
  END IF;
END $$;
GRANT USAGE ON SCHEMA public TO {APP_ROLE};
GRANT SELECT, INSERT, UPDATE, DELETE ON {", ".join(t for t in TABLES if t != "audit_log")}
  TO {APP_ROLE};
GRANT SELECT, INSERT ON audit_log TO {APP_ROLE};
GRANT SELECT ON jurisdiction_activity TO {APP_ROLE};
"""
    _run_script("CREATE EXTENSION IF NOT EXISTS citext;\n" + contract + triggers + grants)


def downgrade() -> None:
    drops = "\n".join(f"DROP TABLE {t};" for t in reversed(TABLES))
    _run_script(
        f"""
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {APP_ROLE};
REVOKE USAGE ON SCHEMA public FROM {APP_ROLE};
DROP MATERIALIZED VIEW jurisdiction_activity;
ALTER TABLE item DROP CONSTRAINT fk_item_regulation;
{drops}
DROP FUNCTION set_updated_at();
DROP FUNCTION uuidv7();
DROP EXTENSION citext;
DROP EXTENSION pg_trgm;
"""
    )
