from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.database.types import JSONType, enum_column
from app.domain.enums import (
    BacktestStatus,
    IndexBasis,
    IndexFrequency,
    IndexRunStatus,
    IndexVariant,
    PublicationDisposition,
)
from app.domain.models import utcnow


class BasketVersion(Base):
    __tablename__ = "basket_versions"
    __table_args__ = (UniqueConstraint("version", name="uq_basket_version"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    version: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(128))
    method_version: Mapped[str] = mapped_column(String(32), default="1.0.0")
    routes_json: Mapped[list] = mapped_column(JSONType, default=list)
    lead_windows_json: Mapped[list] = mapped_column(JSONType, default=list)
    carriers_json: Mapped[list] = mapped_column(JSONType, default=list)
    config_hash: Mapped[str] = mapped_column(String(64))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WeightVersion(Base):
    __tablename__ = "weight_versions"
    __table_args__ = (UniqueConstraint("version", name="uq_weight_version"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    version: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(64), default="declared")
    file_name: Mapped[str | None] = mapped_column(String(256))
    file_uri: Mapped[str | None] = mapped_column(String(512))
    checksum: Mapped[str | None] = mapped_column(String(64))
    route_weights_json: Mapped[dict] = mapped_column(JSONType, default=dict)
    carrier_weights_json: Mapped[dict] = mapped_column(JSONType, default=dict)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IndexRun(Base):
    __tablename__ = "index_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    status: Mapped[IndexRunStatus] = mapped_column(enum_column(IndexRunStatus), default=IndexRunStatus.PENDING)
    method_version: Mapped[str] = mapped_column(String(32), default="1.0.0")
    basket_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("basket_versions.id"))
    weight_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("weight_versions.id"))
    basis: Mapped[IndexBasis] = mapped_column(enum_column(IndexBasis), default=IndexBasis.BOOK)
    variant: Mapped[IndexVariant] = mapped_column(enum_column(IndexVariant), default=IndexVariant.T)
    omega_preset: Mapped[str] = mapped_column(String(32), default="uniform")
    observation_start: Mapped[date | None] = mapped_column(Date)
    observation_end: Mapped[date | None] = mapped_column(Date)
    input_hash: Mapped[str | None] = mapped_column(String(64))
    output_hash: Mapped[str | None] = mapped_column(String(64))
    coverage_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    n_quotes: Mapped[int] = mapped_column(Integer, default=0)
    n_cells: Mapped[int] = mapped_column(Integer, default=0)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    diagnostics_json: Mapped[dict] = mapped_column(JSONType, default=dict)
    error_summary: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ElementaryCell(Base):
    __tablename__ = "elementary_cells"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("index_runs.id"), index=True)
    period: Mapped[date] = mapped_column(Date, index=True)
    route: Mapped[str] = mapped_column(String(16), index=True)
    carrier: Mapped[str] = mapped_column(String(8))
    apw_days: Mapped[int] = mapped_column(Integer)
    matched: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    laf: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    availability: Mapped[Decimal] = mapped_column(Numeric(12, 8), default=1)
    adjusted: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    n_matched: Mapped[int] = mapped_column(Integer, default=0)
    n_quotes: Mapped[int] = mapped_column(Integer, default=0)
    suppressed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PublishedIndexValue(Base):
    __tablename__ = "published_index_values"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "series",
            "period",
            "frequency",
            "route",
            "apw_days",
            name="uq_published_point",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("index_runs.id"), index=True)
    series: Mapped[str] = mapped_column(String(32), default="headline")
    period: Mapped[date] = mapped_column(Date, index=True)
    frequency: Mapped[IndexFrequency] = mapped_column(enum_column(IndexFrequency), default=IndexFrequency.DAILY)
    route: Mapped[str | None] = mapped_column(String(16))
    apw_days: Mapped[int | None] = mapped_column(Integer)
    value: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    se: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    ci_low: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    ci_high: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    coverage_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    n_matched: Mapped[int] = mapped_column(Integer, default=0)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    method_version: Mapped[str] = mapped_column(String(32), default="1.0.0")
    basket_version: Mapped[str] = mapped_column(String(64), default="basket-1.0.0")
    weights_version: Mapped[str] = mapped_column(String(64), default="v1")
    provenance_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class QualityCheck(Base):
    __tablename__ = "quality_checks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("index_runs.id"), nullable=True)
    observation_id: Mapped[uuid.UUID | None]
    code: Mapped[str] = mapped_column(String(64))
    disposition: Mapped[PublicationDisposition] = mapped_column(enum_column(PublicationDisposition))
    details: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReferenceObservation(Base):
    __tablename__ = "reference_observations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    dataset: Mapped[str] = mapped_column(String(32), index=True)
    period: Mapped[date] = mapped_column(Date, index=True)
    route: Mapped[str | None] = mapped_column(String(16))
    metric: Mapped[str] = mapped_column(String(64))
    value: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    unit: Mapped[str | None] = mapped_column(String(32))
    source_url: Mapped[str | None] = mapped_column(String(512))
    file_name: Mapped[str] = mapped_column(String(256))
    checksum: Mapped[str] = mapped_column(String(64), index=True)
    raw_row_json: Mapped[dict] = mapped_column(JSONType, default=dict)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BacktestResult(Base):
    __tablename__ = "backtest_results"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("index_runs.id"), nullable=True)
    comparator: Mapped[str] = mapped_column(String(64))
    status: Mapped[BacktestStatus] = mapped_column(enum_column(BacktestStatus), default=BacktestStatus.UNAVAILABLE)
    correlation: Mapped[Decimal | None] = mapped_column(Numeric(12, 8))
    mape: Mapped[Decimal | None] = mapped_column(Numeric(12, 8))
    overlap_months: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str | None] = mapped_column(Text)
    details_json: Mapped[dict] = mapped_column(JSONType, default=dict)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
