"""Database engine and declarative base (SQLAlchemy 2.0 over asyncpg).

``REGWATCH_DATABASE_URL`` follows docs/contracts/env.example (``postgresql://`` or
``postgresql+psycopg://``). The application uses the asyncpg driver (Apache-2.0), so
:func:`async_url` rewrites the scheme; the rest of the URL is passed through unchanged.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

_SCHEMES = ("postgresql+psycopg://", "postgresql+asyncpg://", "postgresql://", "postgres://")


class Base(DeclarativeBase):
    """Declarative base for every module's models; tables are created by Alembic, never here."""

    metadata = MetaData()


def async_url(url: str) -> str:
    """Return ``url`` with its scheme set to SQLAlchemy's asyncpg dialect."""
    for scheme in _SCHEMES:
        if url.startswith(scheme):
            return "postgresql+asyncpg://" + url[len(scheme) :]
    raise ValueError("database URL must start with postgresql:// or postgresql+psycopg://")


def create_engine(url: str, *, poolclass_null: bool = False) -> AsyncEngine:
    """Create an async engine; ``poolclass_null`` suits one-shot commands (migrate, seed)."""
    if poolclass_null:
        return create_async_engine(async_url(url), poolclass=NullPool)
    return create_async_engine(async_url(url), pool_pre_ping=True)
