"""CP-21 (M5 Q1; accepted under the owner's standing instruction of 2026-11-19 to take the
default recommendations): ``item.search_vector_stemmed``, a stored generated tsvector of title
and summary in the item's own language's configuration (english, german, french, spanish,
portuguese; ``simple`` otherwise), with a GIN index.

``schema.sql`` reserved "a per-language expression index"; an expression index made every
ranked candidate recompute ``to_tsvector`` at query time (M5 slice 2 review S3: 8-word and
phrase searches past 5 s on 55,000 items), so the vector is stored instead.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-19
"""

from __future__ import annotations

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

DOCUMENT = "coalesce(title, '') || ' ' || coalesce(summary, '')"
CONFIGS = (("en", "english"), ("de", "german"), ("fr", "french"), ("es", "spanish"),
           ("pt", "portuguese"))  # fmt: skip
# The simple lexemes and the stems of the item's own language, in one vector, so one GIN index
# and one combined query serve every language (the 1M-item load test, BL-118).
STEMMED = (f"to_tsvector('simple'::regconfig, {DOCUMENT}) || CASE "
           + " ".join(f"WHEN language LIKE '{c}%' THEN to_tsvector('{g}'::regconfig, {DOCUMENT})"
                      for c, g in CONFIGS)
           + " ELSE ''::tsvector END")  # fmt: skip


def upgrade() -> None:
    op.execute(f"ALTER TABLE item ADD COLUMN search_vector_stemmed tsvector "
               f"GENERATED ALWAYS AS ({STEMMED}) STORED")  # fmt: skip
    op.execute("CREATE INDEX ix_item_search_stemmed ON item USING gin (search_vector_stemmed)")


def downgrade() -> None:
    op.execute("DROP INDEX ix_item_search_stemmed")
    op.execute("ALTER TABLE item DROP COLUMN search_vector_stemmed")
