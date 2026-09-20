from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    FareComponentRow,
    NormalisedObservation,
    PayloadArtifact,
    ProvenanceRecord,
    RawObservation,
    ValidationFlagRow,
)
from app.domain.enums import PublicationDisposition, ValidationDisposition
from app.domain.hashing import chain_hash
from app.domain.models import (
    CanonicalFareObservation,
    PayloadReference,
    ProvenanceLink,
    ValidationFlag,
)


class ObservationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._last_chain_hash: str | None = None

    async def store_payload(self, reference: PayloadReference, body: str | None) -> PayloadArtifact:
        existing = (
            await self.session.execute(
                select(PayloadArtifact).where(PayloadArtifact.content_hash == reference.content_hash)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        artifact = PayloadArtifact(
            id=reference.artifact_id or uuid.uuid4(),
            content_hash=reference.content_hash,
            media_type=reference.media_type,
            byte_size=reference.byte_size,
            storage_uri=reference.storage_uri,
            capture_method=reference.capture_method,
            body=body,
        )
        self.session.add(artifact)
        await self.session.flush()
        return artifact

    async def store_raw(
        self,
        *,
        source_id: uuid.UUID,
        job_id: uuid.UUID | None,
        attempt_id: uuid.UUID | None,
        collector,
        payload_id: uuid.UUID | None,
        payload_hash: str,
        parser_name: str | None,
        parser_version: str | None,
        record: dict,
        record_hash: str,
        collected_at: datetime,
    ) -> RawObservation:
        row = RawObservation(
            source_id=source_id,
            job_id=job_id,
            attempt_id=attempt_id,
            collector=collector,
            payload_id=payload_id,
            payload_hash=payload_hash,
            parser_name=parser_name,
            parser_version=parser_version,
            record_json=record,
            record_hash=record_hash,
            collected_at=collected_at,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def find_by_duplicate_key(self, duplicate_key: str) -> NormalisedObservation | None:
        if not duplicate_key:
            return None
        stmt = (
            select(NormalisedObservation)
            .where(NormalisedObservation.duplicate_key == duplicate_key)
            .order_by(NormalisedObservation.collected_at.asc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def find_latest_by_duplicate_key(self, duplicate_key: str) -> NormalisedObservation | None:
        if not duplicate_key:
            return None
        stmt = (
            select(NormalisedObservation)
            .where(NormalisedObservation.duplicate_key == duplicate_key)
            .order_by(NormalisedObservation.collected_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def store_normalised(
        self,
        observation: CanonicalFareObservation,
        *,
        source_id: uuid.UUID,
        raw_id: uuid.UUID | None,
        quality_score,
        disposition,
        publication_disposition: PublicationDisposition = PublicationDisposition.ACCEPTED,
        duplicate_of_id: uuid.UUID | None,
        supersedes_id: uuid.UUID | None = None,
    ) -> NormalisedObservation:
        row = NormalisedObservation(
            id=observation.observation_id,
            collected_at=observation.collected_at,
            source_id=source_id,
            source_name=observation.source,
            source_type=observation.source_type,
            collector=observation.collector,
            raw_observation_id=raw_id,
            origin_airport=observation.origin_airport,
            destination_airport=observation.destination_airport,
            travel_date=observation.travel_date,
            booking_date=observation.booking_date,
            lead_time_days=observation.lead_time_days,
            carrier=observation.carrier,
            operating_carrier=observation.operating_carrier,
            flight_number=observation.flight_number,
            departure_time=observation.departure_time,
            arrival_time=observation.arrival_time,
            cabin_class=observation.cabin_class,
            fare_brand=observation.fare_brand,
            fare_class=observation.fare_class,
            base_fare=observation.base_fare,
            taxes=observation.taxes,
            airport_fee=observation.airport_fee,
            udf=observation.udf,
            convenience_fee=observation.convenience_fee,
            other_fee=observation.other_fee,
            total_fare=observation.total_fare,
            currency=observation.currency,
            refundable=observation.refundable,
            baggage_allowance=observation.baggage_allowance,
            availability=observation.seat_or_fare_availability,
            extraction_confidence=observation.extraction_confidence,
            quality_score=quality_score,
            disposition=disposition,
            raw_record_hash=observation.raw_record_hash,
            parser_version=observation.parser_version,
            duplicate_key=observation.duplicate_key or observation.compute_duplicate_key(),
            duplicate_of_id=duplicate_of_id,
            is_simulated=observation.is_simulated,
            supersedes_id=supersedes_id,
            publication_disposition=publication_disposition,
        )
        self.session.add(row)
        self.session.add(
            FareComponentRow(
                observation_id=row.id,
                collected_at=row.collected_at,
                base_fare=observation.base_fare,
                taxes=observation.taxes,
                airport_fee=observation.airport_fee,
                udf=observation.udf,
                convenience_fee=observation.convenience_fee,
                other_fee=observation.other_fee,
                total_fare=observation.total_fare,
                currency=observation.currency,
                components_complete=all(
                    value is not None
                    for value in (
                        observation.base_fare,
                        observation.taxes,
                        observation.total_fare,
                    )
                ),
            )
        )
        await self.session.flush()
        return row

    async def add_flag(self, observation_id: uuid.UUID, collected_at: datetime, flag: ValidationFlag) -> None:
        self.session.add(
            ValidationFlagRow(
                observation_id=observation_id,
                collected_at=collected_at,
                code=flag.code,
                message=flag.message,
                disposition=flag.disposition,
                details=flag.details,
            )
        )

    async def add_provenance(self, link: ProvenanceLink, previous_hash: str | None) -> ProvenanceRecord:
        payload = {
            "entity_type": link.entity_type,
            "entity_id": str(link.entity_id),
            "parent_type": link.parent_type,
            "parent_id": str(link.parent_id) if link.parent_id else None,
            "relation": link.relation,
            "content_hash": link.content_hash,
        }
        previous = previous_hash or ("0" * 64)
        record = ProvenanceRecord(
            entity_type=link.entity_type,
            entity_id=link.entity_id,
            parent_type=link.parent_type,
            parent_id=link.parent_id,
            relation=link.relation,
            content_hash=link.content_hash,
            previous_chain_hash=previous if previous_hash else None,
            chain_hash=chain_hash(previous, payload),
        )
        self.session.add(record)
        await self.session.flush()
        self._last_chain_hash = record.chain_hash
        return record

    async def latest_chain_hash(self) -> str | None:
        stmt = select(ProvenanceRecord.chain_hash).order_by(ProvenanceRecord.created_at.desc()).limit(1)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_latest_fares(self, *, origin: str | None, destination: str | None, limit: int) -> list[NormalisedObservation]:
        identity = (
            NormalisedObservation.origin_airport,
            NormalisedObservation.destination_airport,
            NormalisedObservation.travel_date,
            NormalisedObservation.carrier,
            NormalisedObservation.flight_number,
            NormalisedObservation.lead_time_days,
        )
        latest = (
            select(*identity, func.max(NormalisedObservation.collected_at).label("latest"))
            .group_by(*identity)
            .subquery()
        )
        stmt = (
            select(NormalisedObservation)
            .join(
                latest,
                (NormalisedObservation.origin_airport == latest.c.origin_airport)
                & (NormalisedObservation.destination_airport == latest.c.destination_airport)
                & (NormalisedObservation.travel_date == latest.c.travel_date)
                & (NormalisedObservation.carrier == latest.c.carrier)
                & (NormalisedObservation.flight_number == latest.c.flight_number)
                & (NormalisedObservation.lead_time_days == latest.c.lead_time_days)
                & (NormalisedObservation.collected_at == latest.c.latest),
            )
            .order_by(NormalisedObservation.collected_at.desc())
        )
        if origin:
            stmt = stmt.where(NormalisedObservation.origin_airport == origin.upper())
        if destination:
            stmt = stmt.where(NormalisedObservation.destination_airport == destination.upper())
        stmt = stmt.limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_publishable(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        simulated: bool | None = None,
    ) -> list[NormalisedObservation]:
        stmt = select(NormalisedObservation).order_by(NormalisedObservation.collected_at.asc())
        if start is not None:
            stmt = stmt.where(NormalisedObservation.collected_at >= start)
        if end is not None:
            stmt = stmt.where(NormalisedObservation.collected_at <= end)
        if simulated is not None:
            stmt = stmt.where(NormalisedObservation.is_simulated.is_(simulated))
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_for_job(self, job_id: uuid.UUID) -> list[NormalisedObservation]:
        raw_ids = select(RawObservation.id).where(RawObservation.job_id == job_id)
        stmt = select(NormalisedObservation).where(NormalisedObservation.raw_observation_id.in_(raw_ids))
        return list((await self.session.execute(stmt)).scalars().all())

    async def provenance_for(self, entity_ids: list[uuid.UUID]) -> list[ProvenanceRecord]:
        if not entity_ids:
            return []
        stmt = select(ProvenanceRecord).where(ProvenanceRecord.entity_id.in_(entity_ids)).order_by(
            ProvenanceRecord.created_at
        )
        return list((await self.session.execute(stmt)).scalars().all())
