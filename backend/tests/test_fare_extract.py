from decimal import Decimal
from uuid import UUID

from app.domain.enums import (
    CollectionStatus,
    CollectorModality,
    ReviewStatus,
    RobotsStatus,
    SourceType,
)
from app.domain.models import SourceCapabilities, SourceNetworkPolicy, SourcePolicy, SourceProfile
from app.sources.common.fare_extract import extract_fares
from app.sources.common.html import extract_embedded_json
from tests.conftest import make_query

SOURCE_ID = UUID("00000000-0000-4000-a000-000000000011")


def _source() -> SourceProfile:
    return SourceProfile(
        id=SOURCE_ID,
        name="AkasaAir",
        base_url="https://www.akasaair.com",
        source_type=SourceType.AIRLINE,
        enabled=True,
        automation_allowed=True,
        robots_status=RobotsStatus.ALLOWED,
        terms_review_status=ReviewStatus.APPROVED,
        capabilities=SourceCapabilities(static_html=True, embedded_json=True),
        policy=SourcePolicy(minimum_interval_seconds=8, maximum_concurrency=1, daily_request_limit=80),
        network_policy=SourceNetworkPolicy(),
    )


def test_extract_requires_matching_date_origin_and_flight() -> None:
    query = make_query(lead_time_days=7)
    payload = {
        "itineraries": [
            {
                "origin": "DEL",
                "destination": "BOM",
                "departureDate": "2026-09-27",
                "carrier": "QP",
                "flightNumber": "QP1122",
                "totalFare": 4850,
            }
        ]
    }
    outcome = extract_fares(
        payload,
        query,
        _source(),
        CollectorModality.EMBEDDED_JSON,
        carrier_hint="QP",
        parser_version="1.0.0",
        confidence=Decimal("0.96"),
    )
    assert outcome.status is CollectionStatus.SUCCESS
    assert len(outcome.observations) == 1
    assert outcome.observations[0].total_fare == Decimal("4850.00")
    assert outcome.observations[0].is_simulated is False
    assert outcome.observations[0].flight_number == "QP1122"


def test_extract_ignores_undated_promo_prices() -> None:
    query = make_query(lead_time_days=7)
    payload = {"offers": [{"origin": "DEL", "destination": "BOM", "price": 1999, "title": "Sale"}]}
    outcome = extract_fares(
        payload,
        query,
        _source(),
        CollectorModality.STATIC_HTML,
        carrier_hint="QP",
        parser_version="1.0.0",
        confidence=Decimal("0.94"),
    )
    assert outcome.status is CollectionStatus.NO_RESULTS
    assert outcome.observations == []


def test_extract_ignores_zero_and_mismatched_route() -> None:
    query = make_query(lead_time_days=7)
    payload = {
        "fares": [
            {
                "origin": "DEL",
                "destination": "BOM",
                "departureDate": "2026-09-27",
                "flightNumber": "QP1",
                "price": 0,
            },
            {
                "origin": "BLR",
                "destination": "HYD",
                "departureDate": "2026-09-27",
                "flightNumber": "QP2",
                "price": 3000,
            },
        ]
    }
    outcome = extract_fares(
        payload,
        query,
        _source(),
        CollectorModality.EMBEDDED_JSON,
        carrier_hint="QP",
        parser_version="1.0.0",
        confidence=Decimal("0.96"),
    )
    assert outcome.observations == []


def test_embedded_json_from_next_data() -> None:
    html = (
        '<html><script id="__NEXT_DATA__" type="application/json">'
        '{"props":{"origin":"DEL"}}'
        "</script></html>"
    )
    blobs = extract_embedded_json(html)
    assert blobs == [{"props": {"origin": "DEL"}}]
