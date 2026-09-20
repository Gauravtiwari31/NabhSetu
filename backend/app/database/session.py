from __future__ import annotations

from sqlalchemy import create_engine as create_sync_engine
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.config import Settings


def normalize_database_url(url: str, *, sync: bool = False) -> str:
    parsed = make_url(url)
    driver = parsed.drivername
    if sync:
        if driver.startswith("postgresql"):
            return parsed.set(drivername="postgresql+psycopg").render_as_string(hide_password=False)
        if driver.startswith("sqlite"):
            return parsed.set(drivername="sqlite").render_as_string(hide_password=False)
        return url
    if driver == "postgresql":
        return parsed.set(drivername="postgresql+asyncpg").render_as_string(hide_password=False)
    if driver == "sqlite":
        return parsed.set(drivername="sqlite+aiosqlite").render_as_string(hide_password=False)
    return url


def create_engine_from_settings(settings: Settings, *, echo: bool = False) -> AsyncEngine:
    url = normalize_database_url(settings.require_database_url())
    kwargs: dict = {"echo": echo, "pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        kwargs["poolclass"] = StaticPool
        kwargs.pop("pool_pre_ping", None)
    return create_async_engine(url, **kwargs)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def create_sync_engine_from_url(url: str):
    return create_sync_engine(normalize_database_url(url, sync=True), future=True)
