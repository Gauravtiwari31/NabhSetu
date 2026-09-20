from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.database.types import JSONType, enum_column
from app.domain.enums import (
    AvailabilityState,
    CollectorModality,
    PublicationDisposition,
    SourceType,
    ValidationDisposition,
)
from app.domain.models import utcnow


class ParserVersion(Base):
    __tablename__ = "parser_versions"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_parser_name_version"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(32))
    source_name: Mapped[str | None] = mapped_column(String(128))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PayloadArtifact(Base):
    __tablename__ = "payload_artifacts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    media_type: Mapped[str] = mapped_column(String(128), default="application/json")
    byte_size: Mapped[int] = mapped_column(Integer, default=0)
    storage_uri: Mapped[str | None] = mapped_column(String(512))
    capture_method: Mapped[str] = mapped_column(String(64), default="in_memory")
    body: Mapped[str | None] = mapped_column(Text)
    request_metadata: Mapped[dict] = mapped_column(JSONType, default=dict)
    response_metadata: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RawObservation(Base):
    __tablename__ = "raw_observations"
    __table_args__ = (
        PrimaryKeyConstraint("id", "collected_at"),
        Index("ix_raw_source_collected", "source_id", "collected_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(default=uuid.uuid4)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"))
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("collection_jobs.id"), nullable=True)
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    collector: Mapped[CollectorModality] = mapped_column(enum_column(CollectorModality))
    payload_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    parser_name: Mapped[str | None] = mapped_column(String(64))
    parser_version: Mapped[str | None] = mapped_column(String(32))
    record_json: Mapped[dict] = mapped_column(JSONType)
    record_hash: Mapped[str] = mapped_column(String(64), index=True)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)


class NormalisedObservation(Base):
    __tablename__ = "normalised_observations"
    __table_args__ = (
        PrimaryKeyConstraint("id", "collected_at"),
        Index("ix_norm_route_travel", "origin_airport", "destination_airport", "travel_date"),
        Index("ix_norm_source_collected", "source_id", "collected_at"),
        Index("ix_norm_duplicate_key", "duplicate_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(default=uuid.uuid4)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"))
    source_name: Mapped[str] = mapped_column(String(128))
    source_type: Mapped[SourceType] = mapped_column(enum_column(SourceType))
    collector: Mapped[CollectorModality] = mapped_column(enum_column(CollectorModality))
    raw_observation_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    origin_airport: Mapped[str] = mapped_column(String(3))
    destination_airport: Mapped[str] = mapped_column(String(3))
    travel_date: Mapped[date] = mapped_column(Date)
    booking_date: Mapped[date] = mapped_column(Date)
    lead_time_days: Mapped[int] = mapped_column(Integer)
    carrier: Mapped[str] = mapped_column(String(3))
    operating_carrier: Mapped[str | None] = mapped_column(String(3))
    flight_number: Mapped[str] = mapped_column(String(16))
    departure_time: Mapped[time | None] = mapped_column(Time)
    arrival_time: Mapped[time | None] = mapped_column(Time)
    cabin_class: Mapped[str] = mapped_column(String(16))
    fare_brand: Mapped[str | None] = mapped_column(String(32))
    fare_class: Mapped[str | None] = mapped_column(String(8))
    base_fare: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    taxes: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    airport_fee: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    udf: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    convenience_fee: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    other_fee: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    total_fare: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    refundable: Mapped[bool | None] = mapped_column(Boolean)
    baggage_allowance: Mapped[str | None] = mapped_column(String(64))
    availability: Mapped[AvailabilityState] = mapped_column(enum_column(AvailabilityState))
    extraction_confidence: Mapped[Decimal] = mapped_column(Numeric(6, 4))
    quality_score: Mapped[Decimal] = mapped_column(Numeric(6, 4))
    disposition: Mapped[ValidationDisposition] = mapped_column(
        enum_column(ValidationDisposition), default=ValidationDisposition.VALID
    )
    raw_record_hash: Mapped[str] = mapped_column(String(64))
    parser_version: Mapped[str] = mapped_column(String(32))
    duplicate_key: Mapped[str] = mapped_column(String(64))
    duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    publication_disposition: Mapped[PublicationDisposition] = mapped_column(
        enum_column(PublicationDisposition), default=PublicationDisposition.ACCEPTED
    )


class FareComponentRow(Base):
    __tablename__ = "fare_components"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    observation_id: Mapped[uuid.UUID] = mapped_column(index=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    base_fare: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    taxes: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    airport_fee: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    udf: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    convenience_fee: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    other_fee: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    total_fare: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    components_complete: Mapped[bool] = mapped_column(Boolean, default=False)


class ValidationFlagRow(Base):
    __tablename__ = "validation_flags"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    observation_id: Mapped[uuid.UUID] = mapped_column(index=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    code: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)
    disposition: Mapped[ValidationDisposition] = mapped_column(enum_column(ValidationDisposition))
    details: Mapped[dict] = mapped_column(JSONType, default=dict)
