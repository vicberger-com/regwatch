"""Database engine and declarative base (SQLAlchemy 2.0 over asyncpg).

``REGWATCH_DATABASE_URL`` follows docs/contracts/env.example (``postgresql://`` or
``postgresql+psycopg://``). The application uses the asyncpg driver (Apache-2.0), so
:func:`async_url` rewrites the scheme; the rest of the URL is passed through unchanged.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import MetaData
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


def install_sessions(state: object, url: str) -> None:
    """Give an app (``app.state``) a session factory; the engine connects on first use."""
    state.sessions = async_sessionmaker(create_engine(url), expire_on_commit=False)  # type: ignore[attr-defined]


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """One session per request; writes commit explicitly, anything uncommitted rolls back."""
    factory: async_sessionmaker[AsyncSession] = request.app.state.sessions
    async with factory() as session:
        yield session


Session = Annotated[AsyncSession, Depends(get_session)]
