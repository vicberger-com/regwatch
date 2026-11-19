"""M5 per-language search (Q1; ``schema.sql``: "Language-specific configurations are applied in
a per-language expression index by M5; 'simple' is the baseline").

One partial GIN index per stemmed language on the title and summary, for items of that
language; ``search.query`` matches with the same expression, so these indexes serve it.

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

# language code prefix: PostgreSQL text search configuration (search.query.STEMMED)
LANGUAGES = {"en": "english", "de": "german", "fr": "french", "es": "spanish",
             "pt": "portuguese"}  # fmt: skip
DOCUMENT = "coalesce(title, '') || ' ' || coalesce(summary, '')"


def upgrade() -> None:
    for code, config in LANGUAGES.items():
        op.execute(f"CREATE INDEX ix_item_fts_{code} ON item USING gin "
                   f"(to_tsvector('{config}'::regconfig, {DOCUMENT})) "
                   f"WHERE language LIKE '{code}%'")  # fmt: skip


def downgrade() -> None:
    for code in LANGUAGES:
        op.execute(f"DROP INDEX ix_item_fts_{code}")
