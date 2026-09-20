from datetime import date
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.api.schemas.common import SimulatedEnvelope
from app.config import DataMode


def decimal_string(value) -> str | None:
    if value is None:
        return None
    return format(value, "f")


class IndexPoint(BaseModel):
    period: date
    value: str
    se: str | None = None
    ci_low: str | None = None
    ci_high: str | None = None
    coverage_pct: str | None = None
    n_matched: int = 0
    route: str | None = None
    apw_days: int | None = None
    is_simulated: bool
    method_version: str
    basket_version: str
    weights_version: str
    frequency: str
    series: str


class IndexSeriesResponse(BaseModel):
    items: list[IndexPoint]
    run_id: UUID | None = None
    meta: SimulatedEnvelope


class CellResponse(BaseModel):
    period: date
    route: str
    carrier: str
    apw_days: int
    matched: str | None
    laf: str | None
    availability: str
    adjusted: str | None
    n_matched: int
    n_quotes: int
    suppressed: bool


class CellListResponse(BaseModel):
    items: list[CellResponse]
    run_id: UUID
    meta: SimulatedEnvelope


class CoverageResponse(BaseModel):
    run_id: UUID | None
    coverage_pct: str | None
    n_quotes: int = 0
    n_cells: int = 0
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    meta: SimulatedEnvelope


class MethodologyResponse(BaseModel):
    method_version: str
    variant: str
    basis: str
    omega_preset: str
    omega: dict[str, str]
    apw_windows: list[int]
    n_min: int
    notes: list[str]
    meta: SimulatedEnvelope


class BasketResponse(BaseModel):
    version: str
    name: str
    routes: list[str]
    lead_windows: list[int]
    carriers: list[str]
    config_hash: str
    meta: SimulatedEnvelope


class WeightsResponse(BaseModel):
    version: str
    source: str
    checksum: str | None
    route_weights: dict[str, str]
    carrier_weights: dict[str, dict[str, str]]
    meta: SimulatedEnvelope


class ProvenanceResponse(BaseModel):
    run_id: UUID | None
    input_hash: str | None
    output_hash: str | None
    method_version: str | None
    basket_version: str | None
    weights_version: str | None
    is_simulated: bool
    meta: SimulatedEnvelope


class BacktestResponse(BaseModel):
    id: UUID | None = None
    comparator: str
    status: str
    correlation: str | None = None
    mape: str | None = None
    overlap_months: int = 0
    notes: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    meta: SimulatedEnvelope


class ElasticityResponse(BaseModel):
    items: list[dict[str, Any]]
    meta: SimulatedEnvelope


class StatusResponse(BaseModel):
    data_mode: DataMode
    egress_mode: str
    is_simulated: bool
    notice: str | None
    latest_run_id: UUID | None = None
    latest_run_status: str | None = None
    blocked_sources: int = 0
    enabled_sources: int = 0
    pending_jobs: int = 0
    banner: Literal["mock", "live", "unavailable", "policy_denied"]
    meta: SimulatedEnvelope
