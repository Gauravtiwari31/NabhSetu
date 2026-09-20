from __future__ import annotations

import os

os.environ.setdefault("APIX_DATA_MODE", "mock")
os.environ.setdefault("APIX_EGRESS_MODE", "direct")
os.environ.setdefault("APIX_API_KEY", "test-api-key")
os.environ.setdefault("APIX_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("APIX_ENVIRONMENT", "test")

from collections.abc import AsyncIterator  # noqa: E402
from datetime import date, timedelta  # noqa: E402

import pytest  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.config.settings import get_settings  # noqa: E402
from app.database.base import Base  # noqa: E402
from app.database.immutability import install_immutability_guards  # noqa: E402
from app.database.models import *  # noqa: F403,E402
from app.domain.models import FareQuery  # noqa: E402
from app.services.container import AppContainer, build_container  # noqa: E402
from app.services.seeding import seed_if_needed  # noqa: E402

get_settings.cache_clear()


def make_query(**kwargs) -> FareQuery:
    observation = kwargs.pop("observation_date", date(2026, 9, 20))
    lead = kwargs.pop("lead_time_days", 7)
    travel = kwargs.pop("travel_date", observation + timedelta(days=lead))
    return FareQuery(
        origin=kwargs.pop("origin", "DEL"),
        destination=kwargs.pop("destination", "BOM"),
        observation_date=observation,
        travel_date=travel,
        lead_time_days=lead,
        **kwargs,
    )


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    get_settings.cache_clear()
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.run_sync(install_immutability_guards)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as db_session:
        await seed_if_needed(db_session)
        yield db_session
    await engine.dispose()


@pytest.fixture
async def container(session: AsyncSession) -> AppContainer:
    return build_container(session, get_settings())
