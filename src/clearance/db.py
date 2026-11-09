"""Async database engine/session helpers.

Postgres + pgvector in production (``make up``); tests pass a SQLite URL so the
suite runs with no external services under ``OFFLINE=1``.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from clearance.config import settings


def make_engine(url: str | None = None, *, echo: bool = False) -> AsyncEngine:
    """Create an async engine. Defaults to ``settings.database_url``."""
    return create_async_engine(url or settings.database_url, echo=echo, future=True)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
