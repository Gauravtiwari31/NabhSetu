from __future__ import annotations

from app.acquisition.base import BaseCollector
from app.acquisition.circuit_breaker import CircuitBreaker
from app.config import DataMode, Settings
from app.database.repositories import SourceRepository
from app.domain.enums import (
    DEFAULT_COLLECTOR_PRIORITY,
    NEUTRAL_STATUSES,
    CircuitState,
    CollectionStatus,
    CollectorModality,
)
from app.domain.models import SourceProfile, utcnow


class SourceCapabilityRegistry:
    def __init__(
        self,
        settings: Settings,
        sources: SourceRepository,
        collectors: list[BaseCollector],
        circuit: CircuitBreaker,
    ) -> None:
        self.settings = settings
        self.sources = sources
        self.collectors = collectors
        self.circuit = circuit

    async def get(self, source_id) -> SourceProfile | None:
        return await self.sources.get(source_id)

    async def list_all(self) -> list[SourceProfile]:
        return await self.sources.list_all()

    async def resolve_source(self, profile_hint: SourceProfile | None, source_id=None) -> SourceProfile | None:
        if profile_hint is not None:
            return profile_hint
        if source_id is not None:
            return await self.sources.get(source_id)
        if self.settings.data_mode == DataMode.MOCK:
            return await self.sources.get_mock()
        live = await self.sources.list_live()
        permitted = [
            source
            for source in live
            if source.enabled and source.automation_allowed and not source.temporarily_blocked
        ]
        return permitted[0] if permitted else None

    def bind_robots(self, source_id, snapshot) -> None:
        for collector in self.collectors:
            bind = getattr(collector, "bind_robots", None)
            if bind is not None:
                bind(source_id, snapshot)

    async def rank_collectors(self, source: SourceProfile) -> list[BaseCollector]:
        compatible: list[BaseCollector] = []
        for collector in self.collectors:
            if collector.identity == CollectorModality.MOCK and self.settings.data_mode != DataMode.MOCK:
                continue
            if await collector.supports(source):
                compatible.append(collector)

        preferred = source.capabilities.preferred_adapter
        last_success = source.capabilities.last_successful_adapter
        priority_index = {modality: index for index, modality in enumerate(DEFAULT_COLLECTOR_PRIORITY)}

        def score(collector: BaseCollector) -> tuple:
            stats = source.stats_for(collector.identity)
            circuit_penalty = 0
            if stats and stats.circuit_state == CircuitState.OPEN and not self.circuit.can_probe(stats):
                circuit_penalty = 100
            preferred_rank = 0 if collector.identity == preferred else 1
            success_rank = 0 if collector.identity == last_success else 1
            default_rank = priority_index.get(collector.identity, 99)
            recency = 0 if stats and stats.last_success_at else 1
            success_rate = -(float(stats.success_count) / max(1, stats.success_count + stats.failure_count) if stats else 0)
            latency = float(stats.average_latency_ms or 0) if stats else 0
            return (
                circuit_penalty,
                preferred_rank,
                success_rank,
                default_rank,
                recency,
                success_rate,
                latency,
                collector.identity.value,
            )

        compatible.sort(key=score)
        return [item for item in compatible if score(item)[0] == 0]

    async def record_outcome(
        self,
        source: SourceProfile,
        collector: CollectorModality,
        status: CollectionStatus,
        latency_ms: int,
    ) -> None:
        stats = source.stats_for(collector)
        success = status == CollectionStatus.SUCCESS
        neutral = status in NEUTRAL_STATUSES
        state, consecutive, cooldown = self.circuit.snapshot_after(stats, status, success=success)
        await self.sources.record_adapter_outcome(
            source.id,
            collector,
            success=success,
            latency_ms=latency_ms,
            status=status,
            circuit_state=state,
            consecutive_failures=consecutive,
            cooldown_until=cooldown,
            now=utcnow(),
            neutral=neutral,
        )
        if status in {CollectionStatus.BLOCKED, CollectionStatus.CAPTCHA_BLOCKED}:
            await self.sources.mark_restricted(source.id, status.value)
