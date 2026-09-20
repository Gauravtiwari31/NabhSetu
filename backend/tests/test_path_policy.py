from app.acquisition.path_policy import path_is_blocked, request_permitted
from app.domain.enums import ReviewStatus, RobotsStatus, SourceType
from app.domain.models import SourceCapabilities, SourceNetworkPolicy, SourcePolicy, SourceProfile
from app.services.seeding import MOCK_SOURCE_ID


def _source(**kwargs) -> SourceProfile:
    return SourceProfile(
        id=MOCK_SOURCE_ID,
        name="SpiceJet",
        base_url="https://www.spicejet.com",
        source_type=SourceType.AIRLINE,
        enabled=True,
        automation_allowed=True,
        robots_status=RobotsStatus.ALLOWED,
        terms_review_status=ReviewStatus.APPROVED,
        capabilities=SourceCapabilities(static_html=True),
        policy=SourcePolicy(
            minimum_interval_seconds=8,
            maximum_concurrency=1,
            daily_request_limit=80,
            blocked_paths=["/api/v1", "/externalBooking"],
            allowed_paths=["*"],
        ),
        network_policy=SourceNetworkPolicy(),
        **kwargs,
    )


def test_blocked_booking_api_path_is_denied() -> None:
    assert path_is_blocked("https://www.spicejet.com/api/v1/search", ["/api/v1"]) == "/api/v1"
    allowed, rule = request_permitted("https://www.spicejet.com/api/v1/search", _source())
    assert allowed is False
    assert rule == "/api/v1"


def test_homepage_is_permitted() -> None:
    allowed, rule = request_permitted("https://www.spicejet.com/", _source())
    assert allowed is True
    assert rule is None
