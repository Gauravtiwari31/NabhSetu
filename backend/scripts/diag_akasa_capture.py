"""One-query production-path diagnostic for Akasa Playwright capture."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import date, timedelta

os.environ["APIX_DATA_MODE"] = "live"
os.environ.setdefault("APIX_EGRESS_MODE", "direct")
os.environ.setdefault("APIX_ENVIRONMENT", "live-diag")
os.environ.setdefault("APIX_API_KEY", "live-local-key")
os.environ.setdefault("APIX_PLAYWRIGHT_TIMEOUT_MS", "60000")
os.environ.setdefault("APIX_DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from app.acquisition.adapters.browser import BrowserRuntime  # noqa: E402
from app.acquisition.discovery.robots import fetch_robots  # noqa: E402
from app.config.settings import get_settings  # noqa: E402
from app.domain.enums import CollectorModality, ReviewStatus, SourceType  # noqa: E402
from app.domain.models import (  # noqa: E402
    FareQuery,
    SourceCapabilities,
    SourceNetworkPolicy,
    SourcePolicy,
    SourceProfile,
)
from app.sources.akasa.parser import parse_akasa  # noqa: E402
from app.sources.catalog import AKASA  # noqa: E402


async def main() -> None:
    get_settings.cache_clear()
    settings = get_settings()
    spec = AKASA.spec
    robots = await fetch_robots(settings, spec.base_url)
    source = SourceProfile(
        id=spec.source_id,
        name=spec.name,
        base_url=spec.base_url,
        source_type=SourceType.AIRLINE,
        enabled=True,
        automation_allowed=True,
        robots_status=robots.status,
        terms_review_status=ReviewStatus.APPROVED,
        capabilities=SourceCapabilities(
            static_html=True,
            embedded_json=True,
            requires_javascript=True,
            browser_network_json=True,
        ),
        policy=SourcePolicy(
            minimum_interval_seconds=8,
            maximum_concurrency=1,
            daily_request_limit=80,
            allowed_paths=["*"],
            blocked_paths=list(spec.blocked_paths),
        ),
        network_policy=SourceNetworkPolicy(),
    )
    observation = date(2026, 9, 20)
    query = FareQuery(
        origin="DEL",
        destination="BOM",
        observation_date=observation,
        travel_date=observation + timedelta(days=7),
        lead_time_days=7,
        source_id=spec.source_id,
    )
    plan = AKASA.browser_plan(query)
    runtime = BrowserRuntime(settings)
    try:
        capture = await runtime.capture(source, plan, robots, "diag")
        urls = [item.get("url") for item in capture.json_payloads if isinstance(item, dict)]
        observations = []
        payload_summaries = []
        for item in capture.json_payloads:
            body = item.get("body") if isinstance(item, dict) else item
            url = str(item.get("url") or "") if isinstance(item, dict) else ""
            parsed = parse_akasa(
                body,
                query,
                source,
                CollectorModality.PLAYWRIGHT_NETWORK,
                settings.confidence_playwright_network,
                url=url,
            )
            observations.extend(parsed.observations)
            if "availability" in url.lower():
                data = body.get("data") if isinstance(body, dict) else None
                summary = {"url": url[:180], "top_keys": list(body)[:12] if isinstance(body, dict) else type(body).__name__}
                if isinstance(data, dict):
                    trips = ((data.get("results") or [{}])[0].get("trips") or [])
                    summary["data_keys"] = list(data)[:12]
                    summary["faresAvailable"] = len(data.get("faresAvailable") or [])
                    summary["trips"] = [
                        {"date": trip.get("date"), "markets": len(trip.get("journeysAvailableByMarket") or [])}
                        for trip in trips[:3]
                    ]
                elif isinstance(data, list) and data:
                    summary["calendar_rows"] = len(data)
                    summary["sample"] = {"date": data[0].get("date"), "price": data[0].get("price")}
                payload_summaries.append(summary)
        report = {
            "robots": robots.status.value,
            "robots_error": robots.error,
            "can_fetch_start": robots.can_fetch(settings.identified_user_agent, plan.start_url if plan else ""),
            "final_url": capture.url,
            "capture_status": capture.status.value,
            "message": capture.message,
            "json_count": len(capture.json_payloads),
            "json_urls": urls[:20],
            "availability_summaries": payload_summaries,
            "fare_count": len(observations),
            "fares": [
                {
                    "flight": item.flight_number,
                    "total": format(item.total_fare, "f"),
                    "date": item.travel_date.isoformat(),
                }
                for item in observations[:12]
            ],
        }
        print(json.dumps(report, indent=2))
    finally:
        await runtime.close()


if __name__ == "__main__":
    asyncio.run(main())
