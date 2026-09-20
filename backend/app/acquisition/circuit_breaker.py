from __future__ import annotations

from datetime import timedelta

from app.config import Settings
from app.database.repositories import SourceRepository
from app.domain.enums import NEUTRAL_STATUSES, CircuitState, CollectionStatus
from app.domain.models import AdapterStats, ensure_utc, utcnow

POLICY_OPEN_STATUSES = {
    CollectionStatus.BLOCKED,
    CollectionStatus.CAPTCHA_BLOCKED,
    CollectionStatus.POLICY_DENIED,
    CollectionStatus.SOURCE_CHANGED,
}


class CircuitBreaker:
    def __init__(self, settings: Settings, sources: SourceRepository) -> None:
        self.settings = settings
        self.sources = sources

    def snapshot_after(
        self,
        stats: AdapterStats | None,
        status: CollectionStatus,
        *,
        success: bool,
    ) -> tuple[CircuitState, int, object]:
        now = utcnow()
        consecutive = 0 if stats is None else stats.consecutive_failures
        state = CircuitState.CLOSED if stats is None else stats.circuit_state
        cooldown = None if stats is None else stats.cooldown_until

        if success:
            return CircuitState.CLOSED, 0, None
        if status in NEUTRAL_STATUSES:
            consecutive = 0 if stats is None else stats.consecutive_failures
            state = CircuitState.CLOSED if stats is None else stats.circuit_state
            cooldown = None if stats is None else stats.cooldown_until
            return state, consecutive, cooldown

        if status in POLICY_OPEN_STATUSES:
            until = now + timedelta(seconds=self.settings.circuit_cooldown_seconds)
            return CircuitState.OPEN, consecutive + 1, until

        consecutive += 1
        if consecutive >= self.settings.circuit_failure_threshold:
            until = now + timedelta(seconds=self.settings.circuit_cooldown_seconds)
            return CircuitState.OPEN, consecutive, until
        return state if state != CircuitState.OPEN else CircuitState.CLOSED, consecutive, cooldown

    def can_probe(self, stats: AdapterStats | None) -> bool:
        if stats is None:
            return True
        if stats.circuit_state != CircuitState.OPEN:
            return True
        if stats.cooldown_until is None:
            return True
        if ensure_utc(stats.cooldown_until) is not None and utcnow() >= ensure_utc(stats.cooldown_until):
            stats.circuit_state = CircuitState.HALF_OPEN
            return True
        return False
