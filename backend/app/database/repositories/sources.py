from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import (
    Source,
    SourceAdapterStat,
    SourceCapability,
    SourcePolicyRow,
)
from app.domain.enums import (
    CircuitState,
    CollectionStatus,
    CollectorModality,
    RobotsStatus,
    SourceType,
)
from app.domain.models import (
    AdapterStats,
    SourceCapabilities,
    SourceNetworkPolicy,
    SourcePolicy,
    SourceProfile,
    ensure_utc,
    utcnow,
)


def _to_profile(row: Source) -> SourceProfile:
    cap = row.capabilities
    pol = row.policy
    net = row.network_policy
    return SourceProfile(
        id=row.id,
        name=row.name,
        base_url=row.base_url,
        source_type=row.source_type,
        enabled=row.enabled,
        automation_allowed=row.automation_allowed,
        robots_status=row.robots_status,
        terms_review_status=row.terms_review_status,
        robots_checked_at=ensure_utc(row.robots_checked_at),
        terms_checked_at=ensure_utc(row.terms_checked_at),
        temporarily_blocked=row.temporarily_blocked,
        restriction_reason=row.restriction_reason,
        capabilities=SourceCapabilities(
            public_api=cap.public_api,
            static_html=cap.static_html,
            embedded_json=cap.embedded_json,
            requires_javascript=cap.requires_javascript,
            browser_network_json=cap.browser_network_json,
            documents_available=cap.documents_available,
            structured_feed=cap.structured_feed,
            session_required=cap.session_required,
            preferred_adapter=cap.preferred_adapter,
            last_successful_adapter=cap.last_successful_adapter,
            last_success_at=ensure_utc(cap.last_success_at),
            last_failure_at=ensure_utc(cap.last_failure_at),
            success_rate=cap.success_rate,
            average_latency_ms=cap.average_latency_ms,
            notes=cap.notes,
        ),
        policy=SourcePolicy(
            minimum_interval_seconds=pol.minimum_interval_seconds,
            maximum_concurrency=pol.maximum_concurrency,
            daily_request_limit=pol.daily_request_limit,
            allowed_paths=list(pol.allowed_paths or ["*"]),
            blocked_paths=list(pol.blocked_paths or []),
            allowed_routes=list(pol.allowed_routes or ["*"]),
            notes=pol.notes,
            policy_checked_at=ensure_utc(pol.policy_checked_at),
            policy_version=pol.policy_version,
        ),
        network_policy=SourceNetworkPolicy(
            egress_mode=net.egress_mode,
            allowed_regions=list(net.allowed_regions or []),
            preferred_region=net.preferred_region,
            maximum_egress_nodes=net.maximum_egress_nodes,
            rotation_strategy=net.rotation_strategy,
            sticky_session_required=net.sticky_session_required,
            session_ttl_seconds=net.session_ttl_seconds,
            cooldown_seconds=net.cooldown_seconds,
            cooldown_after_429_seconds=net.cooldown_after_429_seconds,
            enabled=net.enabled,
            network_policy_version=net.network_policy_version,
        ),
        adapter_stats=[
            AdapterStats(
                adapter=stat.adapter,
                success_count=stat.success_count,
                failure_count=stat.failure_count,
                last_success_at=ensure_utc(stat.last_success_at),
                last_failure_at=ensure_utc(stat.last_failure_at),
                average_latency_ms=stat.average_latency_ms,
                circuit_state=stat.circuit_state,
                consecutive_failures=stat.consecutive_failures,
                cooldown_until=ensure_utc(stat.cooldown_until),
                last_failure_kind=stat.last_failure_kind,
            )
            for stat in row.adapter_stats
        ],
    )


def _source_load(stmt: Select[tuple[Source]]) -> Select[tuple[Source]]:
    return stmt.options(
        selectinload(Source.capabilities),
        selectinload(Source.policy),
        selectinload(Source.network_policy),
        selectinload(Source.adapter_stats),
    )


class SourceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, source_id: uuid.UUID) -> SourceProfile | None:
        stmt = _source_load(select(Source).where(Source.id == source_id))
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return _to_profile(row) if row else None

    async def get_by_name(self, name: str) -> SourceProfile | None:
        stmt = _source_load(select(Source).where(Source.name == name))
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return _to_profile(row) if row else None

    async def list_enabled(self) -> list[SourceProfile]:
        stmt = _source_load(select(Source).where(Source.enabled.is_(True)).order_by(Source.name))
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_to_profile(row) for row in rows]

    async def list_all(self) -> list[SourceProfile]:
        stmt = _source_load(select(Source).order_by(Source.name))
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_to_profile(row) for row in rows]

    async def get_mock(self) -> SourceProfile | None:
        stmt = _source_load(select(Source).where(Source.source_type == SourceType.MOCK))
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return _to_profile(row) if row else None

    async def list_live(self) -> list[SourceProfile]:
        stmt = _source_load(
            select(Source)
            .where(Source.source_type != SourceType.MOCK)
            .order_by(Source.name)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_to_profile(row) for row in rows]

    async def apply_robots_snapshot(
        self,
        source_id: uuid.UUID,
        *,
        robots_status: RobotsStatus,
        checked_at: datetime,
        blocked_paths: list[str] | None = None,
        allowed_paths: list[str] | None = None,
    ) -> None:
        """Record a live robots.txt fetch. Never flips automation_allowed."""
        row = await self.session.get(Source, source_id)
        if row is None:
            return
        row.robots_status = robots_status
        row.robots_checked_at = checked_at
        row.updated_at = utcnow()
        policy = await self.session.get(SourcePolicyRow, source_id)
        if policy is None:
            return
        if blocked_paths is not None:
            existing = list(policy.blocked_paths or [])
            merged: list[str] = []
            for item in existing + blocked_paths:
                if item and item not in merged:
                    merged.append(item)
            policy.blocked_paths = merged
        if allowed_paths is not None:
            policy.allowed_paths = list(allowed_paths)
        policy.policy_checked_at = checked_at

    async def mark_restricted(self, source_id: uuid.UUID, reason: str) -> None:
        row = await self.session.get(Source, source_id)
        if row is None:
            return
        row.temporarily_blocked = True
        row.restriction_reason = reason
        row.updated_at = utcnow()

    async def record_adapter_outcome(
        self,
        source_id: uuid.UUID,
        adapter: CollectorModality,
        *,
        success: bool,
        latency_ms: int,
        status: CollectionStatus,
        circuit_state: CircuitState,
        consecutive_failures: int,
        cooldown_until: datetime | None,
        now: datetime | None = None,
        neutral: bool = False,
    ) -> None:
        moment = now or utcnow()
        stmt = select(SourceAdapterStat).where(
            SourceAdapterStat.source_id == source_id,
            SourceAdapterStat.adapter == adapter,
        )
        stat = (await self.session.execute(stmt)).scalar_one_or_none()
        if stat is None:
            stat = SourceAdapterStat(source_id=source_id, adapter=adapter)
            self.session.add(stat)
            await self.session.flush()
        if success:
            stat.success_count += 1
            stat.last_success_at = moment
            stat.consecutive_failures = 0
        elif not neutral:
            stat.failure_count += 1
            stat.last_failure_at = moment
            stat.consecutive_failures = consecutive_failures
            stat.last_failure_kind = status
        else:
            stat.last_failure_kind = status
        total = stat.success_count + stat.failure_count
        if stat.average_latency_ms is None:
            stat.average_latency_ms = Decimal(latency_ms)
        elif total > 0:
            prev = Decimal(stat.average_latency_ms)
            stat.average_latency_ms = ((prev * (total - 1)) + Decimal(latency_ms)) / Decimal(total)
        stat.circuit_state = circuit_state
        stat.cooldown_until = cooldown_until

        cap = await self.session.get(SourceCapability, source_id)
        if cap is None:
            return
        if success:
            cap.last_successful_adapter = adapter
            cap.last_success_at = moment
        elif not neutral:
            cap.last_failure_at = moment
        stats = (
            await self.session.execute(
                select(SourceAdapterStat).where(SourceAdapterStat.source_id == source_id)
            )
        ).scalars().all()
        successes = sum(item.success_count for item in stats)
        failures = sum(item.failure_count for item in stats)
        denom = successes + failures
        cap.success_rate = (Decimal(successes) / Decimal(denom)).quantize(Decimal("0.0001")) if denom else None
        latencies = [item.average_latency_ms for item in stats if item.average_latency_ms is not None]
        cap.average_latency_ms = (sum(latencies) / Decimal(len(latencies))) if latencies else None
