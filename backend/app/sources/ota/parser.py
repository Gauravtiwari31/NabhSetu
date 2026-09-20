from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.domain.enums import AvailabilityState, CollectionStatus, CollectorModality
from app.domain.hashing import sha256_canonical
from app.domain.models import CanonicalFareObservation, FareQuery, SourceProfile, utcnow
from app.sources.common.fare_extract import ParseOutcome, coerce_money, coerce_time

PARSER_NAME = "ota_dom_cards"
PARSER_VERSION = "1.0.0"

FLIGHT_RE = re.compile(r"\b([A-Z0-9]{2})\s*-\s*(\d{1,4}[A-Z]?)\b")
AIRPORT_RE = re.compile(r"\(([A-Z]{3})\)")
PRICE_RE = re.compile(r"₹\s*([\d,]+(?:\.\d{1,2})?)")
TIME_RE = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")


def _query_matches_page(page_url: str, query: FareQuery) -> bool:
    parsed = urlparse(page_url)
    if not parsed.path.startswith("/flight-search/listing"):
        return False
    search = parse_qs(parsed.query).get("srch", [""])[0]
    parts = search.split("|")
    if len(parts) < 3:
        return False
    try:
        travel_date = datetime.strptime(parts[2], "%d/%m/%Y").date()
    except ValueError:
        return False
    return (
        parts[0].upper().startswith(query.origin + "-")
        and parts[1].upper().startswith(query.destination + "-")
        and travel_date == query.travel_date
    )


def _parse_card(
    text: str,
    query: FareQuery,
    source: SourceProfile,
    collector: CollectorModality,
    confidence: Decimal,
) -> CanonicalFareObservation | None:
    flight_match = FLIGHT_RE.search(text.upper())
    airports = AIRPORT_RE.findall(text.upper())
    price_match = PRICE_RE.search(text)
    if flight_match is None or len(airports) < 2 or price_match is None:
        return None
    origin, destination = airports[0], airports[1]
    if origin != query.origin or destination != query.destination:
        return None
    carrier = flight_match.group(1)
    flight_number = f"{carrier}{flight_match.group(2)}"
    total_fare = coerce_money(price_match.group(1))
    if total_fare is None:
        return None
    times = [match.group(0) for match in TIME_RE.finditer(text)]
    raw = {
        "carrier": carrier,
        "destination": destination,
        "flight_number": flight_number,
        "origin": origin,
        "total_fare": format(total_fare, "f"),
        "travel_date": query.travel_date.isoformat(),
    }
    return CanonicalFareObservation(
        source=source.name,
        source_type=source.source_type,
        collector=collector,
        collected_at=utcnow(),
        origin_airport=origin,
        destination_airport=destination,
        travel_date=query.travel_date,
        booking_date=query.observation_date,
        lead_time_days=query.lead_time_days,
        carrier=carrier,
        flight_number=flight_number,
        departure_time=coerce_time(times[0]) if times else None,
        arrival_time=coerce_time(times[1]) if len(times) > 1 else None,
        cabin_class=query.cabin_class,
        fare_brand="OTA_LISTED",
        total_fare=total_fare,
        currency=query.currency,
        seat_or_fare_availability=AvailabilityState.AVAILABLE,
        extraction_confidence=confidence,
        raw_record_hash=sha256_canonical(raw),
        parser_version=PARSER_VERSION,
        is_simulated=False,
    )


def parse_easemytrip_dom(
    payload: Any,
    query: FareQuery,
    source: SourceProfile,
    collector: CollectorModality,
    confidence: Decimal,
) -> ParseOutcome:
    if not isinstance(payload, dict):
        return ParseOutcome(status=CollectionStatus.NO_RESULTS)
    page_url = str(payload.get("page_url") or "")
    records = payload.get("dom_records")
    if not _query_matches_page(page_url, query) or not isinstance(records, list):
        return ParseOutcome(
            status=CollectionStatus.NO_RESULTS,
            message="OTA DOM payload did not match the requested route and date",
        )
    observations: list[CanonicalFareObservation] = []
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, str):
            continue
        observation = _parse_card(record, query, source, collector, confidence)
        if observation is None or observation.raw_record_hash in seen:
            continue
        seen.add(observation.raw_record_hash)
        observations.append(observation)
    if observations:
        return ParseOutcome(status=CollectionStatus.SUCCESS, observations=observations)
    return ParseOutcome(
        status=CollectionStatus.NO_RESULTS,
        message="No matching dated itinerary cards were present in the OTA result page",
    )
