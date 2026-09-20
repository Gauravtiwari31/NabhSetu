from app.acquisition.base import BaseCollector
from app.config.settings import get_settings
from app.config import DataMode
from app.domain.enums import CollectionStatus, CollectorModality, SourceType
from app.domain.models import CollectionError, CollectionResult, utcnow
from app.services.container import build_container
from app.services.seeding import MOCK_SOURCE_ID
from tests.conftest import make_query


class ScriptedCollector(BaseCollector):
    parser_name = "scripted"
    parser_version = "0"

    def __init__(self, identity: CollectorModality, statuses: list[CollectionStatus]) -> None:
        self.identity = identity
        self.statuses = list(statuses)
        self.calls = 0

    async def supports(self, source) -> bool:
        return True

    async def collect(self, query, source, *, lease, egress) -> CollectionResult:
        self.calls += 1
        status = self.statuses.pop(0) if self.statuses else CollectionStatus.TEMPORARY_FAILURE
        return CollectionResult(
            source_id=source.id,
            collector=self.identity,
            status=status,
            requested_at=utcnow(),
            completed_at=utcnow(),
            errors=[CollectionError(code=status.value.upper(), message=status.value)],
            is_simulated=True,
        )


async def _router_with(session, collectors) -> tuple:
    settings = get_settings()
    container = build_container(session, settings)
    container.registry.collectors = collectors
    return container, await container.sources.get(MOCK_SOURCE_ID)


async def test_registry_prefers_configured_adapter(container) -> None:
    source = await container.sources.get(MOCK_SOURCE_ID)
    ranked = await container.registry.rank_collectors(source)
    assert ranked
    assert ranked[0].identity is CollectorModality.MOCK


async def test_live_source_selection_skips_mock(container) -> None:
    container.registry.settings = container.settings.model_copy(update={"data_mode": DataMode.LIVE})
    source = await container.registry.resolve_source(None, None)
    assert source is not None
    assert source.source_type is not SourceType.MOCK


async def test_router_stops_on_captcha_without_fallback(session) -> None:
    captcha = ScriptedCollector(CollectorModality.STATIC_HTML, [CollectionStatus.CAPTCHA_BLOCKED])
    fallback = ScriptedCollector(CollectorModality.EMBEDDED_JSON, [CollectionStatus.SUCCESS])
    container, source = await _router_with(session, [captcha, fallback])
    job = await container.jobs.create(make_query(), request_id="r1", source_id=source.id)
    result = await container.router.collect(make_query(), job_id=job.id, request_id="r1", source=source)
    assert result.status is CollectionStatus.CAPTCHA_BLOCKED
    assert captcha.calls == 1
    assert fallback.calls == 0
    refreshed = await container.sources.get(MOCK_SOURCE_ID)
    assert refreshed is not None
    assert refreshed.temporarily_blocked is True


async def test_router_stops_on_block_without_fallback(session) -> None:
    blocked = ScriptedCollector(CollectorModality.STATIC_HTML, [CollectionStatus.BLOCKED])
    fallback = ScriptedCollector(CollectorModality.EMBEDDED_JSON, [CollectionStatus.SUCCESS])
    container, source = await _router_with(session, [blocked, fallback])
    job = await container.jobs.create(make_query(), request_id="r2", source_id=source.id)
    result = await container.router.collect(make_query(), job_id=job.id, request_id="r2", source=source)
    assert result.status is CollectionStatus.BLOCKED
    assert fallback.calls == 0


async def test_router_falls_back_on_unsupported(session) -> None:
    unsupported = ScriptedCollector(CollectorModality.STATIC_HTML, [CollectionStatus.UNSUPPORTED])
    mock = ScriptedCollector(CollectorModality.MOCK, [CollectionStatus.SUCCESS])
    container, source = await _router_with(session, [unsupported, mock])
    source.capabilities.preferred_adapter = CollectorModality.STATIC_HTML
    source.capabilities.last_successful_adapter = None
    job = await container.jobs.create(make_query(), request_id="r3", source_id=source.id)
    result = await container.router.collect(make_query(), job_id=job.id, request_id="r3", source=source)
    assert result.status is CollectionStatus.SUCCESS
    assert unsupported.calls == 1
    assert mock.calls == 1


async def test_router_falls_back_on_no_results(session) -> None:
    empty = ScriptedCollector(CollectorModality.STATIC_HTML, [CollectionStatus.NO_RESULTS])
    json_collector = ScriptedCollector(CollectorModality.EMBEDDED_JSON, [CollectionStatus.SUCCESS])
    container, source = await _router_with(session, [empty, json_collector])
    source.capabilities.preferred_adapter = CollectorModality.STATIC_HTML
    source.capabilities.last_successful_adapter = None
    job = await container.jobs.create(make_query(), request_id="r4", source_id=source.id)
    result = await container.router.collect(make_query(), job_id=job.id, request_id="r4", source=source)
    assert result.status is CollectionStatus.SUCCESS
    assert empty.calls == 1
    assert json_collector.calls == 1


async def test_circuit_ignores_no_results(container) -> None:
    source = await container.sources.get(MOCK_SOURCE_ID)
    assert source is not None
    adapter = CollectorModality.MOCK
    for _ in range(container.settings.circuit_failure_threshold):
        await container.registry.record_outcome(source, adapter, CollectionStatus.NO_RESULTS, latency_ms=10)
        source = await container.sources.get(MOCK_SOURCE_ID)
        assert source is not None
    stats = source.stats_for(adapter)
    assert stats is not None
    assert stats.circuit_state.value == "closed"
    assert stats.consecutive_failures == 0


async def test_circuit_opens_after_repeated_transient_failures(container) -> None:
    source = await container.sources.get(MOCK_SOURCE_ID)
    assert source is not None
    adapter = CollectorModality.MOCK
    for _ in range(container.settings.circuit_failure_threshold):
        await container.registry.record_outcome(
            source, adapter, CollectionStatus.TEMPORARY_FAILURE, latency_ms=10
        )
        source = await container.sources.get(MOCK_SOURCE_ID)
        assert source is not None
    stats = source.stats_for(adapter)
    assert stats is not None
    assert stats.circuit_state.value == "open"
    ranked = await container.registry.rank_collectors(source)
    assert ranked == []
