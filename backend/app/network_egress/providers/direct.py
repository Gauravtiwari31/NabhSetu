from __future__ import annotations

from app.database.models import EgressNode
from app.domain.enums import EgressMode, RotationStrategy
from app.domain.models import SourceNetworkPolicy


class EgressProvider:
    name: str
    mode: EgressMode

    def supports(self, policy: SourceNetworkPolicy) -> bool:
        return True

    def select(self, nodes: list[EgressNode], policy: SourceNetworkPolicy) -> EgressNode | None:
        raise NotImplementedError


class DirectProvider(EgressProvider):
    name = "direct"
    mode = EgressMode.DIRECT

    def select(self, nodes: list[EgressNode], policy: SourceNetworkPolicy) -> EgressNode | None:
        for node in nodes:
            if node.provider == "direct" and node.enabled and node.healthy:
                return node
        for node in nodes:
            if node.provider == "direct" and node.enabled:
                return node
        return None


class StaticProxyProvider(EgressProvider):
    """Interface only — vendor integration is deferred."""

    name = "static_proxy"
    mode = EgressMode.STATIC_PROXY

    def supports(self, policy: SourceNetworkPolicy) -> bool:
        return policy.egress_mode == EgressMode.STATIC_PROXY

    def select(self, nodes: list[EgressNode], policy: SourceNetworkPolicy) -> EgressNode | None:
        static_nodes = [node for node in nodes if node.provider != "direct" and node.enabled]
        return static_nodes[0] if static_nodes else None


class ProxyPoolProvider(EgressProvider):
    """Health/least-loaded pool selection. Never rotates on 403/CAPTCHA/block."""

    name = "proxy_pool"
    mode = EgressMode.PROXY_POOL

    def supports(self, policy: SourceNetworkPolicy) -> bool:
        return policy.egress_mode in {EgressMode.PROXY_POOL, EgressMode.FAILOVER, EgressMode.REGION_PINNED}

    def select(self, nodes: list[EgressNode], policy: SourceNetworkPolicy) -> EgressNode | None:
        candidates = [node for node in nodes if node.provider != "direct" and node.enabled and node.healthy]
        if policy.preferred_region:
            regional = [node for node in candidates if node.region == policy.preferred_region]
            if regional:
                candidates = regional
        if policy.allowed_regions:
            candidates = [node for node in candidates if node.region in policy.allowed_regions]
        if not candidates:
            return None
        strategy = policy.rotation_strategy
        if strategy == RotationStrategy.LEAST_LOADED:
            return sorted(candidates, key=lambda node: (node.active_sessions, node.failure_count))[0]
        if strategy == RotationStrategy.HEALTH_BASED:
            return sorted(candidates, key=lambda node: (node.failure_count, node.latency_ms or 0))[0]
        if strategy == RotationStrategy.REGION_PINNED:
            return candidates[0]
        return candidates[0]
