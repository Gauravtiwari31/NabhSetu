"""Enqueue collection jobs for the active basket and lead-time windows."""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from pathlib import Path
from typing import Any

from app.config import DataMode, Settings, get_settings
from app.database.session import create_engine_from_settings, create_session_factory
from app.domain.enums import ALLOWED_LEAD_TIMES, SourceType
from app.observability.logging import configure_logging
from app.pipeline.method_config import load_basket
from app.services.container import build_container
from app.services.seeding import seed_if_needed

logger = logging.getLogger("apix.scheduler")


def select_scheduled_sources(
    profiles: list[Any],
    settings: Settings,
) -> list[Any]:
    """Enqueue only sources that are permitted for the active data mode."""
    allowlist = settings.scheduler_source_allowlist()
    selected: list[Any] = []
    for profile in profiles:
        if settings.data_mode == DataMode.MOCK:
            if profile.source_type != SourceType.MOCK or not profile.enabled:
                continue
        else:
            if profile.source_type == SourceType.MOCK:
                continue
            if not profile.enabled or not profile.automation_allowed or profile.temporarily_blocked:
                continue
        if allowlist and profile.name not in allowlist:
            continue
        selected.append(profile)
    return selected


def _mark_healthy() -> None:
    try:
        Path("/tmp/apix-healthy").write_text("ok", encoding="utf-8")
    except OSError:
        Path("apix-healthy").write_text("ok", encoding="utf-8")


async def enqueue_once() -> int:
    settings = get_settings()
    engine = create_engine_from_settings(settings)
    factory = create_session_factory(engine)
    created = 0
    async with factory() as session:
        await seed_if_needed(session, settings)
        container = build_container(session, settings)
        basket = load_basket(settings)
        routes = [tuple(item.split("-")) for item in basket.get("routes") or []]
        leads = tuple(int(item) for item in basket.get("lead_windows") or ALLOWED_LEAD_TIMES)
        observation = date.today()
        sources = select_scheduled_sources(await container.registry.list_all(), settings)
        if not sources:
            logger.warning("no permitted sources available to schedule")
        for profile in sources:
            for origin, destination in routes:
                queries = container.scheduler.expand(
                    origin=origin,
                    destination=destination,
                    observation_date=observation,
                    lead_times=leads,
                    source_id=profile.id,
                )
                for query in queries:
                    await container.collection.enqueue(query, request_id="scheduler")
                    created += 1
        await session.commit()
    await engine.dispose()
    logger.info("enqueued %s collection jobs", created)
    return created


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    _mark_healthy()
    while True:
        try:
            await enqueue_once()
        except Exception:
            logger.exception("scheduler cycle failed")
        await asyncio.sleep(settings.scheduler_interval_seconds)


if __name__ == "__main__":
    asyncio.run(main())
