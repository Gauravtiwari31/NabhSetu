from __future__ import annotations

from decimal import Decimal
from urllib.parse import parse_qs, urlparse

from app.domain.enums import AvailabilityState, CollectionStatus, CollectorModality
from app.domain.hashing import sha256_canonical
from app.domain.models import CanonicalFareObservation, FareQuery, SourceProfile, utcnow
from app.sources.common.fare_extract import ParseOutcome, coerce_date, coerce_money, coerce_time

PARSER_NAME = "akasa_availability"
PARSER_VERSION = "1.0.0"


def _money_from_charges(passenger_fare: dict) -> tuple[Decimal | None, Decimal | None, Decimal | None, Decimal | None, Decimal]:
    charges = passenger_fare.get("serviceCharges") or []
    base = coerce_money(passenger_fare.get("publishedFare") or passenger_fare.get("fareAmount"))
    taxes = Decimal("0.00")
    udf = Decimal("0.00")
    other = Decimal("0.00")
    for charge in charges:
        amount = coerce_money(charge.get("amount"))
        if amount is None:
            continue
        kind = str(charge.get("type") or "")
        code = str(charge.get("code") or "")
        if kind == "FarePrice":
            base = amount
        elif kind == "Tax" or code.upper() in {"GST", "IGST", "CGST", "SGST"}:
            taxes += amount
        elif code.upper() in {"UDF", "DUDF"}:
            udf += amount
        elif kind == "TravelFee":
            other += amount
    total = coerce_money(passenger_fare.get("fareAmount"))
    if total is None:
        parts = [item for item in (base, taxes, udf, other) if item is not None]
        total = sum(parts, Decimal("0.00"))
    return base, taxes if taxes else None, udf if udf else None, other if other else None, total


def _observation(
    *,
    query: FareQuery,
    source: SourceProfile,
    collector: CollectorModality,
    confidence: Decimal,
    origin: str,
    destination: str,
    carrier: str,
    flight_number: str,
    travel_date,
    departure,
    arrival,
    total: Decimal,
    base=None,
    taxes=None,
    udf=None,
    other=None,
    fare_class: str | None = None,
    fare_brand: str | None = None,
    raw: dict,
) -> CanonicalFareObservation:
    return CanonicalFareObservation(
        source=source.name,
        source_type=source.source_type,
        collector=collector,
        collected_at=utcnow(),
        origin_airport=origin,
        destination_airport=destination,
        travel_date=travel_date,
        booking_date=query.observation_date,
        lead_time_days=query.lead_time_days,
        carrier=carrier,
        flight_number=flight_number,
        departure_time=coerce_time(departure),
        arrival_time=coerce_time(arrival),
        cabin_class=query.cabin_class,
        fare_brand=fare_brand,
        fare_class=fare_class,
        base_fare=base,
        taxes=taxes,
        udf=udf,
        other_fee=other,
        total_fare=total,
        currency=query.currency,
        seat_or_fare_availability=AvailabilityState.AVAILABLE,
        extraction_confidence=confidence,
        raw_record_hash=sha256_canonical(raw),
        parser_version=PARSER_VERSION,
        is_simulated=False,
    )


def _calendar(payload, query: FareQuery, source, collector, confidence, url: str) -> list[CanonicalFareObservation]:
    data = payload.get("data") if isinstance(payload, dict) else payload
    if not (isinstance(data, list) and data and isinstance(data[0], dict) and "price" in data[0] and "date" in data[0]):
        return []
    origin, destination = query.origin, query.destination
    qs = parse_qs(urlparse(url).query)
    if qs.get("origin") and qs.get("destination"):
        origin = qs["origin"][0].upper()
        destination = qs["destination"][0].upper()
    if origin != query.origin or destination != query.destination:
        return []
    found: list[CanonicalFareObservation] = []
    for row in data:
        if row.get("soldOut") or row.get("noFlights"):
            continue
        travel = coerce_date(row.get("date"))
        price = coerce_money(row.get("price"))
        if travel != query.travel_date or price is None:
            continue
        found.append(
            _observation(
                query=query,
                source=source,
                collector=collector,
                confidence=confidence,
                origin=origin,
                destination=destination,
                carrier="QP",
                flight_number="UNSPECIFIED",
                travel_date=travel,
                departure=None,
                arrival=None,
                total=price,
                fare_brand="calendar_lowest",
                raw={"date": row.get("date"), "price": row.get("price"), "origin": origin, "destination": destination},
            )
        )
    return found


