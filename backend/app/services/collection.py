from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from app.acquisition.discovery.robots import fetch_robots
from app.acquisition.router import AcquisitionRouter
from app.config import DataMode, Settings
from app.database.repositories import ObservationRepository
from app.database.repositories.jobs import JobRepository
from app.domain.enums import CollectionStatus, JobStatus, RobotsStatus, SourceType
from app.domain.hashing import canonical_dumps, sha256_canonical
from app.domain.models import CollectionResult, FareQuery, ProvenanceLink, utcnow
from app.normalisation.deduplication import apply_duplicate_key
from app.provenance.lineage import observation_lineage
from app.quality.mapping import map_publication_disposition
from app.quality.validation import disposition_from, quality_score, validate_observation


class CollectionService:
    def __init__(
        self,
        settings: Settings,
        jobs: JobRepository,
        observations: ObservationRepository,
        router: AcquisitionRouter,
    ) -> None:
        self.settings = settings
        self.jobs = jobs
        self.observations = observations
        self.router = router

    async def enqueue(self, query: FareQuery, *, request_id: str) -> UUID:
        job = await self.jobs.create(query, request_id=request_id, source_id=query.source_id)
        return job.id

    async def submit(self, query: FareQuery, *, request_id: str) -> tuple[UUID, CollectionResult]:
        job = await self.jobs.create(query, request_id=request_id, source_id=query.source_id)
        result = await self.execute(job, query, request_id=request_id)
        return job.id, result

    async def execute(self, job, query: FareQuery, *, request_id: str) -> CollectionResult:
        await self.jobs.set_status(job, JobStatus.RUNNING)
        await self._ensure_live_robots(query)
        result = await self.router.collect(query, job_id=job.id, request_id=request_id)
        await self.persist_result(job.id, result)
        completed = JobStatus.FAILED
        if result.status in {CollectionStatus.SUCCESS, CollectionStatus.NO_RESULTS}:
            completed = JobStatus.COMPLETED
        elif result.status == CollectionStatus.POLICY_DENIED:
            completed = JobStatus.DENIED
        await self.jobs.set_status(
            job,
            completed,
            result_status=result.status,
            collector=result.collector,
            is_simulated=result.is_simulated,
            error_summary=result.errors[0].message if result.errors else None,
            completed=True,
        )
        return result

    async def _ensure_live_robots(self, query: FareQuery) -> None:
        if self.settings.data_mode != DataMode.LIVE:
            return
        profile = await self.router.registry.resolve_source(None, query.source_id)
        if profile is None or profile.source_type == SourceType.MOCK:
            return
        stale = profile.robots_status == RobotsStatus.UNKNOWN or profile.robots_checked_at is None
        if profile.robots_checked_at is not None:
            age = utcnow() - profile.robots_checked_at
            stale = stale or age > timedelta(days=self.settings.robots_review_max_age_days)
        if not stale:
            return
        snapshot = await fetch_robots(self.settings, profile.base_url)
        await self.router.registry.sources.apply_robots_snapshot(
            profile.id,
            robots_status=snapshot.status,
            checked_at=snapshot.fetched_at,
            blocked_paths=snapshot.disallow_paths,
        )
        self.router.registry.bind_robots(profile.id, snapshot)

    async def persist_result(self, job_id: UUID, result: CollectionResult) -> None:
        if result.status != CollectionStatus.SUCCESS or not result.observations:
            return
        attempts = await self.jobs.list_attempts(job_id)
        attempt_id = attempts[-1].id if attempts else None
        payload_id = None
        if result.raw_payload_reference is not None:
            body = canonical_dumps([obs.model_dump(mode="json") for obs in result.observations])
            artifact = await self.observations.store_payload(result.raw_payload_reference, body)
            payload_id = artifact.id
        previous = await self.observations.latest_chain_hash()
        for observation in result.observations:
            apply_duplicate_key(observation, self.settings.observation_bucket_seconds)
            flags = validate_observation(observation)
            disposition = disposition_from(flags)
            publication = map_publication_disposition(observation, flags)
            score = quality_score(observation, self.settings, flags)
            raw = await self.observations.store_raw(
                source_id=result.source_id,
                job_id=job_id,
                attempt_id=attempt_id,
                collector=result.collector,
                payload_id=payload_id,
                payload_hash=result.payload_hash or observation.raw_record_hash,
                parser_name=result.parser_name,
                parser_version=result.parser_version,
                record=observation.model_dump(mode="json"),
                record_hash=observation.raw_record_hash,
                collected_at=observation.collected_at,
            )
            original = await self.observations.find_by_duplicate_key(observation.duplicate_key or "")
            latest = await self.observations.find_latest_by_duplicate_key(observation.duplicate_key or "")
            stored = await self.observations.store_normalised(
                observation,
                source_id=result.source_id,
                raw_id=raw.id,
                quality_score=score,
                disposition=disposition,
                publication_disposition=publication,
                duplicate_of_id=original.id if original is not None else None,
                supersedes_id=latest.id if latest is not None else None,
            )
            for flag in flags:
                await self.observations.add_flag(stored.id, stored.collected_at, flag)
            links = observation_lineage(
                observation_id=stored.id,
                raw_id=raw.id,
                payload_id=payload_id,
                attempt_id=attempt_id,
                source_id=result.source_id,
                hashes={
                    "observation": sha256_canonical(observation.model_dump(mode="json")),
                    "raw": raw.record_hash,
                    "payload": result.payload_hash,
                },
            )
            for link in links:
                record = await self.observations.add_provenance(link, previous)
                previous = record.chain_hash
            extra = ProvenanceLink(
                entity_type="collection_job",
                entity_id=job_id,
                parent_type="normalised_observation",
                parent_id=stored.id,
                relation="produced",
                content_hash=result.payload_hash,
            )
            record = await self.observations.add_provenance(extra, previous)
            previous = record.chain_hash
