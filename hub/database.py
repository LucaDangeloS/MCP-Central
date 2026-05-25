"""Async SQLAlchemy engine + session factory."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from hub.config import get_settings


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


def _make_engine() -> AsyncEngine:
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    db_url = settings.db_url
    connect_args: dict[str, object] = {}
    if db_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False, "timeout": 30}

    created_engine = create_async_engine(
        settings.db_url,
        echo=settings.debug,
        connect_args=connect_args,
        pool_pre_ping=True,
    )
    if db_url.startswith("sqlite"):
        _configure_sqlite_engine(created_engine.sync_engine)
    return created_engine


def _configure_sqlite_engine(sync_engine: Any) -> None:
    @event.listens_for(sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection: Any, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()


engine = _make_engine()

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a DB session and closes it after the request."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Create all tables (used only in tests and first-run bootstrap)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
