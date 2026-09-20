import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.acquisition.adapters.browser import BrowserRuntime
from app.config.settings import Settings
from app.domain.enums import (
    CollectionStatus,
    CollectorModality,
    ReviewStatus,
    RobotsStatus,
    SourceType,
)
from app.domain.models import SourceCapabilities, SourceNetworkPolicy, SourcePolicy, SourceProfile
from app.sources.ota.catalog import (
    CLEARTRIP,
    EASE_MY_TRIP,
    GOIBIBO,
    IXIGO,
    MAKE_MY_TRIP,
    OTA_PLUGINS,
    YATRA,
)
from app.sources.ota.parser import parse_easemytrip_dom
from tests.conftest import make_query

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "sources"
    / "ota"
    / "fixtures"
    / "easemytrip_dom_cards.json"
)


def _source() -> SourceProfile:
    return SourceProfile(
        id=EASE_MY_TRIP.spec.source_id,
        name="EaseMyTrip",
        base_url=EASE_MY_TRIP.spec.base_url,
        source_type=SourceType.OTA,
        enabled=True,
        automation_allowed=True,
        robots_status=RobotsStatus.ALLOWED,
        terms_review_status=ReviewStatus.APPROVED,
        capabilities=SourceCapabilities(
            static_html=True,
            embedded_json=True,
            requires_javascript=True,
            browser_network_json=True,
        ),
        policy=SourcePolicy(
            minimum_interval_seconds=12,
            maximum_concurrency=1,
            daily_request_limit=40,
        ),
        network_policy=SourceNetworkPolicy(),
    )


def test_all_named_otas_are_registered_with_explicit_terms_decisions() -> None:
    assert {plugin.spec.name for plugin in OTA_PLUGINS} == {
        "MakeMyTrip",
        "Yatra",
        "EaseMyTrip",
        "Cleartrip",
        "Ixigo",
        "Goibibo",
    }
    assert all(plugin.spec.source_type is SourceType.OTA for plugin in OTA_PLUGINS)
    assert MAKE_MY_TRIP.spec.terms_review_status is ReviewStatus.DENIED
    assert CLEARTRIP.spec.terms_review_status is ReviewStatus.DENIED
    assert IXIGO.spec.terms_review_status is ReviewStatus.DENIED
    assert YATRA.spec.terms_review_status is ReviewStatus.REVIEW_REQUIRED
    assert GOIBIBO.spec.terms_review_status is ReviewStatus.REVIEW_REQUIRED
    assert EASE_MY_TRIP.spec.terms_review_status is ReviewStatus.APPROVED
    assert EASE_MY_TRIP.spec.automation_allowed is True
    assert all(
        plugin.spec.automation_allowed is False
        for plugin in (MAKE_MY_TRIP, YATRA, CLEARTRIP, IXIGO, GOIBIBO)
    )


def test_easemytrip_plan_uses_public_form_and_dom_cards() -> None:
    plan = EASE_MY_TRIP.browser_plan(make_query())
    assert plan is not None
    assert plan.start_url == "https://www.easemytrip.com/"
    assert plan.widget == "easemytrip"
    assert plan.dom_record_selector == ".nw_listing_bx"
    assert plan.origin_code == "DEL"
    assert plan.destination_code == "BOM"


def test_easemytrip_dom_parser_uses_listed_fare_not_lock_or_promo_amount() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    outcome = parse_easemytrip_dom(
        payload,
        make_query(lead_time_days=7),
        _source(),
        CollectorModality.PLAYWRIGHT_NETWORK,
        Decimal("0.97"),
    )
    assert outcome.status is CollectionStatus.SUCCESS
    assert [(row.flight_number, row.total_fare) for row in outcome.observations] == [
        ("IX1165", Decimal("6245.00")),
        ("QP1110", Decimal("6530.00")),
        ("SG162", Decimal("6292.00")),
    ]
    assert all(row.source_type is SourceType.OTA for row in outcome.observations)
    assert all(row.is_simulated is False for row in outcome.observations)


def test_easemytrip_dom_parser_rejects_wrong_route_or_date_context() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    outcome = parse_easemytrip_dom(
        payload,
        make_query(lead_time_days=1),
        _source(),
        CollectorModality.PLAYWRIGHT_NETWORK,
        Decimal("0.97"),
    )
    assert outcome.status is CollectionStatus.NO_RESULTS
    assert outcome.observations == []


def test_browser_capture_cache_is_date_specific() -> None:
    runtime = BrowserRuntime(Settings(_env_file=None))
    first = make_query(lead_time_days=1)
    second = make_query(lead_time_days=7)
    assert runtime.cache_key(EASE_MY_TRIP.spec.source_id, first) != runtime.cache_key(
        EASE_MY_TRIP.spec.source_id, second
    )


@pytest.mark.asyncio
async def test_seeded_ota_policy_matches_review(container) -> None:
    easemytrip = await container.sources.get(EASE_MY_TRIP.spec.source_id)
    makemytrip = await container.sources.get(MAKE_MY_TRIP.spec.source_id)
    assert easemytrip is not None
    assert makemytrip is not None
    assert easemytrip.source_type is SourceType.OTA
    assert easemytrip.terms_review_status is ReviewStatus.APPROVED
    assert easemytrip.automation_allowed is True
    assert makemytrip.terms_review_status is ReviewStatus.DENIED
    assert makemytrip.automation_allowed is False
