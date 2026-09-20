from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import EgressNode, EgressSessionRow, SystemEvent
from app.domain.models import EgressSession, utcnow


class EgressRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_enabled(self) -> list[EgressNode]:
        stmt = select(EgressNode).where(EgressNode.enabled.is_(True)).order_by(EgressNode.provider, EgressNode.region)
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_healthy(self) -> list[EgressNode]:
        stmt = (
            select(EgressNode)
            .where(EgressNode.enabled.is_(True), EgressNode.healthy.is_(True))
            .order_by(EgressNode.failure_count, EgressNode.active_sessions, EgressNode.provider)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get(self, node_id: uuid.UUID) -> EgressNode | None:
        return await self.session.get(EgressNode, node_id)

    async def get_direct(self) -> EgressNode | None:
        stmt = select(EgressNode).where(EgressNode.provider == "direct").limit(1)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def mark_unhealthy(self, node_id: uuid.UUID) -> None:
        node = await self.get(node_id)
        if node is None:
            return
        node.healthy = False
        node.failure_count += 1
        node.last_health_check = utcnow()

    async def mark_healthy(self, node_id: uuid.UUID, latency_ms: int | None = None) -> None:
        node = await self.get(node_id)
        if node is None:
            return
        node.healthy = True
        node.failure_count = 0
        node.last_health_check = utcnow()
        if latency_ms is not None:
            node.latency_ms = latency_ms

    async def create_session(
        self,
        source_id: uuid.UUID,
        node_id: uuid.UUID,
        ttl_seconds: int,
        now: datetime | None = None,
    ) -> EgressSession:
        moment = now or utcnow()
        row = EgressSessionRow(
            source_id=source_id,
            egress_id=node_id,
            created_at=moment,
            expires_at=moment + timedelta(seconds=ttl_seconds),
            request_count=1,
            closed=False,
        )
        self.session.add(row)
        node = await self.get(node_id)
        if node is not None:
            node.active_sessions += 1
        await self.session.flush()
        return EgressSession(
            session_id=row.id,
            source_id=source_id,
            egress_id=node_id,
            created_at=row.created_at,
            expires_at=row.expires_at,
            request_count=row.request_count,
            closed=False,
        )

    async def active_session(self, source_id: uuid.UUID, now: datetime | None = None) -> EgressSession | None:
        moment = now or utcnow()
        stmt = (
            select(EgressSessionRow)
            .where(
                EgressSessionRow.source_id == source_id,
                EgressSessionRow.closed.is_(False),
                EgressSessionRow.expires_at > moment,
            )
            .order_by(EgressSessionRow.created_at.desc())
            .limit(1)
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return None
        return EgressSession(
            session_id=row.id,
            source_id=row.source_id,
            egress_id=row.egress_id,
            created_at=row.created_at,
            expires_at=row.expires_at,
            request_count=row.request_count,
            closed=row.closed,
        )

    async def touch_session(self, session_id: uuid.UUID) -> None:
        row = await self.session.get(EgressSessionRow, session_id)
        if row is not None:
            row.request_count += 1

    async def close_session(self, session_id: uuid.UUID) -> None:
        row = await self.session.get(EgressSessionRow, session_id)
        if row is None or row.closed:
            return
        row.closed = True
        node = await self.get(row.egress_id)
        if node is not None:
            node.active_sessions = max(0, node.active_sessions - 1)


class EventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def emit(
        self,
        code: str,
        message: str,
        *,
        severity: str = "info",
        source_id: uuid.UUID | None = None,
        job_id: uuid.UUID | None = None,
        request_id: str | None = None,
        collector: str | None = None,
        route: str | None = None,
        payload: dict | None = None,
    ) -> SystemEvent:
        event = SystemEvent(
            code=code,
            message=message,
            severity=severity,
            source_id=source_id,
            job_id=job_id,
            request_id=request_id,
            collector=collector,
            route=route,
            payload=payload or {},
        )
        self.session.add(event)
        await self.session.flush()
        return event
