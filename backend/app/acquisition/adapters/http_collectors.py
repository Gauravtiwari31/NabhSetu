from __future__ import annotations

from app.acquisition.adapters.results import (
    confidence_for,
    denied_result,
    from_outcome,
    from_page_error,
    robots_or_deny,
)
from app.acquisition.base import BaseCollector
from app.acquisition.discovery.robots import RobotsSnapshot
from app.acquisition.http import GovernedHttpClient
from app.config import DataMode, Settings
from app.domain.enums import CollectionStatus, CollectorModality, SourceType
from app.domain.models import (
    CollectionResult,
    ComplianceLease,
    FareQuery,
    SourceProfile,
    utcnow,
)
from app.sources.catalog import plugin_for
from app.sources.common.fare_extract import ParseOutcome
from app.sources.common.html import looks_like_challenge


class LiveHttpCollector(BaseCollector):
    def __init__(self, settings: Settings, http: GovernedHttpClient) -> None:
        self.settings = settings
        self.http = http
        self._robots: dict = {}

    def bind_robots(self, source_id, snapshot: RobotsSnapshot) -> None:
        self._robots[source_id] = snapshot

    def robots_for(self, source: SourceProfile) -> RobotsSnapshot | None:
        return self._robots.get(source.id)

    def plugin(self, source: SourceProfile):
        return plugin_for(source.id, source.name)

    async def live_supported(self, source: SourceProfile, flag: bool) -> bool:
        return (
            flag
            and self.settings.data_mode == DataMode.LIVE
            and source.source_type != SourceType.MOCK
            and self.plugin(source) is not None
        )


class PublicApiCollector(LiveHttpCollector):
    identity = CollectorModality.PUBLIC_API
    parser_name = "airline_public_api"
    parser_version = "1.0.0"

    async def supports(self, source: SourceProfile) -> bool:
        return await self.live_supported(source, source.capabilities.public_api)

    async def collect(self, query, source, *, lease, egress) -> CollectionResult:
        started = utcnow()
        return CollectionResult(
            source_id=source.id,
            collector=self.identity,
            status=CollectionStatus.UNSUPPORTED,
            requested_at=started,
            completed_at=utcnow(),
            metadata={"reason": "no_documented_public_fare_api"},
        )


class StructuredFeedCollector(LiveHttpCollector):
    identity = CollectorModality.STRUCTURED_FEED
    parser_name = "airline_feed"
    parser_version = "1.0.0"

    async def supports(self, source: SourceProfile) -> bool:
        return await self.live_supported(source, source.capabilities.structured_feed)

    async def collect(self, query, source, *, lease, egress) -> CollectionResult:
        started = utcnow()
        if not lease.is_valid(started):
            return denied_result(
                source, self.identity, started, code="LEASE_INVALID", message="Compliance lease is not valid"
            )
        robots = self.robots_for(source)
        blocked = robots_or_deny(source, self.identity, started, robots)
        if blocked:
            return blocked
        plugin = self.plugin(source)
        assert plugin is not None
        urls = plugin.feed_urls()
        if not urls:
            return CollectionResult(
                source_id=source.id,
                collector=self.identity,
                status=CollectionStatus.UNSUPPORTED,
                requested_at=started,
                completed_at=utcnow(),
                metadata={"reason": "no_feed_url"},
            )
        page = await self.http.get(urls[0], source, robots=robots, cache=True)
        if page.collection_status in {
            CollectionStatus.TEMPORARY_FAILURE,
            CollectionStatus.NETWORK_ERROR,
            CollectionStatus.NO_RESULTS,
        }:
            return CollectionResult(
                source_id=source.id,
                collector=self.identity,
                status=CollectionStatus.UNSUPPORTED,
                requested_at=started,
                completed_at=utcnow(),
                errors=[],
                metadata={"feed_unavailable": True, "http_status": page.status_code, "url": page.url},
            )
        error = from_page_error(source, self.identity, started, page)
        if error is not None:
            return error
        outcome = plugin.parse_html(
            page.text, query, source, self.identity, confidence_for(self.settings, self.identity)
        )
        if not outcome.observations:
            outcome = ParseOutcome(
                status=CollectionStatus.NO_RESULTS,
                message="Sitemap/feed contained no matching dated fares",
            )
        return from_outcome(
            source,
            self.identity,
            started,
            outcome,
            page=page,
            parser_name=plugin.spec.parser_name,
            parser_version=plugin.spec.parser_version,
            limit=self.settings.live_payload_max_bytes,
        )


class StaticHtmlCollector(LiveHttpCollector):
    identity = CollectorModality.STATIC_HTML
    parser_name = "airline_html"
    parser_version = "1.0.0"

    async def supports(self, source: SourceProfile) -> bool:
        return await self.live_supported(source, source.capabilities.static_html)

    async def collect(self, query, source, *, lease, egress) -> CollectionResult:
        return await collect_landing_pages(self, query, source, lease=lease)


class EmbeddedJsonCollector(LiveHttpCollector):
    identity = CollectorModality.EMBEDDED_JSON
    parser_name = "airline_embedded_json"
    parser_version = "1.0.0"

    async def supports(self, source: SourceProfile) -> bool:
        return await self.live_supported(source, source.capabilities.embedded_json)

    async def collect(self, query, source, *, lease, egress) -> CollectionResult:
        return await collect_landing_pages(self, query, source, lease=lease)


async def collect_landing_pages(
    collector: LiveHttpCollector,
    query: FareQuery,
    source: SourceProfile,
    *,
    lease: ComplianceLease,
) -> CollectionResult:
    started = utcnow()
    identity = collector.identity
    if not lease.is_valid(started):
        return denied_result(
            source, identity, started, code="LEASE_INVALID", message="Compliance lease is not valid"
        )
    robots = collector.robots_for(source)
    blocked = robots_or_deny(source, identity, started, robots)
    if blocked:
        return blocked
    plugin = collector.plugin(source)
    assert plugin is not None
    last_page = None
    last_stop = None
    for url in plugin.landing_urls(query):
        page = await collector.http.get(url, source, robots=robots, cache=True)
        last_page = page
        if looks_like_challenge(page.text):
            page.collection_status = CollectionStatus.CAPTCHA_BLOCKED
        error = from_page_error(source, identity, started, page)
        if error is not None and error.status in {
            CollectionStatus.BLOCKED,
            CollectionStatus.CAPTCHA_BLOCKED,
            CollectionStatus.POLICY_DENIED,
            CollectionStatus.RATE_LIMITED,
        }:
            return error
        if error is not None:
            last_stop = error
            continue
        outcome = plugin.parse_html(
            page.text, query, source, identity, confidence_for(collector.settings, identity)
        )
        if outcome.observations:
            return from_outcome(
                source,
                identity,
                started,
                outcome,
                page=page,
                parser_name=plugin.spec.parser_name,
                parser_version=plugin.spec.parser_version,
                limit=collector.settings.live_payload_max_bytes,
            )
    if last_stop is not None and last_stop.status in {
        CollectionStatus.TEMPORARY_FAILURE,
        CollectionStatus.NETWORK_ERROR,
    }:
        return last_stop
    empty = ParseOutcome(
        status=CollectionStatus.NO_RESULTS,
        message="Permitted pages contained no matching dated fares",
    )
    return from_outcome(
        source,
        identity,
        started,
        empty,
        page=last_page,
        parser_name=plugin.spec.parser_name,
        parser_version=plugin.spec.parser_version,
        limit=collector.settings.live_payload_max_bytes,
    )