def _journeys(payload, query: FareQuery, source, collector, confidence) -> list[CanonicalFareObservation]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict) or "faresAvailable" not in data or "results" not in data:
        return []
    fare_map: dict = {}
    for item in data.get("faresAvailable") or []:
        if not isinstance(item, dict):
            continue
        value = item.get("value") or {}
        if item.get("key"):
            fare_map[item["key"]] = value
        key = value.get("fareAvailabilityKey")
        if key:
            fare_map[key] = value
    found: list[CanonicalFareObservation] = []
    for result in data.get("results") or []:
        for trip in result.get("trips") or []:
            trip_date = coerce_date(trip.get("date"))
            markets = trip.get("journeysAvailableByMarket") or []
            for market in markets:
                journeys = market.get("value") if isinstance(market, dict) else None
                if not isinstance(journeys, list):
                    continue
                for journey in journeys:
                    designator = journey.get("designator") or {}
                    origin = str(designator.get("origin") or "").upper()
                    destination = str(designator.get("destination") or "").upper()
                    if origin != query.origin or destination != query.destination:
                        continue
                    travel = coerce_date(designator.get("departure")) or trip_date
                    if travel != query.travel_date:
                        continue
                    segments = journey.get("segments") or []
                    ident = (segments[0].get("identifier") if segments else {}) or {}
                    carrier = str(ident.get("carrierCode") or "QP")
                    number = str(ident.get("identifier") or "").strip()
                    if not number:
                        continue
                    flight_number = f"{carrier}{number}".replace(" ", "")
                    cheapest = None
                    cheapest_meta = None
                    for fare in journey.get("fares") or []:
                        value = fare_map.get(fare.get("fareAvailabilityKey"))
                        if not value:
                            continue
                        totals = value.get("totals") or {}
                        passenger = ((value.get("fares") or [{}])[0].get("passengerFares") or [{}])[0]
                        base, taxes, udf, other, total = _money_from_charges(passenger)
                        total = coerce_money(totals.get("fareTotal")) or total
                        if total is None:
                            continue
                        if cheapest is None or total < cheapest:
                            cheapest = total
                            cheapest_meta = {
                                "base": base,
                                "taxes": taxes,
                                "udf": udf,
                                "other": other,
                                "class": (value.get("fares") or [{}])[0].get("classOfService"),
                                "brand": (value.get("fares") or [{}])[0].get("productClass"),
                            }
                    if cheapest is None or cheapest_meta is None:
                        continue
                    found.append(
                        _observation(
                            query=query,
                            source=source,
                            collector=collector,
                            confidence=confidence,
                            origin=origin,
                            destination=destination,
                            carrier=carrier,
                            flight_number=flight_number,
                            travel_date=travel,
                            departure=designator.get("departure"),
                            arrival=designator.get("arrival"),
                            total=cheapest,
                            base=cheapest_meta["base"],
                            taxes=cheapest_meta["taxes"],
                            udf=cheapest_meta["udf"],
                            other=cheapest_meta["other"],
                            fare_class=cheapest_meta["class"],
                            fare_brand=cheapest_meta["brand"],
                            raw={
                                "flight": flight_number,
                                "origin": origin,
                                "destination": destination,
                                "total": format(cheapest, "f"),
                                "departure": designator.get("departure"),
                            },
                        )
                    )
    return found


def parse_akasa(
    payload,
    query: FareQuery,
    source: SourceProfile,
    collector: CollectorModality,
    confidence: Decimal,
    url: str = "",
) -> ParseOutcome:
    journeys = _journeys(payload, query, source, collector, confidence)
    if journeys:
        return ParseOutcome(status=CollectionStatus.SUCCESS, observations=journeys)
    calendar = _calendar(payload, query, source, collector, confidence, url)
    if calendar:
        return ParseOutcome(status=CollectionStatus.SUCCESS, observations=calendar)
    return ParseOutcome(
        status=CollectionStatus.NO_RESULTS,
        message="Akasa payload contained no matching dated itineraries",
    )
