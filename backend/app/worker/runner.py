"""Claim pending collection jobs with SKIP LOCKED and run governed collection."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from app.config import get_settings
from app.database.session import create_engine_from_settings, create_session_factory
from app.domain.models import FareQuery
from app.observability.logging import configure_logging
from app.services.container import build_container
from app.services.seeding import seed_if_needed

logger = logging.getLogger("apix.worker")


def _mark_healthy() -> None:
    try:
        Path("/tmp/apix-healthy").write_text("ok", encoding="utf-8")
    except OSError:
        Path("apix-healthy").write_text("ok", encoding="utf-8")


async def run_once() -> bool:
    settings = get_settings()
    engine = create_engine_from_settings(settings)
    factory = create_session_factory(engine)
    claimed = False
    async with factory() as session:
        await seed_if_needed(session)
        container = build_container(session, settings)
        job = await container.jobs.claim_pending()
        if job is None:
            await session.commit()
            await engine.dispose()
            return False
        query = FareQuery.model_validate(job.query_json)
        result = await container.collection.execute(job, query, request_id=job.request_id)
        await session.commit()
        claimed = True
        logger.info("job %s %s", job.id, result.status.value)
    await engine.dispose()
    return claimed


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    _mark_healthy()
    while True:
        try:
            worked = await run_once()
        except Exception:
            logger.exception("collection worker cycle failed")
            worked = False
        if not worked:
            await asyncio.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    asyncio.run(main())
