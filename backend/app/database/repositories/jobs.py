from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    CollectionAttempt,
    CollectionJob,
    ComplianceLeaseRow,
    SourceRateWindow,
)
from app.domain.enums import CollectionStatus, CollectorModality, JobStatus
from app.domain.models import CollectionResult, ComplianceLease, FareQuery, ensure_utc, utcnow


class JobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        query: FareQuery,
        *,
        request_id: str,
        source_id: uuid.UUID | None,
    ) -> CollectionJob:
        job = CollectionJob(
            request_id=request_id,
            source_id=source_id,
            status=JobStatus.PENDING,
            query_json=query.identity_payload(),
            query_hash=query.identity_hash(),
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def get(self, job_id: uuid.UUID) -> CollectionJob | None:
        return await self.session.get(CollectionJob, job_id)

    async def set_status(
        self,
        job: CollectionJob,
        status: JobStatus,
        *,
        result_status: CollectionStatus | None = None,
        collector: CollectorModality | None = None,
        is_simulated: bool = False,
        error_summary: str | None = None,
        completed: bool = False,
    ) -> None:
        job.status = status
        if status == JobStatus.RUNNING and job.started_at is None:
            job.started_at = utcnow()
        if result_status is not None:
            job.result_status = result_status
        if collector is not None:
            job.collector = collector
        job.is_simulated = is_simulated
        if error_summary is not None:
            job.error_summary = error_summary
        if completed:
            job.completed_at = utcnow()

    async def add_attempt(self, job_id: uuid.UUID, result: CollectionResult, retry_count: int) -> CollectionAttempt:
        latency = int((result.completed_at - result.requested_at).total_seconds() * 1000)
        attempt = CollectionAttempt(
            job_id=job_id,
            source_id=result.source_id,
            collector=result.collector,
            status=result.status,
            started_at=result.requested_at,
            completed_at=result.completed_at,
            retry_count=retry_count,
            http_response_category=result.http_response_category,
            egress_id=result.egress_id,
            egress_region=result.egress_region,
            session_id=result.session_id,
            network_failure_category=result.network_failure_category,
            failover_count=result.failover_count,
            latency_ms=latency,
            parser_name=result.parser_name,
            parser_version=result.parser_version,
            payload_hash=result.payload_hash,
            error_json=[error.model_dump(mode="json") for error in result.errors],
            metadata_json=result.metadata,
        )
        self.session.add(attempt)
        await self.session.flush()
        return attempt

    async def claim_pending(self) -> CollectionJob | None:
        dialect = self.session.bind.dialect.name if self.session.bind is not None else "sqlite"
        stmt = (
            select(CollectionJob)
            .where(CollectionJob.status == JobStatus.PENDING)
            .order_by(CollectionJob.created_at.asc())
            .limit(1)
        )
        if dialect == "postgresql":
            stmt = stmt.with_for_update(skip_locked=True)
        job = (await self.session.execute(stmt)).scalar_one_or_none()
        if job is None:
            return None
        job.status = JobStatus.RUNNING
        if job.started_at is None:
            job.started_at = utcnow()
        await self.session.flush()
        return job

    async def list_recent(self, *, limit: int = 50) -> list[CollectionJob]:
        stmt = select(CollectionJob).order_by(CollectionJob.created_at.desc()).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_attempts(self, job_id: uuid.UUID) -> list[CollectionAttempt]:
        stmt = (
            select(CollectionAttempt)
            .where(CollectionAttempt.job_id == job_id)
            .order_by(CollectionAttempt.started_at)
        )
        return list((await self.session.execute(stmt)).scalars().all())


class RateLimitRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_window(self, source_id: uuid.UUID, day: str) -> SourceRateWindow | None:
        return await self.session.get(SourceRateWindow, (source_id, day))

    async def reserve(
        self,
        source_id: uuid.UUID,
        *,
        day: str,
        now: datetime,
        minimum_interval_seconds: int,
        daily_limit: int,
        max_concurrency: int,
        cooldown_until: datetime | None = None,
    ) -> tuple[bool, list[str], datetime | None]:
        row = await self.get_window(source_id, day)
        if row is None:
            row = SourceRateWindow(source_id=source_id, window_date=day, request_count=0, in_flight=0)
            self.session.add(row)
            await self.session.flush()

        reasons: list[str] = []
        retry_after: datetime | None = None
        if row.cooldown_until and ensure_utc(row.cooldown_until) > now:
            reasons.append("SOURCE_COOLDOWN")
            retry_after = ensure_utc(row.cooldown_until)
        if cooldown_until and cooldown_until > now:
            reasons.append("SOURCE_COOLDOWN")
            retry_after = cooldown_until
        if row.request_count >= daily_limit:
            reasons.append("DAILY_QUOTA_EXHAUSTED")
        if row.in_flight >= max_concurrency:
            reasons.append("CONCURRENCY_EXHAUSTED")
        if row.last_request_at is not None:
            elapsed = (now - ensure_utc(row.last_request_at)).total_seconds()
            if elapsed < minimum_interval_seconds:
                reasons.append("MINIMUM_INTERVAL")
                retry_after = row.last_request_at
        if reasons:
            return False, reasons, retry_after

        row.request_count += 1
        row.in_flight += 1
        row.last_request_at = now
        return True, [], None

    async def release(self, source_id: uuid.UUID, day: str, *, cooldown_until: datetime | None = None) -> None:
        row = await self.get_window(source_id, day)
        if row is None:
            return
        row.in_flight = max(0, row.in_flight - 1)
        if cooldown_until is not None:
            row.cooldown_until = cooldown_until

    async def add_lease(self, lease: ComplianceLease, job_id: uuid.UUID | None) -> None:
        self.session.add(
            ComplianceLeaseRow(
                id=lease.lease_id,
                source_id=lease.source_id,
                job_id=job_id,
                issued_at=lease.issued_at,
                expires_at=lease.expires_at,
                policy_version=lease.policy_version,
                reason_codes=lease.reason_codes,
            )
        )

    async def get_lease(self, lease_id: uuid.UUID) -> ComplianceLeaseRow | None:
        return await self.session.get(ComplianceLeaseRow, lease_id)

    async def release_lease(self, lease_id: uuid.UUID) -> None:
        row = await self.get_lease(lease_id)
        if row is not None and row.released_at is None:
            row.released_at = utcnow()
