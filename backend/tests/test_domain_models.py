from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.domain.enums import CollectorModality, SourceType
from app.domain.hashing import sha256_canonical
from app.domain.models import CanonicalFareObservation, FareQuery
from tests.conftest import make_query


def test_fare_query_requires_matching_lead_time() -> None:
    with pytest.raises(ValidationError):
        FareQuery(
            origin="DEL",
            destination="BOM",
            observation_date=date(2026, 9, 20),
            travel_date=date(2026, 9, 22),
            lead_time_days=7,
        )


def test_fare_query_rejects_unknown_lead_time() -> None:
    with pytest.raises(ValidationError):
        make_query(lead_time_days=2, travel_date=date(2026, 9, 22))


def test_fare_query_normalises_iata_and_is_deterministic() -> None:
    first = make_query(origin="del", destination="bom")
    second = make_query(origin="DEL", destination="BOM")
    assert first.origin == "DEL"
    assert first.identity_hash() == second.identity_hash()
    assert first.identity_hash() == sha256_canonical(first.identity_payload())


def test_money_fields_reject_negatives() -> None:
    with pytest.raises(ValidationError):
        CanonicalFareObservation(
            source="MockFareSource",
            source_type=SourceType.MOCK,
            collector=CollectorModality.MOCK,
            collected_at=datetime(2026, 9, 20, 12, 0, 0, tzinfo=UTC),
            origin_airport="DEL",
            destination_airport="BOM",
            travel_date=date(2026, 9, 27),
            booking_date=date(2026, 9, 20),
            lead_time_days=7,
            carrier="6E",
            flight_number="6E201",
            cabin_class="ECONOMY",
            total_fare=Decimal("-1.00"),
            raw_record_hash="abc",
            parser_version="1",
        )


def test_duplicate_key_is_stable_inside_a_time_bucket() -> None:
    collected = datetime(2026, 9, 20, 12, 0, 5, tzinfo=UTC)
    first = CanonicalFareObservation(
        source="MockFareSource",
        source_type=SourceType.MOCK,
        collector=CollectorModality.MOCK,
        collected_at=collected,
        origin_airport="DEL",
        destination_airport="BOM",
        travel_date=date(2026, 9, 27),
        booking_date=date(2026, 9, 20),
        lead_time_days=7,
        carrier="6E",
        flight_number="6E201",
        cabin_class="ECONOMY",
        total_fare=Decimal("5700.00"),
        raw_record_hash="abc",
        parser_version="1",
    )
    second = first.model_copy(update={"collected_at": collected + timedelta(seconds=10)})
    assert first.compute_duplicate_key(60) == second.compute_duplicate_key(60)
