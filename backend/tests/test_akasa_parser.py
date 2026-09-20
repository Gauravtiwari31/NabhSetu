import json
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from app.domain.enums import CollectionStatus, CollectorModality
from app.sources.akasa.parser import parse_akasa
from app.sources.catalog import plugin_for
from tests.conftest import make_query
from tests.test_fare_extract import _source

FIXTURES = Path(__file__).resolve().parents[1] / "app" / "sources" / "akasa" / "fixtures"


def test_availability_search_emits_real_flight_numbers() -> None:
    payload = json.loads((FIXTURES / "availability_search.json").read_text(encoding="utf-8"))
    query = make_query(lead_time_days=7)
    outcome = parse_akasa(
        payload,
        query,
        _source(),
        CollectorModality.PLAYWRIGHT_NETWORK,
        Decimal("0.97"),
    )
    assert outcome.status is CollectionStatus.SUCCESS
    numbers = {item.flight_number for item in outcome.observations}
    assert numbers == {"QP1833", "QP1119"}
    cheapest = min(item.total_fare for item in outcome.observations)
    assert cheapest == Decimal("6880.00")
    sample = next(item for item in outcome.observations if item.flight_number == "QP1833")
    assert sample.origin_airport == "DEL"
    assert sample.destination_airport == "BOM"
    assert sample.carrier == "QP"
    assert sample.base_fare == Decimal("5640.00")
    assert sample.udf == Decimal("241.00")
    assert sample.taxes == Decimal("288.00")
    assert sample.is_simulated is False


def test_calendar_lowest_is_dated_fallback_only() -> None:
    payload = json.loads((FIXTURES / "calendar_lowest.json").read_text(encoding="utf-8"))
    query = make_query(lead_time_days=7)
    outcome = parse_akasa(
        payload,
        query,
        _source(),
        CollectorModality.PLAYWRIGHT_NETWORK,
        Decimal("0.97"),
        url=payload["url"],
    )
    assert outcome.status is CollectionStatus.SUCCESS
    assert len(outcome.observations) == 1
    row = outcome.observations[0]
    assert row.flight_number == "UNSPECIFIED"
    assert row.total_fare == Decimal("6530.00")
    assert row.fare_brand == "calendar_lowest"


def test_wrong_travel_date_is_no_results() -> None:
    payload = json.loads((FIXTURES / "availability_search.json").read_text(encoding="utf-8"))
    query = make_query(lead_time_days=1)
    outcome = parse_akasa(
        payload,
        query,
        _source(),
        CollectorModality.PLAYWRIGHT_NETWORK,
        Decimal("0.97"),
    )
    assert outcome.status is CollectionStatus.NO_RESULTS
    assert outcome.observations == []


def test_akasa_plugin_uses_availability_parser() -> None:
    payload = json.loads((FIXTURES / "availability_search.json").read_text(encoding="utf-8"))
    plugin = plugin_for(UUID("00000000-0000-4000-a000-000000000011"))
    assert plugin is not None
    outcome = plugin.parse_payload(
        payload,
        make_query(lead_time_days=7),
        _source(),
        CollectorModality.PLAYWRIGHT_NETWORK,
        Decimal("0.97"),
    )
    assert outcome.status is CollectionStatus.SUCCESS
    assert {item.flight_number for item in outcome.observations} == {"QP1833", "QP1119"}
