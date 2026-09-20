from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any

from app.domain.enums import AvailabilityState, CollectionStatus, CollectorModality
from app.domain.hashing import sha256_canonical
from app.domain.models import CanonicalFareObservation, FareQuery, SourceProfile, utcnow

PRICE_KEYS = {
    "totalfare",
    "total_fare",
    "totalamount",
    "total_amount",
    "grandtotal",
    "grossfare",
    "grossamount",
    "publishedfare",
    "offerprice",
    "offer_price",
    "amount",
    "fare",
    "price",
    "netfare",
    "adtamount",
}
ORIGIN_KEYS = {
    "origin",
    "from",
    "fromcode",
    "origincode",
    "originairport",
    "departureairport",
    "boardpoint",
    "fromairport",
    "departurestation",
}
DEST_KEYS = {
    "destination",
    "to",
    "tocode",
    "destinationcode",
    "destinationairport",
    "arrivalairport",
    "offpoint",
    "toairport",
    "arrivalstation",
}
DATE_KEYS = {
    "departuredate",
    "traveldate",
    "flightdate",
    "departuredatetime",
    "std",
    "departure",
    "date",
    "departs",
}
FLIGHT_KEYS = {
    "flightnumber",
    "flight_number",
    "flightno",
    "marketingflightnumber",
    "operatingflightnumber",
    "fltno",
}
CARRIER_KEYS = {
    "carrier",
    "airline",
    "airlinecode",
    "marketingcarrier",
    "operatingcarrier",
    "carriercode",
    "validatingcarrier",
}
BRAND_KEYS = {"farebrand", "brand", "farefamily", "productclass", "cabin", "bookingclass", "fareclass"}
FLIGHT_NUMBER_RE = re.compile(r"^[A-Z0-9]{2,3}\s?\d{1,4}[A-Z]?$")


@dataclass
class ParseOutcome:
    status: CollectionStatus
    observations: list[CanonicalFareObservation] = field(default_factory=list)
    message: str = ""


def coerce_money(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, dict):
        for key in ("amount", "value", "total", "fare", "price", "totalFare"):
            if key in value:
                found = coerce_money(value[key])
                if found is not None:
                    return found
        return None
    if isinstance(value, (list, tuple)) and value:
        return coerce_money(value[0])
    text = str(value).strip().lower().replace(",", "")
    for token in ("inr", "rs.", "rs", "₹", "usd", "eur"):
        text = text.replace(token, "")
    text = text.strip()
    if not text:
        return None
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return None
    if amount <= 0 or amount > Decimal("10000000"):
        return None
    return amount.quantize(Decimal("0.01"))


def coerce_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, dict):
        for key in ("date", "departureDate", "travelDate", "localDate"):
            if key in value:
                found = coerce_date(value[key])
                if found is not None:
                    return found
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "")).date()
    except ValueError:
        pass
    chunks = [text[:10], text[:8], text[:16], text[:19], text]
    formats = ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y", "%Y%m%d", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S")
    for chunk in chunks:
        for fmt in formats:
            try:
                return datetime.strptime(chunk, fmt).date()
            except ValueError:
                continue
    return None


def coerce_time(value: Any) -> time | None:
    if value is None:
        return None
    if isinstance(value, time):
        return value
    if isinstance(value, datetime):
        return value.time().replace(microsecond=0)
    text = str(value)
    match = re.search(r"(\d{1,2}):(\d{2})", text)
    if not match:
        return None
    hours = int(match.group(1))
    minutes = int(match.group(2))
    if hours > 23 or minutes > 59:
        return None
    return time(hours, minutes)


