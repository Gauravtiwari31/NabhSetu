from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import DataMode, Settings, get_settings
from app.database.models import (
    Airport,
    Carrier,
    EgressNode,
    ParserVersion,
    Route,
    Source,
    SourceAdapterStat,
    SourceCapability,
    SourceNetworkPolicyRow,
    SourcePolicyRow,
)
from app.domain.enums import (
    CircuitState,
    CollectorModality,
    EgressMode,
    ReviewStatus,
    RobotsStatus,
    RotationStrategy,
    SourceType,
)
from app.domain.models import utcnow
from app.normalisation.airports import KNOWN_AIRPORTS
from app.normalisation.carriers import KNOWN_CARRIERS
from app.sources.catalog import PLUGINS
from app.sources.common.cities import CITY_LABELS
from app.sources.mock_fare.parser import PARSER_NAME, PARSER_VERSION

MOCK_SOURCE_ID = UUID("00000000-0000-4000-a000-000000000001")
DIRECT_EGRESS_ID = UUID("00000000-0000-4000-a000-0000000000e1")
PARSER_VERSION_ID = UUID("00000000-0000-4000-a000-0000000000aa")
LIVE_PARSER_VERSION_ID = UUID("00000000-0000-4000-a000-0000000000ab")

SEED_ROUTES = (
    ("DEL", "BOM"),
    ("BOM", "DEL"),
    ("DEL", "BLR"),
    ("BOM", "BLR"),
    ("DEL", "HYD"),
)


async def seed_reference_data(session: AsyncSession) -> None:
    for code, name in KNOWN_AIRPORTS.items():
        if await session.get(Airport, code) is None:
            city = CITY_LABELS.get(code, (name,))[0]
            session.add(Airport(iata_code=code, name=name, city=city))
    for code, name in KNOWN_CARRIERS.items():
        if await session.get(Carrier, code) is None:
            session.add(Carrier(iata_code=code, name=name))
    for origin, destination in SEED_ROUTES:
        existing_route = (
            await session.execute(select(Route).where(Route.origin == origin, Route.destination == destination))
        ).scalar_one_or_none()
        if existing_route is None:
            session.add(
                Route(
                    origin=origin,
                    destination=destination,
                    route_class="domestic",
                    weight=1,
                    weight_source="seed",
                    active_from=date(2024, 1, 1),
                )
            )
    if await session.get(ParserVersion, PARSER_VERSION_ID) is None:
        session.add(
            ParserVersion(
                id=PARSER_VERSION_ID,
                name=PARSER_NAME,
                version=PARSER_VERSION,
                source_name="MockFareSource",
                notes="Fixture parser for SIH mock mode",
            )
        )
    if await session.get(ParserVersion, LIVE_PARSER_VERSION_ID) is None:
        session.add(
            ParserVersion(
                id=LIVE_PARSER_VERSION_ID,
                name="airline_html",
                version="1.0.0",
                source_name="live_airline_sites",
                notes="Conservative dated-itinerary extractor. Never fabricates fares.",
            )
        )
    if await session.get(EgressNode, DIRECT_EGRESS_ID) is None:
        session.add(
            EgressNode(
                id=DIRECT_EGRESS_ID,
                provider="direct",
                region="local",
                endpoint_reference="direct://local",
                enabled=True,
                healthy=True,
            )
        )
    await session.flush()


