from decimal import Decimal

from app.domain.enums import AvailabilityState, PublicationDisposition, ValidationDisposition
from app.domain.models import CanonicalFareObservation, ValidationFlag, utcnow
from app.quality.cells import tukey_fences, winsorise
from app.quality.mapping import map_publication_disposition
from tests.conftest import make_query


def _obs(**kwargs) -> CanonicalFareObservation:
    query = make_query()
    payload = dict(
        source="MockFareSource",
        source_type="mock",
        collector="mock",
        collected_at=utcnow(),
        origin_airport="DEL",
        destination_airport="BOM",
        travel_date=query.travel_date,
        booking_date=query.observation_date,
        lead_time_days=7,
        carrier="6E",
        flight_number="6E-101",
        cabin_class="ECONOMY",
        total_fare=Decimal("5000.00"),
        raw_record_hash="a" * 64,
        parser_version="1.0.0",
        is_simulated=True,
    )
    payload.update(kwargs)
    return CanonicalFareObservation(**payload)


def test_tukey_winsorises_extreme_fares() -> None:
    prices = [Decimal(str(value)) for value in (4000, 4100, 4200, 4300, 4400, 20000)]
    fences = tukey_fences(prices, Decimal("3"))
    assert fences is not None
    clipped = winsorise(Decimal("20000"), *fences)
    assert clipped < Decimal("20000")


def test_sold_out_is_quarantined() -> None:
    obs = _obs(seat_or_fare_availability=AvailabilityState.SOLD_OUT)
    disposition = map_publication_disposition(obs, [])
    assert disposition is PublicationDisposition.QUARANTINED


def test_excluded_flags_are_not_published() -> None:
    obs = _obs()
    flags = [
        ValidationFlag(code="UNKNOWN_AIRPORT", message="no", disposition=ValidationDisposition.FLAGGED)
    ]
    assert map_publication_disposition(obs, flags) is PublicationDisposition.EXCLUDED
