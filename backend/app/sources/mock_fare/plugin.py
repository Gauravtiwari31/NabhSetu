from __future__ import annotations

from app.acquisition.base import BaseCollector
from app.config import DataMode, Settings
from app.domain.enums import CollectionStatus, CollectorModality, HttpResponseCategory, SourceType
from app.domain.hashing import canonical_dumps, sha256_hex
from app.domain.models import (
    CollectionError,
    CollectionResult,
    ComplianceLease,
    EgressSelection,
    FareQuery,
    PayloadReference,
    SourceProfile,
    utcnow,
)
from app.sources.mock_fare.normaliser import normalise_observation
from app.sources.mock_fare.parser import (
    PARSER_NAME,
    PARSER_VERSION,
    MockParseError,
    load_fixture,
    parse_records,
)


class MockCollector(BaseCollector):
    identity = CollectorModality.MOCK
    parser_name = PARSER_NAME
    parser_version = PARSER_VERSION

    def __init__(self, settings: Settings, fixture_name: str = "valid.json") -> None:
        self.settings = settings
        self.fixture_name = fixture_name

    async def supports(self, source: SourceProfile) -> bool:
        return (
            self.settings.data_mode == DataMode.MOCK
            and source.source_type == SourceType.MOCK
            and source.capabilities.preferred_adapter == CollectorModality.MOCK
        )

    async def collect(
        self,
        query: FareQuery,
        source: SourceProfile,
        *,
        lease: ComplianceLease,
        egress: EgressSelection | None,
    ) -> CollectionResult:
        started = utcnow()
        if not lease.is_valid(started):
            return CollectionResult(
                source_id=source.id,
                collector=self.identity,
                status=CollectionStatus.POLICY_DENIED,
                requested_at=started,
                completed_at=utcnow(),
                errors=[CollectionError(code="LEASE_INVALID", message="Compliance lease is not valid")],
                is_simulated=True,
            )
        try:
            payload = load_fixture(self.fixture_name)
            raw = canonical_dumps(payload)
            observations = [
                normalise_observation(item) for item in parse_records(payload, query, source)
            ]
        except MockParseError as exc:
            return CollectionResult(
                source_id=source.id,
                collector=self.identity,
                status=exc.status,
                requested_at=started,
                completed_at=utcnow(),
                parser_name=self.parser_name,
                parser_version=self.parser_version,
                errors=[CollectionError(code=exc.status.value.upper(), message=exc.message)],
                is_simulated=True,
                http_response_category=HttpResponseCategory.SIMULATED,
            )

        payload_hash = sha256_hex(raw)
        return CollectionResult(
            source_id=source.id,
            collector=self.identity,
            status=CollectionStatus.SUCCESS if observations else CollectionStatus.NO_RESULTS,
            requested_at=started,
            completed_at=utcnow(),
            raw_payload_reference=PayloadReference(
                content_hash=payload_hash,
                media_type="application/json",
                byte_size=len(raw.encode("utf-8")),
                capture_method="mock_fixture",
            ),
            payload_hash=payload_hash,
            parser_name=self.parser_name,
            parser_version=self.parser_version,
            observations=observations,
            metadata={"fixture": self.fixture_name, "lease_id": str(lease.lease_id)},
            is_simulated=True,
            http_response_category=HttpResponseCategory.SIMULATED,
        )
