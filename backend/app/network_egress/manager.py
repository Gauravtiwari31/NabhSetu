from __future__ import annotations

from uuid import UUID

from app.config import Settings
from app.database.repositories import EgressRepository, EventRepository
from app.domain.enums import EgressMode, NetworkFailureCategory
from app.domain.models import EgressSelection, SourceProfile
from app.network_egress.classification import may_failover_egress
from app.network_egress.policy import effective_mode
from app.network_egress.providers import DirectProvider, ProxyPoolProvider, StaticProxyProvider
from app.observability.metrics import metrics


class NetworkEgressManager:
    """Controlled egress under collectors. Optional; direct mode needs no proxy."""

    def __init__(
        self,
        settings: Settings,
        repo: EgressRepository,
        events: EventRepository,
    ) -> None:
        self.settings = settings
        self.repo = repo
        self.events = events
        self.direct = DirectProvider()
        self.static = StaticProxyProvider()
        self.pool = ProxyPoolProvider()

    async def acquire(
        self,
        source: SourceProfile,
        *,
        job_id: UUID | None = None,
        request_id: str | None = None,
        restart_session: bool = False,
    ) -> EgressSelection:
        mode = effective_mode(source, self.settings.egress_mode)
        if source.network_policy.sticky_session_required and not restart_session:
            existing = await self.repo.active_session(source.id)
            if existing is not None:
                await self.repo.touch_session(existing.session_id)
                node = await self.repo.get(existing.egress_id)
                if node is not None:
                    metrics.increment("session_count")
                    return EgressSelection(
                        node_id=node.id,
                        provider=node.provider,
                        region=node.region,
                        endpoint_reference=node.endpoint_reference,
                        mode=mode,
                        session_id=existing.session_id,
                        sticky=True,
                    )
        node = await self._select_node(source, mode)
        session_id = None
        if source.network_policy.sticky_session_required:
            session = await self.repo.create_session(
                source.id, node.id, source.network_policy.session_ttl_seconds
            )
            session_id = session.session_id
        metrics.increment("requests_by_region", region=node.region or "unspecified")
        return EgressSelection(
            node_id=node.id,
            provider=node.provider,
            region=node.region,
            endpoint_reference=node.endpoint_reference,
            mode=mode,
            session_id=session_id,
            sticky=source.network_policy.sticky_session_required,
        )

    async def failover(
        self,
        source: SourceProfile,
        *,
        current: EgressSelection,
        category: NetworkFailureCategory,
        job_id: UUID | None = None,
        request_id: str | None = None,
    ) -> EgressSelection:
        if not may_failover_egress(category):
            await self.events.emit(
                "EGRESS_FAILOVER_DENIED",
                "Source restriction cannot rotate egress",
                severity="warning",
                source_id=source.id,
                job_id=job_id,
                request_id=request_id,
                payload={"category": category.value},
            )
            return current
        await self.repo.mark_unhealthy(current.node_id)
        if current.session_id is not None:
            await self.repo.close_session(current.session_id)
        replacement = await self.acquire(source, job_id=job_id, request_id=request_id, restart_session=True)
        replacement.failover_count = current.failover_count + 1
        replacement.failover_reason = category
        metrics.increment("egress_failovers", reason=category.value)
        metrics.increment("network_failures", reason=category.value)
        await self.events.emit(
            "EGRESS_FAILOVER",
            "Failed over to another healthy egress node",
            source_id=source.id,
            job_id=job_id,
            request_id=request_id,
            payload={"from": str(current.node_id), "to": str(replacement.node_id), "reason": category.value},
        )
        return replacement

    async def _select_node(self, source: SourceProfile, mode: EgressMode):
        nodes = await self.repo.list_enabled()
        selected = None
        if mode == EgressMode.DIRECT:
            selected = self.direct.select(nodes, source.network_policy)
        elif mode == EgressMode.STATIC_PROXY:
            selected = self.static.select(nodes, source.network_policy) or self.direct.select(
                nodes, source.network_policy
            )
        else:
            selected = self.pool.select(nodes, source.network_policy) or self.direct.select(
                nodes, source.network_policy
            )
        if selected is None:
            selected = await self.repo.get_direct()
        if selected is None:
            raise RuntimeError("No egress node is configured; seed the direct node")
        return selected
