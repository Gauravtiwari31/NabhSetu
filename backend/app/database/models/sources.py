from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.types import JSONType, enum_column
from app.domain.enums import (
    CircuitState,
    CollectionStatus,
    CollectorModality,
    EgressMode,
    ReviewStatus,
    RobotsStatus,
    RotationStrategy,
    SourceType,
)
from app.domain.models import utcnow


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    base_url: Mapped[str] = mapped_column(String(512))
    source_type: Mapped[SourceType] = mapped_column(enum_column(SourceType))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    automation_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    robots_status: Mapped[RobotsStatus] = mapped_column(
        enum_column(RobotsStatus), default=RobotsStatus.UNKNOWN
    )
    terms_review_status: Mapped[ReviewStatus] = mapped_column(
        enum_column(ReviewStatus), default=ReviewStatus.UNKNOWN
    )
    robots_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terms_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    temporarily_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    restriction_reason: Mapped[str | None] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    capabilities: Mapped[SourceCapability] = relationship(back_populates="source", uselist=False)
    policy: Mapped[SourcePolicyRow] = relationship(back_populates="source", uselist=False)
    network_policy: Mapped[SourceNetworkPolicyRow] = relationship(
        back_populates="source", uselist=False
    )
    adapter_stats: Mapped[list[SourceAdapterStat]] = relationship(back_populates="source")


class SourceCapability(Base):
    __tablename__ = "source_capabilities"

    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"), primary_key=True)
    public_api: Mapped[bool] = mapped_column(Boolean, default=False)
    static_html: Mapped[bool] = mapped_column(Boolean, default=False)
    embedded_json: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_javascript: Mapped[bool] = mapped_column(Boolean, default=False)
    browser_network_json: Mapped[bool] = mapped_column(Boolean, default=False)
    documents_available: Mapped[bool] = mapped_column(Boolean, default=False)
    structured_feed: Mapped[bool] = mapped_column(Boolean, default=False)
    session_required: Mapped[bool] = mapped_column(Boolean, default=False)
    preferred_adapter: Mapped[CollectorModality | None] = mapped_column(
        enum_column(CollectorModality), nullable=True
    )
    last_successful_adapter: Mapped[CollectorModality | None] = mapped_column(
        enum_column(CollectorModality), nullable=True
    )
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    success_rate: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    average_latency_ms: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    notes: Mapped[str | None] = mapped_column(Text)

    source: Mapped[Source] = relationship(back_populates="capabilities")


class SourcePolicyRow(Base):
    __tablename__ = "source_policies"

    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"), primary_key=True)
    minimum_interval_seconds: Mapped[int] = mapped_column(Integer)
    maximum_concurrency: Mapped[int] = mapped_column(Integer)
    daily_request_limit: Mapped[int] = mapped_column(Integer)
    allowed_paths: Mapped[list] = mapped_column(JSONType, default=list)
    blocked_paths: Mapped[list] = mapped_column(JSONType, default=list)
    allowed_routes: Mapped[list] = mapped_column(JSONType, default=list)
    notes: Mapped[str | None] = mapped_column(Text)
    policy_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    policy_version: Mapped[str] = mapped_column(String(32), default="1")

    source: Mapped[Source] = relationship(back_populates="policy")


class SourceNetworkPolicyRow(Base):
    __tablename__ = "source_network_policies"

    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"), primary_key=True)
    egress_mode: Mapped[EgressMode] = mapped_column(enum_column(EgressMode), default=EgressMode.DIRECT)
    allowed_regions: Mapped[list] = mapped_column(JSONType, default=list)
    preferred_region: Mapped[str | None] = mapped_column(String(32))
    maximum_egress_nodes: Mapped[int] = mapped_column(Integer, default=1)
    rotation_strategy: Mapped[RotationStrategy] = mapped_column(
        enum_column(RotationStrategy), default=RotationStrategy.NONE
    )
    sticky_session_required: Mapped[bool] = mapped_column(Boolean, default=False)
    session_ttl_seconds: Mapped[int] = mapped_column(Integer, default=300)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, default=30)
    cooldown_after_429_seconds: Mapped[int] = mapped_column(Integer, default=60)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    network_policy_version: Mapped[str] = mapped_column(String(32), default="1")

    source: Mapped[Source] = relationship(back_populates="network_policy")


class SourceAdapterStat(Base):
    __tablename__ = "source_adapter_stats"
    __table_args__ = (UniqueConstraint("source_id", "adapter", name="uq_source_adapter"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"), index=True)
    adapter: Mapped[CollectorModality] = mapped_column(enum_column(CollectorModality))
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    average_latency_ms: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    circuit_state: Mapped[CircuitState] = mapped_column(
        enum_column(CircuitState), default=CircuitState.CLOSED
    )
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_kind: Mapped[CollectionStatus | None] = mapped_column(
        enum_column(CollectionStatus), nullable=True
    )

    source: Mapped[Source] = relationship(back_populates="adapter_stats")


class SourceRateWindow(Base):
    __tablename__ = "source_rate_windows"

    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"), primary_key=True)
    window_date: Mapped[str] = mapped_column(String(10), primary_key=True)
    request_count: Mapped[int] = mapped_column(Integer, default=0)
    in_flight: Mapped[int] = mapped_column(Integer, default=0)
    last_request_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
