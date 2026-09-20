from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.config import DataMode
from app.domain.enums import CollectionStatus, CollectorModality, JobStatus
from app.domain.models import CollectionError, FareQuery, ProvenanceLink

SIMULATED_NOTICE = (
    "This payload is simulated/demo data and is not a measurement of Indian airfares."
)


class SimulatedEnvelope(BaseModel):
    is_simulated: bool
    data_mode: DataMode
    notice: str | None = None


class CollectionJobCreate(BaseModel):
    origin: str
    destination: str
    travel_date: date | None = None
    observation_date: date | None = None
    lead_time_days: int | None = None
    passengers: int = Field(default=1, ge=1, le=9)
    cabin_class: str = "ECONOMY"
    currency: str = "INR"
    source_id: UUID | None = None


class CollectionJobResponse(BaseModel):
    id: UUID
    status: JobStatus
    query: FareQuery
    result_status: CollectionStatus | None = None
    collector: CollectorModality | None = None
    is_simulated: bool
    observation_ids: list[UUID]
    errors: list[CollectionError]
    provenance: list[ProvenanceLink]
    meta: SimulatedEnvelope


class SourceStatusResponse(BaseModel):
    id: UUID
    name: str
    enabled: bool
    source_type: str
    preferred_adapter: str | None
    last_successful_adapter: str | None
    temporarily_blocked: bool
    restriction_reason: str | None
    robots_status: str
    terms_review_status: str
    circuit: dict
    network_policy: dict
    meta: SimulatedEnvelope


class FareObservationResponse(BaseModel):
    observation_id: UUID
    origin: str
    destination: str
    travel_date: date
    lead_time_days: int
    carrier: str
    flight_number: str
    total_fare: str
    currency: str
    availability: str
    disposition: str
    quality_score: str
    is_simulated: bool
    collector: str
    collected_at: str


class FareListResponse(BaseModel):
    items: list[FareObservationResponse]
    meta: SimulatedEnvelope


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    service: str
    version: str
    data_mode: DataMode
    egress_mode: str
    database: str
    is_simulated: bool
    notice: str | None = None
