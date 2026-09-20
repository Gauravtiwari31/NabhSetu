from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.database.types import JSONType, enum_column
from app.domain.enums import (
    CollectionStatus,
    CollectorModality,
    HttpResponseCategory,
    JobStatus,
    NetworkFailureCategory,
)
from app.domain.models import utcnow


class CollectionJob(Base):
    __tablename__ = "collection_jobs"
    __table_args__ = (
        Index("ix_collection_jobs_status", "status", "created_at"),
        Index("ix_collection_jobs_source", "source_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
    status: Mapped[JobStatus] = mapped_column(enum_column(JobStatus), default=JobStatus.PENDING)
    query_json: Mapped[dict] = mapped_column(JSONType)
    query_hash: Mapped[str] = mapped_column(String(64), index=True)
    result_status: Mapped[CollectionStatus | None] = mapped_column(
        enum_column(CollectionStatus), nullable=True
    )
    collector: Mapped[CollectorModality | None] = mapped_column(
        enum_column(CollectorModality), nullable=True
    )
    is_simulated: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_summary: Mapped[str | None] = mapped_column(Text)


class CollectionAttempt(Base):
    __tablename__ = "collection_attempts"
    __table_args__ = (
        Index("ix_attempts_source_adapter_status", "source_id", "collector", "status", "started_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("collection_jobs.id"), index=True)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"), index=True)
    collector: Mapped[CollectorModality] = mapped_column(enum_column(CollectorModality))
    status: Mapped[CollectionStatus] = mapped_column(enum_column(CollectionStatus))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    http_status: Mapped[int | None] = mapped_column(Integer)
    http_response_category: Mapped[HttpResponseCategory] = mapped_column(
        enum_column(HttpResponseCategory), default=HttpResponseCategory.NONE
    )
    egress_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("egress_nodes.id"), nullable=True)
    egress_region: Mapped[str | None] = mapped_column(String(32))
    session_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    network_failure_category: Mapped[NetworkFailureCategory] = mapped_column(
        enum_column(NetworkFailureCategory), default=NetworkFailureCategory.NONE
    )
    failover_count: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    parser_name: Mapped[str | None] = mapped_column(String(64))
    parser_version: Mapped[str | None] = mapped_column(String(32))
    payload_hash: Mapped[str | None] = mapped_column(String(64))
    error_json: Mapped[dict | None] = mapped_column(JSONType)
    metadata_json: Mapped[dict] = mapped_column(JSONType, default=dict)


class ComplianceLeaseRow(Base):
    __tablename__ = "compliance_leases"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"), index=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("collection_jobs.id"), nullable=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    policy_version: Mapped[str] = mapped_column(String(32))
    reason_codes: Mapped[list] = mapped_column(JSONType, default=list)
