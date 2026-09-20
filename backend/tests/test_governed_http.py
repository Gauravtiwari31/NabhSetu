from urllib.robotparser import RobotFileParser

import httpx

from app.acquisition.discovery.robots import RobotsSnapshot
from app.acquisition.http import GovernedHttpClient
from app.config.settings import Settings
from app.domain.enums import CollectionStatus, ReviewStatus, RobotsStatus, SourceType
from app.domain.models import (
    SourceCapabilities,
    SourceNetworkPolicy,
    SourcePolicy,
    SourceProfile,
    utcnow,
)
from app.services.seeding import MOCK_SOURCE_ID


def _settings() -> Settings:
    return Settings(
        data_mode="live",
        identified_user_agent="Nabhsetu-Research-Bot/0.1 (+https://www.mospi.gov.in; SIH26056 airfare index research)",
        http_timeout_seconds=5,
        http_connect_timeout_seconds=2,
    )


def _source() -> SourceProfile:
    return SourceProfile(
        id=MOCK_SOURCE_ID,
        name="AkasaAir",
        base_url="https://www.akasaair.com",
        source_type=SourceType.AIRLINE,
        enabled=True,
        automation_allowed=True,
        robots_status=RobotsStatus.ALLOWED,
        terms_review_status=ReviewStatus.APPROVED,
        capabilities=SourceCapabilities(static_html=True),
        policy=SourcePolicy(minimum_interval_seconds=1, maximum_concurrency=1, daily_request_limit=80),
        network_policy=SourceNetworkPolicy(),
    )


def _robots() -> RobotsSnapshot:
    parser = RobotFileParser()
    parser.parse(["User-agent: *", "Allow: /"])
    return RobotsSnapshot(
        status=RobotsStatus.ALLOWED,
        fetched_at=utcnow(),
        robots_url="https://www.akasaair.com/robots.txt",
        parser=parser,
    )


async def test_403_is_blocked_not_rotated() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    client = GovernedHttpClient(_settings(), transport=httpx.MockTransport(handler))
    page = await client.get("https://www.akasaair.com/", _source(), robots=_robots(), cache=False)
    assert page.collection_status is CollectionStatus.BLOCKED
    assert page.status_code == 403


async def test_disallowed_path_is_not_fetched() -> None:
    called = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        called["n"] += 1
        return httpx.Response(200, text="ok")

    source = _source()
    source.policy.blocked_paths = ["/flight-availability"]
    client = GovernedHttpClient(_settings(), transport=httpx.MockTransport(handler))
    page = await client.get(
        "https://www.airindiaexpress.com/flight-availability",
        source,
        robots=_robots(),
        cache=False,
    )
    assert called["n"] == 0
    assert page.collection_status is CollectionStatus.POLICY_DENIED
