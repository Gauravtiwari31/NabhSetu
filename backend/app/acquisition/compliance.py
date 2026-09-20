from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from app.config import DataMode, Settings
from app.database.repositories import EventRepository, RateLimitRepository, SourceRepository
from app.domain.enums import (
    CircuitState,
    CollectionStatus,
    CollectorModality,
    ComplianceDecision,
    ReviewStatus,
    RobotsStatus,
    SourceType,
)
from app.domain.models import (
    ComplianceEvaluation,
    ComplianceLease,
    FareQuery,
    SourceProfile,
    ensure_utc,
    utcnow,
)


class ComplianceGovernor:
    """Fail-closed pre-access gate. Collection must not continue on DENY."""

    def __init__(
        self,
        settings: Settings,
        sources: SourceRepository,
        rates: RateLimitRepository,
        events: EventRepository,
    ) -> None:
        self.settings = settings
        self.sources = sources
        self.rates = rates
        self.events = events

    async def evaluate(
        self,
        source: SourceProfile,
        query: FareQuery,
        *,
        job_id=None,
        request_id: str | None = None,
        adapter: CollectorModality | None = None,
    ) -> ComplianceEvaluation:
        reasons: list[str] = []
        now = utcnow()

        if not source.enabled:
            reasons.append("SOURCE_DISABLED")
        if not source.automation_allowed:
            reasons.append("AUTOMATION_NOT_ALLOWED")
        if source.temporarily_blocked:
            reasons.append("SOURCE_TEMPORARILY_BLOCKED")
        if source.terms_review_status == ReviewStatus.DENIED:
            reasons.append("TERMS_DENIED")
        elif source.terms_review_status in {ReviewStatus.UNKNOWN, ReviewStatus.STALE}:
            reasons.append("TERMS_REVIEW_REQUIRED")
        elif source.terms_review_status == ReviewStatus.REVIEW_REQUIRED:
            reasons.append("TERMS_REVIEW_REQUIRED")
        elif source.terms_checked_at is None:
            reasons.append("TERMS_REVIEW_REQUIRED")
        elif (now - ensure_utc(source.terms_checked_at)).days > self.settings.terms_review_max_age_days:
            reasons.append("TERMS_REVIEW_STALE")

        if source.robots_status in {RobotsStatus.UNKNOWN, RobotsStatus.UNREADABLE}:
            reasons.append("ROBOTS_UNKNOWN")
        elif source.robots_status == RobotsStatus.DISALLOWED:
            reasons.append("ROBOTS_DISALLOWED")
        elif source.robots_checked_at is None:
            reasons.append("ROBOTS_UNKNOWN")
        elif (now - ensure_utc(source.robots_checked_at)).days > self.settings.robots_review_max_age_days:
            reasons.append("ROBOTS_REVIEW_STALE")

        if source.policy.minimum_interval_seconds is None or source.policy.daily_request_limit < 1:
            reasons.append("RATE_POLICY_MISSING")

        route_key = f"{query.origin}-{query.destination}"
        allowed_routes = source.policy.allowed_routes or ["*"]
        if "*" not in allowed_routes and route_key not in allowed_routes:
            reasons.append("ROUTE_NOT_PERMITTED")

        if source.source_type == SourceType.MOCK and self.settings.data_mode != DataMode.MOCK:
            reasons.append("MOCK_SOURCE_IN_LIVE_MODE")
        if adapter == CollectorModality.MOCK and self.settings.data_mode != DataMode.MOCK:
            reasons.append("MOCK_COLLECTOR_IN_LIVE_MODE")

        stats = source.stats_for(adapter) if adapter else None
        if stats and stats.circuit_state == CircuitState.OPEN:
            if stats.last_failure_kind in {
                CollectionStatus.CAPTCHA_BLOCKED,
                CollectionStatus.BLOCKED,
                CollectionStatus.POLICY_DENIED,
            }:
                reasons.append("CIRCUIT_OPEN_RESTRICTION")
            elif stats.cooldown_until and ensure_utc(stats.cooldown_until) > now:
                reasons.append("CIRCUIT_OPEN")

        review_reasons = {code for code in reasons if code.endswith("REVIEW_REQUIRED") or code.endswith("STALE") or code == "ROBOTS_UNKNOWN"}
        deny_hard = set(reasons) - review_reasons

        if reasons:
            decision = (
                ComplianceDecision.REVIEW_REQUIRED
                if review_reasons and not deny_hard
                else ComplianceDecision.DENY
            )
            await self.events.emit(
                "COMPLIANCE_DENIED",
                "Collection denied by compliance governor",
                severity="warning",
                source_id=source.id,
                job_id=job_id,
                request_id=request_id,
                payload={"reasons": reasons, "decision": decision.value},
            )
            return ComplianceEvaluation(
                decision=decision,
                reason_codes=reasons,
                policy_version=source.policy.policy_version,
            )

        reserved, rate_reasons, retry_at = await self.rates.reserve(
            source.id,
            day=now.date().isoformat(),
            now=now,
            minimum_interval_seconds=source.policy.minimum_interval_seconds,
            daily_limit=source.policy.daily_request_limit,
            max_concurrency=source.policy.maximum_concurrency,
        )
        if not reserved:
            await self.events.emit(
                "COMPLIANCE_DENIED",
                "Collection denied by rate policy",
                severity="warning",
                source_id=source.id,
                job_id=job_id,
                request_id=request_id,
                payload={"reasons": rate_reasons},
            )
            retry_after = None
            if retry_at is not None:
                retry_after = max(1, int((retry_at + timedelta(seconds=source.policy.minimum_interval_seconds) - now).total_seconds()))
            return ComplianceEvaluation(
                decision=ComplianceDecision.DENY,
                reason_codes=rate_reasons,
                policy_version=source.policy.policy_version,
                retry_after_seconds=retry_after,
            )

        lease = ComplianceLease(
            lease_id=uuid4(),
            source_id=source.id,
            issued_at=now,
            expires_at=now + timedelta(seconds=self.settings.compliance_lease_seconds),
            policy_version=source.policy.policy_version,
            reason_codes=["ALLOW"],
        )
        await self.rates.add_lease(lease, job_id)
        return ComplianceEvaluation(
            decision=ComplianceDecision.ALLOW,
            reason_codes=["ALLOW"],
            policy_version=source.policy.policy_version,
            lease=lease,
        )

    async def release(self, source: SourceProfile, lease: ComplianceLease | None, *, cooldown=None) -> None:
        if lease is None:
            return
        await self.rates.release_lease(lease.lease_id)
        await self.rates.release(source.id, utcnow().date().isoformat(), cooldown_until=cooldown)
