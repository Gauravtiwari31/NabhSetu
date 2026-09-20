from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import uuid4

from app.acquisition.discovery.robots import RobotsSnapshot, fetch_robots
from app.config import DataMode
from app.domain.enums import CollectionStatus, SourceType
from app.domain.models import FareQuery, SourceProfile
from app.services.container import AppContainer

STOP_SOURCE_STATUSES = {
    CollectionStatus.BLOCKED,
    CollectionStatus.CAPTCHA_BLOCKED,
}


@dataclass
class QueryRunRecord:
    source: str
    origin: str
    destination: str
    travel_date: str
    lead_time_days: int
    status: str
    collector: str | None
    observation_count: int
    fares: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    robots_status: str | None = None
    job_id: str | None = None
    is_simulated: bool = False
    json_count: int | None = None
    final_url: str | None = None


class LiveRunOrchestrator:
    """Multi-source, multi-date runner. Persists only real collection outcomes."""

    def __init__(self, container: AppContainer) -> None:
        self.container = container

    def _bind_robots(self, source_id, snapshot: RobotsSnapshot) -> None:
        self.container.registry.bind_robots(source_id, snapshot)

    async def refresh_robots(self, source: SourceProfile) -> tuple[SourceProfile, RobotsSnapshot]:
        snapshot = await fetch_robots(self.container.settings, source.base_url)
        await self.container.sources.apply_robots_snapshot(
            source.id,
            robots_status=snapshot.status,
            checked_at=snapshot.fetched_at,
            blocked_paths=snapshot.disallow_paths,
        )
        await self.container.events.emit(
            "ROBOTS_REFRESHED",
            "Live robots.txt snapshot recorded",
            source_id=source.id,
            payload={
                "status": snapshot.status.value,
                "http_status": snapshot.http_status,
                "error": snapshot.error,
                "disallow": snapshot.disallow_paths,
                "sitemaps": snapshot.sitemaps,
            },
        )
        self.container.registry.bind_robots(source.id, snapshot)
        refreshed = await self.container.sources.get(source.id)
        assert refreshed is not None
        return refreshed, snapshot

    async def run(
        self,
        *,
        routes: list[tuple[str, str]],
        observation_date: date,
        lead_times: tuple[int, ...] | None = None,
        source_types: set[SourceType] | None = None,
    ) -> list[QueryRunRecord]:
        if self.container.settings.data_mode != DataMode.LIVE:
            raise RuntimeError("LiveRunOrchestrator requires APIX_DATA_MODE=live")
        records: list[QueryRunRecord] = []
        sources = await self.container.sources.list_live()
        if source_types is not None:
            sources = [source for source in sources if source.source_type in source_types]
        for source in sources:
            source, snapshot = await self.refresh_robots(source)
            await self.container.session.commit()
            skip_source = False
            for origin, destination in routes:
                queries = self.container.scheduler.expand(
                    origin=origin,
                    destination=destination,
                    observation_date=observation_date,
                    source_id=source.id,
                    lead_times=lead_times or (1, 7, 15, 30, 45),
                )
                for query in queries:
                    record = await self._collect_one(source, query, snapshot)
                    records.append(record)
                    await self.container.session.commit()
                    print(
                        f"{record.source} {record.origin}-{record.destination} "
                        f"{record.travel_date} T+{record.lead_time_days} "
                        f"{record.status} collector={record.collector} "
                        f"fares={record.observation_count} json={record.json_count} "
                        f"url={record.final_url}",
                        flush=True,
                    )
                    if record.status in {status.value for status in STOP_SOURCE_STATUSES}:
                        skip_source = True
                        break
                    if record.status != CollectionStatus.POLICY_DENIED.value:
                        await asyncio.sleep(source.policy.minimum_interval_seconds)
                if skip_source:
                    break
        return records

    async def _collect_one(
        self, source: SourceProfile, query: FareQuery, snapshot: RobotsSnapshot
    ) -> QueryRunRecord:
        request_id = f"live-{uuid4()}"
        job_id, result = await self.container.collection.submit(query, request_id=request_id)
        fares = [
            {
                "carrier": item.carrier,
                "flight_number": item.flight_number,
                "total_fare": format(item.total_fare, "f"),
                "currency": item.currency,
                "travel_date": item.travel_date.isoformat(),
                "collector": item.collector.value,
            }
            for item in result.observations
        ]
        return QueryRunRecord(
            source=source.name,
            origin=query.origin,
            destination=query.destination,
            travel_date=query.travel_date.isoformat(),
            lead_time_days=query.lead_time_days,
            status=result.status.value,
            collector=result.collector.value,
            observation_count=len(result.observations),
            fares=fares,
            errors=[f"{item.code}:{item.message}" for item in result.errors],
            robots_status=snapshot.status.value,
            job_id=str(job_id),
            is_simulated=result.is_simulated,
            json_count=(result.metadata or {}).get("json_count"),
            final_url=(result.metadata or {}).get("final_url"),
        )
