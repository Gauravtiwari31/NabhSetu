from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.router import api_router
from app.config import get_settings
from app.database.base import Base
from app.database.immutability import install_immutability_guards
from app.database.models import *  # noqa: F403
from app.database.session import create_engine_from_settings, create_session_factory
from app.database.timescale import install_hypertables
from app.observability.logging import configure_logging
from app.observability.middleware import RequestLoggingMiddleware
from app.services.seeding import seed_if_needed


async def _prepare_schema(engine: AsyncEngine) -> None:
    dialect = engine.dialect.name
    async with engine.begin() as connection:
        if dialect == "sqlite":
            await connection.run_sync(Base.metadata.create_all)
            await connection.run_sync(install_immutability_guards)
            return
        await connection.run_sync(install_immutability_guards)
        await connection.run_sync(install_hypertables)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    engine = create_engine_from_settings(settings)
    factory = create_session_factory(engine)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = factory
    await _prepare_schema(engine)
    async with factory() as session:
        await seed_if_needed(session)
        from app.pipeline.run_index import IndexPublisher
        from app.database.repositories.observations import ObservationRepository
        from app.database.repositories.publication import PublicationRepository

        publisher = IndexPublisher(settings, ObservationRepository(session), PublicationRepository(session))
        await publisher.ensure_versions()
        await session.commit()
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        description="Nabhsetu airfare price index. Mock observations and published series are labelled as simulated.",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list() or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_middleware(RequestLoggingMiddleware)

    # Liveness ping for uptime monitors and the Render health check. It is
    # deliberately dependency-free and deliberately NOT /health: the real
    # /health lives on api_router, touches the database, and reports
    # data_mode and is_simulated. Registering a bare /health here would be
    # matched first and would hide that.
    @application.get("/healthz", tags=["system"])
    def liveness():
        return {"status": "ok"}

    application.include_router(api_router)
    return application


app = create_app()
