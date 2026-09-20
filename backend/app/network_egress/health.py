from __future__ import annotations

from app.database.repositories import EgressRepository


class EgressHealth:
    def __init__(self, repo: EgressRepository) -> None:
        self.repo = repo

    async def snapshot(self) -> dict[str, int]:
        nodes = await self.repo.list_enabled()
        healthy = [node for node in nodes if node.healthy]
        return {
            "enabled_nodes": len(nodes),
            "healthy_nodes": len(healthy),
            "unhealthy_nodes": len(nodes) - len(healthy),
            "active_sessions": sum(node.active_sessions for node in nodes),
        }
