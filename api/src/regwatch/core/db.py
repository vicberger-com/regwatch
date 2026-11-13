"""Database engine and declarative base (SQLAlchemy 2.0 over asyncpg).

``REGWATCH_DATABASE_URL`` follows docs/contracts/env.example (``postgresql://`` or
``postgresql+psycopg://``). The application uses the asyncpg driver (Apache-2.0), so
:func:`async_url` rewrites the scheme; the rest of the URL is passed through unchanged.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import DateTime, MetaData
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

_SCHEMES = ("postgresql+psycopg://", "postgresql+asyncpg://", "postgresql://", "postgres://")


class Base(DeclarativeBase):
    """Declarative base for every module's models; tables are created by Alembic, never here."""

    metadata = MetaData()
    # Every timestamp column in schema.sql is timestamptz.
    type_annotation_map = {datetime: DateTime(timezone=True)}


def async_url(url: str) -> str:
    """Return ``url`` with its scheme set to SQLAlchemy's asyncpg dialect."""
    for scheme in _SCHEMES:
        if url.startswith(scheme):
            return "postgresql+asyncpg://" + url[len(scheme) :]
    raise ValueError("database URL must start with postgresql:// or postgresql+psycopg://")


def create_engine(url: str, *, poolclass_null: bool = False) -> AsyncEngine:
    """Create an async engine; ``poolclass_null`` suits one-shot commands (migrate, seed)."""
    if poolclass_null:
        return create_async_engine(async_url(url), poolclass=NullPool, hide_parameters=True)
    # hide_parameters keeps bound values (emails, password hashes) out of error messages and
    # therefore out of logs (8.2; review finding 7).
    return create_async_engine(async_url(url), pool_pre_ping=True, hide_parameters=True)


# Privileges that would let the login rewrite history (8.1: the app role cannot alter audit).
# Checked for every role the login is a member of, whether or not it inherits (a NOINHERIT
# member can still SET ROLE), at table and at column level (re-review 6c). Superusers, the
# table owner and the schema owner can alter or drop it, so they fail the check too.
_AUDIT_CAN_MUTATE = """
SELECT EXISTS (
  SELECT 1 FROM pg_roles r
  WHERE pg_has_role(current_user, r.oid, 'MEMBER')
    AND (r.rolsuper
         OR has_table_privilege(r.oid, 'audit_log', 'UPDATE')
         OR has_table_privilege(r.oid, 'audit_log', 'DELETE')
         OR has_table_privilege(r.oid, 'audit_log', 'TRUNCATE')
         OR has_any_column_privilege(r.oid, 'audit_log', 'UPDATE')
         OR pg_has_role(r.oid, (SELECT relowner FROM pg_class
                                WHERE oid = 'public.audit_log'::regclass), 'MEMBER')
         -- the schema owner can drop the table (final review L1)
         OR pg_has_role(r.oid, (SELECT nspowner FROM pg_namespace
                                WHERE nspname = 'public'), 'MEMBER'))
)
"""


async def audit_log_is_append_only(engine: AsyncEngine) -> bool:
    """True when no role the engine's login can use may alter ``audit_log`` (BL-61).

    Raises if the table does not exist (an unmigrated database).
    """
    from sqlalchemy import text

    async with engine.connect() as conn:
        can_mutate = await conn.scalar(text(_AUDIT_CAN_MUTATE))
    return not can_mutate


def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request from the app's factory."""
    factory: async_sessionmaker[AsyncSession] = request.app.state.db
    async with factory() as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(get_db)]
