"""One-cell live demo: EaseMyTrip DEL-BOM T+7, then publish APIx-T.

Does not fabricate fares. A blocked or empty source is recorded as-is.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import date, timedelta
from pathlib import Path

os.environ["APIX_DATA_MODE"] = "live"
os.environ.setdefault("APIX_EGRESS_MODE", "direct")
os.environ.setdefault("APIX_ENVIRONMENT", "live-demo")
os.environ.setdefault("APIX_API_KEY", "change-me")
os.environ.setdefault("APIX_COMPLIANCE_LEASE_SECONDS", "180")
os.environ.setdefault("APIX_MAX_ADAPTER_RETRIES", "0")
os.environ.setdefault("APIX_PLAYWRIGHT_TIMEOUT_MS", "60000")
os.environ.setdefault("APIX_LIVE_PAYLOAD_MAX_BYTES", "2097152")
os.environ.setdefault("APIX_HTTP_TIMEOUT_SECONDS", "45")
os.environ.setdefault("APIX_DATABASE_URL", "sqlite+aiosqlite:///./data/apix-live-demo.db")

from app.config.settings import get_settings  # noqa: E402
from app.database.base import Base  # noqa: E402
from app.database.immutability import install_immutability_guards  # noqa: E402
from app.database.models import *  # noqa: F403,E402
from app.database.session import create_engine_from_settings, create_session_factory  # noqa: E402
from app.database.timescale import install_hypertables  # noqa: E402
from app.domain.models import FareQuery  # noqa: E402
from app.observability.logging import configure_logging  # noqa: E402
from app.services.container import build_container  # noqa: E402
from app.services.seeding import seed_if_needed  # noqa: E402
from app.sources.ota.catalog import EASE_MY_TRIP  # noqa: E402

REPORT_PATH = Path("data/live-demo-report.json")
ORIGIN = "DEL"
DESTINATION = "BOM"
LEAD = 7


async def run() -> dict:
    get_settings.cache_clear()
    settings = get_settings()
    configure_logging(settings.log_level)
    observation = date.today()
    query = FareQuery(
        origin=ORIGIN,
        destination=DESTINATION,
        observation_date=observation,
        travel_date=observation + timedelta(days=LEAD),
        lead_time_days=LEAD,
        source_id=EASE_MY_TRIP.spec.source_id,
    )
    engine = create_engine_from_settings(settings)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.run_sync(install_immutability_guards)
        await connection.run_sync(install_hypertables)
    factory = create_session_factory(engine)
    browser = None
    payload: dict = {}
    try:
        async with factory() as session:
            await seed_if_needed(session, settings)
            container = build_container(session, settings)
            browser = container.browser
            job_id, result = await container.collection.submit(query, request_id="live-demo")
            observations = await container.observations.list_for_job(job_id)
            publication = None
            publish_error = None
            try:
                published = await container.publisher.publish()
                publication = {
                    "headline_points": len(published.headline),
                    "cell_points": len(published.cells),
                }
            except ValueError as exc:
                publish_error = str(exc)
            await session.commit()
            payload = {
                "observation_date": observation.isoformat(),
                "data_mode": settings.data_mode.value,
                "source": EASE_MY_TRIP.spec.name,
                "query": f"{ORIGIN}-{DESTINATION} T+{LEAD}",
                "job_id": str(job_id),
                "result_status": result.status.value,
                "is_simulated": result.is_simulated,
                "observation_count": len(observations),
                "errors": [error.model_dump(mode="json") for error in result.errors],
                "publication": publication,
                "publish_error": publish_error,
                "database_url": settings.require_database_url(),
            }
            return payload
    finally:
        if browser is not None:
            await browser.close()
        await engine.dispose()


def main() -> None:
    payload = asyncio.run(run())
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
