from __future__ import annotations

import json
from datetime import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from app.domain.enums import AvailabilityState, CollectionStatus, CollectorModality
from app.domain.hashing import sha256_canonical
from app.domain.models import CanonicalFareObservation, FareQuery, SourceProfile, utcnow

PARSER_NAME = "mock_fare"
PARSER_VERSION = "1.0.0"
FIXTURE_DIR = Path(__file__).parent / "fixtures"


class MockParseError(Exception):
    def __init__(self, status: CollectionStatus, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def load_fixture(name: str) -> Any:
    path = FIXTURE_DIR / name
    return json.loads(path.read_text(encoding="utf-8"))


def _money(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise MockParseError(CollectionStatus.INVALID_DATA, f"invalid money value: {value}") from exc
    if amount < 0:
        raise MockParseError(CollectionStatus.INVALID_DATA, "negative money is invalid")
    return amount.quantize(Decimal("0.01"))


def _availability(value: Any) -> AvailabilityState:
    if value is None:
        return AvailabilityState.UNKNOWN
    try:
        return AvailabilityState(str(value).lower())
    except ValueError:
        return AvailabilityState.UNKNOWN


def _time(value: Any) -> time | None:
    if not value:
        return None
    hours, minutes = str(value).split(":")[:2]
    return time(int(hours), int(minutes))


def parse_records(payload: Any, query: FareQuery, source: SourceProfile) -> list[CanonicalFareObservation]:
    if isinstance(payload, dict) and "offers" in payload:
        raise MockParseError(CollectionStatus.SOURCE_CHANGED, "unexpected offers layout")
    if not isinstance(payload, list):
        raise MockParseError(CollectionStatus.PARSER_ERROR, "fixture must be a list of fare records")

    observations: list[CanonicalFareObservation] = []
    for record in payload:
        if not isinstance(record, dict):
            raise MockParseError(CollectionStatus.PARSER_ERROR, "fare record must be an object")
        if "total_fare" not in record:
            raise MockParseError(CollectionStatus.INVALID_DATA, "total_fare is required")
        origin = str(record.get("origin") or query.origin)
        destination = str(record.get("destination") or query.destination)
        observations.append(
            CanonicalFareObservation(
                source=source.name,
                source_type=source.source_type,
                collector=CollectorModality.MOCK,
                collected_at=utcnow(),
                origin_airport=origin,
                destination_airport=destination,
                travel_date=query.travel_date,
                booking_date=query.observation_date,
                lead_time_days=query.lead_time_days,
                carrier=str(record.get("carrier") or "6E"),
                operating_carrier=record.get("operating_carrier"),
                flight_number=str(record.get("flight_number") or "UNK000"),
                departure_time=_time(record.get("departure_time")),
                arrival_time=_time(record.get("arrival_time")),
                cabin_class=str(record.get("cabin") or query.cabin_class),
                fare_brand=record.get("fare_brand"),
                fare_class=record.get("fare_class"),
                base_fare=_money(record.get("base_fare")),
                taxes=_money(record.get("taxes")),
                airport_fee=_money(record.get("airport_fee")),
                udf=_money(record.get("udf")),
                convenience_fee=_money(record.get("convenience_fee")),
                other_fee=_money(record.get("other_fee")),
                total_fare=_money(record["total_fare"]) or Decimal("0.00"),
                currency=str(record.get("currency") or query.currency),
                refundable=record.get("refundable"),
                baggage_allowance=record.get("baggage_allowance"),
                seat_or_fare_availability=_availability(record.get("availability")),
                extraction_confidence=Decimal("0.90"),
                raw_record_hash=sha256_canonical(record),
                parser_version=PARSER_VERSION,
                is_simulated=True,
            )
        )
    return observations
