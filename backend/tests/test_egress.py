from uuid import uuid4

from app.domain.enums import CollectionStatus, EgressMode, NetworkFailureCategory
from app.domain.models import EgressSelection
from app.network_egress.classification import classify_collection_failure, may_failover_egress
from app.observability.redaction import redact
from app.services.seeding import DIRECT_EGRESS_ID, MOCK_SOURCE_ID


def test_restrictions_must_not_failover_egress() -> None:
    for status in (
        CollectionStatus.RATE_LIMITED,
        CollectionStatus.BLOCKED,
        CollectionStatus.CAPTCHA_BLOCKED,
        CollectionStatus.POLICY_DENIED,
    ):
        category = classify_collection_failure(status, http_status=403)
        assert category is NetworkFailureCategory.SOURCE_RESTRICTION
        assert may_failover_egress(category) is False


def test_network_failures_may_failover_egress() -> None:
    category = classify_collection_failure(
        CollectionStatus.NETWORK_ERROR,
        network_category=NetworkFailureCategory.DEAD_PROXY,
    )
    assert may_failover_egress(category) is True


def test_redaction_strips_proxy_credentials() -> None:
    payload = redact({"proxy_password": "super-secret", "egress_id": "abc", "nested": {"api_key": "k"}})
    assert payload["proxy_password"] == "***"
    assert payload["nested"]["api_key"] == "***"
    assert payload["egress_id"] == "abc"


async def test_direct_mode_works_without_proxy_pool(container) -> None:
    source = await container.sources.get(MOCK_SOURCE_ID)
    selection = await container.egress.acquire(source, job_id=uuid4(), request_id="e1")
    assert selection.mode is EgressMode.DIRECT
    assert selection.node_id == DIRECT_EGRESS_ID
    assert selection.endpoint_reference == "direct://local"


async def test_sticky_session_keeps_the_same_node(container) -> None:
    source = await container.sources.get(MOCK_SOURCE_ID)
    assert source is not None
    source.network_policy.sticky_session_required = True
    first = await container.egress.acquire(source, job_id=uuid4(), request_id="s1")
    second = await container.egress.acquire(source, job_id=uuid4(), request_id="s1")
    assert first.session_id == second.session_id
    assert first.node_id == second.node_id


async def test_restriction_does_not_change_egress_node(container) -> None:
    source = await container.sources.get(MOCK_SOURCE_ID)
    current = await container.egress.acquire(source, job_id=uuid4(), request_id="f1")
    after = await container.egress.failover(
        source,
        current=current,
        category=NetworkFailureCategory.SOURCE_RESTRICTION,
        job_id=uuid4(),
        request_id="f1",
    )
    assert after.node_id == current.node_id
    assert after.failover_count == 0


async def test_dead_proxy_marks_node_unhealthy_and_counts_failover(container) -> None:
    source = await container.sources.get(MOCK_SOURCE_ID)
    current = EgressSelection(
        node_id=DIRECT_EGRESS_ID,
        provider="direct",
        region="local",
        endpoint_reference="direct://local",
        mode=EgressMode.DIRECT,
        failover_count=0,
    )
    after = await container.egress.failover(
        source,
        current=current,
        category=NetworkFailureCategory.DEAD_PROXY,
        job_id=uuid4(),
        request_id="f2",
    )
    assert after.failover_count == 1
    node = await container.egress_repo.get(DIRECT_EGRESS_ID)
    assert node is not None
    assert node.healthy is False
