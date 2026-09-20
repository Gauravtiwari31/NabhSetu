from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.acquisition.adapters import (
    DocumentCollector,
    EmbeddedJsonCollector,
    PlaywrightDomCollector,
    PlaywrightNetworkCollector,
    PublicApiCollector,
    StaticHtmlCollector,
    StructuredFeedCollector,
    VisualCollector,
)
from app.acquisition.adapters.browser import BrowserRuntime
from app.acquisition.circuit_breaker import CircuitBreaker
from app.acquisition.compliance import ComplianceGovernor
from app.acquisition.http import GovernedHttpClient
from app.acquisition.registry import SourceCapabilityRegistry
from app.acquisition.router import AcquisitionRouter
from app.acquisition.scheduler import QueryScheduler
from app.config import Settings
from app.database.repositories import (
    EgressRepository,
    EventRepository,
    JobRepository,
    ObservationRepository,
    PublicationRepository,
    RateLimitRepository,
    SourceRepository,
)
from app.network_egress.manager import NetworkEgressManager
from app.pipeline.run_index import IndexPublisher
from app.services.collection import CollectionService
from app.sources.mock_fare import MockCollector


@dataclass
class AppContainer:
    settings: Settings
    session: AsyncSession
    sources: SourceRepository
    jobs: JobRepository
    rates: RateLimitRepository
    observations: ObservationRepository
    egress_repo: EgressRepository
    events: EventRepository
    governor: ComplianceGovernor
    registry: SourceCapabilityRegistry
    egress: NetworkEgressManager
    router: AcquisitionRouter
    scheduler: QueryScheduler
    collection: CollectionService
    publications: PublicationRepository
    publisher: IndexPublisher
    http: GovernedHttpClient
    browser: BrowserRuntime


def build_container(
    session: AsyncSession,
    settings: Settings,
    *,
    http: GovernedHttpClient | None = None,
    browser: BrowserRuntime | None = None,
) -> AppContainer:
    sources = SourceRepository(session)
    jobs = JobRepository(session)
    rates = RateLimitRepository(session)
    observations = ObservationRepository(session)
    publications = PublicationRepository(session)
    egress_repo = EgressRepository(session)
    events = EventRepository(session)
    circuit = CircuitBreaker(settings, sources)
    http_client = http or GovernedHttpClient(settings)
    browser_runtime = browser or BrowserRuntime(settings)
    collectors = [
        PublicApiCollector(settings, http_client),
        StructuredFeedCollector(settings, http_client),
        StaticHtmlCollector(settings, http_client),
        EmbeddedJsonCollector(settings, http_client),
        PlaywrightNetworkCollector(settings, browser_runtime),
        PlaywrightDomCollector(settings, browser_runtime),
        DocumentCollector(settings),
        VisualCollector(settings),
        MockCollector(settings),
    ]
    registry = SourceCapabilityRegistry(settings, sources, collectors, circuit)
    governor = ComplianceGovernor(settings, sources, rates, events)
    egress = NetworkEgressManager(settings, egress_repo, events)
    router = AcquisitionRouter(settings, registry, governor, egress, jobs, events)
    collection = CollectionService(settings, jobs, observations, router)
    publisher = IndexPublisher(settings, observations, publications)
    return AppContainer(
        settings=settings,
        session=session,
        sources=sources,
        jobs=jobs,
        rates=rates,
        observations=observations,
        egress_repo=egress_repo,
        events=events,
        governor=governor,
        registry=registry,
        egress=egress,
        router=router,
        scheduler=QueryScheduler(),
        collection=collection,
        publications=publications,
        publisher=publisher,
        http=http_client,
        browser=browser_runtime,
    )