async def seed_mock_source(session: AsyncSession) -> None:
    if await session.get(Source, MOCK_SOURCE_ID) is not None:
        return
    reviewed = utcnow()
    session.add(
        Source(
            id=MOCK_SOURCE_ID,
            name="MockFareSource",
            base_url="https://mock.apix.local",
            source_type=SourceType.MOCK,
            enabled=True,
            automation_allowed=True,
            robots_status=RobotsStatus.ALLOWED,
            terms_review_status=ReviewStatus.APPROVED,
            robots_checked_at=reviewed,
            terms_checked_at=reviewed,
        )
    )
    session.add(
        SourceCapability(
            source_id=MOCK_SOURCE_ID,
            public_api=False,
            static_html=False,
            preferred_adapter=CollectorModality.MOCK,
            last_successful_adapter=CollectorModality.MOCK,
            notes="Simulated source for SIH demonstration. Not a live airline.",
        )
    )
    session.add(
        SourcePolicyRow(
            source_id=MOCK_SOURCE_ID,
            minimum_interval_seconds=0,
            maximum_concurrency=4,
            daily_request_limit=10_000,
            allowed_paths=["*"],
            blocked_paths=[],
            allowed_routes=["DEL-BOM", "*"],
            notes="Mock source has no network path.",
            policy_checked_at=reviewed,
            policy_version="1",
        )
    )
    session.add(
        SourceNetworkPolicyRow(
            source_id=MOCK_SOURCE_ID,
            egress_mode=EgressMode.DIRECT,
            rotation_strategy=RotationStrategy.NONE,
            sticky_session_required=False,
            enabled=True,
            network_policy_version="1",
        )
    )
    session.add(
        SourceAdapterStat(
            source_id=MOCK_SOURCE_ID,
            adapter=CollectorModality.MOCK,
            circuit_state=CircuitState.CLOSED,
        )
    )
    await session.flush()


async def seed_live_sources(session: AsyncSession) -> None:
    reviewed = utcnow()
    for plugin in PLUGINS:
        spec = plugin.spec
        if await session.get(Source, spec.source_id) is not None:
            continue
        session.add(
            Source(
                id=spec.source_id,
                name=spec.name,
                base_url=spec.base_url,
                source_type=spec.source_type,
                enabled=True,
                automation_allowed=spec.automation_allowed,
                robots_status=RobotsStatus.UNKNOWN,
                terms_review_status=spec.terms_review_status,
                terms_checked_at=reviewed,
            )
        )
        preferred = CollectorModality.STATIC_HTML
        session.add(
            SourceCapability(
                source_id=spec.source_id,
                public_api=spec.public_api,
                static_html=spec.static_html,
                embedded_json=spec.embedded_json,
                requires_javascript=spec.requires_javascript,
                browser_network_json=spec.browser_network_json,
                documents_available=spec.documents_available,
                structured_feed=spec.structured_feed,
                preferred_adapter=preferred,
                notes=spec.terms_notes,
            )
        )
        session.add(
            SourcePolicyRow(
                source_id=spec.source_id,
                minimum_interval_seconds=spec.minimum_interval_seconds,
                maximum_concurrency=1,
                daily_request_limit=spec.daily_request_limit,
                allowed_paths=list(spec.allowed_paths),
                blocked_paths=list(spec.blocked_paths),
                allowed_routes=["*"],
                notes=spec.terms_notes,
                policy_checked_at=reviewed,
                policy_version="1",
            )
        )
        session.add(
            SourceNetworkPolicyRow(
                source_id=spec.source_id,
                egress_mode=EgressMode.DIRECT,
                rotation_strategy=RotationStrategy.NONE,
                sticky_session_required=False,
                enabled=True,
                network_policy_version="1",
            )
        )
        modalities = [CollectorModality.STATIC_HTML, CollectorModality.EMBEDDED_JSON]
        if spec.public_api:
            modalities.append(CollectorModality.PUBLIC_API)
        if spec.structured_feed:
            modalities.append(CollectorModality.STRUCTURED_FEED)
        if spec.browser_network_json:
            modalities.append(CollectorModality.PLAYWRIGHT_NETWORK)
        if spec.requires_javascript:
            modalities.append(CollectorModality.PLAYWRIGHT_DOM)
        for adapter in dict.fromkeys(modalities):
            session.add(
                SourceAdapterStat(
                    source_id=spec.source_id,
                    adapter=adapter,
                    circuit_state=CircuitState.CLOSED,
                )
            )
    await session.flush()


async def apply_data_mode_source_flags(session: AsyncSession, data_mode: DataMode) -> None:
    """Keep mock isolated. Live mode never enables the fixture source."""
    mock = await session.get(Source, MOCK_SOURCE_ID)
    if mock is not None:
        mock.enabled = data_mode == DataMode.MOCK


async def seed_if_needed(session: AsyncSession, settings: Settings | None = None) -> None:
    await seed_reference_data(session)
    await seed_mock_source(session)
    await seed_live_sources(session)
    mode = (settings or get_settings()).data_mode
    await apply_data_mode_source_flags(session, mode)
    await session.commit()
