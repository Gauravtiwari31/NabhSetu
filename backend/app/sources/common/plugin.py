from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import urljoin
from uuid import UUID

from app.domain.enums import CollectionStatus, CollectorModality, ReviewStatus, SourceType
from app.domain.models import CanonicalFareObservation, FareQuery, SourceProfile
from app.sources.common.cities import CITY_SLUGS, labels_for
from app.sources.common.fare_extract import ParseOutcome, extract_fares
from app.sources.common.html import extract_embedded_json


@dataclass(frozen=True)
class BrowserSearchPlan:
    start_url: str
    origin_query: str
    destination_query: str
    travel_date: date
    origin_code: str = ""
    destination_code: str = ""
    submit_labels: tuple[str, ...] = ("Search Flights", "Search", "Find flights", "Book")
    widget: str = "generic"
    dom_record_selector: str | None = None


@dataclass(frozen=True)
class SiteSpec:
    source_id: UUID
    name: str
    carrier: str | None
    base_url: str
    homepage_path: str = "/"
    blocked_paths: tuple[str, ...] = ()
    allowed_paths: tuple[str, ...] = ("*",)
    marketing_path_template: str | None = None
    sitemap_url: str | None = None
    public_api: bool = False
    static_html: bool = True
    embedded_json: bool = True
    structured_feed: bool = False
    requires_javascript: bool = False
    browser_network_json: bool = False
    documents_available: bool = False
    minimum_interval_seconds: int = 8
    daily_request_limit: int = 80
    automation_allowed: bool = True
    terms_review_status: ReviewStatus = ReviewStatus.APPROVED
    terms_url: str | None = None
    terms_notes: str = ""
    source_type: SourceType = SourceType.AIRLINE
    browser_widget: str = "generic"
    dom_record_selector: str | None = None
    parser_name: str = "airline_html"
    parser_version: str = "1.0.0"


@dataclass
class AirlineSitePlugin:
    spec: SiteSpec

    def absolute(self, path: str) -> str:
        return urljoin(self.spec.base_url.rstrip("/") + "/", path.lstrip("/"))

    def landing_urls(self, query: FareQuery) -> list[str]:
        urls = [self.absolute(self.spec.homepage_path)]
        template = self.spec.marketing_path_template
        if template:
            origin_slug = CITY_SLUGS.get(query.origin)
            dest_slug = CITY_SLUGS.get(query.destination)
            if origin_slug and dest_slug:
                urls.append(
                    self.absolute(
                        template.format(origin=origin_slug, destination=dest_slug)
                    )
                )
        return list(dict.fromkeys(urls))

    def feed_urls(self) -> list[str]:
        if self.spec.sitemap_url:
            return [self.spec.sitemap_url]
        return []

    def public_api_urls(self, query: FareQuery) -> list[str]:
        return []

    def browser_plan(self, query: FareQuery) -> BrowserSearchPlan | None:
        if not self.spec.requires_javascript and not self.spec.browser_network_json:
            return None
        origin_labels = labels_for(query.origin)
        dest_labels = labels_for(query.destination)
        return BrowserSearchPlan(
            start_url=self.absolute(self.spec.homepage_path),
            origin_query=origin_labels[0],
            destination_query=dest_labels[0],
            origin_code=query.origin,
            destination_code=query.destination,
            travel_date=query.travel_date,
            widget=self.spec.browser_widget,
            dom_record_selector=self.spec.dom_record_selector,
        )

    def parse_payload(
        self,
        payload: Any,
        query: FareQuery,
        source: SourceProfile,
        collector: CollectorModality,
        confidence,
        url: str = "",
    ) -> ParseOutcome:
        return extract_fares(
            payload,
            query,
            source,
            collector,
            carrier_hint=self.spec.carrier,
            parser_version=self.spec.parser_version,
            confidence=confidence,
        )

    def parse_html(
        self,
        html: str,
        query: FareQuery,
        source: SourceProfile,
        collector: CollectorModality,
        confidence,
    ) -> ParseOutcome:
        blobs = extract_embedded_json(html)
        observations: list[CanonicalFareObservation] = []
        for blob in blobs:
            outcome = self.parse_payload(blob, query, source, collector, confidence)
            observations.extend(outcome.observations)
        if observations:
            return ParseOutcome(status=CollectionStatus.SUCCESS, observations=observations)
        if blobs:
            return ParseOutcome(
                status=CollectionStatus.NO_RESULTS,
                message="Embedded JSON present but contained no matching dated fares",
            )
        return ParseOutcome(
            status=CollectionStatus.NO_RESULTS,
            message="No embedded machine-readable fares in HTML",
        )
