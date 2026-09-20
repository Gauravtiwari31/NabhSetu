from __future__ import annotations

import logging
from datetime import timedelta

from app.acquisition.compliance import ComplianceGovernor
from app.acquisition.registry import SourceCapabilityRegistry
from app.config import Settings
from app.database.repositories import EventRepository, JobRepository
from app.domain.enums import (
    FALLBACK_STATUSES,
    RETRY_STATUSES,
    STOP_STATUSES,
    CollectionStatus,
    CollectorModality,
    ComplianceDecision,
    HttpResponseCategory,
    NetworkFailureCategory,
)
from app.domain.models import CollectionError, CollectionResult, FareQuery, SourceProfile, utcnow
from app.network_egress.classification import classify_http_status, may_failover_egress
from app.network_egress.manager import NetworkEgressManager
from app.observability.redaction import redact

logger = logging.getLogger("apix.acquisition")


class AcquisitionRouter:
    def __init__(
        self,
        settings: Settings,
        registry: SourceCapabilityRegistry,
        governor: ComplianceGovernor,
        egress: NetworkEgressManager,
        jobs: JobRepository,
        events: EventRepository,
    ) -> None:
        self.settings = settings
        self.registry = registry
        self.governor = governor
        self.egress = egress
        self.jobs = jobs
        self.events = events

    async def collect(
        self,
        query: FareQuery,
        *,
        job_id,
        request_id: str,
        source: SourceProfile | None = None,
    ) -> CollectionResult:
        profile = await self.registry.resolve_source(source, query.source_id)
        if profile is None:
            return CollectionResult(
                source_id=query.source_id or job_id,
                collector=CollectorModality.MOCK,
                status=CollectionStatus.POLICY_DENIED,
                requested_at=utcnow(),
                completed_at=utcnow(),
                errors=[CollectionError(code="NO_SOURCE", message="No permitted source is available")],
            )

        evaluation = await self.governor.evaluate(
            profile, query, job_id=job_id, request_id=request_id
        )
        if evaluation.decision != ComplianceDecision.ALLOW or evaluation.lease is None:
            await self.events.emit(
                "POLICY_DENIED",
                "Router stopped before collectors",
                severity="warning",
                source_id=profile.id,
                job_id=job_id,
                request_id=request_id,
                route=f"{query.origin}-{query.destination}",
                payload={"reasons": evaluation.reason_codes},
            )
            return CollectionResult(
                source_id=profile.id,
                collector=CollectorModality.MOCK,
                status=CollectionStatus.POLICY_DENIED,
                requested_at=utcnow(),
                completed_at=utcnow(),
                errors=[
                    CollectionError(
                        code="POLICY_DENIED",
                        message="Compliance governor denied collection",
                        details={"reasons": evaluation.reason_codes},
                    )
                ],
                metadata={"reasons": evaluation.reason_codes},
            )

        lease = evaluation.lease
        candidates = await self.registry.rank_collectors(profile)
        if not candidates:
            await self.governor.release(profile, lease)
            return CollectionResult(
                source_id=profile.id,
                collector=CollectorModality.MOCK,
                status=CollectionStatus.UNSUPPORTED,
                requested_at=utcnow(),
                completed_at=utcnow(),
                errors=[CollectionError(code="NO_COLLECTOR", message="No compatible collector is registered")],
            )

        last_result: CollectionResult | None = None
        egress_selection = None
        try:
            egress_selection = await self.egress.acquire(profile, job_id=job_id, request_id=request_id)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("egress_acquire_failed", extra={"request_id": request_id})
            await self.governor.release(profile, lease)
            return CollectionResult(
                source_id=profile.id,
                collector=candidates[0].identity,
                status=CollectionStatus.NETWORK_ERROR,
                requested_at=utcnow(),
                completed_at=utcnow(),
                errors=[CollectionError(code="EGRESS_UNAVAILABLE", message=str(exc))],
                network_failure_category=NetworkFailureCategory.PROXY_INFRASTRUCTURE,
            )

        for collector in candidates:
            retries = 0
            while retries <= self.settings.max_adapter_retries:
                started = utcnow()
                try:
                    result = await collector.collect(
                        query, profile, lease=lease, egress=egress_selection
                    )
                except Exception as exc:
                    logger.exception(
                        "collector_crashed",
                        extra={
                            "request_id": request_id,
                            "job_id": str(job_id),
                            "source_id": str(profile.id),
                            "collector": collector.identity.value,
                        },
                    )
                    result = CollectionResult(
                        source_id=profile.id,
                        collector=collector.identity,
                        status=CollectionStatus.TEMPORARY_FAILURE,
                        requested_at=started,
                        completed_at=utcnow(),
                        errors=[CollectionError(code="COLLECTOR_EXCEPTION", message=type(exc).__name__, retryable=True)],
                    )
                result = self._annotate(result, egress_selection)
                latency_ms = int((result.completed_at - result.requested_at).total_seconds() * 1000)
                await self.registry.record_outcome(profile, collector.identity, result.status, latency_ms)
                await self.jobs.add_attempt(job_id, result, retries)
                self._log(request_id, job_id, query, profile, result)

                if result.status == CollectionStatus.SUCCESS:
                    await self.governor.release(profile, lease)
                    return result
                if result.status in STOP_STATUSES:
                    await self.governor.release(profile, lease)
                    return result
                if result.status == CollectionStatus.RATE_LIMITED:
                    cooldown = utcnow() + timedelta(seconds=profile.network_policy.cooldown_after_429_seconds)
                    await self.governor.release(profile, lease, cooldown=cooldown)
                    return result
                if result.status in FALLBACK_STATUSES:
                    last_result = result
                    break
                if result.status in RETRY_STATUSES and result.status != CollectionStatus.RATE_LIMITED:
                    if may_failover_egress(result.network_failure_category):
                        egress_selection = await self.egress.failover(
                            profile,
                            current=egress_selection,
                            category=result.network_failure_category,
                            job_id=job_id,
                            request_id=request_id,
                        )
                        result.failover_count = egress_selection.failover_count
                    retries += 1
                    last_result = result
                    continue
                last_result = result
                break
            last_result = last_result
        await self.governor.release(profile, lease)
        return last_result or CollectionResult(
            source_id=profile.id,
            collector=candidates[0].identity,
            status=CollectionStatus.TEMPORARY_FAILURE,
            requested_at=utcnow(),
            completed_at=utcnow(),
            errors=[CollectionError(code="ALL_COLLECTORS_FAILED", message="No collector produced a usable result")],
        )

    def _annotate(self, result: CollectionResult, egress) -> CollectionResult:
        if result.egress_id is None and egress is not None:
            result.egress_id = egress.node_id
            result.egress_region = egress.region
            result.session_id = egress.session_id
            result.failover_count = egress.failover_count
        if result.http_response_category == HttpResponseCategory.NONE:
            status = result.metadata.get("http_status") if result.metadata else None
            if isinstance(status, int):
                result.http_response_category = classify_http_status(status)
        return result

    def _log(self, request_id, job_id, query: FareQuery, source: SourceProfile, result: CollectionResult) -> None:
        logger.info(
            "collection_attempt",
            extra=redact(
                {
                    "request_id": request_id,
                    "job_id": str(job_id),
                    "source_id": str(source.id),
                    "route": f"{query.origin}-{query.destination}",
                    "collector": result.collector.value,
                    "status": result.status.value,
                    "json_count": (result.metadata or {}).get("json_count"),
                    "final_url": (result.metadata or {}).get("final_url"),
                    "egress_id": str(result.egress_id) if result.egress_id else None,
                    "egress_region": result.egress_region,
                    "session_id": str(result.session_id) if result.session_id else None,
                    "http_response_category": result.http_response_category.value,
                    "parser_version": result.parser_version,
                    "latency_ms": int((result.completed_at - result.requested_at).total_seconds() * 1000),
                    "failover_count": result.failover_count,
                }
            ),
        )
