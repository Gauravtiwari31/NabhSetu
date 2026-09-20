from __future__ import annotations

import asyncio
import json
import os
from datetime import date
from pathlib import Path

os.environ["APIX_DATA_MODE"] = "live"
os.environ.setdefault("APIX_EGRESS_MODE", "direct")
os.environ.setdefault("APIX_ENVIRONMENT", "ota-live-run")
os.environ.setdefault("APIX_API_KEY", "ota-live-local")
os.environ.setdefault("APIX_COMPLIANCE_LEASE_SECONDS", "240")
os.environ.setdefault("APIX_MAX_ADAPTER_RETRIES", "0")
os.environ.setdefault("APIX_PLAYWRIGHT_TIMEOUT_MS", "60000")
os.environ.setdefault("APIX_LIVE_PAYLOAD_MAX_BYTES", "2097152")
os.environ.setdefault("APIX_HTTP_TIMEOUT_SECONDS", "45")
os.environ.setdefault("APIX_HTTP_CONNECT_TIMEOUT_SECONDS", "15")
os.environ.setdefault("APIX_DATABASE_URL", "sqlite+aiosqlite:///./data/apix-ota-live.db")

from app.acquisition.orchestrator import LiveRunOrchestrator  # noqa: E402
from app.config.settings import get_settings  # noqa: E402
from app.database.base import Base  # noqa: E402
from app.database.immutability import install_immutability_guards  # noqa: E402
from app.database.models import *  # noqa: F403,E402
from app.database.session import create_engine_from_settings, create_session_factory  # noqa: E402
from app.database.timescale import install_hypertables  # noqa: E402
from app.domain.enums import SourceType  # noqa: E402
from app.observability.logging import configure_logging  # noqa: E402
from app.services.container import build_container  # noqa: E402
from app.services.seeding import seed_if_needed  # noqa: E402

ROUTES = [("DEL", "BOM"), ("DEL", "BLR"), ("BOM", "BLR")]
OBSERVATION_DATE = date.today()
REPORT_PATH = Path("data/ota-live-run-report.json")


async def collect() -> dict:
    get_settings.cache_clear()
    settings = get_settings()
    configure_logging(settings.log_level)
    engine = create_engine_from_settings(settings)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.run_sync(install_immutability_guards)
        await connection.run_sync(install_hypertables)
    factory = create_session_factory(engine)
    browser = None
    try:
        async with factory() as session:
            await seed_if_needed(session)
            container = build_container(session, settings)
            browser = container.browser
            records = await LiveRunOrchestrator(container).run(
                routes=ROUTES,
                observation_date=OBSERVATION_DATE,
                source_types={SourceType.OTA},
            )
            return {
                "observation_date": OBSERVATION_DATE.isoformat(),
                "data_mode": settings.data_mode.value,
                "egress_mode": settings.egress_mode.value,
                "user_agent": settings.identified_user_agent,
                "routes": ["-".join(route) for route in ROUTES],
                "lead_times": [1, 7, 15, 30, 45],
                "results": [record.__dict__ for record in records],
                "observation_total": sum(item.observation_count for item in records),
                "simulated_total": sum(1 for item in records if item.is_simulated),
            }
    finally:
        if browser is not None:
            await browser.close()
        await engine.dispose()


def main() -> None:
    payload = asyncio.run(collect())
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
