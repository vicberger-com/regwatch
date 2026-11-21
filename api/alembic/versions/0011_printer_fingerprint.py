"""CP-33 (BL-15, BL-145): a printer's optional pinned certificate fingerprint.

Office printers mostly carry self-signed certificates. ``tls_sha256`` pins one by the SHA-256
digest of its DER certificate (ippx ``TlsConfig.fingerprint``); without it, ``ipps://`` checks
the certificate as usual.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-21
"""

from __future__ import annotations

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE printer ADD COLUMN tls_sha256 text "
               "CHECK (tls_sha256 ~ '^[0-9a-f]{64}$')")  # fmt: skip


def downgrade() -> None:
    op.execute("ALTER TABLE printer DROP COLUMN tls_sha256")
