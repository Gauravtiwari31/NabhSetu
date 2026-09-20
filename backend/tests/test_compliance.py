from datetime import UTC, datetime, timedelta

import pytest

from app.domain.enums import (
    CircuitState,
    CollectionStatus,
    ComplianceDecision,
    ReviewStatus,
    RobotsStatus,
)
from app.services.seeding import MOCK_SOURCE_ID
from tests.conftest import make_query


@pytest.mark.asyncio
async def test_governor_allows_reviewed_mock_source(container) -> None:
    source = await container.sources.get(MOCK_SOURCE_ID)
    assert source is not None
    result = await container.governor.evaluate(source, make_query())
    assert result.decision is ComplianceDecision.ALLOW
    assert result.lease is not None
    await container.governor.release(source, result.lease)


@pytest.mark.asyncio
async def test_governor_denies_disabled_source(container) -> None:
    source = await container.sources.get(MOCK_SOURCE_ID)
    assert source is not None
    source.enabled = False
    result = await container.governor.evaluate(source, make_query())
    assert result.decision is ComplianceDecision.DENY
    assert "SOURCE_DISABLED" in result.reason_codes


@pytest.mark.asyncio
async def test_governor_denies_disallowed_robots(container) -> None:
    source = await container.sources.get(MOCK_SOURCE_ID)
    assert source is not None
    source.robots_status = RobotsStatus.DISALLOWED
    result = await container.governor.evaluate(source, make_query())
    assert result.decision is ComplianceDecision.DENY
    assert "ROBOTS_DISALLOWED" in result.reason_codes


@pytest.mark.asyncio
async def test_governor_requires_review_when_terms_unknown(container) -> None:
    source = await container.sources.get(MOCK_SOURCE_ID)
    assert source is not None
    source.terms_review_status = ReviewStatus.UNKNOWN
    result = await container.governor.evaluate(source, make_query())
    assert result.decision is ComplianceDecision.REVIEW_REQUIRED


@pytest.mark.asyncio
async def test_governor_denies_unknown_route(container) -> None:
    source = await container.sources.get(MOCK_SOURCE_ID)
    assert source is not None
    source.policy.allowed_routes = ["BLR-HYD"]
    result = await container.governor.evaluate(source, make_query())
    assert result.decision is ComplianceDecision.DENY
    assert "ROUTE_NOT_PERMITTED" in result.reason_codes


@pytest.mark.asyncio
async def test_governor_enforces_daily_quota(container) -> None:
    source = await container.sources.get(MOCK_SOURCE_ID)
    assert source is not None
    source.policy.daily_request_limit = 1
    first = await container.governor.evaluate(source, make_query())
    assert first.decision is ComplianceDecision.ALLOW
    second = await container.governor.evaluate(source, make_query())
    assert second.decision is ComplianceDecision.DENY
    assert "DAILY_QUOTA_EXHAUSTED" in second.reason_codes
    await container.governor.release(source, first.lease)


@pytest.mark.asyncio
async def test_open_captcha_circuit_is_not_retried(container) -> None:
    source = await container.sources.get(MOCK_SOURCE_ID)
    assert source is not None
    stats = source.adapter_stats[0]
    stats.circuit_state = CircuitState.OPEN
    stats.last_failure_kind = CollectionStatus.CAPTCHA_BLOCKED
    stats.cooldown_until = datetime.now(UTC) + timedelta(hours=1)
    result = await container.governor.evaluate(
        source, make_query(), adapter=stats.adapter
    )
    assert result.decision is ComplianceDecision.DENY
    assert "CIRCUIT_OPEN_RESTRICTION" in result.reason_codes