def coerce_airport(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        for key in ("code", "iata", "iataCode", "airportCode", "airport", "stationCode"):
            if key in value:
                found = coerce_airport(value[key])
                if found is not None:
                    return found
        return None
    text = str(value).strip().upper()
    if re.fullmatch(r"[A-Z]{3}", text):
        return text
    return None


def coerce_carrier(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        for key in ("code", "iata", "carrierCode", "airlineCode"):
            if key in value:
                found = coerce_carrier(value[key])
                if found is not None:
                    return found
        return None
    text = str(value).strip().upper().replace(" ", "")
    if re.fullmatch(r"[A-Z0-9]{2,3}", text):
        return text
    return None


def coerce_flight_number(value: Any, carrier: str | None = None) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper().replace(" ", "")
    if not text:
        return None
    if re.fullmatch(r"\d{1,4}[A-Z]?", text) and carrier:
        text = f"{carrier}{text}"
    if FLIGHT_NUMBER_RE.match(text):
        return text
    return None


def _lookup(record: dict[str, Any], keys: set[str]) -> Any:
    for key, value in record.items():
        compact = re.sub(r"[^a-z0-9]", "", str(key).lower())
        if compact in keys and value not in (None, "", [], {}):
            return value
    return None


def extract_fares(
    payload: Any,
    query: FareQuery,
    source: SourceProfile,
    collector: CollectorModality,
    *,
    carrier_hint: str | None,
    parser_version: str,
    confidence: Decimal,
) -> ParseOutcome:
    found: list[CanonicalFareObservation] = []
    seen: set[str] = set()

    def consider(record: dict[str, Any], context: dict[str, Any]) -> None:
        merged = {**context, **{k: v for k, v in record.items() if v not in (None, "", [], {})}}
        origin = coerce_airport(_lookup(merged, ORIGIN_KEYS))
        dest = coerce_airport(_lookup(merged, DEST_KEYS))
        travel = coerce_date(_lookup(merged, DATE_KEYS))
        price = coerce_money(_lookup(merged, PRICE_KEYS))
        if origin is None or dest is None or travel is None or price is None:
            return
        if travel != query.travel_date or origin != query.origin or dest != query.destination:
            return
        carrier = coerce_carrier(_lookup(merged, CARRIER_KEYS)) or carrier_hint
        flight = coerce_flight_number(_lookup(merged, FLIGHT_KEYS), carrier)
        if flight is None:
            return
        if carrier is None:
            match = re.match(r"^([A-Z0-9]{2,3})(?=\d)", flight)
            if match is None:
                return
            carrier = match.group(1)
        brand = _lookup(merged, BRAND_KEYS)
        observation = CanonicalFareObservation(
            source=source.name,
            source_type=source.source_type,
            collector=collector,
            collected_at=utcnow(),
            origin_airport=origin,
            destination_airport=dest,
            travel_date=query.travel_date,
            booking_date=query.observation_date,
            lead_time_days=query.lead_time_days,
            carrier=carrier,
            flight_number=flight,
            departure_time=coerce_time(_lookup(merged, {"departuretime", "std", "departtime"})),
            arrival_time=coerce_time(_lookup(merged, {"arrivaltime", "sta", "arrivetime"})),
            cabin_class=str(brand or query.cabin_class),
            fare_brand=str(brand) if brand else None,
            total_fare=price,
            currency=query.currency,
            seat_or_fare_availability=AvailabilityState.AVAILABLE,
            extraction_confidence=confidence,
            raw_record_hash=sha256_canonical(
                {
                    "carrier": carrier,
                    "dest": dest,
                    "flight": flight,
                    "origin": origin,
                    "price": format(price, "f"),
                    "travel_date": travel.isoformat(),
                }
            ),
            parser_version=parser_version,
            is_simulated=False,
        )
        if observation.raw_record_hash in seen:
            return
        seen.add(observation.raw_record_hash)
        found.append(observation)

    def walk(node: Any, context: dict[str, Any]) -> None:
        if isinstance(node, dict):
            next_context = dict(context)
            origin = coerce_airport(_lookup(node, ORIGIN_KEYS))
            dest = coerce_airport(_lookup(node, DEST_KEYS))
            travel = coerce_date(_lookup(node, DATE_KEYS))
            carrier = coerce_carrier(_lookup(node, CARRIER_KEYS))
            if origin:
                next_context["origin"] = origin
            if dest:
                next_context["destination"] = dest
            if travel:
                next_context["departureDate"] = travel.isoformat()
            if carrier:
                next_context["carrier"] = carrier
            consider(node, next_context)
            for value in node.values():
                walk(value, next_context)
        elif isinstance(node, list):
            for item in node:
                walk(item, context)

    initial_context = {"carrier": carrier_hint} if carrier_hint else {}
    walk(payload, initial_context)
    if found:
        return ParseOutcome(status=CollectionStatus.SUCCESS, observations=found)
    return ParseOutcome(
        status=CollectionStatus.NO_RESULTS,
        message="No dated itinerary fares matching the query were present in the payload",
    )
