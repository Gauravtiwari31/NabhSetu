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


def _flatten_observation(item: Any) -> dict[str, Any]:
    """One collected fare as a flat, export-ready row.

    This used to project six fields -- carrier, flight number, total fare,
    currency, travel date, collector -- and drop the rest. A row with no
    origin, no destination and no booking date cannot be attributed to a route
    or an advance-purchase window, which makes it useless for index
    construction: the CSV that fell out of it could only ever be a fare
    listing, not index input. The observation already carries every field the
    PS asks for, including the base-fare/tax/UDF/convenience split, so emit
    all of it and let the consumer choose columns.
    """
    def money(value: Any) -> str | None:
        return None if value is None else format(value, "f")

    return {
        "observation_id": str(item.observation_id),
        "source": item.source,
        "source_type": item.source_type.value,
        "collector": item.collector.value,
        "collected_at": item.collected_at.isoformat(),
        "origin": item.origin_airport,
        "destination": item.destination_airport,
        "route": f"{item.origin_airport}-{item.destination_airport}",
        "travel_date": item.travel_date.isoformat(),
        "booking_date": item.booking_date.isoformat(),
        "lead_time_days": item.lead_time_days,
        "carrier": item.carrier,
        "operating_carrier": item.operating_carrier,
        "flight_number": item.flight_number,
        "departure_time": item.departure_time.isoformat() if item.departure_time else None,
        "arrival_time": item.arrival_time.isoformat() if item.arrival_time else None,
        "cabin_class": item.cabin_class,
        "fare_brand": item.fare_brand,
        "fare_class": item.fare_class,
        "base_fare": money(item.base_fare),
        "taxes": money(item.taxes),
        "airport_fee": money(item.airport_fee),
        "udf": money(item.udf),
        "convenience_fee": money(item.convenience_fee),
        "other_fee": money(item.other_fee),
        "total_fare": money(item.total_fare),
        "currency": item.currency,
        "refundable": item.refundable,
        "baggage_allowance": item.baggage_allowance,
        "availability": item.seat_or_fare_availability.value,
        "extraction_confidence": format(item.extraction_confidence, "f"),
        "raw_record_hash": item.raw_record_hash,
        "parser_version": item.parser_version,
        "is_simulated": item.is_simulated,
    }


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
        fares = [_flatten_observation(item) for item in result.observations]
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
