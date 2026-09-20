from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal

from apix_index.types import Quote
from app.database.models.observations import NormalisedObservation
from app.domain.enums import AvailabilityState, PublicationDisposition
from app.domain.models import CanonicalFareObservation, ValidationFlag, ensure_utc, utcnow
from app.quality.cells import cell_outlier_flags, tukey_fences, winsorise
from app.quality.gates import freshness_flag, sold_out_flag
from app.quality.mapping import map_publication_disposition
from app.quality.validation import validate_observation


def observation_to_quote(
    row: NormalisedObservation,
    *,
    price: Decimal | None = None,
    disposition: PublicationDisposition | None = None,
) -> Quote:
    mapped = disposition or row.publication_disposition
    return Quote(
        collected_date=row.booking_date,
        departure_date=row.travel_date,
        route=f"{row.origin_airport}-{row.destination_airport}",
        carrier=row.carrier,
        apw_days=row.lead_time_days,
        flight_number=row.flight_number,
        fare_family=row.fare_brand or "UNKNOWN",
        cabin=row.cabin_class,
        stops=0,
        price=price if price is not None else row.total_fare,
        is_sold_out=row.availability == AvailabilityState.SOLD_OUT,
        disposition=mapped.value.upper(),
        observation_id=str(row.id),
    )


def clean_observations(
    rows: list[NormalisedObservation],
    *,
    tukey_k: Decimal,
    hampel_z: Decimal,
    freshness_hours: int,
    now: datetime | None = None,
) -> tuple[list[Quote], list[dict]]:
    moment = now or utcnow()
    grouped: dict[tuple, list[NormalisedObservation]] = defaultdict(list)
    for row in rows:
        grouped[(row.origin_airport, row.destination_airport, row.carrier, row.lead_time_days, row.booking_date)].append(row)

    quotes: list[Quote] = []
    checks: list[dict] = []
    for _key, group in grouped.items():
        prices = [item.total_fare for item in group]
        fences = tukey_fences(prices, tukey_k)
        for row in group:
            collected = ensure_utc(row.collected_at) or utcnow()
            synthetic = CanonicalFareObservation(
                observation_id=row.id,
                source=row.source_name,
                source_type=row.source_type,
                collector=row.collector,
                collected_at=collected,
                origin_airport=row.origin_airport,
                destination_airport=row.destination_airport,
                travel_date=row.travel_date,
                booking_date=row.booking_date,
                lead_time_days=row.lead_time_days,
                carrier=row.carrier,
                flight_number=row.flight_number,
                cabin_class=row.cabin_class,
                fare_brand=row.fare_brand,
                total_fare=row.total_fare,
                currency=row.currency,
                seat_or_fare_availability=row.availability,
                raw_record_hash=row.raw_record_hash,
                parser_version=row.parser_version,
                is_simulated=row.is_simulated,
            )
            flags: list[ValidationFlag] = list(validate_observation(synthetic))
            flags.extend(cell_outlier_flags(prices, synthetic, tukey_k=tukey_k, hampel_z=hampel_z))
            sold = sold_out_flag(synthetic)
            if sold:
                flags.append(sold)
            stale = freshness_flag(synthetic, moment, freshness_hours)
            collected_at = ensure_utc(row.collected_at) or row.collected_at
            if stale and collected_at < moment - timedelta(hours=freshness_hours):
                flags.append(stale)
            winsorised = False
            price = row.total_fare
            if fences is not None and (price < fences[0] or price > fences[1]):
                price = winsorise(price, fences[0], fences[1])
                winsorised = True
            disposition = map_publication_disposition(synthetic, flags, winsorised=winsorised)
            checks.append(
                {
                    "observation_id": row.id,
                    "code": ",".join(flag.code for flag in flags) or "OK",
                    "disposition": disposition,
                    "details": {"winsorised": winsorised, "flags": [flag.code for flag in flags]},
                }
            )
            if disposition in {PublicationDisposition.ACCEPTED, PublicationDisposition.WINSORISED}:
                quotes.append(observation_to_quote(row, price=price, disposition=disposition))
    return quotes, checks
