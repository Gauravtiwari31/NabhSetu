"""Pydantic domain models for acquisition, compliance, and fare observations."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.enums import (
    ALLOWED_LEAD_TIMES,
    AvailabilityState,
    CircuitState,
    CollectionStatus,
    CollectorModality,
    ComplianceDecision,
    EgressMode,
    HttpResponseCategory,
    JobStatus,
    NetworkFailureCategory,
    ReviewStatus,
    RobotsStatus,
    RotationStrategy,
    SourceType,
    ValidationDisposition,
)
from app.domain.hashing import sha256_canonical

IATA_AIRPORT = re.compile(r"^[A-Z]{3}$")
IATA_CARRIER = re.compile(r"^[A-Z0-9]{2,3}$")
CURRENCY = re.compile(r"^[A-Z]{3}$")


def utcnow() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class FareQuery(StrictModel):
    origin: str
    destination: str
    travel_date: date
    observation_date: date
    lead_time_days: int
    passengers: int = Field(default=1, ge=1, le=9)
    cabin_class: str = "ECONOMY"
    currency: str = "INR"
    source_id: UUID | None = None

    @field_validator("origin", "destination")
    @classmethod
    def airport_code(cls, value: str) -> str:
        code = value.upper()
        if not IATA_AIRPORT.match(code):
            raise ValueError("airport identifiers must be 3-letter IATA codes")
        return code

    @field_validator("currency", "cabin_class")
    @classmethod
    def upper_token(cls, value: str) -> str:
        return value.upper()

    @field_validator("currency")
    @classmethod
    def currency_code(cls, value: str) -> str:
        if not CURRENCY.match(value):
            raise ValueError("currency must be a 3-letter ISO code")
        return value

    @model_validator(mode="after")
    def dates_and_lead_time(self) -> Self:
        if self.origin == self.destination:
            raise ValueError("origin and destination must differ")
        if self.lead_time_days not in ALLOWED_LEAD_TIMES:
            raise ValueError(f"lead_time_days must be one of {ALLOWED_LEAD_TIMES}")
        actual = (self.travel_date - self.observation_date).days
        if actual != self.lead_time_days:
            raise ValueError("travel_date - observation_date must equal lead_time_days")
        return self

    def identity_payload(self) -> dict[str, Any]:
        return {
            "cabin_class": self.cabin_class,
            "currency": self.currency,
            "destination": self.destination,
            "lead_time_days": self.lead_time_days,
            "observation_date": self.observation_date.isoformat(),
            "origin": self.origin,
            "passengers": self.passengers,
            "source_id": str(self.source_id) if self.source_id else None,
            "travel_date": self.travel_date.isoformat(),
        }

    def identity_hash(self) -> str:
        return sha256_canonical(self.identity_payload())


class FareComponent(StrictModel):
    base_fare: Decimal | None = None
    taxes: Decimal | None = None
    airport_fee: Decimal | None = None
    udf: Decimal | None = None
    convenience_fee: Decimal | None = None
    other_fee: Decimal | None = None
    total_fare: Decimal

    @field_validator(
        "base_fare",
        "taxes",
        "airport_fee",
        "udf",
        "convenience_fee",
        "other_fee",
        "total_fare",
    )
    @classmethod
    def non_negative_money(cls, value: Decimal | None) -> Decimal | None:
        if value is None:
            return None
        if value < 0:
            raise ValueError("money fields must be non-negative")
        return value.quantize(Decimal("0.01"))


class CanonicalFareObservation(StrictModel):
    observation_id: UUID = Field(default_factory=uuid4)
    source: str
    source_type: SourceType
    collector: CollectorModality
    collected_at: datetime
    origin_airport: str
    destination_airport: str
    travel_date: date
    booking_date: date
    lead_time_days: int
    carrier: str
    operating_carrier: str | None = None
    flight_number: str
    departure_time: time | None = None
    arrival_time: time | None = None
    cabin_class: str
    fare_brand: str | None = None
    fare_class: str | None = None
    base_fare: Decimal | None = None
    taxes: Decimal | None = None
    airport_fee: Decimal | None = None
    udf: Decimal | None = None
    convenience_fee: Decimal | None = None
    other_fee: Decimal | None = None
    total_fare: Decimal
    currency: str = "INR"
    refundable: bool | None = None
    baggage_allowance: str | None = None
    seat_or_fare_availability: AvailabilityState = AvailabilityState.UNKNOWN
    extraction_confidence: Decimal = Decimal("0.90")
    raw_record_hash: str
    parser_version: str
    is_simulated: bool = False
    duplicate_key: str | None = None

    @field_validator("origin_airport", "destination_airport")
    @classmethod
    def airport_code(cls, value: str) -> str:
        code = value.upper()
        if not IATA_AIRPORT.match(code):
            raise ValueError("airport identifiers must be 3-letter IATA codes")
        return code

    @field_validator("carrier", "operating_carrier")
    @classmethod
    def carrier_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        code = value.upper()
        if not IATA_CARRIER.match(code):
            raise ValueError("carrier identifiers must be 2-3 character IATA codes")
        return code

    @field_validator(
        "base_fare",
        "taxes",
        "airport_fee",
        "udf",
        "convenience_fee",
        "other_fee",
        "total_fare",
        "extraction_confidence",
    )
    @classmethod
    def non_negative(cls, value: Decimal | None) -> Decimal | None:
        if value is None:
            return None
        if value < 0:
            raise ValueError("numeric fields must be non-negative")
        return value

    @field_validator("collected_at")
    @classmethod
    def timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("collected_at must be timezone-aware")
        return value

    def components(self) -> FareComponent:
        return FareComponent(
            base_fare=self.base_fare,
            taxes=self.taxes,
            airport_fee=self.airport_fee,
            udf=self.udf,
            convenience_fee=self.convenience_fee,
            other_fee=self.other_fee,
            total_fare=self.total_fare,
        )

    def dedup_payload(self, bucket_seconds: int = 60) -> dict[str, Any]:
        collected = int(self.collected_at.timestamp())
        bucket = collected - (collected % bucket_seconds)
        departure = self.departure_time.isoformat() if self.departure_time else None
        return {
            "bucket": bucket,
            "carrier": self.carrier,
            "destination": self.destination_airport,
            "fare_class": self.fare_class,
            "flight_number": self.flight_number,
            "origin": self.origin_airport,
            "source": self.source,
            "total_fare": format(self.total_fare, "f"),
            "travel_date": self.travel_date.isoformat(),
            "departure_time": departure,
        }

    def compute_duplicate_key(self, bucket_seconds: int = 60) -> str:
        return sha256_canonical(self.dedup_payload(bucket_seconds))


class CollectionError(StrictModel):
    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class PayloadReference(StrictModel):
    artifact_id: UUID | None = None
    content_hash: str
    media_type: str = "application/json"
    byte_size: int = 0
    storage_uri: str | None = None
    capture_method: str = "in_memory"


class CollectionResult(StrictModel):
    source_id: UUID
    collector: CollectorModality
    status: CollectionStatus
    requested_at: datetime
    completed_at: datetime
    raw_payload_reference: PayloadReference | None = None
    payload_hash: str | None = None
    parser_name: str | None = None
    parser_version: str | None = None
    observations: list[CanonicalFareObservation] = Field(default_factory=list)
    errors: list[CollectionError] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    is_simulated: bool = False
    egress_id: UUID | None = None
    egress_region: str | None = None
    session_id: UUID | None = None
    http_response_category: HttpResponseCategory = HttpResponseCategory.NONE
    failover_count: int = 0
    network_failure_category: NetworkFailureCategory = NetworkFailureCategory.NONE


class SourceCapabilities(StrictModel):
    public_api: bool = False
    static_html: bool = False
    embedded_json: bool = False
    requires_javascript: bool = False
    browser_network_json: bool = False
    documents_available: bool = False
    structured_feed: bool = False
    session_required: bool = False
    preferred_adapter: CollectorModality | None = None
    last_successful_adapter: CollectorModality | None = None
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    success_rate: Decimal | None = None
    average_latency_ms: Decimal | None = None
    notes: str | None = None


class SourcePolicy(StrictModel):
    minimum_interval_seconds: int = Field(ge=0)
    maximum_concurrency: int = Field(ge=1)
    daily_request_limit: int = Field(ge=1)
    allowed_paths: list[str] = Field(default_factory=lambda: ["*"])
    blocked_paths: list[str] = Field(default_factory=list)
    allowed_routes: list[str] = Field(default_factory=lambda: ["*"])
    notes: str | None = None
    policy_checked_at: datetime | None = None
    policy_version: str = "1"


class SourceNetworkPolicy(StrictModel):
    egress_mode: EgressMode = EgressMode.DIRECT
    allowed_regions: list[str] = Field(default_factory=list)
    preferred_region: str | None = None
    maximum_egress_nodes: int = Field(default=1, ge=1)
    rotation_strategy: RotationStrategy = RotationStrategy.NONE
    sticky_session_required: bool = False
    session_ttl_seconds: int = Field(default=300, ge=1)
    cooldown_seconds: int = Field(default=30, ge=0)
    cooldown_after_429_seconds: int = Field(default=60, ge=0)
    enabled: bool = True
    network_policy_version: str = "1"


class AdapterStats(StrictModel):
    adapter: CollectorModality
    success_count: int = 0
    failure_count: int = 0
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    average_latency_ms: Decimal | None = None
    circuit_state: CircuitState = CircuitState.CLOSED
    consecutive_failures: int = 0
    cooldown_until: datetime | None = None
    last_failure_kind: CollectionStatus | None = None


class SourceProfile(StrictModel):
    id: UUID
    name: str
    base_url: str
    source_type: SourceType
    enabled: bool
    automation_allowed: bool
    robots_status: RobotsStatus
    terms_review_status: ReviewStatus
    robots_checked_at: datetime | None = None
    terms_checked_at: datetime | None = None
    temporarily_blocked: bool = False
    restriction_reason: str | None = None
    capabilities: SourceCapabilities
    policy: SourcePolicy
    network_policy: SourceNetworkPolicy
    adapter_stats: list[AdapterStats] = Field(default_factory=list)

    def stats_for(self, adapter: CollectorModality) -> AdapterStats | None:
        for row in self.adapter_stats:
            if row.adapter == adapter:
                return row
        return None


class ComplianceLease(StrictModel):
    lease_id: UUID
    source_id: UUID
    issued_at: datetime
    expires_at: datetime
    policy_version: str
    reason_codes: list[str] = Field(default_factory=list)

    def is_valid(self, now: datetime | None = None) -> bool:
        moment = now or utcnow()
        return self.issued_at <= moment < self.expires_at


class ComplianceEvaluation(StrictModel):
    decision: ComplianceDecision
    reason_codes: list[str] = Field(default_factory=list)
    policy_version: str
    lease: ComplianceLease | None = None
    retry_after_seconds: int | None = None


class EgressSelection(StrictModel):
    node_id: UUID
    provider: str
    region: str | None = None
    endpoint_reference: str
    mode: EgressMode
    session_id: UUID | None = None
    failover_count: int = 0
    failover_reason: NetworkFailureCategory | None = None
    sticky: bool = False


class EgressSession(StrictModel):
    session_id: UUID
    source_id: UUID
    egress_id: UUID
    created_at: datetime
    expires_at: datetime
    request_count: int = 0
    closed: bool = False


class ProvenanceLink(StrictModel):
    entity_type: str
    entity_id: UUID
    parent_type: str | None = None
    parent_id: UUID | None = None
    relation: str
    content_hash: str | None = None


class ValidationFlag(StrictModel):
    code: str
    message: str
    disposition: ValidationDisposition
    details: dict[str, Any] = Field(default_factory=dict)


class CollectionJobView(StrictModel):
    id: UUID
    status: JobStatus
    query: FareQuery
    source_id: UUID | None = None
    result_status: CollectionStatus | None = None
    is_simulated: bool = False
    created_at: datetime
    completed_at: datetime | None = None
    observation_ids: list[UUID] = Field(default_factory=list)
    errors: list[CollectionError] = Field(default_factory=list)
    provenance: list[ProvenanceLink] = Field(default_factory=list)
    collector: CollectorModality | None = None
    request_id: str | None = None
