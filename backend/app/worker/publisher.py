"""Quality-gate observations and publish versioned APIx series."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from app.config import get_settings
from app.database.session import create_engine_from_settings, create_session_factory
from app.observability.logging import configure_logging
from app.services.container import build_container
from app.services.seeding import seed_if_needed

logger = logging.getLogger("apix.publisher")


def _mark_healthy() -> None:
    try:
        Path("/tmp/apix-healthy").write_text("ok", encoding="utf-8")
    except OSError:
        Path("apix-healthy").write_text("ok", encoding="utf-8")


async def publish_once() -> None:
    settings = get_settings()
    engine = create_engine_from_settings(settings)
    factory = create_session_factory(engine)
    async with factory() as session:
        await seed_if_needed(session)
        container = build_container(session, settings)
        try:
            result = await container.publisher.publish()
            await session.commit()
            logger.info("published %s periods", len(result.headline))
        except ValueError as exc:
            await session.commit()
            logger.warning("publication skipped: %s", exc)
    await engine.dispose()


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    _mark_healthy()
    while True:
        try:
            await publish_once()
        except Exception:
            logger.exception("publisher cycle failed")
        await asyncio.sleep(settings.publisher_interval_seconds)


if __name__ == "__main__":
    asyncio.run(main())
